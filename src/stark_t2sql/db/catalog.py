"""Future catalog reads and deterministic role-permitted physical metadata.

These are trusted metadata queries, never a path for model-generated SQL.
Prompt 3 owns emitted DDL, semantic compilation and schema-drift rules.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Mapping, TYPE_CHECKING

from ..contracts import Persona
from ..errors import ConfigurationError, MissingDependencyError
from ..policy.loader import PolicyMatrix, require_identifier, require_policy_schema
from ..utils.fingerprints import sha256_context

if TYPE_CHECKING:
    from .connections import RuntimeConnections


@dataclass(frozen=True, slots=True)
class ColumnDefinition:
    name: str
    sql_type: str
    nullable: bool
    ordinal: int


@dataclass(frozen=True, slots=True)
class ForeignKeyDefinition:
    name: str
    columns: tuple[str, ...]
    referenced_schema: str
    referenced_table: str
    referenced_columns: tuple[str, ...]
    on_update: str
    on_delete: str


@dataclass(frozen=True, slots=True)
class TableDefinition:
    name: str
    columns: tuple[ColumnDefinition, ...]
    primary_key: tuple[str, ...] = ()
    unique_keys: tuple[tuple[str, ...], ...] = ()
    foreign_keys: tuple[ForeignKeyDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class SchemaSnapshot:
    schema: str
    tables: tuple[TableDefinition, ...]

    @property
    def columns_by_table(self) -> Mapping[str, tuple[str, ...]]:
        return MappingProxyType({table.name: tuple(column.name for column in table.columns) for table in self.tables})

    def table(self, name: str) -> TableDefinition:
        for table in self.tables:
            if table.name == name:
                return table
        raise ConfigurationError(f"Table is absent from the permitted catalog: {name}")


_COLUMNS_QUERY = """
SELECT relation.relname, attribute.attname,
       pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
       NOT attribute.attnotnull, attribute.attnum
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
JOIN pg_catalog.pg_attribute AS attribute ON attribute.attrelid = relation.oid
WHERE namespace.nspname = %s AND relation.relkind IN ('r', 'p')
  AND attribute.attnum > 0 AND NOT attribute.attisdropped
ORDER BY relation.relname COLLATE "C", attribute.attnum
"""

_CONSTRAINTS_QUERY = """
SELECT relation.relname, constraint_record.conname, constraint_record.contype,
       ARRAY(SELECT attribute.attname
             FROM pg_catalog.unnest(constraint_record.conkey) WITH ORDINALITY AS key(attnum, position)
             JOIN pg_catalog.pg_attribute AS attribute
               ON attribute.attrelid = relation.oid AND attribute.attnum = key.attnum
             ORDER BY key.position),
       referenced_namespace.nspname, referenced_relation.relname,
       ARRAY(SELECT attribute.attname
             FROM pg_catalog.unnest(constraint_record.confkey) WITH ORDINALITY AS key(attnum, position)
             JOIN pg_catalog.pg_attribute AS attribute
               ON attribute.attrelid = referenced_relation.oid AND attribute.attnum = key.attnum
             ORDER BY key.position),
       constraint_record.confupdtype, constraint_record.confdeltype
FROM pg_catalog.pg_constraint AS constraint_record
JOIN pg_catalog.pg_class AS relation ON relation.oid = constraint_record.conrelid
JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
LEFT JOIN pg_catalog.pg_class AS referenced_relation ON referenced_relation.oid = constraint_record.confrelid
LEFT JOIN pg_catalog.pg_namespace AS referenced_namespace ON referenced_namespace.oid = referenced_relation.relnamespace
WHERE namespace.nspname = %s AND relation.relkind IN ('r', 'p')
  AND constraint_record.contype IN ('p', 'u', 'f')
ORDER BY relation.relname COLLATE "C", constraint_record.conname COLLATE "C"
"""

_ACTIONS = {"a": "NO ACTION", "r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "d": "SET DEFAULT"}


def snapshot_schema(connection, schema: str = "public") -> SchemaSnapshot:
    """Read live metadata later; the caller owns the trusted connection lifetime."""
    require_identifier(schema, label="catalog schema")
    columns: dict[str, list[ColumnDefinition]] = {}
    primary_keys = {}
    unique_keys: dict[str, list[tuple[str, ...]]] = {}
    foreign_keys: dict[str, list[ForeignKeyDefinition]] = {}
    with connection.cursor() as cursor:
        cursor.execute(_COLUMNS_QUERY, (schema,))
        for table, name, sql_type, nullable, ordinal in cursor.fetchall():
            columns.setdefault(table, []).append(ColumnDefinition(name, sql_type, bool(nullable), int(ordinal)))
        cursor.execute(_CONSTRAINTS_QUERY, (schema,))
        for table, name, kind, keys, ref_schema, ref_table, ref_keys, update, delete in cursor.fetchall():
            if kind == "p":
                primary_keys[table] = tuple(keys)
            elif kind == "u":
                unique_keys.setdefault(table, []).append(tuple(keys))
            elif kind == "f":
                if update not in _ACTIONS or delete not in _ACTIONS:
                    raise ConfigurationError("Unrecognized catalog foreign-key action.")
                foreign_keys.setdefault(table, []).append(ForeignKeyDefinition(
                    name, tuple(keys), ref_schema, ref_table, tuple(ref_keys), _ACTIONS[update], _ACTIONS[delete]
                ))
    return SchemaSnapshot(schema, tuple(
        TableDefinition(table, tuple(sorted(columns[table], key=lambda column: column.ordinal)),
            primary_keys.get(table, ()), tuple(unique_keys.get(table, ())), tuple(foreign_keys.get(table, ())))
        for table in sorted(columns)
    ))


def filter_catalog(snapshot: SchemaSnapshot, matrix: PolicyMatrix, business_role: str) -> SchemaSnapshot:
    """Retain only permitted columns and relationships with visible endpoints.

    Even a foreign-key name is omitted when its target or any endpoint column is
    hidden. Defaults/check expressions are not exposed as unreviewed DDL text.
    This transformation minimizes context; grants and RLS enforce access.
    """
    if snapshot.schema != matrix.schema:
        raise ConfigurationError("Catalog and access matrix refer to different schemas.")
    require_policy_schema(matrix, snapshot.columns_by_table)
    permitted = {
        table: set(matrix.permitted_columns(business_role, table, snapshot.columns_by_table[table]))
        for table in matrix.permitted_tables(business_role)
    }
    tables = []
    for table_name in sorted(permitted):
        original = snapshot.table(table_name)
        visible = permitted[table_name]
        foreign_keys = tuple(key for key in original.foreign_keys if (
            set(key.columns) <= visible
            and key.referenced_schema == matrix.schema
            and key.referenced_table in permitted
            and set(key.referenced_columns) <= permitted[key.referenced_table]
        ))
        tables.append(TableDefinition(
            table_name, tuple(column for column in original.columns if column.name in visible),
            original.primary_key if set(original.primary_key) <= visible else (),
            tuple(key for key in original.unique_keys if set(key) <= visible), foreign_keys,
        ))
    return SchemaSnapshot(matrix.schema, tuple(tables))


def load_role_catalog(
    connections: RuntimeConnections, persona: Persona, matrix: PolicyMatrix
) -> SchemaSnapshot:
    """Read metadata under an audited persona login and project loaded entitlements."""
    if connections.matrix.sha256 != matrix.sha256:
        raise ConfigurationError("Catalog and connections require the same loaded policy.")
    try:
        from psycopg2 import sql
    except ImportError as exc:
        raise MissingDependencyError("psycopg2 is required for catalog reads.") from exc
    role = matrix.role(persona.business_role)
    with connections.connection(persona) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.set_config('app.principal_id', %s, true)", (str(persona.principal_id),))
            cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role.name)))
        return filter_catalog(snapshot_schema(connection, schema=matrix.schema), matrix, role.name)


def policy_state_sha256(connection, matrix: PolicyMatrix) -> str:
    """Fingerprint actual installed scope metadata for future trusted setup/runtime.

    This records all policies and application functions, not just expected names,
    so a stale permissive policy or changed definer body changes the digest. OIDs
    are resolved to names to keep equivalent restored metadata deterministic.
    It is a drift guard, never a claim about observed row-level behavior.
    """
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT relation.relname, relation.relrowsecurity, relation.relforcerowsecurity,
                   policy.polname, policy.polcmd, policy.polpermissive,
                   ARRAY(SELECT CASE WHEN role_oid = 0 THEN 'PUBLIC' ELSE role_record.rolname END
                         FROM pg_catalog.unnest(policy.polroles) AS role_oid
                         LEFT JOIN pg_catalog.pg_roles AS role_record ON role_record.oid = role_oid
                         ORDER BY CASE WHEN role_oid = 0 THEN 'PUBLIC' ELSE role_record.rolname END COLLATE "C"),
                   pg_catalog.pg_get_expr(policy.polqual, policy.polrelid),
                   pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
            FROM pg_catalog.pg_class AS relation
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            LEFT JOIN pg_catalog.pg_policy AS policy ON policy.polrelid = relation.oid
            WHERE namespace.nspname = %s AND relation.relname = ANY(%s)
            ORDER BY relation.relname COLLATE "C", policy.polname COLLATE "C"
        """, (matrix.schema, list(matrix.rls_tables)))
        policies = cursor.fetchall()
        cursor.execute("""
            SELECT function_record.proname, pg_catalog.pg_get_function_identity_arguments(function_record.oid),
                   function_record.prokind, function_record.prosecdef, function_record.provolatile,
                   owner_role.rolname, function_record.proconfig,
                   CASE WHEN function_record.prokind <> 'a'
                        THEN pg_catalog.pg_get_functiondef(function_record.oid) ELSE NULL END
            FROM pg_catalog.pg_proc AS function_record
            JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = function_record.pronamespace
            JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = function_record.proowner
            WHERE namespace.nspname = %s
            ORDER BY function_record.proname COLLATE "C",
                     pg_catalog.pg_get_function_identity_arguments(function_record.oid) COLLATE "C"
        """, (matrix.schema,))
        functions = cursor.fetchall()
    return sha256_context(json.dumps(
        {"schema": matrix.schema, "matrix_sha256": matrix.sha256, "policies": policies, "functions": functions},
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
    ))
