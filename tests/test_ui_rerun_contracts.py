"""Rerun/layout unit contracts and real Streamlit AppTest offline exercises.

AppTest executes Streamlit's script runtime without an HTTP server or browser.
Connected views use a synthetic facade only; no model/database is started.
"""

import sys
from types import SimpleNamespace

import pytest

from stark_t2sql.ui.ui_state import ANSWER_KEY, BUSY_KEY, initialize_state, request_guard
from stark_t2sql.ui.views import (
    NAVIGATION, render_persona_selector, render_processing, render_shell,
)


def test_orphaned_session_busy_flag_recovers_when_no_ui_request_is_active():
    state = {BUSY_KEY: True}
    initialize_state(state)
    assert state[BUSY_KEY] is False
    with request_guard(state) as acquired:
        assert acquired is True
    assert state[BUSY_KEY] is False


def test_busy_state_is_not_cleared_while_another_request_owns_ui_lock():
    active = {}
    stale = {BUSY_KEY: True}
    initialize_state(active)
    with request_guard(active) as acquired:
        assert acquired is True
        initialize_state(stale)
        assert stale[BUSY_KEY] is True
        with request_guard(stale) as parallel:
            assert parallel is False
    initialize_state(stale)
    assert stale[BUSY_KEY] is False


def test_base_exception_rerun_releases_guard_and_allows_next_request():
    class StreamlitLikeRerun(BaseException):
        pass

    state = {}
    initialize_state(state)
    with pytest.raises(StreamlitLikeRerun):
        with request_guard(state) as acquired:
            assert acquired is True
            raise StreamlitLikeRerun()
    assert state[BUSY_KEY] is False
    with request_guard(state) as acquired:
        assert acquired is True


class FakeContainer:
    def __init__(self, streamlit, children):
        self.streamlit = streamlit
        self.children = children

    def __enter__(self):
        self.streamlit.stack.append(self.children)
        return self

    def __exit__(self, *args):
        self.streamlit.stack.pop()


class FakeStreamlit:
    def __init__(self):
        self.root = []
        self.sidebar_children = []
        self.stack = [self.root]
        self.sidebar = FakeContainer(self, self.sidebar_children)

    def add(self, kind, label):
        self.stack[-1].append((kind, label))

    def markdown(self, text, **kwargs):
        self.add("markdown", "css")

    def title(self, text):
        self.add("title", text)

    def caption(self, text):
        self.add("caption", text)

    def divider(self):
        self.add("divider", "")

    def radio(self, label, values, **kwargs):
        self.add("radio", label)
        return values[0]

    def container(self):
        children = []
        self.stack[-1].append(("container", children))
        return FakeContainer(self, children)

    def selectbox(self, label, values, **kwargs):
        self.add("selectbox", label)
        return values[0]

    def info(self, message):
        self.add("info", message)

    def button(self, label, **kwargs):
        self.add("button", (label, kwargs))
        return False


def test_selector_is_visually_anchored_above_sidebar_footer(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    navigation, persona_slot = render_shell()
    personas = tuple(SimpleNamespace(display_name=f"Persona {index}") for index in range(4))
    selected = render_persona_selector(
        SimpleNamespace(personas=personas), persona_slot=persona_slot,
    )
    assert navigation == "Health & Status"
    assert selected is personas[0]
    sidebar = fake_st.sidebar_children
    anchor_index = next(i for i, item in enumerate(sidebar) if item[0] == "container")
    footer_index = next(
        i for i, item in enumerate(sidebar)
        if item[0] == "caption" and item[1].startswith("Persona identity is simulated")
    )
    assert anchor_index < footer_index
    assert sidebar[anchor_index][1] == [("selectbox", "Simulated persona")]


def test_processing_view_offers_refresh_without_enabling_another_ask(monkeypatch):
    fake_st = FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    render_processing()
    buttons = [item[1] for item in fake_st.root if item[0] == "button"]
    assert buttons == [
        ("Ask", {"disabled": True, "key": "stark_busy_ask"}),
        ("Refresh status", {"key": "stark_refresh_busy_status"}),
    ]


@pytest.mark.parametrize("during_acquire", (True, False))
def test_session_state_rerun_during_busy_write_cannot_abandon_global_guard(during_acquire):
    class StreamlitLikeRerun(BaseException):
        pass
    class InterruptedState(dict):
        interrupted = False
        def __setitem__(self, key, value):
            if key == BUSY_KEY and value is during_acquire and not self.interrupted:
                self.interrupted = True
                raise StreamlitLikeRerun()
            super().__setitem__(key, value)
    with pytest.raises(StreamlitLikeRerun):
        with request_guard(InterruptedState()):
            pass
    # Independent state must be able to acquire after either set or reset fails.
    with request_guard({}) as acquired:
        assert acquired is True


def test_recovery_state_exception_still_releases_its_temporary_lock():
    class InvalidState(dict):
        def __setitem__(self, key, value):
            raise RuntimeError("TEST_ONLY interrupted stale-state recovery")
    with pytest.raises(RuntimeError):
        initialize_state(InvalidState({BUSY_KEY: True}))
    with request_guard({}) as acquired:
        assert acquired is True


def test_stale_recovery_does_not_race_with_new_request_ownership():
    from stark_t2sql.ui.ui_state import _UI_REQUEST_LOCK
    class RecoveryState(dict):
        def __setitem__(self, key, value):
            if key == BUSY_KEY and value is False:
                # A simultaneous request cannot acquire while stale state is
                # being cleared. This catches a check-then-clear race.
                assert _UI_REQUEST_LOCK.acquire(blocking=False) is False
            super().__setitem__(key, value)
    stale = RecoveryState({BUSY_KEY: True})
    initialize_state(stale)
    assert stale[BUSY_KEY] is False


def test_another_session_cannot_dispatch_even_when_its_own_busy_flag_is_false():
    active, other = {}, {}
    with request_guard(active) as first:
        assert first is True
        initialize_state(other)
        assert other[BUSY_KEY] is False
        with request_guard(other) as second:
            assert second is False
    with request_guard(other) as acquired:
        assert acquired is True


def test_real_streamlit_all_seven_navigation_views_remain_offline(project_root, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("STARK_ENABLE_CONNECTED_UI", raising=False)
    def forbidden():
        raise AssertionError("Offline navigation cannot load a connected runtime")
    monkeypatch.setitem(sys.modules, "stark_t2sql.pipeline.orchestrator", SimpleNamespace(load_persona_runtime=forbidden))
    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()
    assert not app.exception and app.title[0].value == "Local health & status"
    assert tuple(app.sidebar.radio[0].options) == NAVIGATION
    for name in NAVIGATION[1:]:
        app.sidebar.radio[0].set_value(name).run()
        assert not app.exception
        if name == "Offline demo":
            assert app.title[0].value == "Offline E0 demo"
            assert any("SIMULATED" in item.value for item in app.warning)
        if name in {"Playground", "Semantic Catalog", "Access Policy"}:
            assert any("BLOCKED" in item.value for item in app.warning)
            assert not app.selectbox and not app.text_area
    # Actual Streamlit reruns also exercise returning to earlier navigation.
    app.sidebar.radio[0].set_value("Health & Status").run()
    assert not app.exception and app.title[0].value == "Local health & status"


def test_real_streamlit_busy_refresh_never_dispatches_another_ask(project_root, monkeypatch):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("STARK_ENABLE_CONNECTED_UI", raising=False)
    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()
    owner_state = {}
    with request_guard(owner_state) as acquired:
        assert acquired is True
        app.session_state[BUSY_KEY] = True
        app.run()
        assert not app.exception and not app.sidebar.radio
        assert app.button(key="stark_busy_ask").disabled is True
        app.button(key="stark_refresh_busy_status").click().run()
        assert not app.exception and not app.sidebar.radio
        assert app.session_state[BUSY_KEY] is True
        assert owner_state[BUSY_KEY] is True
    app.button(key="stark_refresh_busy_status").click().run()
    assert not app.exception and app.session_state[BUSY_KEY] is False
    assert app.title[0].value == "Local health & status"


@pytest.mark.parametrize("backend_raises", (False, True))
def test_real_streamlit_guarded_dispatch_retains_only_safe_response(project_root, monkeypatch, payroll_persona, backend_raises):
    from dataclasses import replace
    import json
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest
    from stark_t2sql.ui.ui_state import _UI_REQUEST_LOCK
    from .helpers import make_outcome
    monkeypatch.setenv("STARK_ENABLE_CONNECTED_UI", "1")
    personas = tuple(replace(payroll_persona, display_name=f"TEST_ONLY Persona {index}") for index in range(4))
    calls = []
    private = "PRIVATE_SENTINEL SQL password stacktrace driver detail"
    def answer(persona, question, as_of_date):
        import streamlit as st
        assert st.session_state[BUSY_KEY] is True and _UI_REQUEST_LOCK.locked()
        calls.append((persona, question, as_of_date))
        if backend_raises:
            raise RuntimeError(private)
        return make_outcome(persona).to_safe_response()
    facade = SimpleNamespace(personas=personas, answer=answer)
    monkeypatch.setitem(sys.modules, "stark_t2sql.pipeline.orchestrator", SimpleNamespace(load_persona_runtime=lambda: facade))
    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Playground").run()
    assert not app.exception and app.sidebar.selectbox[0].label == "Simulated persona"
    app.text_area(key="stark_question").set_value("TEST_ONLY business question").run()
    assert app.button(key="stark_ask").disabled is False
    app.button(key="stark_ask").click().run()
    assert not app.exception and len(calls) == 1
    assert app.session_state[BUSY_KEY] is False and not _UI_REQUEST_LOCK.locked()
    assert app.button(key="stark_ask").disabled is False
    stored = app.session_state[ANSWER_KEY]
    assert private not in repr(stored)
    assert private not in json.dumps(app.session_state.to_dict(), default=str)
    assert private not in " ".join(item.value for kind in (app.text, app.caption, app.warning, app.error) for item in kind)
    # A plain rerun must not resubmit the last clicked Ask.
    app.run()
    assert not app.exception and len(calls) == 1
