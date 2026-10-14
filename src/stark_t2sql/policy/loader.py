"""Immutable access-matrix loading and future schema preflight interfaces.

No matrix is loaded on import. Later policy, catalog and test-source consumers
share one loaded matrix; permission rules are not copied into another catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from ..contracts import RowScopeKind
from ..errors import ConfigurationError, MissingDependencyError, SourceReadError
from ..utils.fingerprints import sha256_bytes


_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}")
_ROLE_LOGINS = {
    "app_payroll": "stark_payroll_login",
    "app_hr_bp": "stark_hr_login",
    "app_sales_mgr": "stark_sales_login",
}


def require_identifier(value: object, *, label: str) -> str:
    """Require a simple lowercase identifier; SQL emitters still quote it."""
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ConfigurationError(f"Invalid policy identifier for {label}.")
    if value.startswith("pg_"):
        raise ConfigurationError(f"Reserved policy identifier for {label}.")
    return value


@dataclass(frozen=True, slots=True)
class TableAccess:
    columns: tuple[str, ...] | None
    row_scope: RowScopeKind

    def __post_init__(self) -> None:
        if self.columns is not None:
            columns = tuple(self.columns)
            if not columns or len(set(columns)) != len(columns):
                raise ConfigurationError("Restricted column lists must be nonempty and unique.")
            for column in columns:
                require_identifier(column, label="column")
            object.__setattr__(self, "columns", columns)
        if not isinstance(self.row_scope, RowScopeKind):
            raise ConfigurationError("A supported row-scope kind is required.")


@dataclass(frozen=True, slots=True)
class RolePolicy:
    name: str
    login_role: str
    tables: Mapping[str, TableAccess]

    def __post_init__(self) -> None:
        require_identifier(self.name, label="business role")
        require_identifier(self.login_role, label="login role")
        for table, access in self.tables.items():
            require_identifier(table, label="table")
            if not isinstance(access, TableAccess):
                raise ConfigurationError("Table entitlements must be typed TableAccess values.")
        object.__setattr__(self, "tables", MappingProxyType(dict(self.tables)))


@dataclass(frozen=True, slots=True)
class PolicyMatrix:
    version: str
    schema: str
    tables: tuple[str, ...]
    rls_tables: tuple[str, ...]
    roles: tuple[RolePolicy, ...]
    sha256: str

    def __post_init__(self) -> None:
        require_identifier(self.schema, label="schema")
        object.__setattr__(self, "tables", tuple(self.tables))
        object.__setattr__(self, "rls_tables", tuple(self.rls_tables))
        object.__setattr__(self, "roles", tuple(self.roles))
        if not isinstance(self.version, str) or not self.version.strip():
            raise ConfigurationError("Policy version must be nonempty text.")
        if len(set(self.tables)) != len(self.tables) or len(set(self.rls_tables)) != len(self.rls_tables):
            raise ConfigurationError("Policy table lists must be unique.")
        for table in self.tables:
            require_identifier(table, label="table")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise ConfigurationError("The matrix requires its actual SHA-256 fingerprint.")
        if len({role.name for role in self.roles}) != len(self.roles):
            raise ConfigurationError("Business roles must be unique.")

    def role(self, name: str) -> RolePolicy:
        for role in self.roles:
            if role.name == name:
                return role
        raise ConfigurationError(f"Unknown policy role: {name}")

    def permitted_tables(self, role: str) -> tuple[str, ...]:
        return tuple(sorted(self.role(role).tables))

    def permitted_columns(self, role: str, table: str, schema_columns: tuple[str, ...]) -> tuple[str, ...]:
        access = self.role(role).tables.get(table)
        if access is None:
            return ()
        if access.columns is None:
            return tuple(schema_columns)
        unknown = set(access.columns) - set(schema_columns)
        if unknown:
            raise ConfigurationError(f"Matrix columns are absent from the schema for {table}.")
        # Physical ordinal order is retained; role-filtered output is deterministic.
        return tuple(column for column in schema_columns if column in access.columns)


@dataclass(frozen=True, slots=True)
class PolicyIssue:
    code: str
    detail: str


def _mapping(value: object, *, label: str) -> dict:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ConfigurationError(f"{label} must be a string-keyed mapping.")
    return value


def _exact_keys(value: dict, keys: set[str], *, label: str) -> None:
    if set(value) != keys:
        raise ConfigurationError(f"{label} has missing or unsupported fields.")


def _names(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigurationError(f"{label} must be a nonempty list.")
    names = tuple(require_identifier(item, label=label) for item in value)
    if len(set(names)) != len(names):
        raise ConfigurationError(f"{label} contains duplicates.")
    return names


def load_policy(path: str | Path, *, max_bytes: int = 1_048_576) -> PolicyMatrix:
    """Read real YAML later, rejecting aliases, duplicates and unknown fields.

    PyYAML is a later environment dependency; no package is installed here.
    Hashing and parsing use the same read bytes, avoiding mismatched fingerprints.
    """
    if type(max_bytes) is not int or max_bytes < 1:
        raise ConfigurationError("A positive matrix byte limit is required.")
    try:
        with Path(path).open("rb") as source:
            source_bytes = source.read(max_bytes + 1)
    except FileNotFoundError as exc:
        raise MissingDependencyError(f"Access matrix is absent: {path}") from exc
    except (OSError, ValueError, TypeError) as exc:
        raise SourceReadError("The access matrix could not be read.") from exc
    if len(source_bytes) > max_bytes:
        raise ConfigurationError("Access matrix exceeds the configured source size limit.")
    try:
        text = source_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SourceReadError("The access matrix must be UTF-8 source.") from exc
    try:
        import yaml
    except ImportError as exc:
        raise MissingDependencyError("PyYAML is required to load the access matrix.") from exc

    class StrictLoader(yaml.SafeLoader):
        def compose_node(self, parent, index):
            if self.check_event(yaml.events.AliasEvent):
                raise ConfigurationError("YAML aliases are not permitted in the access matrix.")
            return super().compose_node(parent, index)

        def construct_mapping(self, node, deep=False):
            result = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str) or key in result:
                    raise ConfigurationError("YAML mapping keys must be unique text.")
                result[key] = self.construct_object(value_node, deep=deep)
            return result

    try:
        document = _mapping(yaml.load(text, Loader=StrictLoader), label="matrix")
    except yaml.YAMLError as exc:
        raise ConfigurationError("The access matrix is not supported YAML.") from exc
    _exact_keys(document, {"version", "schema", "tables", "rls_tables", "roles"}, label="matrix")
    tables = _names(document["tables"], label="tables")
    rls_tables = _names(document["rls_tables"], label="RLS tables")
    roles_document = _mapping(document["roles"], label="roles")
    if set(roles_document) != set(_ROLE_LOGINS):
        raise ConfigurationError("This MVP requires exactly the three approved business roles.")
    roles = []
    for name in sorted(roles_document):
        role_document = _mapping(roles_document[name], label="role")
        _exact_keys(role_document, {"login_role", "tables"}, label="role")
        if role_document["login_role"] != _ROLE_LOGINS[name]:
            raise ConfigurationError(f"Unexpected login-role reference for {name}.")
        accesses = {}
        for table, raw_access in sorted(_mapping(role_document["tables"], label="role tables").items()):
            access_document = _mapping(raw_access, label="table access")
            _exact_keys(access_document, {"columns", "row_scope"}, label="table access")
            raw_columns = access_document["columns"]
            columns = None if raw_columns == "*" else _names(raw_columns, label="columns")
            try:
                row_scope = RowScopeKind(access_document["row_scope"])
            except (ValueError, TypeError) as exc:
                raise ConfigurationError("Unsupported row-scope kind.") from exc
            accesses[table] = TableAccess(columns, row_scope)
        roles.append(RolePolicy(name, role_document["login_role"], accesses))
    matrix = PolicyMatrix(
        document["version"], require_identifier(document["schema"], label="schema"),
        tables, rls_tables, tuple(roles), sha256_bytes(source_bytes),
    )
    # Structural policy requirements need no live database. Physical references
    # are handled by the callable preflight below, not by a hidden connection.
    if set(matrix.rls_tables) != {"employees", "leave_balances"}:
        raise ConfigurationError("The approved RLS table set is employees and leave_balances.")
    if not set(matrix.rls_tables) <= set(matrix.tables):
        raise ConfigurationError("RLS references an unknown matrix table.")
    if any(set(role.tables) - set(matrix.tables) for role in matrix.roles):
        raise ConfigurationError("A role references an unknown matrix table.")
    if any("hr_bp_assignments" in role.tables for role in matrix.roles):
        raise ConfigurationError("Direct business-role assignment-table access is not approved.")
    return matrix


def preflight_policy(
    matrix: PolicyMatrix, schema_columns: Mapping[str, tuple[str, ...]]
) -> tuple[PolicyIssue, ...]:
    """Report unknown physical references and incoherent scopes when called later."""
    issues = []
    if {role.name for role in matrix.roles} != set(_ROLE_LOGINS):
        issues.append(PolicyIssue("UNKNOWN_ROLE", "Business roles differ from the approved MVP roles."))
    for table in sorted(set(matrix.tables) - set(schema_columns)):
        issues.append(PolicyIssue("UNKNOWN_TABLE", f"Missing matrix table: {table}"))
    for table in sorted(set(schema_columns) - set(matrix.tables)):
        issues.append(PolicyIssue("UNMANAGED_TABLE", f"Unmanaged application table: {table}"))
    if set(matrix.rls_tables) != {"employees", "leave_balances"}:
        issues.append(PolicyIssue("RLS_SCOPE", "The approved RLS table set differs."))
    required_scope_columns = {
        "employees": {"employee_id", "department_id", "manager_id"},
        "departments": {"department_id", "division_id"},
        "hr_bp_assignments": {"employee_id", "division_id", "effective_to"},
        "leave_balances": {"employee_id"},
    }
    for table, columns in sorted(required_scope_columns.items()):
        for column in sorted(columns - set(schema_columns.get(table, ()))):
            issues.append(PolicyIssue("SCOPE_COLUMN", f"Missing scope column: {table}.{column}"))
    for role in sorted(matrix.roles, key=lambda item: item.name):
        if _ROLE_LOGINS.get(role.name) != role.login_role:
            issues.append(PolicyIssue("UNKNOWN_LOGIN_ROLE", f"Unexpected login role for {role.name}"))
        for table, access in sorted(role.tables.items()):
            if table not in matrix.tables or table not in schema_columns:
                issues.append(PolicyIssue("UNKNOWN_TABLE", f"Unknown role table: {role.name}:{table}"))
            if access.columns is not None:
                for column in sorted(set(access.columns) - set(schema_columns.get(table, ()))):
                    issues.append(PolicyIssue("UNKNOWN_COLUMN", f"Unknown column: {role.name}:{table}.{column}"))
            if access.row_scope is not RowScopeKind.ALL and table not in matrix.rls_tables:
                issues.append(PolicyIssue("RLS_SCOPE", f"Scoped table has no RLS: {table}"))
            if access.row_scope in {RowScopeKind.DIRECT_REPORTS, RowScopeKind.ASSIGNED_DIVISIONS} and table != "employees":
                issues.append(PolicyIssue("RLS_SCOPE", f"Employee scope used for another table: {table}"))
            if access.row_scope is RowScopeKind.VIA_EMPLOYEES:
                parent = role.tables.get("employees")
                if table != "leave_balances" or parent is None or (
                    parent.columns is not None and "employee_id" not in parent.columns
                ):
                    issues.append(PolicyIssue("RLS_SCOPE", f"Invalid via-employees scope: {role.name}:{table}"))
            if table == "hr_bp_assignments":
                issues.append(PolicyIssue("DIRECT_ASSIGNMENT_ACCESS", f"Forbidden direct assignment access: {role.name}"))
    return tuple(issues)


def require_policy_schema(matrix: PolicyMatrix, schema_columns: Mapping[str, tuple[str, ...]]) -> None:
    issues = preflight_policy(matrix, schema_columns)
    if issues:
        raise ConfigurationError("Policy/schema preflight: " + "; ".join(issue.detail for issue in issues))


@dataclass(frozen=True, slots=True)
class AuthorizationSpec:
    """Expected permission metadata, never an observed authorization result."""

    business_role: str
    login_role: str
    table: str
    column: str | None
    expected_select: bool
    row_scope: RowScopeKind | None


def authorization_specs(
    matrix: PolicyMatrix, schema_columns: Mapping[str, tuple[str, ...]]
) -> tuple[AuthorizationSpec, ...]:
    """Generate future table/column authorization specifications from one matrix."""
    require_policy_schema(matrix, schema_columns)
    specifications = []
    for role in sorted(matrix.roles, key=lambda item: item.name):
        for table in sorted(matrix.tables):
            access = role.tables.get(table)
            scope = access.row_scope if access is not None else None
            specifications.append(AuthorizationSpec(role.name, role.login_role, table, None,
                access is not None and access.columns is None, scope))
            permitted = set(matrix.permitted_columns(role.name, table, schema_columns[table]))
            for column in schema_columns[table]:
                specifications.append(AuthorizationSpec(role.name, role.login_role, table,
                    column, column in permitted, scope))
    return tuple(specifications)
