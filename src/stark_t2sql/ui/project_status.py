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



def live_service_status(*, timeout_seconds: float = 0.4) -> dict[str, str]:
    """Read-only loopback service checks; never load credentials or a model.

    TCP reachability establishes a PostgreSQL listener, not authentication,
    catalog integrity, RLS enforcement, or readiness for governed queries.
    """
    import http.client
    import os
    import socket

    def local_port(name: str, default: int) -> int | None:
        try:
            port = int(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            return None
        return port if 1024 <= port <= 65535 else None

    def configured_loopback(name: str) -> bool:
        return os.environ.get(name, "127.0.0.1") in {"127.0.0.1", "localhost", "::1"}

    database = "NOT CONFIGURED"
    pg_port = local_port("STARK_PG_PORT", 5433)
    if pg_port is not None and configured_loopback("STARK_PG_HOST"):
        try:
            with socket.create_connection(("127.0.0.1", pg_port), timeout=timeout_seconds):
                database = "LISTENING — authentication not checked"
        except (OSError, TimeoutError):
            database = "OFFLINE"

    model = "NOT CONFIGURED"
    model_port = local_port("STARK_LLAMACPP_PORT", 8081)
    if model_port is not None and configured_loopback("STARK_LLAMACPP_HOST"):
        connection = http.client.HTTPConnection("127.0.0.1", model_port, timeout=timeout_seconds)
        try:
            connection.request("GET", "/health", headers={"Connection": "close"})
            response = connection.getresponse()
            model = "ONLINE" if response.status == 200 else "OFFLINE"
            response.read(256)
        except (OSError, TimeoutError, http.client.HTTPException):
            model = "OFFLINE"
        finally:
            connection.close()
    return {"PostgreSQL listener": database, "SQLCoder model": model}


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
    st.subheader("Live local services")
    for feature, status in live_service_status().items():
        st.markdown(f"**{feature}:** {status}")
    st.caption("PostgreSQL listener reachability does not confirm credentials, policies, or live query readiness.")
    st.subheader("Application readiness")
    for feature, status in health().items():
        st.markdown(f"**{feature}:** {status}")
    st.info("Architecture, Progress and the offline demo work without database or model credentials.")
    st.caption("SIMULATED examples never submit SQL. Connected execution requires separately reviewed resources and explicit operator opt-in.")


def render_demo(root=ROOT):
    from stark_t2sql.ui.offline_demo import render_offline_demo

    render_offline_demo(root)

