"""Local Streamlit rendering tests; no database/model credentials or sockets."""
from pathlib import Path
import json
import sys
from types import SimpleNamespace

import pytest

from ops.serve import command
from ops.progress import load, html_block
from stark_t2sql.ui.project_status import health

def test_loopback_launch_cannot_bind_external(root=None):
    args=command(Path.cwd(),8501)
    assert "--server.address=127.0.0.1" in args and "--browser.gatherUsageStats=false" in args
    with pytest.raises(ValueError): command(Path.cwd(),80)

def test_health_and_cached_progress_need_no_runtime(project_root,monkeypatch):
    monkeypatch.setitem(sys.modules,"stark_t2sql.pipeline.orchestrator",SimpleNamespace())
    assert health(project_root)["Architecture & Progress"]=="LOCAL READY"
    data=load(project_root)
    assert [m["gate"] for m in data["milestones"][:3]]==["R01","R02","R03"]
    assert all(m["state"]=="MERGED" and m["live_postgresql"]=="UNVERIFIED" for m in data["milestones"])

def test_real_streamlit_public_views_without_connected_startup(project_root,monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("STARK_ENABLE_CONNECTED_UI",raising=False)
    monkeypatch.setitem(sys.modules,"stark_t2sql.pipeline.orchestrator",SimpleNamespace())
    app=AppTest.from_file(str(project_root/"app.py"),default_timeout=30).run()
    assert not app.exception and app.title[0].value=="Local health & status"
    for name,heading in (("Architecture","Six-stage runtime architecture"),("Progress","Implementation progress explorer")):
        app.sidebar.radio[0].set_value(name).run()
        assert not app.exception and any(item.value==heading for item in app.subheader)
        assert any("R03 · MERGED" in item.value for item in app.markdown)
    app.sidebar.radio[0].set_value("Playground").run()
    assert not app.exception and any("BLOCKED" in item.value for item in app.warning)

def test_original_e0_navigation_and_truthful_simulation_labels_preserved(project_root):
    text=(project_root/"STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html").read_text(encoding="utf-8")
    assert 'id="page-playground"' in text and 'id="page-policy"' in text and 'id="page-architecture"' in text
    assert "SIMULATED" in text and "FRD 1.7" not in text and "FRD 1.8" in text
    assert text.count("<!-- STARK_PROGRESS_BEGIN -->")==1 and "Actual merge commit" in text


def test_progress_is_manually_rendered_without_agent_dispatch(project_root):
    data = load(project_root)
    html = (project_root / "STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html").read_text(encoding="utf-8")
    assert html_block(data) in html
    assert data["interim"]["state"].startswith("MERGED")
    assert "automation" not in data
    assert not (project_root / "ops/coordinator.py").exists()
    assert "Agent handoffs" not in health(project_root)
