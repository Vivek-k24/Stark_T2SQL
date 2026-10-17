"""Explicit fixed-target read-only acceptance; never generates or applies SQL.

Credentials come from existing STARK_* environment variables only. This is an
operator verification lane, not a question executor or a general SQL interface.
It records metadata, independent counts, safe denied SELECTs and before/after
fixture digests; no raw rows or secrets are emitted.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path

from stark_t2sql.config import DatabaseConnectionAlias, load_config
from stark_t2sql.db.connections import AdminConnectionSource, RuntimeConnections
from stark_t2sql.db.catalog import policy_state_sha256
from stark_t2sql.pipeline.metadata import inspect_metadata, load_installation_digest
from stark_t2sql.policy.loader import load_policy


def verify(root, *, environment, installation_binding):
    config = load_config(root=root, environment=environment)
    # Establish fixed target, actual installed policy, identities and all login
    # audits before any operator data observation.
    metadata = inspect_metadata(config, installation_binding=installation_binding, environment=environment)
    matrix = load_policy(config.paths.policy_matrix)
    expected = load_installation_digest(installation_binding, root=root, matrix_sha256=matrix.sha256)
    alias = DatabaseConnectionAlias("readonly_acceptance", "postgres", "127.0.0.1", 5433,
                                    "STARK_PG_DATABASE", "STARK_ADMIN_PASSWORD")
    admin = AdminConnectionSource(replace(config, database_connections=(*config.database_connections, alias)),
                                  alias.alias, environment=environment)
    source = RuntimeConnections(config, matrix, metadata._registry, expected_policy_state_sha256=expected,
                                environment=environment)
    import psycopg2.sql as sql

    def fixture_fingerprints():
        hashes, counts = {}, {}
        with admin.connection(readonly=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '5000ms'")
                for name in sorted(matrix.tables):
                    cursor.execute(sql.SQL("SELECT row_to_json(t)::text FROM {}.{} AS t ORDER BY row_to_json(t)::text").format(
                        sql.Identifier(matrix.schema), sql.Identifier(name)))
                    digest, count = sha256(), 0
                    while True:
                        rows = cursor.fetchmany(500)
                        if not rows: break
                        for row in rows:
                            digest.update(row[0].encode("utf-8") + b"\n")
                            count += 1
                    hashes[name], counts[name] = digest.hexdigest(), count
        return hashes, counts

    def restricted(persona, statement):
        with source.connection(persona) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_catalog.set_config('app.principal_id', %s, true)", (str(persona.principal_id),))
                cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(persona.business_role)))
                cursor.execute(statement)
                return cursor.fetchone()

    checks = []
    try:
        before, counts_before = fixture_fingerprints()
        for persona in metadata.personas:
            with admin.connection(readonly=True) as connection:
                with connection.cursor() as cursor:
                    if persona.business_role == "app_payroll":
                        cursor.execute("SELECT count(*) FROM public.employees")
                    elif persona.business_role == "app_sales_mgr":
                        cursor.execute("SELECT count(*) FROM public.employees WHERE manager_id = %s", (persona.principal_id,))
                    else:
                        cursor.execute("SELECT count(*) FROM public.employees AS e JOIN public.departments AS d USING (department_id) "
                            "WHERE d.division_id IN (SELECT division_id FROM public.hr_bp_assignments WHERE employee_id = %s AND effective_to IS NULL)",
                            (persona.principal_id,))
                    expected_count = cursor.fetchone()[0]
            observed = metadata.employee_count(persona)
            checks.append({"check": "independent_scope_count", "persona": persona.display_name,
                           "observed_count": observed, "expected_count": expected_count, "passed": observed == expected_count})
            if persona.business_role == "app_payroll":
                denied = ("SELECT * FROM public.hr_bp_assignments LIMIT 0",)
            elif persona.business_role == "app_hr_bp":
                denied = ("SELECT employee_number FROM public.employees LIMIT 0", "SELECT base_salary FROM public.employee_compensation LIMIT 0")
            else:
                denied = ("SELECT * FROM public.employees LIMIT 0", "SELECT base_salary FROM public.employee_compensation LIMIT 0")
            for index, statement in enumerate(denied):
                state = None
                try: restricted(persona, statement)
                except Exception as error:
                    state = getattr(error, "pgcode", None)
                    if state is None: raise
                checks.append({"check": f"forbidden_projection_{index + 1}", "persona": persona.display_name,
                               "sqlstate": state, "passed": state == "42501"})
        scopes = metadata._registry.division_scopes
        checks.append({"check": "two_distinct_nonempty_hr_scopes", "passed": bool(scopes["hr_1"] and scopes["hr_2"] and scopes["hr_1"] != scopes["hr_2"])})
        after, counts_after = fixture_fingerprints()
        with admin.connection(readonly=True) as connection:
            policy_after = policy_state_sha256(connection, matrix)
        checks.append({"check": "all_fixture_rows_unchanged", "passed": before == after and counts_before == counts_after})
        checks.append({"check": "installed_policy_unchanged", "passed": policy_after == expected})
        return {"kind": "ACTUAL_READONLY_LIVE_UI_METADATA_V1", "executed_at": datetime.now(timezone.utc).isoformat(),
            "target": "127.0.0.1:5433/stark_test", "policy_state_sha256": expected,
            "checks": checks, "passed": sum(item["passed"] for item in checks),
            "failed": sum(not item["passed"] for item in checks), "fixture_rows": counts_after,
            "fixture_row_sha256": after, "model_inference": "NOT_EXECUTED", "browser": "NOT_ESTABLISHED_BY_THIS_RUN",
            "principal_spoofing": "KNOWN_SQL_SET_SINGLE_LAYER_DEPENDENCY",
            "production_promotion": "NOT_APPROVED"}
    finally:
        source.close()
        admin.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-existing", action="store_true", required=True)
    parser.add_argument("--installation-binding", type=Path, required=True)
    parser.add_argument("--evidence-out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify(Path(__file__).resolve().parents[1], environment=dict(os.environ), installation_binding=args.installation_binding)
        text = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.evidence_out:
            with args.evidence_out.open("x", encoding="utf-8") as stream: stream.write(text)
        print(text)
        return 0 if result["failed"] == 0 else 1
    except Exception:
        print(json.dumps({"status": "BLOCKED", "reason": "Read-only verification failed; inspect credentials, fixed target, policy binding and budgets privately."}))
        return 2


if __name__ == "__main__": raise SystemExit(main())
