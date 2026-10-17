"""Explicit existing-fixture checks; never selected as ordinary offline evidence.

Run this file alone with STARK_LIVE_UI_READONLY=1 and private STARK credential
variables. Never enable/reset the whole database suite for this check.
AppTest here uses REAL PostgreSQL but is still not a browser walkthrough.
"""
import os
from pathlib import Path
import pytest


@pytest.fixture
def authorized_existing_environment():
    if os.environ.get("STARK_LIVE_UI_READONLY") != "1" or os.environ.get("STARK_TEST_ENABLE_DB_INTEGRATION") == "0":
        pytest.skip("Existing live-UI read-only checks require explicit separate opt-in and private credentials; no setup/reset.")
    values = dict(os.environ)
    required = ("STARK_ADMIN_PASSWORD", "STARK_PAYROLL_PASSWORD", "STARK_HR_PASSWORD", "STARK_SALES_PASSWORD",
                "STARK_INSTALLATION_BINDING_PATH", "STARK_RESOURCE_MEASUREMENTS_PATH")
    if not all(values.get(key) for key in required):
        pytest.skip("Actual private existing STARK credentials/bindings are not supplied.")
    return values


def test_actual_existing_fixture_readonly_security_and_unchanged_rows(project_root, authorized_existing_environment):
    from ops.live_ui_verify import verify
    values = authorized_existing_environment
    result = verify(project_root, environment=values, installation_binding=Path(values["STARK_INSTALLATION_BINDING_PATH"]))
    assert result["failed"] == 0 and result["passed"] == 14
    assert result["model_inference"] == "NOT_EXECUTED"


def test_actual_masked_setup_and_four_persona_views_with_model_off(project_root, authorized_existing_environment, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from stark_t2sql.ui.project_status import live_service_status
    from stark_t2sql.ui import workspace
    values = authorized_existing_environment
    assert live_service_status()["SQLCoder model"] == "OFFLINE"
    # Exercise the actual masked form, rather than the configured-environment path.
    monkeypatch.delenv("STARK_INSTALLATION_BINDING_PATH")
    monkeypatch.delenv("STARK_ENABLE_CONNECTED_UI", raising=False)
    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=40).run()
    app.sidebar.radio[0].set_value("Settings").run()
    for key, variable in zip(workspace.PASSWORD_KEYS, ("STARK_ADMIN_PASSWORD", "STARK_PAYROLL_PASSWORD", "STARK_HR_PASSWORD", "STARK_SALES_PASSWORD")):
        app.text_input(key=key).set_value(values[variable])
    app.text_input(key="stark_setup_binding").set_value(values["STARK_INSTALLATION_BINDING_PATH"])
    app.text_input(key="stark_setup_measurements").set_value(values["STARK_RESOURCE_MEASUREMENTS_PATH"])
    next(button for button in app.button if button.label.startswith("Verify database")).click().run()
    assert not app.exception
    assert bool(app.session_state[workspace.HANDLE_KEY])
    state = app.session_state.to_dict()
    assert all(not state.get(key) for key in workspace.PASSWORD_KEYS)
    app.sidebar.radio[0].set_value("Playground").run()
    names = tuple(app.sidebar.selectbox[0].options)
    assert len(names) == 4
    for name in names:
        app.sidebar.selectbox[0].set_value(name).run()
        app.text_area(key="stark_question").set_value("How many employees are visible?").run()
        assert not app.exception and app.button(key="stark_ask").disabled
        assert any("SQLCoder offline" in item.value for item in app.warning)
        for page in ("Semantic Catalog", "Access Policy"):
            app.sidebar.radio[0].set_value(page).run()
            assert not app.exception and app.sidebar.selectbox[0].value == name
        app.sidebar.radio[0].set_value("Playground").run()
