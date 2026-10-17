"""Explicit read-only setup for one local STARK application; no admin writes."""
from pathlib import Path
from .workspace import NOTICE_KEY, connect_from_form, current_workspace, disconnect


def render_settings(root: Path):
    import streamlit as st
    st.title("Settings")
    st.info("Local operator setup · fixed 127.0.0.1:5433/stark_test · read-only checks only.")
    st.caption("Use existing database credentials. This does not create accounts or change roles, passwords, policies or services. "
               "Passwords are masked, removed from widget state on submit, and never saved to disk or process environment.")
    active = current_workspace(st.session_state)
    if active:
        st.success("Database metadata verified at " + active.verified_at)
        st.button("Disconnect this session", on_click=disconnect, args=(st.session_state,))
    if NOTICE_KEY in st.session_state: st.text(st.session_state[NOTICE_KEY])
    with st.form("stark_readonly_setup"):
        st.text("Fixed target: public schema · 12 fixture tables · 4 simulated personas")
        st.text_input("Existing postgres password — trusted metadata only", type="password", key="stark_setup_admin")
        st.text_input("Existing Payroll login password", type="password", key="stark_setup_payroll")
        st.text_input("Existing HR login password", type="password", key="stark_setup_hr")
        st.text_input("Existing Sales login password", type="password", key="stark_setup_sales")
        st.text_input("Reviewed installation binding JSON", value=r"H:\STARK_Runtime\stark_policy_installation_binding_20261016.json", key="stark_setup_binding")
        st.text_input("Actual resource measurement file", value=r"H:\STARK_Runtime\stark_pg_resource_20261016_171019.txt", key="stark_setup_measurements")
        st.number_input("Installed work memory (KiB)", min_value=1, value=4096, key="stark_setup_work")
        st.number_input("Installed temporary-file limit (KiB)", min_value=0, value=65536, key="stark_setup_temp")
        st.checkbox("Explicitly enable governed FULL inference when the model is already online", key="stark_setup_inference")
        st.caption("Never starts SQLCoder. Metadata checks work without model files, a model memory declaration or parser approval.")
        with st.expander("Optional existing model/runtime inputs"):
            st.text_input("Genuine runtime binding JSON", key="stark_setup_runtime")
            st.text_input("Existing SQLCoder GGUF file", value=r"H:\STARK_Runtime\models\sqlcoder-7b-2.Q4_K_M.gguf", key="stark_setup_model")
            st.number_input("Independently approved enforced model memory (MiB)", min_value=0, value=0, key="stark_setup_model_memory")
            st.caption("Zero means unavailable. Do not reuse the unsafe 9,216-context / 6,144-MiB setup without approved RAM preflight.")
        st.form_submit_button("Verify database and load metadata — no changes", on_click=connect_from_form,
                              args=(st.session_state,), kwargs={"root": root})


def render_gated_feature(name):
    import streamlit as st
    st.title(name)
    if name == "Admin Panel":
        st.warning("BLOCKED · Real application administrator authentication and approval storage are not enabled.")
        st.text("A simulated persona, a navigation choice, or a database metadata check grants no application administrator authority.")
        st.button("Manage accounts — security review required", disabled=True)
    elif name == "Login / Signup":
        st.warning("NOT IMPLEMENTED · Real local user authentication requires independent threat-model and enablement review.")
        st.text("No accounts or sessions are created here. Signup must initially grant zero persona, database or administrator privileges.")
        st.button("Create account — review required", disabled=True)
    elif name == "Data Lab":
        st.warning("NOT IMPLEMENTED · Faker diversification requires a deterministic preview/export contract and separate clone activation approval.")
        st.text("The authoritative 12-table fixture is preserved. No database reset, seed, restore or write action exists on this page.")
        st.button("Generate database — separately approved clone required", disabled=True)
