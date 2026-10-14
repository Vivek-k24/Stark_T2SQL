"""In-memory contract helpers; numbers below are unit operands, not fixture answers."""
from datetime import date

from stark_t2sql.contracts import (
    Clarification, ColumnMetadata, Diagnostic, ExecutionMode, InputRequest,
    Outcome, OutcomeStatus, ReasonCode, RequestContext, StoppingLayer,
)


def make_outcome(persona, *, status=OutcomeStatus.ANSWERED, reason=ReasonCode.ANSWERED,
                 layer=StoppingLayer.NONE, rows=(), columns=(), mode=ExecutionMode.FULL,
                 sql=None, sqlstate=None, clarification=None, truncated=False):
    request = InputRequest(persona, "Unit contract question", date(2026, 10, 12), mode)
    diagnostics = () if sqlstate is None else (Diagnostic("unit-sqlstate", "Private driver detail", sqlstate),)
    return Outcome(status, layer, reason, RequestContext(request, "unit-contract-request"), 1000,
        columns=tuple(ColumnMetadata(item) if isinstance(item, str) else item for item in columns),
        rows=tuple(rows), executed_sql=sql, extracted_sql=sql, diagnostics=diagnostics,
        clarification=clarification, truncated=truncated)
