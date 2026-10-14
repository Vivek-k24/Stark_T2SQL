"""Public local project health; never imports a DB/model client or reads secrets."""
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

def cached_progress(root=ROOT):
    # ops is a repo-local control plane, deliberately separate from HR pipeline.
    from ops.progress import load
    return load(root)

def health(root=ROOT):
    try: cached_progress(root); progress = "LOCAL READY"
    except Exception: progress = "BLOCKED"
    return {"Architecture & Progress":progress,
            "Streamlit dependency":"LOCAL READY" if find_spec("streamlit") else "BLOCKED",
            "Scripted playground":"DEMO",
            "Agent handoffs":"BLOCKED — requires CLI/auth/sandbox checks and opt-in scheduled task",
            "Secured SQLCoder ↔ PostgreSQL":"BLOCKED — live end-to-end acceptance not established"}

def render_evidence(root=ROOT):
    import streamlit as st
    st.subheader("GitHub-backed remediation progress")
    try: data = cached_progress(root)
    except Exception:
        st.warning("BLOCKED · The local public evidence cache is missing or invalid.")
        return
    if st.button("Refresh public GitHub evidence", key="public_progress_refresh"):
        try:
            from ops.github import GitHub
            from ops.progress import build
            data = build(GitHub())
            st.success("LIVE · Public GitHub evidence refreshed for this view.")
        except Exception: st.warning("GitHub refresh unavailable. Showing cached public evidence.")
    st.caption("FRD 1.8 · LOCAL READY · cached evidence works offline. No HR data is sent to GitHub.")
    for item in data["milestones"]:
        with st.container(border=True):
            st.markdown(f'**{item["gate"]} · {item["state"]} · PR #{item["pr"]}**')
            st.text("Merge commit: " + item.get("merge_sha", "not merged"))
            t = item["tests"]
            st.caption(f'{t["passed"]} passed · {t["failed"]} failed · {t["skipped"]} skipped · {t["scope"]}')
            st.caption("Independent review: " + item["review_verdict"])
            st.link_button("Read versioned evidence", item["evidence_url"])
    st.info("INT-01 · " + data["interim"]["state"])
    st.warning("Agent automation: " + data["automation"]["state"] + ". " + data["automation"]["reason"])
    st.caption("Live PostgreSQL/model acceptance remains unverified. Remediation merges do not mark whole FRD epics complete.")

def render_health():
    import streamlit as st
    st.title("Local health & status")
    st.success("LIVE · This Streamlit page is running locally. This is UI health, not live SQL execution.")
    for feature, status in health().items():
        st.markdown(f"**{feature}:** {status}")
    st.info("Architecture, Progress and the offline demo work without database or model credentials.")
    st.caption("SIMULATED examples never submit SQL. Connected execution requires separately reviewed resources and explicit operator opt-in.")

def render_demo(root=ROOT):
    import streamlit as st
    import streamlit.components.v1 as components
    st.title("Offline E0 demo")
    st.warning("DEMO · STATIC · SIMULATED · Every example result is scripted; no SQL or model call is performed.")
    components.html((root / "STARK_STATIC_UI_PROTOTYPE_E0_EXPANDED.html").read_text(encoding="utf-8"), height=950, scrolling=True)
