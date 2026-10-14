"""Extraction, decoding and unavailable-template source contracts; no model calls."""
import pytest
import json

from stark_t2sql.contracts import FailureClass
from stark_t2sql.errors import GenerationTimeoutError, GenerationTruncatedError, MissingDependencyError, SQLExtractionError
from stark_t2sql.inference.client import DecodingDefaults, GenerationResult
from stark_t2sql.inference.extract import extract_sql
from stark_t2sql.inference.template import load_template
from stark_t2sql.inference.template import ReviewedTemplateContract
from .conftest import required_input


@pytest.mark.parametrize("raw,expected", (
    ("SELECT 1", "SELECT 1;"), (" SELECT 1; ", "SELECT 1;"),
    ("SELECT 1;;; trailing", "SELECT 1;"), ("SELECT 1``` trailing", "SELECT 1;"),
    ("SELECT 1;``` trailing", "SELECT 1;"), ("SELECT 1```; trailing", "SELECT 1;"),
    ("\nSELECT\n 1\n", "SELECT\n 1;"), ("SELECT 'a;b';", "SELECT 'a;"),
    ("SELECT '```';", "SELECT ';"), ("Explanation SELECT 1; text", "Explanation SELECT 1;"),
))
def test_exact_first_delimiter_extraction(raw, expected):
    assert extract_sql(raw) == expected


@pytest.mark.parametrize("raw", ("", " \n ", "; SELECT 1", "```sql\nSELECT 1;"))
def test_empty_extraction_is_distinct_failure(raw):
    with pytest.raises(SQLExtractionError) as captured:
        extract_sql(raw)
    assert captured.value.failure_class is FailureClass.EXTRACT


def test_token_cap_incomplete_candidate_never_reaches_sql():
    generation = GenerationResult("SELECT employee_id FROM", 10.0, True, False, "limit", 300)
    with pytest.raises(GenerationTruncatedError) as captured:
        extract_sql(generation)
    assert captured.value.failure_class is FailureClass.TRUNCATED_GEN
    assert not isinstance(captured.value, GenerationTimeoutError)


def test_token_cap_with_completed_first_semicolon_keeps_complete_candidate():
    generation = GenerationResult("SELECT 1;", 10.0, True, True, "stop", 300)
    assert extract_sql(generation) == "SELECT 1;"


def test_frozen_decoding_and_explicit_missing_template(project_root):
    decoding = DecodingDefaults()
    assert decoding.temperature == 0 and decoding.seed == 42 and decoding.max_tokens == 300
    assert decoding.stop == (";",) and decoding.timeout_seconds == 120
    with pytest.raises(MissingDependencyError):
        load_template(project_root / "src" / "inference" / "prompt_template.txt", contract=None)


def test_actual_template_as_of_placement_keeps_original_bytes(project_root,governed_catalog,matrix,schema_metadata,payroll_persona,fixture_date):
    from stark_t2sql.context.builder import build_context
    from stark_t2sql.contracts import InputRequest
    from stark_t2sql.inference.prompt_builder import build_prompt
    raw=json.loads(required_input("STARK_TEST_TEMPLATE_CONTRACT_PATH",project_root).read_text(encoding="utf-8"))
    contract=ReviewedTemplateContract(**raw)
    template=load_template(project_root/"src"/"inference"/"prompt_template.txt",contract=contract)
    original=template.source_bytes
    context=build_context(InputRequest(payroll_persona,"Unit explicit request",fixture_date),schema_metadata,governed_catalog,matrix)
    prompt=build_prompt(template,context)
    question_region=prompt.text.split(contract.question_open_tag,1)[1].split(contract.question_close_tag,1)[0]
    assert "Unit explicit request"+template.newline+contract.as_of_line_prefix+fixture_date.isoformat() in question_region
    assert template.source_bytes == original and prompt.template_sha256 == template.sha256
