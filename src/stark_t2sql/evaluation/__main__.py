"""Minimal future, local TUNING evaluation entrypoint; source authoring only.

Default invocation never imports an owner composition. Explicit --execute is a
future execution decision, not authority granted by drafting this module. The
owner must supply an actually reviewed local composition and its recorded hash;
this module defines no sample configuration, datasets, credentials, or scores.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
from typing import Callable, Sequence

from ..contracts import ExecutionMode
from .cases import require_sha256
from .holdout import CasePartition


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Future local TUNING evaluation; source drafting does not authorize a run.")
    parser.add_argument("--execute", action="store_true", help="Explicitly request the separately authorized future evaluation.")
    parser.add_argument("--mode", choices=tuple(mode.value for mode in ExecutionMode), help="Required with --execute; harness isolation remains mandatory.")
    parser.add_argument("--composition", type=Path, help="Reviewed owner composition .py file inside the project workspace.")
    parser.add_argument("--composition-sha256", help="Actual recorded SHA-256 of the reviewed owner composition bytes.")
    parser.add_argument("--root", type=Path, help="Project source workspace; must equal this source package's project root.")
    return parser


def _project_root(requested: Path | None) -> Path:
    source_root = Path(__file__).resolve().parents[3]
    root = source_root if requested is None else Path(requested).resolve()
    if root != source_root:
        raise ValueError("The CLI root must equal the source workspace")
    return root


def _load_owner_factory(root: Path, composition: Path, recorded_sha256: str) -> Callable:
    """Future load of the exact approved bytes, with no reopen between hash/exec."""
    require_sha256(recorded_sha256, "Recorded owner composition")
    source_path = composition if composition.is_absolute() else root / composition
    source_path = source_path.resolve()
    if source_path.suffix.lower() != ".py" or not source_path.is_relative_to(root) or source_path == Path(__file__).resolve():
        raise ValueError("The owner composition must be a distinct .py source file inside the workspace")
    payload = source_path.read_bytes()
    if sha256(payload).hexdigest() != recorded_sha256:
        raise ValueError("Actual owner composition bytes differ from the recorded review digest")
    module_name = "_stark_reviewed_evaluation_owner_" + recorded_sha256
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise ValueError("Owner composition import metadata is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        # Compile the same bytes that were hashed; a changing file is never
        # reopened by the loader. This is invoked only after --execute gates.
        exec(compile(payload, str(source_path), "exec"), module.__dict__)
        factory = getattr(module, "compose_evaluation_job", None)
        if not callable(factory):
            raise ValueError("The reviewed owner source must expose compose_evaluation_job")
        return factory
    except BaseException:
        sys.modules.pop(module_name, None)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.execute:
        print("No evaluation was requested. A future run requires --execute, an explicit mode, and reviewed local composition inputs.")
        return 0
    if args.mode is None or args.composition is None or args.composition_sha256 is None:
        print("Evaluation was not started: explicit mode and reviewed local composition inputs are required.", file=sys.stderr)
        return 2
    try:
        root = _project_root(args.root)
        requested_mode = ExecutionMode(args.mode)
        factory = _load_owner_factory(root, args.composition, args.composition_sha256)
        # Future composition may resolve required real assets/identities. It
        # is never imported or invoked by default invocation or source drafting.
        from .runner import EvaluationJob, RunSummary

        job = factory(root=root, mode=requested_mode)
        if type(job) is not EvaluationJob:
            raise TypeError("Owner composition must return the exact typed evaluation job")
        if job.plan.partition is not CasePartition.TUNING or job.plan.mode is not requested_mode:
            raise PermissionError("The CLI permits only the requested TUNING mode")
        summary = job.execute()
        if type(summary) is not RunSummary:
            raise TypeError("The evaluator must return its typed run summary")
        if type(summary.complete) is not bool or any(type(count) is not int or count < 0 for count in (summary.scored_cases, summary.pending_cases)):
            raise TypeError("The evaluator must supply actual bounded counts and an explicit completeness state")
        print(f"Evaluation records: scored cases={summary.scored_cases}; pending cases={summary.pending_cases}.")
        if not summary.complete:
            print("Evaluation inputs or triage remain pending. Internal metadata is in the owner-configured local output directory.")
            return 3
        print("The requested run returned complete evaluation metadata in the owner-configured local output directory.")
        return 0
    except KeyboardInterrupt:
        print("Evaluation was interrupted.", file=sys.stderr)
        return 130
    except Exception:
        # Never print arbitrary owner/driver exceptions, environment values,
        # case contents, SQL, results, credentials, or trace payloads here.
        print("Evaluation could not proceed. Required reviewed inputs, isolation, or local runtime resources are unavailable.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

