"""Read-only local health and manually maintained public progress."""
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def cached_progress(root=ROOT):
    from ops.progress import load
    return load(root)


def health(root=ROOT):
    try:
        cached_progress(root)
        progress = "LOCAL READY"
    except Exception:
        progress = "BLOCKED"
    return {
        "Architecture & Progress": progress,
        "Streamlit dependency": "LOCAL READY" if find_spec("streamlit") else "BLOCKED",
        "Scripted playground": "DEMO",
        "Secured SQLCoder ↔ PostgreSQL": "BLOCKED — live end-to-end acceptance not established",
    }


def render_evidence(root=ROOT):
    import streamlit as st
    st.subheader("Reviewed remediation progress")
    try:
        data = cached_progress(root)
    except Exception:
        st.warning("BLOCKED · The local progress record is missing or invalid.")
        return
    st.caption("FRD 1.8 · Manually maintained from versioned GitHub evidence; "
               "this view works offline and never dispatches agents.")
    for item in data["milestones"]:
        with st.container(border=True):
            st.markdown(f'**{item["gate"]} · {item["state"]} · PR #{item["pr"]}**')
            st.text("Merge commit: " + item.get("merge_sha", "not merged"))
            t = item["tests"]
            st.caption(f'{t["passed"]} passed · {t["failed"]} failed · {t["skipped"]} skipped · {t["scope"]}')
            st.caption("Independent review: " + item["review_verdict"])
            st.link_button("Read versioned evidence", item["evidence_url"])
    st.info("INT-01 · " + data["interim"]["state"])
    st.caption("Actual SQLCoder/PostgreSQL integration remains unverified. "
               "Remediation merges do not mark whole FRD epics complete.")


def render_health():
    import streamlit as st
    st.title("Local health & status")
    st.success("LIVE · This Streamlit page is running locally. This is UI health, not live SQL execution.")
    for feature, status in health().items():
        st.markdown(f"**{feature}:** {status}")
    st.info("Architecture, Progress and the offline demo work without database or model credentials.")
    st.caption("SIMULATED examples never submit SQL. Connected execution requires separately reviewed resources and explicit operator opt-in.")


def render_demo(root=ROOT):
    from stark_t2sql.ui.offline_demo import render_offline_demo

    render_offline_demo(root)

