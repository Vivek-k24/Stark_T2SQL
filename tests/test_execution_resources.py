"""Driver-boundary mocks, not SQL submissions or measured resource evidence."""
from collections import namedtuple
from contextlib import contextmanager
from hashlib import sha256
from importlib import import_module
import sys
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from seed_data import TABLE_COLUMNS
from stark_t2sql.config import DatabaseCredentials, IsolationControls, ResourceBudgets, RuntimeLimits
from stark_t2sql.contracts import ExecutionMode, OutcomeStatus, ReasonCode
from stark_t2sql.db import connections
from stark_t2sql.errors import ConfigurationError, LocalEndpointError, MissingDependencyError
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


class AuditCursor:
    """Ordered mock catalog responses; never opens a socket."""
    def __init__(self, *, one=(), many=()):
        self.one, self.many = iter(one), iter(many)
        self.calls = []
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, query, parameters=()): self.calls.append((query, parameters))
    def fetchone(self): return next(self.one)
    def fetchall(self): return next(self.many)


@pytest.mark.parametrize("attribute", ("rolsuper", "rolbypassrls", "rolcreatedb", "rolcreaterole", "rolreplication", "rolinherit"))
def test_role_audit_rejects_each_elevated_login_flag(attribute):
    flags = dict(rolcanlogin=True, rolinherit=False, rolsuper=False, rolbypassrls=False,
                 rolcreatedb=False, rolcreaterole=False, rolreplication=False)
    flags[attribute] = True
    with pytest.raises(ConfigurationError, match="unsafe login"):
        connections._role_flags(AuditCursor(one=[(101, *flags.values())]), "unit_login", login=True)


@pytest.mark.parametrize("can_login,expected_login", ((True, False), (False, True)))
def test_role_audit_refuses_wrong_login_kind(can_login, expected_login):
    with pytest.raises(ConfigurationError):
        connections._role_flags(AuditCursor(one=[(101, can_login, False, False, False, False, False, False)]),
                                "unit_identity", login=expected_login)


def test_role_audit_accepts_unprivileged_explicit_login():
    assert connections._role_flags(AuditCursor(one=[(101, True, False, False, False, False, False, False)]),
                                   "unit_login", login=True) == 101


@pytest.mark.parametrize("flags", ((True, False, False), (False, True, False), (False, False, True)))
def test_ddl_audit_rejects_database_owner_schema_create_and_object_ownership(flags):
    cursor = AuditCursor(one=[(flag,) for flag in flags])
    with pytest.raises(ConfigurationError, match="owns objects"):
        connections._deny_ddl(cursor, "unit_login", 101)
    assert "d.datdba = %s" in cursor.calls[0][0] and "has_database_privilege" in cursor.calls[0][0]
    assert "has_schema_privilege" in cursor.calls[1][0]


def test_ddl_audit_accepts_no_ownership_or_create_privileges():
    connections._deny_ddl(AuditCursor(one=[(False,), (False,), (False,)]), "unit_login", 101)


@pytest.fixture
def audit_config():
    # Synthetic introspection expectations only, not measured deployment inputs.
    budgets = SimpleNamespace(database_work_mem_kib=64, database_temp_file_limit_kib=10000,
                              require_database_budget_inputs=Mock())
    return SimpleNamespace(limits=RuntimeLimits(), resource_budgets=budgets)


def unit_effective_settings():
    return {"default_transaction_read_only": "on", "statement_timeout": "15000", "row_security": "on",
            "work_mem": "64", "temp_file_limit": "10000", "search_path": '"pg_catalog", "public", "pg_temp"'}


def unit_login_defaults():
    return ["default_transaction_read_only=on", "statement_timeout=15s", "row_security=on", "work_mem=64kB",
            "temp_file_limit=10000kB", 'search_path="pg_catalog", "public", "pg_temp"']


def test_settings_audit_accepts_pinned_baseline_login(audit_config):
    cursor = AuditCursor(many=[list(unit_effective_settings().items())], one=[(unit_login_defaults(),)])
    connections._settings(cursor, audit_config, "stark_eval_baseline_login", "public")
    assert cursor.calls[-1][1] == ("stark_eval_baseline_login",)


@pytest.mark.parametrize("key,value", (("default_transaction_read_only", "off"), ("row_security", "off"),
    ("statement_timeout", "0"), ("statement_timeout", "15001"), ("work_mem", "128"),
    ("temp_file_limit", "-1"), ("search_path", '"pg_temp", "public", "pg_catalog"')))
def test_settings_audit_refuses_changed_effective_controls(audit_config, key, value):
    settings = dict(unit_effective_settings(), **{key: value})
    with pytest.raises(ConfigurationError, match="settings differ"):
        connections._settings(AuditCursor(many=[list(settings.items())]), audit_config, "unit_login", "public")


@pytest.mark.parametrize("missing", ("statement_timeout", "default_transaction_read_only", "work_mem", "temp_file_limit", "search_path"))
def test_settings_audit_requires_persistent_login_defaults(audit_config, missing):
    declared = [item for item in unit_login_defaults() if not item.startswith(missing + "=")]
    with pytest.raises(ConfigurationError, match="pinned on the login"):
        connections._settings(AuditCursor(many=[list(unit_effective_settings().items())], one=[(declared,)]),
                              audit_config, "unit_login", "public")


@pytest.mark.parametrize("address,port", (("192.0.2.1", 5432), (None, 5432), ("127.0.0.2", 5432), ("127.0.0.1", 9999)))
def test_connection_audit_refuses_nonlocal_or_mismatched_destination(monkeypatch, matrix, audit_config, address, port):
    credentials = DatabaseCredentials("127.0.0.1", 5432, "unit_db", "stark_hr_login", "unit-only-not-a-secret")
    cursor = AuditCursor(one=[(credentials.login_role, credentials.login_role, "unit_db", address, port)])
    connection = SimpleNamespace(cursor=lambda: cursor)
    flags = Mock(side_effect=AssertionError("must stop before privilege audit"))
    monkeypatch.setattr(connections, "_role_flags", flags)
    with pytest.raises((ConfigurationError, LocalEndpointError)):
        connections._audit(connection, audit_config, matrix, credentials, matrix.role("app_hr_bp"))
    flags.assert_not_called()
    assert connection.readonly is True


@pytest.mark.parametrize("baseline", (False, True))
def test_connection_audit_routes_exact_membership_and_privilege_checks(monkeypatch, matrix, audit_config, baseline):
    business = None if baseline else matrix.role("app_hr_bp")
    login = "stark_eval_baseline_login" if baseline else business.login_role
    credentials = DatabaseCredentials("127.0.0.1", 5432, "unit_db", login, "unit-only-not-a-secret")
    identity = (login, login, "unit_db", "127.0.0.1", 5432)
    cursor = AuditCursor(one=[identity, (False,)], many=[[] if baseline else [(business.name, False, False, True)]])
    connection = SimpleNamespace(cursor=lambda: cursor, rollback=Mock())
    for name in ("_role_flags", "_deny_ddl", "_settings", "_relation_privileges", "_function_privileges"):
        monkeypatch.setattr(connections, name, Mock(return_value=101))
    connections._audit(connection, audit_config, matrix, credentials, business)
    connections._relation_privileges.assert_any_call(cursor, matrix, login, baseline=baseline, direct_login=not baseline)
    connections._function_privileges.assert_any_call(cursor, matrix, login, baseline=baseline, login=True)
    if business:
        connections._relation_privileges.assert_any_call(cursor, matrix, business.name)
    connection.rollback.assert_called_once_with()
    assert connection.readonly is True


@pytest.mark.parametrize("membership", (
    [("app_hr_bp", True, False, True)], [("app_hr_bp", False, True, True)],
    [("app_hr_bp", False, False, False)], [("app_payroll", False, False, True)],
))
@pytest.mark.parametrize("baseline", (False, True))
def test_connection_audit_refuses_widened_or_wrong_membership(monkeypatch, matrix, audit_config, membership, baseline):
    login = "stark_eval_baseline_login" if baseline else "stark_hr_login"
    credentials = DatabaseCredentials("127.0.0.1", 5432, "unit_db", login, "unit-only-not-a-secret")
    cursor = AuditCursor(one=[(login, login, "unit_db", "127.0.0.1", 5432)], many=[membership])
    monkeypatch.setattr(connections, "_role_flags", lambda *args, **kwargs: 101)
    monkeypatch.setattr(connections, "_deny_ddl", lambda *args: None)
    with pytest.raises(ConfigurationError, match="membership widens"):
        connections._audit(SimpleNamespace(cursor=lambda: cursor), audit_config, matrix, credentials,
                           None if baseline else matrix.role("app_hr_bp"))


class PrivilegeCursor:
    """Mock physical columns/ACLs derived from the frozen R02 column contract."""
    def __init__(self, matrix, defect=None):
        self.matrix, self.defect = matrix, defect
        self.relations = [(i, "public", name, "r", name in matrix.rls_tables, name in matrix.rls_tables)
                          for i, name in enumerate(TABLE_COLUMNS, 1)]
        if defect in {"rls_disabled", "force_disabled"}:
            self.relations = [(oid, schema, name, kind, False if defect == "rls_disabled" else rls, False)
                              if name == "employees" else (oid, schema, name, kind, rls, force)
                              for oid, schema, name, kind, rls, force in self.relations]
        if defect == "extra_view": self.relations.append((1000, "public", "unit_unmanaged_view", "v", False, False))
        if defect == "sequence_privilege": self.relations.append((1001, "public", "unit_sequence", "S", False, False))
    def execute(self, query, parameters=()): self.query, self.parameters = query, parameters
    def fetchall(self):
        if "SELECT c.oid" in self.query:
            return self.relations[:-1] if self.defect == "missing_table" else self.relations
        name = self.relations[self.parameters[0] - 1][2]
        return [(column,) for column in TABLE_COLUMNS[name]]
    def fetchone(self):
        query, parameters = self.query, self.parameters
        if "aclexplode" in query:
            return (self.defect == ("public_acl" if "acl.grantee = 0" in query else "table_override"),)
        if "has_sequence_privilege" in query: return (True,)
        role, oid = parameters[:2]
        table = self.relations[oid - 1][2]
        access = self.matrix.role(role).tables.get(table)
        if "has_table_privilege" in query:
            if "'SELECT'" not in query: return (self.defect == "write",)
            return (access is not None and access.columns is None or table == "employees" and self.defect == "table_override",)
        if "'SELECT'" not in query: return (False,)
        column = parameters[2]
        allowed = access is not None and (access.columns is None or column in access.columns)
        if self.defect == "hidden_column" and table == "employees" and column == "employee_number": allowed = True
        if self.defect == "missing_grant" and table == "employees" and column == "employee_id": allowed = False
        return (allowed,)


def test_live_column_audit_contract_accepts_exact_hr_entitlements(matrix):
    connections._relation_privileges(PrivilegeCursor(matrix), matrix, "app_hr_bp")


@pytest.mark.parametrize("defect", ("missing_table", "table_override", "hidden_column", "missing_grant", "write", "public_acl",
                                   "rls_disabled", "force_disabled", "extra_view", "sequence_privilege"))
def test_live_column_audit_contract_rejects_bad_mock_privileges(matrix, defect):
    with pytest.raises(ConfigurationError):
        connections._relation_privileges(PrivilegeCursor(matrix, defect), matrix, "app_hr_bp")


@pytest.mark.parametrize("change", ("predicate", "function_body", "search_path"))
def test_policy_fingerprint_rejects_mock_catalog_drift(matrix, change):
    from stark_t2sql.db.catalog import policy_state_sha256
    policies = [("employees", True, True, "unit_scope", "r", True, ["app_hr_bp"], "unit_scope_predicate", None)]
    functions = [("hr_bp_current_divisions", "", "f", True, "s", "stark_scope_owner", ["search_path=pg_catalog,public,pg_temp"], "unit_body")]
    original = SimpleNamespace(cursor=lambda: AuditCursor(many=[policies, functions]))
    expected = policy_state_sha256(original, matrix)
    if change == "predicate": policies = [tuple(list(policies[0][:-2]) + ["true", None])]
    elif change == "function_body": functions = [functions[0][:-1] + ("changed_unit_body",)]
    else: functions = [functions[0][:-2] + (["search_path=pg_temp,public"], functions[0][-1])]
    altered = SimpleNamespace(cursor=lambda: AuditCursor(many=[policies, functions]), rollback=Mock())
    with pytest.raises(ConfigurationError, match="trusted setup binding"):
        connections._require_policy_state(altered, matrix, expected)
    altered.rollback.assert_not_called()


def test_matching_policy_fingerprint_ends_audit_transaction(matrix):
    from stark_t2sql.db.catalog import policy_state_sha256
    connection = SimpleNamespace(cursor=lambda: AuditCursor(many=[[], []]), rollback=Mock())
    connections._require_policy_state(connection, matrix, policy_state_sha256(connection, matrix))
    connection.rollback.assert_called_once_with()
    assert connection.readonly is True


@pytest.mark.parametrize("sql", ("SET app.principal_id='326'", "SET ROLE app_payroll", "SELECT 1; SET app.principal_id='326'"))
def test_command_and_multistatement_entry_guard_without_inventing_parser_approval(matrix, sql):
    import sqlglot
    from stark_t2sql.security.validator import ReviewedSQLValidator, ValidationRuleCode, _Rejected
    # Test the existing statement-entry guard in isolation; no approval/profile
    # is constructed and this does not establish full R05 parser acceptance.
    validator = ReviewedSQLValidator(matrix)
    with pytest.raises(_Rejected) as stopped: validator._parse_one(sqlglot, sql)
    assert stopped.value.code in {ValidationRuleCode.TOP_LEVEL, ValidationRuleCode.STATEMENT_COUNT}


def mocked_evaluation_source(matrix, persona):
    source = object.__new__(connections.EvaluationConnectionSource)
    source.matrix = matrix
    source.personas = SimpleNamespace(resolve=lambda selection: persona)
    source.config = SimpleNamespace(limits=RuntimeLimits(), resource_budgets=SimpleNamespace(require_database_budget_inputs=Mock()))
    source.clone_alias = "unit_clone"
    source.provenance = SimpleNamespace(clone_database="unit_clone", clone_token="unit-only-clone-token",
                                       fixture_dump_sha256=sha256(b"unit-only fixture").hexdigest())
    source.connection = Mock(side_effect=AssertionError("unaudited unit source must not open"))
    return source


def test_no_validator_keeps_mandatory_harness_safety_review(matrix, payroll_persona):
    from stark_t2sql.db.executor import EvaluationExecutor
    from stark_t2sql.security.validator import HarnessSafetyReviewer
    source = mocked_evaluation_source(matrix, payroll_persona)
    result = EvaluationExecutor(source, safety_reviewer=HarnessSafetyReviewer(matrix)).execute(
        payroll_persona, "SET app.principal_id='1'", mode=ExecutionMode.NO_VALIDATOR)
    source.connection.assert_not_called()
    assert result.executed_sql is None and result.reason_code is ReasonCode.HARNESS_SAFETY_STOP


@pytest.mark.parametrize("mode", (ExecutionMode.NO_VALIDATOR, ExecutionMode.UNCONTROLLED))
@pytest.mark.parametrize("permission_denied", (False, True))
def test_ablation_driver_routing_keeps_business_identity_except_uncontrolled(monkeypatch, matrix, payroll_persona, mode, permission_denied):
    from stark_t2sql.db.executor import EvaluationExecutor, HarnessSelectReview
    module = import_module("stark_t2sql.db.executor")
    source = mocked_evaluation_source(matrix, payroll_persona)
    connection = MemoryConnection([(1,)])
    selected = []
    @contextmanager
    def lease(*, persona):
        selected.append(persona)
        yield connection
    source.connection = lease
    candidate = "SELECT 1"
    if permission_denied:
        execute = connection.cursor_object.execute
        def deny_candidate(query, parameters=None):
            execute(query, parameters)
            if query == candidate:
                error = RuntimeError("unit-only permission denial, not live PostgreSQL")
                error.pgcode = "42501"
                raise error
        monkeypatch.setattr(connection.cursor_object, "execute", deny_candidate)
    review = HarnessSelectReview(candidate, sha256(candidate.encode()).hexdigest(), mode,
        payroll_persona.principal_id, matrix.sha256, source.provenance.clone_token,
        source.provenance.fixture_dump_sha256, "unit-only reviewer, not parser approval")
    reviewer = SimpleNamespace(review_candidate=Mock(return_value=review))
    monkeypatch.setitem(sys.modules, "psycopg2", SimpleNamespace(sql=SimpleNamespace(SQL=TextSQL, Identifier=lambda name: '"' + name + '"')))
    monkeypatch.setattr(module, "_ClientDeadline", NoDeadlineThread)
    result = EvaluationExecutor(source, safety_reviewer=reviewer).execute(payroll_persona, candidate, mode=mode)
    assert result.executed_sql == candidate
    if permission_denied:
        assert result.status is OutcomeStatus.BLOCKED_DB and result.reason_code is ReasonCode.DB_PERMISSION_DENIED
        assert connection.rollbacks == 1 and connection.commits == 0
    else:
        assert result.status is OutcomeStatus.ANSWERED
    scoped = mode is ExecutionMode.NO_VALIDATOR
    assert selected == [payroll_persona if scoped else None]
    calls = connection.cursor_object.calls
    if scoped:
        assert calls[0][1] == ("326",) and calls[1][0] == 'SET LOCAL ROLE "app_payroll"'
    else:
        assert calls == [(candidate, None)]
