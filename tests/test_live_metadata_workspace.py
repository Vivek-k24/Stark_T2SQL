"""Offline session/security/UI contracts; live checks are separate opt-ins."""
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stark_t2sql.config import load_config
from stark_t2sql.contracts import OutcomeStatus, Persona
from stark_t2sql.errors import ConfigurationError
from stark_t2sql.pipeline.metadata import MetadataApplication, inspect_metadata, load_installation_digest
from stark_t2sql.pipeline.response import SafeConcept, SafePolicyRow
from stark_t2sql.ui import workspace


@pytest.fixture
def safe_metadata(payroll_persona):
    personas = (payroll_persona,
        Persona("HR business partner #1", "app_hr_bp", 47, "stark_hr_login"),
        Persona("HR business partner #2", "app_hr_bp", 361, "stark_hr_login"),
        Persona("Sales manager", "app_sales_mgr", 99, "stark_sales_login"))
    def resolve(persona):
        if persona not in personas: raise ValueError("Unresolved persona")
        return persona
    registry = SimpleNamespace(personas=dict(zip(("payroll", "hr_1", "hr_2", "sales"), personas)), resolve=resolve)
    concepts = {p.business_role: (SafeConcept("visible_employee_count", "Visible employees", "Governed visible rows",
        "metric", (), "employees", (), (), "count"),) for p in personas}
    policies = {p.business_role: (SafePolicyRow("employees", ("employee_id",), "all", "Allowed rows only"),) for p in personas}
    return MetadataApplication(registry, concepts, policies, {p: index + 1 for index, p in enumerate(personas)})


def test_metadata_capability_cannot_accept_forged_persona(safe_metadata):
    p = safe_metadata.personas[0]
    with pytest.raises(ValueError): safe_metadata.policy_view(replace(p, principal_id=9999))
    assert not hasattr(safe_metadata, "answer") and not hasattr(safe_metadata, "connection")
    assert safe_metadata.employee_count(p) == 1


def test_capability_handle_is_bound_to_server_session_and_expires(safe_metadata):
    clock = [0]
    store = workspace.WorkspaceStore(ttl_seconds=10, clock=lambda: clock[0])
    handle = store.put("owner", workspace.Workspace(safe_metadata))
    assert store.get("owner", handle).metadata is safe_metadata
    assert store.get("other", handle) is None
    store.remove("other", handle)
    assert store.get("owner", handle) is not None
    clock[0] = 11
    assert store.get("owner", handle) is None


def test_new_setup_replaces_old_capability_and_bounds_memory(safe_metadata):
    store = workspace.WorkspaceStore(maximum=1)
    first = store.put("owner", workspace.Workspace(safe_metadata))
    second = store.put("owner", workspace.Workspace(safe_metadata))
    assert first != second and store.get("owner", first) is None
    store.put("other", workspace.Workspace(safe_metadata))
    assert store.get("owner", second) is None


def test_session_booleans_never_grant_metadata_or_admin_access():
    assert workspace.current_workspace({"admin": True, "connected": True, workspace.HANDLE_KEY: "forged"}, session_id="other") is None


def test_offline_answer_never_dispatches_even_with_a_bound_full_facade(safe_metadata, monkeypatch):
    from stark_t2sql.ui import project_status
    def forbidden(*args): pytest.fail("Offline question cannot generate or execute SQL")
    monkeypatch.setattr(project_status, "live_service_status", lambda: {"SQLCoder model": "OFFLINE"})
    app = workspace.Workspace(safe_metadata, SimpleNamespace(answer=forbidden))
    result = app.answer(safe_metadata.personas[0], "show every employee", date(2026, 10, 12))
    assert result.status is OutcomeStatus.MODEL_ERROR and result.rows == ()


def test_masked_setup_clears_passwords_and_does_not_change_environment(safe_metadata, monkeypatch, tmp_path):
    import os
    before = dict(os.environ)
    state = {key: "PRIVATE_SENTINEL_PASSWORD" for key in workspace.PASSWORD_KEYS}
    state["stark_setup_measurements"] = str(tmp_path / "measurement.txt")
    monkeypatch.setattr(workspace, "inspect_metadata", lambda *a, **k: safe_metadata)
    monkeypatch.setattr(workspace, "_ATTEMPTS", {})
    workspace.connect_from_form(state, root=tmp_path, session_id="test-private-owner")
    assert all(key not in state for key in workspace.PASSWORD_KEYS)
    assert "PRIVATE_SENTINEL_PASSWORD" not in json.dumps(state)
    assert workspace.current_workspace(state, session_id="test-private-owner").metadata is safe_metadata
    assert dict(os.environ) == before
    workspace.disconnect(state, session_id="test-private-owner")
    assert workspace.HANDLE_KEY not in state


def test_failed_setup_never_leaks_driver_error_or_retains_a_capability(monkeypatch, tmp_path):
    state = {key: "PRIVATE_SENTINEL_PASSWORD" for key in workspace.PASSWORD_KEYS}
    def fail(*args, **kwargs): raise RuntimeError("PRIVATE_SENTINEL_PASSWORD raw database error SQL")
    monkeypatch.setattr(workspace, "inspect_metadata", fail)
    monkeypatch.setattr(workspace, "_ATTEMPTS", {})
    workspace.connect_from_form(state, root=tmp_path, session_id="test-failed-owner")
    assert "PRIVATE_SENTINEL" not in json.dumps(state)
    assert workspace.HANDLE_KEY not in state
    assert "BLOCKED" in state[workspace.NOTICE_KEY]


def test_setup_rate_limit_is_server_side(monkeypatch):
    monkeypatch.setattr(workspace, "_ATTEMPTS", {})
    for _ in range(5): workspace._allow_attempt("same-browser")
    with pytest.raises(ValueError): workspace._allow_attempt("same-browser")


@pytest.mark.parametrize("database,host,port", (("other", "127.0.0.1", 5433), ("stark_test", "127.0.0.1", 5432), ("stark_test", "::1", 5433)))
def test_metadata_rejects_wrong_fixed_target_before_connection(tmp_path, database, host, port, monkeypatch):
    values = {"STARK_PG_DATABASE": database, "STARK_PG_HOST": host, "STARK_PG_PORT": str(port)}
    from stark_t2sql.pipeline import metadata
    monkeypatch.setattr(metadata, "AdminConnectionSource", lambda *a, **k: pytest.fail("No wrong-target connection"))
    with pytest.raises(ConfigurationError): inspect_metadata(load_config(root=tmp_path, environment=values), installation_binding=tmp_path / "unused", environment=values)


@pytest.mark.parametrize("change", ("matrix", "database", "digest", "duplicate"))
def test_installation_binding_is_not_a_self_declared_policy_bypass(tmp_path, change):
    record = {"database_name": "stark_test", "matrix_sha256": "1" * 64, "policy_state_sha256": "2" * 64}
    if change == "matrix": record["matrix_sha256"] = "3" * 64
    if change == "database": record["database_name"] = "other"
    if change == "digest": record["policy_state_sha256"] = "bad"
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(record) if change != "duplicate" else '{"database_name":"a","database_name":"stark_test"}')
    with pytest.raises(Exception): load_installation_digest(path, root=tmp_path, matrix_sha256="1" * 64)


def test_app_renders_authenticated_metadata_while_model_offline(project_root, safe_metadata, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from stark_t2sql.ui import project_status
    monkeypatch.delenv("STARK_ENABLE_CONNECTED_UI", raising=False)
    monkeypatch.setattr(project_status, "live_service_status", lambda **kwargs: {"PostgreSQL listener": "LISTENING", "SQLCoder model": "OFFLINE"})
    monkeypatch.setattr(workspace, "session_identity", lambda: "TEST_UI_OWNER")
    handle = workspace.STORE.put("TEST_UI_OWNER", workspace.Workspace(safe_metadata))
    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()
    app.session_state[workspace.HANDLE_KEY] = handle
    for name in ("Playground", "Semantic Catalog", "Access Policy"):
        app.sidebar.radio[0].set_value(name).run()
        assert not app.exception and app.sidebar.selectbox[0].label == "Simulated persona"
        if name == "Playground":
            app.text_area(key="stark_question").set_value("A real typed question").run()
            assert app.button(key="stark_ask").disabled
            assert any("SQLCoder offline" in item.value for item in app.warning)
        else:
            assert not any("Connected views are paused" in item.value for item in app.warning)
    workspace.STORE.remove("TEST_UI_OWNER", handle)


def test_settings_fields_are_masked_and_real_account_features_remain_gated(project_root):
    from streamlit.testing.v1 import AppTest
    from streamlit.proto.TextInput_pb2 import TextInput
    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Settings").run()
    assert not app.exception
    assert all(app.text_input(key=key).proto.type == TextInput.PASSWORD for key in workspace.PASSWORD_KEYS)
    for page in ("Admin Panel", "Login / Signup", "Data Lab"):
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception
        assert all(button.disabled for button in app.button)


def test_no_layout_deprecation_and_primary_palette_is_monochrome(project_root):
    from stark_t2sql.ui.views import _LOCAL_CSS
    import re
    for path in (project_root / "src/stark_t2sql/ui").glob("*.py"):
        assert "use_container_width=" not in path.read_text(encoding="utf-8")
    for color in re.findall(r"#[0-9a-fA-F]{6}", _LOCAL_CSS):
        assert color[1:3].lower() == color[3:5].lower() == color[5:7].lower()


def test_offline_suite_never_autoloads_configured_database_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("STARK_TEST_ENABLE_DB_INTEGRATION", "0")
    monkeypatch.setattr(workspace, "inspect_metadata", lambda *a, **k: pytest.fail("Offline test cannot connect"))
    for name in ("STARK_ADMIN_PASSWORD", "STARK_PAYROLL_PASSWORD", "STARK_HR_PASSWORD", "STARK_SALES_PASSWORD",
                 "STARK_INSTALLATION_BINDING_PATH", "STARK_RESOURCE_MEASUREMENTS_PATH"):
        monkeypatch.setenv(name, "TEST_ONLY")
    state = {}
    workspace.load_configured_metadata(state, root=tmp_path)
    assert not state
