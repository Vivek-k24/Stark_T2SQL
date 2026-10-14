"""Typed immutable governed definitions, with no fixture or numeric answer data."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..contracts import RowScopeKind
from ..errors import ConfigurationError
from ..policy.loader import require_identifier


def _tuples(instance: object, names: tuple[str, ...]) -> None:
    for name in names:
        object.__setattr__(instance, name, tuple(getattr(instance, name)))


@dataclass(frozen=True, slots=True)
class ColumnRef:
    table: str
    column: str

    def __post_init__(self) -> None:
        require_identifier(self.table, label="semantic table")
        require_identifier(self.column, label="semantic column")

    def __str__(self) -> str:
        return f"{self.table}.{self.column}"


@dataclass(frozen=True, slots=True)
class RelationshipDefinition:
    id: str
    source: ColumnRef
    target: ColumnRef
    cardinality: str


@dataclass(frozen=True, slots=True)
class EntityDefinition:
    id: str
    name: str
    kind: str
    description: str
    aliases: tuple[str, ...]
    source_tables: tuple[str, ...]
    source_columns: tuple[ColumnRef, ...]
    relationship_ids: tuple[str, ...]
    filters: tuple[str, ...]
    temporal_rule_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _tuples(self, ("aliases", "source_tables", "source_columns", "relationship_ids", "filters", "temporal_rule_ids"))


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    id: str
    name: str
    description: str
    aliases: tuple[str, ...]
    expression: str
    grain: tuple[ColumnRef, ...]
    source_tables: tuple[str, ...]
    source_columns: tuple[ColumnRef, ...]
    relationship_ids: tuple[str, ...]
    filters: tuple[str, ...]
    aggregation: str
    null_handling: str
    units: str
    temporal_rule_ids: tuple[str, ...]
    allowed_scopes: tuple[RowScopeKind, ...]
    dependencies: tuple[str, ...]
    pending_roles: tuple[str, ...]

    def __post_init__(self) -> None:
        _tuples(self, ("aliases", "grain", "source_tables", "source_columns", "relationship_ids", "filters",
            "temporal_rule_ids", "allowed_scopes", "dependencies", "pending_roles"))


@dataclass(frozen=True, slots=True)
class TemporalRule:
    id: str
    description: str
    source_tables: tuple[str, ...]
    source_columns: tuple[ColumnRef, ...]
    predicate: str
    selection: str

    def __post_init__(self) -> None:
        _tuples(self, ("source_tables", "source_columns"))


@dataclass(frozen=True, slots=True)
class AmbiguityDefinition:
    term: str
    targets: tuple[str, ...]

    def __post_init__(self) -> None:
        _tuples(self, ("targets",))


@dataclass(frozen=True, slots=True)
class SemanticCatalog:
    version: str
    entities: Mapping[str, EntityDefinition]
    metrics: Mapping[str, MetricDefinition]
    relationships: Mapping[str, RelationshipDefinition]
    temporal_rules: Mapping[str, TemporalRule]
    ambiguities: tuple[AmbiguityDefinition, ...]
    sha256: str

    def __post_init__(self) -> None:
        for name in ("entities", "metrics", "relationships", "temporal_rules"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        _tuples(self, ("ambiguities",))
        if (
            not isinstance(self.sha256, str) or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise ConfigurationError("A catalog requires the actual source SHA-256 fingerprint.")

    def concept(self, concept_id: str) -> EntityDefinition | MetricDefinition:
        value = self.entities.get(concept_id) or self.metrics.get(concept_id)
        if value is None:
            raise ConfigurationError(f"Unknown governed concept: {concept_id}")
        return value
