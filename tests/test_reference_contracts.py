"""Reference/probe contract source with no real approval or database operation.

Pure render mocks describe unit protocol strings only; their digests do not
stand in for a dump, fixture, policy installation or human reference review.
The actual-review immutability case requires the later owner's input. No model
SQL, admin fallback, scope reference or approved SELECT is invented here.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError,fields,MISSING
from datetime import date
import json
import sys
from types import SimpleNamespace

import pytest

from stark_t2sql.contracts import ColumnMetadata,ExecutionMode,ExpectedOutcome,RowScopeKind
from stark_t2sql.db.catalog import ColumnDefinition,SchemaSnapshot,TableDefinition
from stark_t2sql.errors import ConfigurationError,MissingDependencyError
from stark_t2sql.evaluation.cases import Case,CaseSet
from stark_t2sql.evaluation.reference import AuthorizationObserver,ReferenceAuthority,ReferenceReview,_render_reference
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
