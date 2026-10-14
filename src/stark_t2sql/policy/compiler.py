"""Pure ordered policy-to-SQL compilation, with no database connection or output file.

Only the separate administrative policy_apply path may apply a future plan.
Compilation requires real supplied database-budget measurements and schema
metadata. Their provenance is an input dependency, never fabricated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..contracts import RowScopeKind
from ..errors import ConfigurationError, MissingDependencyError
from .grants import grant_statements
from .loader import PolicyMatrix, require_policy_schema
from .privileges import (
    login_default_statements,
    quote_identifier,
    require_definer_name,
    role_statements,
    schema_statements,
    set_config_statements,
    trusted_search_path,
)
from .rls import rls_statements, scope_function_statements


@dataclass(frozen=True, slots=True)
class CompileSettings:
    """Trusted setup inputs; absent measured work/temp budgets stop compilation.

    measurement_sha256 hashes the actual supplied measurement artifact;
    measurement_provenance identifies it. Supplying fields is not proof of
    measurement quality. The future administrative path owns review of inputs.
    Initial statement timeout comes from FR-6.2, not a guessed resource budget.
    """

    definer_owner: str
    statement_timeout_ms: int = 15000
    work_mem_kib: int | None = None
    temp_file_limit_kib: int | None = None
    measurement_sha256: str | None = None
    measurement_provenance: str | None = None

    def __post_init__(self) -> None:
        quote_identifier(self.definer_owner)
        if type(self.statement_timeout_ms) is not int or not 0 < self.statement_timeout_ms <= 2147483647:
            raise ConfigurationError("statement_timeout_ms must be a positive PostgreSQL int32 value.")
        if self.work_mem_kib is None or self.temp_file_limit_kib is None:
            raise MissingDependencyError("Measured work_mem and temporary-file budget inputs are unavailable.")
        if type(self.work_mem_kib) is not int or not 64 <= self.work_mem_kib <= 2147483647:
            raise ConfigurationError("Measured work_mem must fit PostgreSQL's KiB range (at least 64).")
        if type(self.temp_file_limit_kib) is not int or not 0 <= self.temp_file_limit_kib <= 2147483647:
            raise ConfigurationError("Measured temp_file_limit must be a bounded nonnegative KiB value.")
        if self.measurement_sha256 is None or self.measurement_provenance is None:
            raise MissingDependencyError("Resource measurement hash and provenance are required.")
        if (
            not isinstance(self.measurement_sha256, str)
            or len(self.measurement_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.measurement_sha256)
        ):
            raise ConfigurationError("The measurement hash must be lowercase SHA-256 hex.")
        if not isinstance(self.measurement_provenance, str) or not self.measurement_provenance.strip():
            raise ConfigurationError("Resource measurement provenance must be nonempty text.")


@dataclass(frozen=True, slots=True)
class CompiledPolicy:
    matrix_sha256: str
    schema: str
    statements: tuple[str, ...]
    settings: CompileSettings

    @property
    def sql_text(self) -> str:
        """Reviewable text only; transaction control belongs to policy_apply."""
        return "\n\n".join(self.statements) + "\n"


def _require_scope_dependencies(
    matrix: PolicyMatrix, schema_columns: Mapping[str, tuple[str, ...]]
) -> None:
    required_columns = {
        "employees": ("employee_id", "department_id", "manager_id"),
        "departments": ("department_id", "division_id"),
        "leave_balances": ("employee_id",),
        "hr_bp_assignments": ("employee_id", "division_id", "effective_to"),
    }
    for table, columns in required_columns.items():
        actual = schema_columns.get(table, ())
        if any(column not in actual for column in columns):
            raise ConfigurationError(f"Schema columns required by policy scope are absent on {table}.")
    if tuple(matrix.rls_tables) != ("employees", "leave_balances"):
        raise ConfigurationError("FRD 1.8 requires employees and leave_balances RLS in that order.")
    for role in matrix.roles:
        for table, access in role.tables.items():
            if table not in matrix.rls_tables and access.row_scope is not RowScopeKind.ALL:
                raise ConfigurationError("A scoped table must have a generated RLS boundary.")
            if access.row_scope is RowScopeKind.VIA_EMPLOYEES:
                employees = role.tables.get("employees")
                if employees is None or (
                    employees.columns is not None and "employee_id" not in employees.columns
                ):
                    raise ConfigurationError("Child scope requires the caller's visible employee_id column.")


def compile_policy(
    matrix: PolicyMatrix,
    schema_columns: Mapping[str, tuple[str, ...]],
    settings: CompileSettings,
) -> CompiledPolicy:
    """Compile a single loaded matrix and metadata snapshot without side effects.

    This function does not read schema.sql, connect, execute, serialize policy
    SQL to disk, or establish any runtime security claim. Applying its final
    set_config statements before a future fixture restore is forbidden.
    """
    if not isinstance(matrix, PolicyMatrix) or not isinstance(settings, CompileSettings):
        raise ConfigurationError("Compilation requires PolicyMatrix and CompileSettings inputs.")
    require_policy_schema(matrix, schema_columns)
    require_definer_name(settings.definer_owner, matrix)
    trusted_search_path(matrix.schema)
    _require_scope_dependencies(matrix, schema_columns)
    statements = (
        role_statements(matrix, settings)
        + schema_statements(matrix, settings)
        + grant_statements(matrix, schema_columns, definer_owner=settings.definer_owner)
        + scope_function_statements(matrix, definer_owner=settings.definer_owner)
        + rls_statements(matrix)
        + login_default_statements(matrix, settings)
        + set_config_statements(matrix, settings)
    )
    return CompiledPolicy(
        matrix_sha256=matrix.sha256,
        schema=matrix.schema,
        statements=statements,
        settings=settings,
    )
