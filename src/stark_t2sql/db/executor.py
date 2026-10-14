"""Future FR-6/FR-8 execution boundary; this module is source only.

Prompt 3 owns the reviewed AST validator and SQL-function safety policy. Neither
is implemented here. Missing reviewers fail closed. Receipt seals distinguish
source-controlled reviewer decisions from SQL strings supplied by a caller;
they are process-local capabilities, not authentication or cryptographic proof
against arbitrary Python code running inside the process.

The future answer() pipeline is the sole caller for persona and harness flows.
These lower-level components produce private ExecutionResult records. The
pipeline must use contracts.Outcome.to_safe_response(), never serialize these
records into a persona view. Administrator sources cannot enter either path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import math
from threading import Event, Lock, Timer
from time import monotonic
import traceback
from typing import Protocol, cast

from ..contracts import (
    ColumnMetadata,
    Diagnostic,
    ExecutionMode,
    OutcomeStatus,
    Persona,
    ReasonCode,
    RequestTimings,
    ResultRow,
    StoppingLayer,
)
from ..errors import (
    ConfigurationError,
    DatabaseExecutionError,
    HarnessSafetyStopError,
    MissingDependencyError,
    SQLValidationError,
    StarkT2SQLError,
    StatementTimeoutError,
)
from .connections import EvaluationConnectionSource, RuntimeConnections
from .persona import PersonaRegistry


def _sql_hash(sql: str) -> str:
    return sha256(sql.encode("utf-8")).hexdigest()


def _require_hash(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ConfigurationError(f"{label} must be an actual lowercase SHA-256 fingerprint.")


@dataclass(frozen=True, slots=True)
class SelectReview:
    """A trusted future validator's decision after all FR-5 rules succeed.

    The reviewer must parse one statement, reject command/write nodes throughout
    the tree, enforce permitted table/schema and reviewed function policy, regenerate PostgreSQL
    SELECT-family SQL, and establish the FR-5.7 parse/regeneration contract.
    FR-5.8 leaves column enforcement to PostgreSQL grants; wall-clock lint and
    cost estimation also do not belong to this validator. This type and nonempty
    text alone establish none of those properties.
    """

    regenerated_sql: str
    principal_id: int
    login_role: str
    business_role: str
    policy_fingerprint: str
    validator_revision: str


class ReviewedSQLValidator(Protocol):
    """Implemented and human-reviewed in Prompt 3, with no permissive fallback."""

    def review_select(
        self, candidate_sql: str, *, persona: Persona, policy_fingerprint: str
    ) -> SelectReview:
        """Return a reviewed decision, or raise SQLValidationError on rejection."""
        ...


@dataclass(frozen=True, slots=True)
class ValidatedSelect:
    """One-use SQL receipt; a freely constructed instance has no issuer seal."""

    regenerated_sql: str
    principal_id: int
    login_role: str
    business_role: str
    policy_fingerprint: str
    sql_fingerprint: str
    validator_revision: str
    _issuer: object = field(repr=False, compare=False)
    _nonce: object = field(repr=False, compare=False)


class ValidationAuthority:
    """Issue receipts only through an injected, source-controlled AST reviewer.

    Configuration must inject the reviewed Prompt 3 implementation. A model,
    HTTP payload or persona input may not select or supply an implementation.
    There is deliberately no string-to-approved-query convenience constructor.
    """

    def __init__(
        self,
        reviewed_validator: ReviewedSQLValidator | None,
        *,
        policy_fingerprint: str,
        personas: PersonaRegistry,
    ) -> None:
        _require_hash(policy_fingerprint, "access-matrix fingerprint")
        if type(personas) is not PersonaRegistry:
            raise ConfigurationError("A fixture-resolved PersonaRegistry is required.")
        self.policy_fingerprint = policy_fingerprint
        self.personas = personas
        self._reviewer = reviewed_validator
        self._seal = object()
        self._issued: dict[object, ValidatedSelect] = {}
        self._lock = Lock()

    def review(self, candidate_sql: str, persona: Persona) -> ValidatedSelect:
        selected = self.personas.resolve(persona)
        if self._reviewer is None:
            raise MissingDependencyError("The reviewed Prompt 3 SQL validator is unavailable.")
        if not isinstance(candidate_sql, str) or not candidate_sql.strip():
            raise SQLValidationError("A nonempty candidate is required for AST review.")
        decision = self._reviewer.review_select(
            candidate_sql, persona=selected, policy_fingerprint=self.policy_fingerprint
        )
        if type(decision) is not SelectReview:
            raise SQLValidationError("The validator returned no typed SELECT review decision.")
        expected = (
            selected.principal_id,
            selected.login_role,
            selected.business_role,
            self.policy_fingerprint,
        )
        observed = (
            decision.principal_id,
            decision.login_role,
            decision.business_role,
            decision.policy_fingerprint,
        )
        if observed != expected:
            raise SQLValidationError("The validator decision is bound to a different identity or policy.")
        if (
            not isinstance(decision.regenerated_sql, str)
            or not decision.regenerated_sql.strip()
            or not isinstance(decision.validator_revision, str)
            or not decision.validator_revision.strip()
        ):
            raise SQLValidationError("The validator decision lacks regenerated SQL or its revision.")
        receipt = ValidatedSelect(
            regenerated_sql=decision.regenerated_sql,
            principal_id=selected.principal_id,
            login_role=selected.login_role,
            business_role=selected.business_role,
            policy_fingerprint=self.policy_fingerprint,
            sql_fingerprint=_sql_hash(decision.regenerated_sql),
            validator_revision=decision.validator_revision,
            _issuer=self._seal,
            _nonce=object(),
        )
        with self._lock:
            self._issued[receipt._nonce] = receipt
        return receipt

    def _consume(self, receipt: ValidatedSelect, persona: Persona, policy_fingerprint: str) -> str:
        if type(receipt) is not ValidatedSelect:
            raise SQLValidationError("Execution requires an issued validator receipt.")
        with self._lock:
            issued = self._issued.pop(receipt._nonce, None)
        if issued is not receipt or receipt._issuer is not self._seal:
            raise SQLValidationError("The validator receipt is foreign, altered, or already consumed.")
        selected = self.personas.resolve(persona)
        if (
            receipt.policy_fingerprint != policy_fingerprint
            or receipt.policy_fingerprint != self.policy_fingerprint
            or receipt.principal_id != selected.principal_id
            or receipt.login_role != selected.login_role
            or receipt.business_role != selected.business_role
            or receipt.sql_fingerprint != _sql_hash(receipt.regenerated_sql)
        ):
            raise SQLValidationError("The validator receipt no longer matches SQL, policy, or persona.")
        return receipt.regenerated_sql

    def discard(self, receipt: ValidatedSelect) -> None:
        """Release an unused receipt when a later pipeline step stops the request."""
        if type(receipt) is not ValidatedSelect or receipt._issuer is not self._seal:
            raise SQLValidationError("An unused receipt belongs to a different issuer.")
        with self._lock:
            if self._issued.get(receipt._nonce) is receipt:
                del self._issued[receipt._nonce]


@dataclass(frozen=True, slots=True)
class HarnessSelectReview:
    """Typed decision from a future independent, reviewed harness safety gate.

    The gate must reject multiple statements, writes/commands anywhere in the
    AST, SELECT INTO, locking clauses, privileged objects and unsafe or mutable
    SQL functions. It must enforce a reviewed function policy even when ordinary
    authorization validation is ablated. Returning a bool, echoing a string or
    recognizing a SELECT prefix cannot implement this contract. UNCONTROLLED
    may read the fixture baseline but must retain these execution-safety rules.
    """

    regenerated_sql: str
    candidate_fingerprint: str
    mode: ExecutionMode
    principal_id: int
    policy_fingerprint: str
    clone_token: str
    fixture_dump_fingerprint: str
    safety_reviewer_revision: str


class HarnessSafetyReviewer(Protocol):
    """Future reviewed AST/function-policy dependency; this prompt does not supply it."""

    def review_candidate(
        self,
        candidate_sql: str,
        *,
        persona: Persona,
        mode: ExecutionMode,
        policy_fingerprint: str,
        clone_token: str,
        fixture_dump_fingerprint: str,
    ) -> HarnessSelectReview:
        """Return a safety-reviewed SELECT, or raise HarnessSafetyStopError."""
        ...


@dataclass(frozen=True, slots=True)
class _HarnessReceipt:
    """Internal single-call capability created after the trusted review callback."""

    sql: str
    sql_fingerprint: str
    persona: Persona
    mode: ExecutionMode
    policy_fingerprint: str
    clone_identity: tuple[str, str, str, str]
    reviewer_revision: str
    seal: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Private database component result, for assembly into the shared Outcome."""

    status: OutcomeStatus
    stopping_layer: StoppingLayer
    reason_code: ReasonCode
    row_cap: int
    columns: tuple[ColumnMetadata, ...] = ()
    rows: tuple[ResultRow, ...] = ()
    truncated: bool = False
    timings: RequestTimings = field(default_factory=RequestTimings)
    diagnostics: tuple[Diagnostic, ...] = ()
    sqlstate: str | None = None
    executed_sql: str | None = None
    cancelled: bool = False


def _failure_result(
    exc: Exception,
    *,
    row_cap: int,
    started: float,
    executed_sql: str | None = None,
    harness_safety_stop: bool = False,
    cancelled: bool = False,
) -> ExecutionResult:
    """Raw exceptions remain private; public consumers receive fixed enum codes."""
    sqlstate = getattr(exc, "pgcode", None)
    if not isinstance(sqlstate, str):
        sqlstate = None
    if harness_safety_stop:
        status, layer, reason = (
            OutcomeStatus.HARNESS_SAFETY_STOP,
            StoppingLayer.HARNESS,
            ReasonCode.HARNESS_SAFETY_STOP,
        )
    elif isinstance(exc, (TimeoutError, StatementTimeoutError)):
        status, layer, reason = (
            OutcomeStatus.TIMEOUT, StoppingLayer.DATABASE, ReasonCode.STATEMENT_TIMEOUT
        )
        cancelled = True
    elif sqlstate == "42501":
        status, layer, reason = (
            OutcomeStatus.BLOCKED_DB, StoppingLayer.DATABASE, ReasonCode.DB_PERMISSION_DENIED
        )
    elif sqlstate == "57014":
        status, layer, reason = (
            OutcomeStatus.TIMEOUT, StoppingLayer.DATABASE, ReasonCode.STATEMENT_TIMEOUT
        )
        cancelled = True
    elif sqlstate == "42601":
        status, layer, reason = (
            OutcomeStatus.MODEL_SQL_ERROR, StoppingLayer.DATABASE, ReasonCode.SQL_SYNTAX_ERROR
        )
    elif sqlstate in {"42P01", "42703", "42883"}:
        status, layer, reason = (
            OutcomeStatus.MODEL_SQL_ERROR, StoppingLayer.DATABASE, ReasonCode.UNKNOWN_DATABASE_OBJECT
        )
    elif isinstance(exc, StarkT2SQLError):
        status, layer, reason = exc.status, exc.stopping_layer, exc.reason_code
    else:
        status, layer, reason = (
            OutcomeStatus.ERROR, StoppingLayer.DATABASE, ReasonCode.DATABASE_ERROR
        )
    diagnostic = Diagnostic(
        code=reason.value,
        internal_detail=f"{type(exc).__module__}.{type(exc).__qualname__}: {exc}",
        sqlstate=sqlstate,
        traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )
    return ExecutionResult(
        status=status,
        stopping_layer=layer,
        reason_code=reason,
        row_cap=row_cap,
        timings=RequestTimings(database_ms=(monotonic() - started) * 1000.0),
        diagnostics=(diagnostic,),
        sqlstate=sqlstate,
        executed_sql=executed_sql,
        cancelled=cancelled,
    )


class _ClientDeadline:
    """Cancel an active transaction on timeout, with no reusable connection lease.

    Both allowed sources create fresh connections and always discard them. A
    timer racing with completion therefore cannot cancel a subsequent request.
    PostgreSQL statement timeout remains separately enforced on audited logins.
    """

    def __init__(self, connection: object, remaining_seconds: float, join_budget: float) -> None:
        self._connection = connection
        self._lock = Lock()
        self._active = True
        self._expired = Event()
        self._join_budget = join_budget
        self.cancel_error: Exception | None = None
        self._timer = Timer(max(0.0, remaining_seconds), self._cancel)
        self._timer.daemon = True

    def _cancel(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._expired.set()
        try:
            self._connection.cancel()
        except Exception as exc:
            self.cancel_error = exc

    def start(self) -> None:
        self._timer.start()

    def require_time(self) -> None:
        if self._expired.is_set():
            raise StatementTimeoutError("The executor client deadline cancelled the transaction.")

    def finish(self) -> None:
        with self._lock:
            self._active = False
        self._timer.cancel()
        self._timer.join(timeout=self._join_budget)
        if self._timer.is_alive():
            self._expired.set()
            self.cancel_error = StatementTimeoutError("The client cancellation call has not settled.")


class _ClientTransactionTimeout(StatementTimeoutError):
    """Retain an original database error and SQLSTATE when cancellation races it."""

    def __init__(self, original: Exception, *, cancellation: Exception | None, cleanup: Exception | None) -> None:
        self.pgcode = getattr(original, "pgcode", None)
        details = [f"Original transaction error: {type(original).__name__}: {original}"]
        if cancellation is not None:
            details.append(f"Client cancellation error: {type(cancellation).__name__}: {cancellation}")
        if cleanup is not None:
            details.append(f"Rollback error: {type(cleanup).__name__}: {cleanup}")
        super().__init__("\n".join(details))


def _timeout_seconds(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        raise ConfigurationError("The executor client timeout must be finite and positive.")
    return float(value)


def _transaction(
    connection: object,
    *,
    principal: Persona,
    switch_business_role: bool,
    approved_sql: str,
    row_cap: int,
    started: float,
    deadline: float,
    client_timeout_seconds: float,
    execution_record: list[str],
) -> ExecutionResult:
    """Shared transaction path; only callers with issued receipts can reach it."""
    # Driver dependency is imported only in a future runtime invocation.
    try:
        from psycopg2 import sql
    except ImportError as exc:
        raise MissingDependencyError("The future PostgreSQL driver is unavailable.") from exc
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise StatementTimeoutError("The executor deadline expired before candidate submission.")
    connection.readonly = True
    guard = _ClientDeadline(connection, remaining, client_timeout_seconds)
    guard.start()
    try:
        with connection.cursor() as cursor:
            guard.require_time()
            if switch_business_role:
                # This call precedes SET ROLE, while current_user is still the
                # persona login. The unrestricted clone login has no principal
                # scope and deliberately has no set_config privilege.
                cursor.execute(
                    "SELECT pg_catalog.set_config('app.principal_id', %s::text, true)",
                    (str(principal.principal_id),),
                )
                guard.require_time()
                cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(principal.business_role)))
            guard.require_time()
            execution_record.append(approved_sql)
            cursor.execute(approved_sql)
            if cursor.description is None:
                raise DatabaseExecutionError("A reviewed SELECT returned no result description.")
            columns = tuple(
                ColumnMetadata(name=column.name, nullable=column.null_ok)
                for column in cursor.description
            )
            fetched = cursor.fetchmany(row_cap + 1)
            rows = tuple(cast(ResultRow, tuple(row)) for row in fetched[:row_cap])
            truncated = len(fetched) > row_cap
            guard.require_time()
        connection.commit()
        guard.finish()
        guard.require_time()
        if monotonic() > deadline:
            raise StatementTimeoutError("The transaction completed after the executor deadline.")
        return ExecutionResult(
            status=OutcomeStatus.ANSWERED,
            stopping_layer=StoppingLayer.NONE,
            reason_code=ReasonCode.ANSWERED,
            row_cap=row_cap,
            columns=columns,
            rows=rows,
            truncated=truncated,
            timings=RequestTimings(database_ms=(monotonic() - started) * 1000.0),
            executed_sql=approved_sql,
        )
    except Exception as exc:
        guard.finish()
        # Rollback is attempted for a cancelled/failed transaction. The source
        # still closes this fresh connection even when rollback itself fails.
        rollback_error: Exception | None = None
        try:
            connection.rollback()
        except Exception as cleanup_exc:
            rollback_error = cleanup_exc
        if guard._expired.is_set() and (
            not isinstance(exc, StatementTimeoutError)
            or guard.cancel_error is not None
            or rollback_error is not None
        ):
            raise _ClientTransactionTimeout(
                exc, cancellation=guard.cancel_error, cleanup=rollback_error
            ) from exc
        if rollback_error is not None:
            # Keep the original SQLSTATE/status and attach cleanup to its private
            # diagnostic chain; no alternate connection is acquired or reused.
            raise exc from rollback_error
        raise


class ProductionExecutor:
    """Persona runtime component: exact business source, FULL and approved SQL only."""

    def __init__(
        self,
        source: RuntimeConnections,
        authority: ValidationAuthority,
        *,
        client_timeout_seconds: float | None = None,
    ) -> None:
        if type(source) is not RuntimeConnections or type(authority) is not ValidationAuthority:
            raise ConfigurationError("The production executor requires its audited business source and validator issuer.")
        if authority.personas is not source.personas or authority.policy_fingerprint != source.matrix.sha256:
            raise ConfigurationError("Executor policy and fixture persona registry differ from validator bindings.")
        self._source = source
        self._authority = authority
        self._timeout = _timeout_seconds(
            source.config.limits.statement_timeout_seconds
            if client_timeout_seconds is None else client_timeout_seconds
        )

    def execute(
        self,
        persona: Persona,
        ticket: ValidatedSelect,
        *,
        mode: ExecutionMode = ExecutionMode.FULL,
    ) -> ExecutionResult:
        started = monotonic()
        row_cap = self._source.config.limits.output_row_cap
        executed: list[str] = []
        try:
            if mode is not ExecutionMode.FULL:
                raise HarnessSafetyStopError("A production executor cannot execute an ablation mode.")
            selected = self._source.personas.resolve(persona)
            self._source.config.resource_budgets.require_database_budget_inputs()
            approved = self._authority._consume(ticket, selected, self._source.matrix.sha256)
            with self._source.connection(selected) as connection:
                return _transaction(
                    connection,
                    principal=selected,
                    switch_business_role=True,
                    approved_sql=approved,
                    row_cap=row_cap,
                    started=started,
                    deadline=started + self._timeout,
                    client_timeout_seconds=self._timeout,
                    execution_record=executed,
                )
        except Exception as exc:
            return _failure_result(
                exc, row_cap=row_cap, started=started,
                executed_sql=executed[-1] if executed else None,
            )


class EvaluationExecutor:
    """Harness component: actual isolated clone and reviewed execution safety.

    FULL and NO_PROMPT_FILTER retain ordinary authorization validation and a
    business identity on the clone. NO_VALIDATOR retains the clone's business
    role controls. UNCONTROLLED alone uses the dedicated broad SELECT baseline
    login, without adopting a business role. Every mode still needs the reviewed
    harness AST/function safety gate. This component does not implement an
    evaluation runner or permit administrators to submit generated statements.
    """

    def __init__(
        self,
        source: EvaluationConnectionSource,
        *,
        safety_reviewer: HarnessSafetyReviewer | None,
        validation_authority: ValidationAuthority | None = None,
        client_timeout_seconds: float | None = None,
    ) -> None:
        if type(source) is not EvaluationConnectionSource:
            raise ConfigurationError("The harness executor requires an audited disposable-clone source.")
        if validation_authority is not None and (
            type(validation_authority) is not ValidationAuthority
            or validation_authority.personas is not source.personas
            or validation_authority.policy_fingerprint != source.matrix.sha256
        ):
            raise ConfigurationError("Harness validator bindings differ from clone policy and personas.")
        self._source = source
        self._reviewer = safety_reviewer
        self._authority = validation_authority
        self._seal = object()
        self._timeout = _timeout_seconds(
            source.config.limits.statement_timeout_seconds
            if client_timeout_seconds is None else client_timeout_seconds
        )

    def _clone_identity(self) -> tuple[str, str, str, str]:
        provenance = self._source.provenance
        return (
            self._source.clone_alias,
            provenance.clone_database,
            provenance.clone_token,
            provenance.fixture_dump_sha256,
        )

    def _review(
        self, persona: Persona, candidate_sql: str, mode: ExecutionMode,
        ticket: ValidatedSelect | None,
    ) -> _HarnessReceipt:
        selected = self._source.personas.resolve(persona)
        if not isinstance(mode, ExecutionMode):
            raise HarnessSafetyStopError("An explicit defined evaluation mode is required.")
        if self._reviewer is None:
            raise HarnessSafetyStopError("The future reviewed harness AST/function safety gate is unavailable.")
        if not isinstance(candidate_sql, str) or not candidate_sql.strip():
            raise HarnessSafetyStopError("The harness has no candidate to review.")
        validated = mode in {ExecutionMode.FULL, ExecutionMode.NO_PROMPT_FILTER}
        if validated:
            if self._authority is None or ticket is None:
                raise HarnessSafetyStopError("This harness mode requires an issued authorization-validator receipt.")
            approved = self._authority._consume(ticket, selected, self._source.matrix.sha256)
            if candidate_sql != approved:
                raise HarnessSafetyStopError("The harness candidate differs from the validator's regenerated SQL.")
        elif ticket is not None:
            raise HarnessSafetyStopError("A validator receipt cannot relabel an ablated-mode request.")
        identity = self._clone_identity()
        decision = self._reviewer.review_candidate(
            candidate_sql,
            persona=selected,
            mode=mode,
            policy_fingerprint=self._source.matrix.sha256,
            clone_token=identity[2],
            fixture_dump_fingerprint=identity[3],
        )
        if type(decision) is not HarnessSelectReview or (
            not isinstance(decision.regenerated_sql, str)
            or not decision.regenerated_sql.strip()
            or decision.candidate_fingerprint != _sql_hash(candidate_sql)
            or decision.mode is not mode
            or decision.principal_id != selected.principal_id
            or decision.policy_fingerprint != self._source.matrix.sha256
            or decision.clone_token != identity[2]
            or decision.fixture_dump_fingerprint != identity[3]
            or not isinstance(decision.safety_reviewer_revision, str)
            or not decision.safety_reviewer_revision.strip()
        ):
            raise HarnessSafetyStopError("The harness safety review is absent or bound to different inputs.")
        if validated and decision.regenerated_sql != candidate_sql:
            raise HarnessSafetyStopError("Harness safety review changed the authorization-approved SQL.")
        return _HarnessReceipt(
            sql=decision.regenerated_sql,
            sql_fingerprint=_sql_hash(decision.regenerated_sql),
            persona=selected,
            mode=mode,
            policy_fingerprint=self._source.matrix.sha256,
            clone_identity=identity,
            reviewer_revision=decision.safety_reviewer_revision,
            seal=self._seal,
        )

    def execute(
        self,
        persona: Persona,
        candidate_sql: str,
        *,
        mode: ExecutionMode,
        validation_ticket: ValidatedSelect | None = None,
    ) -> ExecutionResult:
        started = monotonic()
        row_cap = self._source.config.limits.output_row_cap
        executed: list[str] = []
        try:
            receipt = self._review(persona, candidate_sql, mode, validation_ticket)
            if (
                receipt.seal is not self._seal
                or receipt.clone_identity != self._clone_identity()
                or receipt.policy_fingerprint != self._source.matrix.sha256
                or receipt.sql_fingerprint != _sql_hash(receipt.sql)
            ):
                raise HarnessSafetyStopError("The isolated harness execution receipt is stale or foreign.")
            self._source.config.resource_budgets.require_database_budget_inputs()
            scoped = mode is not ExecutionMode.UNCONTROLLED
            with self._source.connection(persona=receipt.persona if scoped else None) as connection:
                return _transaction(
                    connection,
                    principal=receipt.persona,
                    switch_business_role=scoped,
                    approved_sql=receipt.sql,
                    row_cap=row_cap,
                    started=started,
                    deadline=started + self._timeout,
                    client_timeout_seconds=self._timeout,
                    execution_record=executed,
                )
        except Exception as exc:
            # A missing/failed safety gate or clone audit is never attributed to
            # ordinary validator/database blocking. The candidate was not run.
            safety_stop = not executed and not isinstance(exc, (TimeoutError, StatementTimeoutError))
            return _failure_result(
                exc,
                row_cap=row_cap,
                started=started,
                executed_sql=executed[-1] if executed else None,
                harness_safety_stop=safety_stop,
            )
