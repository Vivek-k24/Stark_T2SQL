"""Harness-only FR-9.5 profiles over the existing constrained executors.

Questions use canonical answer(), including FULL on the clone. Direct-SQL
benchmarks are the explicitly requested no-model lane over the same existing
validator receipts and EvaluationExecutor, never a persona production API.
No administrator or bare SQL connection may replace the clone capability.
Safety stops remain unexecuted and are not attributed to DB/validator blocks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from threading import Event
from time import monotonic
import traceback
from uuid import uuid4

from ..context.builder import build_harness_context
from ..contracts import (
    ArtifactFingerprints, Diagnostic, ExecutionMode, InputRequest, Outcome, OutcomeStatus,
    Persona, ReasonCode, RequestContext, RequestTimings, RowScopeKind, StoppingLayer,
)
from ..db.connections import EvaluationConnectionSource
from ..db.executor import EvaluationExecutor, ValidatedSelect, ValidationAuthority
from ..errors import ConfigurationError, HarnessSafetyStopError, StarkT2SQLError
from ..inference.client import warmup
from ..inference.prompt_builder import build_prompt
from ..pipeline.orchestrator import HarnessApplication
from ..pipeline.answer import _REQUEST_LOCK
from ..pipeline.trace import TraceWriter
from ..security.validator import HarnessSafetyReviewer, ParserReviewApproval, ReviewedSQLValidator
from ..semantic.contracts import ResolutionStatus
from ..semantic.resolver import resolve_question
from .cases import Case
from .records import WarmupRecord


@dataclass(frozen=True, slots=True)
class ModeProfile:
    mode: ExecutionMode
    prompt_version: int

    def __post_init__(self) -> None:
        if type(self.mode) is not ExecutionMode or type(self.prompt_version) is not int:
            raise ConfigurationError("Evaluation profiles must be explicit typed source metadata.")
        valid = (self.mode is ExecutionMode.UNCONTROLLED and self.prompt_version == 1) or (
            self.mode in {ExecutionMode.FULL, ExecutionMode.NO_PROMPT_FILTER, ExecutionMode.NO_VALIDATOR} and self.prompt_version == 2
        )
        if not valid:
            raise HarnessSafetyStopError("The requested ablation/prompt version has no defined profile.")


def all_mode_profiles() -> tuple[ModeProfile, ...]:
    return (
        ModeProfile(ExecutionMode.FULL, 2), ModeProfile(ExecutionMode.NO_PROMPT_FILTER, 2),
        ModeProfile(ExecutionMode.NO_VALIDATOR, 2), ModeProfile(ExecutionMode.UNCONTROLLED, 1),
    )


@dataclass(frozen=True, slots=True)
class _DirectComponents:
    source: EvaluationConnectionSource
    executor: EvaluationExecutor


@dataclass(frozen=True, slots=True)
class _DirectRuntime:
    harness: _DirectComponents
    validation_authority: ValidationAuthority
    trace: TraceWriter

    @property
    def config(self):
        return self.harness.source.config

    @property
    def matrix(self):
        return self.harness.source.matrix

    @property
    def personas(self):
        return self.harness.source.personas


class AblationHarness:
    """Small trusted evaluator facade; never imported by the normal UI."""

    def __init__(
        self, application: HarnessApplication | None = None, *,
        source: EvaluationConnectionSource | None = None, parser_approval: ParserReviewApproval | None = None,
    ) -> None:
        if application is not None:
            if type(application) is not HarnessApplication or application._runtime.harness is None or source is not None:
                raise ConfigurationError("Model ablations require the separately composed actual clone harness.")
            self._application, self._runtime = application, application._runtime
        else:
            # E3's deterministic direct-SQL lane does not require a model,
            # template, warmup or model file merely to observe DB/validator.
            if type(source) is not EvaluationConnectionSource:
                raise ConfigurationError("Direct-only evaluation requires the exact isolated clone source.")
            validator = ReviewedSQLValidator(source.matrix, approval=parser_approval)
            authority = ValidationAuthority(validator, policy_fingerprint=source.matrix.sha256, personas=source.personas)
            executor = EvaluationExecutor(
                source, safety_reviewer=HarnessSafetyReviewer(source.matrix, approval=parser_approval),
                validation_authority=authority,
            )
            self._application = None
            self._runtime = _DirectRuntime(_DirectComponents(source, executor), authority, TraceWriter(source.config.paths.root))

    @property
    def model_available(self) -> bool:
        return self._application is not None

    @property
    def source(self) -> EvaluationConnectionSource:
        return self._runtime.harness.source

    def question(self, case: Case, profile: ModeProfile, *, cancel_event: Event | None = None) -> Outcome:
        if type(case) is not Case or case.question is None or type(profile) is not ModeProfile:
            raise ConfigurationError("A model case needs an actual question and typed harness profile.")
        if self._application is None:
            raise ConfigurationError("This direct-only harness has no configured local model capability.")
        return self._application.answer(
            self._runtime.personas.resolve(case.persona), case.question, case.as_of_date,
            profile.mode, prompt_version=profile.prompt_version, cancel_event=cancel_event,
        )

    def warmup(self, case: Case, profile: ModeProfile, *, cancel_event: Event | None = None) -> WarmupRecord:
        """Future helper uses an actual TUNING case supplied by the runner guard."""
        if type(case) is not Case or case.question is None or type(profile) is not ModeProfile:
            raise ConfigurationError("Warmup requires an actual guarded tuning question.")
        if self._application is None:
            raise ConfigurationError("A direct-only evaluation has no model warmup.")
        runtime, components = self._runtime, self._runtime.harness
        if components is None:
            raise HarnessSafetyStopError("The isolated warmup capability is unavailable.")
        request = InputRequest(runtime.personas.resolve(case.persona), case.question, case.as_of_date, profile.mode)
        resolution = resolve_question(case.question, runtime.catalog, runtime.matrix, runtime.snapshot, request.persona.business_role)
        if resolution.status is not ResolutionStatus.RESOLVED:
            raise ConfigurationError("The selected warmup case requires clarification; use an actual resolved tuning input.")
        if not _REQUEST_LOCK.acquire(blocking=False):
            raise HarnessSafetyStopError("Another request owns the authoritative process flight guard.")
        receipt = None
        try:
            receipt = components.context_authority.issue(request, prompt_version=profile.prompt_version)
            compiled = build_harness_context(
                components.context_authority, receipt, runtime.snapshot, runtime.matrix,
                baseline=components.baseline if profile.prompt_version == 1 else None,
                catalog=runtime.catalog if profile.prompt_version == 2 else None,
            )
            generated = warmup(runtime.client, build_prompt(runtime.template, compiled), cancel_event=cancel_event)
        finally:
            try:
                if receipt is not None:
                    components.context_authority.discard(receipt)
            finally:
                _REQUEST_LOCK.release()
        return WarmupRecord(True, False, generated.generation_ms, generated.tokens_predicted, case.id)

    def direct(self, case: Case, profile: ModeProfile, *, never_execute: bool = False) -> Outcome:
        """No-model case, still mandatory clone/AST/function safety before SQL.

        never_execute=True can only restrict execution further. False grants
        nothing: the existing mandatory safety review remains the final gate.
        Even NO_VALIDATOR currently retains role-table checks in that gate;
        record any resulting safety stop rather than claiming DB enforcement.
        """
        if type(case) is not Case or case.sql is None or type(profile) is not ModeProfile or type(never_execute) is not bool:
            raise ConfigurationError("Direct evaluation needs typed actual SQL source and profile.")
        runtime, components = self._runtime, self._runtime.harness
        if components is None:
            raise HarnessSafetyStopError("The separate isolated direct-SQL harness is unavailable.")
        selected = runtime.personas.resolve(case.persona)
        request = InputRequest(selected, case.sql, case.as_of_date, profile.mode)
        context = RequestContext(request, uuid4().hex)
        fingerprints = ArtifactFingerprints(dataset=runtime.personas.fixture_dump_sha256, policy=runtime.matrix.sha256)
        ticket: ValidatedSelect | None = None
        started, validation_ms = monotonic(), None
        outcome: Outcome | None = None
        acquired = _REQUEST_LOCK.acquire(blocking=False)
        try:
            if never_execute or not acquired:
                raise HarnessSafetyStopError("The prepared case is unexecutable or another direct audit owns the single-flight guard.")
            if profile.mode in {ExecutionMode.FULL, ExecutionMode.NO_PROMPT_FILTER}:
                validation_started = monotonic()
                try:
                    ticket = runtime.validation_authority.review(case.sql, selected)
                finally:
                    validation_ms = (monotonic() - validation_started) * 1000.0
            candidate = ticket.regenerated_sql if ticket is not None else case.sql
            result = components.executor.execute(selected, candidate, mode=profile.mode, validation_ticket=ticket)
            regenerated = ticket.regenerated_sql if ticket is not None else result.executed_sql
            ticket = None
            outcome = Outcome(
                result.status, result.stopping_layer, result.reason_code, context, result.row_cap,
                columns=result.columns, rows=result.rows, truncated=result.truncated,
                extracted_sql=case.sql, regenerated_sql=regenerated, executed_sql=result.executed_sql,
                timings=replace(result.timings, total_ms=(monotonic() - started) * 1000.0, validation_ms=validation_ms),
                fingerprints=fingerprints, diagnostics=result.diagnostics,
                row_scope=RowScopeKind.ALL if profile.mode is ExecutionMode.UNCONTROLLED else runtime.matrix.role(selected.business_role).tables["employees"].row_scope,
            )
        except Exception as exc:
            if isinstance(exc, StarkT2SQLError):
                status, layer, reason = exc.status, exc.stopping_layer, exc.reason_code
            else:
                status, layer, reason = OutcomeStatus.ERROR, StoppingLayer.HARNESS, ReasonCode.INTERNAL_ERROR
            state = getattr(exc, "pgcode", None)
            outcome = Outcome(
                status, layer, reason, context, runtime.config.limits.output_row_cap,
                extracted_sql=case.sql, fingerprints=fingerprints,
                timings=RequestTimings(total_ms=(monotonic() - started) * 1000.0, validation_ms=validation_ms),
                diagnostics=(Diagnostic(reason.value, str(exc), state if isinstance(state, str) else None, "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))),),
            )
        finally:
            try:
                if ticket is not None:
                    runtime.validation_authority.discard(ticket)
                if outcome is not None:
                    # Direct source has its own one event; question() already
                    # records its event through canonical answer(), so do not
                    # write a second event for the model path.
                    try:
                        runtime.trace.write_request(outcome, request_id=context.request_id, metadata={"prompt_version": profile.prompt_version, "scored": True})
                    except Exception as exc:
                        outcome = replace(
                            outcome, status=OutcomeStatus.ERROR, stopping_layer=StoppingLayer.RESPONSE,
                            reason_code=ReasonCode.INTERNAL_ERROR, columns=(), rows=(), truncated=False,
                            diagnostics=outcome.diagnostics + (Diagnostic("TRACE_UNAVAILABLE", str(exc)),),
                        )
            finally:
                if acquired:
                    _REQUEST_LOCK.release()
        if outcome is None:
            raise HarnessSafetyStopError("The direct audit was interrupted before an outcome was available.")
        return outcome


def require_run_change_discipline(previous: object, current: object) -> None:
    """Future actual-record comparison, never a fabricated baseline decision."""
    from .records import RunRecord

    if type(previous) is not RunRecord or type(current) is not RunRecord:
        raise ConfigurationError("Change discipline requires actual prior/current run records.")
    model_changed = previous.fingerprints.model_gguf_sha256 != current.fingerprints.model_gguf_sha256
    prompt_changed = (
        previous.fingerprints.prompt_template_sha256 != current.fingerprints.prompt_template_sha256
        or previous.settings.prompt_version != current.settings.prompt_version
    )
    if model_changed and prompt_changed:
        raise ConfigurationError("Changing model and prompt together is not a controlled comparison; declare a separate new baseline.")
    if model_changed and (not current.settings.baseline_reference or current.settings.baseline_reference == previous.settings.baseline_reference):
        raise ConfigurationError("A model change requires its own explicit new baseline/template record.")
