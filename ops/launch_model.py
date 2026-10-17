"""Foreground llama.cpp launcher with an enforced per-process memory cap.

Runs ``llama-server`` bound to numeric loopback with one slot inside a Windows
Job Object carrying JOB_OBJECT_LIMIT_PROCESS_MEMORY and KILL_ON_JOB_CLOSE. An
allocation beyond the cap fails inside the model process, so a runaway context
cannot exhaust the host (NFR-2). The cap applies to committed private memory.
File-backed mmap pages of the GGUF are not charged to it.

``--dry-run`` prints the command and limit without starting anything. Starting
or replacing the running model service is an owner-approved operation. This
module does not stop an existing server or choose a port that is in use.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys

DEFAULT_BINARY = Path(r"H:\STARK_Runtime\llama.cpp\llama-b11609-bin-win-cpu-x64\llama-server.exe")
DEFAULT_MODEL = Path(r"H:\STARK_Runtime\models\sqlcoder-7b-2.Q4_K_M.gguf")

JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9


class LaunchError(ValueError):
    """Fixed launcher refusal; no service is started."""


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def command(*, binary: Path, model: Path, port: int, ctx_size: int, threads: int, threads_batch: int,
            kv_cache_type: str | None) -> tuple[str, ...]:
    """Fixed loopback/one-slot command; only measured sizing knobs are variable."""
    if type(port) is not int or not 1024 <= port <= 65535:
        raise LaunchError("Use an unprivileged loopback port.")
    if type(ctx_size) is not int or not 2048 <= ctx_size <= 16384 or ctx_size % 256:
        raise LaunchError("Context size must be a multiple of 256 within the model's 16,384-token training context.")
    if any(type(value) is not int or not 1 <= value <= 64 for value in (threads, threads_batch)):
        raise LaunchError("Thread counts must be small positive integers.")
    arguments = [str(binary), "--model", str(model), "--host", "127.0.0.1", "--port", str(port),
                 "--ctx-size", str(ctx_size), "--parallel", "1", "--threads", str(threads),
                 "--threads-batch", str(threads_batch)]
    if kv_cache_type is not None:
        if kv_cache_type not in {"f16", "q8_0"}:
            raise LaunchError("Only f16 or q8_0 KV cache types are reviewed.")
        # A quantized V cache requires flash attention in llama.cpp.
        arguments += ["--flash-attn", "on", "--cache-type-k", kv_cache_type, "--cache-type-v", kv_cache_type]
    return tuple(arguments)


def _job_with_memory_cap(limit_mib: int):
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise LaunchError("The Windows job object could not be created.")
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    info.ProcessMemoryLimit = limit_mib * 1024 * 1024
    if not kernel32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                            ctypes.byref(info), ctypes.sizeof(info)):
        kernel32.CloseHandle(job)
        raise LaunchError("The job memory limit could not be applied.")
    return kernel32, job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--ctx-size", type=int, default=4096)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--threads-batch", type=int, default=4)
    parser.add_argument("--kv-cache-type", choices=("f16", "q8_0"))
    parser.add_argument("--memory-limit-mib", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not 1024 <= args.memory_limit_mib <= 14336:
            raise LaunchError("The memory cap must leave headroom on the 16 GB workstation (1024-14336 MiB).")
        cmd = command(binary=args.binary, model=args.model, port=args.port, ctx_size=args.ctx_size,
                      threads=args.threads, threads_batch=args.threads_batch, kv_cache_type=args.kv_cache_type)
        if not args.binary.is_file() or not args.model.is_file():
            raise LaunchError("The llama-server binary or GGUF model is unavailable.")
    except LaunchError as exc:
        print(json.dumps({"status": "NOT_STARTED", "reason": str(exc)}))
        return 2
    plan = {"command": list(cmd), "process_memory_limit_mib": args.memory_limit_mib,
            "enforcement": "WINDOWS_JOB_OBJECT_PROCESS_MEMORY_KILL_ON_CLOSE"}
    if args.dry_run or sys.platform != "win32":
        print(json.dumps({"status": "DRY_RUN" if args.dry_run else "NOT_STARTED_NON_WINDOWS", **plan}, indent=2))
        return 0 if args.dry_run else 2
    kernel32, job = _job_with_memory_cap(args.memory_limit_mib)
    process = subprocess.Popen(cmd, shell=False)
    try:
        # Assigned immediately after creation, during model load and before
        # the listener exists. IsProcessInJob confirms the binding.
        if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
            process.kill()
            raise LaunchError("The model process could not be placed under the memory cap.")
        in_job = wintypes.BOOL()
        kernel32.IsProcessInJob(wintypes.HANDLE(int(process._handle)), job, ctypes.byref(in_job))
        print(json.dumps({"status": "STARTED", "pid": process.pid, "in_job": bool(in_job.value), **plan}), flush=True)
        return process.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        kernel32.CloseHandle(job)  # KILL_ON_JOB_CLOSE stops the child with the launcher.


if __name__ == "__main__":
    raise SystemExit(main())
