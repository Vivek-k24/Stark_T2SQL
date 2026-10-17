"""The single FR-8 answer path for production and the isolated local harness.

Only this module calls the existing Prompt 2 candidate executors. It composes
the Prompt 3 resolver/context/validator without reimplementing their rules.
Raw SQL, output and diagnostics remain in Outcome/local trace; the persona
facade projects the shared SafeResponse. Importing this source does no work.

Malformed input without a valid fixture-resolved InputRequest is traced and
raises a typed non-sensitive-boundary error. It cannot produce a shared Outcome
without inventing a principal, date or question. Normal typed requests, including
configuration/model/database failures and harness stops, return Outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from threading import Event, Lock
from time import monotonic
import traceback
from typing import Mapping
from uuid import uuid4

from ..context.builder import HarnessContextRequest, build_context, build_harness_context
from ..contracts import (
    ArtifactFingerprints, Clarification, Diagnostic, ExecutionMode, FailureClass, InputRequest,
    Outcome, OutcomeStatus, Persona, ReasonCode, RequestContext, RequestTimings,
    RowScopeKind, StoppingLayer,
)
from ..db.executor import ExecutionResult, ValidatedSelect
from ..errors import (
    HarnessSafetyStopError, InvalidRequestError, MissingDependencyError,
    ModelGenerationError, StarkT2SQLError,
)
from ..inference.extract import extract_sql
from ..inference.prompt_builder import build_prompt
from ..semantic.contracts import ResolutionStatus
from ..semantic.resolver import resolve_question
from .orchestrator import (
    PROJECT_ROOT, _ACTIVE_CANCEL, _ACTIVE_HARNESS, _ACTIVE_RUNTIME, _HARNESS_SEAL,
    _HarnessInvocation, _PipelineRuntime, load_persona_runtime,
)
from .trace import TraceWriter


# One process-wide guard covers every persona, CLI and harness invocation. No
# queued request can overlap context generation, inference, validation or SQL.
_REQUEST_LOCK = Lock()
_MAX_QUESTION_BYTES = 16_384


@dataclass(slots=True)
class _Work:
    stage: StoppingLayer = StoppingLayer.INPUT
    raw_output: str | None = None
    extracted_sql: str | None = None
    regenerated_sql: str | None = None
    execution: ExecutionResult | None = None
    clarification: Clarification | None = None
    fingerprints: ArtifactFingerprints = field(default_factory=ArtifactFingerprints)
    timings: RequestTimings = field(default_factory=RequestTimings)
    metadata: dict[str, object] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()
    ticket: ValidatedSelect | None = None
    context_receipt: HarnessContextRequest | None = None
    scope: RowScopeKind | None = None


def _diagnostic(exc: BaseException, reason: ReasonCode) -> Diagnostic:
    sqlstate = getattr(exc, "pgcode", None)
    return Diagnostic(
        reason.value, f"{type(exc).__module__}.{type(exc).__qualname__}: {exc}",
        sqlstate if isinstance(sqlstate, str) else None,
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )


def _attempted_input(persona: object, question: object, as_of_date: object, mode: object) -> Mapping[str, object]:
    """Trace primitive attempted fields; never call repr on an arbitrary object."""
    values: dict[str, object] = {
        "persona": persona if type(persona) is str else None,
        "question": question if type(question) is str else None,
        "as_of_date": as_of_date.isoformat() if type(as_of_date) is date else None,
        "mode": mode.value if type(mode) is ExecutionMode else None,
    }
    if type(persona) is Persona:
        values.update({
            "persona": persona.display_name, "principal_id": persona.principal_id,
            "business_role": persona.business_role, "login_role": persona.login_role,
        })
    return values


def _validate_request(
    runtime: _PipelineRuntime, persona: Persona | str, question: str,
    as_of_date: date, mode: ExecutionMode,
) -> InputRequest:
    selected = runtime.personas.resolve(persona)
    try:
        request = InputRequest(selected, question, as_of_date, mode)
        if len(question.encode("utf-8", errors="strict")) > _MAX_QUESTION_BYTES:
            raise ValueError("Question exceeds the source-defined input byte bound.")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise InvalidRequestError("An explicit persona, nonempty bounded question, date and defined mode are required.") from exc
    return request


def _require_profile(
    runtime: _PipelineRuntime, request: InputRequest, invocation: _HarnessInvocation | None,
) -> int:
    if invocation is None:
        if runtime.harness is not None or runtime.production_executor is None or request.mode is not ExecutionMode.FULL:
            raise HarnessSafetyStopError("Persona requests require the production FULL path.")
        return 2
    if (
        type(invocation) is not _HarnessInvocation or invocation.seal is not _HARNESS_SEAL
        or invocation.runtime is not runtime or runtime.harness is None
        or runtime.production_executor is not None or invocation.mode is not request.mode
        or type(invocation.prompt_version) is not int
    ):
        raise HarnessSafetyStopError("An issued isolated harness profile is required.")
    if invocation.prompt_version == 1 and request.mode is ExecutionMode.UNCONTROLLED:
        return 1
    if invocation.prompt_version == 2 and request.mode in {
        ExecutionMode.FULL, ExecutionMode.NO_PROMPT_FILTER, ExecutionMode.NO_VALIDATOR,
    }:
        return 2
    raise HarnessSafetyStopError("This prompt-version/mode combination has no defined harness profile.")


class _RequestCancelledError(StarkT2SQLError):
    """Explicit cancellation has no invented timeout/token-cap reason code."""

    def __init__(self, layer: StoppingLayer) -> None:
        super().__init__("The local caller cancelled the request; further submission/output is suppressed.")
        self.stopping_layer = layer
        self.cancelled = True
        self.failure_class = FailureClass.RUNTIME


def _require_not_cancelled(cancel: Event | None, layer: StoppingLayer) -> None:
    if cancel is not None and cancel.is_set():
        # Cancellation is not elapsed-time timeout or token-cap truncation.
        raise _RequestCancelledError(layer)


def _perform(
    runtime: _PipelineRuntime, request: InputRequest, work: _Work,
    invocation: _HarnessInvocation | None, cancel: Event | None,
) -> tuple[OutcomeStatus, StoppingLayer, ReasonCode]:
    version = _require_profile(runtime, request, invocation)
    work.fingerprints = ArtifactFingerprints(
        dataset=runtime.personas.fixture_dump_sha256, prompt=runtime.template.sha256,
        policy=runtime.matrix.sha256, semantic_catalog=runtime.catalog.sha256,
    )
    work.metadata.update({
        "template_sha256": runtime.template.sha256,
        "model_sha256": runtime.client.service.model_sha256,
        "llama_cpp_build": runtime.client.service.llama_cpp_build,
        "launcher_sha256": runtime.client.service.launcher_sha256,
        "measurement_sha256": runtime.client.measurement_sha256,
        "seed": runtime.client.decoding.seed, "max_tokens": runtime.client.decoding.max_tokens,
        "prompt_version": version, "scored": True, "cancelled": False,
    })
    _require_not_cancelled(cancel, work.stage)
    work.stage = StoppingLayer.CONTEXT
    context_started = monotonic()
    try:
        # Resolve vocabulary for v2 semantic modes; v1 UNCONTROLLED baseline has no semantic layer.
        if version != 1 and runtime.catalog is not None:
            resolution = resolve_question(
                request.question, runtime.catalog, runtime.matrix, runtime.snapshot, request.persona.business_role,
            )
            if resolution.status is ResolutionStatus.CLARIFICATION_REQUIRED:
                work.clarification = resolution.clarification
                return OutcomeStatus.CLARIFICATION_REQUIRED, StoppingLayer.CONTEXT, ReasonCode.CLARIFICATION_REQUIRED
        if invocation is None:
            compiled = build_context(request, runtime.snapshot, runtime.catalog, runtime.matrix)
        else:
            harness = runtime.harness
            if harness is None:
                raise HarnessSafetyStopError("The isolated harness context capability is unavailable.")
            # Existing authority performs clone audits before any full context
            # may leave its boundary. No candidate SQL is used for these audits.
            work.context_receipt = harness.context_authority.issue(request, prompt_version=version)
            if version == 1:
                compiled = build_harness_context(
                    harness.context_authority, work.context_receipt, runtime.snapshot, runtime.matrix,
                    baseline=harness.baseline,
                )
            else:
                compiled = build_harness_context(
                    harness.context_authority, work.context_receipt, runtime.snapshot, runtime.matrix,
                    catalog=runtime.catalog,
                )
            work.context_receipt = None
        work.fingerprints = replace(
            work.fingerprints, filtered_ddl=compiled.ddl_sha256, semantic=compiled.semantic_sha256,
            semantic_catalog=compiled.semantic_catalog_sha256,
        )
        prompt = build_prompt(runtime.template, compiled)
        work.metadata["rendered_prompt_sha256"] = prompt.rendered_sha256
    finally:
        work.timings = replace(work.timings, context_ms=(monotonic() - context_started) * 1000.0)

    _require_not_cancelled(cancel, work.stage)
    work.stage = StoppingLayer.MODEL
    generation_started = monotonic()
    try:
        generated = runtime.client.generate(prompt, cancel_event=cancel)
        work.raw_output = generated.raw_output
        work.metadata.update({
            "finish_reason": generated.finish_reason, "token_count": generated.tokens_predicted,
            "scored": generated.scored,
        })
        if not generated.scored:
            raise ModelGenerationError("An unscored warmup cannot become an answer or measured case.")
    except StarkT2SQLError as exc:
        work.raw_output = getattr(exc, "raw_output", work.raw_output)
        failure = getattr(exc, "failure_class", None)
        if failure is not None:
            work.metadata["failure_class"] = failure.value
        native_response = getattr(exc, "raw_response", None)
        if isinstance(native_response, str):
            work.diagnostics += (Diagnostic("MODEL_NATIVE_RESPONSE", native_response),)
        raise
    finally:
        work.timings = replace(work.timings, generation_ms=(monotonic() - generation_started) * 1000.0)

    _require_not_cancelled(cancel, work.stage)
    work.stage = StoppingLayer.EXTRACTION
    extraction_started = monotonic()
    try:
        # The existing FR-4.7 extractor separately refuses token-cap output;
        # elapsed timeout is already a distinct typed client failure.
        work.extracted_sql = extract_sql(generated)
    except StarkT2SQLError as exc:
        failure = getattr(exc, "failure_class", None)
        if failure is not None:
            work.metadata["failure_class"] = failure.value
        raise
    finally:
        work.timings = replace(work.timings, extraction_ms=(monotonic() - extraction_started) * 1000.0)

    _require_not_cancelled(cancel, work.stage)
    if request.mode in {ExecutionMode.FULL, ExecutionMode.NO_PROMPT_FILTER}:
        work.stage = StoppingLayer.VALIDATOR
        validation_started = monotonic()
        try:
            work.ticket = runtime.validation_authority.review(work.extracted_sql, request.persona)
            work.regenerated_sql = work.ticket.regenerated_sql
        except StarkT2SQLError as exc:
            rule = getattr(exc, "validation_rule_code", None)
            if rule is not None:
                work.metadata["validator_rule"] = rule.value if hasattr(rule, "value") else str(rule)
            raise
        finally:
            work.timings = replace(work.timings, validation_ms=(monotonic() - validation_started) * 1000.0)

    _require_not_cancelled(cancel, work.stage)
    work.stage = StoppingLayer.DATABASE if invocation is None else StoppingLayer.HARNESS
    if invocation is None:
        executor = runtime.production_executor
        if executor is None or work.ticket is None:
            raise MissingDependencyError("The restricted executor or authorization receipt is unavailable.")
        result = executor.execute(request.persona, work.ticket, mode=ExecutionMode.FULL)
    else:
        harness = runtime.harness
        if harness is None:
            raise HarnessSafetyStopError("The isolated executor is unavailable.")
        # Every mode still goes through the existing reviewed harness safety
        # gate. Unsafe UNCONTROLLED candidates stop before candidate submission.
        candidate = work.regenerated_sql if work.ticket is not None else work.extracted_sql
        result = harness.executor.execute(
            request.persona, candidate, mode=request.mode, validation_ticket=work.ticket,
        )
    work.execution = result
    work.ticket = None
    if work.regenerated_sql is None and result.executed_sql is not None:
        # In ablations only the executor can establish safety-regenerated text.
        work.regenerated_sql = result.executed_sql
    work.timings = replace(work.timings, database_ms=result.timings.database_ms)
    work.diagnostics += result.diagnostics
    work.metadata["cancelled"] = result.cancelled
    # The existing executor owns cancellation of a submitted statement through
    # its bounded client/server deadlines. An external event arriving during
    # that bounded transaction also withholds its result after cleanup settles.
    _require_not_cancelled(cancel, StoppingLayer.DATABASE if result.executed_sql is not None else work.stage)
    # Cap+one, SQLSTATE mapping and transaction cancellation are inherited from
    # the sole existing execution boundary, not duplicated in this module.
    if request.mode is ExecutionMode.UNCONTROLLED:
        work.scope = RowScopeKind.ALL
    else:
        role_policy = runtime.matrix.role(request.persona.business_role)
        sql_for_scope = (result.executed_sql or work.regenerated_sql or work.extracted_sql or "").lower()
        import re as _re
        referenced = {
            tbl for tbl in role_policy.tables
            if _re.search(r"(?<!\w)" + _re.escape(tbl.lower()) + r"(?!\w)", sql_for_scope)
        }
        if "leave_balances" in referenced and "leave_balances" in role_policy.tables:
            work.scope = role_policy.tables["leave_balances"].row_scope
        elif "employees" in referenced and "employees" in role_policy.tables:
            work.scope = role_policy.tables["employees"].row_scope
        elif referenced:
            work.scope = RowScopeKind.ALL
        else:
            work.scope = role_policy.tables["employees"].row_scope
    return result.status, result.stopping_layer, result.reason_code


def _outcome(
    request: InputRequest, request_id: str, row_cap: int, work: _Work,
    status: OutcomeStatus, layer: StoppingLayer, reason: ReasonCode, *, started: float,
) -> Outcome:
    result = work.execution
    answered = status is OutcomeStatus.ANSWERED and result is not None
    return Outcome(
        status, layer, reason, RequestContext(request, request_id), row_cap,
        columns=result.columns if answered else (), rows=result.rows if answered else (),
        truncated=result.truncated if answered else False,
        raw_output=work.raw_output, extracted_sql=work.extracted_sql,
        regenerated_sql=work.regenerated_sql, executed_sql=result.executed_sql if result is not None else None,
        timings=replace(work.timings, total_ms=(monotonic() - started) * 1000.0),
        fingerprints=work.fingerprints, diagnostics=work.diagnostics,
        clarification=work.clarification if status is OutcomeStatus.CLARIFICATION_REQUIRED else None,
        row_scope=work.scope if answered else None,
    )


def answer(
    persona: Persona | str, question: str, as_of_date: date, mode: ExecutionMode = ExecutionMode.FULL,
) -> Outcome:
    """Canonical request function; modes are enums, never coerced from strings.

    UI callers use PersonaApplication.answer with FULL fixed in source. Local
    evaluation callers use HarnessApplication.answer with a clone-bound scoped
    invocation. Direct calls without that capability cannot obtain an ablation.
    One internal event is attempted per invocation, including malformed input
    and cancellation; log failure suppresses an ordinary successful response.
    """
    started = monotonic()
    request_id = uuid4().hex
    work = _Work()
    runtime = _ACTIVE_RUNTIME.get()
    invocation = _ACTIVE_HARNESS.get()
    cancel = _ACTIVE_CANCEL.get()
    writer = runtime.trace if runtime is not None else TraceWriter(PROJECT_ROOT)
    request: InputRequest | None = None
    outcome: Outcome | None = None
    error: BaseException | None = None
    acquired = _REQUEST_LOCK.acquire(blocking=False)
    try:
        if not acquired:
            if runtime is not None and type(mode) is ExecutionMode:
                request = _validate_request(runtime, persona, question, as_of_date, mode)
            raise ModelGenerationError("A request already owns the process single-flight guard.")
        if type(mode) is not ExecutionMode:
            raise InvalidRequestError("Request modes must be source-selected enums; text coercion is unavailable.")
        if (
            type(as_of_date) is not date or not isinstance(question, str) or not question.strip()
            or type(persona) not in {Persona, str}
        ):
            raise InvalidRequestError("An explicit persona selection, nonempty question and date are required.")
        if runtime is None:
            if mode is not ExecutionMode.FULL or invocation is not None:
                raise HarnessSafetyStopError("A separate isolated harness capability is required before selecting an ablation.")
            work.stage = StoppingLayer.CONFIGURATION
            runtime = load_persona_runtime()._runtime
            writer = runtime.trace
        work.stage = StoppingLayer.INPUT
        request = _validate_request(runtime, persona, question, as_of_date, mode)
        if cancel is not None and not isinstance(cancel, Event):
            raise InvalidRequestError("Cancellation must use an explicit local Event.")
        status, layer, reason = _perform(runtime, request, work, invocation, cancel)
        outcome = _outcome(request, request_id, runtime.config.limits.output_row_cap, work, status, layer, reason, started=started)
        work.stage = StoppingLayer.RESPONSE
        # Require the shared public cell vocabulary before claiming an answer
        # in a trace. Interval/driver-specific objects cannot reach UI rendering
        # by silently using repr or a generic JSON fallback.
        outcome.to_safe_response().to_dict()
    except Exception as exc:
        error = exc
        if getattr(exc, "cancelled", False) is True:
            work.metadata["cancelled"] = True
        failure_class = getattr(exc, "failure_class", None)
        if type(failure_class) is FailureClass:
            work.metadata["failure_class"] = failure_class.value
        if isinstance(exc, StarkT2SQLError):
            status, layer, reason = exc.status, exc.stopping_layer, exc.reason_code
        else:
            status, layer, reason = OutcomeStatus.ERROR, work.stage, ReasonCode.INTERNAL_ERROR
        work.diagnostics += (_diagnostic(exc, reason),)
        if request is not None and runtime is not None:
            outcome = _outcome(request, request_id, runtime.config.limits.output_row_cap, work, status, layer, reason, started=started)
    except BaseException as exc:
        # Keep interruption semantics, but release receipts/flight and record a
        # private event first. External caller cancellation reaches the client
        # watchdog; the DB executor owns its statement/client deadline cleanup.
        error = exc
        if isinstance(cancel, Event):
            cancel.set()
        work.metadata["cancelled"] = True
        work.diagnostics += (_diagnostic(exc, ReasonCode.INTERNAL_ERROR),)
        if request is not None and runtime is not None:
            outcome = _outcome(
                request, request_id, runtime.config.limits.output_row_cap, work,
                OutcomeStatus.ERROR, work.stage, ReasonCode.INTERNAL_ERROR, started=started,
            )
    finally:
        try:
            if runtime is not None and work.ticket is not None:
                runtime.validation_authority.discard(work.ticket)
            if runtime is not None and runtime.harness is not None and work.context_receipt is not None:
                runtime.harness.context_authority.discard(work.context_receipt)
        finally:
            try:
                writer.write_request(
                    outcome, request_id=request_id, attempted_input=_attempted_input(persona, question, as_of_date, mode),
                    metadata=work.metadata, diagnostic=work.diagnostics[-1] if outcome is None and work.diagnostics else None,
                    attempted_status=error.status if isinstance(error, StarkT2SQLError) else OutcomeStatus.ERROR,
                    attempted_stopping_layer=error.stopping_layer if isinstance(error, StarkT2SQLError) else work.stage,
                    attempted_elapsed_ms=(monotonic() - started) * 1000.0,
                )
            except Exception as trace_error:
                # Never retry an append whose partial completion is unknown.
                # No fabricated trace is claimed; the private Outcome retains
                # its original execution facts but public result data is hidden.
                if outcome is not None:
                    outcome = replace(
                        outcome, status=OutcomeStatus.ERROR, stopping_layer=StoppingLayer.RESPONSE,
                        reason_code=ReasonCode.INTERNAL_ERROR, columns=(), rows=(), truncated=False,
                        clarification=None, row_scope=None,
                        diagnostics=outcome.diagnostics + (_diagnostic(trace_error, ReasonCode.SOURCE_READ_ERROR),),
                    )
                elif error is None or isinstance(error, Exception):
                    error = trace_error
            finally:
                if acquired:
                    _REQUEST_LOCK.release()
    if error is not None and not isinstance(error, Exception):
        raise error
    if outcome is not None:
        return outcome
    if isinstance(error, StarkT2SQLError):
        raise error
    raise InvalidRequestError("The request could not establish a valid local runtime and typed input.") from error
