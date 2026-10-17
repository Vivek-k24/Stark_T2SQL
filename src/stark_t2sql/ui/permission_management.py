"""Non-executable administrative proposal preview for fixed STARK policy.

The page intentionally offers no save, approve or apply action until real,
server-validated administrator sessions and an auditable review store exist.
Viewing or using this page never constitutes administrator authorization.
"""

from __future__ import annotations

from pathlib import Path

from .permission_proposals import PermissionChange, ProposalError, preview_change

ROOT = Path(__file__).resolve().parents[3]


def render_permission_management(root: Path = ROOT) -> None:
    import streamlit as st

    st.title("Permission Management")
    st.warning(
        "DESIGN PREVIEW ONLY — administrator authentication, persistent requests, "
        "independent approvals and database application are not implemented. "
        "No permission changes can be saved, approved or executed."
    )
    st.caption(
        "Fixed public schema · 3 PostgreSQL business roles · 4 simulated personas. "
        "This page reads the versioned policy source, NOT live PostgreSQL permissions."
    )
    try:
        from ops.policy_plan import source_columns
        from stark_t2sql.policy.loader import load_policy

        matrix = load_policy(root / "policy" / "access_matrix.yaml")
        schema_columns = source_columns(
            (root / "schema.sql").read_bytes(), expected_schema=matrix.schema
        )
    except Exception:
        st.error("The authoritative policy source or schema is unavailable.")
        return

    with st.container(border=True):
        st.subheader("Draft proposed change")
        st.caption("Local preview only; proposals are not persisted or submitted.")
        kind_label = st.selectbox(
            "Permission type",
            ("Table SELECT", "Column SELECT", "Row-level scope"),
            key="stark_permission_kind",
        )
        kind = {
            "Table SELECT": "table_select",
            "Column SELECT": "column_select",
            "Row-level scope": "row_scope",
        }[kind_label]
        role = st.selectbox(
            "Business role", tuple(item.name for item in matrix.roles),
            key="stark_permission_role",
        )
        available_tables = (
            tuple(table for table in matrix.rls_tables if table in matrix.role(role).tables)
            if kind == "row_scope" else tuple(matrix.tables)
        )
        if not available_tables:
            st.info("No supported table for this change.")
            return
        table = st.selectbox("Table", available_tables, key="stark_permission_table")
        operation = ""
        column = ""
        proposed_scope = ""
        if kind == "row_scope":
            from stark_t2sql.contracts import RowScopeKind
            proposed_scope = st.selectbox(
                "Proposed row scope", tuple(scope.value for scope in RowScopeKind),
                key="stark_permission_scope",
            )
        else:
            operation = st.selectbox(
                "Proposed SELECT change", ("grant", "revoke"),
                key="stark_permission_operation",
            )
            if kind == "column_select":
                columns = tuple(schema_columns.get(table, ()))
                if not columns:
                    st.error("Schema columns are unavailable.")
                    return
                column = st.selectbox(
                    "Column", columns, key="stark_permission_column"
                )
        if st.button("Preview change — no database writes", key="stark_permission_preview"):
            try:
                preview = preview_change(
                    matrix, schema_columns,
                    PermissionChange(kind, role, table, operation, column, proposed_scope),
                )
            except ProposalError as exc:
                st.info(str(exc))
                return
            st.subheader("Source matrix change preview")
            st.text(f"Role: {preview.role} · Table: {preview.table}")
            st.text(f"Before: {preview.before}")
            st.text(f"Proposed: {preview.after}")
            st.warning(preview.impact)
            st.caption("Proposal SHA-256: " + preview.proposal_sha256)
            st.caption("Source matrix SHA-256: " + preview.matrix_sha256)
            for blocker in preview.blockers:
                st.text("BLOCKED · " + blocker)
            assert preview.executable is False
    st.info(
        "Future workflow: submit → impact review → security approval → "
        "independent owner approval → backed-up, digest-locked execution → "
        "PostgreSQL policy verification and negative access probes. "
        "No execution path exists in this page."
    )
