"""Small role-projected metadata views and the shared safe response boundary.

These types intentionally contain no SQL expressions, dependency graphs,
denied names, model output, database errors, trace paths or artifact hashes.
Their caller must project the governed catalog and physical policy first.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import Outcome, RowScopeKind, SafeResponse


@dataclass(frozen=True, slots=True)
class SafeConcept:
    concept_id: str
    name: str
    description: str
    kind: str
    aliases: tuple[str, ...]
    units: str | None
    grain: tuple[str, ...]
    date_notes: tuple[str, ...]
    aggregation: str | None


@dataclass(frozen=True, slots=True)
class SafePolicyRow:
    table: str
    columns: tuple[str, ...]
    scope: str
    scope_note: str


_SCOPE_NOTES = {
    RowScopeKind.ALL: "All rows permitted by this persona's role.",
    RowScopeKind.DIRECT_REPORTS: "Only this persona's direct reports; the manager's own row is excluded.",
    RowScopeKind.ASSIGNED_DIVISIONS: "Only divisions currently assigned to this persona.",
    RowScopeKind.VIA_EMPLOYEES: "Only rows belonging to employees visible to this persona.",
}


def scope_note(scope: RowScopeKind) -> str:
    return _SCOPE_NOTES[scope]


def safe_response(outcome: Outcome) -> SafeResponse:
    """Use the contracts allowlist; never serialize the internal record for UI."""
    if type(outcome) is not Outcome:
        raise TypeError("A shared internal Outcome is required for safe projection.")
    return outcome.to_safe_response()
