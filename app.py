"""Loopback UI with public offline health/progress and opt-in connected views."""

from __future__ import annotations

from pathlib import Path
import os
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
# Permit the future Streamlit entrypoint to use this repository's src layout
# without installing anything during the source-authoring assignment.
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
    # The request guard and canonical pipeline lock additionally protect
    # concurrent reruns; a warning or session boolean alone is insufficient.
    if session_is_busy(st.session_state):
        render_processing()
        st.stop()

    navigation, persona_slot = render_shell()
    from stark_t2sql.ui.workspace import current_workspace, load_configured_metadata
    load_configured_metadata(st.session_state, root=PROJECT_ROOT)
    workspace = current_workspace(st.session_state)
    from stark_t2sql.ui.project_status import render_health, render_demo
    if navigation == "Health & Status":
        render_health(workspace)
        return
    if navigation == "Offline demo":
        render_demo()
        return
    if navigation == "Settings":
        from stark_t2sql.ui.settings import render_settings
        render_settings(PROJECT_ROOT)
        return
    if navigation in {"Admin Panel", "Login / Signup", "Data Lab"}:
        from stark_t2sql.ui.settings import render_gated_feature
        render_gated_feature(navigation)
        return
    if navigation == "Permission Management":
        from stark_t2sql.ui.permission_management import render_permission_management

        render_permission_management(PROJECT_ROOT)
        return
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
        if workspace is not None:
            application = workspace
            st.caption("DB-verified read-only metadata · checked " + workspace.verified_at)
        elif os.environ.get("STARK_ENABLE_CONNECTED_UI") != "1":
            st.title(navigation)
            st.warning("BLOCKED · Database metadata not authenticated. Open Settings; SQLCoder is not required for metadata.")
            if navigation == "Playground":
                st.text_area("Business question", key="stark_question")
                st.button("Ask", disabled=True, key="stark_ask")
                st.info("No query generated or executed. Authenticate the fixed database in Settings.")
            return
        else:
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
            if workspace is not None:
                from stark_t2sql.ui.project_status import live_service_status
                online = live_service_status()["SQLCoder model"] == "ONLINE"
                ready = online and workspace.generation is not None
                render_playground(application, persona, generation_available=ready,
                    availability_note=workspace.generation_note if online else "SQLCoder offline — no query generated or executed.")
                st.caption("Visible employee count from restricted read-only metadata probe: " + str(workspace.employee_count(persona)))
            else:
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
