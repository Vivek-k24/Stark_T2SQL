"""Independent deterministic semantic block after exact entitlement projection.

Only complete, role-permitted definitions enter the role block. Permission
derivation is owned by semantic.entitlements, not duplicated here. Raw catalog
provenance and the exact emitted block fingerprint remain distinct. This file
does not resolve questions, assemble prompts, or communicate with services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from ..semantic.metrics import _bind_date

from ..db.catalog import SchemaSnapshot
from ..errors import ConfigurationError
from ..policy.loader import PolicyMatrix
from ..semantic.entitlements import filter_catalog_for_role
from ..semantic.models import ColumnRef, SemanticCatalog
from ..utils.fingerprints import sha256_context


@dataclass(frozen=True, slots=True)
class FilteredSemantic:
    catalog: SemanticCatalog
    text: str
    sha256: str
    catalog_sha256: str
    policy_sha256: str
    business_role: str | None


def _column(reference: ColumnRef) -> dict[str, str]:
    return {"table": reference.table, "column": reference.column}


def _columns(references: tuple[ColumnRef, ...]) -> list[dict[str, str]]:
    return [_column(reference) for reference in sorted(references, key=lambda ref: (ref.table, ref.column))]


def serialize_semantics(catalog: SemanticCatalog, *, as_of_date: date | None = None) -> str:
    """Serialize an already-governed projection; never include removed aliases.

    Stable mapping keys, definition IDs, aliases, source columns, relationships
    and ambiguity targets make identical supplied metadata byte-deterministic.
    Filter sequence remains author-defined; grain column order remains semantic.
    A catalog supplied directly to this pure serializer is not authorization.
    """
    if type(catalog) is not SemanticCatalog:
        raise ConfigurationError("A typed governed catalog is required for semantic context.")
    entities = []
    for identifier, entity in sorted(catalog.entities.items()):
        entities.append({
            "id": identifier, "name": entity.name, "kind": entity.kind,
            "description": entity.description, "aliases": sorted(entity.aliases),
            "source_tables": sorted(entity.source_tables),
            "source_columns": _columns(entity.source_columns),
            "relationship_ids": sorted(entity.relationship_ids),
            "filters": [_bind_date(f, as_of_date) if as_of_date is not None else f for f in entity.filters],
            "temporal_rule_ids": sorted(entity.temporal_rule_ids),
        })
    metrics = []
    for identifier, metric in sorted(catalog.metrics.items()):
        metrics.append({
            "id": identifier, "name": metric.name, "description": metric.description,
            "aliases": sorted(metric.aliases), "expression": _bind_date(metric.expression, as_of_date) if as_of_date is not None else metric.expression,
            "grain": [_column(reference) for reference in metric.grain],
            "source_tables": sorted(metric.source_tables),
            "source_columns": _columns(metric.source_columns),
            "relationship_ids": sorted(metric.relationship_ids),
            "filters": [_bind_date(f, as_of_date) if as_of_date is not None else f for f in metric.filters], "aggregation": metric.aggregation,
            "null_handling": metric.null_handling, "units": metric.units,
            "temporal_rule_ids": sorted(metric.temporal_rule_ids),
            "dependencies": sorted(metric.dependencies),
        })
    relationships = [
        {"id": identifier, "source": _column(relationship.source),
         "target": _column(relationship.target), "cardinality": relationship.cardinality}
        for identifier, relationship in sorted(catalog.relationships.items())
    ]
    temporal_rules = [
        {"id": identifier, "description": rule.description,
         "source_tables": sorted(rule.source_tables),
         "source_columns": _columns(rule.source_columns),
         "predicate": _bind_date(rule.predicate, as_of_date) if as_of_date is not None else rule.predicate, "selection": _bind_date(rule.selection, as_of_date) if as_of_date is not None else rule.selection}
        for identifier, rule in sorted(catalog.temporal_rules.items())
    ]
    ambiguities = [
        {"term": item.term, "targets": sorted(item.targets)}
        for item in sorted(catalog.ambiguities, key=lambda item: (item.term, item.targets))
    ]
    return json.dumps(
        {"catalog_version": catalog.version, "entities": entities, "metrics": metrics,
         "relationships": relationships, "temporal_rules": temporal_rules,
         "ambiguities": ambiguities},
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ) + "\n"


def compile_semantics(
    catalog: SemanticCatalog, matrix: PolicyMatrix,
    snapshot: SchemaSnapshot, business_role: str,
    *, as_of_date: date | None = None,
) -> FilteredSemantic:
    """Independently project and hash permissible semantic metadata.

    The full trusted snapshot is required by the semantic contract owner. An
    already-filtered physical DDL snapshot is insufficient for whole-catalog
    schema/policy drift validation and must not be mistaken for that input.
    """
    projected = filter_catalog_for_role(catalog, matrix, snapshot, business_role)
    text = serialize_semantics(projected, as_of_date=as_of_date)
    return FilteredSemantic(projected, text, sha256_context(text), catalog.sha256, matrix.sha256, business_role)


def compile_full_semantics(catalog: SemanticCatalog, matrix: PolicyMatrix, *, as_of_date: date | None = None) -> FilteredSemantic:
    """Unfiltered semantic text for the separately authorized context ablation.

    The harness builder must first require catalog/schema contract validation
    and consume its clone-bound capability. Normal persona context never calls
    this pure serializer; it grants no authority itself.
    """
    text = serialize_semantics(catalog, as_of_date=as_of_date)
    return FilteredSemantic(catalog, text, sha256_context(text), catalog.sha256, matrix.sha256, None)
