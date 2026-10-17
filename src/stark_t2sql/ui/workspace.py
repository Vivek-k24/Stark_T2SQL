"""Session-bound capabilities for explicit local read-only operator setup.

This is not app-user authentication. No account, privilege, database policy or
credential is created. A successful inspection authenticates existing database
credentials and returns safe metadata. Passwords never go into session handles,
reports, logs, or process environment. Real account/admin mutations stay gated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import secrets
from threading import Lock
from time import monotonic

from ..config import load_config
from ..contracts import OutcomeStatus, ReasonCode, SafeResponse, StoppingLayer
from ..pipeline.metadata import inspect_metadata


@dataclass(frozen=True)
class Workspace:
    metadata: object = field(repr=False)
    generation: object = field(default=None, repr=False)
    generation_note: str = "Governed inference bindings have not been activated."

    @property
    def personas(self): return self.metadata.personas
    @property
    def verified_at(self): return self.metadata.verified_at
    def semantic_view(self, persona): return self.metadata.semantic_view(persona)
    def policy_view(self, persona): return self.metadata.policy_view(persona)
    def employee_count(self, persona): return self.metadata.employee_count(persona)

    def answer(self, persona, question, as_of_date):
        from .project_status import live_service_status
        if self.generation is None or live_service_status()["SQLCoder model"] != "ONLINE":
            return SafeResponse(status=OutcomeStatus.MODEL_ERROR, stopping_layer=StoppingLayer.MODEL,
                                reason_code=ReasonCode.MODEL_UNAVAILABLE, as_of_date=as_of_date)
        return self.generation.answer(persona, question, as_of_date)


class WorkspaceStore:
    """Opaque handles require the same server-assigned Streamlit session ID."""
    def __init__(self, *, ttl_seconds=1800, maximum=32, clock=monotonic):
        self._entries = {}
        self._lock = Lock()
        self._clock, self._ttl, self._maximum = clock, ttl_seconds, maximum

    def _expire(self):
        now = self._clock()
        self._entries = {key: value for key, value in self._entries.items() if value[2] > now}

    def put(self, session_id, workspace):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("A server-bound browser session is required.")
        with self._lock:
            self._expire()
            for key in tuple(self._entries):
                if self._entries[key][0] == session_id: del self._entries[key]
            if len(self._entries) >= self._maximum:
                del self._entries[min(self._entries, key=lambda key: self._entries[key][2])]
            token = secrets.token_urlsafe(32)
            self._entries[token] = (session_id, workspace, self._clock() + self._ttl)
            return token

    def get(self, session_id, token):
        with self._lock:
            self._expire()
            item = self._entries.get(token) if type(token) is str else None
            return item[1] if item is not None and item[0] == session_id else None

    def remove(self, session_id, token):
        with self._lock:
            item = self._entries.get(token) if type(token) is str else None
            if item is not None and item[0] == session_id: del self._entries[token]


STORE = WorkspaceStore()
HANDLE_KEY = "stark_workspace_handle"
NOTICE_KEY = "stark_setup_notice"
PASSWORD_KEYS = ("stark_setup_admin", "stark_setup_payroll", "stark_setup_hr", "stark_setup_sales")
_ATTEMPTS = {}
_ATTEMPT_LOCK = Lock()


def session_identity():
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    context = get_script_run_ctx(suppress_warning=True)
    return context.session_id if context is not None else None


def current_workspace(state, *, session_id=None):
    return STORE.get(session_identity() if session_id is None else session_id, state.get(HANDLE_KEY))


def _allow_attempt(session_id):
    # Bound repeated privileged authentication attempts, including new tabs.
    with _ATTEMPT_LOCK:
        now = monotonic()
        for key in tuple(_ATTEMPTS):
            _ATTEMPTS[key] = [stamp for stamp in _ATTEMPTS[key] if now - stamp < 60]
            if not _ATTEMPTS[key]: del _ATTEMPTS[key]
        if len(_ATTEMPTS.get(session_id, ())) >= 5 or sum(map(len, _ATTEMPTS.values())) >= 20:
            raise ValueError("Setup checks are rate limited. Wait one minute.")
        _ATTEMPTS.setdefault(session_id, []).append(now)


def connect_from_form(state, *, root, session_id=None):
    """Form callback: clear password widgets before any result or rerun."""
    sid = session_identity() if session_id is None else session_id
    passwords = tuple(state.pop(key, "") for key in PASSWORD_KEYS)
    values = {}
    try:
        if not sid or any(not value for value in passwords):
            raise ValueError("Existing role credentials are required.")
        _allow_attempt(sid)
        values = {"STARK_PG_HOST": "127.0.0.1", "STARK_PG_PORT": "5433", "STARK_PG_DATABASE": "stark_test",
            "STARK_ADMIN_PASSWORD": passwords[0], "STARK_PAYROLL_PASSWORD": passwords[1],
            "STARK_HR_PASSWORD": passwords[2], "STARK_SALES_PASSWORD": passwords[3],
            "STARK_DATABASE_WORK_MEM_KIB": str(state.get("stark_setup_work", 4096)),
            "STARK_DATABASE_TEMP_FILE_LIMIT_KIB": str(state.get("stark_setup_temp", 65536)),
            "STARK_RESOURCE_MEASUREMENTS_PATH": state.get("stark_setup_measurements", "")}
        config = load_config(root=root, environment=values)
        metadata = inspect_metadata(config, installation_binding=Path(state.get("stark_setup_binding", "")), environment=values)
        generation, note = None, "Governed inference bindings have not been activated."
        if state.get("stark_setup_inference") is True:
            from .project_status import live_service_status
            if live_service_status()["SQLCoder model"] != "ONLINE":
                note = "SQLCoder offline — no query generated or executed."
            else:
                try:
                    from ..pipeline.orchestrator import compose_persona_runtime, load_runtime_source_inputs
                    values.update(STARK_GGUF_PATH=state.get("stark_setup_model", ""),
                                  STARK_MODEL_MEMORY_LIMIT_MIB=str(state.get("stark_setup_model_memory", 0)))
                    config = load_config(root=root, environment=values)
                    inputs = load_runtime_source_inputs(Path(state.get("stark_setup_runtime", "")), root=Path(root))
                    reference = inputs.parser_approval.review_reference.lower().replace("_", " ").replace("-", " ")
                    if "test only" in reference or inputs.admin_password_environment_variable != "STARK_ADMIN_PASSWORD":
                        raise ValueError("Genuine production review inputs are required.")
                    generation = compose_persona_runtime(config, inputs, environment=values)
                    note = "Governed FULL runtime composed; each request still checks model and database enforcement."
                except Exception:
                    note = "Inference unavailable: verify genuine model, parser, memory and runtime bindings. Metadata remains available."
        state[HANDLE_KEY] = STORE.put(sid, Workspace(metadata, generation, note))
        state[NOTICE_KEY] = "VERIFIED · Authenticated PostgreSQL, installed policy and four persona metadata checked read-only."
    except Exception:
        STORE.remove(sid, state.pop(HANDLE_KEY, None))
        state[NOTICE_KEY] = "BLOCKED · Read-only setup failed or is rate limited. Check credentials, installation binding and measured settings. No policy or data changed."
    finally:
        values.clear()
        passwords = ()


def disconnect(state, *, session_id=None):
    STORE.remove(session_identity() if session_id is None else session_id, state.pop(HANDLE_KEY, None))
    for key in PASSWORD_KEYS: state.pop(key, None)
    state[NOTICE_KEY] = "Disconnected. This browser session holds no workspace capability."


def load_configured_metadata(state, *, root):
    """Reuse explicitly configured server credentials without populating widgets.

    A configured single-user local app may publish the four simulated persona
    metadata views. This confers no app-user/admin approval or write capability.
    No credentials or paths are discovered, generated or persisted here.
    """
    import os
    if os.environ.get("STARK_TEST_ENABLE_DB_INTEGRATION") == "0":
        return
    if state.get("stark_configured_metadata_attempted"):
        return
    required = ("STARK_ADMIN_PASSWORD", "STARK_PAYROLL_PASSWORD", "STARK_HR_PASSWORD", "STARK_SALES_PASSWORD",
                "STARK_INSTALLATION_BINDING_PATH", "STARK_RESOURCE_MEASUREMENTS_PATH")
    if not all(os.environ.get(key) for key in required): return
    if (os.environ.get("STARK_PG_DATABASE") != "stark_test" or os.environ.get("STARK_PG_PORT") != "5433"
            or os.environ.get("STARK_PG_HOST", "127.0.0.1") != "127.0.0.1"): return
    state["stark_configured_metadata_attempted"] = True
    private = {key: os.environ[name] for key, name in zip(PASSWORD_KEYS, required[:4])}
    private.update(stark_setup_measurements=os.environ["STARK_RESOURCE_MEASUREMENTS_PATH"],
                   stark_setup_binding=os.environ["STARK_INSTALLATION_BINDING_PATH"],
                   stark_setup_work=os.environ.get("STARK_DATABASE_WORK_MEM_KIB", "4096"),
                   stark_setup_temp=os.environ.get("STARK_DATABASE_TEMP_FILE_LIMIT_KIB", "65536"))
    try:
        connect_from_form(private, root=root)
        for key in (HANDLE_KEY, NOTICE_KEY):
            if key in private: state[key] = private[key]
    finally:
        private.clear()
