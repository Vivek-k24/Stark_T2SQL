"""Hand-authored scalar/projection operands, never fixture answers or canaries."""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import pytest

from stark_t2sql.contracts import ColumnMetadata, ExpectedOutcome, OutcomeStatus, ReasonCode, StoppingLayer, Clarification
from stark_t2sql.evaluation.cases import Case, CaseSet
from stark_t2sql.evaluation.comparator import ApprovedColumnMapping, ResultTable, canonical_cell, compare_results, evaluate_expected
from stark_t2sql.utils.fingerprints import sha256_context
from .helpers import make_outcome


def table(identities, rows):
    return ResultTable(tuple(ColumnMetadata(identity, canonical_identity=identity) for identity in identities), tuple(rows))


@pytest.mark.parametrize("actual,reference,matches", (
    (table(("x",), ((2,), (1,))), table(("x",), ((1,), (2,))), True),
    (table(("money",), ((Decimal("1.005"),),)), table(("money",), ((Decimal("1.01"),),)), True),
    (table(("money",), ((1.004,),)), table(("money",), ((Decimal("1.00"),),)), True),
    (table(("money",), ((Decimal("-1.005"),),)), table(("money",), ((Decimal("-1.01"),),)), True),
    (table(("x",), ((None,),)), table(("x",), ((None,),)), True),
    (table(("x",), ((None,),)), table(("x",), ((0,),)), False),
    (table(("x",), ()), table(("x",), ()), True),
    (table(("x",), ()), table(("x",), ((1,),)), False),
    (table(("x",), ((1,), (1,))), table(("x",), ((1,),)), False),
    (table(("x",), ((1,), (1,))), table(("x",), ((1,), (1,))), True),
    (table(("a", "b"), ((1, 2),)), table(("a",), ((1,),)), False),
    (table(("b", "a"), ((2, 1),)), table(("a", "b"), ((1, 2),)), True),
    (table(("salary", "tax"), ((2, 1),)), table(("salary", "tax"), ((1, 2),)), False),
    (table(("salary",), ((1,),)), table(("tax",), ((1,),)), False),
    (table(("x",), ((True,),)), table(("x",), ((1,),)), False),
    (table(("x",), ((1,),)), table(("x",), ((Decimal("1.00"),),)), False),
    (table(("date",), ((date(2026,10,12),),)), table(("date",), ((date(2026,10,12),),)), True),
    (table(("date",), ((datetime(2026,10,12),),)), table(("date",), ((date(2026,10,12),),)), False),
))
def test_comparison_hand_authored_pairs(actual, reference, matches):
    assert compare_results(actual, reference).matches is matches


def test_matching_aliases_do_not_establish_projection_approval():
    unbound = ResultTable((ColumnMetadata("x"),), ((1,),))
    comparison = compare_results(unbound, unbound)
    assert not comparison.matches and comparison.dependency_unavailable


def test_duplicate_column_labels_require_external_slot_mapping():
    duplicate = table(("x", "x"), ((1, 2),))
    assert not compare_results(duplicate, duplicate).matches


def test_nonbijective_approval_is_rejected_without_review_invention():
    with pytest.raises(ValueError):
        ApprovedColumnMapping(("a", "b"), ("a", "b"), (0, 0), "")


def make_case(expected, *, reference_sql=None, requires_canaries=False):
    return Case("unit-expected-outcome", CaseSet.REGRESSIONS, "payroll", date(2026,10,12),
        expected, question="Unit contract question", reference_sql=reference_sql, requires_forbidden_values=requires_canaries)


@pytest.mark.parametrize("expected,status,reason,layer", (
    (ExpectedOutcome.BLOCKED_DB,OutcomeStatus.BLOCKED_DB,ReasonCode.DB_PERMISSION_DENIED,StoppingLayer.DATABASE),
    (ExpectedOutcome.BLOCKED_VALIDATOR,OutcomeStatus.BLOCKED_VALIDATOR,ReasonCode.VALIDATOR_REJECTED,StoppingLayer.VALIDATOR),
    (ExpectedOutcome.BLOCKED_ANY,OutcomeStatus.BLOCKED_DB,ReasonCode.DB_PERMISSION_DENIED,StoppingLayer.DATABASE),
))
def test_expected_blocks_are_only_observed_enforcement(expected, status, reason, layer, payroll_persona):
    outcome = make_outcome(payroll_persona, status=status, reason=reason, layer=layer)
    assert evaluate_expected(make_case(expected), outcome).passed is True


def test_clarification_executes_no_sql(payroll_persona):
    outcome = make_outcome(payroll_persona, status=OutcomeStatus.CLARIFICATION_REQUIRED,
        reason=ReasonCode.CLARIFICATION_REQUIRED,layer=StoppingLayer.CONTEXT,clarification=Clarification("Which meaning?"))
    assert evaluate_expected(make_case(ExpectedOutcome.CLARIFICATION_REQUIRED), outcome).passed is True


@pytest.mark.parametrize("expected", (ExpectedOutcome.MATCH_REFERENCE,ExpectedOutcome.CANONICAL_RESOLUTION,ExpectedOutcome.SCOPED_RESULT))
def test_empty_passes_only_against_empty_independent_reference(expected, payroll_persona):
    outcome = make_outcome(payroll_persona, columns=(ColumnMetadata("x",canonical_identity="x"),))
    case = make_case(expected, reference_sql="SELECT employee_id FROM employees WHERE false")
    assert evaluate_expected(case,outcome,reference=table(("x",),())).passed is True
    assert evaluate_expected(case,outcome,reference=table(("x",),((1,),))).passed is False


def test_missing_canaries_and_harness_safety_stop_are_unscored(payroll_persona):
    outcome = make_outcome(payroll_persona, status=OutcomeStatus.BLOCKED_DB,reason=ReasonCode.DB_PERMISSION_DENIED,layer=StoppingLayer.DATABASE)
    assessment = evaluate_expected(make_case(ExpectedOutcome.BLOCKED_DB,requires_canaries=True),outcome)
    assert assessment.passed is None and assessment.missing_canary_requirement is not None
    stop = make_outcome(payroll_persona,status=OutcomeStatus.HARNESS_SAFETY_STOP,reason=ReasonCode.HARNESS_SAFETY_STOP,layer=StoppingLayer.HARNESS)
    assert evaluate_expected(make_case(ExpectedOutcome.BLOCKED_ANY),stop).passed is None


# These are TEST-ONLY operands and mapping-contract strings. No human-approved
# production SQL/mapping, fixture answer or database result is claimed.
REFERENCE_HASH=sha256_context("TEST-ONLY reviewed reference operand")
CANDIDATE_HASH=sha256_context("TEST-ONLY executed candidate operand")


def reviewed_table(columns=("employee_id","department_id"),identities=("employee.id","department.id"),rows=((1,2),),sql_hash=REFERENCE_HASH):
    return ResultTable(tuple(ColumnMetadata(name,canonical_identity=identity) for name,identity in zip(columns,identities)),rows,sql_hash)


def raw_table(names=("employee_id","department_id"),rows=((1,2),),sql_hash=CANDIDATE_HASH):
    return ResultTable(tuple(ColumnMetadata(name) for name in names),rows,sql_hash)


@pytest.mark.parametrize("names,rows,mapping", (
    (("employee_id","department_id"),((1,2),),(0,1)),
    (("department_id","employee_id"),((2,1),),(1,0)),
    (("employee.id","department.id"),((1,2),),(0,1)),
))
def test_r06_dynamic_cursor_maps_exact_unique_labels_without_candidate_prehash(names,rows,mapping):
    actual=raw_table(names,rows,sql_hash=None)
    result=compare_results(actual,reviewed_table())
    assert result.matches and result.mapping == mapping


@pytest.mark.parametrize("candidate_sql", ("SELECT employee_id,department_id FROM employees", "SELECT employee_id,department_id FROM employees WHERE employee_id > 0"))
def test_r06_explicit_mapping_supports_dynamic_candidate_sql_with_fixed_reference_hash(candidate_sql):
    actual=raw_table(("id_value","dept_value"),sql_hash=sha256_context(candidate_sql))
    approval=ApprovedColumnMapping(("employee.id","department.id"),("id_value","dept_value"),(0,1),
        "TEST-ONLY projection contract",reference_sql_sha256=REFERENCE_HASH)
    assert approval.candidate_sql_sha256 is None
    assert compare_results(actual,reviewed_table(),approval=approval).matches


@pytest.mark.parametrize("reference_hash,approved_hash", ((None,REFERENCE_HASH),(REFERENCE_HASH,None),(REFERENCE_HASH,"0"*64)))
def test_r06_raw_projection_mapping_requires_matching_reference_sql_binding(reference_hash,approved_hash):
    approval=ApprovedColumnMapping(("employee.id","department.id"),("employee_id","department_id"),(0,1),
        "TEST-ONLY projection contract",reference_sql_sha256=approved_hash)
    assert not compare_results(raw_table(),reviewed_table(sql_hash=reference_hash),approval=approval).matches


def test_r06_automatic_cursor_mapping_requires_reference_sql_binding():
    result=compare_results(raw_table(),reviewed_table(sql_hash=None))
    assert not result.matches and result.dependency_unavailable


@pytest.mark.parametrize("actual_hash", (None,"0"*64))
def test_r06_explicit_candidate_hash_cannot_be_ignored_when_actual_hash_is_missing_or_wrong(actual_hash):
    approval=ApprovedColumnMapping(("employee.id","department.id"),("employee_id","department_id"),(0,1),
        "TEST-ONLY projection contract",candidate_sql_sha256=CANDIDATE_HASH,reference_sql_sha256=REFERENCE_HASH)
    assert not compare_results(raw_table(sql_hash=actual_hash),reviewed_table(),approval=approval).matches


@pytest.mark.parametrize("names", (("id","id"),("unknown","department_id"),("EMPLOYEE_ID","department_id"),("employee_id","employee_id")))
def test_r06_unknown_duplicate_or_case_changed_raw_aliases_do_not_guess_from_equal_values(names):
    result=compare_results(raw_table(names,((1,1),)),reviewed_table(rows=((1,1),)))
    assert not result.matches and result.dependency_unavailable


def test_r06_competing_display_and_canonical_alias_meanings_are_ambiguous():
    reference=reviewed_table(columns=("a","b"),identities=("b","a"))
    result=compare_results(raw_table(("a","b")),reference)
    assert not result.matches and result.dependency_unavailable


def test_r06_mixed_metadata_never_discards_an_explicit_different_meaning():
    actual=ResultTable((ColumnMetadata("employee_id",canonical_identity="salary.amount"),ColumnMetadata("department_id")),((1,2),))
    assert not compare_results(actual,reviewed_table()).matches


def test_r06_column_correspondence_must_remain_bijective_with_mixed_labels():
    # Both labels refer to the first reference slot; equal values cannot make
    # a missing department slot equivalent.
    actual=raw_table(("employee_id","employee.id"),((1,1),))
    assert not compare_results(actual,reviewed_table(rows=((1,1),))).matches


def test_r06_duplicate_cursor_labels_need_fixed_reviewed_sql_even_with_slot_mapping():
    actual=raw_table(("id","id"))
    dynamic=ApprovedColumnMapping(("employee.id","department.id"),("id","id"),(0,1),
        "TEST-ONLY stable-slot contract",reference_sql_sha256=REFERENCE_HASH)
    assert not compare_results(actual,reviewed_table(),approval=dynamic).matches
    fixed=ApprovedColumnMapping(("employee.id","department.id"),("id","id"),(0,1),
        "TEST-ONLY stable-slot contract",candidate_sql_sha256=CANDIDATE_HASH,reference_sql_sha256=REFERENCE_HASH)
    assert compare_results(actual,reviewed_table(),approval=fixed).matches


@pytest.mark.parametrize("reference_ids,candidate_ids,permutation,review", (
    (("a","b"),("a","b"),(0,0),"TEST-ONLY"),
    (("a","b"),("a",),(0,1),"TEST-ONLY"),
    (("a","b"),("a","b"),(0,2),"TEST-ONLY"),
    (("a","b"),("a","b"),(False,1),"TEST-ONLY"),
    (("a","b"),("a","b"),(0,1),""),
    (("a","a"),("a","b"),(0,1),"TEST-ONLY"),
    ((),(),(),"TEST-ONLY"),
    (("a",""),("a","b"),(0,1),"TEST-ONLY"),
))
def test_r06_invalid_reviewed_column_mappings_fail_closed(reference_ids,candidate_ids,permutation,review):
    with pytest.raises(ValueError): ApprovedColumnMapping(reference_ids,candidate_ids,permutation,review)


@pytest.mark.parametrize("value,expected", (
    (Decimal("1.005"),Decimal("1.01")),(Decimal("-1.005"),Decimal("-1.01")),
    (1.005,Decimal("1.01")),(-1.005,Decimal("-1.01")),
    (Decimal("0.0049"),Decimal("0.00")),(Decimal("1E+40"),Decimal("1E+40")),
))
def test_r06_rounding_uses_decimal_half_up(value,expected):
    assert canonical_cell(value) == ("decimal",expected)


@pytest.mark.parametrize("value", (float("nan"),float("inf"),float("-inf"),Decimal("NaN"),Decimal("Infinity"),Decimal("sNaN"),[],{},object()))
def test_r06_nonfinite_or_unknown_scalars_cannot_compare(value):
    result=compare_results(table(("x",),((value,),)),table(("x",),((value,),)))
    assert not result.matches


@pytest.mark.parametrize("left,right", ((None,0),(False,0),(True,1),(1,Decimal("1.00")),(date(2026,10,12),datetime(2026,10,12))))
def test_r06_scalar_kinds_are_distinct(left,right):
    assert canonical_cell(left) != canonical_cell(right)


def test_r06_datetime_keeps_its_exact_timezone_and_date_kind():
    original=datetime(2026,10,12,1,tzinfo=timezone(timedelta(hours=5)))
    assert canonical_cell(original) == ("datetime",original.isoformat())
    assert canonical_cell(original) != canonical_cell(original.astimezone(timezone.utc))


def test_r06_row_order_is_ignored_and_duplicate_multiplicity_is_preserved():
    reference=table(("x",),((1,),(2,),(1,)))
    assert compare_results(table(("x",),((2,),(1,),(1,))),reference).matches
    assert not compare_results(table(("x",),((2,),(2,),(1,))),reference).matches


@pytest.mark.parametrize("actual_rows,reference_rows,matches", (((),(),True),((),((1,),),False),(((9,),),(),False),(((9,),),((1,),),True),(((9,),(9,)),((1,),),False)))
def test_r06_scoped_result_uses_persona_reference_row_count_only(payroll_persona,actual_rows,reference_rows,matches):
    case=make_case(ExpectedOutcome.SCOPED_RESULT,reference_sql="SELECT employee_id FROM employees")
    outcome=make_outcome(payroll_persona,columns=(ColumnMetadata("x",canonical_identity="x"),),rows=actual_rows)
    assert evaluate_expected(case,outcome,reference=table(("x",),reference_rows)).passed is matches
