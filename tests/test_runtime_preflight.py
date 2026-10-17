"""Offline operator diagnostics are declarations, never live acceptance."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import socket
import subprocess

import pytest

from ops import runtime_preflight as preflight


@pytest.fixture
def runtime_inputs(tmp_path, project_root):
    """Synthetic private declarations; no service or approval is established."""
    root = tmp_path / "workspace"
    root.mkdir()
    for name in (
        "STARK_T2SQL FRD 1.8.txt", "schema.sql", "policy/access_matrix.yaml",
        "semantic/catalog.yaml", "src/inference/prompt_template.txt",
        "fixture_pg_dump.sql", "fixture_manifest.json",
        "STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html",
    ):
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((project_root / name).read_bytes())
    model = root / "unit.gguf"
    model.write_bytes(b"unit bytes; not actual GGUF weights")
    measurements = root / "unit_measurements.json"
    measurements.write_text('{"unit_operand_only":true}', encoding="utf-8")
    parser = json.loads((project_root / "tests/fixtures/parser_approval_sqlglot_30_22_0.json").read_text(encoding="utf-8"))
    parser["review_reference"] = "DECLARATION-ONLY-PROFILE"
    raw = {
        "admin_login_role": "unit_metadata_login",
        "admin_password_environment_variable": "UNIT_METADATA_PASSWORD",
        "sales_division_name": "Sales",
        "fixture_hash_path": ["fixture_dump_sha256"],
        "installed_policy_state_sha256": "a" * 64,
        "template_contract": json.loads((project_root / "tests/fixtures/template_contract.json").read_text(encoding="utf-8")),
        "model_service": {
            "model_sha256": sha256(model.read_bytes()).hexdigest(),
            "llama_cpp_build": "DECLARATION-ONLY-BUILD",
            "launcher_sha256": "b" * 64,
            "beam_support_reviewed": True, "beam_supported": False,
            "weights_postdate_2024_02_07": True, "memory_limit_enforced": True,
            "slots": 1, "prefix_cache_enabled": True,
        },
        "parser_approval": parser,
    }
    bindings = root / "unit_bindings.json"
    bindings.write_text(json.dumps(raw), encoding="utf-8")
    # The actual manifest field is explicit; a fixture record is not a DB audit.
    manifest = json.loads((root / "fixture_manifest.json").read_text(encoding="utf-8"))
    def locate(value, path=()):
        if isinstance(value, dict):
            for key, item in value.items():
                if item == sha256((root / "fixture_pg_dump.sql").read_bytes()).hexdigest():
                    return (*path, key)
                result = locate(item, (*path, key))
                if result:
                    return result
        return None
    raw["fixture_hash_path"] = list(locate(manifest))
    bindings.write_text(json.dumps(raw), encoding="utf-8")
    environment = {
        "STARK_RUNTIME_BINDINGS_PATH": str(bindings),
        "STARK_GGUF_PATH": str(model),
        "STARK_RESOURCE_MEASUREMENTS_PATH": str(measurements),
        "STARK_DATABASE_WORK_MEM_KIB": "64",
        "STARK_DATABASE_TEMP_FILE_LIMIT_KIB": "1024",
        "STARK_MODEL_MEMORY_LIMIT_MIB": "128",
        "STARK_PG_DATABASE": "unit_fixture",
        "STARK_PAYROLL_PASSWORD": "DO_NOT_PRINT_PAYROLL",
        "STARK_HR_PASSWORD": "DO_NOT_PRINT_HR",
        "STARK_SALES_PASSWORD": "DO_NOT_PRINT_SALES",
        "UNIT_METADATA_PASSWORD": "DO_NOT_PRINT_METADATA",
    }
    return root, environment, raw, bindings


def by_code(report):
    return {check.code: check for check in report.checks}


def test_empty_environment_reports_exact_missing_inputs_without_live_claim(project_root):
    report = preflight.inspect_runtime(root=project_root, environment={})
    checks = by_code(report)
    assert checks["RUNTIME_BINDINGS_MISSING"].status == "MISSING"
    assert checks["MODEL_FILE_MISSING"].status == "MISSING"
    assert checks["MEASUREMENTS_MISSING"].status == "MISSING"
    assert checks["ENV_STARK_HR_PASSWORD"].status == "MISSING"
    assert report.offline_prerequisites == "BLOCKED"
    assert report.live_acceptance == "NOT_RUN"
    assert report.production_promotion == "NOT_APPROVED"


def test_complete_synthetic_declarations_only_establish_offline_prerequisites(runtime_inputs):
    root, environment, _, _ = runtime_inputs
    report = preflight.inspect_runtime(root=root, environment=environment, verify_model_hash=True)
    assert report.offline_prerequisites == "VALID"
    assert all(check.status == "OK" for check in report.checks)
    assert report.live_acceptance == "NOT_RUN"
    assert report.production_promotion == "NOT_APPROVED"


@pytest.mark.parametrize("setting,value", (
    ("STARK_PG_HOST", "192.0.2.10"),
    ("STARK_PG_PORT", "SECRET_INVALID_PORT"),
    ("STARK_GENERATION_TIMEOUT_SECONDS", "nan"),
    ("STARK_PG_DATABASE", "dbname=SECRET_DSN"),
))
def test_invalid_config_or_credentials_are_sanitized(runtime_inputs, setting, value):
    root, environment, _, _ = runtime_inputs
    environment[setting] = value
    report = preflight.inspect_runtime(root=root, environment=environment)
    assert report.offline_prerequisites == "BLOCKED"
    assert any(check.status == "INVALID" for check in report.checks)
    output = report.to_json()
    assert value not in output
    assert "DO_NOT_PRINT" not in output
    assert str(root) not in output


@pytest.mark.parametrize("section,key,value,code", (
    ("template_contract", "template_sha256", "PRIVATE_BAD_HASH", "TEMPLATE_BINDING_INVALID"),
    ("model_service", "memory_limit_enforced", False, "MODEL_BINDING_INVALID"),
    ("parser_approval", "approved_node_shapes", ["PRIVATE_BAD_SHAPE"], "PARSER_BINDING_INVALID"),
))
def test_nested_binding_errors_report_only_static_categories(runtime_inputs, section, key, value, code):
    root, environment, raw, bindings = runtime_inputs
    raw[section][key] = value
    bindings.write_text(json.dumps(raw), encoding="utf-8")
    report = preflight.inspect_runtime(root=root, environment=environment)
    assert by_code(report)[code].status == "INVALID"
    assert "PRIVATE_BAD" not in report.to_json()


@pytest.mark.parametrize("reference", ("TEST_ONLY fixture", "test-only evidence", "Test only parser"))
def test_test_only_parser_declarations_are_not_runtime_approval(runtime_inputs, reference):
    root, environment, raw, bindings = runtime_inputs
    raw["parser_approval"]["review_reference"] = reference
    bindings.write_text(json.dumps(raw), encoding="utf-8")
    report = preflight.inspect_runtime(root=root, environment=environment)
    assert by_code(report)["PARSER_TEST_ONLY"].status == "INVALID"
    assert report.offline_prerequisites == "BLOCKED"


def test_parser_version_drift_is_detected_without_executing_sql(runtime_inputs):
    root, environment, raw, bindings = runtime_inputs
    raw["parser_approval"]["sqlglot_version"] = "0.0.0"
    bindings.write_text(json.dumps(raw), encoding="utf-8")
    report = preflight.inspect_runtime(root=root, environment=environment)
    assert by_code(report)["PARSER_VERSION_MISMATCH"].status == "INVALID"


def test_template_and_fixture_drift_are_found_without_db(runtime_inputs):
    root, environment, _, _ = runtime_inputs
    (root / "src/inference/prompt_template.txt").write_bytes(b"changed")
    (root / "fixture_pg_dump.sql").write_bytes(b"changed")
    report = preflight.inspect_runtime(root=root, environment=environment)
    assert by_code(report)["TEMPLATE_INTEGRITY_INVALID"].status == "INVALID"
    assert by_code(report)["FIXTURE_INTEGRITY_INVALID"].status == "INVALID"


def test_model_hash_is_explicitly_opt_in_and_drift_is_sanitized(runtime_inputs):
    root, environment, _, _ = runtime_inputs
    (root / "unit.gguf").write_bytes(b"changed")
    report = preflight.inspect_runtime(root=root, environment=environment)
    assert "MODEL_INTEGRITY_INVALID" not in by_code(report)
    report = preflight.inspect_runtime(root=root, environment=environment, verify_model_hash=True)
    assert by_code(report)["MODEL_INTEGRITY_INVALID"].status == "INVALID"


def test_duplicate_keys_and_private_payloads_are_not_echoed(runtime_inputs):
    root, environment, _, bindings = runtime_inputs
    bindings.write_text('{"private":"SECRET_A","private":"SECRET_B"}', encoding="utf-8")
    report = preflight.inspect_runtime(root=root, environment=environment)
    assert by_code(report)["RUNTIME_BINDINGS_INVALID"].status == "INVALID"
    assert "SECRET_" not in report.to_json()


@pytest.mark.parametrize("payload", (
    b'{"private":NaN}', b'["PRIVATE_ARRAY"]', b'\xffPRIVATE_UTF8',
    b' ' * 1_048_577,
), ids=("nonfinite", "array", "invalid-utf8", "oversized"))
def test_malformed_or_oversized_private_records_fail_closed(runtime_inputs, payload):
    root, environment, _, bindings = runtime_inputs
    bindings.write_bytes(payload)
    report = preflight.inspect_runtime(root=root, environment=environment)
    assert by_code(report)["RUNTIME_BINDINGS_INVALID"].status == "INVALID"
    assert "PRIVATE_" not in report.to_json()


def test_explicit_external_local_artifacts_and_bindings_do_not_require_copies(runtime_inputs):
    root, environment, _, bindings = runtime_inputs
    private_root = root.parent / "private_runtime"
    private_root.mkdir()
    for setting in ("STARK_GGUF_PATH", "STARK_RESOURCE_MEASUREMENTS_PATH", "STARK_RUNTIME_BINDINGS_PATH"):
        old_path = Path(environment[setting])
        target = private_root / old_path.name
        target.write_bytes(old_path.read_bytes())
        environment[setting] = str(target)
    report = preflight.inspect_runtime(root=root, environment=environment, verify_model_hash=True)
    assert report.offline_prerequisites == "VALID"
    assert str(private_root) not in report.to_json()


@pytest.mark.parametrize("setting,value", (
    ("STARK_GGUF_PATH", "../private.gguf"),
    ("STARK_RESOURCE_MEASUREMENTS_PATH", r"\\server\private\measurement.json"),
    ("STARK_RUNTIME_BINDINGS_PATH", r"\\?\C:\private\bindings.json"),
    ("STARK_RUNTIME_BINDINGS_PATH", "https://example.invalid/private.json"),
))
def test_nonlocal_or_escaping_paths_are_rejected_without_echo(runtime_inputs, setting, value):
    root, environment, _, _ = runtime_inputs
    environment[setting] = value
    report = preflight.inspect_runtime(root=root, environment=environment)
    assert report.offline_prerequisites == "BLOCKED"
    assert any(check.status == "INVALID" for check in report.checks)
    assert value not in report.to_json()


def test_missing_dependency_is_reported_without_attempting_source_runtime_import(project_root, monkeypatch):
    real_version = preflight.version
    def package_version(name):
        if name == "PyYAML":
            raise preflight.PackageNotFoundError("PRIVATE_INSTALL_PATH")
        return real_version(name)
    monkeypatch.setattr(preflight, "version", package_version)
    report = preflight.inspect_runtime(root=project_root, environment={})
    assert by_code(report)["DEPENDENCY_PYYAML"].status == "MISSING"
    assert "PRIVATE_INSTALL_PATH" not in report.to_json()


def test_preflight_never_connects_launches_composes_or_writes(runtime_inputs, monkeypatch):
    root, environment, _, _ = runtime_inputs
    import psycopg2
    from stark_t2sql.pipeline import orchestrator
    from stark_t2sql.inference.client import LocalInferenceClient
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline preflight attempted a consequential operation")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(psycopg2, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(orchestrator, "compose_persona_runtime", forbidden)
    monkeypatch.setattr(LocalInferenceClient, "__init__", forbidden)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    original = deepcopy(environment)
    report = preflight.inspect_runtime(root=root, environment=environment, verify_model_hash=True)
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert report.offline_prerequisites == "VALID"
    assert environment == original
    assert before == after


def test_cli_outputs_actionable_json_and_nonzero_for_missing_inputs(project_root, monkeypatch, capsys):
    monkeypatch.setattr(preflight.os, "environ", {})
    assert preflight.main(["--root", str(project_root), "--json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["live_acceptance"] == "NOT_RUN"
    assert any("STARK_RUNTIME_BINDINGS_PATH" in check["action"] for check in report["checks"])
