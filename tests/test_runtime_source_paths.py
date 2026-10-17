"""Local private source boundaries; no model, database or service execution."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from stark_t2sql.config import load_config
from stark_t2sql.errors import ConfigurationError, SourceReadError
from stark_t2sql.pipeline.orchestrator import load_runtime_source_inputs
from stark_t2sql.utils.local_sources import resolve_runtime_path


@pytest.fixture
def private_bindings(project_root):
    # TEST_ONLY type-validation operands; never deployment approval/evidence.
    template = json.loads((project_root / "tests/fixtures/template_contract.json").read_text())
    parser = json.loads((project_root / "tests/fixtures/parser_approval_sqlglot_30_22_0.json").read_text())
    return {
        "admin_login_role": "unit_startup", "admin_password_environment_variable": "UNIT_PASSWORD",
        "sales_division_name": "Sales", "fixture_hash_path": ["fixture_dump_sha256"],
        "installed_policy_state_sha256": "1" * 64, "template_contract": template,
        "model_service": {"model_sha256": "2" * 64, "llama_cpp_build": "TEST_ONLY",
            "launcher_sha256": "3" * 64, "beam_support_reviewed": True, "beam_supported": False,
            "weights_postdate_2024_02_07": True, "memory_limit_enforced": True,
            "slots": 1, "prefix_cache_enabled": True},
        "parser_approval": {key: parser[key] for key in ("sqlglot_version", "validator_revision",
            "function_policy_revision", "approved_node_shapes", "approved_function_rule_ids", "review_reference")},
    }


def test_explicit_absolute_private_runtime_files_can_stay_outside_git(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    private = tmp_path / "private"
    private.mkdir()
    model = private / "model.gguf"
    measurements = private / "measurements.txt"
    config = load_config(root=root, environment={"STARK_GGUF_PATH": str(model),
        "STARK_RESOURCE_MEASUREMENTS_PATH": str(measurements)})
    assert config.paths.model_file == model.resolve()
    assert config.resource_budgets.measurement_source == measurements.resolve()
    assert not model.exists() and not measurements.exists()


def test_external_bindings_load_without_opening_connections(tmp_path, private_bindings, monkeypatch):
    import psycopg2
    def forbidden(*args, **kwargs): raise AssertionError("Reading bindings cannot connect")
    monkeypatch.setattr(psycopg2, "connect", forbidden)
    root = tmp_path / "project"
    root.mkdir()
    path = tmp_path / "private-bindings.json"
    path.write_text(json.dumps(private_bindings), encoding="utf-8")
    loaded = load_runtime_source_inputs(path, root=root)
    assert loaded.admin_password_environment_variable == "UNIT_PASSWORD"
    assert loaded.model_service.model_sha256 == "2" * 64


@pytest.mark.parametrize("path", ("../private.json", "..\\private.json", "https://example.com/input",
    "\\\\server\\share\\input.json", "//server/share/input.json", "\\\\?\\C:\\input.json", "C:relative.json"))
def test_relative_escape_network_and_device_sources_are_rejected(tmp_path, path):
    with pytest.raises(ConfigurationError):
        resolve_runtime_path(path, root=tmp_path, label="test source")


def test_normal_relative_source_is_confined_to_workspace(tmp_path):
    assert resolve_runtime_path("local/input.json", root=tmp_path, label="unit") == tmp_path / "local/input.json"


@pytest.mark.parametrize("setting", ("STARK_GGUF_PATH", "STARK_RESOURCE_MEASUREMENTS_PATH"))
def test_config_rejects_relative_escape_instead_of_converting_to_absolute(tmp_path, setting):
    with pytest.raises(ConfigurationError):
        load_config(root=tmp_path, environment={setting: "../outside.bin"})


@pytest.mark.parametrize("wire", ('{"admin_login_role":"first","admin_login_role":"second"}',
    '{"value":NaN}', '{"value":Infinity}'))
def test_ambiguous_private_json_is_rejected_without_echoing_input(tmp_path, wire):
    path = tmp_path / "bindings.json"
    path.write_text(wire, encoding="utf-8")
    with pytest.raises((ConfigurationError, SourceReadError)) as error:
        load_runtime_source_inputs(path, root=tmp_path)
    assert wire not in str(error.value)


def test_private_record_byte_bound_remains_enforced(tmp_path):
    path = tmp_path / "oversize.json"
    path.write_bytes(b" " * 1_048_577)
    with pytest.raises(ConfigurationError):
        load_runtime_source_inputs(path, root=tmp_path)
