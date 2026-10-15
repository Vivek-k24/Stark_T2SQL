"""Taxonomy, wall-clock, immutable split and observed-attribution test source.

In-memory observations are unit operands, never measured run records. No real
holdout contents or canaries are embedded/read by these source definitions.
"""
from dataclasses import replace
from datetime import date
import json

import pytest

from stark_t2sql.contracts import ExecutionMode, FailureClass, OutcomeStatus, ReasonCode, StoppingLayer
from stark_t2sql.evaluation.attribution import LayerObservation, accuracy_histogram, attribute_layers, changed_cases, leakage_by_mode
from stark_t2sql.evaluation.cases import CaseSet
from stark_t2sql.evaluation.comparator import CaseAssessment
from stark_t2sql.evaluation.failure_classes import ManualTriage, classify_failure
from stark_t2sql.evaluation.holdout import CasePartition, FrozenCaseIndex, FrozenCaseMetadata, HoldoutAuthority, read_tuning_payload, split_for_id
from stark_t2sql.evaluation.wallclock import WallClockReview, WallClockLintResult, WallClockViolation, lint_wallclock
from stark_t2sql.utils.fingerprints import sha256_bytes
from .conftest import required_input
from .helpers import make_outcome


@pytest.mark.parametrize("reason,sqlstate,expected", (
    (ReasonCode.SQL_EXTRACTION_FAILED,None,FailureClass.EXTRACT),
    (ReasonCode.GENERATION_TIMEOUT,None,FailureClass.TIMEOUT_GEN),
    (ReasonCode.GENERATION_TRUNCATED,None,FailureClass.TRUNCATED_GEN),
    (ReasonCode.STATEMENT_TIMEOUT,"57014",FailureClass.TIMEOUT_STMT),
    (ReasonCode.SQL_SYNTAX_ERROR,"42601",FailureClass.SYNTAX),
    (ReasonCode.UNKNOWN_DATABASE_OBJECT,"42P01",FailureClass.HALLUC),
    (ReasonCode.UNKNOWN_DATABASE_OBJECT,"42703",FailureClass.HALLUC),
    (ReasonCode.UNKNOWN_DATABASE_OBJECT,"42883",FailureClass.HALLUC),
    (ReasonCode.DB_PERMISSION_DENIED,"42501",FailureClass.POLICY),
    (ReasonCode.DATABASE_ERROR,"XX000",FailureClass.RUNTIME),
))
def test_single_automatic_failure_class(reason,sqlstate,expected,payroll_persona):
    outcome=make_outcome(payroll_persona,status=OutcomeStatus.ERROR,reason=reason,layer=StoppingLayer.DATABASE,sqlstate=sqlstate)
    result=classify_failure(outcome,CaseAssessment(False,"Unit symptom"))
    assert result.failure_class is expected


def test_observed_wallclock_takes_precedence_over_matching_result(payroll_persona):
    lint=WallClockLintResult(True,(WallClockViolation("unit-node","unit-clock-rule"),))
    result=classify_failure(make_outcome(payroll_persona),CaseAssessment(True,"Unit matching result"),wallclock=lint)
    assert result.failure_class is FailureClass.WALLCLOCK


def test_leak_indicator_has_precedence_and_no_canary_text_is_needed(payroll_persona):
    result=classify_failure(make_outcome(payroll_persona),CaseAssessment(False,"Unit leak indicator",leak_found=True))
    assert result.failure_class is FailureClass.LEAK


def test_expected_permission_block_is_not_policy_defect(payroll_persona):
    outcome=make_outcome(payroll_persona,status=OutcomeStatus.BLOCKED_DB,reason=ReasonCode.DB_PERMISSION_DENIED,layer=StoppingLayer.DATABASE,sqlstate="42501")
    assert classify_failure(outcome,CaseAssessment(True,"Expected block",block_expected=True)).failure_class is None
    wrong_layer=classify_failure(outcome,CaseAssessment(False,"Wrong expected layer",block_expected=True))
    assert wrong_layer.failure_class is None and wrong_layer.triage_pending


def test_unresolved_intent_failure_remains_pending_without_invented_triage(payroll_persona):
    result=classify_failure(make_outcome(payroll_persona),CaseAssessment(False,"Unit mismatch"))
    assert result.failure_class is None and result.triage_pending
    with pytest.raises(ValueError): ManualTriage(FailureClass.SEMANTIC,"","")


def test_reference_proven_validator_overblock_is_distinct(payroll_persona):
    outcome=make_outcome(payroll_persona,status=OutcomeStatus.BLOCKED_VALIDATOR,reason=ReasonCode.VALIDATOR_REJECTED,layer=StoppingLayer.VALIDATOR)
    assessment=CaseAssessment(False,"Unit legitimate reference",reference_proves_legitimate=True,legitimate_in_entitlement=True)
    assert classify_failure(outcome,assessment).failure_class is FailureClass.VALIDATOR
    unproved=replace(assessment,reference_proves_legitimate=False)
    assert classify_failure(outcome,unproved).failure_class is FailureClass.OVERBLOCK


@pytest.fixture
def wallclock_review(project_root):
    raw=json.loads(required_input("STARK_TEST_WALLCLOCK_REVIEW_PATH",project_root).read_text(encoding="utf-8"))
    return WallClockReview(**raw)


@pytest.mark.parametrize("sql", (
    "SELECT CURRENT_DATE","SELECT CURRENT_TIMESTAMP","SELECT CURRENT_TIME","SELECT LOCALTIMESTAMP",
    "SELECT NOW()","SELECT CAST('today' AS DATE)","SELECT 'tomorrow'::timestamp",
    "SELECT 'yesterday'::date","SELECT 'now'::timestamp","SELECT CLOCK_TIMESTAMP()",
    "SELECT TIMEOFDAY()","SELECT AGE(DATE '2026-01-01')","SELECT STATEMENT_TIMESTAMP()",
    "SELECT TRANSACTION_TIMESTAMP()","SELECT CASE WHEN true THEN CURRENT_DATE ELSE DATE '2026-10-12' END",
))
def test_wallclock_ast_lint_future_guarded_capabilities(sql,wallclock_review):
    result=lint_wallclock(sql,review=wallclock_review)
    assert result.available,result.unavailable_reason
    assert result.uses_wallclock


def test_as_of_literal_is_not_wallclock(wallclock_review):
    result=lint_wallclock("SELECT DATE '2026-10-12'",review=wallclock_review)
    assert result.available and not result.uses_wallclock


def test_missing_wallclock_profile_is_unavailable():
    assert not lint_wallclock("SELECT CURRENT_DATE").available


def unit_id(partition):
    # Find a unit ID in a desired fixed bucket at future runtime. This embeds
    # no actual assignment, initial freeze ID or holdout payload in source.
    for ordinal in range(10000):
        candidate=f"unit-split-contract-{ordinal}"
        if split_for_id(candidate) is partition: return candidate
    raise AssertionError("Expected a unit ID in each hash bucket")


def test_case_additions_never_shift_existing_bucket_assignments():
    payload=b"Opaque unit metadata bytes; no question or answer"
    digest=sha256_bytes(payload)
    old_id=unit_id(CasePartition.TUNING)
    old=FrozenCaseMetadata(old_id,split_for_id(old_id),digest)
    index=FrozenCaseIndex((old,),"In-memory unit index; not an actual benchmark freeze")
    new_id=unit_id(CasePartition.HOLDOUT)
    extended=index.extend((FrozenCaseMetadata(new_id,split_for_id(new_id),digest),),freeze_reference="In-memory unit extension")
    assert extended.by_id[old_id] == old
    assert split_for_id(old_id) is CasePartition.TUNING
    with pytest.raises(ValueError): index.extend((old,),freeze_reference="In-memory unit duplicate")


def test_holdout_guard_precedes_payload_reader():
    case_id=unit_id(CasePartition.HOLDOUT)
    metadata=FrozenCaseMetadata(case_id,CasePartition.HOLDOUT,sha256_bytes(b"Opaque unit bytes"))
    index=FrozenCaseIndex((metadata,),"In-memory unit index; no real holdout")
    calls=[]
    def forbidden_loader(entry): calls.append(entry); raise AssertionError("Holdout loader must not be called")
    with pytest.raises(PermissionError): read_tuning_payload(index,case_id,loader=forbidden_loader)
    assert calls == []


def observation(mode,*,status=OutcomeStatus.BLOCKED_VALIDATOR,layer=StoppingLayer.VALIDATOR,passed=None,leak=None,failure=None):
    return LayerObservation("unit-attribution-only",mode,status,layer,passed,leak,failure,case_set=CaseSet.ADVERSARIAL_SQL)


def test_safety_stop_cannot_be_claimed_as_database_block_or_no_leak():
    stop=observation(ExecutionMode.UNCONTROLLED,status=OutcomeStatus.HARNESS_SAFETY_STOP,layer=StoppingLayer.HARNESS)
    with pytest.raises(ValueError): replace(stop,passed=True,leak_observed=False)
    summary=next(item for item in leakage_by_mode((stop,)) if item.mode is ExecutionMode.UNCONTROLLED)
    assert summary.unknown == 1 and summary.harness_safety_stops == 1 and not summary.stopping_layers
    attribution=attribute_layers((stop,))[0]
    assert any("harness safety" in limitation for limitation in attribution.limitations)


def test_observed_counts_and_exact_changed_cases_use_only_inputs():
    old=observation(ExecutionMode.FULL,passed=False,leak=None,failure=FailureClass.VALIDATOR)
    new=replace(old,passed=True,failure_class=None)
    histogram=accuracy_histogram((old,))
    assert histogram.total == 1 and histogram.overblocking_count == 1
    changes=changed_cases((old,),(new,))
    assert len(changes) == 1 and changes[0].case_id == "unit-attribution-only"
    assert "passed" in changes[0].changes and "failure_class" in changes[0].changes


# R07 precedence operands are simulated symptoms, not actual SQLSTATE, parser
# review, human triage evidence or forbidden fixture values.
@pytest.mark.parametrize("passed",(None,True,False))
@pytest.mark.parametrize("status,reason,state",(
    (OutcomeStatus.ANSWERED,ReasonCode.ANSWERED,None),
    (OutcomeStatus.ERROR,ReasonCode.GENERATION_TIMEOUT,"57014"),
    (OutcomeStatus.BLOCKED_VALIDATOR,ReasonCode.VALIDATOR_REJECTED,"42601"),
    (OutcomeStatus.HARNESS_SAFETY_STOP,ReasonCode.HARNESS_SAFETY_STOP,None),
))
def test_r07_leak_precedes_every_other_symptom(payroll_persona,passed,status,reason,state):
    outcome=make_outcome(payroll_persona,status=status,reason=reason,layer=StoppingLayer.HARNESS,sqlstate=state)
    clock=WallClockLintResult(True,(WallClockViolation("TEST-ONLY","simulated clock"),))
    result=classify_failure(outcome,CaseAssessment(passed,"TEST-ONLY",leak_found=True),wallclock=clock)
    assert result.failure_class is FailureClass.LEAK and not result.triage_pending


@pytest.mark.parametrize("passed",(None,True,False))
def test_r07_wallclock_precedes_matches_unavailable_and_error_symptoms(payroll_persona,passed):
    outcome=make_outcome(payroll_persona,status=OutcomeStatus.ERROR,reason=ReasonCode.SQL_EXTRACTION_FAILED,sqlstate="42601")
    clock=WallClockLintResult(True,(WallClockViolation("TEST-ONLY","simulated clock"),))
    result=classify_failure(outcome,CaseAssessment(passed,"TEST-ONLY"),wallclock=clock)
    assert result.failure_class is FailureClass.WALLCLOCK and not result.triage_pending


@pytest.mark.parametrize("status,passed",((OutcomeStatus.HARNESS_SAFETY_STOP,False),(OutcomeStatus.ERROR,None),(OutcomeStatus.ANSWERED,True)))
def test_r07_unscored_safety_and_passes_do_not_get_failure_classes(payroll_persona,status,passed):
    outcome=make_outcome(payroll_persona,status=status,reason=ReasonCode.DB_PERMISSION_DENIED,layer=StoppingLayer.HARNESS,sqlstate="42501")
    result=classify_failure(outcome,CaseAssessment(passed,"TEST-ONLY"),wallclock=WallClockLintResult(False))
    assert result.failure_class is None and not result.triage_pending


@pytest.mark.parametrize("reason,states,expected",(
    (ReasonCode.SQL_EXTRACTION_FAILED,("57014","42601"),FailureClass.EXTRACT),
    (ReasonCode.GENERATION_TIMEOUT,("42601",),FailureClass.TIMEOUT_GEN),
    (ReasonCode.GENERATION_TRUNCATED,("42P01",),FailureClass.TRUNCATED_GEN),
    (ReasonCode.DATABASE_ERROR,("57014","42601","42P01"),FailureClass.SYNTAX),
    (ReasonCode.DATABASE_ERROR,("57014","42703"),FailureClass.HALLUC),
    (ReasonCode.UNKNOWN_DATABASE_OBJECT,("57014",),FailureClass.HALLUC),
    (ReasonCode.STATEMENT_TIMEOUT,("42501",),FailureClass.TIMEOUT_STMT),
))
def test_r07_automatic_symptom_precedence_over_enforcement_and_manual_triage(payroll_persona,reason,states,expected):
    from stark_t2sql.contracts import Diagnostic

    outcome=make_outcome(payroll_persona,status=OutcomeStatus.BLOCKED_VALIDATOR,reason=reason,layer=StoppingLayer.VALIDATOR)
    outcome=replace(outcome,diagnostics=tuple(Diagnostic("TEST-ONLY","simulated SQLSTATE",state) for state in states))
    assessment=CaseAssessment(False,"TEST-ONLY",reference_proves_legitimate=True,legitimate_in_entitlement=True)
    triage=ManualTriage(FailureClass.SEMANTIC,"TEST-ONLY reviewer","TEST-ONLY evidence; no real triage")
    result=classify_failure(outcome,assessment,manual_triage=triage)
    assert result.failure_class is expected and not result.triage_pending


@pytest.mark.parametrize("proof,legitimate,block_expected,expected,pending",(
    (True,True,False,FailureClass.VALIDATOR,False),
    (False,True,False,FailureClass.OVERBLOCK,False),
    (False,False,False,FailureClass.POLICY,False),
    (False,False,True,None,True),
))
def test_r07_reference_overblock_and_expected_permission_precedence(payroll_persona,proof,legitimate,block_expected,expected,pending):
    outcome=make_outcome(payroll_persona,status=OutcomeStatus.BLOCKED_VALIDATOR,reason=ReasonCode.DB_PERMISSION_DENIED,
        layer=StoppingLayer.VALIDATOR,sqlstate="42501")
    assessment=CaseAssessment(False,"TEST-ONLY",reference_proves_legitimate=proof,legitimate_in_entitlement=legitimate,block_expected=block_expected)
    result=classify_failure(outcome,assessment)
    assert result.failure_class is expected and result.triage_pending is pending


def test_r07_unrecognized_sqlstate_stays_runtime_pending_before_manual_intent(payroll_persona):
    outcome=make_outcome(payroll_persona,status=OutcomeStatus.ERROR,reason=ReasonCode.DATABASE_ERROR,sqlstate="XX999")
    triage=ManualTriage(FailureClass.SEMANTIC,"TEST-ONLY reviewer","TEST-ONLY metadata")
    result=classify_failure(outcome,CaseAssessment(False,"TEST-ONLY"),manual_triage=triage)
    assert result.failure_class is FailureClass.RUNTIME and result.triage_pending


@pytest.mark.parametrize("failure",(FailureClass.SCHEMA,FailureClass.JOIN,FailureClass.FILTER,FailureClass.AGG,FailureClass.TEMPORAL,FailureClass.SEMANTIC))
def test_r07_manual_triage_requires_typed_allowed_class_and_metadata(payroll_persona,failure):
    triage=ManualTriage(failure,"TEST-ONLY reviewer","TEST-ONLY evidence; not human approval")
    result=classify_failure(make_outcome(payroll_persona),CaseAssessment(False,"TEST-ONLY mismatch"),manual_triage=triage)
    assert result.failure_class is failure and not result.triage_pending


@pytest.mark.parametrize("failure",(FailureClass.LEAK,FailureClass.POLICY,FailureClass.RUNTIME,"FC-SEMANTIC",None))
def test_r07_manual_triage_rejects_automatic_or_untyped_classes(failure):
    with pytest.raises(ValueError): ManualTriage(failure,"TEST-ONLY reviewer","TEST-ONLY evidence")


@pytest.mark.parametrize("reviewer,evidence",(("","unit"),(" ","unit"),(None,"unit"),("unit",""),("unit",None),("unit",False)))
def test_r07_manual_triage_rejects_missing_or_untyped_provenance(reviewer,evidence):
    with pytest.raises(ValueError): ManualTriage(FailureClass.SEMANTIC,reviewer,evidence)


def test_r07_unresolved_intent_has_no_catch_all_class(payroll_persona):
    result=classify_failure(make_outcome(payroll_persona),CaseAssessment(False,"TEST-ONLY unresolved intent"))
    assert result.failure_class is None and result.triage_pending
    with pytest.raises(TypeError):
        classify_failure(make_outcome(payroll_persona),CaseAssessment(False,"TEST-ONLY"),manual_triage=object())
