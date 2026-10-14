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
