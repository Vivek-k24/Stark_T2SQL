"""Vocabulary and canonical metric interfaces consumed by later pipeline sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from ..contracts import Clarification
from ..errors import ConfigurationError
from .models import ColumnRef, RelationshipDefinition, TemporalRule


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class VocabularyResolution:
    status: ResolutionStatus
    concept_ids: tuple[str, ...]
    clarification: Clarification | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "concept_ids", tuple(self.concept_ids))
        if not isinstance(self.status, ResolutionStatus):
            raise ConfigurationError("A vocabulary resolution requires a defined status.")
        if self.status is ResolutionStatus.CLARIFICATION_REQUIRED:
            if not isinstance(self.clarification, Clarification) or self.concept_ids:
                raise ConfigurationError("Clarification must have a safe question and no selected meaning.")
        elif self.clarification is not None:
            raise ConfigurationError("A resolved meaning cannot include an ambiguity question.")


@dataclass(frozen=True, slots=True)
class MetricContract:
    """Trusted canonical fragments, not executable model queries or measured answers."""

    metric_id: str
    expression: str
    grain: tuple[ColumnRef, ...]
    filters: tuple[str, ...]
    relationships: tuple[RelationshipDefinition, ...]
    aggregation: str
    null_handling: str
    units: str
    temporal_rules: tuple[TemporalRule, ...]
    as_of_date: date

    def __post_init__(self) -> None:
        for name in ("grain", "filters", "relationships", "temporal_rules"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if type(self.as_of_date) is not date:
            raise ConfigurationError("Canonical metrics require an explicit date.")
