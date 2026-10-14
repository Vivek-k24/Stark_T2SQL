"""Internal NFR-7 JSONL writer source; no log is created on import.

Only write_request() performs a future append to logs/events.jsonl. The caller
invokes it once per request. This is a local CLI/harness diagnostic record, not
a persona response, UI tab, URL parameter or public download. The assignment
creates neither that directory nor any event. Inputs must be synthetic only.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import json
import math
from pathlib import Path
from threading import Lock
from typing import Mapping

from ..contracts import Diagnostic, Outcome, OutcomeStatus, ReasonCode, StoppingLayer
from ..errors import ConfigurationError, SourceReadError


_APPEND_LOCK = Lock()
_MAX_EVENT_BYTES = 16_777_216
_METADATA_FIELDS = frozenset({
    "template_sha256", "model_sha256", "llama_cpp_build", "launcher_sha256",
    "measurement_sha256", "rendered_prompt_sha256", "seed", "max_tokens", "prompt_version",
    "failure_class", "finish_reason", "token_count", "validator_rule", "cancelled", "scored",
})
_ATTEMPT_FIELDS = frozenset({
    "persona", "question", "as_of_date", "mode", "principal_id", "business_role", "login_role",
})


def _primitive(value: object) -> object:
    """Closed serialization vocabulary; never repr arbitrary runtime objects."""
    if value is None or type(value) in {str, int, bool}:
        return value
    if isinstance(value, Enum):
        return _primitive(value.value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ConfigurationError("Trace durations/numbers must be finite.")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ConfigurationError("Trace decimal numbers must be finite.")
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ConfigurationError("Trace mapping keys must be text.")
        return {key: _primitive(item) for key, item in value.items()}
    if type(value) in {tuple, list}:
        return [_primitive(item) for item in value]
    raise ConfigurationError("An unsupported runtime object cannot enter a diagnostic trace.")


def _diagnostic(value: Diagnostic) -> dict[str, object]:
    if type(value) is not Diagnostic:
        raise ConfigurationError("Trace diagnostics require the shared internal contract.")
    return {
        "code": value.code, "internal_detail": value.internal_detail,
        "sqlstate": value.sqlstate, "traceback": value.traceback,
    }


def _selected(values: Mapping[str, object] | None, allowed: frozenset[str]) -> dict[str, object]:
    if values is None:
        return {}
    if not isinstance(values, Mapping) or any(type(key) is not str or key not in allowed for key in values):
        raise ConfigurationError("The trace metadata field is outside its explicit allowlist.")
    return {key: _primitive(value) for key, value in values.items()}


def _outcome(value: Outcome) -> dict[str, object]:
    request = value.request_context.input_request
    persona = request.persona
    timings = value.timings
    fingerprints = value.fingerprints
    return {
        "status": value.status.value, "stopping_layer": value.stopping_layer.value,
        "reason_code": value.reason_code.value,
        "request": {
            "persona": persona.display_name, "business_role": persona.business_role,
            "principal_id": persona.principal_id, "login_role": persona.login_role,
            "question": request.question, "as_of_date": request.as_of_date.isoformat(), "mode": request.mode.value,
        },
        "sql": {
            "raw_model_output": value.raw_output, "extracted_sql": value.extracted_sql,
            "regenerated_sql": value.regenerated_sql, "executed_sql": value.executed_sql,
        },
        "result": {
            "columns": [{
                "name": column.name, "data_type": column.data_type, "nullable": column.nullable,
                "canonical_identity": column.canonical_identity,
            } for column in value.columns],
            # Full capped rows remain in the developer Outcome. Request traces
            # need their size/scope, not duplicate fixture values or real PII.
            "row_count": len(value.rows), "row_cap": value.row_cap, "truncated": value.truncated,
            "row_scope": value.row_scope.value if value.row_scope is not None else None,
        },
        "clarification": None if value.clarification is None else {
            "question": value.clarification.question, "options": value.clarification.options,
        },
        "timings": {
            "total_ms": timings.total_ms, "context_ms": timings.context_ms,
            "generation_ms": timings.generation_ms, "extraction_ms": timings.extraction_ms,
            "validation_ms": timings.validation_ms, "database_ms": timings.database_ms,
        },
        "fingerprints": {
            "fixture_dump": fingerprints.dataset, "prompt_template": fingerprints.prompt,
            "access_matrix": fingerprints.policy, "semantic_block": fingerprints.semantic,
            "filtered_ddl": fingerprints.filtered_ddl, "semantic_catalog": fingerprints.semantic_catalog,
        },
        "diagnostics": [_diagnostic(item) for item in value.diagnostics],
    }


class TraceWriter:
    """One bounded append operation for one complete internal request record.

    A disk failure raises a typed private exception; the caller suppresses a
    public answer and must not retry an append with unknown partial completion.
    This cannot promise a durable event when the local disk itself is unavailable.
    No credentials, config dataclasses, connection objects or arbitrary reprs
    are accepted by the writer. It never reads or exposes existing events.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.path = self.root / "logs" / "events.jsonl"

    def write_request(
        self, outcome: Outcome | None, *, request_id: str,
        attempted_input: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        diagnostic: Diagnostic | None = None,
        attempted_status: OutcomeStatus = OutcomeStatus.ERROR,
        attempted_stopping_layer: StoppingLayer = StoppingLayer.INPUT,
        attempted_elapsed_ms: float | None = None,
    ) -> None:
        if not isinstance(request_id, str) or not request_id.strip():
            raise ConfigurationError("Every trace invocation requires its actual request identifier.")
        if outcome is not None and type(outcome) is not Outcome:
            raise ConfigurationError("A trace can contain only the shared internal Outcome.")
        if outcome is not None and outcome.request_context.request_id != request_id:
            raise ConfigurationError("Trace and Outcome request identifiers differ.")
        record: dict[str, object] = {
            "event_schema": "stark-request-1", "request_id": request_id,
            # UTC clock use is trace metadata only, never a business as-of date.
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "metadata": _selected(metadata, _METADATA_FIELDS),
        }
        if outcome is not None:
            record.update(_outcome(outcome))
        else:
            reason = diagnostic.code if diagnostic is not None else ReasonCode.INVALID_INPUT.value
            if type(attempted_status) is not OutcomeStatus or type(attempted_stopping_layer) is not StoppingLayer:
                raise ConfigurationError("A rejected request event requires typed status and stopping layer.")
            record.update({
                "status": attempted_status.value, "stopping_layer": attempted_stopping_layer.value,
                "reason_code": reason, "request": _selected(attempted_input, _ATTEMPT_FIELDS),
                "sql": {"raw_model_output": None, "extracted_sql": None, "regenerated_sql": None, "executed_sql": None},
                "timings": {"total_ms": attempted_elapsed_ms}, "fingerprints": None,
                "diagnostics": [_diagnostic(diagnostic)] if diagnostic is not None else [],
            })
        # JSON escapes also preserve rejected lone-surrogate input without
        # allowing it to prevent the sole diagnostic append during UTF-8 encoding.
        payload = (json.dumps(_primitive(record), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        if len(payload) > _MAX_EVENT_BYTES:
            raise ConfigurationError("The complete request trace exceeds its source-defined byte bound.")
        with _APPEND_LOCK:
            try:
                # Re-resolve before both directory and file operations, so a
                # redirected log path cannot leave the intended workspace.
                if not self.path.resolve().is_relative_to(self.root):
                    raise ConfigurationError("The internal event path must remain inside the project workspace.")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if not self.path.resolve().is_relative_to(self.root):
                    raise ConfigurationError("The internal event path must remain inside the project workspace.")
                with self.path.open("ab", buffering=0) as stream:
                    written = stream.write(payload)
                    if written != len(payload):
                        raise OSError("The local request event append was incomplete.")
            except OSError as exc:
                raise SourceReadError("The internal local request event could not be appended.") from exc
