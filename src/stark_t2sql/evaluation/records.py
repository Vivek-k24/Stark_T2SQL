"""Future internal FR-9.7 run records, with unavailable inputs kept explicit.

No record or PROJECT_LOG.md is created by importing or authoring this source.
Writers below are invoked only by a separately authorized local evaluator.
Held-out question/reference/canary contents are absent from these metadata
records; any detailed pipeline events must live in the owner's sealed lane.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
import re
from threading import Lock
from typing import Mapping
from uuid import uuid4

from ..contracts import ExecutionMode, FailureClass, Outcome, OutcomeStatus, ReasonCode, StoppingLayer
from ..errors import ConfigurationError, SourceReadError
from .cases import Case, require_sha256
from .holdout import CasePartition, HoldoutExposure


@dataclass(frozen=True, slots=True)
class UnavailableInput:
    field: str
    reason: str


@dataclass(frozen=True, slots=True)
class RunFingerprints:
    fixture_dump_sha256: str | None = None
    access_matrix_sha256: str | None = None
    semantic_catalog_sha256: str | None = None
    prompt_template_sha256: str | None = None
    model_gguf_sha256: str | None = None
    llama_launcher_sha256: str | None = None
    parser_review_sha256: str | None = None
    validator_source_sha256: str | None = None
    case_set_sha256: str | None = None
    source_schema_sha256: str | None = None
    resource_measurements_sha256: str | None = None

    def __post_init__(self) -> None:
        for field, value in asdict(self).items():
            if value is not None:
                require_sha256(value, field)

    @property
    def unavailable(self) -> tuple[UnavailableInput, ...]:
        return tuple(UnavailableInput(name, "Actual artifact fingerprint is unavailable.") for name, value in asdict(self).items() if value is None)


@dataclass(frozen=True, slots=True)
class RunSettings:
    prompt_version: int
    llama_cpp_build: str | None
    model_context_size: int | None
    model_threads: int | None
    sqlglot_version: str | None
    validator_revision: str | None
    validator_commit: str | None
    temperature: float
    seed: int
    max_tokens: int
    stop: tuple[str, ...]
    generation_timeout_seconds: float
    statement_timeout_seconds: float
    output_row_cap: int
    database_work_mem_kib: int | None
    database_temp_file_limit_kib: int | None
    model_memory_limit_mib: int | None
    baseline_reference: str | None
    exclusive_model_service_reference: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "stop", tuple(self.stop))
        if self.prompt_version not in (1, 2) or type(self.prompt_version) is not int:
            raise ConfigurationError("An explicit supported prompt version is required.")
        if self.temperature != 0.0 or type(self.seed) is not int or self.max_tokens != 300 or self.stop != (";",):
            raise ConfigurationError("The initial measured baseline uses greedy fixed-seed, 300-token semicolon decoding.")
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)):
            raise ConfigurationError("Temperature metadata must be numeric, not a boolean surrogate.")
        for name in ("model_context_size", "model_threads", "output_row_cap", "database_work_mem_kib", "model_memory_limit_mib"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                raise ConfigurationError("Actual run sizes/budgets must be positive integers or unavailable.")
        if self.database_temp_file_limit_kib is not None and (type(self.database_temp_file_limit_kib) is not int or self.database_temp_file_limit_kib < 0):
            raise ConfigurationError("The recorded database temporary-file budget cannot be unlimited.")
        for value in (self.generation_timeout_seconds, self.statement_timeout_seconds):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ConfigurationError("Actual timeout declarations must be finite and positive.")


@dataclass(frozen=True, slots=True)
class WarmupRecord:
    performed: bool
    scored: bool = False
    generation_ms: float | None = None
    token_count: int | None = None
    source_case_id: str | None = None
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.performed) is not bool or self.scored is not False:
            raise ConfigurationError("Warmup is always explicitly unscored.")
        if self.performed and (self.generation_ms is None or self.source_case_id is None):
            raise ConfigurationError("A performed warmup requires actual duration and tuning source metadata.")


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    mode: ExecutionMode
    partition: CasePartition
    fingerprints: RunFingerprints
    settings: RunSettings
    warmup: WarmupRecord
    unavailable_inputs: tuple[UnavailableInput, ...] = ()
    parent_run_id: str | None = None
    change_reference: str | None = None
    never_execute_case_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CaseRunRecord:
    run_id: str
    mode: ExecutionMode
    partition: CasePartition
    case_id: str
    case_set: str
    persona: str
    principal_id: int
    expected_outcome: str
    status: OutcomeStatus
    stopping_layer: StoppingLayer
    reason_code: ReasonCode
    failure_class: FailureClass | None
    triage_pending: bool
    assessment: bool | None
    assessment_reason: str
    leakage_observed: bool | None
    latency_ms: float | None
    result_truncated: bool
    row_count: int
    row_cap: int
    candidate_sha256: str | None
    filtered_ddl_sha256: str | None
    semantic_block_sha256: str | None
    warmup: bool = False
    request_id: str | None = None
    as_of_date: str | None = None


def case_record(
    case: Case, outcome: Outcome, *, run_id: str, partition: CasePartition,
    assessment: bool | None, assessment_reason: str, leakage_observed: bool | None,
    failure_class: FailureClass | None, triage_pending: bool, candidate_sha256: str | None,
) -> CaseRunRecord:
    persona = outcome.request_context.input_request.persona
    return CaseRunRecord(
        run_id, outcome.request_context.input_request.mode, partition, case.id, case.set.value,
        case.persona, persona.principal_id, case.expected_outcome.value,
        outcome.status, outcome.stopping_layer, outcome.reason_code, failure_class, triage_pending,
        assessment, assessment_reason, leakage_observed, outcome.timings.total_ms,
        outcome.truncated, len(outcome.rows), outcome.row_cap, candidate_sha256,
        outcome.fingerprints.filtered_ddl, outcome.fingerprints.semantic, False, outcome.request_context.request_id,
        outcome.request_context.input_request.as_of_date.isoformat(),
    )


def new_run_id() -> str:
    """Future UTC metadata clock only; never supplies a business as-of date."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex[:12]


def _json_value(value: object) -> object:
    if value is None or type(value) in {str, int, bool}:
        return value
    if isinstance(value, Enum):
        return value.value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in {tuple, list}:
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping) and all(type(key) is str for key in value):
        return {key: _json_value(item) for key, item in value.items()}
    raise ConfigurationError("Internal evaluation metadata contains an unsupported object.")


_WRITE_LOCK = Lock()


def validate_case_accounting(values: Mapping[str, int]) -> None:
    required = {"total_cases", "scored_cases", "unscored_cases", "pending_triage_cases", "unsubmitted_cases", "pending_cases"}
    if not isinstance(values, Mapping) or set(values) != required or any(type(value) is not int or value < 0 for value in values.values()):
        raise ConfigurationError("Case accounting requires exact nonnegative integer counts.")
    if values["total_cases"] != values["scored_cases"] + values["unscored_cases"] + values["unsubmitted_cases"]:
        raise ConfigurationError("Scored, unscored and unsubmitted cases must reconcile to the total.")
    if values["pending_cases"] != values["unscored_cases"] + values["unsubmitted_cases"] or values["pending_triage_cases"] > values["scored_cases"]:
        raise ConfigurationError("Pending triage is a subset of scored failures, not additional pending cases.")


class EvaluationRecordWriter:
    """Metadata-only local writer; construction creates nothing.

    A HOLDOUT writer must use a distinct owner-controlled sealed directory;
    it never exports question, reference SQL, canaries or comparison rows.
    Restricting access to the sealed directory remains the local owner's duty.
    """

    def __init__(self, root: Path, run_id: str, partition: CasePartition, *, sealed_root: Path | None = None) -> None:
        self.root = Path(root).resolve()
        if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id) is None or type(partition) is not CasePartition:
            raise ConfigurationError("Run record paths require an actual bounded ID and typed partition.")
        self.run_id, self.partition = run_id, partition
        if partition is CasePartition.HOLDOUT:
            if sealed_root is None:
                raise ConfigurationError("Holdout metadata requires its explicit sealed local root.")
            base = Path(sealed_root).resolve()
            if base == self.root or not base.is_relative_to(self.root):
                raise ConfigurationError("The sealed record root must be a distinct directory inside the project.")
        else:
            base = self.root / "logs" / "evaluation"
        self.directory = base / run_id

    def _append(self, filename: str, values: Mapping[str, object]) -> None:
        path = self.directory / filename
        payload = (json.dumps(_json_value(values), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")
        if len(payload) > 4_194_304:
            raise ConfigurationError("The evaluation metadata event exceeds its byte bound.")
        with _WRITE_LOCK:
            try:
                if not path.resolve().is_relative_to(self.root):
                    raise ConfigurationError("Evaluation record paths cannot leave the project.")
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.resolve().is_relative_to(self.root):
                    raise ConfigurationError("Evaluation record paths cannot leave the project.")
                with path.open("ab", buffering=0) as stream:
                    if stream.write(payload) != len(payload):
                        raise OSError("Evaluation metadata append was incomplete.")
                    # An exposure callback must finish its durable metadata
                    # append before the holdout authority invokes any reader.
                    os.fsync(stream.fileno())
            except OSError as exc:
                raise SourceReadError("The internal local evaluation record could not be appended.") from exc

    def write_run(self, record: RunRecord) -> None:
        if type(record) is not RunRecord or record.run_id != self.run_id or record.partition is not self.partition:
            raise ConfigurationError("The run metadata is bound to a different writer.")
        self._append("runs.jsonl", {"record_type": "RUN", **asdict(record)})

    def write_case(self, record: CaseRunRecord) -> None:
        if type(record) is not CaseRunRecord or record.run_id != self.run_id or record.partition is not self.partition or record.warmup:
            raise ConfigurationError("Scored case metadata must match this run and cannot be warmup.")
        self._append("cases.jsonl", {"record_type": "CASE", **asdict(record)})

    def write_summary(self, summary: Mapping[str, object]) -> None:
        # Caller supplies only counts/percentages and changed IDs/observations;
        # this function does not compute or invent measured outcomes.
        allowed = {"accuracy", "leakage", "attribution", "changed_cases", "complete", "source_limits", "unavailable_inputs", "unsubmitted_case_ids", "accounting"}
        if set(summary) - allowed:
            raise ConfigurationError("Summary fields cannot contain question/reference/canary payloads.")
        if "accounting" in summary:
            values = summary["accounting"]
            if not isinstance(values, Mapping):
                raise ConfigurationError("Case accounting must be explicit metadata.")
            validate_case_accounting(values)
            accuracy = summary.get("accuracy")
            if isinstance(accuracy, Mapping) and (
                any(accuracy.get(key) != values[field] for key, field in (("scored", "scored_cases"), ("unscored", "unscored_cases"), ("pending_triage_count", "pending_triage_cases")))
                or accuracy.get("total") != values["total_cases"] - values["unsubmitted_cases"]
                or type(accuracy.get("failed")) is not int or values["pending_triage_cases"] > accuracy["failed"]
            ):
                raise ConfigurationError("Summary accounting disagrees with its actual accuracy histogram.")
        self._append("summary.jsonl", {"record_type": "SUMMARY", "run_id": self.run_id, **summary})

    def record_exposure(self, exposure: HoldoutExposure) -> None:
        if type(exposure) is not HoldoutExposure or self.partition is not CasePartition.HOLDOUT or exposure.run_id != self.run_id:
            raise ConfigurationError("Exposure metadata requires this sealed boundary writer.")
        self._append("exposures.jsonl", {"record_type": "HOLDOUT_EXPOSURE", **asdict(exposure)})

    def append_project_log(self, record: RunRecord, *, scored_cases: int, pending_cases: int, accounting: Mapping[str, int] | None = None) -> None:
        """Future brief actual run metadata, never a source-only progress claim."""
        if record.run_id != self.run_id or record.partition is not self.partition:
            raise ConfigurationError("Project-log metadata must match the completed local run.")
        if any(type(value) is not int or value < 0 for value in (scored_cases, pending_cases)):
            raise ConfigurationError("Project-log counts must be nonnegative integers.")
        details = ""
        if accounting is not None:
            validate_case_accounting(accounting)
            if scored_cases != accounting["scored_cases"] or pending_cases != accounting["pending_cases"]:
                raise ConfigurationError("Project-log counts disagree with run accounting.")
            details = (f"total cases={accounting['total_cases']}, unscored cases={accounting['unscored_cases']}, "
                       f"unsubmitted cases={accounting['unsubmitted_cases']}, pending triage cases={accounting['pending_triage_cases']}; ")
        # Sealed runs expose metadata only, never case IDs or content here.
        text = (
            f"\n- Run {record.run_id}: {record.mode.value}, {record.partition.value}, "
            f"prompt v{record.settings.prompt_version}; scored cases={scored_cases}, "
            f"pending cases={pending_cases}; {details}warmup performed={record.warmup.performed}. "
            f"Case-set SHA-256={record.fingerprints.case_set_sha256 or 'unavailable'}.\n"
        )
        path = self.root / "PROJECT_LOG.md"
        with _WRITE_LOCK:
            try:
                if not path.resolve().is_relative_to(self.root):
                    raise ConfigurationError("The project log cannot leave the project workspace.")
                with path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(text)
            except OSError as exc:
                raise SourceReadError("The local project run metadata could not be appended.") from exc
