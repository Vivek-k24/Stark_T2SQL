"""Unit tests for individual Streamlit UI components and safe projection contracts."""

from datetime import date
from decimal import Decimal
import sys
from types import SimpleNamespace
import pytest

from stark_t2sql.contracts import (
    Clarification,
    OutcomeStatus,
    Persona,
    ReasonCode,
    RowScopeKind,
    SafeResponse,
    StoppingLayer,
)
from stark_t2sql.pipeline.response import SafeConcept, SafePolicyRow
from stark_t2sql.ui.ui_state import ANSWER_KEY, BUSY_KEY, current_answer, initialize_state, retain_answer
from stark_t2sql.ui.views import (
    REQUEST_UNAVAILABLE,
    SERVICE_UNAVAILABLE,
    render_access_policy,
    render_safe_response,
    render_semantic_catalog,
)


class RecordingStreamlit:
    def __init__(self):
        self.infos = []
        self.successes = []
        self.warnings = []
        self.errors = []
        self.texts = []
        self.captions = []
        self.dataframes = []

    def info(self, msg):
        self.infos.append(msg)

    def success(self, msg):
        self.successes.append(msg)

    def warning(self, msg):
        self.warnings.append(msg)

    def error(self, msg):
        self.errors.append(msg)

    def text(self, msg):
        self.texts.append(msg)

    def caption(self, msg):
        self.captions.append(msg)

    def dataframe(self, df, **kwargs):
        self.dataframes.append((df, kwargs))


def test_render_safe_response_answered_with_results(monkeypatch):
    fake_st = RecordingStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    resp = SafeResponse(
        status=OutcomeStatus.ANSWERED,
        stopping_layer=StoppingLayer.NONE,
        reason_code=ReasonCode.ANSWERED,
        as_of_date=date(2026, 10, 12),
        columns=("active_headcount",),
        rows=((435,),),
        elapsed_ms=150.0,
    )
    render_safe_response(resp)

    assert "Allowed" in fake_st.successes
    assert resp.message in fake_st.texts
    assert any("ANSWERED · NONE · ANSWERED" in cap for cap in fake_st.captions)
    assert any("2026-10-12" in cap for cap in fake_st.captions)
    assert any("0.15 seconds" in cap for cap in fake_st.captions)
    assert len(fake_st.dataframes) == 1
    df, kwargs = fake_st.dataframes[0]
    assert list(df.columns) == ["active_headcount"]
    assert kwargs.get("hide_index") is True


def test_render_safe_response_answered_zero_rows(monkeypatch):
    fake_st = RecordingStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    resp = SafeResponse(
        status=OutcomeStatus.ANSWERED,
        stopping_layer=StoppingLayer.NONE,
        reason_code=ReasonCode.ANSWERED,
        as_of_date=date(2026, 10, 12),
        columns=("leave_id", "employee_id", "balance"),
        rows=(),
        row_scope=RowScopeKind.ASSIGNED_DIVISIONS,
    )
    render_safe_response(resp)

    assert "Scoped result" in fake_st.infos
    assert "No permitted rows matched this question." in fake_st.infos
    assert resp.scope_note in fake_st.texts


def test_render_safe_response_answered_truncated(monkeypatch):
    fake_st = RecordingStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    resp = SafeResponse(
        status=OutcomeStatus.ANSWERED,
        stopping_layer=StoppingLayer.NONE,
        reason_code=ReasonCode.ANSWERED,
        as_of_date=date(2026, 10, 12),
        columns=("id", "amount"),
        rows=tuple((i, Decimal("10.00")) for i in range(1000)),
        truncated=True,
        row_cap=1000,
    )
    render_safe_response(resp)

    assert any("1000 rows" in w for w in fake_st.warnings)
    assert len(fake_st.dataframes) == 1


def test_render_safe_response_blocked_validator(monkeypatch):
    fake_st = RecordingStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    resp = SafeResponse(
        status=OutcomeStatus.BLOCKED_VALIDATOR,
        stopping_layer=StoppingLayer.VALIDATOR,
        reason_code=ReasonCode.VALIDATOR_REJECTED,
        as_of_date=date(2026, 10, 12),
    )
    render_safe_response(resp)

    assert "Blocked" in fake_st.errors
    assert resp.message in fake_st.texts
    assert any("BLOCKED_VALIDATOR · VALIDATOR · VALIDATOR_REJECTED" in cap for cap in fake_st.captions)
    assert len(fake_st.dataframes) == 0


def test_render_safe_response_blocked_database(monkeypatch):
    fake_st = RecordingStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    resp = SafeResponse(
        status=OutcomeStatus.BLOCKED_DB,
        stopping_layer=StoppingLayer.DATABASE,
        reason_code=ReasonCode.DB_PERMISSION_DENIED,
        as_of_date=date(2026, 10, 12),
    )
    render_safe_response(resp)

    assert "Blocked" in fake_st.errors
    assert resp.message in fake_st.texts
    assert any("BLOCKED_DB · DATABASE · DB_PERMISSION_DENIED" in cap for cap in fake_st.captions)


def test_render_safe_response_clarification(monkeypatch):
    fake_st = RecordingStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    clarification = Clarification(
        question="Did you mean Engineering division?",
        options=("Option A", "Option B"),
    )
    resp = SafeResponse(
        status=OutcomeStatus.CLARIFICATION_REQUIRED,
        stopping_layer=StoppingLayer.INPUT,
        reason_code=ReasonCode.CLARIFICATION_REQUIRED,
        as_of_date=date(2026, 10, 12),
        clarification=clarification,
    )
    render_safe_response(resp)

    assert "Clarification needed" in fake_st.warnings
    assert "Did you mean Engineering division?" in fake_st.texts
    assert "Option A" in fake_st.texts
    assert "Option B" in fake_st.texts


def test_render_safe_response_timeout(monkeypatch):
    fake_st = RecordingStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    resp = SafeResponse(
        status=OutcomeStatus.TIMEOUT,
        stopping_layer=StoppingLayer.MODEL,
        reason_code=ReasonCode.GENERATION_TIMEOUT,
        as_of_date=date(2026, 10, 12),
    )
    render_safe_response(resp)

    assert "Answer unavailable" in fake_st.warnings
    assert resp.message in fake_st.texts
    assert any("TIMEOUT · MODEL · GENERATION_TIMEOUT" in cap for cap in fake_st.captions)


def test_render_safe_response_error(monkeypatch):
    fake_st = RecordingStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    resp = SafeResponse(
        status=OutcomeStatus.ERROR,
        stopping_layer=StoppingLayer.INTERNAL,
        reason_code=ReasonCode.INTERNAL_ERROR,
        as_of_date=date(2026, 10, 12),
    )
    render_safe_response(resp)

    assert "Answer unavailable" in fake_st.warnings
    assert resp.message in fake_st.texts
    assert any("ERROR · INTERNAL · INTERNAL_ERROR" in cap for cap in fake_st.captions)


def test_render_safe_response_rejects_non_safe_response(monkeypatch):
    fake_st = RecordingStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    render_safe_response({"raw_sql": "SELECT *", "status": "OK"})
    assert REQUEST_UNAVAILABLE in fake_st.errors
