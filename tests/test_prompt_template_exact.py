"""R01 regressions; unit operands are not an owner approval or E2 evidence.

The pinned official README was retrieved from Defog's Hugging Face repository.
Its Prompt fenced block contains 306 UTF-8 bytes, including the final LF.
The digests below were computed from that actual response, without rewriting
the block. Tests never fetch it. The acceptance test requires both the local
artifact and the real owner contract; missing evidence is a visible failure.
"""

from dataclasses import replace
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from stark_t2sql.context.builder import CompiledContext
from stark_t2sql.contracts import ExecutionMode, InputRequest, Persona
from stark_t2sql.errors import ConfigurationError, HarnessSafetyStopError, MissingDependencyError, SourceReadError
from stark_t2sql.inference.prompt_builder import _replace_original_slots, build_prompt
from stark_t2sql.inference.template import PromptTemplate, ReviewedTemplateContract, load_template
from stark_t2sql.utils.fingerprints import sha256_context


OFFICIAL_REVISION = "7e5b6f7981c0aa7d143f6bec6fa26625bdfcbe66"
OFFICIAL_SOURCE = f"https://huggingface.co/defog/sqlcoder-7b-2/raw/{OFFICIAL_REVISION}/README.md"
OFFICIAL_README_SHA256 = "cb2bcf750243bd1bf77c1e70b3b989bb69da3a5cf37702278c80467b94ecb524"
OFFICIAL_TEMPLATE_SHA256 = "67d1c6d265202e6bf6abcd1393203e84b92bf9df03207015679339fe807ad6b6"

# Deliberately different from the model card. These source bytes and this
# clearly labelled prefix exercise logic only; they cannot satisfy acceptance.
UNIT_SOURCE = (
    b"Unit template only; no provenance/owner approval.\n"
    b"[QUESTION]{user_question}[/QUESTION]\n"
    b"{table_metadata_string_DDL_statements}\n"
    b"[QUESTION]{user_question}[/QUESTION]\n"
    b"[SQL]\n"
)
UNIT_PREFIX = "UNIT ONLY as-of: "
QUESTION_PAIR = b"[QUESTION]{user_question}[/QUESTION]"


def unit_contract(source=UNIT_SOURCE):
    return ReviewedTemplateContract(
        hashlib.sha256(source).hexdigest(), "{user_question}",
        "{table_metadata_string_DDL_statements}", "[QUESTION]", "[/QUESTION]",
        UNIT_PREFIX, "unit operand only; not model-card or owner-review evidence",
    )


def unit_template(source=UNIT_SOURCE):
    contract = unit_contract(source)
    return PromptTemplate(source, contract.template_sha256, contract)


def prompt_context(question="Unit question", *, version=2, mode=None):
    """In-memory compiled inputs only, with actual hashes of these unit bytes."""
    if mode is None:
        mode = ExecutionMode.UNCONTROLLED if version == 1 else ExecutionMode.FULL
    persona = Persona("Unit payroll", "app_payroll", 326, "stark_payroll_login")
    request = InputRequest(persona, question, date(2026, 10, 12), mode)
    ddl = "-- UNIT_FULL_DDL\nCREATE TABLE unit_full (id integer);\r\n" if version == 1 else "-- UNIT_VISIBLE_DDL\nCREATE TABLE unit_visible (id integer);"
    semantics = "" if version == 1 else "UNIT_SEMANTIC_BLOCK"
    profile = "E2_FROZEN_BASELINE" if version == 1 else "E5_ROLE_FILTERED"
    if mode is ExecutionMode.NO_PROMPT_FILTER:
        profile = "E5_NO_PROMPT_FILTER"
    return CompiledContext(
        request, version, ddl, semantics, sha256_context(ddl), sha256_context(semantics),
        sha256_context("unit policy source"),
        None if version == 1 else sha256_context("unit catalog source"), profile,
    )


def require_authoritative_template(project_root):
    """No fallback prefix, generated approval, network fetch or acceptance skip."""
    supplied = os.environ.get("STARK_TEST_TEMPLATE_CONTRACT_PATH")
    contract_path = Path(supplied) if supplied else project_root / "tests" / "fixtures" / "template_contract.json"
    if not contract_path.is_absolute():
        contract_path = project_root / contract_path
    contract_path = contract_path.resolve()
    if not contract_path.is_relative_to(project_root.resolve()):
        pytest.fail("R01 owner template contract must be inside the project workspace.", pytrace=False)
    template_path = project_root / "src" / "inference" / "prompt_template.txt"
    missing = []
    if not contract_path.is_file():
        missing.append("owner-approved template contract and exact canonical as-of prefix")
    if not template_path.is_file():
        missing.append("approved local src/inference/prompt_template.txt artifact")
    if missing:
        pytest.fail("BLOCKED R01 acceptance: missing " + "; ".join(missing) + ". Unit regressions are not acceptance evidence.", pytrace=False)
    contract = ReviewedTemplateContract(**json.loads(contract_path.read_text(encoding="utf-8")))
    if OFFICIAL_REVISION not in contract.source_reference or "defog/sqlcoder-7b-2" not in contract.source_reference:
        pytest.fail("BLOCKED R01 acceptance: owner provenance must identify the pinned Defog source revision.", pytrace=False)
    assert contract.template_sha256 == OFFICIAL_TEMPLATE_SHA256
    return load_template(template_path, contract=contract)


@pytest.mark.r01_acceptance
def test_load_authoritative_sqlcoder_template(project_root):
    template = require_authoritative_template(project_root)
    assert len(template.source_bytes) == 306
    assert template.source_bytes.decode("utf-8").encode("utf-8") == template.source_bytes
    assert not template.source_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in template.source_bytes and template.source_bytes.endswith(b"\n")
    assert hashlib.sha256(template.source_bytes).hexdigest() == OFFICIAL_TEMPLATE_SHA256
    assert template.sha256 == template.contract.template_sha256
    for marker, count in (("[QUESTION]", 2), ("[/QUESTION]", 2), ("{user_question}", 2), ("{table_metadata_string_DDL_statements}", 1)):
        assert template.text.count(marker) == count


def test_build_prompt_replaces_all_question_occurrences():
    template, context = unit_template(), prompt_context()
    result = build_prompt(template, context)
    regions = [part.split("[/QUESTION]", 1)[0] for part in result.text.split("[QUESTION]")[1:]]
    assert regions == [context.request.question + "\n" + UNIT_PREFIX + "2026-10-12"] * 2
    assert "{user_question}" not in result.text
    assert "{table_metadata_string_DDL_statements}" not in result.text
    assert result.text.count(context.ddl) == 1
    assert result.rendered_sha256 == hashlib.sha256(result.text.encode("utf-8")).hexdigest()


def test_prompt_versions_keep_schema_and_semantic_context_isolated():
    template = unit_template()
    baseline, governed = prompt_context(version=1), prompt_context(version=2)
    v1, v2 = build_prompt(template, baseline), build_prompt(template, governed)
    assert baseline.ddl in v1.text and "UNIT_SEMANTIC_BLOCK" not in v1.text
    assert governed.ddl + "\n\n" + governed.semantic_text in v2.text
    assert "UNIT_FULL_DDL" not in v2.text and "UNIT_VISIBLE_DDL" not in v1.text
    for rendered in (v1.text, v2.text):
        for part in rendered.split("[QUESTION]")[1:]:
            region = part.split("[/QUESTION]", 1)[0]
            assert "CREATE TABLE" not in region and "UNIT_SEMANTIC_BLOCK" not in region


def test_immutable_bytes_preservation():
    template = unit_template()
    original = template.source_bytes
    digest = hashlib.sha256(original).hexdigest()
    for version in (1, 2, 1, 2):
        result = build_prompt(template, prompt_context(version=version))
        assert template.source_bytes is original
        assert result.template_sha256 == digest == template.sha256
    assert hashlib.sha256(template.source_bytes).hexdigest() == digest


@pytest.mark.parametrize("question", (
    '{"foo": "bar"}', "Literal {custom_token} and unmatched { braces } }",
    "Keep {user_question} and {table_metadata_string_DDL_statements} literally",
    "Keep [QUESTION] and [/QUESTION] and [SQL] as input text",
    "Unicode question: caf\u00e9 \u0394\nsecond input line",
))
def test_inserted_question_text_is_never_reinterpreted(question):
    context, template = prompt_context(question), unit_template()
    rendered = build_prompt(template, context).text
    original_question = question + "\n" + UNIT_PREFIX + "2026-10-12"
    expected = (
        "Unit template only; no provenance/owner approval.\n"
        + "[QUESTION]" + original_question + "[/QUESTION]\n"
        + context.ddl + "\n\n" + context.semantic_text + "\n"
        + "[QUESTION]" + original_question + "[/QUESTION]\n[SQL]\n"
    )
    assert rendered == expected


@pytest.mark.parametrize("source", (
    UNIT_SOURCE.replace(QUESTION_PAIR, b"", 1),
    UNIT_SOURCE.replace(b"[SQL]", QUESTION_PAIR + b"\n[SQL]"),
    UNIT_SOURCE.replace(b"[QUESTION]", b"", 1),
    UNIT_SOURCE.replace(b"[/QUESTION]", b"", 1),
    UNIT_SOURCE.replace(b"{user_question}", b"", 1),
    UNIT_SOURCE.replace(b"{table_metadata_string_DDL_statements}", b""),
    UNIT_SOURCE.replace(b"{table_metadata_string_DDL_statements}", b"{table_metadata_string_DDL_statements}" * 2),
    UNIT_SOURCE.replace(QUESTION_PAIR, b"[/QUESTION]{user_question}[QUESTION]", 1),
    UNIT_SOURCE.replace(QUESTION_PAIR, b"[QUESTION]{user_question}[QUESTION]", 1).replace(QUESTION_PAIR, b"[/QUESTION]{user_question}[/QUESTION]", 1),
    UNIT_SOURCE.replace(b"{user_question}", b"{user_question}" * 2, 1).replace(QUESTION_PAIR, b"[QUESTION][/QUESTION]", 1),
    UNIT_SOURCE.replace(b"{user_question}", b"extra{user_question}", 1),
    UNIT_SOURCE.replace(b"{user_question}", b"{user_question}extra", 1),
    UNIT_SOURCE.replace(b"[SQL]", b""),
    UNIT_SOURCE.replace(b"[SQL]", b"[SQL][SQL]"),
    UNIT_SOURCE.replace(b"{table_metadata_string_DDL_statements}", b"[SQL]{table_metadata_string_DDL_statements}").replace(b"\n[SQL]\n", b"\n"),
    UNIT_SOURCE + b"{unreviewed_slot}", UNIT_SOURCE + b"[UNREVIEWED]",
    UNIT_SOURCE + b"[QUESTION", UNIT_SOURCE + b"{unfinished",
    b"\xef\xbb\xbf" + UNIT_SOURCE,
    UNIT_SOURCE.replace(b"\n", b"\r\n"),
))
def test_malformed_marker_layout_fails_closed_even_with_matching_digest(source):
    with pytest.raises(ConfigurationError):
        unit_template(source)


@pytest.mark.parametrize("region_index", (0, 1))
def test_schema_inside_either_question_region_fails_closed(region_index):
    schema = b"{table_metadata_string_DDL_statements}"
    source = UNIT_SOURCE.replace(schema, b"")
    pieces = source.split(QUESTION_PAIR)
    pieces[region_index] += b"[QUESTION]{user_question}" + schema + b"[/QUESTION]"
    source = pieces[0] + (QUESTION_PAIR if region_index != 0 else b"") + pieces[1] + (QUESTION_PAIR if region_index != 1 else b"") + pieces[2]
    with pytest.raises(ConfigurationError):
        unit_template(source)


def test_whitespace_around_each_original_question_slot_is_preserved():
    source = UNIT_SOURCE.replace(QUESTION_PAIR, b"[QUESTION] \t{user_question}\n[/QUESTION]")
    template = unit_template(source)
    rendered = build_prompt(template, prompt_context()).text
    assert rendered.count("[QUESTION] \tUnit question\n" + UNIT_PREFIX + "2026-10-12\n[/QUESTION]") == 2
    assert template.source_bytes == source


def test_template_sha_mismatch_fails_closed(tmp_path):
    path = tmp_path / "template.txt"
    path.write_bytes(UNIT_SOURCE.replace(b"Unit template", b"unit template", 1))
    with pytest.raises(ConfigurationError, match="frozen model-card source binding"):
        load_template(path, contract=unit_contract())
    with pytest.raises(ConfigurationError, match="frozen model-card source binding"):
        PromptTemplate(UNIT_SOURCE, hashlib.sha256(b"different real unit bytes").hexdigest(), unit_contract())


def test_binary_loader_does_not_normalize_bytes(tmp_path):
    path = tmp_path / "template.txt"
    path.write_bytes(UNIT_SOURCE)
    template = load_template(path, contract=unit_contract())
    assert template.source_bytes == path.read_bytes() == UNIT_SOURCE
    path.write_bytes(UNIT_SOURCE.replace(b"\n", b"\r\n"))
    with pytest.raises(ConfigurationError, match="frozen model-card source binding"):
        load_template(path, contract=unit_contract())


def test_missing_and_oversized_source_fail_closed(tmp_path):
    with pytest.raises(MissingDependencyError):
        load_template(tmp_path / "absent.txt", contract=unit_contract())
    path = tmp_path / "template.txt"
    path.write_bytes(UNIT_SOURCE)
    with pytest.raises(ConfigurationError, match="source-size bound"):
        load_template(path, contract=unit_contract(), max_bytes=len(UNIT_SOURCE) - 1)


def test_invalid_utf8_fails_closed_without_replacing_bytes():
    source = UNIT_SOURCE + b"\xff"
    with pytest.raises(SourceReadError, match="strict UTF-8"):
        unit_template(source)


@pytest.mark.parametrize("field,value", (
    ("question_placeholder", "{unreviewed_question}"),
    ("question_open_tag", "[OTHER]"),
    ("question_close_tag", "[/OTHER]"),
    ("schema_placeholder", "{other_schema}"),
))
def test_unreviewed_contract_markers_are_rejected(field, value):
    with pytest.raises(ConfigurationError, match="unreviewed"):
        replace(unit_contract(), **{field: value})


def test_canonical_as_of_prefix_has_no_fallback():
    with pytest.raises(MissingDependencyError, match="exact recorded"):
        replace(unit_contract(), as_of_line_prefix="")
    with pytest.raises(MissingDependencyError, match="exact recorded"):
        replace(unit_contract(), as_of_line_prefix="two\nlines")


@pytest.mark.parametrize("source,replacements", (
    ("aaaa", (("aa", "value"),)),
    ("abcdef", (("abc", "value"), ("bcd", "other"))),
    ("token", (("token", "value"), ("token", "other"))),
    ("source", (("", "value"),)),
    ("source", (("absent", "value"),)),
))
def test_replacement_missing_or_overlapping_original_slots_are_rejected(source, replacements):
    with pytest.raises(ConfigurationError):
        _replace_original_slots(source, replacements)


def test_replacement_scans_only_original_text_for_every_slot():
    source = "{q} {s} {q}"
    assert _replace_original_slots(source, (("{q}", "{s}"), ("{s}", "{q}"))) == "{s} {q} {s}"


@pytest.mark.parametrize("version,mode", ((1, ExecutionMode.FULL), (2, ExecutionMode.UNCONTROLLED)))
def test_aberrant_prompt_modes_fail_closed(version, mode):
    with pytest.raises(HarnessSafetyStopError):
        build_prompt(unit_template(), prompt_context(version=version, mode=mode))


@pytest.mark.parametrize("mode", (ExecutionMode.NO_VALIDATOR, ExecutionMode.NO_PROMPT_FILTER))
def test_existing_governed_harness_profiles_keep_v2_context(mode):
    result = build_prompt(unit_template(), prompt_context(mode=mode))
    assert result.prompt_version == 2 and "UNIT_SEMANTIC_BLOCK" in result.text


def test_inference_import_has_no_model_database_or_network_activity(project_root):
    script = r'''
import builtins
import http.client
import importlib
import pathlib
import socket
import ssl
import subprocess
import sys
import threading
import types

def forbidden(*args, **kwargs):
    raise AssertionError("Inference import attempted runtime activity")

socket.socket = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
threading.Thread.start = forbidden
driver = types.ModuleType("psycopg2")
driver.connect = forbidden
sys.modules["psycopg2"] = driver
original_open = builtins.open
original_path_open = pathlib.Path.open

def guard_path(value):
    path = str(value).replace("\\", "/").lower()
    if path.endswith(".gguf") or path.endswith("/src/inference/prompt_template.txt"):
        forbidden()

def guarded_open(file, *args, **kwargs):
    guard_path(file)
    return original_open(file, *args, **kwargs)

def guarded_path_open(self, *args, **kwargs):
    guard_path(self)
    return original_path_open(self, *args, **kwargs)

builtins.open = guarded_open
pathlib.Path.open = guarded_path_open
for name in ("stark_t2sql.inference", "stark_t2sql.inference.template", "stark_t2sql.inference.prompt_builder", "stark_t2sql.inference.client"):
    importlib.import_module(name)
'''
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=project_root,
        env={**os.environ, "PYTHONPATH": str(project_root / "src")},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
