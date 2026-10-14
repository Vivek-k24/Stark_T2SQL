"""Matrix-driven RLS and the governed zero-argument HR scope function as SQL text."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..contracts import RowScopeKind
from ..errors import ConfigurationError
from .privileges import (
    managed_role_names,
    qualified_name,
    quote_identifier,
    quote_literal,
    trusted_search_path,
)

if TYPE_CHECKING:
    from .loader import PolicyMatrix


def principal_expression() -> str:
    # Missing and transaction-reset empty settings both yield NULL, hence no match.
    return "NULLIF(pg_catalog.current_setting('app.principal_id', true), '')::int"


def scope_function_statements(matrix: PolicyMatrix, *, definer_owner: str) -> tuple[str, ...]:
    function = qualified_name(matrix.schema, "hr_bp_current_divisions") + "()"
    assignments = qualified_name(matrix.schema, "hr_bp_assignments")
    owner = quote_identifier(definer_owner)
    principals = "PUBLIC, " + ", ".join(
        quote_identifier(name) for name in managed_role_names(matrix, definer_owner)
    )
    return (
        f"""CREATE OR REPLACE FUNCTION {function}
RETURNS SETOF integer
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = {trusted_search_path(matrix.schema)}
AS $stark_hr_scope$
    SELECT DISTINCT assignment.division_id
    FROM {assignments} AS assignment
    WHERE assignment.employee_id = {principal_expression()}
      AND assignment.effective_to IS NULL
    ORDER BY assignment.division_id
$stark_hr_scope$;""",
        f"ALTER FUNCTION {function} OWNER TO {owner};",
        f"REVOKE ALL PRIVILEGES ON FUNCTION {function} FROM {principals} CASCADE;",
        f"GRANT EXECUTE ON FUNCTION {function} TO {quote_identifier('app_hr_bp')};",
    )


def _using_expression(matrix: PolicyMatrix, table: str, scope: RowScopeKind) -> str:
    if scope is RowScopeKind.ALL:
        return "true"
    if scope is RowScopeKind.DIRECT_REPORTS and table == "employees":
        return f'{quote_identifier(table)}.{quote_identifier("manager_id")} = {principal_expression()}'
    if scope is RowScopeKind.ASSIGNED_DIVISIONS and table == "employees":
        return (
            f"EXISTS (SELECT 1 FROM {qualified_name(matrix.schema, 'departments')} AS scope_department "
            f"WHERE scope_department.department_id = {quote_identifier(table)}.department_id "
            f"AND scope_department.division_id IN (SELECT scope_division.division_id FROM "
            f"{qualified_name(matrix.schema, 'hr_bp_current_divisions')}() "
            "AS scope_division(division_id)))"
        )
    if scope is RowScopeKind.VIA_EMPLOYEES and table == "leave_balances":
        # This subquery runs as the caller: employees RLS supplies the same scope.
        return (
            f"EXISTS (SELECT 1 FROM {qualified_name(matrix.schema, 'employees')} AS scope_employee "
            f"WHERE scope_employee.employee_id = {quote_identifier(table)}.employee_id)"
        )
    raise ConfigurationError(f"Unsupported RLS row scope for table {table}.")


def rls_statements(matrix: PolicyMatrix) -> tuple[str, ...]:
    tables = ", ".join(quote_literal(table) for table in matrix.rls_tables)
    statements = [
        # A stale permissive policy can widen scope even after ACLs are repaired.
        f"""DO $stark_remove_policies$
DECLARE target record;
BEGIN
    FOR target IN
        SELECT c.relname, p.polname
        FROM pg_catalog.pg_policy AS p
        JOIN pg_catalog.pg_class AS c ON c.oid = p.polrelid
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = {quote_literal(matrix.schema)} AND c.relname IN ({tables})
        ORDER BY c.relname, p.polname
    LOOP
        EXECUTE pg_catalog.format('DROP POLICY %I ON %I.%I',
            target.polname, {quote_literal(matrix.schema)}, target.relname);
    END LOOP;
END
$stark_remove_policies$;""",
    ]
    for table in matrix.rls_tables:
        target = qualified_name(matrix.schema, table)
        statements.append(f"ALTER TABLE {target} ENABLE ROW LEVEL SECURITY;")
        statements.append(f"ALTER TABLE {target} FORCE ROW LEVEL SECURITY;")
        for role in matrix.roles:
            access = role.tables.get(table)
            if access is None:
                continue
            using = _using_expression(matrix, table, access.row_scope)
            policy_name = quote_identifier(f"stark_select_{role.name}")
            statements.append(
                f"CREATE POLICY {policy_name} ON {target} AS PERMISSIVE "
                f"FOR SELECT TO {quote_identifier(role.name)} USING ({using});"
            )
    return tuple(statements)
