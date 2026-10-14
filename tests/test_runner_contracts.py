"""Runner/profile contract definitions over in-memory protocol mocks only.

Unit payloads contain no fixture rows, canaries, actual benchmark questions or
real sealed content. Their computed digests bind only those unit bytes. Mock
reference/lint/warmup results are never owner review or empirical run evidence.
No source definition is invoked by the drafting assignment, and writer methods
below are replaced with memory collectors for a future unit-test invocation.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stark_t2sql.contracts import ColumnMetadata,ExecutionMode,ExpectedOutcome,OutcomeStatus,ReasonCode,StoppingLayer
from stark_t2sql.db.executor import ExecutionResult
from stark_t2sql.errors import ConfigurationError,HarnessSafetyStopError,MissingDependencyError
from stark_t2sql.evaluation.ablation import AblationHarness,ModeProfile,all_mode_profiles
from stark_t2sql.evaluation.cases import Case,CaseSet
from stark_t2sql.evaluation.comparator import ResultTable
from stark_t2sql.evaluation.holdout import CasePartition,FrozenCaseIndex,FrozenCaseMetadata,HoldoutAuthority
from stark_t2sql.evaluation.records import EvaluationRecordWriter,RunFingerprints,RunSettings,WarmupRecord
from stark_t2sql.evaluation.reference import ReferenceAuthority,ReferenceResult
from stark_t2sql.evaluation.runner import EvaluationJob,EvaluationRunner,GuardedCase,RunPlan,load_sealed_case,load_tuning_case
from stark_t2sql.evaluation.wallclock import WallClockLintResult
from stark_t2sql.semantic.contracts import ResolutionStatus,VocabularyResolution
from stark_t2sql.utils.fingerprints import sha256_bytes
from .helpers import make_outcome
from .test_evaluation_contracts import unit_id
from .test_database_integration import actual_authorization_components


def unit_payload(partition,*,question=False,expected=ExpectedOutcome.BLOCKED_ANY,canaries=False,sql_text=None):
    case_id=unit_id(partition)
    raw={"id":case_id,"set":"regressions","persona":"payroll","as_of_date":"2026-10-12",
        "expected_outcome":expected.value,"requires_forbidden_values":canaries}
    raw["question" if question else "sql"]="Unit protocol request" if question else (sql_text if sql_text is not None else "SELECT 1 AS unit_value")
    if expected in {ExpectedOutcome.MATCH_REFERENCE,ExpectedOutcome.SCOPED_RESULT,ExpectedOutcome.CANONICAL_RESOLUTION}:
        raw["reference_sql"]="SELECT 1 AS unit_value"
    payload=json.dumps(raw,sort_keys=True).encode("utf-8")
    metadata=FrozenCaseMetadata(case_id,partition,sha256_bytes(payload))
    index=FrozenCaseIndex((metadata,),"In-memory unit protocol; no actual case-set freeze")
    return payload,metadata,index


def unit_settings():
    return RunSettings(prompt_version=2,llama_cpp_build=None,model_context_size=None,model_threads=None,
        sqlglot_version=None,validator_revision=None,validator_commit=None,temperature=0.0,seed=42,max_tokens=300,
        stop=(";",),generation_timeout_seconds=120,statement_timeout_seconds=15,output_row_cap=1000,
        database_work_mem_kib=None,database_temp_file_limit_kib=None,model_memory_limit_mib=None,
        baseline_reference=None,exclusive_model_service_reference=None)


def unit_plan(index,matrix,*,partition=CasePartition.TUNING,run_id="unit-run-contract",holdout_authority=None,holdout_permit=None):
    return RunPlan(run_id,ExecutionMode.FULL,partition,index,unit_settings(),
        RunFingerprints(access_matrix_sha256=matrix.sha256,case_set_sha256=index.sha256),
        sealed_owner_authorization_reference=(holdout_permit._authorization if holdout_permit is not None else "Unit boundary protocol only; no real run authorization") if partition is CasePartition.HOLDOUT else None,
        holdout_authority=holdout_authority,holdout_permit=holdout_permit)


def memory_writer(root,plan):
    writer=EvaluationRecordWriter(root,plan.run_id,plan.partition,
        sealed_root=root/"unit-sealed-lane" if plan.partition is CasePartition.HOLDOUT else None)
    calls=[]
    writer.write_run=lambda record:calls.append(("run",record))
    writer.write_case=lambda record:calls.append(("case",record))
    writer.write_summary=lambda record:calls.append(("summary",record))
    writer.append_project_log=lambda record,**kwargs:calls.append(("project_metadata",record,kwargs))
    return writer,calls


def protocol_harness(root,matrix,payroll_persona,*,model=False):
    harness=object.__new__(AblationHarness)
    harness._application=object() if model else None
    personas=SimpleNamespace(fixture_dump_sha256=None,resolve=lambda selection:payroll_persona)
    source=SimpleNamespace(personas=personas,matrix=matrix)
    harness._runtime=SimpleNamespace(personas=personas,matrix=matrix,harness=SimpleNamespace(source=source),
        trace=SimpleNamespace(root=root),catalog=None,snapshot=None,template=SimpleNamespace(sha256=None),
        config=SimpleNamespace(limits=SimpleNamespace(generation_timeout_seconds=120,statement_timeout_seconds=15,output_row_cap=1000),
            resource_budgets=SimpleNamespace(database_work_mem_kib=None,database_temp_file_limit_kib=None,model_memory_limit_mib=None)),
        validation_authority=SimpleNamespace(_reviewer=SimpleNamespace(approval=None)),
        client=SimpleNamespace(service=SimpleNamespace(model_sha256=None,launcher_sha256=None,llama_cpp_build=None),
            measurement_sha256=None,decoding=SimpleNamespace(seed=42,temperature=0.0,max_tokens=300,stop=(";",))))
    calls=[]
    harness.direct=lambda case,profile,**kwargs:calls.append(("direct",case.id,profile,kwargs)) or make_outcome(payroll_persona,
        status=OutcomeStatus.BLOCKED_VALIDATOR,reason=ReasonCode.VALIDATOR_REJECTED,layer=StoppingLayer.VALIDATOR,mode=profile.mode)
    harness.question=lambda case,profile,**kwargs:calls.append(("question",case.id,profile)) or make_outcome(payroll_persona,
        columns=(ColumnMetadata("unit_value",canonical_identity="unit_value"),),mode=profile.mode)
    harness.warmup=lambda case,profile,**kwargs:calls.append(("warmup",case.id,profile)) or WarmupRecord(True,False,1.0,1,case.id)
    return harness,calls


def tuning_loaded(index,payload,metadata):
    return load_tuning_case(index,metadata.id,CaseSet.REGRESSIONS,loader=lambda entry:payload)


def test_exact_four_source_profiles_and_no_undefined_prompt_version():
    profiles=all_mode_profiles()
    assert tuple((item.mode,item.prompt_version) for item in profiles) == (
        (ExecutionMode.FULL,2),(ExecutionMode.NO_PROMPT_FILTER,2),(ExecutionMode.NO_VALIDATOR,2),(ExecutionMode.UNCONTROLLED,1))
    with pytest.raises(HarnessSafetyStopError): ModeProfile(ExecutionMode.UNCONTROLLED,2)
    with pytest.raises(HarnessSafetyStopError): ModeProfile(ExecutionMode.FULL,1)
    with pytest.raises(ConfigurationError): ModeProfile("FULL",2)


def test_direct_only_harness_requires_exact_clone_capability():
    with pytest.raises(ConfigurationError): AblationHarness(source=object(),parser_approval=None)
    with pytest.raises(ConfigurationError): AblationHarness()


def test_actual_direct_only_composition_omits_model_and_template(actual_authorization_components,parser_approval):
    # Actual separately opted-in owner composition is required. There is no
    # fake clone/registry/parser approval and no model asset is substituted.
    source,snapshot=actual_authorization_components
    harness=AblationHarness(source=source,parser_approval=parser_approval)
    assert harness.source is source and not harness.model_available
    assert not hasattr(harness._runtime,"client") and not hasattr(harness._runtime,"template")


def test_guarded_case_cannot_be_constructed_from_bare_case_without_private_loader_seal():
    _,metadata,_=unit_payload(CasePartition.TUNING)
    case=Case(metadata.id,CaseSet.REGRESSIONS,"payroll",date(2026,10,12),ExpectedOutcome.BLOCKED_ANY,sql="SELECT 1")
    with pytest.raises(ConfigurationError): GuardedCase(metadata,case)


def test_tuning_loader_rejects_payload_drift_and_never_opens_sealed_ids():
    payload,metadata,index=unit_payload(CasePartition.TUNING)
    with pytest.raises(ValueError): load_tuning_case(index,metadata.id,CaseSet.REGRESSIONS,loader=lambda entry:payload+b" ")
    sealed_payload,sealed_metadata,sealed_index=unit_payload(CasePartition.HOLDOUT)
    calls=[]
    with pytest.raises(PermissionError):
        load_tuning_case(sealed_index,sealed_metadata.id,CaseSet.REGRESSIONS,loader=lambda entry:calls.append(entry) or sealed_payload)
    assert calls == []


def test_run_plan_case_set_binding_is_required(matrix):
    _,_,index=unit_payload(CasePartition.TUNING)
    with pytest.raises(MissingDependencyError):
        RunPlan("unit-run-contract",ExecutionMode.FULL,CasePartition.TUNING,index,unit_settings(),RunFingerprints())


def test_runner_refuses_bare_cases_before_any_candidate_call(project_root,matrix,payroll_persona):
    payload,metadata,index=unit_payload(CasePartition.TUNING)
    loaded=tuning_loaded(index,payload,metadata)
    plan=unit_plan(index,matrix); writer,writes=memory_writer(project_root,plan)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona)
    runner=EvaluationRunner(harness,references=None,wallclock_review=None)
    with pytest.raises(ConfigurationError): runner.run((loaded.case,),plan,writer)
    assert not calls and not writes


def test_runner_index_mismatch_cannot_relabel_case(project_root,matrix,payroll_persona):
    payload,metadata,index=unit_payload(CasePartition.TUNING)
    loaded=tuning_loaded(index,payload,metadata)
    altered=FrozenCaseMetadata(metadata.id,metadata.partition,sha256_bytes(payload+b" "))
    different=FrozenCaseIndex((altered,),"Unit alternate metadata; no actual freeze")
    plan=unit_plan(different,matrix); writer,writes=memory_writer(project_root,plan)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona)
    with pytest.raises(ConfigurationError): EvaluationRunner(harness,references=None,wallclock_review=None).run((loaded,),plan,writer)
    assert not calls and not writes


def test_sealed_loader_records_boundary_binding_and_requires_sealed_trace_lane(project_root,matrix,payroll_persona):
    payload,metadata,index=unit_payload(CasePartition.HOLDOUT)
    exposures=[]
    authority=HoldoutAuthority(index,record_exposure=exposures.append)
    permit=authority.begin_boundary(epic="E8",run_id="unit-sealed-boundary",authorization_reference="Unit opaque protocol; no actual authorization")
    loaded=load_sealed_case(authority,permit,metadata.id,CaseSet.REGRESSIONS,loader=lambda entry:payload)
    assert loaded._boundary_run_id == "unit-sealed-boundary"
    with pytest.raises(ConfigurationError):
        unit_plan(index,matrix,partition=CasePartition.HOLDOUT,run_id="unit-other-boundary",holdout_authority=authority,holdout_permit=permit)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona)
    runner=EvaluationRunner(harness,references=None,wallclock_review=None)
    plan=unit_plan(index,matrix,partition=CasePartition.HOLDOUT,run_id="unit-sealed-boundary",holdout_authority=authority,holdout_permit=permit)
    writer,writes=memory_writer(project_root,plan)
    with pytest.raises(ConfigurationError): runner._guard((loaded,),plan,writer)
    harness._runtime.trace.root=project_root/"unit-sealed-lane"
    runner._guard((loaded,),plan,writer)
    assert not calls and not writes
    authority.end_boundary(permit)
    with pytest.raises(PermissionError): runner._guard((loaded,),plan,writer)
    assert tuple(event.event for event in exposures) == ("BOUNDARY_BEGIN","PAYLOAD_READ_ATTEMPT","BOUNDARY_END")


def test_sealed_plan_requires_live_authority_and_permit(matrix):
    _,_,index=unit_payload(CasePartition.HOLDOUT)
    with pytest.raises(MissingDependencyError): unit_plan(index,matrix,partition=CasePartition.HOLDOUT)


def test_direct_run_does_not_need_model_template_or_warmup(project_root,matrix,payroll_persona):
    payload,metadata,index=unit_payload(CasePartition.TUNING)
    loaded=tuning_loaded(index,payload,metadata)
    plan=unit_plan(index,matrix); writer,writes=memory_writer(project_root,plan)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona)
    summary=EvaluationRunner(harness,references=None,wallclock_review=None).run((loaded,),plan,writer)
    assert tuple(call[0] for call in calls) == ("direct",)
    assert calls[0][3] == {"never_execute":False}
    run_record=next(record for kind,record,*unused in writes if kind == "run")
    assert not run_record.warmup.performed and not run_record.warmup.scored
    assert summary.records[0].leakage_observed is None


def test_question_run_requires_guarded_tuning_warmup_and_never_scores_it(project_root,matrix,payroll_persona):
    payload,metadata,index=unit_payload(CasePartition.TUNING,question=True,expected=ExpectedOutcome.MATCH_REFERENCE)
    loaded=tuning_loaded(index,payload,metadata)
    plan=unit_plan(index,matrix); writer,writes=memory_writer(project_root,plan)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona,model=True)
    runner=EvaluationRunner(harness,references=None,wallclock_review=None)
    with pytest.raises(MissingDependencyError): runner.run((loaded,),plan,writer)
    assert not calls and not writes
    summary=runner.run((loaded,),plan,writer,warmup_case=loaded)
    assert tuple(call[0] for call in calls) == ("warmup","question")
    run_record=next(record for kind,record,*unused in writes if kind == "run")
    assert run_record.warmup.performed and not run_record.warmup.scored
    assert len(summary.records) == 1 and summary.records[0].assessment is None


def test_warmup_from_holdout_partition_is_rejected_without_model_call(project_root,matrix,payroll_persona):
    from stark_t2sql.evaluation.runner import _CASE_SEAL
    payload,metadata,index=unit_payload(CasePartition.TUNING,question=True)
    loaded=tuning_loaded(index,payload,metadata)
    _,sealed_metadata,_=unit_payload(CasePartition.HOLDOUT,question=True)
    sealed_case=Case(sealed_metadata.id,CaseSet.REGRESSIONS,"payroll",date(2026,10,12),ExpectedOutcome.BLOCKED_ANY,question="Unit protocol request")
    sealed=GuardedCase(sealed_metadata,sealed_case,_seal=_CASE_SEAL,_boundary_run_id="unit-boundary")
    extended=index.extend((sealed_metadata,),freeze_reference="Unit metadata extension")
    plan=unit_plan(extended,matrix); writer,writes=memory_writer(project_root,plan)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona,model=True)
    with pytest.raises(ConfigurationError): EvaluationRunner(harness,references=None,wallclock_review=None).run((loaded,),plan,writer,warmup_case=sealed)
    assert not calls and not writes


@pytest.mark.parametrize("dependency", ("reference","projection","canaries","wallclock"))
def test_required_evaluation_inputs_remain_unscored(monkeypatch,project_root,matrix,payroll_persona,dependency):
    import stark_t2sql.evaluation.runner as module
    expected=ExpectedOutcome.BLOCKED_ANY if dependency in {"canaries","wallclock"} else ExpectedOutcome.MATCH_REFERENCE
    payload,metadata,index=unit_payload(CasePartition.TUNING,expected=expected,canaries=dependency=="canaries")
    loaded=tuning_loaded(index,payload,metadata)
    plan=unit_plan(index,matrix); writer,writes=memory_writer(project_root,plan)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona)
    references=None
    if dependency == "projection":
        references=object.__new__(ReferenceAuthority)
        references.source=harness.source
        references.evaluate=lambda *args:ReferenceResult(True,ResultTable((ColumnMetadata("unit_value"),),()),"Unit mock oracle, not actual review",True)
        harness.direct=lambda case,profile,**kwargs:make_outcome(payroll_persona,columns=("unit_value",),mode=profile.mode)
    elif dependency == "reference":
        harness.direct=lambda case,profile,**kwargs:make_outcome(payroll_persona,columns=(ColumnMetadata("unit_value",canonical_identity="unit_value"),),mode=profile.mode)
    elif dependency == "wallclock":
        harness.direct=lambda case,profile,**kwargs:make_outcome(payroll_persona,
            columns=(ColumnMetadata("unit_value",canonical_identity="unit_value"),),sql="SELECT 1",mode=profile.mode)
        monkeypatch.setattr(module,"lint_wallclock",lambda *args,**kwargs:WallClockLintResult(False,unavailable_reason="Unit missing capability"))
    summary=EvaluationRunner(harness,references=references,wallclock_review=None).run((loaded,),plan,writer)
    assert summary.records[0].assessment is None and summary.records[0].leakage_observed is None
    assert not summary.complete


def test_failed_warmup_reports_unsubmitted_ids_without_per_case_result(project_root,matrix,payroll_persona):
    payload,metadata,index=unit_payload(CasePartition.TUNING,question=True)
    loaded=tuning_loaded(index,payload,metadata)
    plan=unit_plan(index,matrix);writer,writes=memory_writer(project_root,plan)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona,model=True)
    def unavailable(*args,**kwargs): raise MissingDependencyError("Unit missing warmup capability")
    harness.warmup=unavailable
    summary=EvaluationRunner(harness,references=None,wallclock_review=None).run((loaded,),plan,writer,warmup_case=loaded)
    assert summary.unsubmitted_case_ids == (metadata.id,)
    assert not summary.records and not summary.observations and not summary.complete
    assert summary.pending_cases == 1 and not calls
    assert not any(event[0] == "case" for event in writes)
    aborted=next(record for kind,record,*unused in writes if kind == "run")
    assert aborted.never_execute_case_ids == ()


def test_canonical_definition_id_mismatch_is_not_reference_success(monkeypatch,project_root,matrix,payroll_persona):
    import stark_t2sql.evaluation.runner as module
    payload,metadata,index=unit_payload(CasePartition.TUNING,question=True,expected=ExpectedOutcome.CANONICAL_RESOLUTION)
    loaded=tuning_loaded(index,payload,metadata)
    plan=replace(unit_plan(index,matrix),canonical_expectations=((metadata.id,"active_headcount"),))
    writer,writes=memory_writer(project_root,plan)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona,model=True)
    references=object.__new__(ReferenceAuthority)
    references.source=harness.source
    references.evaluate=lambda *args:ReferenceResult(True,ResultTable((ColumnMetadata("unit_value",canonical_identity="unit_value"),),()),"Unit mock oracle only",True)
    monkeypatch.setattr(module,"resolve_question",lambda *args:VocabularyResolution(ResolutionStatus.RESOLVED,("unit_wrong_definition",)))
    summary=EvaluationRunner(harness,references=references,wallclock_review=None).run((loaded,),plan,writer,warmup_case=loaded)
    assert summary.records[0].assessment is False and summary.records[0].triage_pending


def test_job_rejects_generic_runner_before_any_execution():
    job=EvaluationJob(object(),(),None,None)
    with pytest.raises(ConfigurationError): job.execute()


def test_question_facade_uses_existing_application_answer_without_rewriting(payroll_persona,fixture_date):
    harness=object.__new__(AblationHarness)
    calls=[]
    harness._runtime=SimpleNamespace(personas=SimpleNamespace(resolve=lambda selection:payroll_persona))
    harness._application=SimpleNamespace(answer=lambda *args,**kwargs:calls.append((args,kwargs)) or make_outcome(payroll_persona))
    case=Case("unit-question-route",CaseSet.REGRESSIONS,"payroll",fixture_date,ExpectedOutcome.BLOCKED_ANY,question="Unit unchanged question")
    profile=ModeProfile(ExecutionMode.NO_VALIDATOR,2)
    harness.question(case,profile)
    assert calls == [((payroll_persona,"Unit unchanged question",fixture_date,ExecutionMode.NO_VALIDATOR),{"prompt_version":2,"cancel_event":None})]


@pytest.mark.parametrize("mode", (ExecutionMode.FULL,ExecutionMode.NO_VALIDATOR))
def test_direct_facade_submits_only_to_existing_executor_protocol(matrix,payroll_persona,fixture_date,mode):
    calls=[]; traces=[]; reviews=[]
    ticket=SimpleNamespace(regenerated_sql="SELECT 1 AS unit_regenerated")
    def review(candidate,persona): reviews.append((candidate,persona)); return ticket
    def execute(persona,candidate,**kwargs):
        calls.append((persona,candidate,kwargs))
        return ExecutionResult(OutcomeStatus.ANSWERED,StoppingLayer.NONE,ReasonCode.ANSWERED,1000,executed_sql=candidate)
    runtime=SimpleNamespace(personas=SimpleNamespace(resolve=lambda selection:payroll_persona,fixture_dump_sha256=None),matrix=matrix,
        config=SimpleNamespace(limits=SimpleNamespace(output_row_cap=1000)),
        harness=SimpleNamespace(executor=SimpleNamespace(execute=execute)),
        validation_authority=SimpleNamespace(review=review,discard=lambda issued:None),
        trace=SimpleNamespace(write_request=lambda outcome,**kwargs:traces.append((outcome,kwargs))))
    harness=object.__new__(AblationHarness); harness._runtime=runtime; harness._application=None
    case=Case("unit-direct-route",CaseSet.REGRESSIONS,"payroll",fixture_date,ExpectedOutcome.BLOCKED_ANY,sql="SELECT 1 AS unit_source")
    outcome=harness.direct(case,ModeProfile(mode,2))
    assert len(calls) == 1 and len(traces) == 1 and outcome.status is OutcomeStatus.ANSWERED
    expected=ticket.regenerated_sql if mode is ExecutionMode.FULL else case.sql
    assert calls[0][1] == expected and calls[0][2]["mode"] is mode
    assert calls[0][2]["validation_ticket"] is (ticket if mode is ExecutionMode.FULL else None)
    assert bool(reviews) is (mode is ExecutionMode.FULL)


def test_preclassified_hazard_is_trace_only_and_never_executor_input(matrix,payroll_persona,fixture_date):
    calls=[]; traces=[]
    def forbidden(*args,**kwargs): calls.append((args,kwargs)); raise AssertionError("Prepared hazard must remain unexecuted")
    harness=object.__new__(AblationHarness); harness._application=None
    harness._runtime=SimpleNamespace(personas=SimpleNamespace(resolve=lambda selection:payroll_persona,fixture_dump_sha256=None),matrix=matrix,
        config=SimpleNamespace(limits=SimpleNamespace(output_row_cap=1000)),
        harness=SimpleNamespace(executor=SimpleNamespace(execute=forbidden)),
        validation_authority=SimpleNamespace(review=forbidden,discard=forbidden),
        trace=SimpleNamespace(write_request=lambda outcome,**kwargs:traces.append((outcome,kwargs))))
    case=Case("unit-hazard-only",CaseSet.ADVERSARIAL_SQL,"payroll",fixture_date,
        ExpectedOutcome.BLOCKED_ANY,sql="SET app.principal_id='326'",requires_forbidden_values=True)
    outcome=harness.direct(case,ModeProfile(ExecutionMode.UNCONTROLLED,1),never_execute=True)
    assert outcome.status is OutcomeStatus.HARNESS_SAFETY_STOP and outcome.executed_sql is None
    assert not calls and len(traces) == 1


def test_direct_metadata_collection_keeps_missing_model_artifacts_and_never_reads_cases_or_services(monkeypatch,project_root,matrix,payroll_persona):
    import stark_t2sql.evaluation.runner as module
    from stark_t2sql.evaluation.runner import RuntimeRecordInputs,collect_run_metadata
    from stark_t2sql.security.validator import VALIDATOR_REVISION
    # Bind only opaque unit metadata bytes; no benchmark payload file exists.
    case_id=unit_id(CasePartition.TUNING)
    metadata=FrozenCaseMetadata(case_id,CasePartition.TUNING,sha256_bytes(b"Unit metadata-only binding"))
    index=FrozenCaseIndex((metadata,),"Unit metadata collection protocol; no actual benchmark freeze")
    harness,calls=protocol_harness(project_root,matrix,payroll_persona)
    runtime=harness._runtime
    runtime.config.paths=SimpleNamespace(root=project_root,schema=project_root/"schema.sql")
    runtime.config.resource_budgets.measurement_source=project_root/"unit-unavailable-measurement-input"
    runtime.validation_authority._reviewer.revision=VALIDATOR_REVISION
    forbidden_reads=[]
    def forbidden(*args,**kwargs):
        forbidden_reads.append((args,kwargs))
        raise AssertionError("Metadata collection must not read case payloads or contact services")
    class ForbiddenModelInput:
        def __getattribute__(self,name):
            raise AssertionError("Direct metadata must not consult a model/template/catalog capability")
    runtime.client=ForbiddenModelInput()
    runtime.template=ForbiddenModelInput()
    runtime.catalog=ForbiddenModelInput()
    runtime.personas.resolve=forbidden
    harness.source.connection=forbidden
    monkeypatch.setattr(module,"read_tuning_payload",forbidden)
    monkeypatch.setattr(module,"load_tuning_case",forbidden)
    attempted_sources=[]
    def unavailable_source(path):
        attempted_sources.append(Path(path))
        raise MissingDependencyError("Unit missing source artifact read")
    monkeypatch.setattr(module,"sha256_file",unavailable_source)
    fingerprints,settings=collect_run_metadata(harness,index,ModeProfile(ExecutionMode.FULL,2),supplied=RuntimeRecordInputs())
    assert set(attempted_sources) == {
        project_root/"unit-unavailable-measurement-input",project_root/"schema.sql",
        project_root/"src"/"stark_t2sql"/"security"/"validator.py"}
    assert not forbidden_reads and not calls
    assert fingerprints.case_set_sha256 == index.sha256 and fingerprints.access_matrix_sha256 == matrix.sha256
    assert fingerprints.fixture_dump_sha256 is None and fingerprints.parser_review_sha256 is None
    assert fingerprints.model_gguf_sha256 is None and fingerprints.llama_launcher_sha256 is None
    assert fingerprints.prompt_template_sha256 is None and fingerprints.semantic_catalog_sha256 is None
    assert fingerprints.resource_measurements_sha256 is None and fingerprints.source_schema_sha256 is None
    assert settings.llama_cpp_build is None and settings.model_context_size is None and settings.model_threads is None
    assert settings.sqlglot_version is None and settings.validator_commit is None
    assert settings.max_tokens == 300 and settings.temperature == 0.0 and settings.stop == (";",)


def test_never_execute_plan_ids_are_unique_frozen_direct_source_ids(project_root,matrix,payroll_persona):
    payload,metadata,index=unit_payload(CasePartition.TUNING,sql_text="SET ROLE app_payroll")
    loaded=tuning_loaded(index,payload,metadata)
    plan=replace(unit_plan(index,matrix),never_execute_case_ids=(metadata.id,))
    with pytest.raises(ConfigurationError): replace(plan,never_execute_case_ids=(metadata.id,metadata.id))
    with pytest.raises(ConfigurationError): replace(plan,never_execute_case_ids=("unit-not-frozen",))
    writer,writes=memory_writer(project_root,plan)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona)
    direct_calls=[]
    def restricted(case,profile,*,never_execute):
        direct_calls.append((case.id,never_execute))
        assert never_execute is True
        return make_outcome(payroll_persona,status=OutcomeStatus.HARNESS_SAFETY_STOP,
            reason=ReasonCode.HARNESS_SAFETY_STOP,layer=StoppingLayer.HARNESS,mode=profile.mode)
    harness.direct=restricted
    summary=EvaluationRunner(harness,references=None,wallclock_review=None).run((loaded,),plan,writer)
    assert direct_calls == [(metadata.id,True)] and not calls
    assert summary.records[0].status is OutcomeStatus.HARNESS_SAFETY_STOP
    assert summary.records[0].assessment is None and summary.records[0].leakage_observed is None
    recorded=next(record for kind,record,*unused in writes if kind == "run")
    assert recorded.never_execute_case_ids == (metadata.id,)


def test_never_execute_plan_binding_cannot_target_model_question(project_root,matrix,payroll_persona):
    payload,metadata,index=unit_payload(CasePartition.TUNING,question=True)
    loaded=tuning_loaded(index,payload,metadata)
    plan=replace(unit_plan(index,matrix),never_execute_case_ids=(metadata.id,))
    writer,writes=memory_writer(project_root,plan)
    harness,calls=protocol_harness(project_root,matrix,payroll_persona,model=True)
    with pytest.raises(ConfigurationError):
        EvaluationRunner(harness,references=None,wallclock_review=None).run((loaded,),plan,writer,warmup_case=loaded)
    assert not calls and not writes
