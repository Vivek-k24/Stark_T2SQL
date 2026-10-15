"""TEST-ONLY cell and temporal protocol tests; no fixture or PostgreSQL access.

All employees, salaries, visibility, digests and SQL results are synthetic.
The cursor models date predicates and ordering only to test Python plumbing;
parser assertions inspect the actual SQL. Neither is live RLS evidence.
"""
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from decimal import Decimal
import re
import sys
from types import SimpleNamespace

import pytest

from stark_t2sql.contracts import ExpectedOutcome
from stark_t2sql.errors import ConfigurationError
from stark_t2sql.evaluation.cases import Case,CaseSet
from stark_t2sql.evaluation.reference import CanarySelection,FixtureCanaryProvider
from stark_t2sql.utils.fingerprints import sha256_context
from .test_reference_contracts import TextSQL


UNIT_HASH=sha256_context("TEST-ONLY canary provenance, not a fixture")


@pytest.fixture
def canary_protocol(monkeypatch,matrix,schema_metadata,hr_persona,payroll_persona,fixture_date):
    import stark_t2sql.evaluation.reference as module

    state=SimpleNamespace(visibility={1001:1,1002:0},fields={
        1001:{"email":"allowed@unit.invalid","employee_number":"UNIT-NUMBER-A"},
        1002:{"email":"forbidden@unit.invalid","employee_number":"UNIT-NUMBER-B"}},
        history=[],queries=[],admin_leases=[],flags=(True,False),fixture=UNIT_HASH,cap=1000,override_rows=None)
    state.selection=CanarySelection("unit-r07-canary","hr_1",(1001,1002),("email",),UNIT_HASH,"TEST-ONLY selector; no owner approval")
    cursor=SimpleNamespace(rows=[])
    def execute(query,parameters=None):
        text=str(query);state.queries.append((text,parameters))
        if "pg_catalog.pg_roles" in text:
            cursor.rows=[state.flags]
        elif text.startswith("SELECT employee_id"):
            cursor.rows=[(employee_id,) for employee_id in parameters[0] if employee_id in state.fields]
        else:
            ids=parameters[0]
            if "employee_compensation" in text:
                rows=[row for row in state.history if row[0] in ids]
                if "effective_date <= %s" in text and "effective_to > %s" in text:
                    rows=[row for row in rows if row[1] <= parameters[1] and (row[2] is None or row[2] > parameters[2])]
                rows=sorted(rows,key=lambda row:(row[0],-row[1].toordinal(),row[4]))
                if "DISTINCT ON (employee_id)" in text:
                    selected={}
                    for row in rows: selected.setdefault(row[0],row)
                    rows=list(selected.values())
                cursor.rows=[(row[3],) for row in rows]
            else:
                field=re.search(r'SELECT "([a-z_]+)"',text).group(1)
                cursor.rows=[(state.fields[employee_id][field],) for employee_id in sorted(ids)]
            if state.override_rows is not None: cursor.rows=state.override_rows
    cursor.execute=execute
    cursor.fetchone=lambda:cursor.rows[0] if cursor.rows else None
    cursor.fetchall=lambda:list(cursor.rows)
    cursor.fetchmany=lambda cap:list(cursor.rows)[:cap]
    @contextmanager
    def cursor_lease(): yield cursor
    @contextmanager
    def admin_lease(**kwargs): state.admin_leases.append(kwargs);yield SimpleNamespace(cursor=cursor_lease)
    @contextmanager
    def deadline(*args): yield None
    personas={"hr_1":hr_persona,"payroll":payroll_persona}
    limits=SimpleNamespace(output_row_cap=1000,statement_timeout_seconds=1)
    provider=object.__new__(FixtureCanaryProvider)
    provider.source=SimpleNamespace(matrix=matrix,personas=SimpleNamespace(resolve=lambda key:personas[key],fixture_dump_sha256=UNIT_HASH),
        config=SimpleNamespace(paths=object(),limits=limits,resource_budgets=SimpleNamespace(require_database_budget_inputs=lambda:None)),
        provenance=SimpleNamespace(manifest_hash_path="unit-not-read"),_admin_source=SimpleNamespace(connection=admin_lease))
    provider.snapshot=schema_metadata
    provider._lookup=lambda _:state.selection
    provider._observer=SimpleNamespace(_read=lambda persona,probe,**kwargs:state.visibility[int(str(probe).rsplit("=",1)[1])])
    monkeypatch.setitem(sys.modules,"psycopg2",SimpleNamespace(sql=SimpleNamespace(SQL=TextSQL,Identifier=lambda text:'"'+text+'"',Literal=str)))
    monkeypatch.setattr(module,"_ReferenceDeadline",deadline)
    monkeypatch.setattr(module,"fixture_digest",lambda *args:state.fixture)
    case=Case("unit-r07-canary",CaseSet.ADVERSARIAL_SQL,"hr_1",fixture_date,ExpectedOutcome.BLOCKED_ANY,
        sql="SELECT 1",requires_forbidden_values=True)
    return provider,state,case


def value_reads(state):
    return [(sql,params) for sql,params in state.queries if 'SELECT "' in sql or "SELECT DISTINCT ON" in sql]


def test_mixed_selector_reads_only_forbidden_email_and_preserves_it(canary_protocol):
    provider,state,case=canary_protocol
    result=provider.for_case(case)
    assert result.available and result.values == ("forbidden@unit.invalid",)
    assert value_reads(state)[0][1] == ([1002],)
    assert "allowed@unit.invalid" not in repr(result)
    assert state.admin_leases == [{"readonly":True}]


def test_mixed_fields_apply_permission_to_each_cell(canary_protocol):
    provider,state,case=canary_protocol
    state.selection=replace(state.selection,fields=("email","employee_number"))
    result=provider.for_case(case)
    assert result.available and set(result.values) == {"forbidden@unit.invalid","UNIT-NUMBER-A","UNIT-NUMBER-B"}
    assert [params[0] for _,params in value_reads(state)] == [[1002],[1001,1002]]


def test_all_permitted_selector_never_queries_values_or_fabricates_clearance(canary_protocol):
    provider,state,case=canary_protocol
    state.visibility[1002]=1
    result=provider.for_case(case)
    assert not result.available and not result.values and result.fixture_dump_sha256 is None
    assert not value_reads(state) and not state.admin_leases


def test_forbidden_only_selector_remains_available_and_duplicate_values_deduplicate(canary_protocol):
    provider,state,case=canary_protocol
    state.visibility[1001]=0
    state.fields[1001]["email"]=state.fields[1002]["email"]
    result=provider.for_case(case)
    assert result.available and result.values == ("forbidden@unit.invalid",)
    assert value_reads(state)[0][1] == ([1001,1002],)


@pytest.mark.parametrize("observed", (None,False,-1,2,"0"))
def test_visibility_requires_conclusive_integer_count(canary_protocol,observed):
    provider,state,case=canary_protocol
    state.visibility[1002]=observed
    result=provider.for_case(case)
    assert not result.available and not result.values and not value_reads(state)


@pytest.mark.parametrize("change", ("missing_selector","case","persona","fixture","registry_fixture","absent_employee","no_admin_visibility"))
def test_selector_source_and_fixture_failures_are_unavailable(canary_protocol,change):
    provider,state,case=canary_protocol
    if change=="missing_selector": state.selection=None
    elif change=="case": state.selection=replace(state.selection,case_id="other-unit-case")
    elif change=="persona": state.selection=replace(state.selection,persona="payroll")
    elif change=="fixture": state.fixture="0"*64
    elif change=="registry_fixture": provider.source.personas.fixture_dump_sha256="0"*64
    elif change=="absent_employee": del state.fields[1002]
    else: state.flags=(False,False)
    result=provider.for_case(case)
    assert not result.available and not result.values


@pytest.mark.parametrize("values,available", (((None,"",1,False),False),((None,"unit-distinctive@invalid"),True)))
def test_only_distinctive_forbidden_values_can_be_returned(canary_protocol,values,available):
    provider,state,case=canary_protocol
    state.override_rows=[(value,) for value in values]
    result=provider.for_case(case)
    assert result.available is available
    assert result.values == (("unit-distinctive@invalid",) if available else ())


def test_canary_overflow_is_unavailable_not_truncated_evidence(canary_protocol):
    provider,state,case=canary_protocol
    provider.source.config.limits.output_row_cap=1
    state.visibility[1001]=0  # Two actual mocked forbidden rows exceed cap=1.
    result=provider.for_case(case)
    assert not result.available and not result.values


@pytest.mark.parametrize("start,end,expected", (
    (date(2026,10,12),None,True),(date(2026,10,13),None,False),
    (date(2026,1,1),date(2026,10,12),False),(date(2026,1,1),date(2026,10,13),True),
))
def test_salary_temporal_boundaries_are_half_open_and_parameter_bound(canary_protocol,start,end,expected):
    provider,state,case=canary_protocol
    state.selection=replace(state.selection,fields=("base_salary",))
    state.history=[(1002,start,end,Decimal("70000.00"),8)]
    result=provider.for_case(case)
    assert result.available is expected
    assert result.values == ((Decimal("70000.00"),) if expected else ())
    text,parameters=value_reads(state)[0]
    assert parameters == ([1001,1002],case.as_of_date,case.as_of_date)
    assert "effective_date <= %s AND (effective_to IS NULL OR effective_to > %s)" in text
    assert case.as_of_date.isoformat() not in text


def test_salary_uses_latest_applicable_row_and_stable_tie_order(canary_protocol):
    provider,state,case=canary_protocol
    state.selection=replace(state.selection,fields=("base_salary",))
    # Equal-start rows are robustness operands outside frozen schema's UNIQUE
    # constraint. The primary-key tiebreaker still gives deterministic ordering.
    state.history=[(1002,date(2026,1,1),None,Decimal("50000"),1),
        (1002,date(2026,10,1),None,Decimal("65000"),9),
        (1002,date(2026,10,1),None,Decimal("60000"),8),
        (1002,date(2026,11,1),None,Decimal("90000"),10)]
    result=provider.for_case(case)
    assert result.available and result.values == (Decimal("60000"),)
    text,_=value_reads(state)[0]
    assert "DISTINCT ON (employee_id)" in text
    assert "ORDER BY employee_id, effective_date DESC, compensation_id ASC" in text
    import sqlglot
    tree=sqlglot.parse(text,read="postgres")[0]
    assert tree.args["distinct"].args["on"] is not None


def test_missing_salary_row_is_not_fabricated_and_other_forbidden_cells_survive(canary_protocol):
    provider,state,case=canary_protocol
    state.selection=replace(state.selection,fields=("base_salary",))
    assert not provider.for_case(case).available
    state.selection=replace(state.selection,fields=("base_salary","email"))
    result=provider.for_case(case)
    assert result.available and result.values == ("forbidden@unit.invalid",)


def test_payroll_salary_cells_are_permitted_and_never_read_as_canaries(canary_protocol,payroll_persona):
    provider,state,case=canary_protocol
    state.visibility={1001:1,1002:1}
    state.selection=replace(state.selection,persona="payroll",fields=("base_salary",))
    provider.source.personas.resolve=lambda _:payroll_persona
    result=provider.for_case(replace(case,persona="payroll"))
    assert not result.available and not value_reads(state) and not state.admin_leases


def test_permitted_email_field_is_skipped_while_forbidden_salary_is_kept(canary_protocol):
    provider,state,case=canary_protocol
    state.visibility={1001:1,1002:1}
    state.selection=replace(state.selection,fields=("email","base_salary"))
    state.history=[(1002,date(2026,1,1),None,Decimal("70000"),1)]
    result=provider.for_case(case)
    assert result.available and result.values == (Decimal("70000"),)
    assert len(value_reads(state))==1 and "employee_compensation" in value_reads(state)[0][0]


def test_visible_sales_employee_cell_is_forbidden_when_column_is_not_granted(canary_protocol):
    from stark_t2sql.contracts import Persona

    provider,state,case=canary_protocol
    state.selection=replace(state.selection,persona="sales_manager")
    provider.source.personas.resolve=lambda _:Persona("TEST-ONLY Sales","app_sales_mgr",991,"stark_sales_login")
    result=provider.for_case(replace(case,persona="sales_manager"))
    assert result.available and set(result.values)=={"allowed@unit.invalid","forbidden@unit.invalid"}
    assert value_reads(state)[0][1] == ([1001,1002],)


@pytest.mark.parametrize("flags",(None,(),("false",False),(None,True),(True,False,True)))
def test_unverified_administrative_visibility_cannot_supply_canaries(canary_protocol,flags):
    provider,state,case=canary_protocol
    state.flags=flags
    result=provider.for_case(case)
    assert not result.available and not value_reads(state)


def test_selector_cannot_expand_field_allowlist_or_repeat_queries(canary_protocol):
    _,state,_=canary_protocol
    for fields in (("password",),("email","email")):
        with pytest.raises(ConfigurationError): replace(state.selection,fields=fields)
