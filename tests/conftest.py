"""Offline source metadata, test parser evidence and external acceptance inputs.

The DDL fallback describes checked-in structure only, not a live catalog audit.
The explicit R05 parser fixture exercises only its empirically tested subset.
It is not human production approval. Adversarial/reference/live-DB evidence
still requires separately supplied inputs; no acceptance evidence is invented.
"""
from __future__ import annotations

import ast
from dataclasses import replace
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
    """Use supplied catalog evidence, or parse frozen source entirely offline."""
    if not os.environ.get("STARK_TEST_SCHEMA_METADATA_PATH"):
        return _offline_schema_snapshot(project_root)
    raw = json.loads(required_input("STARK_TEST_SCHEMA_METADATA_PATH", project_root).read_text(encoding="utf-8"))
    tables = tuple(TableDefinition(
        item["name"], tuple(ColumnDefinition(**column) for column in item["columns"]),
        tuple(item.get("primary_key", ())), tuple(tuple(key) for key in item.get("unique_keys", ())),
        tuple(ForeignKeyDefinition(**dict(fk, columns=tuple(fk["columns"]), referenced_columns=tuple(fk["referenced_columns"])))
        for fk in item.get("foreign_keys", ())),
    ) for item in raw["tables"])
    return SchemaSnapshot(raw["schema"], tables)


def _offline_schema_snapshot(project_root):
    """Read types, nullability, keys and FK actions; execute no SQL/generator.

    sqlglot parses trusted DDL here, independently of the generated-SQL guard's
    required external parser review. Partial unique indexes are not unique
    constraints and must not be promoted into unconditional cardinality claims.
    """
    import sqlglot
    from sqlglot import exp

    tables = []
    for statement in sqlglot.parse((project_root / "schema.sql").read_text(encoding="utf-8"), read="postgres"):
        if not isinstance(statement, exp.Create) or statement.kind != "TABLE":
            continue
        relation = statement.this.this
        assert relation.db == "public" and not relation.catalog
        columns, primary, unique, foreign = [], (), [], []
        for item in statement.this.expressions:
            if isinstance(item, exp.ColumnDef):
                sql_type = item.args["kind"].sql(dialect="postgres").lower().replace(", ", ",")
                if sql_type == "int":
                    sql_type = "integer"
                elif sql_type.startswith("decimal("):
                    sql_type = "numeric" + sql_type[len("decimal"):]
                nullable = not any(isinstance(c.kind, exp.NotNullColumnConstraint) for c in item.constraints)
                columns.append(ColumnDefinition(item.name, sql_type, nullable, len(columns) + 1))
            elif isinstance(item, exp.Constraint):
                for key in item.expressions:
                    if isinstance(key, exp.PrimaryKey):
                        primary = tuple(column.name for column in key.expressions)
                    elif isinstance(key, exp.UniqueColumnConstraint):
                        unique.append(tuple(column.name for column in key.this.expressions))
                    elif isinstance(key, exp.ForeignKey):
                        reference = key.args["reference"]
                        actions = reference.args.get("options", ())
                        action = lambda kind: next((value[len(kind) + 1:] for value in actions if value.startswith(kind + " ")), "NO ACTION")
                        foreign.append(ForeignKeyDefinition(
                            item.name, tuple(column.name for column in key.expressions),
                            reference.this.this.db, reference.this.this.name,
                            tuple(column.name for column in reference.this.expressions),
                            action("ON UPDATE"), action("ON DELETE"),
                        ))
        columns = tuple(replace(c, nullable=False) if c.name in primary else c for c in columns)
        tables.append(TableDefinition(relation.name, columns, primary, tuple(unique), tuple(foreign)))
    snapshot = SchemaSnapshot("public", tuple(sorted(tables, key=lambda table: table.name)))
    # Cross-check the independent frozen generator's column declarations by AST,
    # without importing it, generating rows or inferring historical/live fidelity.
    seed_ast = ast.parse((project_root / "seed_data.py").read_text(encoding="utf-8"))
    declaration = next(node for node in seed_ast.body if isinstance(node, ast.AnnAssign)
                       and isinstance(node.target, ast.Name) and node.target.id == "TABLE_COLUMNS")
    expected = ast.literal_eval(declaration.value.args[0])
    assert dict(snapshot.columns_by_table) == expected
    return snapshot


@pytest.fixture(scope="session")
def parser_approval(project_root):
    """Prefer an explicit external profile; otherwise use TEST-ONLY R05 evidence.

    The authored JSON pins one release and a measured subset. Neither runtime
    composition nor production approval loads this pytest-only fallback.
    """
    path = (required_input("STARK_TEST_PARSER_REVIEW_PATH", project_root)
            if os.environ.get("STARK_TEST_PARSER_REVIEW_PATH") else
            project_root / "tests" / "fixtures" / "parser_approval_sqlglot_30_22_0.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["approved_node_shapes"] = frozenset(raw["approved_node_shapes"])
    raw["approved_function_rule_ids"] = frozenset(raw["approved_function_rule_ids"])
    return ParserReviewApproval(**raw)


@pytest.fixture(scope="session")
def governed_catalog(project_root, matrix, schema_metadata):
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
