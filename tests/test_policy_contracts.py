"""Matrix/grant/RLS source contracts, distinct from future installed-DB evidence."""
from hashlib import sha256

import pytest

from seed_data import TABLE_COLUMNS
from stark_t2sql.contracts import RowScopeKind
from stark_t2sql.errors import ConfigurationError, MissingDependencyError
from stark_t2sql.policy.compiler import CompileSettings, compile_policy
from stark_t2sql.policy.grants import grant_statements
from stark_t2sql.policy.loader import preflight_policy
from stark_t2sql.policy.privileges import (
    login_default_statements, managed_role_names, role_statements,
    schema_statements, set_config_statements, trusted_search_path,
)
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


@pytest.mark.parametrize("baseline", (None, "stark_eval_baseline_login"))
def test_grant_output_matches_matrix_columns(matrix, baseline):
    # Frozen R02 column contracts, not externally recorded/live catalog evidence.
    statements = grant_statements(matrix, TABLE_COLUMNS, definer_owner="stark_scope_owner",
                                  baseline_eval_login=baseline)
    expected = set()
    for role in matrix.roles:
        for table, access in role.tables.items():
            target = f'ON TABLE "public"."{table}" TO "{role.name}"'
            if access.columns is None:
                expected.add(f"GRANT SELECT {target};")
            else:
                columns = ", ".join(f'"{column}"' for column in TABLE_COLUMNS[table] if column in access.columns)
                expected.add(f"GRANT SELECT ({columns}) {target};")
    expected.add('GRANT SELECT ("employee_id", "division_id", "effective_to") '
                 'ON TABLE "public"."hr_bp_assignments" TO "stark_scope_owner";')
    if baseline:
        expected.update(f'GRANT SELECT ON TABLE "public"."{table}" TO "{baseline}";' for table in TABLE_COLUMNS)
    assert {item for item in statements if item.startswith("GRANT SELECT")} == expected
    assert len([item for item in statements if item.startswith("GRANT SELECT")]) == len(expected)
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
    text = "\n".join(set_config_statements(matrix, unit_settings()))
    assert "set_config" in text and "FROM PUBLIC" in text
    for role in matrix.roles:
        assert f'"{role.login_role}"' in text.split("GRANT EXECUTE", 1)[1]
        assert not any("GRANT EXECUTE" in item and f'TO "{role.name}"' in item for item in text.splitlines())


def test_identity_spoof_is_a_documented_single_layer_dependency(project_root):
    frd = (project_root / "STARK_T2SQL FRD 1.8.txt").read_text(encoding="utf-8")
    assert "KNOWN single-layer dependency" in frd
    assert "WITHIN the same business role" in frd
    assert "equivalent to real authentication" in frd


def unit_settings(baseline=None):
    """Synthetic compiler inputs only; these are not measured runtime budgets."""
    return CompileSettings(
        "stark_scope_owner", work_mem_kib=64, temp_file_limit_kib=10000,
        measurement_sha256=sha256(b"R03 unit resource input, not a deployment measurement").hexdigest(),
        measurement_provenance="R03 offline unit input; no live resource measurement",
        baseline_eval_login=baseline,
    )


@pytest.mark.parametrize("baseline", (None, "stark_eval_baseline_login"))
def test_baseline_creation_defaults_and_cleanup_are_explicit(matrix, baseline):
    settings = unit_settings(baseline)
    names = managed_role_names(matrix, settings.definer_owner, baseline)
    roles = "\n".join(role_statements(matrix, settings))
    defaults = login_default_statements(matrix, settings)
    if baseline is None:
        assert len(names) == 7
        assert "stark_eval_baseline_login" not in roles + "\n".join(defaults)
        return
    assert names[-1] == baseline and len(names) == 8
    flags = "LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION"
    assert f'CREATE ROLE "{baseline}" {flags}' in roles
    assert f'ALTER ROLE "{baseline}" {flags};' in roles
    assert f'ALTER ROLE "{baseline}" RESET ALL;' in roles
    assert baseline in roles.split("$stark_role_safety$;", 1)[0]
    assert baseline in roles.split("DO $stark_memberships$", 1)[1]
    assert all(f'"{baseline}"' not in item for item in role_statements(matrix, settings) if item.startswith("GRANT "))
    expected = {
        "statement_timeout": "E'15000ms'", "default_transaction_read_only": "E'on'",
        "row_security": "E'on'", "work_mem": "E'64kB'", "temp_file_limit": "E'10000kB'",
        "search_path": '"pg_catalog", "public", "pg_temp"',
    }
    for key, value in expected.items():
        assert f'ALTER ROLE "{baseline}" SET {key} = {value};' in defaults
    scoped = [item for item in defaults if f"E'{baseline}'" in item]
    assert len(scoped) == 2 and "IN DATABASE %I RESET ALL" in scoped[0]
    for key in expected:
        assert f"SET {key} = " in scoped[1]
    assert "pg_catalog.current_database()" in scoped[1]
    for statements in (schema_statements(matrix, settings),
                       grant_statements(matrix, TABLE_COLUMNS, definer_owner=settings.definer_owner, baseline_eval_login=baseline),
                       scope_function_statements(matrix, definer_owner=settings.definer_owner, baseline_eval_login=baseline),
                       set_config_statements(matrix, settings)):
        # The separate PUBLIC schema-CREATE revoke intentionally names no role.
        revokes = [item for item in statements if "REVOKE" in item and not item.startswith("REVOKE CREATE ON SCHEMA")]
        assert revokes and all(baseline in item for item in revokes)
    function_grants = "\n".join(scope_function_statements(matrix, definer_owner=settings.definer_owner, baseline_eval_login=baseline)
                                 + set_config_statements(matrix, settings))
    assert not any(baseline in item for item in function_grants.splitlines() if item.startswith("GRANT EXECUTE"))


@pytest.mark.parametrize("baseline", (None, "stark_eval_baseline_login"))
def test_compile_is_repeatable_and_production_has_no_baseline_access(matrix, baseline):
    settings = unit_settings(baseline)
    assert preflight_policy(matrix, TABLE_COLUMNS) == ()
    plan = compile_policy(matrix, TABLE_COLUMNS, settings)
    assert plan == compile_policy(matrix, dict(reversed(list(TABLE_COLUMNS.items()))), settings)
    assert plan.sql_text == compile_policy(matrix, TABLE_COLUMNS, settings).sql_text
    assert ("stark_eval_baseline_login" in plan.sql_text) is bool(baseline)
    for table in matrix.rls_tables:
        policy = (f'CREATE POLICY "stark_select_stark_eval_baseline_login" ON "public"."{table}" '
                  'AS PERMISSIVE FOR SELECT TO "stark_eval_baseline_login" USING (true);')
        assert (policy in plan.statements) is bool(baseline)
    production = compile_policy(matrix, TABLE_COLUMNS, unit_settings()).statements
    business_grants = lambda statements: {line for line in statements if line.startswith("GRANT SELECT") and 'TO "app_' in line}
    assert business_grants(production) == business_grants(plan.statements)
    assert plan.statements[-2].startswith("REVOKE ALL PRIVILEGES ON FUNCTION pg_catalog.set_config")
    assert plan.statements[-1].startswith("GRANT EXECUTE ON FUNCTION pg_catalog.set_config")


@pytest.mark.parametrize("table", tuple(TABLE_COLUMNS))
def test_compile_refuses_every_missing_table(matrix, table):
    columns = dict(TABLE_COLUMNS)
    del columns[table]
    with pytest.raises(ConfigurationError, match="preflight"):
        compile_policy(matrix, columns, unit_settings())


# Every explicit entitlement/scope column, independently enumerated from the FRD.
@pytest.mark.parametrize("table,column", (
    *(("employees", name) for name in ("employee_id", "first_name", "last_name", "email", "hire_date",
       "termination_date", "status", "employment_type", "department_id", "position_id", "manager_id", "location_id", "legal_entity")),
    ("departments", "department_id"), ("departments", "division_id"), ("leave_balances", "employee_id"),
    ("hr_bp_assignments", "employee_id"), ("hr_bp_assignments", "division_id"), ("hr_bp_assignments", "effective_to"),
))
def test_compile_refuses_missing_entitlement_or_scope_column(matrix, table, column):
    columns = dict(TABLE_COLUMNS)
    columns[table] = tuple(name for name in columns[table] if name != column)
    with pytest.raises(ConfigurationError, match="preflight"):
        compile_policy(matrix, columns, unit_settings())


@pytest.mark.parametrize("baseline", (
    "app_payroll", "app_hr_bp", "app_sales_mgr", "stark_payroll_login", "stark_hr_login", "stark_sales_login",
    "stark_scope_owner", "postgres", "public", "pg_monitor", "unsafe role", "x" * 51,
))
def test_baseline_cannot_reuse_managed_or_reserved_identities(matrix, baseline):
    with pytest.raises(ConfigurationError):
        compile_policy(matrix, TABLE_COLUMNS, unit_settings(baseline))


def test_compile_refuses_extra_unmanaged_table(matrix):
    with pytest.raises(ConfigurationError, match="Unmanaged application table"):
        compile_policy(matrix, dict(TABLE_COLUMNS, unrelated=("secret",)), unit_settings())
