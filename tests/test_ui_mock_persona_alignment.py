"""Offline mock personas stay aligned with the access matrix and committed fixture.

The independent oracle here parses the frozen fixture dump directly and applies
the documented db.persona.resolve_personas rules. It never connects to a database or
changes production persona resolution, and it is not live acceptance evidence.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
import re

import pytest

from stark_t2sql.config import FIXTURE_AS_OF_DATE
from stark_t2sql.ui.offline_demo import (
    CANONICAL_PERSONAS, HR1_PERSONA, HR2_PERSONA, PAYROLL_PERSONA, ROLE_INFO, SALES_PERSONA,
    MockPersonaApplication,
)

_INSERT = re.compile(r'^INSERT INTO public\."(\w+)" \(([^)]*)\) VALUES \((.*)\);$')
_WANTED = ("divisions", "departments", "employees", "hr_bp_assignments")


def _values(text: str) -> list[str | None]:
    out: list[str | None] = []
    i = 0
    while i < len(text):
        if text.startswith(("E'", "'"), i):
            i += 2 if text[i] == "E" else 1
            buffer = []
            while True:
                character = text[i]
                if character == "\\":
                    buffer.append(text[i + 1]); i += 2
                elif character == "'" and text[i + 1:i + 2] == "'":
                    buffer.append("'"); i += 2
                elif character == "'":
                    i += 1
                    break
                else:
                    buffer.append(character); i += 1
            out.append("".join(buffer))
        else:
            end = text.find(",", i)
            end = len(text) if end == -1 else end
            token = text[i:end].strip()
            typed = re.fullmatch(r"(?:DATE|TIMESTAMP) '([^']*)'", token)
            out.append(None if token == "NULL" else typed.group(1) if typed else token)
            i = end
        while i < len(text) and text[i] in ", ":
            i += 1
    return out


@pytest.fixture(scope="module")
def fixture_rows(project_root):
    dump = project_root / "fixture_pg_dump.sql"
    manifest = json.loads((project_root / "fixture_manifest.json").read_text(encoding="utf-8"))
    assert sha256(dump.read_bytes()).hexdigest() == manifest["fixture_dump_sha256"]
    tables: dict[str, list[dict[str, str | None]]] = {name: [] for name in _WANTED}
    for line in dump.read_text(encoding="utf-8").splitlines():
        match = _INSERT.match(line)
        if match and match.group(1) in tables:
            columns = [column.strip().strip('"') for column in match.group(2).split(",")]
            row = _values(match.group(3))
            assert len(row) == len(columns)
            tables[match.group(1)].append(dict(zip(columns, row)))
    for name in _WANTED:
        assert len(tables[name]) == manifest["row_counts"][name]
    return tables


def _current_divisions(rows, principal: int) -> tuple[int, ...]:
    return tuple(sorted({int(row["division_id"]) for row in rows["hr_bp_assignments"]
                         if int(row["employee_id"]) == principal and row["effective_to"] is None}))


def test_mock_login_roles_match_access_matrix(matrix):
    for persona in CANONICAL_PERSONAS:
        assert persona.login_role == matrix.role(persona.business_role).login_role
    assert {persona.login_role for persona in CANONICAL_PERSONAS} == {
        "stark_payroll_login", "stark_hr_login", "stark_sales_login"}


def test_mock_hr_principals_are_frd_ids_with_distinct_fixture_scopes(fixture_rows):
    assert (PAYROLL_PERSONA.principal_id, HR1_PERSONA.principal_id, HR2_PERSONA.principal_id) == (326, 47, 361)
    first, second = _current_divisions(fixture_rows, 47), _current_divisions(fixture_rows, 361)
    assert first and second and first != second  # so the FRD 364 fallback does not apply


def test_mock_sales_principal_is_the_fixture_derived_sales_manager(fixture_rows):
    sales_division = {row["division_name"]: int(row["division_id"]) for row in fixture_rows["divisions"]}["Sales"]
    division_of = {int(row["department_id"]): int(row["division_id"]) for row in fixture_rows["departments"]}
    managers = {int(row["manager_id"]) for row in fixture_rows["employees"] if row["manager_id"] is not None}
    candidates = sorted(
        int(row["employee_id"]) for row in fixture_rows["employees"]
        if division_of[int(row["department_id"])] == sales_division
        and row["employment_type"] in ("full_time", "part_time") and row["status"] != "cancelled_pre_hire"
        and date.fromisoformat(row["hire_date"]) <= FIXTURE_AS_OF_DATE
        and (row["termination_date"] is None or date.fromisoformat(row["termination_date"]) > FIXTURE_AS_OF_DATE)
        and int(row["employee_id"]) in managers
    )
    assert candidates and SALES_PERSONA.principal_id == candidates[0]
    assert ROLE_INFO["app_sales_mgr"]["principal"].startswith(f"{SALES_PERSONA.principal_id} ")


def test_mock_sales_rows_report_to_the_mock_sales_principal(fixture_date):
    response = MockPersonaApplication().answer(SALES_PERSONA, "List my direct reports.", fixture_date)
    assert response.rows, "the scripted direct-report case must render sample rows"
    manager_column = response.columns.index("manager_id")
    assert {row[manager_column] for row in response.rows} == {SALES_PERSONA.principal_id}
