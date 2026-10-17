"""Offline reference/probe contracts with no human approval or live DB evidence.

Pure render mocks describe unit protocol strings only; their digests do not
stand in for a dump, fixture, policy installation or human reference review.
The actual-review immutability case still requires the owner's external input.
Constructed reviews are explicitly TEST-ONLY and cannot authorize a reference.
Conditional orchestration tests stub evidence approval and database operations;
they do not establish persona/RLS equivalence or produce owner scope records.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError,fields,MISSING,replace
from datetime import date
import json
import sys
from types import SimpleNamespace

import pytest

from stark_t2sql.contracts import ColumnMetadata,ExecutionMode,ExpectedOutcome,OutcomeStatus,RowScopeKind,Persona
from stark_t2sql.db.catalog import ColumnDefinition,SchemaSnapshot,TableDefinition
from stark_t2sql.errors import ConfigurationError,MissingDependencyError
from stark_t2sql.evaluation.cases import Case,CaseSet
from stark_t2sql.evaluation.reference import (
    AuthorizationObserver,ReferenceAuthority,ReferenceReview,ScopeReviewStore,_render_reference,
    _reference_columns,_require_reference_lineage,physical_reference_tables,reference_row_scope,
)
from stark_t2sql.utils.fingerprints import sha256_context
from stark_t2sql.semantic.models import ColumnRef
from .conftest import required_input


def unit_render_protocol(text):
    # This untyped mock is never a ReferenceReview, so it cannot authorize any
    # computation through ReferenceAuthority. It isolates pure literal binding.
    return SimpleNamespace(template_sha256=sha256_context(text),principal_marker="{{principal}}",as_of_marker="{{business_date}}")


def test_reference_render_binds_only_typed_principal_and_explicit_date(payroll_persona,fixture_date):
    text="SELECT {{principal}} AS unit_principal, {{business_date}} AS unit_business_date"
    rendered=_render_reference(text,unit_render_protocol(text),payroll_persona,fixture_date)
    assert rendered == "SELECT 326 AS unit_principal, DATE '2026-10-12' AS unit_business_date"


def test_reference_source_digest_disallows_candidate_substitution(payroll_persona,fixture_date):
    frozen="SELECT {{principal}} AS unit_principal, {{business_date}} AS unit_business_date"
    with pytest.raises(MissingDependencyError):
        _render_reference(frozen+"; SELECT 1",unit_render_protocol(frozen),payroll_persona,fixture_date)


def test_reference_slot_occurs_once_and_cannot_overlap(payroll_persona,fixture_date):
    duplicated="SELECT {{principal}}, {{principal}}, {{business_date}}"
    with pytest.raises(ConfigurationError):
        _render_reference(duplicated,unit_render_protocol(duplicated),payroll_persona,fixture_date)
    text="SELECT {{slot}}"
    mock=SimpleNamespace(template_sha256=sha256_context(text),principal_marker="{{slot}}",as_of_marker="{slot}")
    with pytest.raises(ConfigurationError): _render_reference(text,mock,payroll_persona,fixture_date)


def test_reference_review_scope_and_select_evidence_have_no_defaults():
    metadata={field.name:field for field in fields(ReferenceReview)}
    for required in ("row_scope","scope_review_reference","select_only_reviewed","fixture_dump_sha256","source_policy_state_sha256"):
        assert metadata[required].default is MISSING and metadata[required].default_factory is MISSING


def test_no_owner_review_is_unavailable_before_any_reference_source_call(payroll_persona,fixture_date):
    case=Case("unit-reference-contract",CaseSet.REGRESSIONS,"payroll",fixture_date,
        ExpectedOutcome.MATCH_REFERENCE,question="Unit reference dependency question",
        reference_sql="SELECT employee_id FROM employees")
    calls=[]
    def forbidden(*args,**kwargs): calls.append((args,kwargs)); raise AssertionError("No reference capability is available")
    authority=object.__new__(ReferenceAuthority)
    authority._lookup=lambda case_id,mode:None
    authority.source=SimpleNamespace(personas=SimpleNamespace(resolve=forbidden),connection=forbidden)
    authority.admin_source=SimpleNamespace(connection=forbidden)
    authority._baseline_executor=SimpleNamespace(execute=forbidden)
    result=authority.evaluate(case,ExecutionMode.FULL)
    assert not result.available and result.table is None and not result.proves_legitimate
    assert calls == []
    with pytest.raises(TypeError): authority.evaluate(case,ExecutionMode.FULL,candidate_sql="SELECT 1")


def test_generic_sources_cannot_construct_reference_authority():
    with pytest.raises(ConfigurationError):
        ReferenceAuthority(object(),object(),lookup_review=lambda *args:None,baseline_executor=object())


def test_actual_external_reference_review_is_frozen(project_root):
    raw=json.loads(required_input("STARK_TEST_REFERENCE_REVIEW_PATH",project_root).read_text(encoding="utf-8"))
    raw["mode"]=ExecutionMode(raw["mode"])
    raw["row_scope"]=RowScopeKind(raw["row_scope"])
    raw["as_of_date"]=date.fromisoformat(raw["as_of_date"])
    raw["projection"]=tuple(ColumnMetadata(**column) for column in raw["projection"])
    raw["data_tables"]=tuple(raw.get("data_tables",()))
    raw["data_columns"]=tuple(ColumnRef(**column) for column in raw.get("data_columns",()))
    review=ReferenceReview(**raw)
    with pytest.raises(FrozenInstanceError): review.principal_id=review.principal_id+1
    assert type(review.projection) is tuple and review.scope_review_reference


class TextSQL(str):
    def format(self,*values):
        text=str(self)
        for value in values: text=text.replace("{}",str(value),1)
        return TextSQL(text)


@pytest.fixture
def mocked_observer(monkeypatch,matrix,payroll_persona,hr_persona):
    # Hand-authored schema identifiers are unit metadata, not employee records
    # or an assertion about historical schema fidelity. No row values exist.
    names=("employee_id","employee_number","first_name","last_name","email","department_id","position_id",
        "location_id","manager_id","hire_date","termination_date","status","employment_type","legal_entity")
    snapshot=SchemaSnapshot("public",(TableDefinition("employees",tuple(
        ColumnDefinition(name,"text",True,index+1) for index,name in enumerate(names))),))
    personas={"payroll":payroll_persona,"hr_1":hr_persona}
    observer=object.__new__(AuthorizationObserver)
    observer.source=SimpleNamespace(matrix=matrix,personas=SimpleNamespace(resolve=lambda selected:personas[selected] if type(selected) is str else selected))
    observer.snapshot=snapshot
    monkeypatch.setitem(sys.modules,"psycopg2",SimpleNamespace(sql=SimpleNamespace(SQL=TextSQL,Identifier=lambda name:'"'+name.replace('"','""')+'"')))
    return observer


def test_observer_generates_only_finite_fixed_projection_queries(mocked_observer):
    calls=[]
    mocked_observer._read=lambda persona,query,**kwargs:calls.append((persona,str(query),kwargs))
    observed=mocked_observer.observe("payroll",table="employees",column="employee_id")
    assert observed.allowed is True and observed.expected_access
    assert calls[0][1] == 'SELECT "employee_id" FROM "public"."employees" LIMIT 0'
    with pytest.raises(ConfigurationError): mocked_observer.observe("payroll",table="employees",column="employee_id; SET ROLE app_payroll")
    with pytest.raises(ConfigurationError): mocked_observer.observe("payroll",table="pg_catalog.pg_roles",column=None)
    with pytest.raises(TypeError): mocked_observer.observe("payroll",table="employees",column=None,sql="SELECT 1")
    assert len(calls) == 1


def test_denied_column_probe_preserves_actual_driver_state_without_admin_fallback(mocked_observer):
    def denied(*args,**kwargs):
        error=RuntimeError("Private unit permission detail")
        error.pgcode="42501"
        raise error
    mocked_observer._read=denied
    observed=mocked_observer.observe("hr_1",table="employees",column="employee_number")
    assert observed.allowed is False and not observed.expected_access and observed.sqlstate == "42501"
    assert observed.diagnostics


def test_scoped_counts_admit_only_source_defined_rls_relations(mocked_observer):
    calls=[]
    def read(persona,query,**kwargs): calls.append((str(query),kwargs)); return 0
    mocked_observer._read=read
    observed=mocked_observer.scoped_count("hr_1",table="employees")
    assert observed.count == 0  # Unit mock operand, never a fixture answer.
    assert calls == [('SELECT COUNT(*) FROM "public"."employees"',{"count":True})]
    with pytest.raises(ConfigurationError): mocked_observer.scoped_count("hr_1",table="employee_compensation")
    assert len(calls) == 1


# R06 unit operands below are explicitly TEST-ONLY, not signed owner review,
# reference answers, live scope equivalence, or actual database provenance.
UNIT_DIGEST = sha256_context("TEST-ONLY R06 unit provenance")


def unit_review(sql="SELECT employee_id FROM employees WHERE manager_id = {{principal}}", **changes):
    values = dict(
        case_id="unit-reference-contract", mode=ExecutionMode.FULL, persona="hr_1", principal_id=47,
        as_of_date=date(2026,10,12), template_sha256=sha256_context(sql),
        projection=(ColumnMetadata("employee_id",canonical_identity="employee.id"),),
        row_scope=RowScopeKind.ASSIGNED_DIVISIONS, fixture_dump_sha256=UNIT_DIGEST,
        source_policy_state_sha256=UNIT_DIGEST, review_reference="TEST-ONLY unit metadata; no owner approval",
        scope_review_reference="TEST_ONLY.json", select_only_reviewed=True, principal_marker="{{principal}}",
        data_tables=("employees",), data_columns=(ColumnRef("employees","employee_id"),ColumnRef("employees","manager_id")),
    )
    values.update(changes)
    return ReferenceReview(**values)


@pytest.fixture
def unit_personas(payroll_persona,hr_persona,matrix):
    return {"payroll":payroll_persona,"hr_1":hr_persona,
            "sales_manager":Persona("TEST-ONLY Sales", "app_sales_mgr", 991, matrix.role("app_sales_mgr").login_role)}


@pytest.fixture
def unavailable_authority(matrix,unit_personas):
    from unittest.mock import Mock

    authority=object.__new__(ReferenceAuthority)
    authority.source=SimpleNamespace(matrix=matrix,personas=SimpleNamespace(resolve=lambda key:unit_personas[key]))
    authority.source.connection=Mock(side_effect=AssertionError("No DB operation is authorized by a unit review"))
    authority.admin_source=SimpleNamespace(connection=Mock(side_effect=AssertionError("No admin reference is authorized")))
    authority._baseline_executor=SimpleNamespace(execute=Mock(side_effect=AssertionError("No baseline execution is authorized")))
    authority._scope_reviews=None
    return authority


def assert_unavailable(authority,review,sql,mode=ExecutionMode.FULL,**case_changes):
    values=dict(id="unit-reference-contract",set=CaseSet.REGRESSIONS,persona="hr_1",as_of_date=date(2026,10,12),
                expected_outcome=ExpectedOutcome.MATCH_REFERENCE,question="TEST-ONLY reference binding question",reference_sql=sql)
    values.update(case_changes)
    case=Case(**values)
    authority._lookup=lambda *_:review
    result=authority.evaluate(case,mode)
    assert not result.available and result.table is None and not result.proves_legitimate
    authority.source.connection.assert_not_called()
    authority.admin_source.connection.assert_not_called()
    authority._baseline_executor.execute.assert_not_called()
    return result


@pytest.mark.parametrize("change", (
    {"case_id":"another-case"},{"mode":ExecutionMode.NO_VALIDATOR},{"persona":"sales_manager"},
    {"principal_id":48},{"as_of_date":date(2026,10,13)}, {"template_sha256":"0"*64},
))
def test_r06_reference_context_mismatches_fail_before_sources(unavailable_authority,change):
    sql="SELECT employee_id FROM employees WHERE manager_id = {{principal}}"
    result=assert_unavailable(unavailable_authority,unit_review(sql,**change),sql)
    assert result.diagnostics


@pytest.mark.parametrize("persona,scope", (("hr_1",RowScopeKind.ASSIGNED_DIVISIONS),("sales_manager",RowScopeKind.DIRECT_REPORTS)))
@pytest.mark.parametrize("mode", (ExecutionMode.FULL,ExecutionMode.NO_VALIDATOR,ExecutionMode.NO_PROMPT_FILTER))
def test_r06_global_admin_reference_for_restricted_persona_is_unavailable(unavailable_authority,unit_personas,persona,scope,mode):
    sql="SELECT employee_id FROM employees WHERE manager_id = {{principal}}"
    review=unit_review(sql,persona=persona,principal_id=unit_personas[persona].principal_id,mode=mode,row_scope=RowScopeKind.ALL)
    result=assert_unavailable(unavailable_authority,review,sql,mode,persona=persona)
    assert "row scope" in result.diagnostics[0].internal_detail


@pytest.mark.parametrize("marker", (None,"{{other}}"))
def test_r06_scoped_reference_requires_exact_principal_slot(unavailable_authority,marker):
    sql="SELECT employee_id FROM employees" + (" WHERE manager_id = {{other}}" if marker else "")
    review=unit_review(sql,principal_marker=marker)
    result=assert_unavailable(unavailable_authority,review,sql)
    assert "principal" in result.diagnostics[0].internal_detail


@pytest.mark.parametrize("sql", (
    "SELECT employee_id FROM employees WHERE manager_id = {{principal}}",
    "SELECT employee_id FROM employees -- {{principal}}\n",
    "SELECT employee_id FROM employees WHERE '{{principal}}' <> ''",
    "SELECT employee_id FROM employees WHERE {{principal}} = 47",
))
def test_r06_marker_and_self_declared_review_never_authorize_admin_query(unavailable_authority,sql):
    result=assert_unavailable(unavailable_authority,unit_review(sql),sql)
    assert "scope evidence" in result.diagnostics[0].internal_detail


@pytest.mark.parametrize("sql,tables", (
    ("SELECT employee_id FROM employees",("departments",)),
    ("SELECT base_salary FROM employee_compensation",("employees",)),
    ("SELECT employee_id FROM employees UNION SELECT employee_id FROM employee_compensation",("employees",)),
))
def test_r06_undeclared_physical_reads_cannot_hide_behind_lineage(unavailable_authority,sql,tables):
    review=unit_review(sql,principal_marker=None,data_tables=tables,data_columns=())
    assert_unavailable(unavailable_authority,review,sql)


@pytest.mark.parametrize("persona", ("hr_1","sales_manager"))
def test_r06_forbidden_declared_table_never_opens_admin_source(unavailable_authority,unit_personas,persona):
    sql="SELECT base_salary FROM employee_compensation"
    review=unit_review(sql,persona=persona,principal_id=unit_personas[persona].principal_id,principal_marker=None,
                      data_tables=("employee_compensation",),data_columns=(ColumnRef("employee_compensation","base_salary"),))
    assert_unavailable(unavailable_authority,review,sql,persona=persona)


@pytest.mark.parametrize("persona,table,expected", (
    ("payroll","employees",RowScopeKind.ALL),("hr_1","employees",RowScopeKind.ASSIGNED_DIVISIONS),
    ("sales_manager","employees",RowScopeKind.DIRECT_REPORTS),("hr_1","leave_balances",RowScopeKind.VIA_EMPLOYEES),
    ("payroll","leave_balances",RowScopeKind.ALL),
))
def test_r06_actual_referenced_table_supplies_its_scope(matrix,unit_personas,persona,table,expected):
    tables=physical_reference_tables(f"SELECT COUNT(*) FROM {table}",matrix)
    assert reference_row_scope(tables,matrix,unit_personas[persona],ExecutionMode.FULL) is expected


@pytest.mark.parametrize("persona", ("payroll","hr_1","sales_manager"))
@pytest.mark.parametrize("sql", (
    "SELECT department_id FROM departments", "SELECT department_id AS employees FROM departments",
    "SELECT 'employees leave_balances' AS note FROM departments -- leave_balances\n",
    "WITH employees AS (SELECT department_id FROM departments) SELECT department_id FROM employees",
    'SELECT department_id FROM public."departments" AS leave_balances',
))
def test_r06_names_comments_literals_and_ctes_cannot_impersonate_physical_tables(matrix,unit_personas,persona,sql):
    tables=physical_reference_tables(sql,matrix)
    assert tables == ("departments",)
    assert reference_row_scope(tables,matrix,unit_personas[persona],ExecutionMode.FULL) is RowScopeKind.ALL


@pytest.mark.parametrize("sql", (
    "SELECT e.employee_id FROM employees e JOIN departments d ON d.department_id=e.department_id",
    "WITH selected AS (SELECT employee_id FROM employees) SELECT employee_id FROM selected",
    "SELECT employee_id FROM employees WHERE EXISTS(SELECT 1 FROM departments)",
    "SELECT employee_id FROM employees UNION SELECT department_id FROM departments",
))
@pytest.mark.parametrize("persona,expected", (("hr_1",RowScopeKind.ASSIGNED_DIVISIONS),("sales_manager",RowScopeKind.DIRECT_REPORTS)))
def test_r06_restricted_join_cte_subquery_and_union_cannot_claim_all(matrix,unit_personas,persona,expected,sql):
    tables=physical_reference_tables(sql,matrix)
    assert reference_row_scope(tables,matrix,unit_personas[persona],ExecutionMode.FULL) is expected
    assert reference_row_scope(tables,matrix,unit_personas[persona],ExecutionMode.UNCONTROLLED) is RowScopeKind.ALL


def test_r06_leave_join_uses_known_visible_employee_policy_chain(matrix,hr_persona):
    tables=physical_reference_tables("SELECT b.employee_id FROM leave_balances b JOIN employees e ON b.employee_id=e.employee_id",matrix)
    assert reference_row_scope(tables,matrix,hr_persona,ExecutionMode.FULL) is RowScopeKind.VIA_EMPLOYEES


@pytest.mark.parametrize("sql", (
    "SELECT * FROM absent_table", "SELECT * FROM private.employees", "SELECT * FROM pg_catalog.pg_roles",
    "SELECT * FROM generate_series(1,2)", "SELECT employee_id", "SELECT 1; SELECT 2",
    "SELECT * FROM employees e JOIN departments e ON TRUE", "SELECT 1 FROM employees FOR UPDATE",
    "WITH gone AS (DELETE FROM employees RETURNING employee_id) SELECT * FROM gone",
    "WITH RECURSIVE selected AS (SELECT 1 UNION ALL SELECT 1 FROM selected) SELECT * FROM selected",
))
def test_r06_unknown_unbound_or_ambiguous_relations_fail_closed(matrix,sql):
    with pytest.raises(MissingDependencyError): physical_reference_tables(sql,matrix)


def test_r06_unknown_forbidden_and_conflicting_scope_metadata_fails_closed(matrix,hr_persona):
    from stark_t2sql.policy.loader import TableAccess

    for tables in (("absent_table",),("employee_compensation",)):
        with pytest.raises(MissingDependencyError): reference_row_scope(tables,matrix,hr_persona,ExecutionMode.FULL)
    role=matrix.role("app_hr_bp")
    changed=replace(role,tables={**role.tables,"leave_balances":TableAccess(None,RowScopeKind.DIRECT_REPORTS)})
    conflicting=replace(matrix,roles=tuple(changed if value.name==role.name else value for value in matrix.roles))
    with pytest.raises(MissingDependencyError):
        reference_row_scope(("employees","leave_balances"),conflicting,hr_persona,ExecutionMode.FULL)


@pytest.mark.parametrize("sql,expected", (
    ("SELECT employee_id FROM employees",{ColumnRef("employees","employee_id")}),
    ("SELECT e.employee_id FROM employees e WHERE e.employee_number='unit'",{ColumnRef("employees","employee_id"),ColumnRef("employees","employee_number")}),
    ("SELECT COUNT(*) FROM employees",set()),
    ("WITH selected AS (SELECT employee_id FROM employees) SELECT employee_id FROM selected",{ColumnRef("employees","employee_id")}),
    ("SELECT e.employee_id FROM employees e JOIN departments d ON e.department_id=d.department_id",{
        ColumnRef("employees","employee_id"),ColumnRef("employees","department_id"),ColumnRef("departments","department_id")}),
))
def test_r06_column_lineage_resolves_filters_joins_ctes_and_count(matrix,schema_metadata,sql,expected):
    assert _reference_columns(sql,matrix,schema_metadata) == expected


def test_r06_star_lineage_expands_every_actual_column(matrix,schema_metadata):
    assert _reference_columns("SELECT * FROM employees",matrix,schema_metadata) == {
        ColumnRef("employees",column) for column in schema_metadata.columns_by_table["employees"]}


@pytest.mark.parametrize("sql", ("SELECT nonexistent FROM employees", "SELECT employee_id FROM employees e JOIN leave_balances b ON TRUE"))
def test_r06_unknown_or_ambiguous_column_lineage_is_not_guessed(matrix,schema_metadata,sql):
    with pytest.raises(MissingDependencyError): _reference_columns(sql,matrix,schema_metadata)


def test_r06_test_only_scope_record_cannot_be_production_authorization(tmp_path,matrix):
    from hashlib import sha256

    payload=json.dumps({"kind":"TEST_ONLY", "review_binding_sha256":unit_review().binding_sha256,
        "matrix_sha256":matrix.sha256,"reviewer":"TEST-ONLY","scope_analysis":"No human review or RLS evidence"}).encode()
    (tmp_path / "TEST_ONLY.json").write_bytes(payload)
    store=ScopeReviewStore(tmp_path,frozenset({sha256(payload).hexdigest()}))
    with pytest.raises(MissingDependencyError): store.require(unit_review(),matrix)


def test_r06_scope_record_requires_independent_digest_not_self_declared_string(tmp_path,matrix):
    (tmp_path / "TEST_ONLY.json").write_text("TEST-ONLY unapproved record",encoding="utf-8")
    with pytest.raises(MissingDependencyError): ScopeReviewStore(tmp_path,frozenset())
    store=ScopeReviewStore(tmp_path,frozenset({UNIT_DIGEST}))
    with pytest.raises(MissingDependencyError): store.require(unit_review(),matrix)
    with pytest.raises(MissingDependencyError): store.require(replace(unit_review(),scope_review_reference="../outside.json"),matrix)


def test_r06_unit_review_is_immutable_but_does_not_supply_authorization(unavailable_authority):
    review=unit_review()
    with pytest.raises(FrozenInstanceError): review.principal_id=48
    assert review.binding_sha256 != replace(review,principal_id=48).binding_sha256
    assert review.binding_sha256 != replace(review,data_columns=()).binding_sha256
    assert_unavailable(unavailable_authority,review,"SELECT employee_id FROM employees WHERE manager_id = {{principal}}")


def test_r06_departments_only_reference_cannot_borrow_employee_scope(unavailable_authority):
    sql="SELECT department_id FROM departments"
    review=unit_review(sql,principal_marker=None,data_tables=("departments",),data_columns=(ColumnRef("departments","department_id"),))
    result=assert_unavailable(unavailable_authority,review,sql)
    assert "row scope" in result.diagnostics[0].internal_detail


def test_r06_departments_only_conditional_reference_requires_all_scope(mocked_reference_protocol):
    authority,state=mocked_reference_protocol
    sql="SELECT department_id FROM departments"
    state.projection=("department_id",)
    review=unit_review(sql,principal_marker=None,row_scope=RowScopeKind.ALL,data_tables=("departments",),
        data_columns=(ColumnRef("departments","department_id"),),
        projection=(ColumnMetadata("department_id",canonical_identity="department.id"),))
    result=protocol_evaluate(authority,review,sql)
    assert result.available and result.table.columns == review.projection


def test_r06_leave_reference_requires_principal_before_scope_authorization(unavailable_authority):
    sql="SELECT employee_id FROM leave_balances"
    review=unit_review(sql,principal_marker=None,row_scope=RowScopeKind.VIA_EMPLOYEES,
        data_tables=("leave_balances",),data_columns=(ColumnRef("leave_balances","employee_id"),))
    result=assert_unavailable(unavailable_authority,review,sql)
    assert "principal" in result.diagnostics[0].internal_detail


@pytest.mark.parametrize("column", ("employee_number","base_salary"))
def test_r06_forbidden_physical_columns_cannot_hide_in_reviewed_lineage(matrix,schema_metadata,hr_persona,column):
    table="employees" if column=="employee_number" else "employee_compensation"
    sql=f"SELECT {column} FROM {table}"
    review=unit_review(sql,data_tables=(table,),data_columns=(ColumnRef(table,column),),principal_marker=None)
    with pytest.raises(MissingDependencyError):
        _require_reference_lineage(sql,review,matrix,schema_metadata,hr_persona)


def test_r06_filter_reads_and_stars_cannot_omit_forbidden_column_lineage(matrix,schema_metadata,hr_persona):
    for sql in ("SELECT employee_id FROM employees WHERE employee_number='unit'","SELECT * FROM employees"):
        review=unit_review(sql,data_columns=(ColumnRef("employees","employee_id"),),principal_marker=None)
        with pytest.raises(MissingDependencyError):
            _require_reference_lineage(sql,review,matrix,schema_metadata,hr_persona)


@pytest.fixture
def mocked_reference_protocol(monkeypatch,tmp_path,matrix,schema_metadata,unit_personas,parser_approval):
    """Bypass ONLY in an explicit test: no scope record is approved or invented.

    Store authorization, fixture/policy reads, clock lint and DB I/O are stubs.
    The real safety reviewer and lineage analyzer run. A successful result here
    proves conditional Python orchestration, not genuine persona/RLS scope.
    """
    from contextlib import contextmanager
    from unittest.mock import Mock
    import stark_t2sql.evaluation.reference as module
    from stark_t2sql.security.validator import HarnessSafetyReviewer

    state=SimpleNamespace(sql=[],leases=[],scope_checks=[],rows=((1,),),projection=("employee_id",),policy=UNIT_DIGEST,fixture=UNIT_DIGEST)
    cursor=SimpleNamespace(description=None)
    def execute(sql,params=None):
        state.sql.append((sql,params))
        cursor.description=tuple(SimpleNamespace(name=name) for name in state.projection)
    cursor.execute=execute
    cursor.fetchone=lambda:("unit_source",True,False)
    cursor.fetchmany=lambda cap:list(state.rows)[:cap]
    @contextmanager
    def get_cursor(): yield cursor
    connection=SimpleNamespace(cursor=get_cursor)
    @contextmanager
    def admin_lease(**kwargs):
        state.leases.append(("admin",kwargs)); yield connection
    @contextmanager
    def persona_lease(**kwargs):
        state.leases.append(("persona",kwargs)); yield None
    @contextmanager
    def deadline(*args): yield SimpleNamespace(require_time=lambda:None)
    authority=object.__new__(ReferenceAuthority)
    authority.source=SimpleNamespace(
        matrix=matrix,personas=SimpleNamespace(resolve=lambda key:unit_personas[key],fixture_dump_sha256=UNIT_DIGEST),
        connection=persona_lease,provenance=SimpleNamespace(source_database="unit_source",clone_token="TEST-ONLY clone",manifest_hash_path=tmp_path / "unused"),
        config=SimpleNamespace(paths=object(),limits=SimpleNamespace(statement_timeout_seconds=1,output_row_cap=1000),
            resource_budgets=SimpleNamespace(require_database_budget_inputs=Mock(),database_work_mem_kib=1024,database_temp_file_limit_kib=2048)),
    )
    authority.admin_source=SimpleNamespace(connection=admin_lease)
    authority._baseline_executor=SimpleNamespace(_reviewer=HarnessSafetyReviewer(matrix,approval=parser_approval),execute=Mock())
    authority._wallclock_review=None
    authority._scope_reviews=ScopeReviewStore(tmp_path,frozenset({UNIT_DIGEST}))
    monkeypatch.setattr(ScopeReviewStore,"require",lambda self,review,policy:state.scope_checks.append((review,policy)))
    monkeypatch.setattr(module,"fixture_digest",lambda *args:state.fixture)
    monkeypatch.setattr(module,"policy_state_sha256",lambda *args:state.policy)
    monkeypatch.setattr(module,"snapshot_schema",lambda *args:schema_metadata)
    monkeypatch.setattr(module,"lint_wallclock",lambda *args,**kwargs:SimpleNamespace(available=True,uses_wallclock=False))
    monkeypatch.setattr(module,"_ReferenceDeadline",deadline)
    return authority,state


def protocol_evaluate(authority,review,sql,mode=ExecutionMode.FULL):
    authority._lookup=lambda *_:review
    case=Case(review.case_id,CaseSet.REGRESSIONS,review.persona,review.as_of_date,ExpectedOutcome.MATCH_REFERENCE,
        question="TEST-ONLY conditional protocol",reference_sql=sql)
    return authority.evaluate(case,mode)


@pytest.mark.parametrize("persona,scope", (("payroll",RowScopeKind.ALL),("hr_1",RowScopeKind.ASSIGNED_DIVISIONS),("sales_manager",RowScopeKind.DIRECT_REPORTS)))
@pytest.mark.parametrize("mode",(ExecutionMode.FULL,ExecutionMode.NO_VALIDATOR,ExecutionMode.NO_PROMPT_FILTER))
def test_r06_conditional_reference_protocol_retains_persona_and_bindings(mocked_reference_protocol,unit_personas,persona,scope,mode):
    authority,state=mocked_reference_protocol
    sql="SELECT employee_id FROM employees WHERE manager_id = {{principal}}"
    review=unit_review(sql,mode=mode,persona=persona,principal_id=unit_personas[persona].principal_id,row_scope=scope)
    result=protocol_evaluate(authority,review,sql,mode)
    assert result.available, result.diagnostics
    assert result.table.rows == ((1,),)  # Mock operand only, not a fixture answer.
    assert state.scope_checks and state.leases[0] == ("persona",{"persona":unit_personas[persona]})
    assert state.leases[1] == ("admin",{"readonly":True})
    assert result.table.sql_sha256 == sha256_context(state.sql[-1][0])
    assert result.table.columns == review.projection


@pytest.mark.parametrize("bad_input",("fixture","policy","projection","columns","truncated"))
def test_r06_reference_protocol_rejects_provenance_projection_and_incomplete_results(mocked_reference_protocol,bad_input):
    authority,state=mocked_reference_protocol
    sql="SELECT employee_id FROM employees WHERE manager_id = {{principal}}"
    review=unit_review(sql)
    if bad_input=="fixture": state.fixture="0"*64
    elif bad_input=="policy": state.policy="0"*64
    elif bad_input=="projection": state.projection=("wrong_alias",)
    elif bad_input=="columns": review=replace(review,data_columns=(ColumnRef("employees","employee_id"),))
    else: state.rows=tuple((1,) for _ in range(1001))
    result=protocol_evaluate(authority,review,sql)
    assert not result.available and result.table is None and not result.proves_legitimate
    if bad_input in {"fixture","policy","columns"}:
        assert not any("FROM employees WHERE" in text for text,_ in state.sql)


def test_r06_uncontrolled_reference_retains_existing_baseline_executor(mocked_reference_protocol,unit_personas):
    authority,state=mocked_reference_protocol
    sql="SELECT employee_id FROM employees"
    review=unit_review(sql,mode=ExecutionMode.UNCONTROLLED,row_scope=RowScopeKind.ALL,principal_marker=None,data_columns=(ColumnRef("employees","employee_id"),))
    authority._baseline_executor.execute.return_value=SimpleNamespace(status=OutcomeStatus.ANSWERED,
        executed_sql=sql,truncated=False,columns=(ColumnMetadata("employee_id"),),rows=((1,),))
    result=protocol_evaluate(authority,review,sql,ExecutionMode.UNCONTROLLED)
    assert result.available
    authority._baseline_executor.execute.assert_called_once_with(unit_personas["hr_1"],sql,mode=ExecutionMode.UNCONTROLLED)
    assert not state.leases and not state.scope_checks


def test_r06_relation_parser_version_drift_is_unavailable(monkeypatch,matrix):
    import sqlglot

    monkeypatch.setattr(sqlglot,"__version__","unreviewed-release")
    with pytest.raises(MissingDependencyError): physical_reference_tables("SELECT department_id FROM departments",matrix)


@pytest.mark.parametrize("change", (
    {"case_id":"other-case"},{"mode":ExecutionMode.NO_VALIDATOR},{"persona":"payroll"},{"principal_id":48},
    {"as_of_date":date(2026,10,13)},{"template_sha256":"0"*64},{"fixture_dump_sha256":"0"*64},
    {"source_policy_state_sha256":"0"*64},{"row_scope":RowScopeKind.ALL},{"data_columns":()},
    {"projection":(ColumnMetadata("changed",canonical_identity="another.meaning"),)},
    {"review_reference":"TEST-ONLY changed metadata"},{"scope_review_reference":"another-unit-file.json"},
    {"principal_marker":None},{"as_of_marker":"{{business_date}}"},
))
def test_r06_scope_evidence_binding_covers_every_security_context(change):
    review=unit_review()
    assert review.binding_sha256 != replace(review,**change).binding_sha256
