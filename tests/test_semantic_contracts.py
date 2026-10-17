"""Governed meanings, ambiguity, entitlement and drift source definitions."""
from dataclasses import replace
from datetime import date, datetime

import pytest

from stark_t2sql.errors import ConfigurationError, InvalidRequestError
from stark_t2sql.semantic.catalog import detect_schema_drift, detect_semantic_drift, validate_catalog
from stark_t2sql.semantic.contracts import ResolutionStatus
from stark_t2sql.semantic.entitlements import filter_catalog_for_role
from stark_t2sql.semantic.metrics import _bind_date, compile_metric
from stark_t2sql.semantic.resolver import resolve_question, resolve_term


def test_active_headcount_canonical_grain_and_date(governed_catalog, matrix, schema_metadata, fixture_date):
    contract = compile_metric("active_headcount", governed_catalog, matrix, schema_metadata, "app_payroll", fixture_date)
    assert contract.expression == "COUNT(DISTINCT employees.employee_id)"
    assert tuple(map(str, contract.grain)) == ("employees.employee_id",)
    filters = " ".join(contract.filters)
    assert "full_time" in filters and "part_time" in filters and "cancelled_pre_hire" in filters
    assert "hire_date <=" in filters and "termination_date >" in filters and "termination_date IS NULL" in filters
    assert "2026-10-12" in filters and ":as_of_date" not in filters


def test_engineering_is_division_and_synonym(governed_catalog, matrix, schema_metadata):
    for term in ("Engineering", "engineering division"):
        result = resolve_term(term, governed_catalog, matrix, schema_metadata, "app_hr_bp")
        assert result.status is ResolutionStatus.RESOLVED and result.concept_ids == ("engineering_division",)
    entity = governed_catalog.entities["engineering_division"]
    assert entity.kind == "division_member" and entity.source_tables == ("divisions",)


def test_payroll_status_bonus_and_time_definitions(governed_catalog):
    payroll = governed_catalog.metrics["posted_closed_payroll_run_count"]
    assert any("posted" in item and "closed" in item and "IN" in item for item in payroll.filters)
    bonus = governed_catalog.metrics["bonus_target_percentage"]
    assert bonus.expression == "employee_compensation.bonus_target_pct"
    assert bonus.aggregation == "none" and bonus.units == "percentage_points"
    assert governed_catalog.entities["payroll_pay_date"].source_columns != governed_catalog.entities["payroll_period_end"].source_columns


@pytest.mark.parametrize("question,role", (
    ("headcount", "app_hr_bp"), ("organizational unit", "app_hr_bp"),
    ("payroll timing", "app_payroll"), ("compensation", "app_payroll"),
))
def test_ambiguous_question_does_not_choose_visible_convenient_meaning(question, role, governed_catalog, matrix, schema_metadata):
    result = resolve_question(question, governed_catalog, matrix, schema_metadata, role)
    assert result.status is ResolutionStatus.CLARIFICATION_REQUIRED
    assert result.clarification and result.clarification.options and result.concept_ids == ()


def test_sales_i01_retains_visible_count_but_disables_active_headcount(governed_catalog, matrix, schema_metadata, fixture_date):
    visible = filter_catalog_for_role(governed_catalog, matrix, schema_metadata, "app_sales_mgr")
    assert "active_headcount" not in visible.metrics
    assert "direct_report_count" in visible.metrics
    assert "annual_base_salary" not in visible.metrics
    with pytest.raises(ConfigurationError):
        compile_metric("active_headcount", governed_catalog, matrix, schema_metadata, "app_sales_mgr", fixture_date)
    assert not any(ref.table == "employee_compensation" for metric in visible.metrics.values() for ref in metric.source_columns)


def test_metric_rejects_datetime_and_missing_business_date(governed_catalog, matrix, schema_metadata):
    with pytest.raises(InvalidRequestError):
        compile_metric("active_headcount", governed_catalog, matrix, schema_metadata, "app_payroll", datetime(2026,10,12))


def test_compensation_and_leave_time_basis_is_not_wallclock(governed_catalog):
    compensation=governed_catalog.temporal_rules["compensation_effective_as_of"]
    assert "effective_date <=" in compensation.predicate
    assert "effective_to IS NULL" in compensation.predicate and "effective_to >" in compensation.predicate
    assert ":as_of_date" in compensation.predicate
    leave=governed_catalog.temporal_rules["leave_snapshot_as_of"]
    assert "as_of_date" in leave.predicate and leave.selection
    assert "CURRENT_DATE" not in compensation.predicate+leave.predicate+leave.selection


def test_schema_and_definition_changes_produce_drift(governed_catalog, matrix, schema_metadata):
    employees = schema_metadata.table("employees")
    changed_table = replace(employees, columns=tuple(column for column in employees.columns if column.name != "hire_date"))
    changed_schema = replace(schema_metadata, tables=tuple(changed_table if table.name == "employees" else table for table in schema_metadata.tables))
    assert detect_schema_drift(schema_metadata, changed_schema)
    # Policy/schema validation fails closed before catalog issues can be returned.
    with pytest.raises(ConfigurationError, match="Policy/schema preflight"):
        validate_catalog(governed_catalog, changed_schema, matrix)
    metric = governed_catalog.metrics["active_headcount"]
    changed_catalog = replace(governed_catalog, metrics=dict(governed_catalog.metrics) | {"active_headcount": replace(metric, expression="COUNT(*)")})
    assert detect_semantic_drift(governed_catalog, changed_catalog)


MONETARY = {"gross_pay", "net_pay", "total_earnings_amount", "total_deductions_amount"}
HEADCOUNTS = {"active_headcount", "visible_employee_count", "direct_report_count"}


@pytest.mark.parametrize("role", ("app_payroll", "app_hr_bp", "app_sales_mgr"))
def test_r04_t01_t03_exact_metric_visibility(role, governed_catalog, matrix, schema_metadata):
    visible = filter_catalog_for_role(governed_catalog, matrix, schema_metadata, role)
    if role == "app_payroll":
        assert set(visible.metrics) == set(governed_catalog.metrics)
    elif role == "app_hr_bp":
        assert set(visible.metrics) == HEADCOUNTS | {"leave_balance_hours"}
    else:
        assert set(visible.metrics) == HEADCOUNTS - {"active_headcount"}
    if role != "app_payroll":
        assert not MONETARY & set(visible.metrics)
        assert "annual_base_salary" not in visible.metrics and "bonus_target_percentage" not in visible.metrics
        assert all(not table.startswith("payroll_") and table != "employee_compensation"
                   for metric in visible.metrics.values() for table in metric.source_tables)


@pytest.mark.parametrize("role,options", (
    ("app_payroll", ("Active headcount", "Direct report row count", "Visible employee row count")),
    ("app_hr_bp", ("Active headcount", "Direct report row count", "Visible employee row count")),
    ("app_sales_mgr", ("Direct report row count", "Visible employee row count")),
))
@pytest.mark.parametrize("resolve", (resolve_term, resolve_question))
def test_r04_t04_t05_headcount_uses_all_and_only_actual_entitlements(role, options, resolve, governed_catalog, matrix, schema_metadata):
    result = resolve("headcount", governed_catalog, matrix, schema_metadata, role)
    assert result.status is ResolutionStatus.CLARIFICATION_REQUIRED and not result.concept_ids
    assert result.clarification.options == options


@pytest.mark.parametrize("role", ("app_hr_bp", "app_sales_mgr"))
@pytest.mark.parametrize("phrase", ("compensation", "payroll", "annual base salary", "gross pay", "total deductions"))
@pytest.mark.parametrize("resolve", (resolve_term, resolve_question))
def test_hidden_concept_never_becomes_an_empty_clarification_or_visible_meaning(role, phrase, resolve, governed_catalog, matrix, schema_metadata):
    result = resolve(phrase, governed_catalog, matrix, schema_metadata, role)
    assert result.status is ResolutionStatus.RESOLVED and result.concept_ids == ()
    assert result.clarification is None


def test_hidden_longest_phrase_cannot_fall_back_to_headcount(governed_catalog, matrix, schema_metadata):
    result = resolve_question("Show active headcount", governed_catalog, matrix, schema_metadata, "app_sales_mgr")
    assert result.status is ResolutionStatus.RESOLVED and result.concept_ids == ()
    # A separate genuine ambiguity must still ask, rather than choosing either count.
    result = resolve_question("Show active headcount and headcount", governed_catalog, matrix, schema_metadata, "app_sales_mgr")
    assert result.clarification.options == ("Direct report row count", "Visible employee row count")


def test_unknown_explicit_term_asks_only_answerable_visible_vocabulary(governed_catalog, matrix, schema_metadata):
    visible = filter_catalog_for_role(governed_catalog, matrix, schema_metadata, "app_sales_mgr")
    result = resolve_term("Unit unknown meaning", governed_catalog, matrix, schema_metadata, "app_sales_mgr")
    assert result.status is ResolutionStatus.CLARIFICATION_REQUIRED
    assert set(result.clarification.options) == {item.name for item in (*visible.entities.values(), *visible.metrics.values())}


@pytest.mark.parametrize("resolve", (resolve_term, resolve_question))
def test_only_multiple_visible_meanings_are_ambiguous(resolve, governed_catalog, matrix, schema_metadata):
    bonus = governed_catalog.metrics["bonus_target_percentage"]
    catalog = replace(governed_catalog, metrics=dict(governed_catalog.metrics) | {
        bonus.id: replace(bonus, pending_roles=("app_payroll",)),
    })
    result = resolve("compensation", catalog, matrix, schema_metadata, "app_payroll")
    assert result.status is ResolutionStatus.RESOLVED and result.concept_ids == ("annual_base_salary",)
    assert result.clarification is None


def test_headcount_choices_follow_backing_columns_not_a_role_name(governed_catalog, matrix, schema_metadata):
    role = matrix.role("app_hr_bp")
    employees = role.tables["employees"]
    narrowed_role = replace(role, tables=dict(role.tables) | {
        "employees": replace(employees, columns=tuple(c for c in employees.columns if c != "manager_id")),
    })
    narrowed = replace(matrix, roles=tuple(narrowed_role if item.name == role.name else item for item in matrix.roles))
    result = resolve_question("headcount", governed_catalog, narrowed, schema_metadata, role.name)
    assert result.clarification.options == ("Active headcount", "Visible employee row count")


@pytest.mark.parametrize("metric_id,table,column", (
    ("gross_pay", "payroll_results", "gross_pay"),
    ("net_pay", "payroll_results", "net_pay"),
    ("total_earnings_amount", "payroll_earnings", "amount"),
    ("total_deductions_amount", "payroll_deductions", "amount"),
    ("total_earnings_amount", "payroll_runs", "status"),
    ("total_deductions_amount", "payroll_runs", "pay_date"),
))
def test_monetary_visibility_requires_amount_and_temporal_lineage(metric_id, table, column, governed_catalog, matrix, schema_metadata):
    role = matrix.role("app_payroll")
    columns = matrix.permitted_columns(role.name, table, schema_metadata.columns_by_table[table])
    narrowed_role = replace(role, tables=dict(role.tables) | {
        table: replace(role.tables[table], columns=tuple(c for c in columns if c != column)),
    })
    narrowed = replace(matrix, roles=tuple(narrowed_role if item.name == role.name else item for item in matrix.roles))
    assert metric_id not in filter_catalog_for_role(governed_catalog, narrowed, schema_metadata, role.name).metrics


@pytest.mark.parametrize("metric_id,grain,links,expression", (
    ("gross_pay", ("payroll_results.payroll_result_id",), {"result_run"}, "payroll_results.gross_pay"),
    ("net_pay", ("payroll_results.payroll_result_id",), {"result_run"}, "payroll_results.net_pay"),
    ("total_earnings_amount", ("payroll_runs.payroll_run_id",), {"result_run", "earning_result"}, "COALESCE(SUM(payroll_earnings.amount), 0)"),
    ("total_deductions_amount", ("payroll_runs.payroll_run_id",), {"result_run", "deduction_result"}, "COALESCE(SUM(payroll_deductions.amount), 0)"),
))
def test_monetary_lineage_grain_null_and_payment_date_contracts(metric_id, grain, links, expression, governed_catalog, matrix, schema_metadata, fixture_date):
    assert validate_catalog(governed_catalog, schema_metadata, matrix) == ()
    metric = compile_metric(metric_id, governed_catalog, matrix, schema_metadata, "app_payroll", fixture_date)
    assert metric.expression == expression and tuple(map(str, metric.grain)) == grain
    assert {link.id for link in metric.relationships} == links
    assert metric.filters == ("payroll_runs.status IN ('posted', 'closed')",)
    assert metric.temporal_rules[0].predicate == "payroll_runs.pay_date <= DATE '2026-10-12'"
    assert metric.units == "USD" and metric.null_handling
    assert metric.aggregation == ("sum" if metric_id.startswith("total_") else "none")
    for role in ("app_hr_bp", "app_sales_mgr"):
        with pytest.raises(ConfigurationError):
            compile_metric(metric_id, governed_catalog, matrix, schema_metadata, role, fixture_date)
    definition = governed_catalog.metrics[metric_id]
    broken = replace(definition, relationship_ids=())
    altered = replace(governed_catalog, metrics=dict(governed_catalog.metrics) | {metric_id: broken})
    assert any(issue.code == "JOIN_PATH" for issue in validate_catalog(altered, schema_metadata, matrix))


@pytest.mark.parametrize("fragment", (
    ":as_of_date", "CAST(:as_of_date AS DATE)", "cast ( :as_of_date as date )",
))
def test_date_binding_resolves_direct_and_cast_forms(fragment):
    assert _bind_date(fragment, date(2025, 2, 3)) == "DATE '2025-02-03'"


def test_date_binding_rejects_other_runtime_parameters(fixture_date):
    with pytest.raises(ConfigurationError):
        _bind_date(":principal_id", fixture_date)
