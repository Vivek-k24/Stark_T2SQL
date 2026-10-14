"""Driver-boundary mocks, not SQL submissions or measured resource evidence."""
from collections import namedtuple
from importlib import import_module
import sys
from time import monotonic
from types import SimpleNamespace

import pytest

from stark_t2sql.config import IsolationControls, ResourceBudgets, RuntimeLimits
from stark_t2sql.contracts import OutcomeStatus, ReasonCode
from stark_t2sql.errors import LocalEndpointError, MissingDependencyError
from stark_t2sql.utils.local_only import LoopbackEndpoint, require_allowed_url


@pytest.mark.parametrize("sqlstate,status,reason", (
    ("42501",OutcomeStatus.BLOCKED_DB,ReasonCode.DB_PERMISSION_DENIED),
    ("57014",OutcomeStatus.TIMEOUT,ReasonCode.STATEMENT_TIMEOUT),
    ("42601",OutcomeStatus.MODEL_SQL_ERROR,ReasonCode.SQL_SYNTAX_ERROR),
    ("42P01",OutcomeStatus.MODEL_SQL_ERROR,ReasonCode.UNKNOWN_DATABASE_OBJECT),
    ("42703",OutcomeStatus.MODEL_SQL_ERROR,ReasonCode.UNKNOWN_DATABASE_OBJECT),
    ("42883",OutcomeStatus.MODEL_SQL_ERROR,ReasonCode.UNKNOWN_DATABASE_OBJECT),
    ("XX000",OutcomeStatus.ERROR,ReasonCode.DATABASE_ERROR),
))
def test_sqlstate_contract_keeps_private_driver_detail(sqlstate,status,reason):
    module = import_module("stark_t2sql.db.executor")
    error = RuntimeError("Private driver detail")
    error.pgcode = sqlstate
    result = module._failure_result(error,row_cap=1000,started=monotonic())
    assert result.status is status and result.reason_code is reason
    assert not result.rows and result.diagnostics[0].sqlstate == sqlstate
    assert "Private driver detail" in result.diagnostics[0].internal_detail


class NoDeadlineThread:
    def __init__(self,*args): self._expired = SimpleNamespace(is_set=lambda:False)
    def start(self): pass
    def require_time(self): pass
    def finish(self): pass


class TextSQL(str):
    def format(self,other): return TextSQL(str(self).replace("{}",str(other)))


class MemoryCursor:
    def __init__(self,rows):
        self.rows = rows; self.calls = []; self.requested = []
        self.description = (SimpleNamespace(name="unit_value",null_ok=False),)
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,text,parameters=None): self.calls.append((str(text),parameters))
    def fetchmany(self,count): self.requested.append(count); return self.rows[:count]


class MemoryConnection:
    def __init__(self,rows): self.cursor_object = MemoryCursor(rows); self.commits=0; self.rollbacks=0
    def cursor(self): return self.cursor_object
    def commit(self): self.commits+=1
    def rollback(self): self.rollbacks+=1


@pytest.mark.parametrize("count,truncated", ((2,False),(3,True)))
def test_cap_plus_one_fetch_and_principal_before_role(monkeypatch,payroll_persona,count,truncated):
    module = import_module("stark_t2sql.db.executor")
    monkeypatch.setitem(sys.modules,"psycopg2",SimpleNamespace(sql=SimpleNamespace(SQL=TextSQL,Identifier=lambda text:'"'+text+'"')))
    monkeypatch.setattr(module,"_ClientDeadline",NoDeadlineThread)
    connection = MemoryConnection([(index,) for index in range(count)])
    started = monotonic(); record=[]
    result = module._transaction(connection,principal=payroll_persona,switch_business_role=True,
        approved_sql="SELECT 1",row_cap=2,started=started,deadline=started+15,
        client_timeout_seconds=15,execution_record=record)
    assert connection.readonly and connection.cursor_object.requested == [3]
    assert result.truncated is truncated and len(result.rows) == 2
    calls = connection.cursor_object.calls
    assert calls[0][1] == ("326",) and "set_config" in calls[0][0]
    assert calls[1][0] == 'SET LOCAL ROLE "app_payroll"'
    assert calls[2][0] == "SELECT 1" and record == ["SELECT 1"]


def test_output_cap_is_not_used_as_execution_work_budget():
    limits = RuntimeLimits()
    assert limits.generation_timeout_seconds == 120 and limits.statement_timeout_seconds == 15
    assert limits.output_row_cap == 1000
    with pytest.raises(MissingDependencyError): ResourceBudgets().require_database_budget_inputs()
    isolation = IsolationControls()
    assert isolation.max_concurrent_requests == 1
    assert isolation.require_disposable_fixture_clone and isolation.require_select_only_candidate_login
    assert not isolation.allow_administrative_candidate_execution


@pytest.mark.parametrize("url", (
    "http://example.com:8080/completion", "http://127.0.0.1:9999/completion",
    "http://127.0.0.1:8080@external.example:8080/completion", "http://localhost.evil:8080/",
    "http://127.0.0.1/completion", "http://127.0.0.1:08080/", "http://127.0.0.1:8080/#override",
))
def test_destination_guard_rejects_external_or_unlisted_destination(url):
    with pytest.raises(LocalEndpointError):
        require_allowed_url(url,allowed_endpoints=(LoopbackEndpoint("http","127.0.0.1",8080),))


def test_localhost_is_numeric_and_exact_allowlist():
    assert require_allowed_url("http://localhost:8080/completion",allowed_endpoints=(LoopbackEndpoint("http","127.0.0.1",8080),)) == "http://127.0.0.1:8080/completion"
