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


def test_r07_sealed_writer_outputs_metadata_and_consistent_counts_only(tmp_path,payroll_persona,fixture_date):
    from dataclasses import asdict
    import json
    from stark_t2sql.contracts import ExecutionMode,OutcomeStatus,StoppingLayer
    from stark_t2sql.evaluation.attribution import LayerObservation,accuracy_histogram
    from stark_t2sql.evaluation.records import RunRecord
    from stark_t2sql.utils.fingerprints import sha256_context
    from .test_runner_contracts import unit_settings

    # Synthetic in-memory payload and temporary lane; never actual holdout data.
    private=("UNIT_PRIVATE_QUESTION","UNIT_PRIVATE_REFERENCE","UNIT_PRIVATE_CANARY","UNIT_PRIVATE_ROW")
    case=Case("unit-sealed-case-id",CaseSet.ACCURACY,"payroll",fixture_date,ExpectedOutcome.MATCH_REFERENCE,
        question=private[0],reference_sql="SELECT '"+private[1]+"'",forbidden_values=(private[2],),
        forbidden_values_fixture_sha256=sha256_context("TEST-ONLY fixture"))
    outcome=make_outcome(payroll_persona,columns=("x",),rows=((private[3],),),sql="SELECT 'unit-private-candidate'")
    record=case_record(case,outcome,run_id="unit-sealed-accounting",partition=CasePartition.HOLDOUT,
        assessment=False,assessment_reason="TEST-ONLY pending intent review",leakage_observed=None,
        failure_class=None,triage_pending=True,candidate_sha256=sha256_context(outcome.executed_sql))
    writer=EvaluationRecordWriter(tmp_path,"unit-sealed-accounting",CasePartition.HOLDOUT,sealed_root=tmp_path/"unit-sealed-lane")
    run=RunRecord(writer.run_id,ExecutionMode.FULL,CasePartition.HOLDOUT,RunFingerprints(),unit_settings(),
        WarmupRecord(False,unavailable_reason="TEST-ONLY no model request"))
    histogram=accuracy_histogram((LayerObservation(case.id,ExecutionMode.FULL,OutcomeStatus.ANSWERED,StoppingLayer.NONE,False,None,triage_pending=True),))
    accounting=dict(total_cases=1,scored_cases=1,unscored_cases=0,pending_triage_cases=1,unsubmitted_cases=0,pending_cases=0)
    writer.write_run(run);writer.write_case(record)
    writer.write_summary({"accuracy":asdict(histogram),"accounting":accounting,"complete":False})
    writer.append_project_log(run,scored_cases=1,pending_cases=0,accounting=accounting)
    for path in writer.directory.glob("*.jsonl"):
        content=path.read_text(encoding="utf-8")
        assert not any(value in content for value in (*private,outcome.executed_sql))
        for line in content.splitlines(): assert isinstance(json.loads(line),dict)
    summary=json.loads((writer.directory/"summary.jsonl").read_text())
    assert summary["accounting"]==accounting
    project=(tmp_path/"PROJECT_LOG.md").read_text()
    assert "scored cases=1" in project and "pending cases=0" in project and "pending triage cases=1" in project
    assert case.id not in project and not any(value in project for value in private)


@pytest.mark.parametrize("change",(
    {"total_cases":3},{"pending_cases":2},{"pending_triage_cases":2},{"scored_cases":True},{"unscored_cases":-1},
    {"question":"UNIT_PRIVATE_QUESTION"},
))
def test_r07_invalid_accounting_cannot_be_written(tmp_path,change):
    values=dict(total_cases=2,scored_cases=1,unscored_cases=1,pending_triage_cases=1,unsubmitted_cases=0,pending_cases=1)
    values.update(change)
    writer=EvaluationRecordWriter(tmp_path,"unit-invalid-counts",CasePartition.TUNING)
    with pytest.raises(ConfigurationError): writer.write_summary({"accounting":values})
    assert not writer.directory.exists()


def test_r07_summary_rejects_disagreement_with_accuracy_histogram(tmp_path):
    writer=EvaluationRecordWriter(tmp_path,"unit-mismatched-counts",CasePartition.TUNING)
    values=dict(total_cases=1,scored_cases=1,unscored_cases=0,pending_triage_cases=1,unsubmitted_cases=0,pending_cases=0)
    with pytest.raises(ConfigurationError):
        writer.write_summary({"accounting":values,"accuracy":{"total":1,"scored":1,"unscored":0,"failed":0,"pending_triage_count":1}})


@pytest.mark.parametrize("field",("question","reference_sql","rows","forbidden_values"))
def test_r07_summary_rejects_payload_fields_even_in_sealed_lane(tmp_path,field):
    writer=EvaluationRecordWriter(tmp_path,"unit-no-payload",CasePartition.HOLDOUT,sealed_root=tmp_path/"unit-sealed")
    with pytest.raises(ConfigurationError): writer.write_summary({field:"UNIT_PRIVATE_PAYLOAD"})
    assert not writer.directory.exists()
