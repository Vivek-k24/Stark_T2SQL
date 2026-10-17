"""Owned-child lifecycle; no server or external process in these unit tests."""
import os
import pytest
from ops import serve


@pytest.mark.parametrize("code", (0, 3, 42))
def test_real_child_exit_status_is_preserved(monkeypatch, code):
    class Child:
        def wait(self, **kwargs): return code
    monkeypatch.setattr(serve.subprocess, "Popen", lambda *a, **k: Child())
    assert serve.run_foreground(["unit"], cwd=".", env={}) == code


def test_ctrl_c_signals_and_reaps_only_owned_child(monkeypatch, capsys):
    calls = []
    class Child:
        pid = 12345
        first = True
        def wait(self, **kwargs):
            if self.first:
                self.first = False
                raise KeyboardInterrupt()
            calls.append(("wait", kwargs))
            return 0
        def poll(self): return None
        def send_signal(self, value): calls.append(("signal", value))
    monkeypatch.setattr(serve.subprocess, "Popen", lambda *a, **k: Child())
    if os.name != "nt": monkeypatch.setattr(serve.os, "killpg", lambda *a: calls.append(("signal", a)))
    assert serve.run_foreground(["unit"], cwd=".", env={}) == 130
    assert any(call[0] == "signal" for call in calls)
    assert "Traceback" not in capsys.readouterr().out


def test_unresponsive_child_is_terminated_then_killed_and_reaped(monkeypatch):
    calls = []
    class Child:
        pid = 12345
        first = True
        killed = False
        def wait(self, **kwargs):
            if self.first:
                self.first = False
                raise KeyboardInterrupt()
            if not self.killed: raise serve.subprocess.TimeoutExpired("unit", 1)
            calls.append("reaped")
        def poll(self): return None
        def send_signal(self, value): pass
        def terminate(self): calls.append("terminate")
        def kill(self): self.killed = True; calls.append("kill")
    monkeypatch.setattr(serve.subprocess, "Popen", lambda *a, **k: Child())
    if os.name != "nt": monkeypatch.setattr(serve.os, "killpg", lambda *a: None)
    assert serve.run_foreground(["unit"], cwd=".", env={}) == 130
    assert calls == ["terminate", "kill", "reaped"]


def test_spawn_failure_is_nonzero_and_sanitized(monkeypatch, capsys):
    def fail(*a, **k): raise OSError("PRIVATE_SENTINEL")
    monkeypatch.setattr(serve.subprocess, "Popen", fail)
    assert serve.run_foreground(["unit"], cwd=".", env={}) == 2
    assert "PRIVATE_SENTINEL" not in capsys.readouterr().err


def test_foreground_wait_is_bounded_so_windows_can_dispatch_interrupts(monkeypatch):
    calls = []
    class Child:
        def wait(self, *, timeout):
            calls.append(timeout)
            if len(calls) == 1: raise serve.subprocess.TimeoutExpired("unit", timeout)
            return 0
    monkeypatch.setattr(serve.subprocess, "Popen", lambda *a, **k: Child())
    assert serve.run_foreground(["unit"], cwd=".", env={}) == 0
    assert calls == [0.25, 0.25]
