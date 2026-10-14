"""Opt-in live PostgreSQL contracts and separate offline policy-setup mocks.

No database/clone/generator is created here. The future owner supplies a real
local composition source and independently observed scoped-count metadata.
Absent live inputs yield explicit skips, not acceptance evidence. Offline mocks
below exercise the setup boundary only; they do not establish installed ACL/RLS
or negative SQLSTATE behavior on PostgreSQL.
"""
from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from stark_t2sql.db.catalog import SchemaSnapshot
from stark_t2sql.db.connections import EvaluationConnectionSource
from stark_t2sql.db.policy_apply import PolicyApplyRequest, _require_evaluation_clone
from stark_t2sql.errors import ConfigurationError
from stark_t2sql.evaluation.reference import AuthorizationObserver
from .conftest import required_input


@pytest.fixture(scope="module")
def actual_authorization_components(project_root):
    if os.environ.get("STARK_TEST_ENABLE_DB_INTEGRATION") != "1":
        pytest.skip("Local DB integration is not separately opted in; source definitions provide no evidence.")
    path=required_input("STARK_TEST_AUTHORIZATION_COMPOSITION_PATH",project_root)
    # Only the later explicitly opted-in owner-supplied source may compose the
    # existing constrained disposable-clone boundary. No guessed credentials,
    # review profile, clone marker or asset digest is synthesized by the test.
    spec=importlib.util.spec_from_file_location("stark_owner_test_composition",path)
    if spec is None or spec.loader is None: pytest.fail("Actual composition source cannot be loaded")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source,snapshot=module.compose_authorization_inputs(project_root)
    if type(source) is not EvaluationConnectionSource or type(snapshot) is not SchemaSnapshot:
        pytest.fail("Actual exact constrained clone source and catalog metadata are required")
    try: yield source,snapshot
    finally: source.close()


@pytest.fixture(scope="module")
def authorization_observer(actual_authorization_components):
    source,snapshot=actual_authorization_components
    return AuthorizationObserver(source,snapshot)


def test_actual_matrix_access_equals_controlled_observations(authorization_observer,actual_authorization_components):
    from benchmarks.authorization.spec import build_probes
    source,snapshot=actual_authorization_components
    representatives={"app_payroll":"payroll","app_hr_bp":"hr_1","app_sales_mgr":"sales"}
    for probe in build_probes(source.matrix,snapshot):
        persona=source.personas.resolve(representatives[probe.business_role])
        observed=authorization_observer.observe(persona,table=probe.table,column=probe.column)
        assert observed.allowed is probe.expected_access
        assert observed.expected_access is probe.expected_access
        if not probe.expected_access: assert observed.sqlstate == "42501"


@pytest.mark.parametrize("selection,column", (("sales",None),("hr_1","employee_number"),("hr_2","employee_number")))
def test_actual_sales_star_and_hr_employee_number_denied(authorization_observer,selection,column):
    result=authorization_observer.observe(selection,table="employees",column=column)
    assert result.allowed is False and result.sqlstate == "42501"


def test_actual_four_scopes_match_independent_external_reference_counts(authorization_observer,project_root):
    # This file is an actual separately recorded reference artifact, unavailable
    # during drafting. No numeric fixture answer is written into test source.
    raw=json.loads(required_input("STARK_TEST_EXPECTED_SCOPE_COUNTS_PATH",project_root).read_text(encoding="utf-8"))
    for selection in ("payroll","hr_1","hr_2","sales"):
        assert authorization_observer.scoped_count(selection,table="employees").count == raw[selection]["employees"]
    for selection in ("payroll","hr_1","hr_2"):
        assert authorization_observer.scoped_count(selection,table="leave_balances").count == raw[selection]["leave_balances"]


def test_authorization_observer_has_no_arbitrary_sql_entrypoint(authorization_observer):
    with pytest.raises(TypeError):
        authorization_observer.observe("hr_1",table="employees",column="employee_id",sql="SET app.principal_id='326'")


UNIT_FIXTURE_DIGEST = sha256(b"R03 mock-only fixture bytes; not the actual fixture").hexdigest()


def unit_clone_marker():
    """Synthetic catalog responses only, never written to a live database."""
    return {"kind": "stark_disposable_evaluation_clone", "clone_token": "unit-only-clone-token-012345",
            "source_database": "unit_source", "source_database_oid": 101,
            "clone_database_oid": 202, "fixture_dump_sha256": UNIT_FIXTURE_DIGEST}


class SetupCursor:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.statements = []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, statement, parameters=None): self.statements.append((statement, parameters))
    def fetchone(self): return next(self.rows)


def unit_apply_request():
    return PolicyApplyRequest("unit_clone", ("sha256",), UNIT_FIXTURE_DIGEST,
                              fixture_restore_completed=True, dedicated_fixture_database=True)


def test_evaluation_policy_setup_accepts_matching_catalog_marker_only():
    cursor = SetupCursor([(202, "unit_clone", json.dumps(unit_clone_marker())), (101,)])
    _require_evaluation_clone(cursor, unit_apply_request())
    assert all(statement.startswith("SELECT ") for statement, _ in cursor.statements)
    assert cursor.statements[-1][1] == ("unit_source",)


@pytest.mark.parametrize("field,value", (
    ("kind", "production"), ("clone_token", "short"), ("clone_token", None),
    ("source_database", "unit_clone"), ("source_database", ""), ("source_database", []),
    ("clone_database_oid", 303), ("clone_database_oid", True),
    ("source_database_oid", 999), ("source_database_oid", True),
    ("fixture_dump_sha256", "0" * 64), ("extra", "unexpected"),
))
def test_evaluation_policy_setup_rejects_bad_clone_metadata(field, value):
    marker = dict(unit_clone_marker(), **{field: value})
    cursor = SetupCursor([(202, "unit_clone", json.dumps(marker)), (101,)])
    with pytest.raises(ConfigurationError): _require_evaluation_clone(cursor, unit_apply_request())
    assert all(statement.startswith("SELECT ") for statement, _ in cursor.statements)


@pytest.mark.parametrize("marker", (None, "{}", "[]", "null", "not-json"))
def test_evaluation_policy_setup_refuses_unmarked_database(marker):
    with pytest.raises(ConfigurationError):
        _require_evaluation_clone(SetupCursor([(202, "unit_clone", marker)]), unit_apply_request())


@pytest.mark.parametrize("source", (None, (202,), (999,)))
def test_evaluation_policy_setup_requires_existing_distinct_source_oid(source):
    cursor = SetupCursor([(202, "unit_clone", json.dumps(unit_clone_marker())), source])
    with pytest.raises(ConfigurationError): _require_evaluation_clone(cursor, unit_apply_request())


@pytest.mark.parametrize("baseline,marked", ((None, False), ("stark_eval_baseline_login", False),
                                          ("stark_eval_baseline_login", True)))
def test_policy_apply_checks_clone_before_any_baseline_ddl(monkeypatch, matrix, tmp_path, baseline, marked):
    from seed_data import TABLE_COLUMNS
    from stark_t2sql.config import RuntimeLimits
    from stark_t2sql.db.connections import AdminConnectionSource
    from stark_t2sql.db import policy_apply as module
    from stark_t2sql.policy.compiler import CompileSettings, compile_policy

    # Unit-only files and mocked catalog/driver. No socket or real provisioning.
    resource_input = tmp_path / "unit_resource_input.txt"
    resource_input.write_bytes(b"R03 mock-only budget input, not a deployment measurement")
    settings = CompileSettings("stark_scope_owner", work_mem_kib=64, temp_file_limit_kib=10000,
        measurement_sha256=sha256(resource_input.read_bytes()).hexdigest(),
        measurement_provenance="R03 mock-only input", baseline_eval_login=baseline)
    plan = compile_policy(matrix, TABLE_COLUMNS, settings)
    cursor = SetupCursor([("unit_clone", "unit_setup", "unit_setup"),
                          (202, "unit_clone", json.dumps(unit_clone_marker()) if marked else None), (101,)])
    @contextmanager
    def connection(*, readonly):
        assert readonly is False
        yield SimpleNamespace(cursor=lambda: cursor)
    budgets = SimpleNamespace(database_work_mem_kib=64, database_temp_file_limit_kib=10000,
                              measurement_source=resource_input)
    administrator = object.__new__(AdminConnectionSource)
    administrator.config = SimpleNamespace(paths=SimpleNamespace(policy_matrix="unit-unused"),
        resource_budgets=SimpleNamespace(require_database_budget_inputs=lambda: budgets), limits=RuntimeLimits())
    monkeypatch.setattr(administrator, "connection", connection)
    monkeypatch.setattr(module, "load_policy", lambda _: matrix)
    monkeypatch.setattr(module, "fixture_digest", lambda *args: UNIT_FIXTURE_DIGEST)
    snapshot = Mock(return_value=SimpleNamespace(columns_by_table=TABLE_COLUMNS))
    monkeypatch.setattr(module, "snapshot_schema", snapshot)
    state_hash = sha256(b"R03 mock-only policy metadata").hexdigest()
    monkeypatch.setattr(module, "policy_state_sha256", lambda *args: state_hash)
    if baseline and not marked:
        with pytest.raises(ConfigurationError, match="trusted clone marker"):
            module.policy_apply(plan, administrator, matrix, request=unit_apply_request())
        snapshot.assert_not_called()
        assert all(statement.startswith("SELECT ") for statement, _ in cursor.statements)
    else:
        binding = module.policy_apply(plan, administrator, matrix, request=unit_apply_request())
        assert binding.policy_state_sha256 == state_hash
        assert [statement for statement, _ in cursor.statements if not statement.startswith("SELECT ")] == list(plan.statements)
