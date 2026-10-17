"""Fixed-fixture, model-independent metadata inspection. No candidate SQL.

Trusted credentials exist only during explicit inspection. The returned facade
retains safe role projections and fixture-resolved personas, never connections,
passwords, raw catalogs or a model client. Every source is independently checked
against the installed policy; a listener or a source YAML is not verification.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from ..config import AppConfig, DatabaseConnectionAlias
from ..contracts import Persona
from ..db.catalog import filter_catalog, policy_state_sha256, snapshot_schema
from ..db.connections import AdminConnectionSource, RuntimeConnections
from ..db.persona import resolve_personas
from ..errors import ConfigurationError
from ..policy.loader import load_policy, require_policy_schema
from ..semantic.catalog import load_catalog
from ..semantic.entitlements import filter_catalog_for_role
from ..utils.local_sources import resolve_runtime_path
from .response import SafeConcept, SafePolicyRow, scope_note


def load_installation_digest(path: Path, *, root: Path, matrix_sha256: str) -> str:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ConfigurationError("Ambiguous installation binding.")
            result[key] = value
        return result
    source = resolve_runtime_path(path, root=root, label="installation binding")
    with source.open("rb") as stream:
        data = stream.read(1_048_577)
    if len(data) > 1_048_576: raise ConfigurationError("Installation binding exceeds its bound.")
    record = json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique)
    if (type(record) is not dict or record.get("database_name") != "stark_test"
            or record.get("matrix_sha256") != matrix_sha256):
        raise ConfigurationError("Installation binding differs from the fixed application.")
    digest = record.get("policy_state_sha256")
    from ..inference.template import require_sha256
    require_sha256(digest, label="actual installed policy")
    return digest


class MetadataApplication:
    """Safe snapshots from an explicit authenticated read-only inspection."""
    __slots__ = ("_registry", "_concepts", "_policies", "verified_at", "_counts")

    def __init__(self, registry, concepts, policies, counts):
        self._registry = registry
        self._concepts = MappingProxyType(dict(concepts))
        self._policies = MappingProxyType(dict(policies))
        self._counts = MappingProxyType(dict(counts))
        self.verified_at = datetime.now(timezone.utc).isoformat()

    @property
    def personas(self) -> tuple[Persona, ...]:
        return tuple(self._registry.personas.values())

    def semantic_view(self, persona: Persona) -> tuple[SafeConcept, ...]:
        return self._concepts[self._registry.resolve(persona).business_role]

    def policy_view(self, persona: Persona) -> tuple[SafePolicyRow, ...]:
        return self._policies[self._registry.resolve(persona).business_role]

    def employee_count(self, persona: Persona) -> int:
        return self._counts[self._registry.resolve(persona)]


def inspect_metadata(config: AppConfig, *, installation_binding: Path,
                     environment: Mapping[str, str]) -> MetadataApplication:
    """Explicit fixed read-only metadata and scoped-count probes, with no model.

    No role/schema/password/grant/policy/fixture changes are possible here.
    Session-local principal/role settings are used only on audited restricted
    leases, discarded afterward. Administrator SQL is entirely fixed source.
    """
    if (any(alias.host != "127.0.0.1" or alias.port != 5433 for alias in config.database_connections)
            or environment.get("STARK_PG_DATABASE") != "stark_test"):
        raise ConfigurationError("Only the fixed local STARK fixture can be inspected.")
    matrix = load_policy(config.paths.policy_matrix)
    expected = load_installation_digest(installation_binding, root=config.paths.root, matrix_sha256=matrix.sha256)
    admin_alias = DatabaseConnectionAlias("metadata_only", "postgres", "127.0.0.1", 5433,
                                          "STARK_PG_DATABASE", "STARK_ADMIN_PASSWORD")
    admin = AdminConnectionSource(replace(config, database_connections=(*config.database_connections, admin_alias)),
                                  admin_alias.alias, environment=environment)
    try:
        with admin.connection(readonly=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user, session_user")
                if cursor.fetchone() != ("stark_test", "postgres", "postgres"):
                    raise ConfigurationError("Trusted metadata identity differs.")
                cursor.execute("SET LOCAL statement_timeout = '5000ms'")
            snapshot = snapshot_schema(connection, matrix.schema)
            require_policy_schema(matrix, snapshot.columns_by_table)
            if policy_state_sha256(connection, matrix) != expected:
                raise ConfigurationError("Installed database policy differs from reviewed installation.")
        registry = resolve_personas(admin, matrix, sales_division_name="Sales",
                                    fixture_hash_path=("fixture_dump_sha256",))
        catalog = load_catalog(config.paths.semantic_catalog, snapshot, matrix)
    finally:
        admin.close()
    source = RuntimeConnections(config, matrix, registry, expected_policy_state_sha256=expected,
                                environment=environment)
    counts = {}
    try:
        import psycopg2.sql as sql
        for persona in registry.personas.values():
            with source.connection(persona) as connection:
                connection.readonly = True
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_catalog.set_config('app.principal_id', %s, true)", (str(persona.principal_id),))
                    cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(persona.business_role)))
                    cursor.execute("SELECT count(*) FROM public.employees")
                    counts[persona] = cursor.fetchone()[0]
    finally:
        source.close()
    concepts, policies = {}, {}
    for role in matrix.roles:
        projected = filter_catalog_for_role(catalog, matrix, snapshot, role.name)
        rows = []
        for entity in projected.entities.values():
            rows.append(SafeConcept(entity.id, entity.name, entity.description, entity.kind, entity.aliases,
                None, (), tuple(projected.temporal_rules[k].description for k in entity.temporal_rule_ids), None))
        for metric in projected.metrics.values():
            rows.append(SafeConcept(metric.id, metric.name, metric.description, "metric", metric.aliases,
                metric.units, tuple(str(r) for r in metric.grain),
                tuple(projected.temporal_rules[k].description for k in metric.temporal_rule_ids), metric.aggregation))
        concepts[role.name] = tuple(sorted(rows, key=lambda row: (row.kind, row.name)))
        policies[role.name] = tuple(SafePolicyRow(table.name, tuple(c.name for c in table.columns),
            role.tables[table.name].row_scope.value, scope_note(role.tables[table.name].row_scope))
            for table in filter_catalog(snapshot, matrix, role.name).tables)
    return MetadataApplication(registry, concepts, policies, counts)
