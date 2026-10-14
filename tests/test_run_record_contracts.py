"""Run-record unavailable-input and unscored-warmup definitions; no JSONL output."""
import pytest

from stark_t2sql.errors import ConfigurationError
from stark_t2sql.contracts import ExpectedOutcome
from stark_t2sql.evaluation.cases import Case,CaseSet
from stark_t2sql.evaluation.holdout import CasePartition
from stark_t2sql.evaluation.records import EvaluationRecordWriter,RunFingerprints,WarmupRecord,case_record
from .helpers import make_outcome


def test_missing_artifact_digests_remain_explicitly_unavailable():
    fingerprints=RunFingerprints()
    assert fingerprints.fixture_dump_sha256 is None and fingerprints.model_gguf_sha256 is None
    unavailable={item.field for item in fingerprints.unavailable}
    assert "fixture_dump_sha256" in unavailable and "model_gguf_sha256" in unavailable


def test_warmup_cannot_be_scored_or_claimed_without_observation():
    with pytest.raises(ConfigurationError): WarmupRecord(False,scored=True)
    with pytest.raises(ConfigurationError): WarmupRecord(True)
    unavailable=WarmupRecord(False,unavailable_reason="Required future model and template are absent")
    assert not unavailable.performed and not unavailable.scored and unavailable.generation_ms is None


def test_holdout_writer_requires_distinct_sealed_root_without_creating_files(project_root):
    with pytest.raises(ConfigurationError):
        EvaluationRecordWriter(project_root,"unit-record-contract",CasePartition.HOLDOUT)
    with pytest.raises(ConfigurationError):
        EvaluationRecordWriter(project_root,"unit-record-contract",CasePartition.HOLDOUT,sealed_root=project_root)
    writer=EvaluationRecordWriter(project_root,"unit-record-contract",CasePartition.HOLDOUT,sealed_root=project_root/"unit-owner-sealed-lane")
    assert writer.directory == project_root/"unit-owner-sealed-lane"/"unit-record-contract"


def test_case_metadata_retains_unknown_leakage_and_has_no_sql_or_canary_content(payroll_persona,fixture_date):
    case=Case("unit-record-only",CaseSet.REGRESSIONS,"payroll",fixture_date,
        ExpectedOutcome.BLOCKED_ANY,question="Unit metadata question")
    outcome=make_outcome(payroll_persona)
    record=case_record(case,outcome,run_id="unit-record-contract",partition=CasePartition.TUNING,
        assessment=None,assessment_reason="Unit required input unavailable",leakage_observed=None,
        failure_class=None,triage_pending=False,candidate_sha256=None)
    assert record.assessment is None and record.leakage_observed is None
    assert record.warmup is False and record.case_id == case.id
    assert record.request_id == outcome.request_context.request_id
    assert record.as_of_date == fixture_date.isoformat()
    assert not hasattr(record,"question") and not hasattr(record,"reference_sql")
    assert not hasattr(record,"forbidden_values") and not hasattr(record,"rows")
