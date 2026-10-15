"""R04 routing only: real semantics/context, fake model/validator/DB services.

These tests prove pre-generation behavior and pipeline attribution under stated
mocks. They do not prove SQLCoder generation, AST guard correctness, clone
authorization, PostgreSQL enforcement or adversarial leak/canary acceptance.
"""
from hashlib import sha256
from importlib import import_module
from types import SimpleNamespace

import pytest

from benchmarks.adversarial_nl.spec import prepare_nl_cases
from stark_t2sql.context.builder import FrozenBaselineDDL, HarnessContextAuthority
from stark_t2sql.contracts import Diagnostic, ExecutionMode, OutcomeStatus, Persona, ReasonCode, StoppingLayer
from stark_t2sql.db.executor import ExecutionResult
from stark_t2sql.errors import SQLValidationError
from stark_t2sql.inference.client import GenerationResult
from stark_t2sql.pipeline.orchestrator import _HARNESS_SEAL, _HarnessInvocation, _PipelineRuntime, _request_binding
from stark_t2sql.semantic.contracts import ResolutionStatus
from stark_t2sql.semantic.resolver import resolve_question

from .test_prompt_template_exact import unit_template


ATTACKS = tuple(case for case in prepare_nl_cases() if case.family in {"N2", "N5", "N6"})
RESTRICTED_PERSONAS = (("app_hr_bp", 47), ("app_hr_bp", 361), ("app_sales_mgr", 991))


def _persona(role, principal, matrix):
    # Principal values are test operands; no live identity resolution is claimed.
    return Persona(f"Unit {role} {principal}", role, principal, matrix.role(role).login_role)


def _forbidden(*args, **kwargs):
    raise AssertionError("This boundary must not be reached in this test")


@pytest.fixture
def mocked_services(monkeypatch, matrix, schema_metadata, governed_catalog):
    """Mock external services and clone receipts, leaving context compilation real."""
    def create(persona, mode, candidate, *, baseline=None):
        captured = {key: [] for key in ("prompts", "reviews", "executions", "traces")}

        def generate(prompt, **kwargs):
            captured["prompts"].append(prompt)
            return GenerationResult(candidate, 0.0, False, True, "stop", 1)

        def review(sql, selected):
            captured["reviews"].append((sql, selected))
            raise SQLValidationError("MOCK validator rejection; no actual parser approval is implied")

        def execute(selected, sql, **kwargs):
            captured["executions"].append((sql, selected, kwargs))
            if mode is ExecutionMode.NO_VALIDATOR:
                return ExecutionResult(
                    OutcomeStatus.BLOCKED_DB, StoppingLayer.DATABASE, ReasonCode.DB_PERMISSION_DENIED, 1000,
                    sqlstate="42501", executed_sql=sql,
                    diagnostics=(Diagnostic("MOCK_DB", "Simulated permission denial; no connection opened", "42501"),),
                )
            return ExecutionResult(OutcomeStatus.ANSWERED, StoppingLayer.NONE, ReasonCode.ANSWERED, 1000, executed_sql=sql)

        version = 1 if mode is ExecutionMode.UNCONTROLLED else 2
        # No DB-backed capability is issued. Only receipt consumption/issuance
        # are patched; build_harness_context's source/mode selection stays real.
        authority = object.__new__(HarnessContextAuthority)
        monkeypatch.setattr(HarnessContextAuthority, "issue", lambda self, request, **kwargs: SimpleNamespace(request=request, prompt_version=version))
        monkeypatch.setattr(HarnessContextAuthority, "_consume", lambda self, receipt, supplied: receipt.request)
        harness = None if mode is ExecutionMode.FULL else SimpleNamespace(
            context_authority=authority, executor=SimpleNamespace(execute=execute), baseline=baseline)
        runtime = _PipelineRuntime(
            config=SimpleNamespace(limits=SimpleNamespace(output_row_cap=1000)), matrix=matrix,
            personas=SimpleNamespace(resolve=lambda supplied: persona, fixture_dump_sha256=None),
            snapshot=schema_metadata, catalog=governed_catalog, template=unit_template(),
            client=SimpleNamespace(generate=generate, service=SimpleNamespace(model_sha256=None, llama_cpp_build=None, launcher_sha256=None),
                                   measurement_sha256=None, decoding=SimpleNamespace(seed=42, max_tokens=300)),
            validation_authority=SimpleNamespace(review=review, discard=lambda ticket: None),
            trace=SimpleNamespace(write_request=lambda outcome, **fields: captured["traces"].append(outcome)),
            production_executor=SimpleNamespace(execute=_forbidden) if mode is ExecutionMode.FULL else None,
            harness=harness,
        )
        invocation = None if harness is None else _HarnessInvocation(runtime, mode, version, None, _HARNESS_SEAL)
        return runtime, invocation, captured
    return create


@pytest.mark.parametrize("case", ATTACKS, ids=lambda case: f"{case.family}-{case.variant}")
@pytest.mark.parametrize("role,principal", RESTRICTED_PERSONAS)
@pytest.mark.parametrize("mode", (ExecutionMode.FULL, ExecutionMode.NO_VALIDATOR))
def test_r04_t06_t09_unauthorized_nl_reaches_mocked_stop_layer(case, role, principal, mode, mocked_services, governed_catalog, matrix, schema_metadata, fixture_date):
    persona = _persona(role, principal, matrix)
    resolution = resolve_question(case.question, governed_catalog, matrix, schema_metadata, role)
    assert resolution.status is ResolutionStatus.RESOLVED and resolution.clarification is None
    if case.variant in {"authority_claim", "role_play"}:
        assert resolution.concept_ids == ()
    # This candidate is supplied by the test, not observed model behavior.
    candidate = "SELECT base_salary FROM employee_compensation;"
    runtime, invocation, captured = mocked_services(persona, mode, candidate)
    with _request_binding(runtime, invocation, None):
        result = import_module("stark_t2sql.pipeline.answer").answer(persona, case.question, fixture_date, mode)
    assert len(captured["prompts"]) == 1 and len(captured["traces"]) == 1
    assert result.clarification is None and not result.rows
    prompt = captured["prompts"][0]
    for hidden in ("employee_compensation", "payroll_results", "payroll_runs", "gross_pay", "net_pay"):
        assert hidden not in prompt.text
    if role == "app_sales_mgr":
        assert "active_headcount" not in prompt.text
    assert ":as_of_date" not in prompt.text
    if mode is ExecutionMode.FULL:
        assert result.status is OutcomeStatus.BLOCKED_VALIDATOR and result.stopping_layer is StoppingLayer.VALIDATOR
        assert len(captured["reviews"]) == 1 and captured["executions"] == []
    else:
        assert result.status is OutcomeStatus.BLOCKED_DB and result.stopping_layer is StoppingLayer.DATABASE
        assert captured["reviews"] == [] and len(captured["executions"]) == 1
        assert result.diagnostics[0].sqlstate == "42501"  # explicitly simulated above


@pytest.mark.parametrize("case,clarifies", tuple((case, case.variant not in {"encoding", "multilingual"}) for case in ATTACKS), ids=lambda value: value.variant if hasattr(value, "variant") else str(value))
def test_authorized_payroll_retains_genuine_ambiguity(case, clarifies, governed_catalog, matrix, schema_metadata):
    result = resolve_question(case.question, governed_catalog, matrix, schema_metadata, "app_payroll")
    assert (result.status is ResolutionStatus.CLARIFICATION_REQUIRED) is clarifies
    if clarifies:
        assert result.clarification.options
    else:
        assert result.clarification is None


@pytest.mark.parametrize("role,principal", (("app_payroll", 326), *RESTRICTED_PERSONAS))
def test_headcount_clarifies_before_any_model_validator_or_execution(role, principal, mocked_services, fixture_date, matrix):
    persona = _persona(role, principal, matrix)
    runtime, invocation, captured = mocked_services(persona, ExecutionMode.FULL, "SELECT 1;")
    with _request_binding(runtime, invocation, None):
        result = import_module("stark_t2sql.pipeline.answer").answer(persona, "headcount", fixture_date)
    assert result.status is OutcomeStatus.CLARIFICATION_REQUIRED and result.stopping_layer is StoppingLayer.CONTEXT
    options = ("Direct report row count", "Visible employee row count")
    if role != "app_sales_mgr":
        options = ("Active headcount", *options)
    assert result.clarification.options == options
    assert captured["prompts"] == captured["reviews"] == captured["executions"] == []


@pytest.mark.parametrize("question", ("headcount", "compensation"))
def test_r04_t11_uncontrolled_omits_resolver_and_semantic_catalog(monkeypatch, question, mocked_services, project_root, matrix, fixture_date):
    from dataclasses import replace
    from stark_t2sql.context import builder

    source = (project_root / "schema.sql").read_bytes()
    # Actual frozen bytes, with a unit source binding, not a historical E2 run.
    baseline = FrozenBaselineDDL.from_bytes(source, recorded_sha256=sha256(source).hexdigest())
    persona = _persona("app_sales_mgr", 991, matrix)
    runtime, _, captured = mocked_services(persona, ExecutionMode.UNCONTROLLED, "SELECT 1;", baseline=baseline)
    # No SemanticCatalog exists in this runtime. The unused sha256 is only the
    # pipeline's initial diagnostic field; final v1 provenance must be None.
    runtime = replace(runtime, catalog=SimpleNamespace(sha256=None))
    invocation = _HarnessInvocation(runtime, ExecutionMode.UNCONTROLLED, 1, None, _HARNESS_SEAL)
    monkeypatch.setattr(import_module("stark_t2sql.pipeline.answer"), "resolve_question", _forbidden)
    for name in ("require_catalog_contract", "compile_semantics", "compile_full_semantics"):
        monkeypatch.setattr(builder, name, _forbidden)
    with _request_binding(runtime, invocation, None):
        result = import_module("stark_t2sql.pipeline.answer").answer(persona, question, fixture_date, ExecutionMode.UNCONTROLLED)
    assert result.status is OutcomeStatus.ANSWERED  # fake executor, no live SQL
    assert captured["reviews"] == [] and len(captured["executions"]) == 1
    prompt = captured["prompts"][0]
    assert prompt.prompt_version == 1 and source.decode("utf-8") in prompt.text
    assert '"metrics":' not in prompt.text and '"temporal_rules":' not in prompt.text
    assert result.fingerprints.semantic_catalog is None
    assert result.fingerprints.semantic == sha256(b"").hexdigest()
