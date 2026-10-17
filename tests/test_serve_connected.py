"""Offline connected-launcher checks; no services, browser or database calls."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from ops import serve, serve_connected


@pytest.fixture
def launch_sources(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    root.mkdir()
    for name in serve_connected._REQUIRED_SOURCES:
        source = root / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("TEST_ONLY_SOURCE", encoding="utf-8")
    private = tmp_path / "private"
    private.mkdir()
    bindings = private / "bindings.json"
    bindings.write_text(json.dumps({name: "TEST_ONLY" for name in serve_connected._BINDING_FIELDS}), encoding="utf-8")
    monkeypatch.setattr(serve_connected.importlib.util, "find_spec", lambda name: object())
    return root, bindings


def test_command_uses_existing_interpreter_fixed_loopback_and_security():
    actual = serve_connected.command(Path("workspace"), 8502)
    assert actual[:4] == (sys.executable, "-m", "streamlit", "run")
    assert "--server.address=127.0.0.1" in actual
    assert "--server.port=8502" in actual
    assert "--browser.gatherUsageStats=false" in actual
    assert "--server.enableCORS=true" in actual
    assert "--server.enableXsrfProtection=true" in actual
    assert "--server.enableStaticServing=false" in actual
    assert not any("mode" in item.casefold() or "uncontrolled" in item.casefold() for item in actual)


@pytest.mark.parametrize("port", [True, False, 0, 80, 1023, 65536, "8502", 8502.0])
def test_port_validation_rejects_nonprivileged_or_untyped_values(port):
    with pytest.raises(serve_connected.ConnectedLaunchError):
        serve_connected.command(Path("workspace"), port)


@pytest.mark.parametrize("ack,flag", [(False, None), (False, "1"), (True, None), (True, "true"), (True, "0")])
def test_both_activation_gates_required(launch_sources, ack, flag):
    root, bindings = launch_sources
    environment = {} if flag is None else {"STARK_ENABLE_CONNECTED_UI": flag}
    with pytest.raises(serve_connected.ConnectedLaunchError, match="requires"):
        serve_connected.build_launch(root, bindings, connected_acknowledged=ack, environment=environment)


def test_plan_preserves_private_environment_without_printing_it(launch_sources):
    root, bindings = launch_sources
    environment = {"STARK_ENABLE_CONNECTED_UI": "1", "PRIVATE_PASSWORD": "TEST_ONLY_SECRET", "OTHER": "kept"}
    plan = serve_connected.build_launch(root, bindings, connected_acknowledged=True, environment=environment)
    assert plan.environment["PRIVATE_PASSWORD"] == "TEST_ONLY_SECRET"
    assert plan.environment["OTHER"] == "kept"
    assert plan.environment["STARK_ENABLE_CONNECTED_UI"] == "1"
    assert plan.environment["STARK_RUNTIME_BINDINGS_PATH"] == str(bindings.resolve())
    assert plan.environment["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] == "false"
    assert "TEST_ONLY_SECRET" not in repr(plan)
    assert "STARK_RUNTIME_BINDINGS_PATH" not in environment


@pytest.mark.parametrize("location", ["relative.json", "inside", "missing", "directory", "metadata", "unc"])
def test_private_binding_path_failures(launch_sources, location):
    root, bindings = launch_sources
    if location == "relative.json":
        bindings = Path(location)
    elif location == "inside":
        bindings = root / "bindings.json"
        bindings.write_text("{}", encoding="utf-8")
    elif location == "missing":
        bindings = bindings.parent / "missing.json"
    elif location == "directory":
        bindings = bindings.parent
    elif location == "metadata":
        bindings = bindings.parent / ".git" / "bindings.json"
        bindings.parent.mkdir()
        bindings.write_text("{}", encoding="utf-8")
    else:
        bindings = Path("//remote/private/bindings.json")
    with pytest.raises(serve_connected.ConnectedLaunchError):
        serve_connected.build_launch(root, bindings, connected_acknowledged=True, environment={"STARK_ENABLE_CONNECTED_UI": "1"})


@pytest.mark.parametrize("payload", [b"{}", b"[]", b"null", b"not json", b"\xff", b'{"x":1,"x":2}', b'{"x":NaN}', b"x" * 1_048_577],
                         ids=["empty", "array", "null", "syntax", "encoding", "duplicate", "nonfinite", "oversized"])
def test_invalid_json_fails_without_private_content(launch_sources, payload):
    root, bindings = launch_sources
    bindings.write_bytes(payload)
    with pytest.raises(serve_connected.ConnectedLaunchError) as raised:
        serve_connected.build_launch(root, bindings, connected_acknowledged=True, environment={"STARK_ENABLE_CONNECTED_UI": "1"})
    assert str(bindings) not in str(raised.value)
    assert "not json" not in str(raised.value)


def test_missing_application_source_prevents_launch(launch_sources):
    root, bindings = launch_sources
    (root / "src/inference/prompt_template.txt").unlink()
    with pytest.raises(serve_connected.ConnectedLaunchError, match="source"):
        serve_connected.build_launch(root, bindings, connected_acknowledged=True, environment={"STARK_ENABLE_CONNECTED_UI": "1"})


def test_missing_dependency_prevents_launch(launch_sources, monkeypatch):
    root, bindings = launch_sources
    monkeypatch.setattr(serve_connected.importlib.util, "find_spec", lambda name: None if name == "streamlit" else object())
    with pytest.raises(serve_connected.ConnectedLaunchError, match="dependency"):
        serve_connected.build_launch(root, bindings, connected_acknowledged=True, environment={"STARK_ENABLE_CONNECTED_UI": "1"})


def test_main_executes_only_prepared_foreground_command(launch_sources, monkeypatch, capsys):
    root, bindings = launch_sources
    plan = serve_connected.build_launch(root, bindings, connected_acknowledged=True, environment={"STARK_ENABLE_CONNECTED_UI": "1", "SECRET": "TEST_ONLY_SECRET"})
    monkeypatch.setattr(serve_connected, "build_launch", lambda *args, **kwargs: plan)
    calls = []
    monkeypatch.setattr(serve_connected, "run_foreground", lambda *args, **kwargs: calls.append((args, kwargs)) or 7)
    assert serve_connected.main(["--runtime-bindings", str(bindings), "--enable-connected-ui"]) == 7
    assert calls == [((plan.command,), {"cwd": root.resolve(), "env": dict(plan.environment), "shell": False})]
    assert "TEST_ONLY_SECRET" not in capsys.readouterr().out


def test_main_failures_never_launch(launch_sources, monkeypatch, capsys):
    _, bindings = launch_sources
    def reject(*args, **kwargs):
        raise serve_connected.ConnectedLaunchError("Prerequisite unavailable.")
    monkeypatch.setattr(serve_connected, "build_launch", reject)
    monkeypatch.setattr(serve_connected, "run_foreground", lambda *args, **kwargs: pytest.fail("must not launch"))
    assert serve_connected.main(["--runtime-bindings", str(bindings), "--enable-connected-ui"]) == 2
    assert "NOT STARTED" in capsys.readouterr().err


@pytest.mark.parametrize("error,exit_code", [(OSError("TEST_ONLY_PRIVATE_ERROR"), 2), (KeyboardInterrupt(), 130)])
def test_foreground_launch_failure_and_interrupt_are_sanitized(launch_sources, monkeypatch, capsys, error, exit_code):
    root, bindings = launch_sources
    plan = serve_connected.build_launch(root, bindings, connected_acknowledged=True, environment={"STARK_ENABLE_CONNECTED_UI": "1"})
    monkeypatch.setattr(serve_connected, "build_launch", lambda *args, **kwargs: plan)
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(serve_connected, "run_foreground", fail)
    assert serve_connected.main(["--runtime-bindings", str(bindings), "--enable-connected-ui"]) == exit_code
    assert "TEST_ONLY_PRIVATE_ERROR" not in capsys.readouterr().err


def test_relative_project_root_is_resolved_before_child_command(launch_sources, monkeypatch):
    root, bindings = launch_sources
    monkeypatch.chdir(root.parent)
    plan = serve_connected.build_launch(Path(root.name), bindings, connected_acknowledged=True, environment={"STARK_ENABLE_CONNECTED_UI": "1"})
    assert plan.command[4] == str(root.resolve() / "app.py")
    assert plan.root == root.resolve()


@pytest.mark.parametrize("argument", ["--mode", "--server.address", "--skip-policy", "--disable-xsrf"])
def test_cli_has_no_bypass_arguments(argument):
    with pytest.raises(SystemExit) as raised:
        serve_connected.main(["--runtime-bindings", "private.json", argument, "UNCONTROLLED"])
    assert raised.value.code == 2


def test_offline_launcher_still_removes_connected_optin(monkeypatch):
    monkeypatch.setenv("STARK_ENABLE_CONNECTED_UI", "1")
    monkeypatch.setattr(sys, "argv", ["ops.serve"])
    calls = []
    monkeypatch.setattr(serve, "run_foreground", lambda *args, **kwargs: calls.append((args, kwargs)) or 0)
    assert serve.main() == 0
    assert "STARK_ENABLE_CONNECTED_UI" not in calls[0][1]["env"]
    assert "--server.address=127.0.0.1" in calls[0][0][0]


def test_actual_app_retains_explicit_optin_and_full_only_facade(project_root):
    app = (project_root / "app.py").read_text(encoding="utf-8")
    assert 'os.environ.get("STARK_ENABLE_CONNECTED_UI") != "1"' in app
    from stark_t2sql.pipeline.orchestrator import PersonaApplication, RuntimeSourceInputs
    from inspect import signature
    from dataclasses import fields
    assert tuple(signature(PersonaApplication.answer).parameters) == ("self", "persona", "question", "as_of_date")
    assert serve_connected._BINDING_FIELDS == {field.name for field in fields(RuntimeSourceInputs)}
