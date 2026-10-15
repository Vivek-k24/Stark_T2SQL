"""Reproducible TEST-ONLY evidence for the installed PostgreSQL parser subset.

Every positive node/function below comes from actual PostgreSQL source text,
then survives regeneration and reparsing. No constructed Anonymous alternatives
are counted as observed parser layouts. These offline tests do not constitute
human production approval, a PostgreSQL engine audit, or live DB evidence.
"""
from __future__ import annotations

from dataclasses import fields
import json

import pytest
import sqlglot

from stark_t2sql.security.function_policy import (
    FunctionPolicyViolation,
    RULES_BY_ID,
    ReviewedFunctionPolicy,
)
from stark_t2sql.security.validator import (
    PROPOSED_NODE_SHAPES,
    ParserReviewApproval,
    ReviewedSQLValidator,
    ValidationRuleCode,
    _ASTReview,
    _Rejected,
)


OBSERVED_FUNCTION_SQL = {
    "count-known-v1": "SELECT COUNT(*) FROM employees",
    "sum-known-v1": "SELECT SUM(base_salary) FROM employee_compensation",
    "avg-known-v1": "SELECT AVG(base_salary) FROM employee_compensation",
    "min-known-v1": "SELECT MIN(employee_id) FROM employees",
    "max-known-v1": "SELECT MAX(employee_id) FROM employees",
    "lower-known-v1": "SELECT LOWER(first_name) FROM employees",
    "upper-known-v1": "SELECT UPPER(first_name) FROM employees",
    "abs-known-v1": "SELECT ABS(base_salary) FROM employee_compensation",
    "round-known-v1": "SELECT ROUND(base_salary,2) FROM employee_compensation",
    "coalesce-known-v1": "SELECT COALESCE(manager_id,employee_id) FROM employees",
    "nullif-known-v1": "SELECT NULLIF(manager_id,employee_id) FROM employees",
    "timestamp-trunc-known-v1": "SELECT DATE_TRUNC('month',hire_date) FROM employees",
    "row-number-known-v1": "SELECT ROW_NUMBER() OVER (ORDER BY employee_id) FROM employees",
    "rank-known-v1": "SELECT RANK() OVER (ORDER BY employee_id) FROM employees",
    "dense-rank-known-v1": "SELECT DENSE_RANK() OVER (ORDER BY employee_id) FROM employees",
    "percentile-cont-known-v1": "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY base_salary) FROM employee_compensation",
    "cast-special-v1": "SELECT CAST(employee_id AS BIGINT) FROM employees",
    "extract-special-v1": "SELECT EXTRACT(YEAR FROM hire_date) FROM employees",
    "current-date-known-v1": "SELECT CURRENT_DATE",
    "current-timestamp-known-v1": "SELECT CURRENT_TIMESTAMP",
    "current-time-known-v1": "SELECT CURRENT_TIME",
    "localtimestamp-known-v1": "SELECT LOCALTIMESTAMP",
    "age-anonymous-v1": "SELECT AGE(DATE '2026-10-12',DATE '2026-01-01')",
    "statement-timestamp-anonymous-v1": "SELECT STATEMENT_TIMESTAMP()",
    "transaction-timestamp-anonymous-v1": "SELECT TRANSACTION_TIMESTAMP()",
    "clock-timestamp-anonymous-v1": "SELECT CLOCK_TIMESTAMP()",
    "timeofday-anonymous-v1": "SELECT TIMEOFDAY()",
}

# These are excluded empirical representations, not failures made to disappear
# by constructing a different AST from the actual parser's source result.
UNOBSERVED_FUNCTION_SQL = {
    "date-trunc-known-v1": "SELECT DATE_TRUNC('month',hire_date) FROM employees",
    "localtimestamp-camel-known-v1": "SELECT LOCALTIMESTAMP",
    "age-known-v1": "SELECT AGE(DATE '2026-10-12',DATE '2026-01-01')",
    "statement-timestamp-known-v1": "SELECT STATEMENT_TIMESTAMP()",
    "transaction-timestamp-known-v1": "SELECT TRANSACTION_TIMESTAMP()",
    "clock-timestamp-known-v1": "SELECT CLOCK_TIMESTAMP()",
    "timeofday-known-v1": "SELECT TIMEOFDAY()",
    "count-anonymous-v1": "SELECT COUNT(*) FROM employees",
    "sum-anonymous-v1": "SELECT SUM(base_salary) FROM employee_compensation",
    "avg-anonymous-v1": "SELECT AVG(base_salary) FROM employee_compensation",
    "min-anonymous-v1": "SELECT MIN(employee_id) FROM employees",
    "max-anonymous-v1": "SELECT MAX(employee_id) FROM employees",
    "lower-anonymous-v1": "SELECT LOWER(first_name) FROM employees",
    "date-trunc-anonymous-v1": "SELECT DATE_TRUNC('month',hire_date) FROM employees",
    "percentile-cont-anonymous-v1": "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY base_salary) FROM employee_compensation",
    "now-anonymous-v1": "SELECT NOW()",
}

SHAPE_SQL = (
    "SELECT * FROM employees",
    "WITH selected(x) AS NOT MATERIALIZED (SELECT employee_id FROM employees) SELECT x AS employee FROM selected",
    "SELECT e.employee_id FROM employees e INNER JOIN departments d ON e.department_id=d.department_id",
    "SELECT employee_id FROM (SELECT employee_id FROM employees) e",
    "SELECT CASE WHEN manager_id IS NULL THEN TRUE ELSE FALSE END FROM employees WHERE NOT (employee_id = 0)",
    "SELECT employee_id FROM employees WHERE (employee_id <> 0 AND employee_id > -1 AND employee_id >= 1) OR employee_id < 2 OR employee_id <= 3",
    "SELECT employee_id FROM employees WHERE manager_id IS NOT NULL AND employee_id BETWEEN 1 AND 3 AND employee_id IN (1,2) AND (employee_id,department_id) IN ((1,1))",
    "SELECT first_name FROM employees WHERE first_name LIKE 'A!_%' ESCAPE '!' OR first_name ILIKE 'a%'",
    "SELECT employee_id + 1 - 2 * 3 % 2 FROM employees",
    "SELECT DISTINCT department_id FROM employees ORDER BY department_id DESC NULLS LAST LIMIT 2 OFFSET 1",
    "SELECT department_id,COUNT(*) FILTER(WHERE manager_id IS NOT NULL) FROM employees GROUP BY department_id HAVING COUNT(*) > 1",
    "SELECT ROW_NUMBER() OVER (PARTITION BY department_id ORDER BY employee_id ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) FROM employees",
    "SELECT CAST(employee_id AS NUMERIC(10,2)),EXTRACT(YEAR FROM hire_date),hire_date + INTERVAL '1 day' FROM employees",
    "SELECT employee_id FROM employees WHERE EXISTS (SELECT 1 FROM departments)",
    "SELECT employee_id FROM employees UNION ALL SELECT employee_id FROM employees INTERSECT SELECT employee_id FROM employees EXCEPT SELECT employee_id FROM employees",
    "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY base_salary) FROM employee_compensation",
)


@pytest.fixture(scope="module")
def empirical_approval(project_root):
    """Load the explicit test asset, independently of an external override."""
    raw = json.loads((project_root / "tests/fixtures/parser_approval_sqlglot_30_22_0.json").read_text(encoding="utf-8"))
    payload = {field.name: raw[field.name] for field in fields(ParserReviewApproval)}
    payload["approved_node_shapes"] = frozenset(payload["approved_node_shapes"])
    payload["approved_function_rule_ids"] = frozenset(payload["approved_function_rule_ids"])
    return ParserReviewApproval(**payload)


def _matching(tree, rule):
    cls = getattr(sqlglot.exp, rule.parser_class, None)
    return [node for node in tree.walk() if type(node) is cls
            and (rule.parser_class != "Anonymous" or node.name.lower() == rule.sql_name)]


def test_test_only_profile_matches_actual_observed_layouts(empirical_approval):
    assert sqlglot.__version__ == empirical_approval.sqlglot_version == "30.22.0"
    assert len(OBSERVED_FUNCTION_SQL) == 27
    assert len(UNOBSERVED_FUNCTION_SQL) == 16
    assert not OBSERVED_FUNCTION_SQL.keys() & UNOBSERVED_FUNCTION_SQL.keys()
    assert OBSERVED_FUNCTION_SQL.keys() | UNOBSERVED_FUNCTION_SQL.keys() == RULES_BY_ID.keys()
    assert empirical_approval.approved_function_rule_ids == OBSERVED_FUNCTION_SQL.keys()
    assert empirical_approval.approved_node_shapes == PROPOSED_NODE_SHAPES.keys() - {"Div"}


@pytest.mark.parametrize("rule_id", OBSERVED_FUNCTION_SQL)
def test_real_function_layout_positive_and_roundtrip(rule_id, empirical_approval, matrix, payroll_persona):
    rule = RULES_BY_ID[rule_id]
    source = OBSERVED_FUNCTION_SQL[rule_id]
    tree = sqlglot.parse_one(source, read="postgres")
    rendered = tree.sql(dialect="postgres")
    reparsed = sqlglot.parse_one(rendered, read="postgres")
    single_rule_policy = ReviewedFunctionPolicy(sqlglot.exp, frozenset({rule_id}))
    for actual in (tree, reparsed):
        matches = _matching(actual, rule)
        assert matches, f"Real PostgreSQL source did not produce {rule_id}"
        assert all(single_rule_policy.require(node).rule_id == rule_id for node in matches)
    assert reparsed.sql(dialect="postgres") == rendered
    validator = ReviewedSQLValidator(matrix, approval=empirical_approval)
    decision = validator.validate(source, persona=payroll_persona, policy_fingerprint=matrix.sha256)
    assert decision.accepted, (decision.rule_code, decision.internal_detail)
    assert decision.regenerated_sql == rendered


@pytest.mark.parametrize("rule_id", OBSERVED_FUNCTION_SQL)
def test_observed_function_rejects_unknown_argument(rule_id):
    rule = RULES_BY_ID[rule_id]
    tree = sqlglot.parse_one(OBSERVED_FUNCTION_SQL[rule_id], read="postgres")
    node = _matching(tree, rule)[0]
    node.set("unreviewed_option", True)
    with pytest.raises(FunctionPolicyViolation):
        ReviewedFunctionPolicy(sqlglot.exp, frozenset({rule_id})).require(node)


@pytest.mark.parametrize("rule_id", UNOBSERVED_FUNCTION_SQL)
def test_excluded_function_layout_not_claimed_from_real_source(rule_id, empirical_approval):
    assert rule_id not in empirical_approval.approved_function_rule_ids
    rule = RULES_BY_ID[rule_id]
    tree = sqlglot.parse_one(UNOBSERVED_FUNCTION_SQL[rule_id], read="postgres")
    assert not _matching(tree, rule)
    reparsed = sqlglot.parse_one(tree.sql(dialect="postgres"), read="postgres")
    assert not _matching(reparsed, rule)


def test_every_approved_node_shape_observed_before_and_after_regeneration(empirical_approval):
    before, after = set(), set()
    for source in SHAPE_SQL:
        tree = sqlglot.parse_one(source, read="postgres")
        before.update(type(node).__name__ for node in tree.walk())
        reparsed = sqlglot.parse_one(tree.sql(dialect="postgres"), read="postgres")
        after.update(type(node).__name__ for node in reparsed.walk())
    assert len(empirical_approval.approved_node_shapes) == 59
    assert empirical_approval.approved_node_shapes <= before
    assert empirical_approval.approved_node_shapes <= after


@pytest.mark.parametrize("source", SHAPE_SQL)
def test_real_node_corpus_positive_and_idempotent(source, empirical_approval, matrix, payroll_persona):
    validator = ReviewedSQLValidator(matrix, approval=empirical_approval)
    first = validator.validate(source, persona=payroll_persona, policy_fingerprint=matrix.sha256)
    assert first.accepted, (first.rule_code, first.internal_detail)
    second = validator.validate(first.regenerated_sql, persona=payroll_persona, policy_fingerprint=matrix.sha256)
    assert second.accepted and second.regenerated_sql == first.regenerated_sql


@pytest.mark.parametrize("shape_name", sorted(PROPOSED_NODE_SHAPES.keys() - {"Div"}))
def test_each_real_node_shape_rejects_unknown_argument(shape_name, empirical_approval, matrix):
    # Parse fresh source for each mutation; no fabricated positive layout.
    for source in SHAPE_SQL:
        tree = sqlglot.parse_one(source, read="postgres")
        found = next((node for node in tree.walk() if type(node).__name__ == shape_name), None)
        if found is not None:
            break
    assert found is not None, f"No real PostgreSQL source evidence for {shape_name}"
    found.set("unreviewed_option", True)
    review = _ASTReview(sqlglot, empirical_approval, permitted_tables=frozenset(matrix.tables),
                        real_tables=frozenset(matrix.tables), max_nodes=10_000)
    with pytest.raises(_Rejected) as error:
        review.review(tree)
    assert error.value.code is ValidationRuleCode.UNSUPPORTED_ARGUMENT


def test_observed_division_remains_excluded(empirical_approval, matrix, payroll_persona):
    source = "SELECT employee_id / 2 FROM employees"
    tree = sqlglot.parse_one(source, read="postgres")
    division = next(node for node in tree.walk() if type(node) is sqlglot.exp.Div)
    assert division.args["typed"] is True
    assert "Div" not in empirical_approval.approved_node_shapes
    reparsed = sqlglot.parse_one(tree.sql(dialect="postgres"), read="postgres")
    assert next(node for node in reparsed.walk() if type(node) is sqlglot.exp.Div).args["typed"] is True
    validator = ReviewedSQLValidator(matrix, approval=empirical_approval)
    decision = validator.validate(source, persona=payroll_persona, policy_fingerprint=matrix.sha256)
    assert not decision.accepted
    assert decision.rule_code is ValidationRuleCode.UNSUPPORTED_NODE
    assert decision.regenerated_sql is None
