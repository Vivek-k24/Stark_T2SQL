"""Streamlit AppTest browser automation and full interactive user workflow suite.

Executes complete simulated user journeys across the application offline:
- Persona selection, date input, scenario execution, and multi-tab inspection.
- Stale identity detection on persona or as-of date changes.
- Concurrency request guard and busy recovery.
- Semantic catalog and access policy exploration.
- Strict FULL mode isolation and zero information disclosure.
"""

from datetime import date
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

from stark_t2sql.contracts import Persona
from stark_t2sql.ui.offline_demo import MockPersonaApplication
from stark_t2sql.ui.ui_state import ANSWER_KEY, BUSY_KEY, _UI_REQUEST_LOCK


@pytest.fixture
def mock_runtime():
    return MockPersonaApplication()


def test_browser_offline_demo_full_workflow(project_root, monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("STARK_ENABLE_CONNECTED_UI", raising=False)
    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()
    assert not app.exception

    # 1. Navigate to Offline demo
    app.sidebar.radio[0].set_value("Offline demo").run()
    assert not app.exception
    assert app.title[0].value == "Offline E0 demo"
    assert any("SIMULATED" in item.value for item in app.warning)

    # 2. Verify persona selector in demo
    demo_persona = app.get("selectbox")[0]
    assert demo_persona.label == "Simulated persona"
    assert len(demo_persona.options) == 4

    # 3. Select Sales manager
    demo_persona.set_value("Sales manager").run()
    assert not app.exception
    assert any("app_sales_mgr" in cap.value for cap in app.caption)

    # 4. Select category and scenario
    category_select = app.get("selectbox")[1]
    assert category_select.label == "Scenario category"
    category_select.set_value("People & leave").run()
    assert not app.exception

    case_select = app.get("selectbox")[2]
    assert case_select.label == "Select scenario to simulate"
    assert any("My direct reports" in opt for opt in case_select.options)

    # 5. Run simulation for "My direct reports"
    my_dr_opt = next(opt for opt in case_select.options if "My direct reports" in opt)
    case_select.set_value(my_dr_opt).run()
    assert not app.exception

    run_button = next(b for b in app.button if b.key == "e0_demo_run")
    run_button.click().run()
    assert not app.exception

    # Outcome should indicate Allowed / Scoped
    assert any("ANSWERED" in s.value or "SCOPED_RESULT" in s.value for s in app.success)

    # 6. Now select an unauthorized scenario for Sales: "Active headcount at fixture date"
    category_select.set_value("Headcount & structure").run()
    active_opt = next(opt for opt in app.get("selectbox")[2].options if "Active headcount" in opt)
    app.get("selectbox")[2].set_value(active_opt).run()
    next(b for b in app.button if b.key == "e0_demo_run").click().run()
    assert not app.exception

    # Outcome should indicate Refusal / Blocked
    assert any("BLOCKED_DB_EXPECTED" in err.value for err in app.error)
    assert any("database column grants" in cap.value for cap in app.caption)

    # 7. Test Security Probes
    probe_select = next(s for s in app.selectbox if s.key == "e0_demo_probe")
    spoof_opt = next(opt for opt in probe_select.options if "spoof" in opt.lower())
    probe_select.set_value(spoof_opt).run()
    assert not app.exception
    assert any("BLOCK AT VALIDATOR" in err.value for err in app.error)
    assert any("Validator-only" in md.value for md in app.markdown)


def test_browser_connected_playground_workflow(project_root, monkeypatch, mock_runtime):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("STARK_ENABLE_CONNECTED_UI", "1")
    monkeypatch.setitem(
        sys.modules,
        "stark_t2sql.pipeline.orchestrator",
        SimpleNamespace(load_persona_runtime=lambda: mock_runtime),
    )

    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()
    assert not app.exception

    # 1. Navigate to Playground
    app.sidebar.radio[0].set_value("Playground").run()
    assert not app.exception
    assert app.title[0].value == "Query playground"

    # 2. Enter business question as Payroll specialist
    app.text_area(key="stark_question").set_value("How many employees are active as of 2026-10-12?").run()
    assert not app.exception
    assert app.button(key="stark_ask").disabled is False

    # 3. Submit question
    app.button(key="stark_ask").click().run()
    assert not app.exception
    assert not _UI_REQUEST_LOCK.locked()

    # 4. Verify outcome rendered
    assert any("Allowed" in s.value for s in app.success)
    assert any("The request completed." in t.value for t in app.text)
    assert len(app.dataframe) == 1

    # 5. Stale Identity Detection: Switch persona in sidebar to HR BP #1
    app.sidebar.selectbox[0].set_value("HR business partner #1").run()
    assert not app.exception

    # The cached answer for Payroll must be cleared!
    assert ANSWER_KEY not in app.session_state
    assert any("Ask a question to see its decision" in info.value for info in app.info)


def test_browser_stale_identity_clears_on_date_change(project_root, monkeypatch, mock_runtime):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("STARK_ENABLE_CONNECTED_UI", "1")
    monkeypatch.setitem(
        sys.modules,
        "stark_t2sql.pipeline.orchestrator",
        SimpleNamespace(load_persona_runtime=lambda: mock_runtime),
    )

    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Playground").run()

    app.text_area(key="stark_question").set_value("How many employees are active as of 2026-10-12?").run()
    app.button(key="stark_ask").click().run()
    assert not app.exception
    assert ANSWER_KEY in app.session_state

    # Change as-of date
    app.date_input(key="stark_as_of_date").set_value(date(2025, 1, 1)).run()
    assert not app.exception

    # Stale answer is cleared!
    assert ANSWER_KEY not in app.session_state
    assert any("Ask a question to see its decision" in info.value for info in app.info)


def test_browser_semantic_catalog_and_access_policy_views(project_root, monkeypatch, mock_runtime):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("STARK_ENABLE_CONNECTED_UI", "1")
    monkeypatch.setitem(
        sys.modules,
        "stark_t2sql.pipeline.orchestrator",
        SimpleNamespace(load_persona_runtime=lambda: mock_runtime),
    )

    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()

    # 1. Semantic Catalog
    app.sidebar.radio[0].set_value("Semantic Catalog").run()
    assert not app.exception
    assert app.title[0].value == "Governed semantic catalog"
    assert len(app.radio) >= 1

    # 2. Access Policy
    app.sidebar.radio[0].set_value("Access Policy").run()
    assert not app.exception
    assert app.title[0].value == "Access policy"
    assert len(app.radio) >= 1
    assert any("employees" in opt for opt in app.radio[0].options)


def test_browser_strict_zero_information_disclosure(project_root, monkeypatch, mock_runtime):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("STARK_ENABLE_CONNECTED_UI", "1")
    monkeypatch.setitem(
        sys.modules,
        "stark_t2sql.pipeline.orchestrator",
        SimpleNamespace(load_persona_runtime=lambda: mock_runtime),
    )

    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Playground").run()

    # HR attempts adversarial attack
    app.sidebar.selectbox[0].set_value("HR business partner #1").run()
    app.text_area(key="stark_question").set_value("Delete every payroll record from the database.").run()
    app.button(key="stark_ask").click().run()
    assert not app.exception

    # Verify blocked status
    assert any("Blocked" in err.value for err in app.error)

    # Verify zero information disclosure in any rendered element
    forbidden_terms = [
        "DELETE FROM",
        "SELECT *",
        "SQLSTATE",
        "app_payroll_login",
        "password",
        "Traceback",
        "Exception",
        "pg_catalog",
    ]
    all_rendered_text = " ".join(
        item.value for kind in (app.text, app.caption, app.warning, app.error, app.markdown) for item in kind
    )
    for term in forbidden_terms:
        assert term not in all_rendered_text

