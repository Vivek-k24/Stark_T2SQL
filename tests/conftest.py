"""Future test dependencies, with no generated fixture or review evidence.

External metadata must describe actual supplied artifacts. Missing inputs cause
explicit future skips, which establish no acceptance/security evidence. The
source-only authoring exception does not authorize running these definitions.
"""
from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path

import pytest

from stark_t2sql.contracts import Persona
from stark_t2sql.db.catalog import ColumnDefinition, ForeignKeyDefinition, SchemaSnapshot, TableDefinition
from stark_t2sql.policy.loader import load_policy
from stark_t2sql.security.validator import ParserReviewApproval


@pytest.fixture(scope="session")
def project_root():
    return Path(__file__).resolve().parents[1]


def required_input(variable: str, root: Path) -> Path:
    supplied = os.environ.get(variable)
    if not supplied:
        pytest.skip(f"Pending actual external input: {variable}; skip is not acceptance evidence.")
    path = Path(supplied).resolve()
    if not path.is_relative_to(root.resolve()):
        pytest.fail(f"{variable} must name an input inside the project workspace.")
    if not path.is_file():
        pytest.skip(f"Actual input file unavailable: {variable}; skip is not acceptance evidence.")
    return path


@pytest.fixture(scope="session")
def matrix(project_root):
    return load_policy(project_root / "policy" / "access_matrix.yaml")


@pytest.fixture(scope="session")
def schema_metadata(project_root):
    """Externally recorded catalog structure, never fixture rows or a fake dump."""
    raw = json.loads(required_input("STARK_TEST_SCHEMA_METADATA_PATH", project_root).read_text(encoding="utf-8"))
    tables = tuple(TableDefinition(
        item["name"], tuple(ColumnDefinition(**column) for column in item["columns"]),
        tuple(item.get("primary_key", ())), tuple(tuple(key) for key in item.get("unique_keys", ())),
        tuple(ForeignKeyDefinition(**dict(fk, columns=tuple(fk["columns"]), referenced_columns=tuple(fk["referenced_columns"])))
        for fk in item.get("foreign_keys", ())),
    ) for item in raw["tables"])
    return SchemaSnapshot(raw["schema"], tables)


@pytest.fixture(scope="session")
def parser_approval(project_root):
    raw = json.loads(required_input("STARK_TEST_PARSER_REVIEW_PATH", project_root).read_text(encoding="utf-8"))
    # The file is actual review input, not inferred from installed capabilities.
    raw["approved_node_shapes"] = frozenset(raw["approved_node_shapes"])
    raw["approved_function_rule_ids"] = frozenset(raw["approved_function_rule_ids"])
    return ParserReviewApproval(**raw)


@pytest.fixture(scope="session")
def governed_catalog(project_root, matrix, schema_metadata, parser_approval):
    from stark_t2sql.semantic.catalog import load_catalog
    return load_catalog(project_root / "semantic" / "catalog.yaml", schema_metadata, matrix)


@pytest.fixture
def payroll_persona():
    return Persona("Payroll specialist", "app_payroll", 326, "stark_payroll_login")


@pytest.fixture
def hr_persona():
    return Persona("HR business partner #1", "app_hr_bp", 47, "stark_hr_login")


@pytest.fixture
def fixture_date():
    return date(2026, 10, 12)
