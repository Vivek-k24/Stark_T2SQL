"""Shared internal exceptions with static public descriptions.

The baseline is STARK-TTSQL-FRD-1.8. Outcome statuses follow FR-8; reason
codes are implementation-defined, separate from the FR-9 failure taxonomy.
These classes describe failure boundaries only; later prompts implement
the actual policy, validator, executor, inference, and NFR-7 trace handling.
Exception text and internal_detail are private diagnostic material. Persona
views must use safe_public_description or the SafeResponse projection.
"""

from __future__ import annotations

from typing import ClassVar

from .contracts import OutcomeStatus, ReasonCode, StoppingLayer, public_message_for


class StarkT2SQLError(Exception):
    """Preserve internal detail without turning it into a public message."""

    default_reason_code: ClassVar[ReasonCode] = ReasonCode.INTERNAL_ERROR
    status: ClassVar[OutcomeStatus] = OutcomeStatus.ERROR
    stopping_layer: ClassVar[StoppingLayer] = StoppingLayer.INTERNAL

    def __init__(
        self,
        internal_detail: str,
        *,
        reason_code: ReasonCode | None = None,
    ) -> None:
        if not isinstance(internal_detail, str):
            raise TypeError("internal_detail must be a string")
        selected_code = self.default_reason_code if reason_code is None else reason_code
        if not isinstance(selected_code, ReasonCode):
            raise TypeError("reason_code must be a ReasonCode")
        self.internal_detail = internal_detail
        self.reason_code = selected_code
        super().__init__(internal_detail)

    @property
    def safe_public_description(self) -> str:
        return public_message_for(self.reason_code)

    @property
    def public_message(self) -> str:
        """Convenience name for the same static public description."""

        return self.safe_public_description


class MissingDependencyError(StarkT2SQLError):
    default_reason_code = ReasonCode.MISSING_DEPENDENCY
    stopping_layer = StoppingLayer.CONFIGURATION


class ConfigurationError(StarkT2SQLError):
    default_reason_code = ReasonCode.INVALID_CONFIGURATION
    stopping_layer = StoppingLayer.CONFIGURATION


class LocalEndpointError(StarkT2SQLError):
    default_reason_code = ReasonCode.ENDPOINT_NOT_ALLOWED
    stopping_layer = StoppingLayer.CONFIGURATION


class SourceReadError(StarkT2SQLError):
    default_reason_code = ReasonCode.SOURCE_READ_ERROR
    stopping_layer = StoppingLayer.CONFIGURATION


class InvalidRequestError(StarkT2SQLError):
    default_reason_code = ReasonCode.INVALID_INPUT
    stopping_layer = StoppingLayer.INPUT


class ModelGenerationError(StarkT2SQLError):
    default_reason_code = ReasonCode.MODEL_FAILURE
    status = OutcomeStatus.MODEL_ERROR
    stopping_layer = StoppingLayer.MODEL


class SQLExtractionError(StarkT2SQLError):
    default_reason_code = ReasonCode.SQL_EXTRACTION_FAILED
    status = OutcomeStatus.MODEL_SQL_ERROR
    stopping_layer = StoppingLayer.EXTRACTION


class GenerationTruncatedError(ModelGenerationError):
    """Token-cap incompleteness (FR-4.8), distinct from elapsed timeout."""

    default_reason_code = ReasonCode.GENERATION_TRUNCATED
    status = OutcomeStatus.MODEL_SQL_ERROR


class SQLValidationError(StarkT2SQLError):
    default_reason_code = ReasonCode.VALIDATOR_REJECTED
    status = OutcomeStatus.BLOCKED_VALIDATOR
    stopping_layer = StoppingLayer.VALIDATOR


class DatabaseExecutionError(StarkT2SQLError):
    default_reason_code = ReasonCode.DATABASE_ERROR
    stopping_layer = StoppingLayer.DATABASE


class DatabasePermissionError(DatabaseExecutionError):
    default_reason_code = ReasonCode.DB_PERMISSION_DENIED
    status = OutcomeStatus.BLOCKED_DB


class DatabaseSyntaxError(DatabaseExecutionError):
    """FR-8.1 syntax status; the future executor maps SQLSTATE 42601."""

    default_reason_code = ReasonCode.SQL_SYNTAX_ERROR
    status = OutcomeStatus.MODEL_SQL_ERROR


class DatabaseObjectError(DatabaseExecutionError):
    """FR-8.1 missing-object status for SQLSTATE 42P01/42703/42883."""

    default_reason_code = ReasonCode.UNKNOWN_DATABASE_OBJECT
    status = OutcomeStatus.MODEL_SQL_ERROR


class RequestTimeoutError(StarkT2SQLError):
    default_reason_code = ReasonCode.REQUEST_TIMEOUT
    status = OutcomeStatus.TIMEOUT


class GenerationTimeoutError(RequestTimeoutError):
    default_reason_code = ReasonCode.GENERATION_TIMEOUT
    stopping_layer = StoppingLayer.MODEL


class StatementTimeoutError(RequestTimeoutError):
    default_reason_code = ReasonCode.STATEMENT_TIMEOUT
    stopping_layer = StoppingLayer.DATABASE


class HarnessSafetyStopError(StarkT2SQLError):
    default_reason_code = ReasonCode.HARNESS_SAFETY_STOP
    status = OutcomeStatus.HARNESS_SAFETY_STOP
    stopping_layer = StoppingLayer.HARNESS
