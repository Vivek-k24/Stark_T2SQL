"""Future parser contracts require the real reviewed parser/profile.

Missing review input never becomes a generated approval or acceptance claim.
No candidate in these definitions is submitted to a database.
"""
from dataclasses import replace

import pytest

from stark_t2sql.contracts import ReasonCode
from stark_t2sql.security.function_policy import PROPOSED_RULES, ReviewedFunctionPolicy, FunctionPolicyViolation
from stark_t2sql.security.validator import ReviewedSQLValidator, ValidationRuleCode


GOOD_SQL = (
    "SELECT employee_id FROM employees WHERE employee_id > 0 AND (manager_id IS NULL OR manager_id > 0)",
    "SELECT CASE WHEN manager_id IS NULL THEN first_name ELSE last_name END FROM employees",
    "SELECT e.employee_id FROM employees e WHERE EXISTS (SELECT 1 FROM departments d WHERE d.department_id=e.department_id)",
    "SELECT CAST(employee_id AS BIGINT) FROM employees",
    "SELECT COUNT(DISTINCT employee_id) FROM employees",
    "SELECT COUNT(*) FILTER (WHERE manager_id IS NOT NULL) FROM employees",
    "SELECT ROW_NUMBER() OVER (PARTITION BY department_id ORDER BY employee_id) FROM employees",
    "SELECT DATE_TRUNC('month', hire_date) FROM employees",
    "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY base_salary) FROM employee_compensation",
    "SELECT employee_id FROM employees UNION SELECT employee_id FROM employees",
    "SELECT employee_id FROM employees INTERSECT SELECT employee_id FROM employees",
    "SELECT employee_id FROM employees EXCEPT SELECT employee_id FROM employees WHERE manager_id IS NULL",
    '/* leading comment */ SeLeCt "employee_id" FROM public."employees"',
)

BAD_SQL = (
    "SELECT employee_id FROM employees; SET ROLE app_payroll",
    "WITH removed AS (DELETE FROM employees RETURNING employee_id) SELECT employee_id FROM removed",
    "SET ROLE app_payroll", "RESET ROLE", "SET SESSION AUTHORIZATION postgres",
    "SET app.principal_id='326'", "SELECT set_config('app.principal_id','326',true)",
    "WITH employees AS (SELECT 1 AS employee_id) SELECT employee_id FROM employees",
    "WITH employee_compensation AS (SELECT 1) SELECT * FROM employee_compensation",
    "SELECT employee_id FROM pg_temp.employees", "SELECT employee_id FROM other_schema.employees",
    "SELECT rolname FROM pg_catalog.pg_roles", "SELECT table_name FROM information_schema.tables",
    "SELECT * FROM generate_series(1,1000000000)", "SELECT pg_read_file('unavailable-file')",
    "SELECT pg_sleep(60)", "SELECT current_setting('app.principal_id')",
    "SELECT query_to_xml('SELECT 1',true,true,'')", "SELECT dblink('forbidden','SELECT 1')",
    "SELECT LOWER(pg_read_file('unavailable-file'))", "SELECT public.lower(first_name) FROM employees",
    "SELECT encode(decode('00','hex'),'hex')", "SELECT RANDOM()", "SELECT unknown_function(first_name) FROM employees",
    "SELECT ROUND(base_salary, 99) FROM employee_compensation",
    "SELECT DATE_TRUNC('unreviewed-unit', hire_date) FROM employees",
    "SELECT PERCENTILE_CONT(2) WITHIN GROUP (ORDER BY base_salary) FROM employee_compensation",
    "SELECT employee_id INTO temporary_copy FROM employees", "SELECT employee_id FROM employees FOR UPDATE",
    "TABLE employees", "VALUES (1)", "COPY employees TO STDOUT", "DO $$ BEGIN NULL; END $$",
    "EXPLAIN ANALYZE SELECT employee_id FROM employees", "PREPARE p AS SELECT 1", "EXECUTE p",
)


# Every proposed representation has a positive source contract. A profile
# admits only the representations actually reviewed; optional alternatives do
# not become active merely because this dictionary contains a SQL example.
_BY_NAME = {
    "count": "SELECT COUNT(*) FROM employees", "sum": "SELECT SUM(base_salary) FROM employee_compensation",
    "avg": "SELECT AVG(base_salary) FROM employee_compensation", "min": "SELECT MIN(employee_id) FROM employees",
    "max": "SELECT MAX(employee_id) FROM employees", "lower": "SELECT LOWER(first_name) FROM employees",
    "upper": "SELECT UPPER(first_name) FROM employees", "abs": "SELECT ABS(base_salary) FROM employee_compensation",
    "round": "SELECT ROUND(base_salary, 2) FROM employee_compensation",
    "coalesce": "SELECT COALESCE(manager_id,employee_id) FROM employees",
    "nullif": "SELECT NULLIF(manager_id,employee_id) FROM employees",
    "date_trunc": "SELECT DATE_TRUNC('month',hire_date) FROM employees",
    "row_number": "SELECT ROW_NUMBER() OVER (ORDER BY employee_id) FROM employees",
    "rank": "SELECT RANK() OVER (ORDER BY employee_id) FROM employees",
    "dense_rank": "SELECT DENSE_RANK() OVER (ORDER BY employee_id) FROM employees",
    "percentile_cont": "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY base_salary) FROM employee_compensation",
    "cast": "SELECT CAST(employee_id AS BIGINT) FROM employees",
    "extract": "SELECT EXTRACT(YEAR FROM hire_date) FROM employees",
    "current_date": "SELECT CURRENT_DATE", "current_timestamp": "SELECT CURRENT_TIMESTAMP",
    "current_time": "SELECT CURRENT_TIME", "localtimestamp": "SELECT LOCALTIMESTAMP",
    "age": "SELECT AGE(DATE '2026-10-12',DATE '2026-01-01')", "now": "SELECT NOW()",
    "statement_timestamp": "SELECT STATEMENT_TIMESTAMP()", "transaction_timestamp": "SELECT TRANSACTION_TIMESTAMP()",
    "clock_timestamp": "SELECT CLOCK_TIMESTAMP()", "timeofday": "SELECT TIMEOFDAY()",
}
FUNCTION_POSITIVE_SQL = {rule.rule_id: _BY_NAME[rule.sql_name] for rule in PROPOSED_RULES}


@pytest.fixture
def reviewed_validator(matrix, parser_approval):
    return ReviewedSQLValidator(matrix, approval=parser_approval)


@pytest.mark.parametrize("sql", GOOD_SQL)
def test_reviewed_select_shapes_have_positive_contract(sql, reviewed_validator, payroll_persona, matrix):
    decision = reviewed_validator.validate(sql, persona=payroll_persona, policy_fingerprint=matrix.sha256)
    assert decision.accepted, decision.rule_code
    assert decision.regenerated_sql
    second = reviewed_validator.validate(decision.regenerated_sql, persona=payroll_persona, policy_fingerprint=matrix.sha256)
    assert second.accepted and second.regenerated_sql == decision.regenerated_sql


@pytest.mark.parametrize("sql", BAD_SQL)
def test_rejected_shapes_never_provide_execution_text(sql, reviewed_validator, payroll_persona, matrix):
    decision = reviewed_validator.validate(sql, persona=payroll_persona, policy_fingerprint=matrix.sha256)
    assert not decision.accepted
    assert decision.regenerated_sql is None


@pytest.mark.parametrize("rule", PROPOSED_RULES, ids=lambda rule: rule.rule_id)
def test_each_reviewed_signature_positive(rule, parser_approval, reviewed_validator, payroll_persona, matrix):
    if rule.rule_id not in parser_approval.approved_function_rule_ids:
        pytest.skip(f"Signature is not present in actual external review: {rule.rule_id}; no acceptance evidence.")
    import sqlglot
    decision = reviewed_validator.validate(FUNCTION_POSITIVE_SQL[rule.rule_id], persona=payroll_persona, policy_fingerprint=matrix.sha256)
    assert decision.accepted, decision.rule_code
    parsed = sqlglot.parse(FUNCTION_POSITIVE_SQL[rule.rule_id], read="postgres")
    assert len(parsed) == 1
    policy = ReviewedFunctionPolicy(sqlglot.exp, frozenset({rule.rule_id}))
    exact_class = getattr(sqlglot.exp, rule.parser_class)
    matching = [node for node in parsed[0].walk() if type(node) is exact_class]
    if rule.parser_class == "Anonymous":
        # Exercise that individual alternate layout without pretending that
        # this parser chooses it for recognized SQL names. The parsed original
        # supplies actual child expressions and WITHIN GROUP parent semantics.
        projection = parsed[0].expressions[0]
        original = projection.args["this"] if type(projection) is getattr(sqlglot.exp, "WithinGroup", None) else projection
        arguments = {
            "count": [sqlglot.exp.Star()], "sum": [sqlglot.exp.column("base_salary")],
            "avg": [sqlglot.exp.column("base_salary")], "min": [sqlglot.exp.column("employee_id")],
            "max": [sqlglot.exp.column("employee_id")], "lower": [sqlglot.exp.column("first_name")],
            "date_trunc": [sqlglot.exp.Literal.string("month"),sqlglot.exp.column("hire_date")],
            "percentile_cont": [sqlglot.exp.Literal.number("0.5")],
            "age": [sqlglot.exp.Literal.string("2026-10-12"),sqlglot.exp.Literal.string("2026-01-01")],
        }.get(rule.sql_name, [])
        alternative = exact_class(this=rule.sql_name, expressions=arguments)
        original.replace(alternative)
        matching = [alternative]
    assert matching, "Actual reviewed node layout did not occur; review/profile reconciliation is required."
    assert any(policy.require(node).rule_id == rule.rule_id for node in matching)


def test_no_actual_review_fails_closed(matrix, payroll_persona):
    decision = ReviewedSQLValidator(matrix).validate("SELECT employee_id FROM employees", persona=payroll_persona, policy_fingerprint=matrix.sha256)
    assert not decision.accepted and decision.rule_code is ValidationRuleCode.REVIEW_REQUIRED
    assert decision.reason_code is ReasonCode.MISSING_DEPENDENCY


def test_columns_are_reserved_to_database_grants(reviewed_validator, hr_persona, matrix):
    decision = reviewed_validator.validate("SELECT employee_number FROM employees", persona=hr_persona, policy_fingerprint=matrix.sha256)
    assert decision.accepted  # No DB call; future column-grant enforcement remains separate.


@pytest.mark.parametrize("rule", PROPOSED_RULES, ids=lambda rule: rule.rule_id)
def test_each_reviewed_signature_rejects_unreviewed_arguments(rule,parser_approval):
    if rule.rule_id not in parser_approval.approved_function_rule_ids:
        pytest.skip(f"Signature not actually reviewed: {rule.rule_id}; no acceptance evidence.")
    import sqlglot
    exact_class=getattr(sqlglot.exp,rule.parser_class)
    if rule.parser_class == "Anonymous":
        node=exact_class(this=rule.sql_name,expressions=[])
    else:
        statements=sqlglot.parse(FUNCTION_POSITIVE_SQL[rule.rule_id],read="postgres")
        node=next(item for item in statements[0].walk() if type(item) is exact_class)
    node.set("unreviewed_option",True)
    with pytest.raises(FunctionPolicyViolation):
        ReviewedFunctionPolicy(sqlglot.exp,frozenset({rule.rule_id})).require(node)
