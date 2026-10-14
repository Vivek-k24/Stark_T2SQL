"""Case-builder contracts without actual canaries, fixture records or results."""
from datetime import date
import json

import pytest

from benchmarks.adversarial_sql.spec import SafetyDisposition,build_prepared_cases,materialize_case
from benchmarks.adversarial_sql.spec import ScopeInputs
from benchmarks.adversarial_sql.spec import materialize_safety_stop_case
from stark_t2sql.contracts import ExpectedOutcome
from stark_t2sql.evaluation.cases import CaseSet
from benchmarks.adversarial_nl.spec import prepare_nl_cases
from benchmarks.authorization.spec import build_probes
from .conftest import required_input


def test_s1_through_s8_preparation_has_no_execution_or_fabricated_s9_scope():
    prepared=build_prepared_cases()
    assert {item.family for item in prepared} == {f"S{number}" for number in range(1,9)}
    for case in prepared:
        if case.family in {"S1","S2","S5","S6","S8"}:
            assert not case.executable
    assert not any(case.family == "S9" for case in prepared)  # Actual scope selector is pending.


def test_hazardous_direct_sql_cannot_be_materialized_as_executable_case():
    hazard=next(item for item in build_prepared_cases() if item.safety is SafetyDisposition.NEVER_EXECUTE_STATEMENT)
    with pytest.raises(ValueError):
        materialize_case(hazard,case_id="unit-preparation",persona="hr_1",as_of_date=date(2026,10,12),
            forbidden_values=(),fixture_dump_sha256=None)


@pytest.mark.parametrize("safety", (
    SafetyDisposition.NEVER_EXECUTE_STATEMENT,SafetyDisposition.NEVER_EXECUTE_FUNCTION,SafetyDisposition.NEVER_EXECUTE_RESOURCE))
def test_safety_stop_materializer_needs_no_reference_or_actual_canary_values(safety):
    prepared=next(item for item in build_prepared_cases() if item.safety is safety)
    case=materialize_safety_stop_case(prepared,case_id="unit-prepared-safety-stop",persona="payroll",as_of_date=date(2026,10,12))
    assert case.set is CaseSet.ADVERSARIAL_SQL and case.expected_outcome is ExpectedOutcome.BLOCKED_ANY
    assert case.sql == prepared.sql and case.reference_sql is None
    assert case.forbidden_values == () and case.forbidden_values_fixture_sha256 is None
    assert not case.requires_forbidden_values
    assert any("never_execute_case_ids" in note for note in case.notes)


def test_safety_stop_materializer_rejects_read_attempts_requiring_actual_review_gate():
    prepared=next(item for item in build_prepared_cases() if item.safety is SafetyDisposition.REVIEWED_GATE_REQUIRED)
    with pytest.raises(ValueError):
        materialize_safety_stop_case(prepared,case_id="unit-prepared-read",persona="payroll",as_of_date=date(2026,10,12))


def test_read_attempt_requires_actual_canaries_before_materialization():
    read=next(item for item in build_prepared_cases() if item.executable)
    with pytest.raises(ValueError):
        materialize_case(read,case_id="unit-preparation",persona="hr_1",as_of_date=date(2026,10,12),
            forbidden_values=(),fixture_dump_sha256=None)


def test_n1_through_n7_are_prepared_prompt_source_only():
    prepared=prepare_nl_cases()
    assert {item.family for item in prepared} == {f"N{number}" for number in range(1,8)}
    assert all(item.question and item.requires_actual_canaries for item in prepared)


def test_s9_requires_actual_external_scope_selector(project_root):
    raw=json.loads(required_input("STARK_TEST_ADVERSARIAL_SCOPE_PATH",project_root).read_text(encoding="utf-8"))
    scope=ScopeInputs(**raw)
    prepared=build_prepared_cases(scope)
    assert {item.family for item in prepared} == {f"S{number}" for number in range(1,10)}
    assert all(item.reference_sql and item.requires_actual_canaries for item in prepared if item.family == "S9")


def test_authorization_probe_metadata_covers_every_role_column_and_star(matrix,schema_metadata):
    probes=build_probes(matrix,schema_metadata)
    assert len(probes) == len(matrix.roles)*sum(len(table.columns)+1 for table in schema_metadata.tables)
    assert all(item.sql.endswith("LIMIT 0;") and not item.observes_rows for item in probes)
    sales_star=next(item for item in probes if item.business_role=="app_sales_mgr" and item.table=="employees" and item.column is None)
    hr_number=next(item for item in probes if item.business_role=="app_hr_bp" and item.table=="employees" and item.column=="employee_number")
    assert not sales_star.expected_access and not hr_number.expected_access
