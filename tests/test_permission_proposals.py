"""Preview-only admin permission proposals must never execute or approve SQL."""

from pathlib import Path

import pytest

from ops.policy_plan import source_columns
from stark_t2sql.policy.loader import load_policy
from stark_t2sql.ui.permission_proposals import (
    PermissionChange, ProposalError, preview_change,
)


@pytest.fixture
def policy_source(project_root):
    matrix = load_policy(project_root / "policy" / "access_matrix.yaml")
    columns = source_columns(
        (project_root / "schema.sql").read_bytes(), expected_schema=matrix.schema
    )
    return matrix, columns


def test_table_revoke_is_conceptual_only(policy_source):
    matrix, columns = policy_source
    p = preview_change(
        matrix, columns,
        PermissionChange("table_select", "app_payroll", "payroll_results", "revoke"),
    )
    assert p.before == "all columns"
    assert p.after == "none"
    assert p.executable is False
    assert p.matrix_sha256 == matrix.sha256
    assert len(p.proposal_sha256) == 64
    assert any("owner-authorized execution" in item for item in p.blockers)


def test_column_expansion_is_flagged_and_hash_stable(policy_source):
    matrix, columns = policy_source
    change = PermissionChange("column_select", "app_sales_mgr", "employees", "grant", "email")
    p = preview_change(matrix, columns, change)
    assert p.before == "SELECT denied"
    assert p.after == "SELECT permitted"
    assert "expansion" in p.impact.lower()
    assert p.proposal_sha256 == preview_change(matrix, columns, change).proposal_sha256
    assert p.executable is False


def test_rls_row_scope_change_preview(policy_source):
    matrix, columns = policy_source
    p = preview_change(
        matrix, columns,
        PermissionChange(
            "row_scope", "app_hr_bp", "employees",
            proposed_scope="all",
        ),
    )
    assert p.before == "assigned_divisions"
    assert p.after == "all"
    assert "row-level" in p.impact
    assert p.executable is False


@pytest.mark.parametrize(
    "change",
    [
        PermissionChange("table_select", "postgres", "employees", "grant"),
        PermissionChange("table_select", "app_payroll", "pg_authid", "grant"),
        PermissionChange("column_select", "app_sales_mgr", "employees", "grant", "nonexistent"),
        PermissionChange("row_scope", "app_hr_bp", "departments", proposed_scope="all"),
        PermissionChange("row_scope", "app_hr_bp", "employees", proposed_scope="malicious"),
        PermissionChange("table_select", "app_sales_mgr", "employees", "grant"),
    ],
)
def test_unrecognized_or_noop_changes_rejected(policy_source, change):
    matrix, columns = policy_source
    with pytest.raises(ProposalError):
        preview_change(matrix, columns, change)


def test_permission_page_is_only_local_preview(project_root, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.delenv("STARK_ENABLE_CONNECTED_UI", raising=False)
    app = AppTest.from_file(str(project_root / "app.py"), default_timeout=30).run()
    app.sidebar.radio[0].set_value("Permission Management").run()
    assert not app.exception
    assert app.title[0].value == "Permission Management"
    assert any("DESIGN PREVIEW ONLY" in item.value for item in app.warning)
    assert all("Apply" not in b.label and "Approve" not in b.label for b in app.button)
    assert app.button(key="stark_permission_preview") is not None
    app.button(key="stark_permission_preview").click().run()
    assert not app.exception
    assert any("No permission changes" in item.value for item in app.warning)
