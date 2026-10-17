"""Source-matrix permission change preview.

Pure, non-executable draft design for the local admin workflow. A preview is
NOT a database authorization decision, approved migration or SQL statement.
This module has no connection, filesystem, authentication, or execution code.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping

from ..contracts import RowScopeKind
from ..policy.loader import PolicyMatrix


class ProposalError(ValueError):
    """An invalid or unsupported fixed-schema permission proposal."""


KINDS = ("table_select", "column_select", "row_scope")
OPERATIONS = ("grant", "revoke")


@dataclass(frozen=True, slots=True)
class PermissionChange:
    kind: str
    role: str
    table: str
    operation: str = ""
    column: str = ""
    proposed_scope: str = ""


@dataclass(frozen=True, slots=True)
class PermissionPreview:
    proposal_sha256: str
    matrix_sha256: str
    role: str
    table: str
    kind: str
    before: str
    after: str
    impact: str
    blockers: tuple[str, ...]
    executable: bool = False


def _check_columns(
    matrix: PolicyMatrix, schema_columns: Mapping[str, tuple[str, ...]], table: str
) -> tuple[str, ...]:
    if table not in matrix.tables or table not in schema_columns:
        raise ProposalError("Only existing fixed-schema tables may be proposed.")
    columns = schema_columns[table]
    if not isinstance(columns, tuple) or not columns or any(
        type(name) is not str or not name for name in columns
    ) or len(set(columns)) != len(columns):
        raise ProposalError("Trusted schema column definitions are required.")
    return columns


def preview_change(
    matrix: PolicyMatrix,
    schema_columns: Mapping[str, tuple[str, ...]],
    change: PermissionChange,
) -> PermissionPreview:
    """Preview one typed edit against a *source matrix*; never generate or run SQL.

    The actual installed PostgreSQL catalog must be compared independently.
    Even a valid preview may be incompatible with policy compilation or RLS.
    """
    if not isinstance(matrix, PolicyMatrix) or type(change) is not PermissionChange:
        raise ProposalError("A loaded source matrix and typed change are required.")
    if change.kind not in KINDS:
        raise ProposalError("Unsupported permission change type.")
    if change.role not in {role.name for role in matrix.roles}:
        raise ProposalError("Only the existing three business roles are supported.")

    columns = _check_columns(matrix, schema_columns, change.table)
    role = matrix.role(change.role)
    access = role.tables.get(change.table)
    before: str
    after: str
    impact: str

    if change.kind == "table_select":
        if change.operation not in OPERATIONS or change.column or change.proposed_scope:
            raise ProposalError("A table SELECT proposal requires grant or revoke only.")
        before = "none" if access is None else (
            "all columns" if access.columns is None else "columns: " + ", ".join(access.columns)
        )
        after = "all columns" if change.operation == "grant" else "none"
        impact = "Potential role-wide SELECT expansion" if change.operation == "grant" else "Potential SELECT removal"
    elif change.kind == "column_select":
        if change.operation not in OPERATIONS or change.proposed_scope or change.column not in columns:
            raise ProposalError("Column SELECT proposals require one actual column and grant/revoke.")
        before_allowed = access is not None and (
            access.columns is None or change.column in access.columns
        )
        before = "SELECT permitted" if before_allowed else "SELECT denied"
        after = "SELECT permitted" if change.operation == "grant" else "SELECT denied"
        impact = "Column entitlement expansion" if change.operation == "grant" else "Column entitlement reduction"
    else:
        if change.operation or change.column or not change.proposed_scope:
            raise ProposalError("Row scope proposals require only a proposed scope.")
        if change.table not in matrix.rls_tables or access is None:
            raise ProposalError("Row scope changes require an existing RLS table entitlement.")
        try:
            proposed = RowScopeKind(change.proposed_scope)
        except ValueError as exc:
            raise ProposalError("Unknown row scope kind.") from exc
        before = access.row_scope.value
        after = proposed.value
        impact = "Potential row-level exposure or restriction; independent security review required"

    if before == after:
        raise ProposalError("The requested change is already represented in the source matrix.")
    payload = {
        "kind": change.kind,
        "role": change.role,
        "table": change.table,
        "operation": change.operation,
        "column": change.column,
        "proposed_scope": change.proposed_scope,
        "matrix_sha256": matrix.sha256,
    }
    fingerprint = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    blockers = (
        "Authenticated administrator and independent reviewer approvals required.",
        "Live database identity, installed policy fingerprint and drift comparison required.",
        "Reviewed matrix change, compiled exact SQL digest and compatibility tests required.",
        "Verified backup/rollback plan and negative RLS/column-grant probes required.",
        "Separate owner-authorized execution is not implemented.",
    )
    return PermissionPreview(
        proposal_sha256=fingerprint,
        matrix_sha256=matrix.sha256,
        role=change.role,
        table=change.table,
        kind=change.kind,
        before=before,
        after=after,
        impact=impact,
        blockers=blockers,
    )
