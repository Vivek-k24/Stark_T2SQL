"""Role-derived semantic visibility for FR-3/FR-7, separate from authorization.

This module consumes one loaded access matrix and a physical schema snapshot.
It neither reads a database nor changes grants. Every declared physical column,
relationship endpoint, temporal dependency and semantic dependency is required;
table visibility alone never enables a metric. PostgreSQL grants/RLS and the
SQL guard remain the access boundary. I-01 is deliberately unresolved.
"""

from __future__ import annotations

from dataclasses import replace

from ..contracts import RowScopeKind
from ..db.catalog import SchemaSnapshot
from ..errors import ConfigurationError
from ..policy.loader import PolicyMatrix, require_policy_schema
from .models import ColumnRef, EntityDefinition, MetricDefinition, SemanticCatalog


def _permitted_columns(
    matrix: PolicyMatrix, snapshot: SchemaSnapshot, business_role: str
) -> dict[str, frozenset[str]]:
    if snapshot.schema != matrix.schema:
        raise ConfigurationError("Semantic context and physical policy use different schemas.")
    require_policy_schema(matrix, snapshot.columns_by_table)
    matrix.role(business_role)
    return {
        table: frozenset(matrix.permitted_columns(
            business_role, table, snapshot.columns_by_table[table]
        ))
        for table in matrix.permitted_tables(business_role)
    }


def _physical_is_visible(
    source_tables: tuple[str, ...],
    source_columns: tuple[ColumnRef, ...],
    permitted: dict[str, frozenset[str]],
) -> bool:
    return (
        all(table in permitted for table in source_tables)
        and all(column.table in permitted and column.column in permitted[column.table]
                for column in source_columns)
    )


def _lineage_is_visible(
    definition: EntityDefinition | MetricDefinition,
    catalog: SemanticCatalog,
    permitted: dict[str, frozenset[str]],
) -> bool:
    if not _physical_is_visible(definition.source_tables, definition.source_columns, permitted):
        return False
    if isinstance(definition, MetricDefinition) and not _physical_is_visible((), definition.grain, permitted):
        return False
    for relationship_id in definition.relationship_ids:
        relationship = catalog.relationships.get(relationship_id)
        if relationship is None:
            raise ConfigurationError("A semantic definition has an unresolved relationship.")
        if not _physical_is_visible(
            (relationship.source.table, relationship.target.table),
            (relationship.source, relationship.target), permitted,
        ):
            return False
    for temporal_rule_id in definition.temporal_rule_ids:
        temporal = catalog.temporal_rules.get(temporal_rule_id)
        if temporal is None:
            raise ConfigurationError("A semantic definition has an unresolved temporal rule.")
        if not _physical_is_visible(temporal.source_tables, temporal.source_columns, permitted):
            return False
    return True


def _backing_tables(
    definition: EntityDefinition | MetricDefinition,
    catalog: SemanticCatalog,
    ancestors: frozenset[str] = frozenset(),
) -> set[str]:
    if definition.id in ancestors:
        raise ConfigurationError("Circular semantic dependencies cannot establish backing scope.")
    tables = set(definition.source_tables)
    tables.update(column.table for column in definition.source_columns)
    if isinstance(definition, MetricDefinition):
        tables.update(column.table for column in definition.grain)
    for relationship_id in definition.relationship_ids:
        relationship = catalog.relationships[relationship_id]
        tables.update((relationship.source.table, relationship.target.table))
    for temporal_rule_id in definition.temporal_rule_ids:
        temporal = catalog.temporal_rules[temporal_rule_id]
        tables.update(temporal.source_tables)
        tables.update(column.table for column in temporal.source_columns)
    if isinstance(definition, MetricDefinition):
        for dependency_id in definition.dependencies:
            dependency = catalog.entities.get(dependency_id) or catalog.metrics.get(dependency_id)
            if dependency is None:
                raise ConfigurationError("A metric has an unresolved semantic dependency.")
            tables.update(_backing_tables(dependency, catalog, ancestors | {definition.id}))
    return tables


def _metric_allowed(
    metric_id: str,
    catalog: SemanticCatalog,
    matrix: PolicyMatrix,
    business_role: str,
    permitted: dict[str, frozenset[str]],
    ancestors: frozenset[str],
) -> bool:
    metric = catalog.metrics.get(metric_id)
    if metric is None:
        return False
    if metric_id in ancestors:
        raise ConfigurationError("Circular semantic dependencies cannot establish eligibility.")
    # Even a later accidental grant expansion must not close the open decision.
    # A separately approved source change is needed to remove this I-01 guard.
    if metric_id == "active_headcount" and business_role == "app_sales_mgr":
        return False
    if business_role in metric.pending_roles:
        return False
    if not _lineage_is_visible(metric, catalog, permitted):
        return False
    next_ancestors = ancestors | {metric_id}
    for dependency_id in metric.dependencies:
        entity = catalog.entities.get(dependency_id)
        if entity is not None:
            if not _lineage_is_visible(entity, catalog, permitted):
                return False
        elif dependency_id in catalog.metrics:
            if not _metric_allowed(
                dependency_id, catalog, matrix, business_role, permitted, next_ancestors
            ):
                return False
        else:
            raise ConfigurationError("A metric has an unresolved semantic dependency.")
    role = matrix.role(business_role)
    observed_scopes = {role.tables[table].row_scope for table in _backing_tables(metric, catalog)}
    scoped = observed_scopes - {RowScopeKind.ALL}
    # ALL lookup rows do not erase an employees RLS scope. A scoped metric must
    # describe every non-ALL backing scope, including dependency lineage; a
    # wholly unscoped metric requires ALL.
    required_scopes = scoped if scoped else {RowScopeKind.ALL}
    if not required_scopes <= set(metric.allowed_scopes):
        return False
    return True


def metric_is_allowed(
    catalog: SemanticCatalog,
    matrix: PolicyMatrix,
    snapshot: SchemaSnapshot,
    business_role: str,
    metric_id: str,
) -> bool:
    """Derive eligibility from all physical lineage and the role's exact scope.

    This is descriptive capability metadata. It grants no SQL permission and
    accepts no principal override or policy workaround.
    """
    # A typed catalog may be constructed without going through the YAML loader.
    # Validate the complete source contract before deriving public eligibility.
    # This lazy import keeps catalog loading independent of entitlement helpers.
    from .catalog import require_catalog_contract

    require_catalog_contract(catalog, snapshot, matrix)
    permitted = _permitted_columns(matrix, snapshot, business_role)
    return _metric_allowed(metric_id, catalog, matrix, business_role, permitted, frozenset())


def filter_catalog_for_role(
    catalog: SemanticCatalog,
    matrix: PolicyMatrix,
    snapshot: SchemaSnapshot,
    business_role: str,
) -> SemanticCatalog:
    """Project only eligible meanings and lineage into a role prompt context.

    Aliases live on their parent definitions and disappear with a hidden parent.
    Ambiguity entries retain only visible targets and are emitted only if two
    meanings remain visible. The resolver matches longest phrases in the original
    vocabulary, then tests ambiguity over role-visible meanings only. A hidden
    explicit phrase must never be reinterpreted as a shorter visible concept.
    sha256 retains source-catalog provenance; the context builder independently
    hashes the deterministic emitted semantic text.
    """
    from .catalog import require_catalog_contract

    require_catalog_contract(catalog, snapshot, matrix)
    permitted = _permitted_columns(matrix, snapshot, business_role)
    entities = {
        concept_id: entity for concept_id, entity in sorted(catalog.entities.items())
        if _lineage_is_visible(entity, catalog, permitted)
    }
    metrics = {
        metric_id: metric for metric_id, metric in sorted(catalog.metrics.items())
        if _metric_allowed(metric_id, catalog, matrix, business_role, permitted, frozenset())
    }
    selected = tuple(entities.values()) + tuple(metrics.values())
    temporal_ids = {item for definition in selected for item in definition.temporal_rule_ids}
    # A reviewed physical join remains useful even when no surviving metric
    # explicitly depends on it. Both endpoints and every join column must be
    # visible; concealed relationship names disappear with hidden lineage.
    relationships = {
        relationship_id: relationship
        for relationship_id, relationship in sorted(catalog.relationships.items())
        if _physical_is_visible(
            (relationship.source.table, relationship.target.table),
            (relationship.source, relationship.target), permitted,
        )
    }
    temporal_rules = {
        temporal_id: catalog.temporal_rules[temporal_id] for temporal_id in sorted(temporal_ids)
    }
    visible_ids = set(entities) | set(metrics)
    ambiguities = tuple(
        replace(ambiguity, targets=targets)
        for ambiguity in sorted(catalog.ambiguities, key=lambda item: item.term)
        if len(targets := tuple(sorted(set(ambiguity.targets) & visible_ids))) > 1
    )
    return SemanticCatalog(
        version=catalog.version,
        entities=entities,
        metrics=metrics,
        relationships=relationships,
        temporal_rules=temporal_rules,
        ambiguities=ambiguities,
        sha256=catalog.sha256,
    )
