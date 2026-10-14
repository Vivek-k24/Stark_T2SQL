"""Hand-authored scalar/projection operands, never fixture answers or canaries."""
from datetime import date, datetime
from decimal import Decimal

import pytest

from stark_t2sql.contracts import ColumnMetadata, ExpectedOutcome, OutcomeStatus, ReasonCode, StoppingLayer, Clarification
from stark_t2sql.evaluation.cases import Case, CaseSet
from stark_t2sql.evaluation.comparator import ApprovedColumnMapping, ResultTable, compare_results, evaluate_expected
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
