"""Deterministic DDL from supplied physical metadata and the loaded matrix.

No connection, SQL parser, schema.sql reader, or catalog lookup runs here.
The trusted later caller supplies db.catalog.SchemaSnapshot, ordinarily from
the live catalog. Defaults, check expressions, index expressions and constraint
names are deliberately absent: those strings can reveal hidden dependencies.
This is model context, not a replacement migration or authorization boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from ..db.catalog import (
    ColumnDefinition,
    ForeignKeyDefinition,
    SchemaSnapshot,
    TableDefinition,
    filter_catalog,
)
from ..errors import ConfigurationError
from ..policy.loader import PolicyMatrix, require_identifier, require_policy_schema
from ..policy.privileges import qualified_name, quote_identifier
from ..utils.fingerprints import sha256_context


class SnapshotKind(str, Enum):
    FULL = "full"
    ROLE_FILTERED = "role_filtered"


@dataclass(frozen=True, slots=True)
class FilteredSchema:
    snapshot: SchemaSnapshot
    ddl: str
    sha256: str
    policy_sha256: str
    business_role: str | None


_ATOMIC_TYPES = frozenset({
    "smallint", "integer", "bigint", "boolean", "text", "date", "real",
    "double precision", "bytea", "uuid", "json", "jsonb",
})
_CHARACTER_TYPE = re.compile(r"(character varying|varchar|character|char)(?:\(([1-9][0-9]{0,8})\))?")
_DECIMAL_TYPE = re.compile(r"(numeric|decimal)(?:\(([1-9][0-9]{0,3})(?:,([0-9]{1,4}))?\))?")
_TEMPORAL_TYPE = re.compile(r"(timestamp|time)(?:\(([0-6])\))?(?: (with|without) time zone)?")
_FK_ACTIONS = frozenset({"NO ACTION", "RESTRICT", "CASCADE", "SET NULL", "SET DEFAULT"})


def reviewed_sql_type(value: str) -> str:
    """Allow only reviewed builtin type syntax, never arbitrary catalog SQL.

    The current schema needs integers, booleans, text, dates, character lengths,
    and exact numerics. Additional user/extension/array/domain types require a
    separately reviewed source change. Numeric precision is bounded to 1000;
    negative scales are intentionally unsupported by this context profile.
    """
    if not isinstance(value, str) or len(value) > 100:
        raise ConfigurationError("Physical type metadata is unsupported.")
    normalized = value.strip().lower()
    if normalized in _ATOMIC_TYPES:
        return normalized.upper()
    match = _CHARACTER_TYPE.fullmatch(normalized)
    if match is not None:
        base, length = match.groups()
        if length is not None and int(length) > 10_485_760:
            raise ConfigurationError("Physical character length is outside the reviewed profile.")
        return base.upper() + (f"({int(length)})" if length is not None else "")
    match = _DECIMAL_TYPE.fullmatch(normalized)
    if match is not None:
        base, precision, scale = match.groups()
        if precision is None:
            return base.upper()
        if not 1 <= int(precision) <= 1000 or (scale is not None and not 0 <= int(scale) <= int(precision)):
            raise ConfigurationError("Physical numeric precision/scale is outside the reviewed profile.")
        suffix = str(int(precision)) + (f",{int(scale)}" if scale is not None else "")
        return f"{base.upper()}({suffix})"
    match = _TEMPORAL_TYPE.fullmatch(normalized)
    if match is not None:
        base, precision, zone = match.groups()
        return (
            base.upper()
            + (f"({precision})" if precision is not None else "")
            + (f" {zone.upper()} TIME ZONE" if zone is not None else "")
        )
    raise ConfigurationError("A physical SQL type requires an explicit reviewed context rule.")


def _require_snapshot(snapshot: SchemaSnapshot, matrix: PolicyMatrix) -> None:
    if type(snapshot) is not SchemaSnapshot or type(matrix) is not PolicyMatrix:
        raise ConfigurationError("Context compilation requires typed physical metadata and policy.")
    if snapshot.schema != matrix.schema or matrix.schema != "public":
        raise ConfigurationError("Context compilation requires the reviewed public application schema.")
    names = [table.name for table in snapshot.tables]
    if not names or len(names) != len(set(names)):
        raise ConfigurationError("Physical table metadata must be nonempty and unique.")
    for table in snapshot.tables:
        if type(table) is not TableDefinition:
            raise ConfigurationError("Physical table metadata must be typed.")
        require_identifier(table.name, label="context table")
        columns = [column.name for column in table.columns]
        ordinals = [column.ordinal for column in table.columns]
        if (
            not columns or len(columns) != len(set(columns))
            or len(ordinals) != len(set(ordinals))
            or any(type(ordinal) is not int or ordinal <= 0 for ordinal in ordinals)
        ):
            raise ConfigurationError("Physical columns require unique names and positive ordinals.")
        for column in table.columns:
            if type(column) is not ColumnDefinition:
                raise ConfigurationError("Physical columns must be typed catalog metadata.")
            require_identifier(column.name, label="context column")
            if type(column.nullable) is not bool:
                raise ConfigurationError("Physical nullability must be a boolean.")
            reviewed_sql_type(column.sql_type)
        for key in (table.primary_key, *table.unique_keys):
            if key and (len(key) != len(set(key)) or not set(key) <= set(columns)):
                raise ConfigurationError("Physical keys reference unavailable or duplicate columns.")
        if any(not key for key in table.unique_keys) or len(table.unique_keys) != len(set(table.unique_keys)):
            raise ConfigurationError("Physical unique keys must be nonempty and unique.")
        for key in table.foreign_keys:
            if type(key) is not ForeignKeyDefinition or (
                not key.columns or len(key.columns) != len(key.referenced_columns)
                or len(key.columns) != len(set(key.columns))
                or len(key.referenced_columns) != len(set(key.referenced_columns))
                or not set(key.columns) <= set(columns)
            ):
                raise ConfigurationError("Physical foreign-key metadata is incoherent.")


def _visible_relationships(snapshot: SchemaSnapshot) -> SchemaSnapshot:
    """Drop every FK whose schema/table/column endpoints are not visible."""
    visible = {table.name: set(column.name for column in table.columns) for table in snapshot.tables}
    tables = []
    for table in sorted(snapshot.tables, key=lambda item: item.name):
        retained = []
        for key in table.foreign_keys:
            if (
                key.referenced_schema != snapshot.schema
                or key.referenced_table not in visible
                or not set(key.columns) <= visible[table.name]
                or not set(key.referenced_columns) <= visible[key.referenced_table]
            ):
                continue
            if key.on_update not in _FK_ACTIONS or key.on_delete not in _FK_ACTIONS:
                raise ConfigurationError("A visible FK action is outside the reviewed profile.")
            retained.append(key)
        tables.append(TableDefinition(
            table.name, tuple(sorted(table.columns, key=lambda column: column.ordinal)),
            table.primary_key, tuple(sorted(table.unique_keys)),
            tuple(sorted(retained, key=lambda key: (
                key.columns, key.referenced_schema, key.referenced_table,
                key.referenced_columns, key.on_update, key.on_delete,
            ))),
        ))
    return SchemaSnapshot(snapshot.schema, tuple(tables))


def _column_list(columns: tuple[str, ...]) -> str:
    return ", ".join(quote_identifier(column) for column in columns)


def _emit(snapshot: SchemaSnapshot) -> str:
    statements = []
    for table in snapshot.tables:
        fields = [
            f"    {quote_identifier(column.name)} {reviewed_sql_type(column.sql_type)}"
            + ("" if column.nullable else " NOT NULL")
            for column in table.columns
        ]
        if table.primary_key:
            fields.append(f"    PRIMARY KEY ({_column_list(table.primary_key)})")
        fields.extend(f"    UNIQUE ({_column_list(key)})" for key in table.unique_keys)
        statements.append(
            f"CREATE TABLE {qualified_name(snapshot.schema, table.name)} (\n"
            + ",\n".join(fields) + "\n);"
        )
    # All CREATE statements precede references, including self references and
    # forward alphabetical dependencies. Original constraint names never emit.
    for table in snapshot.tables:
        for key in table.foreign_keys:
            statements.append(
                f"ALTER TABLE {qualified_name(snapshot.schema, table.name)} "
                f"ADD FOREIGN KEY ({_column_list(key.columns)}) "
                f"REFERENCES {qualified_name(key.referenced_schema, key.referenced_table)} "
                f"({_column_list(key.referenced_columns)}) "
                f"ON UPDATE {key.on_update} ON DELETE {key.on_delete};"
            )
    return "\n\n".join(statements) + "\n"


def compile_schema(
    snapshot: SchemaSnapshot, matrix: PolicyMatrix, business_role: str,
    *, snapshot_kind: SnapshotKind = SnapshotKind.FULL,
) -> FilteredSchema:
    """Compile only permitted DDL from full or previously role-filtered metadata.

    ROLE_FILTERED is a metadata declaration, not a capability to widen grants:
    table inventory must equal the role inventory, and every restricted column
    list must equal its visible physical list. A full snapshot always receives
    the existing policy/catalog projection. Hashing describes exact emitted text.
    """
    _require_snapshot(snapshot, matrix)
    role = matrix.role(business_role)
    if snapshot_kind is SnapshotKind.FULL:
        require_policy_schema(matrix, snapshot.columns_by_table)
        projected = filter_catalog(snapshot, matrix, role.name)
    elif snapshot_kind is SnapshotKind.ROLE_FILTERED:
        if {table.name for table in snapshot.tables} != set(matrix.permitted_tables(role.name)):
            raise ConfigurationError("Role-filtered metadata differs from the permitted table inventory.")
        for table in snapshot.tables:
            access = role.tables[table.name]
            if access.columns is not None and set(snapshot.columns_by_table[table.name]) != set(access.columns):
                raise ConfigurationError("Role-filtered metadata differs from the exact permitted columns.")
        projected = snapshot
    else:
        raise ConfigurationError("A defined physical snapshot kind is required.")
    projected = _visible_relationships(projected)
    ddl = _emit(projected)
    return FilteredSchema(projected, ddl, sha256_context(ddl), matrix.sha256, role.name)


def compile_full_schema(snapshot: SchemaSnapshot, matrix: PolicyMatrix) -> FilteredSchema:
    """Full physical fixture context for an already-authorized harness caller.

    This pure compiler grants no harness authority. builder's separate harness
    capability must guard disclosure. E2 v1 must use frozen baseline bytes, not
    this generated rendering: changing its DDL would alter the baseline prompt.
    """
    _require_snapshot(snapshot, matrix)
    require_policy_schema(matrix, snapshot.columns_by_table)
    physical = _visible_relationships(snapshot)
    ddl = _emit(physical)
    return FilteredSchema(physical, ddl, sha256_context(ddl), matrix.sha256, None)
