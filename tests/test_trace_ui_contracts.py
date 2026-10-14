"""Safe display, internal trace serialization and six-stage state definitions."""
import ast
from dataclasses import replace
import json
from pathlib import Path

import pytest

from stark_t2sql.contracts import Diagnostic, OutcomeStatus, ReasonCode, RowScopeKind, StoppingLayer
from stark_t2sql.pipeline.trace import TraceWriter, _outcome
from stark_t2sql.ui.architecture import STAGES
from stark_t2sql.ui.ui_state import ANSWER_KEY, BUSY_KEY, current_answer, initialize_state, request_guard, retain_answer
from stark_t2sql.ui.views import NAVIGATION
from .helpers import make_outcome


def test_persona_projection_hides_raw_sql_errors_and_hashes(payroll_persona):
    outcome = replace(make_outcome(payroll_persona),raw_output="Private model output",extracted_sql="Private SQL",
        regenerated_sql="Private regenerated SQL",diagnostics=(Diagnostic("unit","Private driver detail",traceback="Private traceback"),))
    public = outcome.to_safe_response().to_dict()
    text = json.dumps(public)
    assert "Private" not in text
    assert not set(public) & {"sql","fingerprints","diagnostics","request_context","raw_output"}
    internal = _outcome(outcome)
    assert internal["sql"]["raw_model_output"] == "Private model output"
    assert internal["diagnostics"][0]["traceback"] == "Private traceback"


def test_truncation_and_scope_notes_are_explicit(payroll_persona):
    outcome = replace(make_outcome(payroll_persona,truncated=True),row_scope=RowScopeKind.DIRECT_REPORTS)
    public = outcome.to_safe_response()
    assert public.truncation_note and public.scope_note


def test_writer_definitions_append_one_jsonl_event_to_memory(monkeypatch,project_root,payroll_persona):
    writes=[]
    class MemoryStream:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def write(self,payload): writes.append(payload); return len(payload)
    monkeypatch.setattr(Path,"mkdir",lambda *args,**kwargs:None)
    monkeypatch.setattr(Path,"open",lambda *args,**kwargs:MemoryStream())
    TraceWriter(project_root).write_request(make_outcome(payroll_persona),request_id="unit-contract-request")
    assert len(writes) == 1 and writes[0].endswith(b"\n")
    event = json.loads(writes[0])
    assert event["request_id"] == "unit-contract-request" and event["event_schema"] == "stark-request-1"


def test_ui_busy_guard_resets_after_failure_and_rejects_concurrent_request():
    first={}; second={}; initialize_state(first); initialize_state(second)
    with pytest.raises(RuntimeError):
        with request_guard(first) as acquired:
            assert acquired and first[BUSY_KEY] is True
            with request_guard(second) as other: assert other is False
            raise RuntimeError("Unit cancellation")
    assert first[BUSY_KEY] is False
    with request_guard(second) as acquired: assert acquired is True


def test_safe_result_is_hidden_when_persona_or_question_changes(payroll_persona,fixture_date):
    state={}; response=make_outcome(payroll_persona).to_safe_response()
    retain_answer(state,persona_name="Payroll specialist",question="Unit",as_of_date=fixture_date,response=response)
    assert current_answer(state,persona_name="Payroll specialist",question="Unit",as_of_date=fixture_date) is response
    assert current_answer(state,persona_name="HR business partner #1",question="Unit",as_of_date=fixture_date) is None
    assert ANSWER_KEY not in state


def test_six_stage_metadata_has_details_and_no_review_queue():
    assert tuple(stage.number for stage in STAGES) == tuple(range(1,7))
    for stage in STAGES:
        assert stage.title and stage.purpose and stage.normal_flow and stage.failure_paths
        assert stage.inputs and stage.outputs and stage.requirement_refs and stage.source_paths
    assert "Review Queue" not in NAVIGATION


def test_ui_has_no_mode_selector_or_query_parameter_execution(project_root):
    # Future source AST contract; no application import/server/browser involved.
    for name in ("app.py","src/stark_t2sql/ui/views.py"):
        source = (project_root/name).read_text(encoding="utf-8")
        tree = ast.parse(source)
        assert not any(isinstance(node,ast.Attribute) and node.attr in {"query_params","experimental_get_query_params"} for node in ast.walk(tree))
        assert not any(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr == "selectbox"
            and any(isinstance(arg,ast.Constant) and isinstance(arg.value,str) and "mode" in arg.value.casefold() for arg in node.args) for node in ast.walk(tree))
