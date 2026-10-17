"""Offline guards of the owner-run installer; no socket, database or credential.

Every refusal case asserts no administrative connection is opened. Passing
these tests is not evidence that any policy was installed or behaves correctly.
"""
from __future__ import annotations

from hashlib import sha256
import json

import pytest

from ops import install_policy
from ops.policy_plan import source_columns


@pytest.fixture
def environment(monkeypatch, tmp_path):
    measurement = tmp_path / "unit_measurement.txt"
    measurement.write_bytes(b"unit-only measurement operand; not a deployment measurement")
    for name, value in {
        "STARK_PG_DATABASE": "unit_db", "STARK_PG_PORT": "5433",
        "STARK_DATABASE_WORK_MEM_KIB": "4096", "STARK_DATABASE_TEMP_FILE_LIMIT_KIB": "65536",
        "STARK_RESOURCE_MEASUREMENTS_PATH": str(measurement),
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("STARK_ADMIN_PASSWORD", raising=False)
    opened = []

    def refuse(*args, **kwargs):
        opened.append(True)
        raise AssertionError("No database connection may be opened by a refused request.")

    monkeypatch.setattr("stark_t2sql.db.connections._open", refuse)
    return tmp_path, opened


def run(capsys, *argv):
    code = install_policy.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_plan_digest_is_compiler_output_and_matches_frozen_matrix(environment, capsys, project_root):
    code, report = run(capsys, "plan", "--database", "unit_db")
    assert code == 0 and report["database_changed"] is False
    config = install_policy.load_config(root=project_root)
    matrix = install_policy.load_policy(config.paths.policy_matrix)
    plan = install_policy.compile_plan(config, matrix, definer_owner="stark_scope_owner")
    assert report["plan_sql_sha256"] == sha256(plan.sql_text.encode()).hexdigest()
    assert report["plan_statement_count"] == len(plan.statements) == 97
    assert report["target"] == {"host": "127.0.0.1", "port": 5433, "database": "unit_db"}


def test_measurement_operand_does_not_change_reviewable_sql(environment, project_root):
    # The digest the owner approves binds SQL text; measurement hashes are plan
    # provenance only, so equal budgets produce identical statements.
    config = install_policy.load_config(root=project_root)
    matrix = install_policy.load_policy(config.paths.policy_matrix)
    columns = source_columns((project_root / "schema.sql").read_bytes(), expected_schema="public")
    first = install_policy.compile_plan(config, matrix, definer_owner="stark_scope_owner")
    other = install_policy.compile_policy(matrix, columns, install_policy.CompileSettings(
        "stark_scope_owner", work_mem_kib=4096, temp_file_limit_kib=65536,
        measurement_sha256="0" * 64, measurement_provenance="unit"))
    assert first.statements == other.statements


def test_database_name_must_match_environment(environment, capsys):
    code, report = run(capsys, "inspect", "--database", "some_other_db")
    assert code == 2 and report["status"] == "BLOCKED" and report["database_changed"] is False
    assert environment[1] == []


@pytest.mark.parametrize("extra", (
    ("--approve-sha256", "0" * 64, "--confirm-fixture-restored", "--confirm-dedicated-database"),
    ("--confirm-fixture-restored", "--confirm-dedicated-database"),
))
def test_apply_refuses_unapproved_digest_without_connecting(environment, capsys, extra):
    code, report = run(capsys, "apply", "--database", "unit_db", *extra)
    assert code == 2 and report["database_changed"] is False
    assert "digest" in report["reason"]
    assert environment[1] == []


def test_apply_requires_acknowledgements_backup_and_external_binding(environment, capsys, project_root):
    tmp_path, opened = environment
    _, planned = run(capsys, "plan", "--database", "unit_db")
    digest = planned["plan_sql_sha256"]
    code, report = run(capsys, "apply", "--database", "unit_db", "--approve-sha256", digest)
    assert code == 2 and "confirm" in report["reason"]
    code, report = run(capsys, "apply", "--database", "unit_db", "--approve-sha256", digest,
                       "--confirm-fixture-restored", "--confirm-dedicated-database")
    assert code == 2 and "backup" in report["reason"]
    backup = tmp_path / "unit.dump"
    backup.write_bytes(b"unit")
    code, report = run(capsys, "apply", "--database", "unit_db", "--approve-sha256", digest,
                       "--confirm-fixture-restored", "--confirm-dedicated-database",
                       "--backup", str(backup), "--binding-out", str(project_root / "binding.json"))
    assert code == 2 and "outside the repository" in report["reason"]
    assert opened == []


def test_errors_never_echo_driver_text_or_password(environment, capsys, monkeypatch):
    monkeypatch.setenv("STARK_ADMIN_PASSWORD", "unit-secret-value")

    class DriverFailure(Exception):
        pgcode = "28P01"

    def failing(*args, **kwargs):
        raise DriverFailure("password authentication failed: unit-secret-value")

    monkeypatch.setattr("stark_t2sql.db.connections._open", failing)
    code = install_policy.main(["inspect", "--database", "unit_db"])
    output = capsys.readouterr().out
    assert code == 3 and "unit-secret-value" not in output and "authentication failed" not in output
    assert json.loads(output) == {"status": "ERROR", "error_class": "DriverFailure", "sqlstate": "28P01",
                                  "database_changed": "UNKNOWN_CHECK_INSPECT"}


def test_probe_expectations_cover_frd_section_6_6_negative_rows():
    labels = {label for _, label, _ in install_policy.PROBES}
    assert labels == set(install_policy.EXPECTED_SQLSTATE)
    for required in ("sales_select_star_employees", "sales_base_salary", "hr_employee_number",
                     "hr_payroll_results", "hr_set_role_payroll", "hr_set_config_after_role_switch",
                     "sales_pg_read_file"):
        assert install_policy.EXPECTED_SQLSTATE[required] == "42501"


def test_catalog_checks_evaluates_expected_select(project_root):
    from unittest.mock import MagicMock, patch
    from stark_t2sql.policy.loader import authorization_specs, load_policy

    config = install_policy.load_config(root=project_root)
    matrix = load_policy(config.paths.policy_matrix)
    columns = source_columns((project_root / "schema.sql").read_bytes(), expected_schema=matrix.schema)

    specs = authorization_specs(matrix, columns)
    assert len(specs) == 273
    for spec in specs:
        assert hasattr(spec, "expected_select")
        assert not hasattr(spec, "expected_access")

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    def custom_execute(query, params=()):
        if "rolconfig" in query:
            mock_cursor.fetchone.return_value = ([
                "statement_timeout=15000ms", "default_transaction_read_only=on",
                "work_mem=4096kB", "temp_file_limit=65536kB", "search_path=pg_catalog, public, pg_temp",
            ],)
        elif "pg_proc" in query and "pronargs" in query:
            mock_cursor.fetchall.return_value = [(0, True, "s", "stark_scope_owner", ["search_path=pg_catalog, public, pg_temp"])]
        elif "pg_class" in query:
            mock_cursor.fetchone.return_value = (True, True)
        elif "pg_policies" in query:
            mock_cursor.fetchall.return_value = [("stark_select_app_hr_bp",), ("stark_select_app_payroll",)]
        else:
            mock_cursor.fetchone.return_value = (True,)
            mock_cursor.fetchall.return_value = []

    mock_cursor.execute.side_effect = custom_execute

    with patch("stark_t2sql.db.catalog.snapshot_schema") as mock_snapshot:
        mock_snapshot.return_value.columns_by_table = columns
        checks = install_policy.catalog_checks(mock_conn, matrix, definer_owner="stark_scope_owner")
        assert len(checks) >= 273
        grant_checks = [c for c in checks if c["check"].startswith("grant:")]
        assert len(grant_checks) == 273
        for c in grant_checks:
            assert "expected" in c["detail"]
