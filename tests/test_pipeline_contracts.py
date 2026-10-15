"""Mocked canonical-path contracts. No service/DB/template/log operation occurs."""
from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace

import pytest

from stark_t2sql.contracts import Clarification, ExecutionMode, OutcomeStatus, ReasonCode, StoppingLayer
from stark_t2sql.db.executor import ExecutionResult
from stark_t2sql.errors import GenerationTimeoutError, ModelGenerationError, SQLValidationError
from stark_t2sql.errors import InvalidRequestError
from stark_t2sql.pipeline.orchestrator import _ACTIVE_HARNESS, _ACTIVE_RUNTIME, _PipelineRuntime, PersonaApplication
from stark_t2sql.semantic.contracts import ResolutionStatus, VocabularyResolution


class CapturedTrace:
    def __init__(self): self.calls = []
    def write_request(self, outcome, **fields): self.calls.append((outcome,fields))


@pytest.fixture
def mocked_runtime(payroll_persona, matrix):
    trace = CapturedTrace()
    personas = SimpleNamespace(resolve=lambda selected: payroll_persona,
        fixture_dump_sha256=None,personas={"payroll":payroll_persona})
    runtime = _PipelineRuntime(
        config=SimpleNamespace(limits=SimpleNamespace(output_row_cap=1000)),matrix=matrix,personas=personas,
        snapshot=None,catalog=SimpleNamespace(sha256=None),template=SimpleNamespace(sha256=None),
        client=SimpleNamespace(service=SimpleNamespace(model_sha256=None,llama_cpp_build=None,launcher_sha256=None),
            measurement_sha256=None,decoding=SimpleNamespace(seed=42,max_tokens=300)),
        validation_authority=SimpleNamespace(discard=lambda receipt: None),trace=trace,
        production_executor=object(),harness=None)
    token = _ACTIVE_RUNTIME.set(runtime)
    harness_token = _ACTIVE_HARNESS.set(None)
    try: yield runtime
    finally:
        _ACTIVE_HARNESS.reset(harness_token)
        _ACTIVE_RUNTIME.reset(token)


def test_ambiguity_short_circuits_before_model_and_executor(monkeypatch, mocked_runtime, payroll_persona, fixture_date):
    module = import_module("stark_t2sql.pipeline.answer")
    monkeypatch.setattr(module,"resolve_question",lambda *args: VocabularyResolution(
        ResolutionStatus.CLARIFICATION_REQUIRED,(),Clarification("Please choose the time basis.", ("Payment date", "Period end"))))
    def forbidden(*args,**kwargs): raise AssertionError("No generation/context/SQL on ambiguity")
    mocked_runtime.client.generate = forbidden
    monkeypatch.setattr(module,"build_context",forbidden)
    result = module.answer(payroll_persona,"headcount",fixture_date)
    assert result.status is OutcomeStatus.CLARIFICATION_REQUIRED
    assert result.clarification.options == ("Payment date", "Period end")
    assert result.executed_sql is None and result.raw_output is None and not result.rows
    assert len(mocked_runtime.trace.calls) == 1


@pytest.mark.parametrize("error,status,layer", (
    (GenerationTimeoutError("Private generation detail"),OutcomeStatus.TIMEOUT,StoppingLayer.MODEL),
    (ModelGenerationError("Private model detail"),OutcomeStatus.MODEL_ERROR,StoppingLayer.MODEL),
    (SQLValidationError("Private validator detail"),OutcomeStatus.BLOCKED_VALIDATOR,StoppingLayer.VALIDATOR),
))
def test_stage_failure_retains_private_diagnostics_one_trace(monkeypatch,mocked_runtime,payroll_persona,fixture_date,error,status,layer):
    module = import_module("stark_t2sql.pipeline.answer")
    def fail(*args): raise error
    monkeypatch.setattr(module,"_perform",fail)
    result = module.answer(payroll_persona,"Unit question",fixture_date)
    assert result.status is status and result.stopping_layer is layer and not result.rows
    assert result.diagnostics and len(mocked_runtime.trace.calls) == 1
    assert "Private" not in result.to_safe_response().to_json()


@pytest.mark.parametrize("mode", (ExecutionMode.NO_PROMPT_FILTER,ExecutionMode.NO_VALIDATOR,ExecutionMode.UNCONTROLLED))
def test_production_answer_cannot_acquire_harness_mode(mocked_runtime,payroll_persona,fixture_date,mode):
    module = import_module("stark_t2sql.pipeline.answer")
    result = module.answer(payroll_persona,"Unit question",fixture_date,mode)
    assert result.status is OutcomeStatus.HARNESS_SAFETY_STOP and result.executed_sql is None


def test_persona_facade_forces_full_and_has_no_mode_argument(monkeypatch,mocked_runtime,payroll_persona,fixture_date):
    from .helpers import make_outcome
    module = import_module("stark_t2sql.pipeline.answer")
    seen = []
    def captured(persona,question,as_of_date,mode):
        seen.append(mode)
        return make_outcome(persona)
    monkeypatch.setattr(module,"answer",captured)
    facade = PersonaApplication(mocked_runtime)
    assert facade.answer(payroll_persona,"NO_VALIDATOR",fixture_date).status is OutcomeStatus.ANSWERED
    assert seen == [ExecutionMode.FULL]
    with pytest.raises(TypeError): facade.answer(payroll_persona,"Unit",fixture_date,mode=ExecutionMode.NO_VALIDATOR)


def test_trace_append_failure_suppresses_public_result(monkeypatch,mocked_runtime,payroll_persona,fixture_date):
    module = import_module("stark_t2sql.pipeline.answer")
    def perform(runtime,request,work,invocation,cancel):
        work.execution = ExecutionResult(OutcomeStatus.ANSWERED,StoppingLayer.NONE,ReasonCode.ANSWERED,1000)
        return OutcomeStatus.ANSWERED,StoppingLayer.NONE,ReasonCode.ANSWERED
    def fail_trace(*args,**kwargs): raise OSError("Unit disk failure")
    monkeypatch.setattr(module,"_perform",perform)
    mocked_runtime.trace.write_request = fail_trace
    result = module.answer(payroll_persona,"Unit question",fixture_date)
    assert result.status is OutcomeStatus.ERROR and result.stopping_layer is StoppingLayer.RESPONSE
    assert not result.to_safe_response().rows


@pytest.mark.parametrize("mode", ("FULL","NO_VALIDATOR","UNCONTROLLED",None))
def test_mode_payload_strings_are_never_coerced(mocked_runtime,payroll_persona,fixture_date,mode):
    module=import_module("stark_t2sql.pipeline.answer")
    with pytest.raises(InvalidRequestError): module.answer(payroll_persona,"Unit",fixture_date,mode)
    assert len(mocked_runtime.trace.calls) == 1


def test_process_single_flight_refuses_second_pipeline_request(mocked_runtime,payroll_persona,fixture_date):
    module=import_module("stark_t2sql.pipeline.answer")
    assert module._REQUEST_LOCK.acquire(blocking=False)
    try:
        result=module.answer(payroll_persona,"Unit",fixture_date)
        assert result.status is OutcomeStatus.MODEL_ERROR and result.executed_sql is None
    finally: module._REQUEST_LOCK.release()
    assert len(mocked_runtime.trace.calls) == 1
