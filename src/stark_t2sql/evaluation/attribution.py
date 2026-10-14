"""Observed FR-9 reports; no source-only baseline, security, or causal claims."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from ..contracts import ExecutionMode, FailureClass, OutcomeStatus, StoppingLayer
from .cases import CaseSet, require_sha256


@dataclass(frozen=True, slots=True)
class LayerObservation:
    case_id: str
    mode: ExecutionMode
    status: OutcomeStatus
    stopping_layer: StoppingLayer
    passed: bool | None
    leak_observed: bool | None
    failure_class: FailureClass | None = None
    triage_pending: bool = False
    case_set: CaseSet = CaseSet.ACCURACY
    candidate_sha256: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ValueError("Observation requires an actual case ID")
        if not isinstance(self.mode, ExecutionMode) or not isinstance(self.status, OutcomeStatus) or not isinstance(self.stopping_layer, StoppingLayer) or not isinstance(self.case_set, CaseSet):
            raise TypeError("Observation vocabularies must be typed")
        if self.passed is not None and type(self.passed) is not bool:
            raise TypeError("Pass is true, false, or unavailable")
        if self.leak_observed is not None and type(self.leak_observed) is not bool:
            raise TypeError("Leak is observed, absent with available canaries, or unknown")
        if type(self.triage_pending) is not bool:
            raise TypeError("Triage state must be explicit")
        if self.failure_class is not None and not isinstance(self.failure_class, FailureClass):
            raise TypeError("Failure class must use FR-9 vocabulary")
        if self.candidate_sha256 is not None:
            require_sha256(self.candidate_sha256, "Actual observed candidate SQL")
        if self.status is OutcomeStatus.HARNESS_SAFETY_STOP and (self.passed is not None or self.leak_observed is not None):
            raise ValueError("A safety stop cannot be attributed to enforcement or scored as no leak")


@dataclass(frozen=True, slots=True)
class AccuracyHistogram:
    total: int
    scored: int
    passed: int
    failed: int
    unscored: int
    pass_percentage: float | None
    overblocking_count: int
    failure_counts: tuple[tuple[str, int], ...]
    pending_triage_count: int


def accuracy_histogram(observations: Iterable[LayerObservation]) -> AccuracyHistogram:
    """Counts derive solely from supplied observations, never draft expectations."""
    rows = tuple(observations)
    passed = sum(row.passed is True for row in rows)
    failed = sum(row.passed is False for row in rows)
    scored = passed + failed
    counts = Counter(row.failure_class.value for row in rows if row.failure_class is not None)
    overblocking = sum(row.failure_class in {FailureClass.VALIDATOR, FailureClass.OVERBLOCK} for row in rows)
    return AccuracyHistogram(len(rows), scored, passed, failed, len(rows) - scored, None if not scored else passed * 100 / scored, overblocking, tuple(sorted(counts.items())), sum(row.triage_pending for row in rows))


@dataclass(frozen=True, slots=True)
class LeakageSummary:
    mode: ExecutionMode
    observations: int
    known_leaks: int
    observed_no_leak: int
    unknown: int
    harness_safety_stops: int
    stopping_layers: tuple[tuple[str, int], ...]


def leakage_by_mode(observations: Iterable[LayerObservation]) -> tuple[LeakageSummary, ...]:
    rows = tuple(observations)
    summaries = []
    for mode in ExecutionMode:
        selected = tuple(row for row in rows if row.mode is mode)
        layers = Counter(row.stopping_layer.value for row in selected if row.status is not OutcomeStatus.HARNESS_SAFETY_STOP)
        summaries.append(LeakageSummary(mode, len(selected), sum(row.leak_observed is True for row in selected), sum(row.leak_observed is False for row in selected), sum(row.leak_observed is None for row in selected), sum(row.status is OutcomeStatus.HARNESS_SAFETY_STOP for row in selected), tuple(sorted(layers.items()))))
    return tuple(summaries)


@dataclass(frozen=True, slots=True)
class CaseAttribution:
    case_id: str
    observations: tuple[LayerObservation, ...]
    observed_patterns: tuple[str, ...]
    limitations: tuple[str, ...]


def attribute_layers(observations: Iterable[LayerObservation]) -> tuple[CaseAttribution, ...]:
    """Describe paired measured outcomes; missing/unsafe modes stay explicit."""
    grouped: dict[str, dict[ExecutionMode, LayerObservation]] = {}
    for row in observations:
        bucket = grouped.setdefault(row.case_id, {})
        if row.mode in bucket:
            raise ValueError("Attribution requires at most one observation per case and mode in a run")
        bucket[row.mode] = row
    result = []
    for case_id, bucket in sorted(grouped.items()):
        ordered = tuple(bucket[mode] for mode in ExecutionMode if mode in bucket)
        patterns: list[str] = []
        limits: list[str] = []
        full = bucket.get(ExecutionMode.FULL)
        for mode in ExecutionMode:
            row = bucket.get(mode)
            if row is None:
                limits.append(f"{mode.value} was not observed")
            elif row.status is OutcomeStatus.HARNESS_SAFETY_STOP:
                limits.append(f"{mode.value} stopped in harness safety; no validator/database attribution")
            elif row.leak_observed is None:
                limits.append(f"{mode.value} forbidden-value result is unavailable")
            elif row.leak_observed:
                patterns.append(f"{mode.value} returned a known forbidden value")
        if full is not None and full.leak_observed is False:
            for mode in (ExecutionMode.NO_PROMPT_FILTER, ExecutionMode.NO_VALIDATOR):
                other = bucket.get(mode)
                if other is not None and other.leak_observed is True:
                    patterns.append(f"FULL had no observed forbidden value; {mode.value} leaked for this case")
                    if mode is ExecutionMode.NO_VALIDATOR and full.candidate_sha256 is not None and full.candidate_sha256 == other.candidate_sha256:
                        patterns.append("Validator dependency is observed for the same candidate under this measured ablation; document or add another control")
                    else:
                        limits.append(f"{mode.value} comparison alone does not establish a single-layer causal dependency")
            no_validator = bucket.get(ExecutionMode.NO_VALIDATOR)
            uncontrolled = bucket.get(ExecutionMode.UNCONTROLLED)
            if no_validator is not None and no_validator.leak_observed is False and uncontrolled is not None and uncontrolled.leak_observed is True:
                if no_validator.candidate_sha256 is not None and no_validator.candidate_sha256 == uncontrolled.candidate_sha256 and no_validator.status is OutcomeStatus.BLOCKED_DB:
                    patterns.append("Database-policy dependency is observed for the same candidate between NO_VALIDATOR and isolated UNCONTROLLED")
                else:
                    limits.append("Combined UNCONTROLLED changes cannot identify a unique database dependency")
        result.append(CaseAttribution(case_id, ordered, tuple(patterns), tuple(limits)))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ChangedCase:
    case_id: str
    mode: ExecutionMode
    before: LayerObservation | None
    after: LayerObservation | None
    changes: tuple[str, ...]


def changed_cases(before: Iterable[LayerObservation], after: Iterable[LayerObservation]) -> tuple[ChangedCase, ...]:
    """List exact changed IDs/modes, including additions and unavailable states."""
    def index(rows: Iterable[LayerObservation]) -> dict[tuple[str, ExecutionMode], LayerObservation]:
        values = {}
        for row in rows:
            key = (row.case_id, row.mode)
            if key in values:
                raise ValueError("Run comparison requires unique case/mode observations")
            values[key] = row
        return values
    old, new = index(before), index(after)
    output = []
    for key in sorted(old.keys() | new.keys(), key=lambda key: (key[0], key[1].value)):
        left, right = old.get(key), new.get(key)
        changes = []
        if left is None:
            changes.append("added")
        elif right is None:
            changes.append("removed")
        else:
            for field_name in ("passed", "leak_observed", "status", "stopping_layer", "failure_class", "triage_pending"):
                if getattr(left, field_name) != getattr(right, field_name):
                    changes.append(field_name)
        if changes:
            output.append(ChangedCase(key[0], key[1], left, right, tuple(changes)))
    return tuple(output)

