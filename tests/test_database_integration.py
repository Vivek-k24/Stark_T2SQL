"""Explicitly opt-in future PostgreSQL source contracts; never run in drafting.

No database/clone/generator is created here. The future owner supplies a real
local composition source and independently observed scoped-count metadata.
Absent inputs yield explicit skips, not acceptance evidence. Candidate hazards
remain in parser-only tests/prepared safety cases and never enter this module.
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest

from stark_t2sql.db.catalog import SchemaSnapshot
from stark_t2sql.db.connections import EvaluationConnectionSource
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
