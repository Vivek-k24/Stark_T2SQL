"""CLI test definitions only; this source-authoring assignment executes none."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


def test_default_invocation_stops_before_owner_loader(monkeypatch, capsys):
    from stark_t2sql.evaluation import __main__ as cli

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("Default invocation must not import an owner composition")

    monkeypatch.setattr(cli, "_load_owner_factory", forbidden_loader)
    assert cli.main([]) == 0
    assert "No evaluation was requested" in capsys.readouterr().out


def test_nonexecute_options_never_read_composition(monkeypatch):
    from stark_t2sql.evaluation import __main__ as cli

    def forbidden_read(*args, **kwargs):
        raise AssertionError("No source payload may be read without --execute")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    assert cli.main(["--mode", "UNCONTROLLED", "--composition", "owner.py", "--composition-sha256", "unavailable"]) == 0


def test_explicit_execution_requires_recorded_composition_inputs(monkeypatch):
    from stark_t2sql.evaluation import __main__ as cli

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("Incomplete execution inputs cannot import owner source")

    monkeypatch.setattr(cli, "_load_owner_factory", forbidden_loader)
    assert cli.main(["--execute", "--mode", "FULL"]) == 2


def test_mode_vocabulary_rejects_arbitrary_bypass_name():
    from stark_t2sql.evaluation import __main__ as cli

    with pytest.raises(SystemExit) as raised:
        cli.main(["--mode", "SUPERUSER"])
    assert raised.value.code == 2


def test_help_does_not_import_owner_composition(monkeypatch):
    from stark_t2sql.evaluation import __main__ as cli

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("Help cannot import reviewed owner source")

    monkeypatch.setattr(cli, "_load_owner_factory", forbidden_loader)
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])
    assert raised.value.code == 0


def test_workspace_escape_is_rejected_before_payload_read(monkeypatch, tmp_path):
    from stark_t2sql.evaluation import __main__ as cli

    root = tmp_path / "workspace"
    external = tmp_path / "outside.py"

    def forbidden_read(*args, **kwargs):
        raise AssertionError("An external source must be rejected before file read")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read)
    actual_test_source_hash = sha256(b"# hand-authored test source\n").hexdigest()
    with pytest.raises(ValueError):
        cli._load_owner_factory(root.resolve(), external, actual_test_source_hash)


def test_hash_mismatch_stops_before_owner_module_creation(monkeypatch, tmp_path):
    from stark_t2sql.evaluation import __main__ as cli

    actual_source = b"# different hand-authored test composition\n"
    recorded_source = b"# originally reviewed hand-authored test composition\n"
    monkeypatch.setattr(Path, "read_bytes", lambda self: actual_source)

    def forbidden_module_creation(*args, **kwargs):
        raise AssertionError("Hash mismatch cannot create/import an owner module")

    monkeypatch.setattr(cli.importlib.util, "module_from_spec", forbidden_module_creation)
    with pytest.raises(ValueError):
        cli._load_owner_factory(tmp_path.resolve(), tmp_path / "owner.py", sha256(recorded_source).hexdigest())


def _install_fake_runner(monkeypatch, job_type, summary_type):
    module = SimpleNamespace(EvaluationJob=job_type, RunSummary=summary_type)
    monkeypatch.setitem(sys.modules, "stark_t2sql.evaluation.runner", module)


def test_future_cli_refuses_holdout_job_before_execute(monkeypatch, tmp_path):
    from stark_t2sql.contracts import ExecutionMode
    from stark_t2sql.evaluation import __main__ as cli
    from stark_t2sql.evaluation.holdout import CasePartition

    class Job:
        plan = SimpleNamespace(partition=CasePartition.HOLDOUT, mode=ExecutionMode.FULL)

        def execute(self):
            raise AssertionError("The CLI must never execute a holdout job")

    class Summary:
        pass

    _install_fake_runner(monkeypatch, Job, Summary)
    monkeypatch.setattr(cli, "_project_root", lambda requested: tmp_path)
    monkeypatch.setattr(cli, "_load_owner_factory", lambda *args: lambda **kwargs: Job())
    digest = sha256(b"# hand-authored reviewed composition source for CLI guard test\n").hexdigest()
    assert cli.main(["--execute", "--mode", "FULL", "--composition", "owner.py", "--composition-sha256", digest]) == 2


def test_future_cli_refuses_owner_mode_substitution(monkeypatch, tmp_path):
    from stark_t2sql.contracts import ExecutionMode
    from stark_t2sql.evaluation import __main__ as cli
    from stark_t2sql.evaluation.holdout import CasePartition

    class Job:
        plan = SimpleNamespace(partition=CasePartition.TUNING, mode=ExecutionMode.UNCONTROLLED)

        def execute(self):
            raise AssertionError("A substituted mode must stop before candidate execution")

    class Summary:
        pass

    _install_fake_runner(monkeypatch, Job, Summary)
    monkeypatch.setattr(cli, "_project_root", lambda requested: tmp_path)
    monkeypatch.setattr(cli, "_load_owner_factory", lambda *args: lambda **kwargs: Job())
    digest = sha256(b"# hand-authored reviewed composition source for mode guard test\n").hexdigest()
    assert cli.main(["--execute", "--mode", "FULL", "--composition", "owner.py", "--composition-sha256", digest]) == 2


def test_future_cli_runs_only_exact_requested_tuning_job(monkeypatch, tmp_path):
    from stark_t2sql.contracts import ExecutionMode
    from stark_t2sql.evaluation import __main__ as cli
    from stark_t2sql.evaluation.holdout import CasePartition

    calls = []

    class Summary:
        complete = True
        scored_cases = 0
        pending_cases = 0

    class Job:
        plan = SimpleNamespace(partition=CasePartition.TUNING, mode=ExecutionMode.NO_VALIDATOR)

        def execute(self):
            calls.append("execute")
            return Summary()

    _install_fake_runner(monkeypatch, Job, Summary)
    monkeypatch.setattr(cli, "_project_root", lambda requested: tmp_path)

    def factory(*, root, mode):
        assert root == tmp_path
        assert mode is ExecutionMode.NO_VALIDATOR
        return Job()

    monkeypatch.setattr(cli, "_load_owner_factory", lambda *args: factory)
    digest = sha256(b"# hand-authored reviewed composition source for dispatch test\n").hexdigest()
    assert cli.main(["--execute", "--mode", "NO_VALIDATOR", "--composition", "owner.py", "--composition-sha256", digest]) == 0
    assert calls == ["execute"]


def test_future_cli_reports_pending_summary_without_completion_claim(monkeypatch, tmp_path, capsys):
    from stark_t2sql.contracts import ExecutionMode
    from stark_t2sql.evaluation import __main__ as cli
    from stark_t2sql.evaluation.holdout import CasePartition

    class Summary:
        complete = False
        scored_cases = 0
        pending_cases = 1

    class Job:
        plan = SimpleNamespace(partition=CasePartition.TUNING, mode=ExecutionMode.FULL)

        def execute(self):
            return Summary()

    _install_fake_runner(monkeypatch, Job, Summary)
    monkeypatch.setattr(cli, "_project_root", lambda requested: tmp_path)
    monkeypatch.setattr(cli, "_load_owner_factory", lambda *args: lambda **kwargs: Job())
    digest = sha256(b"# hand-authored reviewed composition source for pending summary test\n").hexdigest()
    assert cli.main(["--execute", "--mode", "FULL", "--composition", "owner.py", "--composition-sha256", digest]) == 3
    output = capsys.readouterr().out
    assert "pending cases=1" in output
    assert "returned complete" not in output


def test_future_cli_does_not_print_owner_exception_payload(monkeypatch, tmp_path, capsys):
    from stark_t2sql.evaluation import __main__ as cli

    private_marker = "private-owner-diagnostic-marker"
    monkeypatch.setattr(cli, "_project_root", lambda requested: tmp_path)

    def unavailable_loader(*args):
        raise RuntimeError(private_marker)

    monkeypatch.setattr(cli, "_load_owner_factory", unavailable_loader)
    digest = sha256(b"# hand-authored reviewed composition source for error boundary test\n").hexdigest()
    assert cli.main(["--execute", "--mode", "FULL", "--composition", "owner.py", "--composition-sha256", digest]) == 2
    output = capsys.readouterr()
    assert private_marker not in output.out + output.err

