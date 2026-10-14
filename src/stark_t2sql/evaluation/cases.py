"""Immutable FR-9 case source contracts; no case payloads are read at import.

Fixture canaries are supplied only by a later fixture-bound computation. This
module defines neither employee records nor held-out questions or answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
import math

from ..contracts import ExpectedOutcome, ResultValue


class CaseSet(str, Enum):
    ACCURACY = "accuracy"
    AUTHORIZATION = "authorization"
    ADVERSARIAL_SQL = "adversarial_sql"
    ADVERSARIAL_NL = "adversarial_nl"
    AMBIGUITY = "ambiguity"
    REGRESSIONS = "regressions"


def require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} requires an actual lowercase SHA-256 digest")


def require_distinctive_canary(value: ResultValue) -> None:
    """Exclude small integer IDs/counts and nondistinctive null/boolean cells."""
    if isinstance(value, str) and value.strip():
        return
    if isinstance(value, Decimal) and value.is_finite() and abs(value) >= Decimal("100"):
        return
    if type(value) is float and math.isfinite(value) and abs(Decimal(str(value))) >= Decimal("100"):
        return
    raise ValueError("Canaries must be distinctive fixture text or exact salary-like decimal values, never small integers")


@dataclass(frozen=True, slots=True)
class MissingCanaryRequirement:
    """Unresolved fixture input, never evidence that a security case has no leak."""

    case_id: str
    reason: str = "Distinctive forbidden values must be computed from the actual fixture before this case can be scored."


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    set: CaseSet
    persona: str
    as_of_date: date
    expected_outcome: ExpectedOutcome
    question: str | None = None
    sql: str | None = None
    reference_sql: str | None = None
    category: str | None = None
    forbidden_values: tuple[ResultValue, ...] = ()
    notes: tuple[str, ...] = ()
    forbidden_values_fixture_sha256: str | None = None
    requires_forbidden_values: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "forbidden_values", tuple(self.forbidden_values))
        object.__setattr__(self, "notes", tuple(self.notes))
        if not isinstance(self.id, str) or not self.id.strip() or self.id != self.id.strip():
            raise ValueError("Case IDs must be immutable nonempty exact strings")
        if not isinstance(self.set, CaseSet) or not isinstance(self.expected_outcome, ExpectedOutcome):
            raise TypeError("Case set and expected outcome require their typed vocabularies")
        if not isinstance(self.persona, str) or not self.persona.strip() or type(self.as_of_date) is not date:
            raise ValueError("A persona selection and explicit as-of date are required")
        texts = (self.question, self.sql)
        if sum(text is not None for text in texts) != 1 or any(text is not None and (not isinstance(text, str) or not text.strip()) for text in texts):
            raise ValueError("A case requires exactly one nonempty question or direct SQL input")
        if self.reference_sql is not None and (not isinstance(self.reference_sql, str) or not self.reference_sql.strip()):
            raise ValueError("Reference SQL must be nonempty when supplied")
        if self.expected_outcome in {ExpectedOutcome.MATCH_REFERENCE, ExpectedOutcome.SCOPED_RESULT, ExpectedOutcome.CANONICAL_RESOLUTION} and self.reference_sql is None:
            raise ValueError("This expected outcome requires independently authored reference SQL")
        if self.category is not None and (not isinstance(self.category, str) or not self.category.strip()):
            raise ValueError("Case categories must be nonempty text")
        if any(not isinstance(note, str) or not note.strip() for note in self.notes):
            raise ValueError("Case notes must be nonempty text")
        if type(self.requires_forbidden_values) is not bool:
            raise TypeError("Canary requirement must be an explicit boolean")
        if self.forbidden_values_fixture_sha256 is not None:
            require_sha256(self.forbidden_values_fixture_sha256, "Canary fixture provenance")
        if self.forbidden_values and self.forbidden_values_fixture_sha256 is None:
            raise ValueError("Actual fixture provenance is required for supplied canaries")
        for value in self.forbidden_values:
            require_distinctive_canary(value)

