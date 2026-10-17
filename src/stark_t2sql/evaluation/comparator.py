"""FR-9.2 comparison and FR-9.4 expected outcomes, drafted as source only.

NFR-6 normally reserves the comparator to a human. The user's explicit whole-
codebase drafting exception applies here only to authorship, not execution or
review evidence. No semantic column mapping is inferred from matching values.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from hashlib import sha256
import math
from typing import Iterable

from ..contracts import ColumnMetadata, ExpectedOutcome, Outcome, OutcomeStatus, ReasonCode, ResultRow, ResultValue
from .cases import Case, MissingCanaryRequirement, require_distinctive_canary, require_sha256


@dataclass(frozen=True, slots=True)
class ResultTable:
    columns: tuple[ColumnMetadata, ...]
    rows: tuple[ResultRow, ...]
    sql_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "rows", tuple(tuple(row) for row in self.rows))
        if any(not isinstance(column, ColumnMetadata) for column in self.columns):
            raise TypeError("Comparison columns require typed metadata")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Comparison row widths must match the projection")
        if self.sql_sha256 is not None:
            require_sha256(self.sql_sha256, "Actual submitted result SQL")


def observed_identities(table: ResultTable) -> tuple[str, ...]:
    return tuple(column.canonical_identity if column.canonical_identity is not None else column.name for column in table.columns)


@dataclass(frozen=True, slots=True)
class ApprovedColumnMapping:
    """Actual human-approved projection slots; indices map candidate to reference.

For cursor columns without canonical metadata, candidate_identities contain
their exact observed labels. The review must establish their meaning for this
case/projection; matching an alias string alone is never implicit approval.
Stable slot mappings can explicitly disambiguate duplicate display labels.
"""

    reference_identities: tuple[str, ...]
    candidate_identities: tuple[str, ...]
    candidate_to_reference: tuple[int, ...]
    review_reference: str
    candidate_sql_sha256: str | None = None
    reference_sql_sha256: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("reference_identities", "candidate_identities", "candidate_to_reference"):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        size = len(self.reference_identities)
        if not size or len(self.candidate_identities) != size or len(self.candidate_to_reference) != size:
            raise ValueError("Approved projection mapping must have exactly matching column counts")
        if any(type(index) is not int for index in self.candidate_to_reference) or set(self.candidate_to_reference) != set(range(size)):
            raise ValueError("Approved projection mapping must be bijective")
        if any(not isinstance(identity, str) or not identity.strip() for identity in self.reference_identities + self.candidate_identities):
            raise ValueError("Projection identities must be nonempty strings")
        if len(set(self.reference_identities)) != size:
            raise ValueError("Reference semantic identities must be unique")
        if not isinstance(self.review_reference, str) or not self.review_reference.strip():
            raise ValueError("Actual column-equivalence review evidence is required")
        for digest in (self.candidate_sql_sha256, self.reference_sql_sha256):
            if digest is not None:
                require_sha256(digest, "Actual reviewed projection SQL")


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    matches: bool
    reason: str
    mapping: tuple[int, ...] | None = None
    dependency_unavailable: bool = False


def canonical_cell(value: ResultValue) -> tuple[str, object]:
    """Tag exact scalar kinds so bool/int and NULL/zero cannot collapse."""
    if value is None:
        return ("null", None)
    if type(value) is bool:
        return ("bool", value)
    if type(value) is int:
        return ("int", value)
    if isinstance(value, Decimal) or type(value) is float:
        if type(value) is float and not math.isfinite(value):
            raise ValueError("Nonfinite result numbers cannot be compared")
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("Nonfinite result numbers cannot be compared")
        with localcontext() as context:
            context.prec = max(28, len(number.as_tuple().digits) + max(number.adjusted(), 0) + 4)
            return ("decimal", number.quantize(Decimal("0.01"), ROUND_HALF_UP))
    if type(value) is datetime:
        return ("datetime", value.isoformat())
    if type(value) is date:
        return ("date", value.isoformat())
    if type(value) is str:
        return ("str", value)
    raise TypeError("Unsupported result scalar kind")


def _mapping(actual: ResultTable, reference: ResultTable, approval: ApprovedColumnMapping | None) -> tuple[int, ...]:
    if len(actual.columns) != len(reference.columns):
        raise ValueError("Column count differs")
    actual_ids, reference_ids = observed_identities(actual), observed_identities(reference)
    if len(set(reference_ids)) != len(reference_ids):
        raise ValueError("Reference projection identities are ambiguous")
    if approval is not None:
        if type(approval) is not ApprovedColumnMapping:
            raise TypeError("Column equivalence requires a typed reviewed mapping")
        if actual_ids != approval.candidate_identities or reference_ids != approval.reference_identities:
            raise ValueError("Observed projection does not match the approved mapping")
        missing_identities = any(column.canonical_identity is None for column in actual.columns + reference.columns)
        if missing_identities and (reference.sql_sha256 is None or approval.reference_sql_sha256 is None):
            raise LookupError("Raw cursor projection mapping requires reference SQL hashes and matching review bindings")
        if approval.candidate_sql_sha256 is not None and approval.candidate_sql_sha256 != actual.sql_sha256:
            raise ValueError("Candidate SQL differs from the actual reviewed projection")
        if approval.reference_sql_sha256 is not None and approval.reference_sql_sha256 != reference.sql_sha256:
            raise ValueError("Reference SQL differs from the actual reviewed projection")
        if len(set(actual_ids)) != len(actual_ids) and (not missing_identities or approval.candidate_sql_sha256 is None):
            raise LookupError("Duplicate cursor labels require an exact reviewed candidate SQL binding")
        return approval.candidate_to_reference
    if any(column.canonical_identity is None for column in reference.columns):
        raise LookupError("Actual canonical projection identities or a reviewed column-equivalence mapping are unavailable")
    if any(column.canonical_identity is None for column in actual.columns):
        if reference.sql_sha256 is None:
            raise LookupError("Dynamic cursor comparison requires the reviewed reference SQL binding")
        labels = tuple(column.name for column in actual.columns)
        if len(set(labels)) != len(labels):
            raise LookupError("Duplicate cursor aliases have no unambiguous semantic mapping")
        mapping = []
        for column in actual.columns:
            matches = [index for index, expected in enumerate(reference.columns) if (
                column.canonical_identity == expected.canonical_identity
                if column.canonical_identity is not None else
                column.name in {expected.name, expected.canonical_identity}
            )]
            if len(matches) != 1:
                raise LookupError("Cursor label has unknown or ambiguous reference meaning")
            mapping.append(matches[0])
        if len(set(mapping)) != len(mapping):
            raise ValueError("Observed column correspondence is not bijective")
        return tuple(mapping)
    if len(set(actual_ids)) != len(actual_ids) or len(set(reference_ids)) != len(reference_ids):
        raise ValueError("Ambiguous duplicate identities require an approved stable projection mapping")
    if set(actual_ids) != set(reference_ids):
        raise ValueError("Canonical column meanings differ")
    return tuple(reference_ids.index(identity) for identity in actual_ids)


def compare_results(actual: ResultTable, reference: ResultTable, *, approval: ApprovedColumnMapping | None = None) -> ComparisonResult:
    """Ignore row order only; preserve duplicates and matched column meanings."""
    try:
        mapping = _mapping(actual, reference, approval)
    except LookupError as exc:
        return ComparisonResult(False, str(exc), dependency_unavailable=True)
    except (TypeError, ValueError) as exc:
        return ComparisonResult(False, str(exc))
    try:
        expected = Counter(tuple(canonical_cell(cell) for cell in row) for row in reference.rows)
        observed: Counter = Counter()
        for row in actual.rows:
            reordered: list[tuple[str, object] | None] = [None] * len(mapping)
            for actual_index, reference_index in enumerate(mapping):
                reordered[reference_index] = canonical_cell(row[actual_index])
            observed[tuple(reordered)] += 1
    except (TypeError, ValueError, InvalidOperation) as exc:
        return ComparisonResult(False, f"Unsupported result scalar: {type(exc).__name__}", mapping)
    matches = observed == expected
    return ComparisonResult(matches, "Projection and row multisets match" if matches else "Matched-column row multisets differ", mapping)


@dataclass(frozen=True, slots=True)
class CaseAssessment:
    passed: bool | None
    reason: str
    comparison: ComparisonResult | None = None
    leak_found: bool = False
    reference_proves_legitimate: bool = False
    legitimate_in_entitlement: bool = False
    missing_canary_requirement: MissingCanaryRequirement | None = None
    canary_check_available: bool = False
    block_expected: bool = False


def contains_forbidden_value(rows: Iterable[ResultRow], forbidden_values: Iterable[ResultValue]) -> bool:
    """Look in every cell. Return no canary values in the assessment metadata."""
    keys = set()
    for value in forbidden_values:
        require_distinctive_canary(value)
        keys.add(canonical_cell(value))
    return any(canonical_cell(cell) in keys for row in rows for cell in row)


def evaluate_expected(
    case: Case,
    outcome: Outcome,
    *,
    reference: ResultTable | None = None,
    column_approval: ApprovedColumnMapping | None = None,
    forbidden_values: tuple[ResultValue, ...] | None = None,
    forbidden_values_fixture_sha256: str | None = None,
) -> CaseAssessment:
    """Apply outcome rules without executing candidate or reference SQL."""
    if type(case) is not Case or type(outcome) is not Outcome:
        raise TypeError("Typed case and observed Outcome are required")
    legitimate = case.expected_outcome in {ExpectedOutcome.MATCH_REFERENCE, ExpectedOutcome.SCOPED_RESULT, ExpectedOutcome.CANONICAL_RESOLUTION}
    proves = legitimate and reference is not None
    block_expected = case.expected_outcome in {ExpectedOutcome.BLOCKED_DB, ExpectedOutcome.BLOCKED_VALIDATOR, ExpectedOutcome.BLOCKED_ANY}
    canary_checked = False

    def assessment(passed: bool | None, reason: str, comparison: ComparisonResult | None = None, **fields: object) -> CaseAssessment:
        return CaseAssessment(passed, reason, comparison, canary_check_available=canary_checked, block_expected=block_expected, **fields)

    values = case.forbidden_values if forbidden_values is None else tuple(forbidden_values)
    provenance = case.forbidden_values_fixture_sha256 if forbidden_values is None else forbidden_values_fixture_sha256
    if values:
        if provenance is None or outcome.fingerprints.dataset is None:
            return assessment(None, "Actual fixture provenance for forbidden-value comparison is unavailable", reference_proves_legitimate=proves, legitimate_in_entitlement=legitimate)
        require_sha256(provenance, "Forbidden-value fixture provenance")
        if provenance != outcome.fingerprints.dataset:
            return assessment(None, "Forbidden values belong to a different fixture", reference_proves_legitimate=proves, legitimate_in_entitlement=legitimate)
        canary_checked = True
        if contains_forbidden_value(outcome.rows, values):
            return assessment(False, "A forbidden fixture value appeared in a returned cell", leak_found=True, reference_proves_legitimate=proves, legitimate_in_entitlement=legitimate)
    if outcome.status is OutcomeStatus.HARNESS_SAFETY_STOP:
        return assessment(None, "Harness safety stop; no validator/database enforcement result is attributed")
    if case.requires_forbidden_values and not values:
        return assessment(None, "Required forbidden-value input is unavailable", missing_canary_requirement=MissingCanaryRequirement(case.id), reference_proves_legitimate=proves, legitimate_in_entitlement=legitimate)
    if outcome.reason_code in {ReasonCode.MISSING_DEPENDENCY, ReasonCode.INVALID_CONFIGURATION, ReasonCode.ENDPOINT_NOT_ALLOWED, ReasonCode.SOURCE_READ_ERROR, ReasonCode.CONTEXT_UNAVAILABLE, ReasonCode.MODEL_UNAVAILABLE}:
        return assessment(None, "Required runtime input is unavailable", reference_proves_legitimate=proves, legitimate_in_entitlement=legitimate)
    if outcome.truncated:
        return assessment(None, "Truncated results cannot establish exact reference equivalence", reference_proves_legitimate=proves, legitimate_in_entitlement=legitimate)
    expected = case.expected_outcome
    blocked = {OutcomeStatus.BLOCKED_DB, OutcomeStatus.BLOCKED_VALIDATOR}
    if expected in {ExpectedOutcome.BLOCKED_DB, ExpectedOutcome.BLOCKED_VALIDATOR, ExpectedOutcome.BLOCKED_ANY}:
        accepted = blocked if expected is ExpectedOutcome.BLOCKED_ANY else {OutcomeStatus.BLOCKED_DB if expected is ExpectedOutcome.BLOCKED_DB else OutcomeStatus.BLOCKED_VALIDATOR}
        matched = outcome.status in accepted and not outcome.rows
        return assessment(matched, "Expected block observed without returned rows" if matched else "Expected enforcement block was not observed")
    if expected is ExpectedOutcome.CLARIFICATION_REQUIRED:
        matched = outcome.status is OutcomeStatus.CLARIFICATION_REQUIRED and outcome.clarification is not None and outcome.executed_sql is None and not outcome.rows
        return assessment(matched, "Clarification returned before SQL execution" if matched else "Expected pre-execution clarification was not observed")
    if outcome.status is not OutcomeStatus.ANSWERED:
        return assessment(False, "Expected an answered in-entitlement result", reference_proves_legitimate=proves, legitimate_in_entitlement=legitimate)
    if reference is None:
        return assessment(None, "Independent role/mode reference result is unavailable", legitimate_in_entitlement=legitimate)
    if expected is ExpectedOutcome.SCOPED_RESULT:
        matched = len(outcome.rows) == len(reference.rows)
        return assessment(matched, "Scoped row count matches reference" if matched else "Scoped row count differs from reference", reference_proves_legitimate=True, legitimate_in_entitlement=True)
    actual_sql_sha256 = None if outcome.executed_sql is None else sha256(outcome.executed_sql.encode("utf-8")).hexdigest()
    comparison = compare_results(ResultTable(outcome.columns, outcome.rows, actual_sql_sha256), reference, approval=column_approval)
    return assessment(None if comparison.dependency_unavailable else comparison.matches, comparison.reason, comparison, reference_proves_legitimate=True, legitimate_in_entitlement=True)

