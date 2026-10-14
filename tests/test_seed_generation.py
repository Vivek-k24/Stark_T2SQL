"""R02 offline evidence and opt-in live reset; mocks are not live acceptance."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock

import pytest

import seed_data as seed


@pytest.fixture(scope="module")
def generated():
    config = seed.default_seed_configuration()
    return config, seed.generate_fixture(config)


def test_repeat_generation_preserves_every_value_and_dump_byte(generated):
    config, first = generated
    second_config = seed.default_seed_configuration()
    second = seed.generate_fixture(second_config)
    assert config == second_config
    assert first.rows == second.rows
    assert seed.fixture_dump_bytes(first, config) == seed.fixture_dump_bytes(second, second_config)


def test_all_eighteen_operational_checks_pass(generated):
    config, fixture = generated
    checks = seed.evaluate_invariants(fixture, config)
    assert len(checks) == 18 and all(check.satisfied for check in checks)
    assert all(check.invariant_id.startswith("DRAFT-FIXTURE-") for check in checks)


def test_population_lifecycles_personas_and_reserved_emails(generated):
    config, fixture = generated
    employees = fixture.table("employees")
    assert [e["employee_id"] for e in employees] == list(range(1, 501))
    assert [e["employee_number"] for e in employees] == [f"S{i:05d}" for i in range(1, 501)]
    assert sum(seed.is_active(e) for e in employees) == 435
    assert {e["status"] for e in employees} >= {"active", "terminated", "pending_hire", "cancelled_pre_hire"}
    assert all(e["email"].endswith("@starkcorp.example.com") for e in employees)
    by_id = {e["employee_id"]: e for e in employees}
    assert all(seed.is_active(by_id[i]) for i in (326, 47, 361, 364))
    assert all(run["created_by_employee_id"] == 326 for run in fixture.table("payroll_runs"))
    assert {d["division_name"] for d in config.divisions} >= {"Sales", "Engineering"}
    assert [d["division_code"] for d in config.divisions] == [f"DIV{i:02d}" for i in range(1, 11)]
    assert [d["department_code"] for d in config.departments] == [f"DEP{i:02d}" for i in range(1, 38)]
    scopes = {p: {a["division_id"] for a in fixture.table("hr_bp_assignments") if a["employee_id"] == p and a["effective_to"] is None}
              for p in (47, 361, 364)}
    assert scopes[47] and scopes[361] and scopes[47].isdisjoint(scopes[361]) and scopes[364]
    assert seed.check_06_manager_graph(fixture, config).satisfied


def test_planted_facts_are_observed_from_rows(generated):
    config, fixture = generated
    runs = {r["run_number"]: r for r in fixture.table("payroll_runs")}
    results = fixture.table("payroll_results")
    negative = [r for r in results if r["payroll_run_id"] == runs["PR-2026-006"]["payroll_run_id"] and r["net_pay"] < 0]
    assert len(negative) == 3 and all(r["total_deductions"] > r["gross_pay"] for r in negative)
    taxes = {}
    for row in results:
        taxes[row["employee_id"]] = taxes.get(row["employee_id"], Decimal(0)) + row["tax_amount"]
    assert sum(value == 0 for value in taxes.values()) == 4
    mismatch = runs["PR-2026-012"]
    assert mismatch["total_gross_pay"] - sum(r["gross_pay"] for r in results if r["payroll_run_id"] == mismatch["payroll_run_id"]) == Decimal("125.00")
    correction = runs["PR-2026-024"]
    assert correction["is_off_cycle"] and correction["status"] == "approved"
    ids = {r["payroll_result_id"] for r in results if r["payroll_run_id"] == correction["payroll_run_id"]}
    assert len(ids) == 4
    assert len([r for r in fixture.table("payroll_earnings") if r["payroll_result_id"] in ids]) == 4
    assert seed.check_17_small_compensated_departments(fixture, config).satisfied


def test_fact_observations_do_not_assume_a_header_column(generated):
    config, fixture = generated
    runs = [dict(row) for row in fixture.table("payroll_runs")]
    run = next(row for row in runs if row["run_number"] == "PR-2026-012")
    run["total_gross_pay"] -= Decimal("125.00")
    run["total_tax"] += Decimal("125.00")
    rows = dict(fixture.rows, payroll_runs=tuple(runs))
    observed = seed.planted_fact_observations(seed.GeneratedFixture(rows, fixture.configuration_sha256, None))
    assert observed["header_mismatch_column"] == "total_tax"
    assert observed["header_mismatch_usd"] == "125.00"


@pytest.mark.parametrize("number", range(1, 19))
def test_each_invariant_rejects_a_relevant_row_defect(number, generated):
    config, fixture = generated
    data = {table: [dict(row) for row in fixture.table(table)] for table in seed.TABLE_COLUMNS}
    if number == 1: data["employees"][0].pop("email")
    elif number == 2: data["divisions"].pop()
    elif number == 3: data["employees"][0]["employee_number"] = "BAD"
    elif number == 4: data["employees"][0]["department_id"] = 9999
    elif number == 5: data["employees"][0]["termination_date"] = date(2026, 1, 1)
    elif number == 6: data["employees"][0]["manager_id"] = 2
    elif number == 7: data["employee_compensation"][0]["effective_to"] = None
    elif number == 8: data["payroll_runs"][0]["pay_period_end"] += timedelta(days=1)
    elif number == 9: data["payroll_runs"][0]["created_by_employee_id"] = 1
    elif number == 10: data["payroll_results"][0]["net_pay"] += Decimal("1")
    elif number == 11: data["payroll_earnings"][0]["amount"] += Decimal("1")
    elif number == 12: data["payroll_deductions"][0]["amount"] += Decimal("1")
    elif number == 13:
        for row in data["payroll_results"]:
            if row["payroll_run_id"] == 6 and row["net_pay"] < 0: row["net_pay"] = Decimal(0)
    elif number == 14:
        next(r for r in data["payroll_results"] if r["employee_id"] == 10)["tax_amount"] = Decimal("1")
    elif number == 15:
        next(r for r in data["payroll_runs"] if r["run_number"] == "PR-2026-012")["total_gross_pay"] -= Decimal("125")
    elif number == 16:
        next(r for r in data["payroll_runs"] if r["run_number"] == "PR-2026-024")["status"] = "closed"
    elif number == 17:
        employees = {e["employee_id"] for e in data["employees"] if e["department_id"] == 8}
        data["employee_compensation"] = [r for r in data["employee_compensation"] if r["employee_id"] not in employees]
    elif number == 18: data["leave_balances"][0]["as_of_date"] = date(2026, 10, 13)
    broken = seed.GeneratedFixture(MappingProxyType({t: tuple(rows) for t, rows in data.items()}), fixture.configuration_sha256, None)
    assert not seed.OPERATIONAL_INVARIANTS[number - 1](broken, config).satisfied


def test_export_pair_repeats_exactly_and_persona_digest_accepts_it(tmp_path, generated):
    from stark_t2sql.config import ProjectPaths
    from stark_t2sql.db.persona import fixture_digest
    config, fixture = generated
    dumps, manifests = [], []
    for name in ("first", "second"):
        root = tmp_path / name
        root.mkdir()
        dump, manifest = root / "fixture_pg_dump.sql", root / "fixture_manifest.json"
        digest = seed.write_fixture_dump(dump, fixture, config)
        metadata = seed.write_fixture_manifest(manifest, dump, fixture, config)
        assert digest == metadata["fixture_dump_sha256"] == metadata["sha256"]
        assert fixture_digest(ProjectPaths.from_root(root), ("fixture_dump_sha256",)) == digest
        assert fixture_digest(ProjectPaths.from_root(root), ("sha256",)) == digest
        assert metadata["verification"]["live_postgresql_verified"] is False
        assert metadata["verification"]["historical_dataset_fidelity_verified"] is False
        assert len(metadata["invariants"]) == 18 and all(i["satisfied"] for i in metadata["invariants"])
        dumps.append(dump.read_bytes()); manifests.append(manifest.read_bytes())
    assert dumps[0] == dumps[1] and manifests[0] == manifests[1]
    assert b"\r" not in dumps[0] and b"\r" not in manifests[0]
    assert b"TRUNCATE" not in dumps[0] and b"CASCADE" not in dumps[0] and b"DROP TABLE" not in dumps[0]
    assert b"SET CONSTRAINTS ALL IMMEDIATE" in dumps[0] and b"ALTER SEQUENCE" in dumps[0]


def test_committed_snapshot_matches_recorded_source_and_regeneration(project_root, generated):
    import importlib.metadata
    config, fixture = generated
    manifest = json.loads((project_root / "fixture_manifest.json").read_bytes())
    payload = (project_root / "fixture_pg_dump.sql").read_bytes()
    assert manifest["provenance"]["faker_version"] == importlib.metadata.version("Faker"), "Use the recorded Faker version to reproduce this baseline."
    assert manifest["provenance"]["generator_sha256"] == hashlib.sha256((project_root / "seed_data.py").read_bytes()).hexdigest()
    assert manifest["provenance"]["schema_sha256"] == hashlib.sha256((project_root / "schema.sql").read_bytes()).hexdigest()
    assert manifest["fixture_dump_sha256"] == manifest["sha256"] == hashlib.sha256(payload).hexdigest()
    assert payload == seed.fixture_dump_bytes(fixture, config)
    assert manifest["row_counts"] == {table: len(fixture.table(table)) for table in seed.TABLE_COLUMNS}


def test_manifest_refuses_tampered_dump_without_writing(tmp_path, generated):
    config, fixture = generated
    dump = tmp_path / "fixture_pg_dump.sql"
    seed.write_fixture_dump(dump, fixture, config)
    dump.write_bytes(dump.read_bytes().replace(b"\n", b"\r\n"))
    manifest = tmp_path / "fixture_manifest.json"
    with pytest.raises(seed.FixtureInvariantError, match="Dump bytes"):
        seed.write_fixture_manifest(manifest, dump, fixture, config)
    assert not manifest.exists()


def test_export_cannot_overwrite_schema_or_source(tmp_path, generated):
    config, fixture = generated
    schema = tmp_path / "schema.sql"
    schema.write_bytes(b"unit protected schema")
    with pytest.raises(seed.FixtureInvariantError, match="dedicated filename"):
        seed.write_fixture_dump(schema, fixture, config)
    assert schema.read_bytes() == b"unit protected schema"


@pytest.mark.parametrize("name", ("postgres", "template0", "template1", "production_db", "stark_t2sql_test_prod", "unrelated", "stark_t2sql_test;DROP"))
def test_unsafe_database_names_stop_before_any_connection(name):
    with pytest.raises(seed.ResetSafetyError): seed.require_test_database_name(name)


@pytest.fixture
def proof(project_root):
    # Unit-only authorization metadata. No marker/database is created or claimed.
    return seed.IsolationProof("stark_t2sql_test_unit", 12345, "127.0.0.1", 5432,
                               "unit-only-isolation-token-not-real-0000", hashlib.sha256((project_root / "schema.sql").read_bytes()).hexdigest())


@pytest.mark.parametrize("field,value", (("database_oid", 0), ("server_address", "203.0.113.1"),
    ("server_port", 0), ("isolation_token", "short"), ("schema_sha256", "missing")))
def test_isolation_proof_rejects_invalid_binding(field, value, proof):
    with pytest.raises((seed.ResetSafetyError, ValueError)):
        replace(proof, **{field: value})


@pytest.mark.parametrize("defect", ("name", "oid", "endpoint", "port", "marker", "limit", "owner", "clients"))
def test_live_identity_guards_reject_mismatches(defect, proof):
    marker = {"kind": "stark_t2sql_isolated_fixture", "version": 1, "database_oid": proof.database_oid,
              "isolation_token": proof.isolation_token, "schema_sha256": proof.schema_sha256}
    row = [proof.database_name, proof.database_oid, proof.server_address, proof.server_port, json.dumps(marker), 1, True]
    replacements = {"name": (0, "postgres"), "oid": (1, 54321), "endpoint": (2, "203.0.113.1"),
                    "port": (3, 5433), "marker": (4, "{}"), "limit": (5, -1), "owner": (6, False)}
    if defect in replacements:
        index, value = replacements[defect]; row[index] = value
    cursor = Mock()
    cursor.fetchone.side_effect = [tuple(row), (1 if defect == "clients" else 0,)]
    with pytest.raises(seed.ResetSafetyError): seed._verify_database_identity(cursor, proof)
    assert all("TRUNCATE" not in str(call) for call in cursor.execute.call_args_list)


def test_unknown_or_partitioned_schema_is_rejected_before_other_queries(project_root):
    cursor = Mock()
    cursor.fetchall.return_value = [("public", t, "r", False) for t in seed.TABLE_COLUMNS] + [("other", "unrelated", "r", False)]
    with pytest.raises(seed.ResetSafetyError, match="unrelated objects"):
        seed._verify_isolated_schema(cursor, project_root)
    assert cursor.execute.call_count == 1


def test_mismatched_column_types_are_rejected(project_root):
    cursor = Mock()
    cursor.fetchall.side_effect = [
        [("public", t, "r", False) for t in seed.TABLE_COLUMNS],
        [(t, c) for t, columns in seed.TABLE_COLUMNS.items() for c in columns], [],
    ]
    with pytest.raises(seed.ResetSafetyError, match="column types"):
        seed._verify_isolated_schema(cursor, project_root)


class FakeCursor:
    def __init__(self, fail_insert=False, occupied=False):
        self.statements, self.parameters = [], ()
        self.fail_insert, self.occupied = fail_insert, occupied
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, statement, parameters=()):
        self.statements.append(repr(statement)); self.parameters = parameters
    def executemany(self, statement, values):
        self.statements.append(repr(statement))
        if self.fail_insert: raise RuntimeError("unit insert failure")
    def fetchone(self):
        if "pg_get_serial_sequence" in self.statements[-1]:
            return ("public", self.parameters[0].split(".")[1] + "_unit_sequence")
        return (self.occupied,)


def mocked_source(monkeypatch, project_root, proof, *, fail_insert=False, occupied=False):
    from stark_t2sql.db.connections import AdminConnectionSource
    source = object.__new__(AdminConnectionSource)
    source.config = SimpleNamespace(paths=SimpleNamespace(root=project_root))
    source.alias = SimpleNamespace(load_credentials=lambda: SimpleNamespace(database=proof.database_name,
                                   host=proof.server_address, port=proof.server_port))
    cursor = FakeCursor(fail_insert, occupied)
    commits, rollbacks = [], []
    @contextmanager
    def lease(*, readonly=True):
        try: yield SimpleNamespace(cursor=lambda: cursor)
        except Exception:
            rollbacks.append(True); raise
        else:
            if not readonly: commits.append(True)
    source.connection = Mock(side_effect=lease)
    monkeypatch.setattr(seed, "_verify_database_identity", lambda *args: None)
    monkeypatch.setattr(seed, "_verify_isolated_schema", lambda *args: None)
    return source, cursor, commits, rollbacks


def test_reset_routes_only_named_tables_and_checks_before_commit(monkeypatch, project_root, proof, generated):
    config, fixture = generated
    source, cursor, commits, rollbacks = mocked_source(monkeypatch, project_root, proof)
    monkeypatch.setattr(seed, "_read_fixture", lambda *args: fixture)
    result = seed.create_fixture(admin_source=source, project_root=project_root, reset=True,
                                 authorization=proof, database_name=proof.database_name)
    statements = "\n".join(cursor.statements)
    assert result.database_verified and commits == [True] and not rollbacks
    assert "TRUNCATE TABLE" in statements and "RESTRICT" in statements and "CASCADE" not in statements
    assert "SET CONSTRAINTS ALL IMMEDIATE" in statements and "setval" not in statements
    assert sum("ALTER SEQUENCE" in query for query in cursor.statements) == 12


def test_insert_failure_rolls_back_reset(monkeypatch, project_root, proof):
    source, cursor, commits, rollbacks = mocked_source(monkeypatch, project_root, proof, fail_insert=True)
    with pytest.raises(RuntimeError, match="unit insert failure"):
        seed.create_fixture(admin_source=source, project_root=project_root, reset=True,
                            authorization=proof, database_name=proof.database_name)
    assert rollbacks == [True] and not commits


def test_nonempty_without_reset_is_refused(monkeypatch, project_root, proof):
    source, cursor, commits, rollbacks = mocked_source(monkeypatch, project_root, proof, occupied=True)
    with pytest.raises(seed.ResetSafetyError, match="Non-empty"):
        seed.create_fixture(admin_source=source, project_root=project_root, reset=False,
                            authorization=proof, database_name=proof.database_name)
    assert not commits and all("TRUNCATE" not in query for query in cursor.statements)


def test_schema_guard_failure_cannot_reach_truncate(monkeypatch, project_root, proof):
    source, cursor, commits, rollbacks = mocked_source(monkeypatch, project_root, proof)
    monkeypatch.setattr(seed, "_verify_isolated_schema", Mock(side_effect=seed.ResetSafetyError("unit schema mismatch")))
    with pytest.raises(seed.ResetSafetyError):
        seed.create_fixture(admin_source=source, project_root=project_root, reset=True,
                            authorization=proof, database_name=proof.database_name)
    assert not commits and all("TRUNCATE" not in query for query in cursor.statements)


def test_unsafe_name_in_loader_never_opens_a_connection(monkeypatch, project_root, proof):
    source, cursor, commits, rollbacks = mocked_source(monkeypatch, project_root, proof)
    with pytest.raises(seed.ResetSafetyError):
        seed.create_fixture(admin_source=source, reset=True, authorization=proof, database_name="postgres")
    source.connection.assert_not_called()
    assert not cursor.statements


def test_missing_proof_cannot_open_a_connection(monkeypatch, project_root, proof):
    source, cursor, commits, rollbacks = mocked_source(monkeypatch, project_root, proof)
    with pytest.raises(seed.ResetSafetyError, match="authorization"):
        seed.create_fixture(admin_source=source, reset=True, database_name=proof.database_name)
    source.connection.assert_not_called()


def test_foreign_sequence_ownership_stops_before_truncate(monkeypatch, project_root, proof):
    source, cursor, commits, rollbacks = mocked_source(monkeypatch, project_root, proof)
    cursor.fetchone = lambda: ("other_schema", "unrelated_sequence")
    with pytest.raises(seed.ResetSafetyError, match="uniquely owned"):
        seed.create_fixture(admin_source=source, reset=True, authorization=proof, database_name=proof.database_name)
    assert not commits and all("TRUNCATE" not in query for query in cursor.statements)


def test_precommit_row_verification_failure_rolls_back(monkeypatch, project_root, proof, generated):
    config, fixture = generated
    source, cursor, commits, rollbacks = mocked_source(monkeypatch, project_root, proof)
    rows = {table: [dict(row) for row in fixture.table(table)] for table in seed.TABLE_COLUMNS}
    rows["payroll_results"][0]["net_pay"] += Decimal("1")
    broken = seed.GeneratedFixture(rows, fixture.configuration_sha256, None)
    monkeypatch.setattr(seed, "_read_fixture", lambda *args: broken)
    with pytest.raises(seed.FixtureInvariantError):
        seed.create_fixture(admin_source=source, reset=True, authorization=proof, database_name=proof.database_name)
    assert rollbacks == [True] and not commits


def test_actual_identity_failure_never_reaches_table_locks(monkeypatch, project_root, proof):
    source, cursor, commits, rollbacks = mocked_source(monkeypatch, project_root, proof)
    monkeypatch.setattr(seed, "_verify_database_identity", Mock(side_effect=seed.ResetSafetyError("unit marker mismatch")))
    with pytest.raises(seed.ResetSafetyError):
        seed.create_fixture(admin_source=source, reset=True, authorization=proof, database_name=proof.database_name)
    assert not cursor.statements and not commits


def test_cli_production_name_is_refused_before_proof_read(monkeypatch, capsys):
    monkeypatch.setattr(seed, "_cli_admin_source", Mock(side_effect=AssertionError("no connection")))
    assert seed.main(["--reset", "--database-name", "production_db", "--isolation-proof", "absent-unit-proof.json"]) == 2
    assert "critical/prod" in capsys.readouterr().err


def test_private_faker_seed_does_not_change_global_faker_rng():
    from faker.generator import random as global_faker_rng
    previous = global_faker_rng.getstate()
    seed.default_seed_configuration()
    assert global_faker_rng.getstate() == previous


def test_sql_literal_escaping_preserves_special_text():
    assert seed._sql_literal("O'Brien\\test\r\n") == "E'O''Brien\\\\test\\r\\n'"


@pytest.mark.parametrize("seed_value,day", ((43, seed.FIXTURE_DATE), (True, seed.FIXTURE_DATE), (42, date(2026, 10, 13))))
def test_seed_and_business_date_are_frozen(seed_value, day):
    with pytest.raises(seed.MissingSeedInputError): seed.generate_fixture(seed=seed_value, as_of_date=day)


def test_cli_default_is_dry_run_and_never_opens_database(monkeypatch, capsys):
    monkeypatch.setattr(seed, "_cli_admin_source", Mock(side_effect=AssertionError("no DB for dry run")))
    monkeypatch.setattr(seed, "write_fixture_dump", Mock(side_effect=AssertionError("no output for dry run")))
    assert seed.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["database_action"] == "none" and result["operational_invariants_satisfied"] == 18


def test_reset_without_real_proof_is_a_usage_error():
    with pytest.raises(SystemExit) as captured: seed.main(["--reset", "--database-name", "stark_t2sql"])
    assert captured.value.code == 2


def test_opt_in_live_reset_with_actual_owner_isolation_proof(project_root):
    if os.environ.get("STARK_TEST_ENABLE_DB_INTEGRATION") != "1":
        pytest.skip("R02 live PostgreSQL reset not opted in; offline results are not live acceptance.")
    proof_path = os.environ.get("STARK_R02_ISOLATION_PROOF")
    if not proof_path:
        pytest.skip("Actual owner-isolated database proof is unavailable; no live acceptance.")
    proof = seed.IsolationProof.from_file(Path(proof_path))
    source = seed._cli_admin_source(project_root)
    from stark_t2sql.errors import DatabaseExecutionError
    try:
        try:
            result = seed.create_fixture(admin_source=source, project_root=project_root, reset=True,
                                         authorization=proof, database_name=proof.database_name)
        except DatabaseExecutionError:
            pytest.skip("Local PostgreSQL connection unavailable; no live acceptance.")
        assert result.database_verified and all(check.satisfied for check in result.operational_invariants)
    finally: source.close()
