"""Shared Prompt 1 contracts drafted from STARK-TTSQL-FRD-1.8.

FR-8 defines internal outcomes and safe persona responses; FR-9 supplies the
failure-class and expected-outcome vocabularies. Reason codes and stopping-layer
names are implementation-defined because the FRD does not enumerate them.
Later prompts own persona resolution, authorization, inference, SQL validation,
execution, evaluation, and the NFR-7 local structured trace writer. Constructing
a request or choosing a mode does not authorize execution. The user's NFR-6
authorship exception permits source drafting only, not runtime activity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import json
import math
from types import MappingProxyType
from typing import Mapping, TypeAlias


class ExecutionMode(str, Enum):
    """FULL is the normal path; later harness code owns other-mode isolation."""

    FULL = "FULL"
    NO_PROMPT_FILTER = "NO_PROMPT_FILTER"
    NO_VALIDATOR = "NO_VALIDATOR"
    UNCONTROLLED = "UNCONTROLLED"


class OutcomeStatus(str, Enum):
    ANSWERED = "ANSWERED"
    BLOCKED_VALIDATOR = "BLOCKED_VALIDATOR"
    BLOCKED_DB = "BLOCKED_DB"
    MODEL_SQL_ERROR = "MODEL_SQL_ERROR"
    MODEL_ERROR = "MODEL_ERROR"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    HARNESS_SAFETY_STOP = "HARNESS_SAFETY_STOP"


class StoppingLayer(str, Enum):
    """Implementation-defined pipeline locations used in the FR-8 record."""

    NONE = "NONE"
    CONFIGURATION = "CONFIGURATION"
    INPUT = "INPUT"
    CONTEXT = "CONTEXT"
    MODEL = "MODEL"
    EXTRACTION = "EXTRACTION"
    VALIDATOR = "VALIDATOR"
    DATABASE = "DATABASE"
    HARNESS = "HARNESS"
    RESPONSE = "RESPONSE"
    INTERNAL = "INTERNAL"


class ReasonCode(str, Enum):
    """Implementation-defined reasons, distinct from FR-9 failure classes."""

    ANSWERED = "ANSWERED"
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_DEPENDENCY = "MISSING_DEPENDENCY"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    ENDPOINT_NOT_ALLOWED = "ENDPOINT_NOT_ALLOWED"
    SOURCE_READ_ERROR = "SOURCE_READ_ERROR"
    CONTEXT_UNAVAILABLE = "CONTEXT_UNAVAILABLE"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_FAILURE = "MODEL_FAILURE"
    SQL_EXTRACTION_FAILED = "SQL_EXTRACTION_FAILED"
    GENERATION_TRUNCATED = "GENERATION_TRUNCATED"
    VALIDATOR_REJECTED = "VALIDATOR_REJECTED"
    DB_PERMISSION_DENIED = "DB_PERMISSION_DENIED"
    SQL_SYNTAX_ERROR = "SQL_SYNTAX_ERROR"
    UNKNOWN_DATABASE_OBJECT = "UNKNOWN_DATABASE_OBJECT"
    DATABASE_ERROR = "DATABASE_ERROR"
    GENERATION_TIMEOUT = "GENERATION_TIMEOUT"
    STATEMENT_TIMEOUT = "STATEMENT_TIMEOUT"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    HARNESS_SAFETY_STOP = "HARNESS_SAFETY_STOP"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class FailureClass(str, Enum):
    """Exact FR-9.3 vocabulary; Prompt 5 owns case classification and triage."""

    EXTRACT = "FC-EXTRACT"
    SYNTAX = "FC-SYNTAX"
    HALLUC = "FC-HALLUC"
    VALIDATOR = "FC-VALIDATOR"
    OVERBLOCK = "FC-OVERBLOCK"
    POLICY = "FC-POLICY"
    WALLCLOCK = "FC-WALLCLOCK"
    TIMEOUT_GEN = "FC-TIMEOUT-GEN"
    TRUNCATED_GEN = "FC-TRUNCATED-GEN"
    TIMEOUT_STMT = "FC-TIMEOUT-STMT"
    LEAK = "FC-LEAK"
    RUNTIME = "FC-RUNTIME"
    SCHEMA = "FC-SCHEMA"
    JOIN = "FC-JOIN"
    FILTER = "FC-FILTER"
    AGG = "FC-AGG"
    TEMPORAL = "FC-TEMPORAL"
    SEMANTIC = "FC-SEMANTIC"


class ExpectedOutcome(str, Enum):
    """Exact FR-9.4 case expectations, separate from observed statuses."""

    MATCH_REFERENCE = "MATCH_REFERENCE"
    BLOCKED_DB = "BLOCKED_DB"
    BLOCKED_VALIDATOR = "BLOCKED_VALIDATOR"
    BLOCKED_ANY = "BLOCKED_ANY"
    SCOPED_RESULT = "SCOPED_RESULT"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    CANONICAL_RESOLUTION = "CANONICAL_RESOLUTION"


class RowScopeKind(str, Enum):
    """The four section 6.4 matrix kinds; this enum enforces no policy."""

    ALL = "all"
    DIRECT_REPORTS = "direct_reports"
    ASSIGNED_DIVISIONS = "assigned_divisions"
    VIA_EMPLOYEES = "via_employees"


_PUBLIC_MESSAGES: Mapping[ReasonCode, str] = MappingProxyType(
    {
        ReasonCode.ANSWERED: "The request completed.",
        ReasonCode.INVALID_INPUT: "Provide a persona, a question, and an explicit date.",
        ReasonCode.MISSING_DEPENDENCY: "A required local resource is unavailable.",
        ReasonCode.INVALID_CONFIGURATION: "The local service configuration is unavailable.",
        ReasonCode.ENDPOINT_NOT_ALLOWED: "The requested service endpoint is unavailable.",
        ReasonCode.SOURCE_READ_ERROR: "A required local resource could not be read.",
        ReasonCode.CONTEXT_UNAVAILABLE: "The required request context is unavailable.",
        ReasonCode.CLARIFICATION_REQUIRED: "Clarify the meaning of the requested term.",
        ReasonCode.MODEL_UNAVAILABLE: "The local model is unavailable.",
        ReasonCode.MODEL_FAILURE: "The local model could not complete this request.",
        ReasonCode.SQL_EXTRACTION_FAILED: "The model did not produce a usable query.",
        ReasonCode.GENERATION_TRUNCATED: "The model did not finish producing a query.",
        ReasonCode.VALIDATOR_REJECTED: "This request cannot be completed for the selected persona.",
        ReasonCode.DB_PERMISSION_DENIED: "This request cannot be completed for the selected persona.",
        ReasonCode.SQL_SYNTAX_ERROR: "The model did not produce a usable query.",
        ReasonCode.UNKNOWN_DATABASE_OBJECT: "The model did not produce a usable query.",
        ReasonCode.DATABASE_ERROR: "The local database could not complete this request.",
        ReasonCode.GENERATION_TIMEOUT: "The local model exceeded the request time limit.",
        ReasonCode.STATEMENT_TIMEOUT: "The query exceeded the request time limit.",
        ReasonCode.REQUEST_TIMEOUT: "The request exceeded its time limit.",
        ReasonCode.HARNESS_SAFETY_STOP: "The evaluation request was stopped for safety.",
        ReasonCode.INTERNAL_ERROR: "The request could not be completed.",
    }
)


_PUBLIC_SCOPE_NOTES: Mapping[RowScopeKind, str] = MappingProxyType(
    {
        RowScopeKind.ALL: "Results include the rows permitted for this persona.",
        RowScopeKind.DIRECT_REPORTS: "Results are limited to direct reports.",
        RowScopeKind.ASSIGNED_DIVISIONS: "Results are limited to assigned divisions.",
        RowScopeKind.VIA_EMPLOYEES: "Results are limited to visible employees.",
    }
)


def public_message_for(reason_code: ReasonCode) -> str:
    """Return static public text; never accept an internal exception message."""

    if not isinstance(reason_code, ReasonCode):
        raise TypeError("reason_code must be a ReasonCode")
    return _PUBLIC_MESSAGES[reason_code]


ResultValue: TypeAlias = str | int | bool | float | Decimal | date | datetime | None
ResultRow: TypeAlias = tuple[ResultValue, ...]
JSONScalar: TypeAlias = str | int | bool | float | None


def _public_cell(value: ResultValue) -> JSONScalar:
    """Serialize supported cells without lossy Decimal-to-float conversion."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("result decimals must be finite")
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("result floats must be finite")
        return value
    raise TypeError("unsupported result cell type")


@dataclass(frozen=True, slots=True)
class Persona:
    """Simulated identity metadata, with no authentication or policy inference."""

    display_name: str
    business_role: str
    principal_id: int
    login_role: str

    def __post_init__(self) -> None:
        for value in (self.display_name, self.business_role, self.login_role):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("persona names and roles must be nonempty strings")
        if type(self.principal_id) is not int or self.principal_id <= 0:
            raise ValueError("principal_id must be a positive integer")


@dataclass(frozen=True, slots=True)
class InputRequest:
    """Request date is mandatory and never taken from the host wall clock."""

    persona: Persona
    question: str
    as_of_date: date
    mode: ExecutionMode = ExecutionMode.FULL

    def __post_init__(self) -> None:
        if not isinstance(self.persona, Persona):
            raise TypeError("persona must be a Persona")
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("question must be a nonempty string")
        if type(self.as_of_date) is not date:
            raise TypeError("as_of_date must be an explicit date, without time")
        if not isinstance(self.mode, ExecutionMode):
            raise TypeError("mode must be an ExecutionMode")


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Internal request context; not a persona-response payload."""

    input_request: InputRequest
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class ColumnMetadata:
    """Metadata supplied later by a role-restricted result executor."""

    name: str
    data_type: str | None = None
    nullable: bool | None = None
    canonical_identity: str | None = None


@dataclass(frozen=True, slots=True)
class RequestTimings:
    """Elapsed milliseconds only; no implicit dates or measured budgets."""

    total_ms: float | None = None
    context_ms: float | None = None
    generation_ms: float | None = None
    extraction_ms: float | None = None
    validation_ms: float | None = None
    database_ms: float | None = None

    def __post_init__(self) -> None:
        for value in (
            self.total_ms,
            self.context_ms,
            self.generation_ms,
            self.extraction_ms,
            self.validation_ms,
            self.database_ms,
        ):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("elapsed milliseconds must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class ArtifactFingerprints:
    """FR-8.5 SHA-256 values; None means an actual artifact is unavailable.

    dataset means the authoritative fixture dump, policy means access-matrix
    bytes, and semantic means the emitted role-filtered semantic block. The
    optional full semantic catalog is a separate FR-9.7 run input. Fingerprint
    functions belong to the utilities; this structure never invents a hash.
    """

    dataset: str | None = None
    prompt: str | None = None
    policy: str | None = None
    semantic: str | None = None
    filtered_ddl: str | None = None
    semantic_catalog: str | None = None

    def __post_init__(self) -> None:
        for value in (
            self.dataset,
            self.prompt,
            self.policy,
            self.semantic,
            self.filtered_ddl,
            self.semantic_catalog,
        ):
            if value is not None and (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError("fingerprints must be lowercase SHA-256 hex or None")

    @property
    def fixture_dump(self) -> str | None:
        return self.dataset

    @property
    def access_matrix(self) -> str | None:
        return self.policy

    @property
    def semantic_block(self) -> str | None:
        return self.semantic


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Internal details for future local trace/harness writers only."""

    code: str
    internal_detail: str
    sqlstate: str | None = None
    traceback: str | None = None


@dataclass(frozen=True, slots=True)
class Clarification:
    """Public wording supplied later by the policy-filtered semantic resolver.

    This is an intentional persona-facing question, never a model response or
    error message. Prompt 3 owns permitted vocabulary and ambiguity resolution;
    constructing this structure does not establish semantic entitlement.
    """

    question: str
    options: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", tuple(self.options))
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError("clarification question must be nonempty text")
        if any(not isinstance(option, str) or not option.strip() for option in self.options):
            raise ValueError("clarification options must be nonempty text")


@dataclass(frozen=True, slots=True)
class Outcome:
    """Internal result, including material that must never reach persona views.

    The future executor supplies already capped rows and detects truncation by
    fetching cap + 1. This contract rejects over-cap rows instead of silently
    making an incorrect truncation claim. Row caps do not constrain query cost.
    regenerated_sql is an approved candidate; executed_sql is populated only
    when the executor actually submits that candidate. They are not aliases.
    """

    status: OutcomeStatus
    stopping_layer: StoppingLayer
    reason_code: ReasonCode
    request_context: RequestContext
    row_cap: int
    columns: tuple[ColumnMetadata, ...] = ()
    rows: tuple[ResultRow, ...] = ()
    truncated: bool = False
    raw_output: str | None = None
    extracted_sql: str | None = None
    regenerated_sql: str | None = None
    executed_sql: str | None = None
    timings: RequestTimings = field(default_factory=RequestTimings)
    fingerprints: ArtifactFingerprints = field(default_factory=ArtifactFingerprints)
    diagnostics: tuple[Diagnostic, ...] = ()
    clarification: Clarification | None = None
    row_scope: RowScopeKind | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "rows", tuple(tuple(row) for row in self.rows))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if not isinstance(self.status, OutcomeStatus):
            raise TypeError("status must be an OutcomeStatus")
        if not isinstance(self.stopping_layer, StoppingLayer):
            raise TypeError("stopping_layer must be a StoppingLayer")
        if not isinstance(self.reason_code, ReasonCode):
            raise TypeError("reason_code must be a ReasonCode")
        if not isinstance(self.request_context, RequestContext):
            raise TypeError("request_context must be a RequestContext")
        if type(self.truncated) is not bool:
            raise TypeError("truncated must be a boolean")
        if self.row_scope is not None and not isinstance(self.row_scope, RowScopeKind):
            raise TypeError("row_scope must be a RowScopeKind or None")
        if self.clarification is not None and (
            not isinstance(self.clarification, Clarification)
            or self.status is not OutcomeStatus.CLARIFICATION_REQUIRED
        ):
            raise ValueError("clarification belongs only to CLARIFICATION_REQUIRED")
        if self.status is OutcomeStatus.CLARIFICATION_REQUIRED:
            if self.clarification is None:
                raise ValueError("CLARIFICATION_REQUIRED requires a clarifying question")
            if self.executed_sql is not None or self.rows:
                raise ValueError("a clarification outcome cannot execute SQL or contain rows")
        if self.status is OutcomeStatus.HARNESS_SAFETY_STOP and self.executed_sql is not None:
            raise ValueError("a harness safety stop cannot execute candidate SQL")
        if type(self.row_cap) is not int or self.row_cap <= 0:
            raise ValueError("row_cap must be a positive integer")
        if len(self.rows) > self.row_cap:
            raise ValueError("outcome rows exceed the configured row cap")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("result row widths must match column metadata")

    def to_safe_response(self) -> SafeResponse:
        """Project a fixed allowlist, without diagnostics or SQL text fields."""

        answered = self.status is OutcomeStatus.ANSWERED
        return SafeResponse(
            status=self.status,
            stopping_layer=self.stopping_layer,
            reason_code=self.reason_code,
            as_of_date=self.request_context.input_request.as_of_date,
            columns=tuple(column.name for column in self.columns) if answered else (),
            rows=self.rows if answered else (),
            truncated=self.truncated if answered else False,
            elapsed_ms=self.timings.total_ms,
            clarification=self.clarification,
            row_cap=self.row_cap if answered else None,
            row_scope=self.row_scope if answered else None,
        )


@dataclass(frozen=True, slots=True)
class SafeResponse:
    """Explicit persona-facing payload, without free-form message arguments.

    No SQL, internal error, model-text, trace, fingerprint, or request-context
    fields exist here. Result names and cells must come from the future
    authorized executor; this type does not perform column/row authorization.
    Use to_dict/to_json for persona output, never serialize Outcome wholesale.
    """

    status: OutcomeStatus
    stopping_layer: StoppingLayer
    reason_code: ReasonCode
    as_of_date: date
    columns: tuple[str, ...] = ()
    rows: tuple[ResultRow, ...] = ()
    truncated: bool = False
    elapsed_ms: float | None = None
    clarification: Clarification | None = None
    row_cap: int | None = None
    row_scope: RowScopeKind | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "rows", tuple(tuple(row) for row in self.rows))
        if not isinstance(self.status, OutcomeStatus):
            raise TypeError("status must be an OutcomeStatus")
        if not isinstance(self.stopping_layer, StoppingLayer):
            raise TypeError("stopping_layer must be a StoppingLayer")
        if not isinstance(self.reason_code, ReasonCode):
            raise TypeError("reason_code must be a ReasonCode")
        if type(self.truncated) is not bool:
            raise TypeError("truncated must be a boolean")
        if self.row_cap is not None and (
            type(self.row_cap) is not int or self.row_cap <= 0
        ):
            raise ValueError("public row_cap must be a positive integer or None")
        if self.truncated and self.row_cap is None:
            raise ValueError("a truncated public response requires its row cap")
        if self.row_cap is not None and len(self.rows) > self.row_cap:
            raise ValueError("public rows exceed the configured row cap")
        if self.row_scope is not None and not isinstance(self.row_scope, RowScopeKind):
            raise TypeError("row_scope must be a RowScopeKind or None")
        if self.clarification is not None and (
            not isinstance(self.clarification, Clarification)
            or self.status is not OutcomeStatus.CLARIFICATION_REQUIRED
        ):
            raise ValueError("clarification belongs only to CLARIFICATION_REQUIRED")
        if self.status is OutcomeStatus.CLARIFICATION_REQUIRED and self.clarification is None:
            raise ValueError("CLARIFICATION_REQUIRED requires a clarifying question")
        if type(self.as_of_date) is not date:
            raise TypeError("as_of_date must be an explicit date, without time")
        if any(not isinstance(column, str) for column in self.columns):
            raise TypeError("public column names must be strings")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("public row widths must match column names")
        if self.status is not OutcomeStatus.ANSWERED and (
            self.columns or self.rows or self.truncated
        ):
            raise ValueError("non-answer public responses cannot contain result data")
        if self.elapsed_ms is not None and (
            isinstance(self.elapsed_ms, bool)
            or not isinstance(self.elapsed_ms, (int, float))
            or not math.isfinite(self.elapsed_ms)
            or self.elapsed_ms < 0
        ):
            raise ValueError("elapsed milliseconds must be finite and nonnegative")

    @property
    def message(self) -> str:
        return public_message_for(self.reason_code)

    @property
    def scope_note(self) -> str | None:
        if self.status is OutcomeStatus.ANSWERED and self.row_scope is not None:
            return _PUBLIC_SCOPE_NOTES[self.row_scope]
        return None

    @property
    def truncation_note(self) -> str | None:
        if self.truncated:
            return f"Results are limited to {self.row_cap} rows and are incomplete."
        return None

    def to_dict(self) -> dict[str, object]:
        """Serialize only explicit public fields, using deterministic cells."""

        return {
            "status": self.status.value,
            "stopping_layer": self.stopping_layer.value,
            "reason_code": self.reason_code.value,
            "as_of_date": self.as_of_date.isoformat(),
            "message": self.message,
            "columns": list(self.columns),
            "rows": [[_public_cell(value) for value in row] for row in self.rows],
            "truncated": self.truncated,
            "scope_note": self.scope_note,
            "truncation_note": self.truncation_note,
            "elapsed_ms": self.elapsed_ms,
            "clarification": (
                {"question": self.clarification.question, "options": list(self.clarification.options)}
                if self.clarification is not None
                else None
            ),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
