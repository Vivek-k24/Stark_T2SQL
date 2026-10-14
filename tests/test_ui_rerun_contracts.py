"""ISS-17 rerun recovery and sidebar layout regressions.

Mock the Streamlit presentation surface; never launch Streamlit, inference,
PostgreSQL, a browser, or a persona backend.
"""

import sys
from types import SimpleNamespace

import pytest

from stark_t2sql.ui.ui_state import BUSY_KEY, initialize_state, request_guard
from stark_t2sql.ui.views import (
    render_persona_selector, render_processing, render_shell,
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
    assert navigation == "Playground"
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
