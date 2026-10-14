"""Matrix/grant/RLS source contracts, distinct from future installed-DB evidence."""
import pytest
from types import SimpleNamespace

from stark_t2sql.contracts import RowScopeKind
from stark_t2sql.errors import MissingDependencyError
from stark_t2sql.policy.compiler import CompileSettings
from stark_t2sql.policy.grants import grant_statements
from stark_t2sql.policy.privileges import set_config_statements, trusted_search_path
from stark_t2sql.policy.rls import rls_statements, scope_function_statements


def test_matrix_scopes_and_column_entitlements(matrix):
    assert matrix.role("app_payroll").tables["employees"].row_scope is RowScopeKind.ALL
    assert matrix.role("app_hr_bp").tables["employees"].row_scope is RowScopeKind.ASSIGNED_DIVISIONS
    assert matrix.role("app_hr_bp").tables["leave_balances"].row_scope is RowScopeKind.VIA_EMPLOYEES
    sales = matrix.role("app_sales_mgr")
    assert sales.tables["employees"].row_scope is RowScopeKind.DIRECT_REPORTS
    assert set(sales.tables["employees"].columns) == {"employee_id", "first_name", "last_name", "department_id", "manager_id"}
    assert "employee_number" not in matrix.role("app_hr_bp").tables["employees"].columns
    assert "employee_compensation" not in matrix.role("app_hr_bp").tables
    assert "hr_bp_assignments" not in matrix.role("app_payroll").tables


def test_grant_output_matches_matrix_columns(matrix, schema_metadata):
    statements = grant_statements(matrix, schema_metadata.columns_by_table, definer_owner="stark_scope_owner")
    for role in matrix.roles:
        for table, access in role.tables.items():
            target = f'ON TABLE "public"."{table}" TO "{role.name}"'
            if access.columns is None:
                assert any("GRANT SELECT " in item and target in item for item in statements)
            else:
                assert any("GRANT SELECT (" in item and target in item and all(f'"{column}"' in item for column in access.columns) for item in statements)
    assert not any('GRANT SELECT ON TABLE "public"."employees" TO "app_sales_mgr"' in item for item in statements)


def test_force_rls_has_explicit_payroll_allow_and_child_scope(matrix):
    text = "\n".join(rls_statements(matrix))
    for table in ("employees", "leave_balances"):
        assert f'ALTER TABLE "public"."{table}" FORCE ROW LEVEL SECURITY;' in text
    assert 'FOR SELECT TO "app_payroll" USING (true)' in text
    assert '"employees"."manager_id" = NULLIF' in text
    assert '"public"."employees" AS scope_employee' in text
    assert "effective_to" not in text  # HR dates live solely in the definer helper.


def test_hr_definer_qualified_source_fixed_path_and_execute_acl(matrix):
    text = "\n".join(scope_function_statements(matrix, definer_owner="stark_scope_owner"))
    assert "SECURITY DEFINER" in text and "STABLE" in text
    assert 'FROM "public"."hr_bp_assignments"' in text
    assert 'SET search_path = "pg_catalog", "public", "pg_temp"' in text
    assert "assignment.effective_to IS NULL" in text
    assert 'GRANT EXECUTE ON FUNCTION "public"."hr_bp_current_divisions"() TO "app_hr_bp"' in text
    assert 'ALTER FUNCTION "public"."hr_bp_current_divisions"() OWNER TO "stark_scope_owner"' in text
    assert trusted_search_path("public").endswith('"pg_temp"')


def test_measurements_are_mandatory_without_fabricating_them():
    with pytest.raises(MissingDependencyError):
        CompileSettings("stark_scope_owner")


def test_set_config_execute_is_login_only(matrix):
    # This SQL producer does not inspect CompileSettings fields.
    text = "\n".join(set_config_statements(matrix, SimpleNamespace(definer_owner="stark_scope_owner")))
    assert "set_config" in text and "FROM PUBLIC" in text
    for role in matrix.roles:
        assert f'"{role.login_role}"' in text.split("GRANT EXECUTE", 1)[1]
        assert not any("GRANT EXECUTE" in item and f'TO "{role.name}"' in item for item in text.splitlines())


def test_identity_spoof_is_a_documented_single_layer_dependency(project_root):
    frd = (project_root / "STARK_T2SQL FRD 1.8.txt").read_text(encoding="utf-8")
    assert "KNOWN single-layer dependency" in frd
    assert "WITHIN the same business role" in frd
    assert "equivalent to real authentication" in frd
