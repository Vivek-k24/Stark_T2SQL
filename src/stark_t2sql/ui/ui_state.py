"""Ephemeral persona UI state and a process-local request guard (FR-10.7).

This source draft has never been invoked by this assignment. The pipeline owns
the additional authoritative single-flight guard shared with CLI/harness paths.
Session state here is navigation/input state, not authentication or persistence.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Lock

from ..config import require_source_file
from ..contracts import SafeResponse


BUSY_KEY = "stark_request_busy"
ANSWER_KEY = "stark_safe_answer"
E0_FILENAME = "STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html"

# Imported modules survive Streamlit script reruns within one process. This is
# deliberately a shared lock rather than a lock constructed in session state.
_UI_REQUEST_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class SubmittedAnswer:
    """Only safe output is retained; a changed persona/input hides old results."""

    persona_name: str
    question: str
    as_of_date: date
    response: SafeResponse


def initialize_state(state: MutableMapping[str, object]) -> None:
    """Recover an abandoned busy flag only when no UI request owns the lock.

    Streamlit session state can outlive an interrupted script run. A stale True
    value must not strand every subsequent rerun behind st.stop(). The global
    nonblocking request lock remains the real concurrency guard; never clear a
    busy flag while any request still holds it.
    """
    if state.get(BUSY_KEY) is True:
        # Acquire rather than check-then-clear: another rerun must not acquire
        # request ownership between the stale check and the state update.
        if _UI_REQUEST_LOCK.acquire(blocking=False):
            try:
                state[BUSY_KEY] = False
            finally:
                _UI_REQUEST_LOCK.release()
    else:
        state.setdefault(BUSY_KEY, False)


def session_is_busy(state: MutableMapping[str, object]) -> bool:
    return state.get(BUSY_KEY) is True


def clear_answer(state: MutableMapping[str, object]) -> None:
    state.pop(ANSWER_KEY, None)


@contextmanager
def request_guard(state: MutableMapping[str, object]) -> Iterator[bool]:
    """Attempt one request without waiting or queuing another model call.

    Set the session flag before control reaches answer(), and reset even when
    cancellation or an exception unwinds the request. A session boolean alone
    cannot protect simultaneous reruns, hence the shared nonblocking lock.
    """

    if session_is_busy(state) or not _UI_REQUEST_LOCK.acquire(blocking=False):
        yield False
        return
    try:
        state[BUSY_KEY] = True
        yield True
    finally:
        try:
            state[BUSY_KEY] = False
        finally:
            _UI_REQUEST_LOCK.release()


def retain_answer(
    state: MutableMapping[str, object],
    *,
    persona_name: str,
    question: str,
    as_of_date: date,
    response: SafeResponse,
) -> None:
    if type(response) is not SafeResponse:
        raise TypeError("The persona UI accepts only an explicit SafeResponse.")
    state[ANSWER_KEY] = SubmittedAnswer(persona_name, question, as_of_date, response)


def current_answer(
    state: MutableMapping[str, object],
    *,
    persona_name: str,
    question: str,
    as_of_date: date,
) -> SafeResponse | None:
    previous = state.get(ANSWER_KEY)
    if type(previous) is not SubmittedAnswer:
        return None
    if (
        previous.persona_name != persona_name
        or previous.question != question
        or previous.as_of_date != as_of_date
    ):
        clear_answer(state)
        return None
    return previous.response


def require_visual_baseline(root: Path) -> Path:
    """Require the real E0 source before a future connected UI startup.

    The supplied source was inspected as text while this E7 draft was authored.
    Presence later is a dependency, not evidence of approval or E1-E6 completion.
    E0 is never copied into Streamlit, rendered, altered, or used as JavaScript.
    """

    return require_source_file(root / E0_FILENAME, label="standalone E0 visual specification")
