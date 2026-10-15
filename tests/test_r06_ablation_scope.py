"""Actual direct harness orchestration with TEST-ONLY mocked SQL execution.

These tests establish metadata and routing behavior, never live rows or RLS.
"""
from types import SimpleNamespace

import pytest

from stark_t2sql.contracts import ColumnMetadata,ExecutionMode,ExpectedOutcome,OutcomeStatus,ReasonCode,RowScopeKind,StoppingLayer
from stark_t2sql.db.executor import ExecutionResult
from stark_t2sql.evaluation.ablation import AblationHarness,ModeProfile
from stark_t2sql.evaluation.cases import Case,CaseSet
from .test_reference_contracts import unit_personas


def unit_harness(matrix,persona,result):
    calls=[]
    ticket=SimpleNamespace(regenerated_sql=result.executed_sql)
    harness=object.__new__(AblationHarness)
    harness._application=None
    harness._runtime=SimpleNamespace(
        personas=SimpleNamespace(resolve=lambda _:persona,fixture_dump_sha256=None),matrix=matrix,
        config=SimpleNamespace(limits=SimpleNamespace(output_row_cap=1000)),
        harness=SimpleNamespace(executor=SimpleNamespace(execute=lambda *args,**kwargs:calls.append((args,kwargs)) or result)),
        validation_authority=SimpleNamespace(review=lambda *_:ticket,discard=lambda _:None),
        trace=SimpleNamespace(write_request=lambda *args,**kwargs:None),
    )
    return harness,calls


@pytest.mark.parametrize("mode",tuple(ExecutionMode))
@pytest.mark.parametrize("persona,sql,scope", (
    ("payroll","SELECT employee_id FROM employees",RowScopeKind.ALL),
    ("hr_1","SELECT employee_id FROM employees",RowScopeKind.ASSIGNED_DIVISIONS),
    ("sales_manager","SELECT employee_id FROM employees",RowScopeKind.DIRECT_REPORTS),
    ("hr_1","SELECT employee_id FROM leave_balances",RowScopeKind.VIA_EMPLOYEES),
    ("hr_1","SELECT department_id FROM departments",RowScopeKind.ALL),
    ("sales_manager","SELECT department_id FROM departments",RowScopeKind.ALL),
    ("hr_1","SELECT e.employee_id FROM employees e JOIN departments d ON e.department_id=d.department_id",RowScopeKind.ASSIGNED_DIVISIONS),
    ("hr_1","SELECT department_id AS employees FROM departments -- leave_balances\n",RowScopeKind.ALL),
    ("hr_1","WITH selected AS (SELECT department_id FROM departments) SELECT department_id FROM selected",RowScopeKind.ALL),
))
def test_actual_direct_harness_attaches_physical_table_scope(matrix,unit_personas,fixture_date,mode,persona,sql,scope):
    result=ExecutionResult(OutcomeStatus.ANSWERED,StoppingLayer.NONE,ReasonCode.ANSWERED,1000,executed_sql=sql)
    harness,calls=unit_harness(matrix,unit_personas[persona],result)
    case=Case("unit-r06-scope",CaseSet.REGRESSIONS,persona,fixture_date,ExpectedOutcome.SCOPED_RESULT,sql=sql,reference_sql=sql)
    outcome=harness.direct(case,ModeProfile(mode,1 if mode is ExecutionMode.UNCONTROLLED else 2))
    assert outcome.status is OutcomeStatus.ANSWERED
    assert len(calls) == 1
    assert outcome.row_scope is (RowScopeKind.ALL if mode is ExecutionMode.UNCONTROLLED else scope)


def test_actual_direct_scope_comes_from_executed_sql_not_the_source_operand(matrix,unit_personas,fixture_date):
    result=ExecutionResult(OutcomeStatus.ANSWERED,StoppingLayer.NONE,ReasonCode.ANSWERED,1000,
        executed_sql="SELECT department_id FROM departments")
    harness,_=unit_harness(matrix,unit_personas["hr_1"],result)
    case=Case("unit-r06-executed-scope",CaseSet.REGRESSIONS,"hr_1",fixture_date,ExpectedOutcome.BLOCKED_ANY,
        sql="SELECT employee_id FROM employees")
    outcome=harness.direct(case,ModeProfile(ExecutionMode.NO_VALIDATOR,2))
    assert outcome.row_scope is RowScopeKind.ALL


@pytest.mark.parametrize("sql", ("SELECT * FROM absent_table","SELECT employee_id","SELECT employee_id FROM employees e JOIN departments e ON TRUE"))
def test_unknown_answered_scope_discards_mock_rows_instead_of_claiming_all(matrix,unit_personas,fixture_date,sql):
    result=ExecutionResult(OutcomeStatus.ANSWERED,StoppingLayer.NONE,ReasonCode.ANSWERED,1000,
        executed_sql=sql,columns=(ColumnMetadata("x"),),rows=((1,),))
    harness,_=unit_harness(matrix,unit_personas["hr_1"],result)
    case=Case("unit-r06-unknown-scope",CaseSet.REGRESSIONS,"hr_1",fixture_date,ExpectedOutcome.BLOCKED_ANY,sql=sql)
    outcome=harness.direct(case,ModeProfile(ExecutionMode.NO_VALIDATOR,2))
    assert outcome.status is not OutcomeStatus.ANSWERED and not outcome.rows
    assert outcome.row_scope is None
    assert outcome.executed_sql == sql  # Preserve execution evidence after metadata failure.


def test_answered_result_without_executed_sql_has_no_approved_scope(matrix,unit_personas,fixture_date):
    result=ExecutionResult(OutcomeStatus.ANSWERED,StoppingLayer.NONE,ReasonCode.ANSWERED,1000,
        columns=(ColumnMetadata("x"),),rows=((1,),))
    harness,_=unit_harness(matrix,unit_personas["hr_1"],result)
    case=Case("unit-r06-missing-sql",CaseSet.REGRESSIONS,"hr_1",fixture_date,ExpectedOutcome.BLOCKED_ANY,sql="SELECT 1")
    outcome=harness.direct(case,ModeProfile(ExecutionMode.NO_VALIDATOR,2))
    assert outcome.status is OutcomeStatus.ERROR and not outcome.rows and outcome.row_scope is None


def test_no_validator_db_denial_keeps_attribution_without_inventing_scope(matrix,unit_personas,fixture_date):
    sql="SELECT base_salary FROM employee_compensation"
    result=ExecutionResult(OutcomeStatus.BLOCKED_DB,StoppingLayer.DATABASE,ReasonCode.DB_PERMISSION_DENIED,1000,executed_sql=sql,sqlstate="42501")
    harness,calls=unit_harness(matrix,unit_personas["sales_manager"],result)
    case=Case("unit-r06-denied-scope",CaseSet.REGRESSIONS,"sales_manager",fixture_date,ExpectedOutcome.BLOCKED_DB,sql=sql)
    outcome=harness.direct(case,ModeProfile(ExecutionMode.NO_VALIDATOR,2))
    assert calls and outcome.status is OutcomeStatus.BLOCKED_DB
    assert outcome.stopping_layer is StoppingLayer.DATABASE and outcome.row_scope is None
