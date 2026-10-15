"""Offline negative contracts for exact AST metadata and two-pass review.

Positive SQL is parsed normally. Mutated ASTs below are negative robustness
inputs, never evidence that a parser emits those malformed representations.
No candidate is sent to PostgreSQL, SQLCoder, or an execution connection.
"""
from dataclasses import replace

import pytest
import sqlglot

from stark_t2sql.contracts import ReasonCode
from stark_t2sql.errors import ConfigurationError
from stark_t2sql.security.function_policy import FunctionPolicyViolation, ReviewedFunctionPolicy
from stark_t2sql.security.validator import (
    ReviewedSQLValidator,
    ValidationRuleCode,
    _ASTReview,
    _Rejected,
)


MALFORMED_FLAGS = (None, 0, 1, "", "true", [], (), {}, [True])
NEGATED_SQL = (
    ("Is", "SELECT employee_id FROM employees WHERE manager_id IS NOT NULL"),
    ("Like", "SELECT first_name FROM employees WHERE first_name NOT LIKE 'A%'"),
    ("ILike", "SELECT first_name FROM employees WHERE first_name NOT ILIKE 'a%'"),
)
SELECT_SQL = "SELECT employee_id FROM employees"


def _tree_node(source, class_name):
    tree = sqlglot.parse_one(source, read="postgres")
    node = next(item for item in tree.walk() if type(item).__name__ == class_name)
    return tree, node


def _review(tree, approval, matrix):
    _ASTReview(sqlglot, approval, permitted_tables=frozenset(matrix.tables),
               real_tables=frozenset(matrix.tables), max_nodes=10_000).review(tree)


def _decision(matrix, approval, persona, source=SELECT_SQL):
    return ReviewedSQLValidator(matrix, approval=approval).validate(
        source, persona=persona, policy_fingerprint=matrix.sha256)


def _assert_rejected(decision, rule):
    assert not decision.accepted
    assert decision.regenerated_sql is None
    assert decision.rule_code is rule


@pytest.mark.parametrize("flag", (True, False, "absent"))
def test_count_only_exact_boolean_metadata_is_admitted(flag, parser_approval, matrix):
    """Unit metadata contract; False/absence are not claimed parser outputs."""
    tree, node = _tree_node("SELECT COUNT(*) FROM employees", "Count")
    if flag == "absent":
        node.args.pop("big_int", None)
    else:
        node.set("big_int", flag)
    assert ReviewedFunctionPolicy(sqlglot.exp, frozenset({"count-known-v1"})).require(node).sql_name == "count"
    _review(tree, parser_approval, matrix)


@pytest.mark.parametrize("source", (
    "SELECT COUNT(*) FROM employees",
    "SELECT COUNT(employee_id) FROM employees",
    "SELECT COUNT(DISTINCT employee_id) FROM employees",
    "SELECT COUNT(*) FILTER(WHERE manager_id IS NOT NULL) FROM employees",
))
def test_real_count_sql_positive_metadata_and_roundtrip(source, parser_approval, matrix, payroll_persona):
    _, node = _tree_node(source, "Count")
    assert node.args["big_int"] is True
    first = _decision(matrix, parser_approval, payroll_persona, source)
    assert first.accepted, (first.rule_code, first.internal_detail)
    _, regenerated_count = _tree_node(first.regenerated_sql, "Count")
    assert regenerated_count.args["big_int"] is True
    second = _decision(matrix, parser_approval, payroll_persona, first.regenerated_sql)
    assert second.accepted and second.regenerated_sql == first.regenerated_sql


@pytest.mark.parametrize("flag", MALFORMED_FLAGS)
def test_count_malformed_boolean_metadata_fails_closed(flag, parser_approval, matrix):
    tree, node = _tree_node("SELECT COUNT(*) FROM employees", "Count")
    # Direct assignment deliberately retains a present None key; set(None)
    # would remove it and test legitimate absence instead of malformed input.
    node.args["big_int"] = flag
    with pytest.raises(FunctionPolicyViolation):
        ReviewedFunctionPolicy(sqlglot.exp, frozenset({"count-known-v1"})).require(node)
    with pytest.raises(_Rejected) as error:
        _review(tree, parser_approval, matrix)
    assert error.value.code is ValidationRuleCode.FUNCTION


@pytest.mark.parametrize("rule_id,class_name,source", (
    ("lower-known-v1", "Lower", "SELECT LOWER(first_name) FROM employees"),
    ("age-anonymous-v1", "Anonymous", "SELECT AGE(hire_date) FROM employees"),
    ("timestamp-trunc-known-v1", "TimestampTrunc", "SELECT DATE_TRUNC('month',hire_date) FROM employees"),
))
@pytest.mark.parametrize("flag", (True, False, None, 0, []))
def test_count_metadata_cannot_expand_other_callable_signatures(rule_id, class_name, source, flag):
    _, node = _tree_node(source, class_name)
    node.args["big_int"] = flag
    with pytest.raises(FunctionPolicyViolation):
        ReviewedFunctionPolicy(sqlglot.exp, frozenset({rule_id})).require(node)


@pytest.mark.parametrize("class_name,source", NEGATED_SQL)
def test_real_negated_operator_sql_is_accepted(class_name, source, parser_approval, matrix, payroll_persona):
    _, node = _tree_node(source, class_name)
    assert node.args["negate"] is True
    first = _decision(matrix, parser_approval, payroll_persona, source)
    assert first.accepted, (first.rule_code, first.internal_detail)
    second = _decision(matrix, parser_approval, payroll_persona, first.regenerated_sql)
    assert second.accepted and second.regenerated_sql == first.regenerated_sql


def test_explicit_not_wrapper_is_also_a_real_supported_layout(parser_approval, matrix, payroll_persona):
    source = "SELECT employee_id FROM employees WHERE NOT (manager_id IS NULL)"
    tree, inner = _tree_node(source, "Is")
    assert "negate" not in inner.args
    assert any(type(node).__name__ == "Not" for node in tree.walk())
    first = _decision(matrix, parser_approval, payroll_persona, source)
    assert first.accepted, (first.rule_code, first.internal_detail)
    second = _decision(matrix, parser_approval, payroll_persona, first.regenerated_sql)
    assert second.accepted and second.regenerated_sql == first.regenerated_sql


@pytest.mark.parametrize("source", (
    "SELECT e.employee_id FROM employees e LEFT OUTER JOIN departments d ON e.department_id=d.department_id",
    "SELECT e.employee_id FROM employees e RIGHT OUTER JOIN departments d ON e.department_id=d.department_id",
    "SELECT e.employee_id FROM employees e FULL OUTER JOIN departments d ON e.department_id=d.department_id",
    "SELECT e.employee_id FROM employees e CROSS JOIN departments d",
    "SELECT e.employee_id FROM (SELECT employee_id FROM employees ORDER BY employee_id LIMIT 5 OFFSET 1) AS e",
))
def test_real_outer_cross_join_and_bounded_subquery_sql(source, parser_approval, matrix, payroll_persona):
    first = _decision(matrix, parser_approval, payroll_persona, source)
    assert first.accepted, (first.rule_code, first.internal_detail)
    second = _decision(matrix, parser_approval, payroll_persona, first.regenerated_sql)
    assert second.accepted and second.regenerated_sql == first.regenerated_sql


@pytest.mark.parametrize("class_name,source", NEGATED_SQL)
@pytest.mark.parametrize("flag", (True, False, "absent"))
def test_reviewed_operator_metadata_boolean_or_absent(class_name, source, flag, parser_approval, matrix):
    tree, node = _tree_node(source, class_name)
    if flag == "absent":
        node.args.pop("negate", None)
    else:
        node.set("negate", flag)
    _review(tree, parser_approval, matrix)


@pytest.mark.parametrize("class_name,source", NEGATED_SQL)
@pytest.mark.parametrize("flag", MALFORMED_FLAGS)
def test_negated_operator_metadata_rejects_non_boolean_values(class_name, source, flag, parser_approval, matrix):
    tree, node = _tree_node(source, class_name)
    node.args["negate"] = flag
    with pytest.raises(_Rejected) as error:
        _review(tree, parser_approval, matrix)
    assert error.value.code is ValidationRuleCode.STRUCTURE


@pytest.mark.parametrize("class_name,source,key", (
    ("EQ", "SELECT employee_id FROM employees WHERE employee_id=1", "negate"),
    ("Add", "SELECT employee_id+1 FROM employees", "negate"),
    ("Count", "SELECT COUNT(*) FROM employees", "negate"),
    ("Lower", "SELECT LOWER(first_name) FROM employees", "negate"),
    ("Anonymous", "SELECT AGE(hire_date) FROM employees", "negate"),
    ("Select", SELECT_SQL, "big_int"),
    ("EQ", "SELECT employee_id FROM employees WHERE employee_id=1", "big_int"),
    ("Is", "SELECT employee_id FROM employees WHERE manager_id IS NULL", "big_int"),
    ("Lower", "SELECT LOWER(first_name) FROM employees", "big_int"),
    ("Anonymous", "SELECT AGE(hire_date) FROM employees", "big_int"),
))
@pytest.mark.parametrize("flag", (True, False, None, []))
def test_metadata_is_rejected_on_other_classes_even_when_falsey(class_name, source, key, flag, parser_approval, matrix):
    tree, node = _tree_node(source, class_name)
    node.args[key] = flag
    with pytest.raises(_Rejected) as error:
        _review(tree, parser_approval, matrix)
    assert error.value.code is ValidationRuleCode.UNSUPPORTED_ARGUMENT


@pytest.mark.parametrize("value", (None, False, 0, "employee_id", [], (), {}, [False]))
def test_count_argument_is_an_expression_not_a_python_scalar_or_container(value):
    _, node = _tree_node("SELECT COUNT(employee_id) FROM employees", "Count")
    node.args["this"] = value
    with pytest.raises(FunctionPolicyViolation):
        ReviewedFunctionPolicy(sqlglot.exp, frozenset({"count-known-v1"})).require(node)


@pytest.mark.parametrize("value", (None, False, "employee_id", [], (), {}, [False], [1]))
def test_count_distinct_requires_nonempty_expression_list(value):
    _, node = _tree_node("SELECT COUNT(DISTINCT employee_id) FROM employees", "Count")
    node.args["this"].args["expressions"] = value
    with pytest.raises(FunctionPolicyViolation):
        ReviewedFunctionPolicy(sqlglot.exp, frozenset({"count-known-v1"})).require(node)


def test_count_distinct_star_and_modified_star_are_rejected():
    _, distinct = _tree_node("SELECT COUNT(DISTINCT employee_id) FROM employees", "Count")
    distinct.args["this"].set("expressions", [sqlglot.exp.Star()])
    _, modified = _tree_node("SELECT COUNT(*) FROM employees", "Count")
    modified.args["this"].set("unreviewed_option", True)
    policy = ReviewedFunctionPolicy(sqlglot.exp, frozenset({"count-known-v1"}))
    for node in (distinct, modified):
        with pytest.raises(FunctionPolicyViolation):
            policy.require(node)


@pytest.mark.parametrize("rule_id,class_name,source,key", (
    ("lower-known-v1", "Lower", "SELECT LOWER(first_name) FROM employees", "this"),
    ("nullif-known-v1", "Nullif", "SELECT NULLIF(manager_id,employee_id) FROM employees", "expression"),
    ("cast-special-v1", "Cast", "SELECT CAST(employee_id AS BIGINT) FROM employees", "to"),
    ("extract-special-v1", "Extract", "SELECT EXTRACT(YEAR FROM hire_date) FROM employees", "this"),
))
@pytest.mark.parametrize("value", (False, 0, "raw", [], (), {}))
def test_function_arguments_never_admit_raw_scalar_or_container_values(rule_id, class_name, source, key, value):
    _, node = _tree_node(source, class_name)
    node.args[key] = value
    with pytest.raises(FunctionPolicyViolation):
        ReviewedFunctionPolicy(sqlglot.exp, frozenset({rule_id})).require(node)


@pytest.mark.parametrize("rule_id,class_name,source", (
    ("count-known-v1", "Count", "SELECT COUNT(*) FROM employees"),
    ("coalesce-known-v1", "Coalesce", "SELECT COALESCE(manager_id,employee_id) FROM employees"),
    ("age-anonymous-v1", "Anonymous", "SELECT AGE(hire_date) FROM employees"),
))
@pytest.mark.parametrize("value", (False, 0, "", (), {}, [False], ["raw"]))
def test_function_expression_collections_reject_bad_containers_and_members(rule_id, class_name, source, value):
    _, node = _tree_node(source, class_name)
    node.args["expressions"] = value
    with pytest.raises(FunctionPolicyViolation):
        ReviewedFunctionPolicy(sqlglot.exp, frozenset({rule_id})).require(node)


@pytest.mark.parametrize("rendered", (None, "", " \n", 1, []))
def test_invalid_regenerator_output_never_becomes_execution_text(rendered, monkeypatch, parser_approval, matrix, payroll_persona):
    monkeypatch.setattr(sqlglot.exp.Select, "sql", lambda self, **kwargs: rendered)
    _assert_rejected(_decision(matrix, parser_approval, payroll_persona), ValidationRuleCode.REGENERATION)


@pytest.mark.parametrize("failing_pass", (1, 2))
def test_renderer_exception_at_either_pass_fails_closed(failing_pass, monkeypatch, parser_approval, matrix, payroll_persona):
    original = sqlglot.exp.Select.sql
    calls = 0

    def render(self, **kwargs):
        nonlocal calls
        calls += 1
        if calls == failing_pass:
            raise RuntimeError("offline injected renderer failure")
        return original(self, **kwargs)

    monkeypatch.setattr(sqlglot.exp.Select, "sql", render)
    _assert_rejected(_decision(matrix, parser_approval, payroll_persona), ValidationRuleCode.REGENERATION)
    assert calls == failing_pass


def test_non_idempotent_renderer_output_fails_closed(monkeypatch, parser_approval, matrix, payroll_persona):
    calls = 0

    def render(self, **kwargs):
        nonlocal calls
        calls += 1
        return SELECT_SQL if calls == 1 else "SELECT manager_id FROM employees"

    monkeypatch.setattr(sqlglot.exp.Select, "sql", render)
    _assert_rejected(_decision(matrix, parser_approval, payroll_persona), ValidationRuleCode.IDEMPOTENCE)
    assert calls == 2


def test_unsafe_regenerated_sql_is_reparsed_and_rejected(monkeypatch, parser_approval, matrix, payroll_persona):
    monkeypatch.setattr(sqlglot.exp.Select, "sql", lambda self, **kwargs: "SELECT pg_sleep(60)")
    _assert_rejected(_decision(matrix, parser_approval, payroll_persona), ValidationRuleCode.FUNCTION)


@pytest.mark.parametrize("failure", ("exception", "empty", "plural", "wrong_container"))
def test_reparser_failure_never_returns_first_pass_text(failure, monkeypatch, parser_approval, matrix, payroll_persona):
    original = sqlglot.parse
    calls = 0

    def parse(source, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(source, **kwargs)
        if failure == "exception":
            raise RuntimeError("offline injected reparser failure")
        statements = original(source, **kwargs)
        if failure == "empty":
            return []
        if failure == "plural":
            return statements + original(source, **kwargs)
        return tuple(statements)

    monkeypatch.setattr(sqlglot, "parse", parse)
    rule = ValidationRuleCode.PARSE if failure == "exception" else ValidationRuleCode.STATEMENT_COUNT
    _assert_rejected(_decision(matrix, parser_approval, payroll_persona), rule)
    assert calls == 2


def test_unapproved_ast_class_is_rejected(parser_approval, matrix, payroll_persona):
    source = "SELECT employee_id[1] FROM employees"
    tree = sqlglot.parse_one(source, read="postgres")
    assert any(type(node).__name__ == "Bracket" for node in tree.walk())
    assert "Bracket" not in parser_approval.approved_node_shapes
    _assert_rejected(_decision(matrix, parser_approval, payroll_persona, source), ValidationRuleCode.UNSUPPORTED_NODE)


def test_wrong_parser_release_fails_closed(parser_approval, matrix, payroll_persona):
    wrong = replace(parser_approval, sqlglot_version="0.0.0")
    decision = _decision(matrix, wrong, payroll_persona)
    _assert_rejected(decision, ValidationRuleCode.PARSER_PROFILE)
    assert decision.reason_code is ReasonCode.MISSING_DEPENDENCY


@pytest.mark.parametrize("key", ("validator_revision", "function_policy_revision"))
def test_wrong_source_revision_profile_is_rejected_at_configuration(key, parser_approval):
    with pytest.raises(ConfigurationError):
        replace(parser_approval, **{key: "unreviewed-source-revision"})


def test_profile_cannot_admit_unavailable_parser_class(parser_approval, matrix, payroll_persona):
    wrong = replace(parser_approval, approved_function_rule_ids=parser_approval.approved_function_rule_ids | {"localtimestamp-camel-known-v1"})
    decision = _decision(matrix, wrong, payroll_persona)
    _assert_rejected(decision, ValidationRuleCode.PARSER_PROFILE)
    assert decision.reason_code is ReasonCode.MISSING_DEPENDENCY


def test_missing_parser_capability_fails_closed(monkeypatch, parser_approval, matrix, payroll_persona):
    monkeypatch.setattr(sqlglot, "parse", None)
    decision = _decision(matrix, parser_approval, payroll_persona)
    _assert_rejected(decision, ValidationRuleCode.PARSER_PROFILE)
    assert decision.reason_code is ReasonCode.MISSING_DEPENDENCY
