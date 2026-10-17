"""Owner-run STARK security-policy installation and read-only database checks.

Run ``python -m ops.install_policy <mode> --help``. Modes:

``inspect``  Read-only administrative inventory: server identity, managed
             roles, RLS/policies, functions, ACLs and fixture row counts.
``apply``    Install the compiler-produced policy via ``db.policy_apply``
             (one transaction, live recompilation, identity guard). Requires
             the exact approved SQL digest and explicit acknowledgements.
``verify``   Read-only post-install catalog comparison with the access matrix.
``probe``    Fixed least-privilege probes as each persona login, following the
             FR-6.3 order. Every probe transaction is rolled back. No model SQL.

Nothing runs on import. Passwords are read only from named environment
variables and are never printed. Database errors are reported by class and
SQLSTATE only. Catalog checks are metadata. Behaviour comes from ``probe``.
Running ``apply`` changes cluster-global roles. It requires owner approval.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from stark_t2sql.config import AppConfig, DatabaseConnectionAlias, FIXTURE_AS_OF_DATE, load_config  # noqa: E402
from stark_t2sql.policy.compiler import CompiledPolicy, CompileSettings, compile_policy  # noqa: E402
from stark_t2sql.policy.loader import PolicyMatrix, authorization_specs, load_policy  # noqa: E402
from stark_t2sql.policy.privileges import managed_role_names  # noqa: E402
from stark_t2sql.utils.fingerprints import sha256_file  # noqa: E402

FIXTURE_HASH_PATH = ("fixture_dump_sha256",)
SCOPE_FUNCTION = "hr_bp_current_divisions"
SET_CONFIG = "pg_catalog.set_config(text,text,boolean)"


class InstallError(RuntimeError):
    """Fixed non-sensitive message; never contains SQL, paths or credentials."""


def _db_error(exc: BaseException) -> dict[str, object]:
    return {"error_class": type(exc).__name__, "sqlstate": getattr(exc, "pgcode", None)}


def admin_source(config: AppConfig, *, admin_role: str, password_variable: str):
    """Add a separate trusted alias, as the persona runtime composition does."""
    from stark_t2sql.db.connections import AdminConnectionSource

    reference = config.database_connections[0]
    alias = DatabaseConnectionAlias(
        "trusted_policy_admin", admin_role, reference.host, reference.port,
        reference.database_environment_variable, password_variable,
    )
    return AdminConnectionSource(replace(config, database_connections=(*config.database_connections, alias)), alias.alias)


def compile_plan(config: AppConfig, matrix: PolicyMatrix, *, definer_owner: str) -> CompiledPolicy:
    """Compile from frozen schema.sql; policy_apply recompiles from the live catalog."""
    from ops.policy_plan import source_columns

    budgets = config.resource_budgets.require_database_budget_inputs()
    columns = source_columns((ROOT / "schema.sql").read_bytes(), expected_schema=matrix.schema)
    settings = CompileSettings(
        definer_owner,
        statement_timeout_ms=max(1, int(config.limits.statement_timeout_seconds * 1000)),
        work_mem_kib=budgets.database_work_mem_kib,
        temp_file_limit_kib=budgets.database_temp_file_limit_kib,
        measurement_sha256=sha256_file(budgets.measurement_source),
        measurement_provenance="owner-recorded PostgreSQL resource test " + Path(budgets.measurement_source).name,
    )
    return compile_policy(matrix, columns, settings)


def plan_digest(plan: CompiledPolicy) -> str:
    return sha256(plan.sql_text.encode("utf-8")).hexdigest()


def _rows(cursor, query: str, parameters: tuple = ()) -> list[tuple]:
    cursor.execute(query, parameters)
    return [tuple(row) for row in cursor.fetchall()]


def inventory(connection, matrix: PolicyMatrix, managed: tuple[str, ...]) -> dict[str, object]:
    """Fixed read-only catalog queries; superuser counts bypass RLS by design (R6)."""
    from psycopg2 import sql
    from stark_t2sql.db.catalog import policy_state_sha256

    manifest = json.loads((ROOT / "fixture_manifest.json").read_text(encoding="utf-8"))
    with connection.cursor() as cursor:
        (version, version_num, database, current, session, address, port, superuser, listen) = _rows(cursor, """
            SELECT pg_catalog.version(), pg_catalog.current_setting('server_version_num'),
                   pg_catalog.current_database(), current_user, session_user,
                   pg_catalog.host(pg_catalog.inet_server_addr()), pg_catalog.inet_server_port(),
                   (SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user),
                   pg_catalog.current_setting('listen_addresses')""")[0]
        roles = _rows(cursor, """
            SELECT rolname, rolcanlogin, rolinherit, rolsuper, rolbypassrls, rolcreatedb,
                   rolcreaterole, rolreplication, COALESCE(rolconfig, '{}')
            FROM pg_catalog.pg_roles WHERE rolname = ANY(%s) ORDER BY rolname""", (list(managed),))
        memberships = _rows(cursor, """
            SELECT parent.rolname, member.rolname, m.admin_option, m.inherit_option, m.set_option
            FROM pg_catalog.pg_auth_members AS m
            JOIN pg_catalog.pg_roles AS parent ON parent.oid = m.roleid
            JOIN pg_catalog.pg_roles AS member ON member.oid = m.member
            WHERE parent.rolname = ANY(%s) OR member.rolname = ANY(%s)
            ORDER BY 1, 2""", (list(managed), list(managed)))
        rls = _rows(cursor, """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_catalog.pg_class AS c JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relkind = 'r' ORDER BY 1""", (matrix.schema,))
        policies = _rows(cursor, """
            SELECT tablename, policyname, roles::text[], cmd, permissive
            FROM pg_catalog.pg_policies WHERE schemaname = %s ORDER BY 1, 2""", (matrix.schema,))
        functions = _rows(cursor, """
            SELECT p.proname, p.pronargs, p.prosecdef, p.provolatile,
                   pg_catalog.pg_get_userbyid(p.proowner), COALESCE(p.proconfig, '{}'),
                   COALESCE(p.proacl::text[], '{}')
            FROM pg_catalog.pg_proc AS p JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
            WHERE n.nspname = %s ORDER BY 1""", (matrix.schema,))
        set_config_acl = _rows(cursor, "SELECT COALESCE(proacl::text[], '{}') FROM pg_catalog.pg_proc WHERE oid = %s::regprocedure", (SET_CONFIG,))[0][0]
        schema_acl = _rows(cursor, "SELECT COALESCE(nspacl::text[], '{}') FROM pg_catalog.pg_namespace WHERE nspname = %s", (matrix.schema,))[0][0]
        database_acl = _rows(cursor, "SELECT COALESCE(datacl::text[], '{}') FROM pg_catalog.pg_database WHERE datname = pg_catalog.current_database()")[0][0]
        databases = [row[0] for row in _rows(cursor, "SELECT datname FROM pg_catalog.pg_database WHERE NOT datistemplate ORDER BY 1")]
        counts = {}
        for table in matrix.tables:
            cursor.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(matrix.schema), sql.Identifier(table)))
            counts[table] = cursor.fetchone()[0]
    return {
        "server": {"version": version, "version_num": int(version_num), "listen_addresses": listen,
                   "connected_address": address, "connected_port": port},
        "session": {"database": database, "current_user": current, "session_user": session, "superuser": bool(superuser)},
        "databases_in_cluster": databases,
        "managed_roles": [{"name": r[0], "login": r[1], "inherit": r[2], "superuser": r[3], "bypassrls": r[4],
                           "createdb": r[5], "createrole": r[6], "replication": r[7], "config": list(r[8])} for r in roles],
        "memberships": [{"role": m[0], "member": m[1], "admin": m[2], "inherit": m[3], "set": m[4]} for m in memberships],
        "rls": {r[0]: {"enabled": r[1], "forced": r[2]} for r in rls},
        "policies": [{"table": p[0], "name": p[1], "roles": list(p[2]), "cmd": p[3], "permissive": p[4]} for p in policies],
        "schema_functions": [{"name": f[0], "nargs": f[1], "security_definer": f[2], "volatility": f[3],
                              "owner": f[4], "config": list(f[5]), "acl": list(f[6])} for f in functions],
        "set_config_acl": list(set_config_acl), "schema_acl": list(schema_acl), "database_acl": list(database_acl),
        "row_counts": counts,
        "row_counts_match_manifest": counts == manifest["row_counts"],
        "policy_state_sha256": policy_state_sha256(connection, matrix),
    }


def catalog_checks(connection, matrix: PolicyMatrix, *, definer_owner: str) -> list[dict[str, object]]:
    """Compare installed metadata with the matrix. Metadata only, not observed row scope."""
    from stark_t2sql.db.catalog import snapshot_schema

    snapshot = snapshot_schema(connection, schema=matrix.schema)
    columns = snapshot.columns_by_table
    checks: list[dict[str, object]] = []

    def check(name: str, ok: bool, detail: object = None) -> None:
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    with connection.cursor() as cursor:
        def scalar(query: str, parameters: tuple) -> Any:
            cursor.execute(query, parameters)
            return cursor.fetchone()[0]

        for spec in authorization_specs(matrix, columns):
            relation = f"{matrix.schema}.{spec.table}"
            if spec.column is None:
                observed = scalar("SELECT pg_catalog.has_table_privilege(%s, %s, 'SELECT')", (spec.business_role, relation))
            else:
                observed = scalar("SELECT pg_catalog.has_column_privilege(%s, %s, %s, 'SELECT')", (spec.business_role, relation, spec.column))
            check(f"grant:{spec.business_role}:{spec.table}:{spec.column or '*'}", observed is spec.expected_access,
                  {"expected": spec.expected_access, "observed": observed})
        for role in matrix.roles:
            leaked = [t for t in matrix.tables if scalar("SELECT pg_catalog.has_any_column_privilege(%s, %s, 'SELECT')",
                                                         (role.login_role, f"{matrix.schema}.{t}"))]
            check(f"login_has_no_direct_table_access:{role.login_role}", not leaked, leaked)
            cursor.execute("""SELECT parent.rolname, m.admin_option, m.inherit_option, m.set_option
                              FROM pg_catalog.pg_auth_members AS m
                              JOIN pg_catalog.pg_roles AS parent ON parent.oid = m.roleid
                              JOIN pg_catalog.pg_roles AS member ON member.oid = m.member
                              WHERE member.rolname = %s""", (role.login_role,))
            edges = [tuple(row) for row in cursor.fetchall()]
            check(f"membership:{role.login_role}", edges == [(role.name, False, False, True)], edges)
            check(f"set_config_execute:{role.login_role}",
                  scalar("SELECT pg_catalog.has_function_privilege(%s, %s, 'EXECUTE')", (role.login_role, SET_CONFIG)) is True)
            check(f"set_config_denied:{role.name}",
                  scalar("SELECT pg_catalog.has_function_privilege(%s, %s, 'EXECUTE')", (role.name, SET_CONFIG)) is False)
            config = scalar("SELECT COALESCE(rolconfig, '{}') FROM pg_catalog.pg_roles WHERE rolname = %s", (role.login_role,))
            declared = dict(item.split("=", 1) for item in config)
            check(f"login_defaults:{role.login_role}",
                  declared.get("default_transaction_read_only") == "on" and "statement_timeout" in declared
                  and "work_mem" in declared and "temp_file_limit" in declared and "search_path" in declared, declared)
        for name in managed_role_names(matrix, definer_owner):
            cursor.execute("""SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication, rolinherit
                              FROM pg_catalog.pg_roles WHERE rolname = %s""", (name,))
            row = cursor.fetchone()
            check(f"role_attributes:{name}", row is not None and not any(row), None if row is None else list(row))
        for table in matrix.rls_tables:
            cursor.execute("""SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_catalog.pg_class AS c
                              JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
                              WHERE n.nspname = %s AND c.relname = %s""", (matrix.schema, table))
            check(f"rls_enabled_and_forced:{table}", tuple(cursor.fetchone() or ()) == (True, True))
            cursor.execute("SELECT policyname FROM pg_catalog.pg_policies WHERE schemaname = %s AND tablename = %s ORDER BY 1",
                           (matrix.schema, table))
            observed = sorted(row[0] for row in cursor.fetchall())
            expected = sorted(f"stark_select_{role.name}" for role in matrix.roles if table in role.tables)
            check(f"policies:{table}", observed == expected, {"expected": expected, "observed": observed})
        cursor.execute("""SELECT p.pronargs, p.prosecdef, p.provolatile, pg_catalog.pg_get_userbyid(p.proowner),
                                 COALESCE(p.proconfig, '{}')
                          FROM pg_catalog.pg_proc AS p JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
                          WHERE n.nspname = %s AND p.proname = %s""", (matrix.schema, SCOPE_FUNCTION))
        functions = [tuple(row) for row in cursor.fetchall()]
        check("scope_function_shape", len(functions) == 1 and functions[0][:4] == (0, True, "s", definer_owner)
              and list(functions[0][4]) == [f"search_path=pg_catalog, {matrix.schema}, pg_temp"],
              [list(map(str, f)) for f in functions])
        signature = f"{matrix.schema}.{SCOPE_FUNCTION}()"
        for role in (*{r.name for r in matrix.roles}, *{r.login_role for r in matrix.roles}):
            allowed = scalar("SELECT pg_catalog.has_function_privilege(%s, %s, 'EXECUTE')", (role, signature))
            check(f"scope_function_execute:{role}", allowed is (role == "app_hr_bp"), allowed)
        public_create = scalar("SELECT pg_catalog.has_schema_privilege('public', %s, 'CREATE')", (matrix.schema,))
        check("public_schema_create_revoked_from_PUBLIC", public_create is False)
    return checks


PROBES: tuple[tuple[str, str, str], ...] = (
    # (selection, label, fixed SQL). Expected results are computed independently below.
    ("sales", "sales_select_star_employees", "SELECT * FROM public.employees"),
    ("sales", "sales_base_salary", "SELECT base_salary FROM public.employee_compensation"),
    ("hr_1", "hr_employee_number", "SELECT employee_number FROM public.employees"),
    ("hr_1", "hr_payroll_results", "SELECT count(*) FROM public.payroll_results"),
    ("hr_1", "hr_assignments_direct", "SELECT count(*) FROM public.hr_bp_assignments"),
    ("payroll", "payroll_assignments_direct", "SELECT count(*) FROM public.hr_bp_assignments"),
    ("hr_1", "hr_set_role_payroll", "SET ROLE app_payroll"),
    ("hr_1", "hr_set_config_after_role_switch", "SELECT pg_catalog.set_config('app.principal_id', '361', true)"),
    ("sales", "sales_pg_read_file", "SELECT pg_catalog.pg_read_file('postgresql.conf')"),
    ("payroll", "payroll_write_in_read_only_txn", "UPDATE public.divisions SET division_name = division_name WHERE false"),
)
EXPECTED_SQLSTATE = {
    "sales_select_star_employees": "42501", "sales_base_salary": "42501", "hr_employee_number": "42501",
    "hr_payroll_results": "42501", "hr_assignments_direct": "42501", "payroll_assignments_direct": "42501",
    "hr_set_role_payroll": "42501", "hr_set_config_after_role_switch": "42501", "sales_pg_read_file": "42501",
    # Read-only transaction and missing UPDATE grant: either refusal is a block.
    "payroll_write_in_read_only_txn": ("25006", "42501"),
}


def _persona_transaction(config: AppConfig, persona, statement: Callable[[Any], Any]) -> dict[str, object]:
    """FR-6.3 order on a fresh login connection; always rolled back and discarded."""
    from psycopg2 import Error, sql
    from stark_t2sql.db.connections import _discard, _open

    alias = next(a for a in config.database_connections if a.login_role == persona.login_role)
    connection = _open(config, alias.load_credentials())
    try:
        connection.readonly = True
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.set_config('app.principal_id', %s::text, true)", (str(persona.principal_id),))
            cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(persona.business_role)))
            try:
                return {"ok": True, "value": statement(cursor)}
            except Error as exc:
                return {"ok": False, **_db_error(exc)}
    finally:
        _discard(connection)


def behavioural_probes(config: AppConfig, admin, matrix: PolicyMatrix, *, sales_division_name: str) -> dict[str, object]:
    from stark_t2sql.db.persona import resolve_personas

    registry = resolve_personas(admin, matrix, sales_division_name=sales_division_name,
                                fixture_hash_path=FIXTURE_HASH_PATH, as_of_date=FIXTURE_AS_OF_DATE)
    personas = {key: registry.resolve(key) for key in ("payroll", "hr_1", "hr_2", "sales")}
    with admin.connection(readonly=True) as connection, connection.cursor() as cursor:
        # Independent superuser reference counts using the documented predicates (R6).
        def count(query: str, parameters: tuple) -> int:
            cursor.execute(query, parameters)
            return cursor.fetchone()[0]
        division_scope = """SELECT count(*) FROM public.employees e JOIN public.departments d ON d.department_id = e.department_id
                            WHERE d.division_id IN (SELECT division_id FROM public.hr_bp_assignments
                                                    WHERE employee_id = %s AND effective_to IS NULL)"""
        leave_scope = """SELECT count(*) FROM public.leave_balances l JOIN public.employees e ON e.employee_id = l.employee_id
                         JOIN public.departments d ON d.department_id = e.department_id
                         WHERE d.division_id IN (SELECT division_id FROM public.hr_bp_assignments
                                                 WHERE employee_id = %s AND effective_to IS NULL)"""
        reference = {
            "payroll": {"employees": count("SELECT count(*) FROM public.employees", ()),
                        "leave_balances": count("SELECT count(*) FROM public.leave_balances", ())},
            "hr_1": {"employees": count(division_scope, (personas["hr_1"].principal_id,)),
                     "leave_balances": count(leave_scope, (personas["hr_1"].principal_id,))},
            "hr_2": {"employees": count(division_scope, (personas["hr_2"].principal_id,)),
                     "leave_balances": count(leave_scope, (personas["hr_2"].principal_id,))},
            "sales": {"employees": count("SELECT count(*) FROM public.employees WHERE manager_id = %s",
                                         (personas["sales"].principal_id,))},
        }
    results: list[dict[str, object]] = []
    for key, persona in personas.items():
        for table in reference[key]:
            observed = _persona_transaction(config, persona, lambda c, t=table: (c.execute(f"SELECT count(*) FROM public.{t}"), c.fetchone()[0])[1])
            results.append({"probe": f"scope:{key}:{table}", "expected_rows": reference[key][table], "observed": observed,
                            "result": "PASS" if observed.get("value") == reference[key][table] else "FAIL"})
    for key, label, statement in PROBES:
        observed = _persona_transaction(config, personas[key], lambda c, s=statement: (c.execute(s), None)[1])
        expected = EXPECTED_SQLSTATE[label]
        accepted = expected if isinstance(expected, tuple) else (expected,)
        results.append({"probe": label, "persona": key, "expected_sqlstate": expected, "observed": observed,
                        "result": "PASS" if (not observed["ok"] and observed.get("sqlstate") in accepted) else "FAIL"})
    # FRD section 2.4 known single-layer dependency: SQL SET is not blocked by the
    # database. Documented by measurement inside a rolled-back read-only transaction.
    spoof_target = personas["hr_2"].principal_id
    spoof = _persona_transaction(config, personas["hr_1"], lambda c: (
        c.execute(f"SET LOCAL app.principal_id = '{int(spoof_target)}'"),
        c.execute("SELECT count(*) FROM public.employees"), c.fetchone()[0])[2])
    results.append({"probe": "known_gap_sql_set_principal_spoof", "persona": "hr_1",
                    "observed": spoof, "hr_2_reference_rows": reference["hr_2"]["employees"],
                    "result": "KNOWN_SINGLE_LAYER_DEPENDENCY_CONFIRMED" if spoof.get("value") == reference["hr_2"]["employees"]
                              else "NOT_REPRODUCED",
                    "note": "Validator (FR-5) is the only preventive control for SQL SET; see FRD section 2.4."})
    return {"personas": {k: {"business_role": p.business_role, "principal_id": p.principal_id} for k, p in personas.items()},
            "hr_division_scopes": {k: list(v) for k, v in registry.division_scopes.items()},
            "reference_counts": reference, "results": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("plan", "inspect", "apply", "verify", "probe"))
    parser.add_argument("--database", required=True, help="Expected target database name (must equal STARK_PG_DATABASE).")
    parser.add_argument("--admin-role", default="postgres")
    parser.add_argument("--admin-password-env", default="STARK_ADMIN_PASSWORD")
    parser.add_argument("--definer-owner", default="stark_scope_owner")
    parser.add_argument("--approve-sha256", help="apply: exact approved compiler SQL digest (see 'plan').")
    parser.add_argument("--confirm-fixture-restored", action="store_true")
    parser.add_argument("--confirm-dedicated-database", action="store_true")
    parser.add_argument("--backup", type=Path, help="apply: existing pre-change pg_dump of the target database.")
    parser.add_argument("--binding-out", type=Path, help="apply: where to write the installation binding JSON (outside repo).")
    parser.add_argument("--sales-division-name", default="Sales")
    parser.add_argument("--out", type=Path, help="Write the JSON report here as well as stdout.")
    args = parser.parse_args(argv)
    import os

    try:
        if os.environ.get("STARK_PG_DATABASE") != args.database:
            raise InstallError("STARK_PG_DATABASE must equal --database.")
        config = load_config(root=ROOT)
        matrix = load_policy(config.paths.policy_matrix)
        plan = compile_plan(config, matrix, definer_owner=args.definer_owner)
        report: dict[str, object] = {"mode": args.mode, "target": {"host": config.database_connections[0].host,
                                     "port": config.database_connections[0].port, "database": args.database},
                                     "matrix_sha256": matrix.sha256, "plan_sql_sha256": plan_digest(plan),
                                     "plan_statement_count": len(plan.statements)}
        if args.mode == "plan":
            report["database_changed"] = False
        else:
            admin = admin_source(config, admin_role=args.admin_role, password_variable=args.admin_password_env)
            managed = managed_role_names(matrix, args.definer_owner)
            try:
                if args.mode == "inspect":
                    with admin.connection(readonly=True) as connection:
                        report["inventory"] = inventory(connection, matrix, managed)
                    report["database_changed"] = False
                elif args.mode == "verify":
                    with admin.connection(readonly=True) as connection:
                        checks = catalog_checks(connection, matrix, definer_owner=args.definer_owner)
                        report["inventory"] = inventory(connection, matrix, managed)
                    report["checks"] = checks
                    report["failed"] = [c["check"] for c in checks if c["result"] != "PASS"]
                    report["evidence_level"] = "CATALOG_METADATA_ONLY_NOT_BEHAVIOURAL"
                    report["database_changed"] = False
                elif args.mode == "probe":
                    report["probes"] = behavioural_probes(config, admin, matrix, sales_division_name=args.sales_division_name)
                    report["failed"] = [r["probe"] for r in report["probes"]["results"] if r["result"] == "FAIL"]
                    report["database_changed"] = False
                else:
                    from stark_t2sql.db.policy_apply import PolicyApplyRequest, policy_apply

                    if args.approve_sha256 != plan_digest(plan):
                        raise InstallError("The approved digest does not match the compiler plan; nothing was changed.")
                    if not (args.confirm_fixture_restored and args.confirm_dedicated_database):
                        raise InstallError("Both --confirm-fixture-restored and --confirm-dedicated-database are required.")
                    if args.backup is None or not args.backup.is_file():
                        raise InstallError("An existing pre-change --backup file is required.")
                    if args.binding_out is None or args.binding_out.resolve().is_relative_to(ROOT):
                        raise InstallError("--binding-out must be outside the repository.")
                    manifest = json.loads((ROOT / "fixture_manifest.json").read_text(encoding="utf-8"))
                    with admin.connection(readonly=True) as connection:
                        before = inventory(connection, matrix, managed)
                    if not before["session"]["superuser"] or before["session"]["database"] != args.database:
                        raise InstallError("Apply requires a superuser session on the expected database.")
                    if not before["row_counts_match_manifest"]:
                        raise InstallError("Live fixture row counts differ from the manifest; nothing was changed.")
                    binding = policy_apply(plan, admin, matrix, request=PolicyApplyRequest(
                        args.database, FIXTURE_HASH_PATH, manifest["fixture_dump_sha256"],
                        fixture_restore_completed=True, dedicated_fixture_database=True))
                    record = {"matrix_sha256": binding.matrix_sha256, "database_name": binding.database_name,
                              "policy_state_sha256": binding.policy_state_sha256, "plan_sql_sha256": plan_digest(plan),
                              "backup_sha256": sha256_file(args.backup), "backup_file": args.backup.name,
                              "before_policy_state_sha256": before["policy_state_sha256"]}
                    args.binding_out.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
                    report["installation_binding"] = record
                    report["database_changed"] = True
            finally:
                admin.close()
    except InstallError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "database_changed": False}))
        return 2
    except Exception as exc:  # noqa: BLE001 - never echo raw driver text or secrets
        print(json.dumps({"status": "ERROR", **_db_error(exc), "database_changed": "UNKNOWN_CHECK_INSPECT"}))
        return 3
    text = json.dumps(report, indent=2, sort_keys=True, default=str)
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if not report.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
