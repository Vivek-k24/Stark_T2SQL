"""Streamlit entrypoint source for the E7 FULL-only persona interface.

Authored without execution. The supplied standalone E0 HTML was inspected as
text, and its visual language is translated into native Streamlit source. Future
connected startup requires that source plus the separately governed E0 review
and E1-E6 runtime prerequisites. No E0 source is altered or embedded here.
The NFR-6 exception in the current authoring request permits source drafting
only; it is not permission to run the application or its backend.
"""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
# Permit the future Streamlit entrypoint to use this repository's src layout
# without installing anything during the source-authoring assignment.
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from stark_t2sql.ui.ui_state import initialize_state, require_visual_baseline, session_is_busy
from stark_t2sql.ui.views import (
    REQUEST_UNAVAILABLE,
    SERVICE_UNAVAILABLE,
    render_access_policy,
    render_persona_selector,
    render_playground,
    render_processing,
    render_semantic_catalog,
    render_shell,
)


def main() -> None:
    try:
        import streamlit as st
    except ImportError:
        raise SystemExit("The local Streamlit UI dependency is unavailable.") from None

    st.set_page_config(page_title="STARK T2SQL", page_icon="S", layout="wide")
    initialize_state(st.session_state)

    # FR-10.7: short-circuit before navigation, startup, or any pipeline call.
    # initialize_state() clears only stale flags after the request lock is free.
    # The request guard and canonical pipeline lock independently prevent
    # concurrent requests; a warning/session boolean alone is insufficient.
    if session_is_busy(st.session_state):
        render_processing()
        st.stop()

    navigation, persona_slot = render_shell()
    visual_source_available = False
    try:
        require_visual_baseline(PROJECT_ROOT)
        visual_source_available = True
    except Exception:
        st.warning(
            "The standalone E0 visual specification is unavailable. "
            "Visual translation is pending, and connected persona views are paused."
        )

    # Development planning is public metadata, with no backend privileges or
    # need to load a runtime, read fixture data, or call any local service.
    if navigation == "Architecture":
        from stark_t2sql.ui.architecture import render_architecture

        render_architecture()
        return
    if navigation == "Progress":
        from stark_t2sql.ui.architecture import render_progress

        render_progress()
        return
    if not visual_source_available:
        st.title(navigation)
        st.info("Architecture and Progress remain available as read-only development planning.")
        return

    try:
        # Import only after the real E0 dependency is present. The loader owns
        # all additional source/configuration/evidence dependencies and refuses
        # missing inputs. No raw runtime or credentials enter widgets/state.
        from stark_t2sql.pipeline.orchestrator import load_persona_runtime

        application = load_persona_runtime()
        persona = render_persona_selector(application, persona_slot=persona_slot)
    except Exception:
        st.title(navigation)
        st.warning(SERVICE_UNAVAILABLE)
        st.info("Architecture and Progress remain available as read-only development planning.")
        return
    if persona is None:
        return
    try:
        if navigation == "Playground":
            render_playground(application, persona)
        elif navigation == "Semantic Catalog":
            render_semantic_catalog(application, persona)
        elif navigation == "Access Policy":
            render_access_policy(application, persona)
    except Exception:
        # Rendering/dependency failures also stay behind the persona boundary;
        # no Streamlit exception display is used as a diagnostic surface.
        st.warning(REQUEST_UNAVAILABLE)


if __name__ == "__main__":
    main()
