"""FULL-only persona views using explicit safe projections (FR-8/FR-10).

The supplied E0 HTML was inspected as text for its navy navigation, blue
accent, light cards, request/outcome split, and list/inspector hierarchy.
Its design is translated into native Streamlit containers and local styling.
No HTML/JavaScript from E0 is copied here; no backend object enters a widget.
The user's NFR-6 exception permits drafting only, not runtime activity.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Protocol

from ..config import FIXTURE_AS_OF_DATE
from ..contracts import OutcomeStatus, Persona, ReasonCode, RowScopeKind, SafeResponse, StoppingLayer
from .ui_state import clear_answer, current_answer, request_guard, retain_answer

if TYPE_CHECKING:
    from streamlit.delta_generator import DeltaGenerator

    from ..pipeline.response import SafeConcept, SafePolicyRow


class PersonaViewApplication(Protocol):
    """Small UI capability: no executor, connections, catalog, or mode input."""

    @property
    def personas(self) -> tuple[Persona, ...]: ...

    def answer(self, persona: Persona, question: str, as_of_date: date) -> SafeResponse: ...

    def semantic_view(self, persona: Persona) -> tuple[SafeConcept, ...]: ...

    def policy_view(self, persona: Persona) -> tuple[SafePolicyRow, ...]: ...


NAVIGATION = ("Playground", "Semantic Catalog", "Access Policy", "Architecture", "Progress")
SERVICE_UNAVAILABLE = "A required local resource is unavailable. Connected views are paused."
REQUEST_UNAVAILABLE = "The request could not be completed. Try again when the local services are available."


# Independently authored CSS translating the supplied E0 design language.
# System fonts and native Streamlit widgets need no external font/image URL.
_LOCAL_CSS = """
<style>
  .stApp { background: #f3f6fb; color: #172439; font-family: "Segoe UI", system-ui, sans-serif; }
  .block-container { max-width: 106rem; padding: 2rem 3rem 3.5rem; }
  [data-testid="stSidebar"] { background: #102039; border-right: 1px solid #29384e; }
  [data-testid="stSidebar"] h1,
  [data-testid="stSidebar"] h2,
  [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] { color: #eef5ff; }
  [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
  [data-testid="stSidebar"] label { color: #adbed4; }
  [data-testid="stSidebar"] [role="radiogroup"] > label {
    padding: .7rem .9rem; border-radius: .65rem; margin: .15rem 0;
  }
  [data-testid="stSidebar"] [role="radiogroup"] > label:has(input:checked) {
    background: #2e466b; color: #ffffff;
  }
  [data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff; border-radius: 15px; border-color: #e1e8f1;
    box-shadow: 0 8px 34px rgba(31,51,80,.042);
  }
  [data-testid="stMain"] h1 { font-size: 1.7rem; letter-spacing: -.04rem; }
  [data-testid="stMain"] h3 { font-size: 1rem; letter-spacing: -.015rem; }
  [data-testid="stMain"] [data-testid="stCaptionContainer"] { color: #65748a; }
  [data-testid="stMain"] input,
  [data-testid="stMain"] textarea { background: #ffffff; color: #172439; border-radius: 10px; }
  [data-testid="stBaseButton-primary"] {
    background: #355ed8; border-color: #355ed8; color: #ffffff; border-radius: 10px;
  }
  [data-testid="stBaseButton-primary"]:hover { background: #2748ba; border-color: #2748ba; }
  button:focus-visible, input:focus-visible, textarea:focus-visible {
    outline: 3px solid #9bb4ff !important; outline-offset: 3px;
  }
  @media (min-width: 900px) {
    [data-testid="stSidebar"] { min-width: 244px; max-width: 244px; }
  }
  @media (max-width: 760px) {
    .block-container { padding: 1.25rem 1rem 2rem; }
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
      min-width: min(100%, 23rem); flex: 1 1 100%;
    }
  }
</style>
"""


def render_shell() -> tuple[str, DeltaGenerator]:
    """Render sidebar once and reserve the persona selector above footer notes.

    Streamlit containers are positional anchors: connected runtime loading can
    happen later without forcing a persona widget into the sidebar footer.
    """
    import streamlit as st

    st.markdown(_LOCAL_CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.title("stark.")
        st.caption("Text-to-SQL workspace")
        st.divider()
        st.caption("CONNECTED WORKSPACE")
        selected = st.radio("Navigation", NAVIGATION, key="stark_navigation")
        st.divider()
        persona_slot = st.container()
        st.caption("Persona identity is simulated. This application does not provide authentication.")
        st.caption("FULL is the only connected request mode.")
    return selected, persona_slot


def render_page_heading(title: str, description: str) -> None:
    import streamlit as st

    st.caption("STARK CONSULTANTS / OFFLINE WORKSPACE")
    st.title(title)
    st.caption(description)
    st.divider()


def render_persona_selector(
    application: PersonaViewApplication, *, persona_slot: DeltaGenerator,
) -> Persona | None:
    import streamlit as st

    # Names are the only widget values; fixture-resolved Persona objects stay
    # local to this call. No arbitrary ID, role, login, or URL input is accepted.
    personas = application.personas
    names = tuple(persona.display_name for persona in personas)
    if len(personas) != 4 or len(set(names)) != 4:
        st.warning(SERVICE_UNAVAILABLE)
        return None
    with persona_slot:
        selected_name = st.selectbox("Simulated persona", names, key="stark_persona_name")
    return next(persona for persona in personas if persona.display_name == selected_name)


def render_processing() -> None:
    import streamlit as st

    st.info("Processing a question. Only one request can run at a time.")
    st.button("Ask", disabled=True, key="stark_busy_ask")
    # Provides a user-initiated rerun even if an earlier script's pending
    # result never triggered a UI refresh; it does not bypass the global lock.
    st.button("Refresh status", key="stark_refresh_busy_status")


def render_safe_response(response: SafeResponse) -> None:
    """Render fields individually; never serialize a runtime outcome wholesale."""

    import streamlit as st

    if type(response) is not SafeResponse:
        st.error(REQUEST_UNAVAILABLE)
        return
    if response.status is OutcomeStatus.ANSWERED:
        if response.row_scope not in (None, RowScopeKind.ALL):
            st.info("Scoped result")
        else:
            st.success("Allowed")
    elif response.status in (OutcomeStatus.BLOCKED_VALIDATOR, OutcomeStatus.BLOCKED_DB):
        st.error("Blocked")
    elif response.status is OutcomeStatus.CLARIFICATION_REQUIRED:
        st.warning("Clarification needed")
    else:
        st.warning("Answer unavailable")

    # These messages come from the contract's fixed public-message allowlist.
    st.text(response.message)
    st.caption(
        f"{response.status.value} · {response.stopping_layer.value} · {response.reason_code.value}"
    )
    st.caption(f"As of {response.as_of_date.isoformat()}")
    if response.scope_note:
        st.text(response.scope_note)
    if response.clarification is not None:
        st.text(response.clarification.question)
        for option in response.clarification.options:
            st.text(option)
        st.caption("Edit the question to clarify the business meaning, then ask again.")
    if response.status is OutcomeStatus.ANSWERED:
        if response.truncation_note:
            st.warning(response.truncation_note)
        if response.columns:
            # Streamlit's table dependency is used only for already authorized
            # result cells. The safe contract handles dates/Decimal explicitly.
            import pandas as pd

            public_cells = response.to_dict()["rows"]
            frame = pd.DataFrame(public_cells, columns=list(response.columns))
            st.dataframe(frame, hide_index=True, use_container_width=True)
        if not response.rows:
            st.info("No permitted rows matched this question.")
    if response.elapsed_ms is not None:
        st.caption(f"Elapsed time: {response.elapsed_ms / 1000:.2f} seconds")


def render_playground(application: PersonaViewApplication, persona: Persona) -> None:
    import streamlit as st

    render_page_heading(
        "Query playground",
        "Ask one business question within the selected persona's permitted scope.",
    )
    inputs_column, outcome_column = st.columns((0.92, 1.28), gap="medium")
    with inputs_column:
        with st.container(border=True):
            st.subheader("01 / Request builder")
            st.caption("FULL · governed request path")
            st.divider()
            st.text("Acting as " + persona.display_name)
            as_of_date = st.date_input("As-of date", value=FIXTURE_AS_OF_DATE, key="stark_as_of_date")
            question = st.text_area("Business question", height=160, key="stark_question")
            st.caption("The question and explicit date are sent unchanged to the governed pipeline.")
            button_slot = st.empty()
            submitted = button_slot.button(
                "Ask", type="primary", disabled=not question.strip() or type(as_of_date) is not date,
                key="stark_ask"
            )
            response = current_answer(
                st.session_state,
                persona_name=persona.display_name,
                question=question,
                as_of_date=as_of_date,
            )
            if submitted:
                with request_guard(st.session_state) as acquired:
                    if not acquired:
                        st.info("A question is already processing. Wait for it to finish before asking again.")
                        return
                    clear_answer(st.session_state)
                    # The busy flag is already true. Replacing the button
                    # disables the visible control before the blocking call.
                    button_slot.button("Ask", disabled=True, key="stark_processing_ask")
                    with st.spinner("Processing the question through the governed local pipeline…"):
                        try:
                            # Exact question/date remain unchanged. This facade
                            # delegates only to canonical FULL, with no mode input.
                            response = application.answer(persona, question, as_of_date)
                            retain_answer(
                                st.session_state,
                                persona_name=persona.display_name,
                                question=question,
                                as_of_date=as_of_date,
                                response=response,
                            )
                        except Exception:
                            # No exception string, SQL, trace, or runtime object
                            # reaches the UI or ordinary persona session state.
                            response = SafeResponse(
                                status=OutcomeStatus.ERROR,
                                stopping_layer=StoppingLayer.INTERNAL,
                                reason_code=ReasonCode.INTERNAL_ERROR,
                                as_of_date=as_of_date,
                            )
                            retain_answer(
                                st.session_state,
                                persona_name=persona.display_name,
                                question=question,
                                as_of_date=as_of_date,
                                response=response,
                            )
                # Finally has released state and lock, including on an
                # interruption. Rerun redraws the enabled Ask control.
                st.rerun()
    with outcome_column:
        with st.container(border=True):
            st.subheader("02 / Safe outcome")
            st.caption("Authorized results · scope · explicit date")
            st.divider()
            if response is None:
                st.info("Ask a question to see its decision and permitted result.")
            else:
                render_safe_response(response)


def render_semantic_catalog(application: PersonaViewApplication, persona: Persona) -> None:
    import streamlit as st

    render_page_heading("Governed semantic catalog", "Read-only business definitions available to the selected persona.")
    try:
        concepts = application.semantic_view(persona)
    except Exception:
        st.warning(SERVICE_UNAVAILABLE)
        return
    # Search and selector options are derived only from the filtered safe
    # projection. No blocked name or count is revealed by this explorer.
    kinds = tuple(sorted({concept.kind for concept in concepts}))
    with st.container(border=True):
        type_column, search_column = st.columns((1, 1.5))
        with type_column:
            selected_kind = st.selectbox(
                "Definition type", ("All permitted types", *kinds), key="stark_concept_kind"
            )
        with search_column:
            search = st.text_input("Search definition or synonym", key="stark_concept_search").casefold()
    available = tuple(
        concept for concept in concepts
        if (selected_kind == "All permitted types" or concept.kind == selected_kind)
        and (not search or search in " ".join((concept.name, concept.description, *concept.aliases)).casefold())
    )
    if not available:
        st.info("No permitted concepts match this selection.")
        return
    entries_column, inspector_column = st.columns((0.8, 1.2), gap="medium")
    with entries_column:
        with st.container(border=True):
            st.subheader("Catalog entries")
            st.caption("Permitted definitions")
            names = tuple(concept.name for concept in available)
            selected_name = st.radio("Governed concept", names, key="stark_concept_name")
    concept = next(concept for concept in available if concept.name == selected_name)
    with inspector_column:
        with st.container(border=True):
            st.subheader("Semantic contract inspector")
            st.caption("Governed business meaning")
            st.divider()
            st.text(concept.name)
            st.text(concept.description)
            st.caption("Available within the selected persona's permitted scope.")
            if concept.aliases:
                st.text("Business vocabulary: " + ", ".join(concept.aliases))
            if concept.units is not None:
                st.text("Units: " + concept.units)
            if concept.aggregation is not None:
                st.text("Aggregation: " + concept.aggregation)
            if concept.grain:
                st.text("Grain: " + ", ".join(concept.grain))
            for note in concept.date_notes:
                st.text(note)


def render_access_policy(application: PersonaViewApplication, persona: Persona) -> None:
    import streamlit as st

    render_page_heading("Access policy", "Read-only table, column, and row entitlements for the selected persona.")
    try:
        policies = application.policy_view(persona)
    except Exception:
        st.warning(SERVICE_UNAVAILABLE)
        return
    if not policies:
        st.info("No permitted policy metadata is available.")
        return
    entries_column, inspector_column = st.columns((0.8, 1.2), gap="medium")
    with entries_column:
        with st.container(border=True):
            st.subheader("Permitted objects")
            st.caption("Read-only access metadata")
            names = tuple(policy.table for policy in policies)
            selected_name = st.radio("Permitted table", names, key="stark_policy_table")
    policy = next(policy for policy in policies if policy.table == selected_name)
    with inspector_column:
        with st.container(border=True):
            st.subheader("Object policy inspector")
            st.caption("Permitted columns and row scope")
            st.divider()
            st.text("Table: " + policy.table)
            st.text(policy.scope_note)
            st.caption("Selected persona permission: read-only SELECT within this scope.")
            if st.checkbox("Show permitted columns", value=True, key="stark_show_columns"):
                for column in policy.columns:
                    st.text(column)
    st.caption("Metadata describes configured permissions. Enforcement belongs to the validator and database.")
