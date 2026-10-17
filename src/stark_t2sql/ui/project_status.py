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
        "Optional offline demo": "SIMULATED — separate from real questions",
        "Governed SQL execution": "Requires current model health and genuine reviewed runtime bindings",
    }



def live_service_status(*, timeout_seconds: float = 0.4) -> dict[str, str]:
    """Read-only loopback service checks; never load credentials or a model.

    TCP reachability establishes a PostgreSQL listener, not authentication,
    catalog integrity, RLS enforcement, or readiness for governed queries.
    """
    import http.client
    import os
    import socket
    import math
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 2:
        raise ValueError("Health checks require a bounded positive timeout.")

    def local_port(name: str, default: int) -> int | None:
        try:
            port = int(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            return None
        return port if 1024 <= port <= 65535 else None

    def configured_loopback(name: str) -> bool:
        return os.environ.get(name, "127.0.0.1") == "127.0.0.1"

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
        connection = None
        try:
            connection = http.client.HTTPConnection("127.0.0.1", model_port, timeout=timeout_seconds)
            connection.request("GET", "/health", headers={"Connection": "close"})
            response = connection.getresponse()
            model = "ONLINE" if response.status == 200 else "LOADING" if response.status == 503 else "OFFLINE"
            response.read(256)
        except (OSError, TimeoutError, http.client.HTTPException):
            model = "OFFLINE"
        finally:
            if connection is not None:
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
    st.caption("Historical gate evidence. Check Health & Status for current services and authenticated policy inspection.")


def render_health(workspace=None):
    import streamlit as st
    st.title("Local health & status")
    st.success("LIVE · This Streamlit page is running locally. This is UI health, not live SQL execution.")
    st.subheader("Live local services")
    for feature, status in live_service_status().items():
        st.markdown(f"**{feature}:** {status}")
    st.caption("PostgreSQL listener reachability does not confirm credentials, policies, or live query readiness.")
    st.subheader("Authenticated database capability")
    if workspace is None:
        st.info("NOT CHECKED · Open Settings to authenticate existing roles and verify installed policy read-only.")
    else:
        st.success("VERIFIED · PostgreSQL authenticated; installed policy, restricted logins and four personas inspected.")
        st.caption("Read-only snapshot checked at " + workspace.verified_at + ". Refresh verification by submitting Settings again.")
        st.text(workspace.generation_note)
    st.subheader("Application readiness")
    for feature, status in health().items():
        st.markdown(f"**{feature}:** {status}")
    st.info("Database metadata and model inference are independent capabilities. SQLCoder is never started by rendering this app.")
    st.caption("The Offline demo is explicitly SIMULATED. Real questions require an online model and the reviewed FULL runtime.")


def render_demo(root=ROOT):
    from stark_t2sql.ui.offline_demo import render_offline_demo

    render_offline_demo(root)

