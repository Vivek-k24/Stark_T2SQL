"""Future governed-source loading, lineage contracts and drift-report functions.

No catalog, parser, database, fixture or holdout is opened on import. Catalog
validation is separate from model SQL validation: it examines trusted metadata
lineage, not persona-query columns. Definitions require future human review.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata
from typing import Mapping

from ..contracts import RowScopeKind
from ..db.catalog import SchemaSnapshot
from ..errors import ConfigurationError, MissingDependencyError, SourceReadError
from ..policy.loader import PolicyMatrix, require_identifier, require_policy_schema
from ..utils.fingerprints import sha256_bytes
from .models import (
    AmbiguityDefinition, ColumnRef, EntityDefinition, MetricDefinition,
    RelationshipDefinition, SemanticCatalog, TemporalRule,
)


@dataclass(frozen=True, slots=True)
class CatalogIssue:
    code: str
    detail: str


def _mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ConfigurationError(f"{label} must be a text-keyed mapping.")
    return value


def _keys(value: dict, expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ConfigurationError(f"{label} has missing or unsupported definition fields.")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(character) < 32 for character in value):
        raise ConfigurationError(f"{label} must be nonempty text without control characters.")
    return value


def _strings(value: object, label: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ConfigurationError(f"{label} must be a definition list.")
    result = tuple(_text(item, label) for item in value)
    if len(set(result)) != len(result):
        raise ConfigurationError(f"{label} contains duplicate definition values.")
    return result


def _ref(value: object) -> ColumnRef:
    text = _text(value, "source column")
    parts = text.split(".")
    if len(parts) != 2:
        raise ConfigurationError("Source columns must explicitly name table.column.")
    return ColumnRef(*parts)


def _refs(value: object, label: str) -> tuple[ColumnRef, ...]:
    return tuple(_ref(item) for item in _strings(value, label, nonempty=True))


def _definition_sources(raw: dict) -> tuple[tuple[str, ...], tuple[ColumnRef, ...]]:
    tables = _strings(raw["source_tables"], "source tables", nonempty=True)
    for table in tables:
        require_identifier(table, label="source table")
    return tables, _refs(raw["source_columns"], "source columns")


def load_catalog(path: str | Path, snapshot: SchemaSnapshot, matrix: PolicyMatrix) -> SemanticCatalog:
    """Load actual YAML bytes later, then require all three catalog contracts.

    PyYAML and sqlglot are later runtime dependencies; neither is imported or
    installed in this assignment. Duplicate keys, aliases and unknown fields
    are refused. Hash and parse always refer to the same source byte sequence.
    """
    try:
        with Path(path).open("rb") as source:
            data = source.read(1_048_577)
    except FileNotFoundError as exc:
        raise MissingDependencyError(f"The governed catalog source is unavailable: {path}") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise SourceReadError("The governed catalog source could not be read.") from exc
    if len(data) > 1_048_576:
        raise ConfigurationError("The governed source exceeds its file size limit.")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SourceReadError("The governed catalog source must be UTF-8.") from exc
    try:
        import yaml
    except ImportError as exc:
        raise MissingDependencyError("PyYAML is required for governed catalog loading.") from exc

    class StrictLoader(yaml.SafeLoader):
        def compose_node(self, parent, index):
            if self.check_event(yaml.events.AliasEvent):
                raise ConfigurationError("Aliases are not permitted in governed catalog YAML.")
            return super().compose_node(parent, index)

        def construct_mapping(self, node, deep=False):
            result = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str) or key in result:
                    raise ConfigurationError("Catalog mapping keys must be unique text.")
                result[key] = self.construct_object(value_node, deep=deep)
            return result

    try:
        raw = _mapping(yaml.load(text, Loader=StrictLoader), "catalog")
    except yaml.YAMLError as exc:
        raise ConfigurationError("The governed source is not supported YAML.") from exc
    _keys(raw, {"version", "entities", "metrics", "relationships", "temporal_rules", "ambiguities"}, "catalog")
    entities, metrics, relationships, temporal_rules = {}, {}, {}, {}
    for identity, value in sorted(_mapping(raw["relationships"], "relationships").items()):
        require_identifier(identity, label="relationship id")
        value = _mapping(value, "relationship")
        _keys(value, {"source", "target", "cardinality"}, "relationship")
        relationships[identity] = RelationshipDefinition(identity, _ref(value["source"]), _ref(value["target"]),
            _text(value["cardinality"], "cardinality"))
    for identity, value in sorted(_mapping(raw["temporal_rules"], "temporal rules").items()):
        require_identifier(identity, label="temporal id")
        value = _mapping(value, "temporal rule")
        _keys(value, {"description", "source_tables", "source_columns", "predicate", "selection"}, "temporal rule")
        tables, columns = _definition_sources(value)
        temporal_rules[identity] = TemporalRule(identity, _text(value["description"], "description"), tables, columns,
            _text(value["predicate"], "predicate"), _text(value["selection"], "selection"))
    entity_keys = {"name", "kind", "description", "aliases", "source_tables", "source_columns", "relationship_ids", "filters", "temporal_rule_ids"}
    for identity, value in sorted(_mapping(raw["entities"], "entities").items()):
        require_identifier(identity, label="entity id")
        value = _mapping(value, "entity")
        _keys(value, entity_keys, "entity")
        tables, columns = _definition_sources(value)
        entities[identity] = EntityDefinition(identity, _text(value["name"], "name"), _text(value["kind"], "kind"),
            _text(value["description"], "description"), _strings(value["aliases"], "aliases", nonempty=True),
            tables, columns, _strings(value["relationship_ids"], "relationship ids"),
            _strings(value["filters"], "filters"), _strings(value["temporal_rule_ids"], "temporal ids"))
    metric_keys = (entity_keys - {"kind"}) | {"expression", "grain", "aggregation", "null_handling", "units", "allowed_scopes", "dependencies", "pending_roles"}
    for identity, value in sorted(_mapping(raw["metrics"], "metrics").items()):
        require_identifier(identity, label="metric id")
        value = _mapping(value, "metric")
        _keys(value, metric_keys, "metric")
        tables, columns = _definition_sources(value)
        try:
            scopes = tuple(RowScopeKind(scope) for scope in _strings(value["allowed_scopes"], "allowed scopes", nonempty=True))
        except ValueError as exc:
            raise ConfigurationError("A metric declares an unsupported scope.") from exc
        metrics[identity] = MetricDefinition(identity, _text(value["name"], "name"), _text(value["description"], "description"),
            _strings(value["aliases"], "aliases", nonempty=True), _text(value["expression"], "expression"),
            _refs(value["grain"], "grain"), tables, columns, _strings(value["relationship_ids"], "relationship ids"),
            _strings(value["filters"], "filters"), _text(value["aggregation"], "aggregation"),
            _text(value["null_handling"], "null handling"), _text(value["units"], "units"),
            _strings(value["temporal_rule_ids"], "temporal ids"), scopes,
            _strings(value["dependencies"], "dependencies"), _strings(value["pending_roles"], "pending roles"))
    if not isinstance(raw["ambiguities"], list):
        raise ConfigurationError("Ambiguities must be a definition list.")
    ambiguities = []
    for value in raw["ambiguities"]:
        value = _mapping(value, "ambiguity")
        _keys(value, {"term", "targets"}, "ambiguity")
        ambiguities.append(AmbiguityDefinition(_text(value["term"], "ambiguity term"), _strings(value["targets"], "targets", nonempty=True)))
    catalog = SemanticCatalog(_text(raw["version"], "version"), entities, metrics, relationships, temporal_rules,
        tuple(ambiguities), sha256_bytes(data))
    require_catalog_contract(catalog, snapshot, matrix)
    return catalog


def _parser():
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError as exc:
        raise MissingDependencyError("sqlglot is required for trusted catalog-expression lineage.") from exc
    classes = {}
    for name in ("Expression", "Select", "Column", "Table", "Subquery"):
        candidate = getattr(exp, name, None)
        if not isinstance(candidate, type):
            raise MissingDependencyError(f"The installed parser lacks catalog lineage capability: {name}")
        classes[name] = candidate
    return sqlglot, classes


def _fragment(expression: str, parser, classes):
    """Parse a trusted scalar fragment later; no SQL execution or query column enforcement."""
    try:
        statements = parser.parse("SELECT " + expression, read="postgres")
    except Exception as exc:
        raise ConfigurationError("A governed SQL fragment is not recognized by the installed parser.") from exc
    if len(statements) != 1 or type(statements[0]) is not classes["Select"]:
        raise ConfigurationError("A governed fragment must be one scalar projection.")
    statement = statements[0]
    if len(statement.expressions) != 1 or any(statement.args.get(key) for key in ("from", "from_", "with", "with_", "joins", "into", "locks")):
        raise ConfigurationError("A governed fragment cannot contain query/table/command clauses.")
    if any(isinstance(node, (classes["Table"], classes["Subquery"])) for node in statement.walk()):
        raise ConfigurationError("Subqueries require separately governed lineage rather than hidden fragment sources.")
    references = set()
    for node in statement.find_all(classes["Column"]):
        if not node.table or node.db or node.catalog or node.is_star:
            raise ConfigurationError("Governed expressions require explicit physical table.column references.")
        references.add(ColumnRef(node.table, node.name))
    return statement.sql(dialect="postgres"), references


def normalize_term(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().replace("_", " ").split())


def validate_catalog(catalog: SemanticCatalog, snapshot: SchemaSnapshot, matrix: PolicyMatrix) -> tuple[CatalogIssue, ...]:
    """Future vocabulary, metric/temporal/FK and policy-reference contracts.

    Parser access is lazy and fail-closed. This function is authored, not called
    here. It inspects trusted catalog declarations independently from FR-5.
    """
    require_policy_schema(matrix, snapshot.columns_by_table)
    if snapshot.schema != matrix.schema:
        return (CatalogIssue("SCHEMA", "Catalog metadata and matrix schema differ."),)
    parser, classes = _parser()
    issues = []
    columns = {ColumnRef(table.name, column.name): column for table in snapshot.tables for column in table.columns}
    concepts = dict(catalog.entities)
    if set(concepts) & set(catalog.metrics):
        issues.append(CatalogIssue("CONCEPT_ID", "Entity and metric IDs overlap."))
    concepts.update(catalog.metrics)
    valid_roles = {role.name for role in matrix.roles}

    def report_refs(label: str, tables: tuple[str, ...], refs: tuple[ColumnRef, ...]) -> None:
        if not tables or not refs or len(set(tables)) != len(tables) or len(set(refs)) != len(refs):
            issues.append(CatalogIssue("LINEAGE", f"Empty or duplicate lineage: {label}"))
        for table in set(tables) - set(snapshot.columns_by_table):
            issues.append(CatalogIssue("TABLE", f"Unknown backing table: {label}:{table}"))
        for ref in refs:
            if ref not in columns or ref.table not in tables:
                issues.append(CatalogIssue("COLUMN", f"Unknown or undeclared backing column: {label}:{ref}"))

    def fragment_refs(label: str, expression: str, declared: set[ColumnRef]) -> None:
        try:
            _, referenced = _fragment(expression, parser, classes)
            if not referenced <= declared:
                issues.append(CatalogIssue("EXPRESSION_LINEAGE", f"Undeclared expression columns: {label}"))
        except ConfigurationError as exc:
            issues.append(CatalogIssue("EXPRESSION", f"Invalid fragment: {label}: {exc.internal_detail}"))

    for identity, relationship in sorted(catalog.relationships.items()):
        if relationship.id != identity or relationship.cardinality != "many_to_one":
            issues.append(CatalogIssue("RELATIONSHIP", f"Unsupported relationship identity/cardinality: {identity}"))
        if relationship.source not in columns or relationship.target not in columns:
            issues.append(CatalogIssue("RELATIONSHIP_COLUMN", f"Missing relationship endpoint: {identity}"))
            continue
        source = snapshot.table(relationship.source.table)
        target = snapshot.table(relationship.target.table)
        if not any(key.columns == (relationship.source.column,) and key.referenced_schema == matrix.schema
            and key.referenced_table == relationship.target.table and key.referenced_columns == (relationship.target.column,)
            for key in source.foreign_keys):
            issues.append(CatalogIssue("RELATIONSHIP_DRIFT", f"Declared foreign-key path is absent: {identity}"))
        if (relationship.target.column,) not in (target.primary_key,) + target.unique_keys:
            issues.append(CatalogIssue("CARDINALITY", f"Many-to-one target is not unique: {identity}"))
        if columns[relationship.source].sql_type != columns[relationship.target].sql_type:
            issues.append(CatalogIssue("RELATIONSHIP_TYPE", f"Join endpoint types differ: {identity}"))
    for identity, temporal in sorted(catalog.temporal_rules.items()):
        if identity != temporal.id:
            issues.append(CatalogIssue("TEMPORAL_ID", f"Temporal key and ID differ: {identity}"))
        report_refs(identity, temporal.source_tables, temporal.source_columns)
        fragment_refs(identity, temporal.predicate, set(temporal.source_columns))
    aliases: dict[str, set[str]] = {}
    for identity, concept in sorted(concepts.items()):
        if identity != concept.id:
            issues.append(CatalogIssue("CONCEPT_ID", f"Concept key and ID differ: {identity}"))
        report_refs(identity, concept.source_tables, concept.source_columns)
        for alias in (concept.id, concept.name) + concept.aliases:
            aliases.setdefault(normalize_term(alias), set()).add(identity)
        for expression in concept.filters:
            fragment_refs(identity, expression, set(concept.source_columns))
        links = []
        for reference in concept.relationship_ids:
            relationship = catalog.relationships.get(reference)
            if relationship is None:
                issues.append(CatalogIssue("RELATIONSHIP", f"Unknown concept join path: {identity}:{reference}"))
            elif not {relationship.source, relationship.target} <= set(concept.source_columns):
                issues.append(CatalogIssue("JOIN_LINEAGE", f"Join endpoints are absent from declared lineage: {identity}:{reference}"))
            else:
                links.append((relationship.source.table, relationship.target.table))
        # Every multi-table definition needs a connected declared join path.
        if concept.source_tables:
            connected = {concept.source_tables[0]}
            while True:
                expanded = connected | {right for left, right in links if left in connected} | {left for left, right in links if right in connected}
                if expanded == connected:
                    break
                connected = expanded
            if not set(concept.source_tables) <= connected:
                issues.append(CatalogIssue("JOIN_PATH", f"Disconnected concept source grain: {identity}"))
        for reference in concept.temporal_rule_ids:
            temporal = catalog.temporal_rules.get(reference)
            if temporal is None:
                issues.append(CatalogIssue("TEMPORAL", f"Unknown temporal rule: {identity}:{reference}"))
            elif not set(temporal.source_columns) <= set(concept.source_columns):
                issues.append(CatalogIssue("TEMPORAL_LINEAGE", f"Temporal columns omitted from lineage: {identity}:{reference}"))
        if isinstance(concept, MetricDefinition):
            fragment_refs(identity, concept.expression, set(concept.source_columns))
            if not concept.grain or not set(concept.grain) <= set(concept.source_columns):
                issues.append(CatalogIssue("GRAIN", f"Metric grain is absent from declared physical lineage: {identity}"))
            if concept.aggregation not in {"none", "count", "count_distinct", "sum", "avg", "min", "max"}:
                issues.append(CatalogIssue("AGGREGATION", f"Unsupported metric aggregation: {identity}"))
            if not concept.allowed_scopes or any(not isinstance(scope, RowScopeKind) for scope in concept.allowed_scopes):
                issues.append(CatalogIssue("SCOPE", f"Metric scopes are invalid: {identity}"))
            if set(concept.pending_roles) - valid_roles:
                issues.append(CatalogIssue("ROLE", f"Unknown pending-decision role: {identity}"))
            for dependency in concept.dependencies:
                if dependency not in concepts:
                    issues.append(CatalogIssue("DEPENDENCY", f"Unknown concept dependency: {identity}:{dependency}"))
    declared_ambiguities = {}
    for ambiguity in catalog.ambiguities:
        term = normalize_term(ambiguity.term)
        if term in declared_ambiguities or len(set(ambiguity.targets)) < 2 or set(ambiguity.targets) - set(concepts):
            issues.append(CatalogIssue("AMBIGUITY", f"Invalid ambiguity declaration: {term}"))
        declared_ambiguities[term] = set(ambiguity.targets)
        if term in aliases and not aliases[term] <= set(ambiguity.targets):
            issues.append(CatalogIssue("AMBIGUITY", f"Ambiguity omits alias meanings: {term}"))
    for alias, targets in aliases.items():
        if len(targets) > 1 and declared_ambiguities.get(alias) != targets:
            issues.append(CatalogIssue("ALIAS_COLLISION", f"Unresolved alias collision: {alias}"))
    visiting, visited = set(), set()

    def visit(identity: str) -> None:
        if identity in visiting:
            issues.append(CatalogIssue("CYCLE", f"Circular metric dependency: {identity}"))
            return
        if identity in visited:
            return
        visiting.add(identity)
        concept = concepts[identity]
        for dependency in getattr(concept, "dependencies", ()):
            if dependency in concepts:
                visit(dependency)
        visiting.remove(identity)
        visited.add(identity)

    for identity in concepts:
        visit(identity)
    issues.extend(_canonical_requirements(catalog, parser, classes))
    return tuple(issues)


def _canonical_requirements(catalog: SemanticCatalog, parser, classes) -> tuple[CatalogIssue, ...]:
    """Keep the mandatory FR-7 definitions explicit; no expected answer values."""
    issues = []

    def same(left: str, right: str) -> bool:
        try:
            return _fragment(left, parser, classes)[0] == _fragment(right, parser, classes)[0]
        except ConfigurationError:
            return False

    active = catalog.metrics.get("active_headcount")
    active_filters = (
        "employees.employment_type IN ('full_time', 'part_time')",
        "employees.status <> 'cancelled_pre_hire'",
        "employees.hire_date <= CAST(:as_of_date AS DATE)",
        "(employees.termination_date IS NULL OR employees.termination_date > CAST(:as_of_date AS DATE))",
    )
    if active is None or not same(active.expression, "COUNT(DISTINCT employees.employee_id)") or (
        active.grain != (ColumnRef("employees", "employee_id"),)
        or active.aggregation != "count_distinct"
        or len(active.filters) != len(active_filters)
        or any(not any(same(predicate, expected) for predicate in active.filters) for expected in active_filters)
        or "app_sales_mgr" not in active.pending_roles
    ):
        issues.append(CatalogIssue("ACTIVE_HEADCOUNT", "Canonical active_headcount differs from FR-7.4/I-01."))
    payroll = catalog.metrics.get("posted_closed_payroll_run_count")
    if payroll is None or not any(same(predicate, "payroll_runs.status IN ('posted', 'closed')") for predicate in payroll.filters):
        issues.append(CatalogIssue("PAYROLL_STATUS", "Payroll counting must include posted and closed statuses."))
    bonus = catalog.metrics.get("bonus_target_percentage")
    if bonus is None or not same(bonus.expression, "employee_compensation.bonus_target_pct") or (
        bonus.aggregation != "none" or bonus.units != "percentage_points"
        or bonus.grain != (ColumnRef("employees", "employee_id"),)
        or "compensation_employee" not in bonus.relationship_ids
        or "compensation_effective_as_of" not in bonus.temporal_rule_ids
    ):
        issues.append(CatalogIssue("BONUS_TARGET", "Bonus target must retain its percentage and employee grain semantics."))
    engineering = catalog.entities.get("engineering_division")
    if engineering is None or engineering.kind != "division_member" or not any(same(predicate, "divisions.division_name = 'Engineering'") for predicate in engineering.filters):
        issues.append(CatalogIssue("ENGINEERING", "Engineering must resolve to the governed division."))
    pay_date = catalog.entities.get("payroll_pay_date")
    period_end = catalog.entities.get("payroll_period_end")
    if pay_date is None or period_end is None or (
        pay_date.source_columns != (ColumnRef("payroll_runs", "pay_date"),)
        or period_end.source_columns != (ColumnRef("payroll_runs", "pay_period_end"),)
    ):
        issues.append(CatalogIssue("PAYROLL_TIME", "Payment and earning-period date meanings must remain distinct."))
    canonical_temporal = {
        "pay_date_as_of": "payroll_runs.pay_date <= CAST(:as_of_date AS DATE)",
        "period_end_as_of": "payroll_runs.pay_period_end <= CAST(:as_of_date AS DATE)",
        "compensation_effective_as_of": (
            "employee_compensation.effective_date <= CAST(:as_of_date AS DATE) AND "
            "(employee_compensation.effective_to IS NULL OR employee_compensation.effective_to > CAST(:as_of_date AS DATE))"
        ),
        "hr_assignment_current": "hr_bp_assignments.effective_to IS NULL",
    }
    for identity, predicate in canonical_temporal.items():
        rule = catalog.temporal_rules.get(identity)
        if rule is None or not same(rule.predicate, predicate):
            issues.append(CatalogIssue("EFFECTIVE_TIME", f"Canonical temporal definition differs: {identity}"))
    return tuple(issues)


def require_catalog_contract(catalog: SemanticCatalog, snapshot: SchemaSnapshot, matrix: PolicyMatrix) -> None:
    issues = validate_catalog(catalog, snapshot, matrix)
    if issues:
        raise ConfigurationError("Governed catalog contract: " + "; ".join(issue.detail for issue in issues))


def detect_schema_drift(previous: SchemaSnapshot, current: SchemaSnapshot) -> tuple[CatalogIssue, ...]:
    """Describe physical changes later; no baseline snapshot is fabricated here."""
    before, after = {table.name: table for table in previous.tables}, {table.name: table for table in current.tables}
    issues = []
    for table in sorted(set(before) | set(after)):
        if table not in before or table not in after:
            issues.append(CatalogIssue("TABLE_DRIFT", f"Table inventory changed: {table}"))
            continue
        old, new = before[table], after[table]
        if old.columns != new.columns:
            issues.append(CatalogIssue("COLUMN_DRIFT", f"Columns, types, nullability or order changed: {table}"))
        if old.primary_key != new.primary_key or old.unique_keys != new.unique_keys or old.foreign_keys != new.foreign_keys:
            issues.append(CatalogIssue("RELATIONSHIP_DRIFT", f"Keys or relationship paths changed: {table}"))
    return tuple(issues)


def detect_semantic_drift(previous: SemanticCatalog, current: SemanticCatalog) -> tuple[CatalogIssue, ...]:
    """Report definition, grain, aggregation, vocabulary and temporal changes."""
    issues = []
    for field in ("entities", "metrics", "relationships", "temporal_rules"):
        before, after = getattr(previous, field), getattr(current, field)
        for identity in sorted(set(before) | set(after)):
            if before.get(identity) != after.get(identity):
                issues.append(CatalogIssue("SEMANTIC_DRIFT", f"Governed {field} definition changed: {identity}"))
    if previous.ambiguities != current.ambiguities:
        issues.append(CatalogIssue("AMBIGUITY_DRIFT", "Governed ambiguity declarations changed."))
    return tuple(issues)


def detect_entitlement_drift(catalog: SemanticCatalog, snapshot: SchemaSnapshot,
    previous: PolicyMatrix, current: PolicyMatrix) -> tuple[CatalogIssue, ...]:
    """Compare actual metadata-derived eligibility later, never a permission result."""
    from .entitlements import filter_catalog_for_role

    issues = []
    before_roles = {role.name for role in previous.roles}
    after_roles = {role.name for role in current.roles}
    if before_roles != after_roles:
        issues.append(CatalogIssue("ROLE_DRIFT", "Business role inventory changed."))
    for role in sorted(before_roles & after_roles):
        before = filter_catalog_for_role(catalog, previous, snapshot, role)
        after = filter_catalog_for_role(catalog, current, snapshot, role)
        for field in ("entities", "metrics", "relationships", "temporal_rules"):
            if set(getattr(before, field)) != set(getattr(after, field)):
                issues.append(CatalogIssue("ENTITLEMENT_DRIFT", f"Role-visible {field} changed: {role}"))
    return tuple(issues)
