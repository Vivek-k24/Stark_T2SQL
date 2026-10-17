"""Offline launcher contracts; nothing is started and no port is opened."""
from __future__ import annotations

import ctypes
import json
import sys

import pytest

from ops import launch_model


def build(**overrides):
    values = dict(binary=launch_model.DEFAULT_BINARY, model=launch_model.DEFAULT_MODEL, port=8081,
                  ctx_size=9216, threads=4, threads_batch=8, kv_cache_type="q8_0")
    values.update(overrides)
    return launch_model.command(**values)


def test_command_is_loopback_single_slot():
    cmd = build()
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--parallel") + 1] == "1"
    assert cmd[cmd.index("--ctx-size") + 1] == "9216"
    assert ("--flash-attn", "on") == cmd[cmd.index("--flash-attn"):cmd.index("--flash-attn") + 2]


def test_default_kv_cache_adds_no_quantization_flags():
    assert "--cache-type-k" not in build(kv_cache_type=None)


@pytest.mark.parametrize("overrides", (
    {"port": 80}, {"ctx_size": 1024}, {"ctx_size": 32768}, {"ctx_size": 9000},
    {"threads": 0}, {"kv_cache_type": "q4_0"},
))
def test_unreviewed_sizing_is_refused(overrides):
    with pytest.raises(launch_model.LaunchError):
        build(**overrides)


def test_dry_run_starts_nothing(capsys, tmp_path, monkeypatch):
    binary, model = tmp_path / "llama-server.exe", tmp_path / "m.gguf"
    binary.write_bytes(b"unit"); model.write_bytes(b"unit")
    monkeypatch.setattr(launch_model.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start"))
    code = launch_model.main(["--binary", str(binary), "--model", str(model), "--memory-limit-mib", "9000",
                              "--ctx-size", "9216", "--dry-run"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["status"] == "DRY_RUN" and report["process_memory_limit_mib"] == 9000


def test_memory_cap_must_leave_host_headroom(capsys):
    assert launch_model.main(["--memory-limit-mib", "15000", "--dry-run"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_STARTED"


@pytest.mark.skipif(sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8, reason="x64 Windows layout only")
def test_job_structure_matches_x64_windows_layout():
    assert ctypes.sizeof(launch_model._BasicLimits) == 64
    assert ctypes.sizeof(launch_model._ExtendedLimits) == 144
