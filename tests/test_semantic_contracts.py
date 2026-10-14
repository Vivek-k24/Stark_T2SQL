"""Governed meanings, ambiguity, entitlement and drift source definitions."""
from dataclasses import replace
from datetime import datetime

import pytest

from stark_t2sql.errors import ConfigurationError, InvalidRequestError
from stark_t2sql.semantic.catalog import detect_schema_drift, detect_semantic_drift, validate_catalog
from stark_t2sql.semantic.contracts import ResolutionStatus
from stark_t2sql.semantic.entitlements import filter_catalog_for_role
from stark_t2sql.semantic.metrics import compile_metric
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


@pytest.mark.parametrize("question", ("headcount", "payroll timing", "organizational unit", "compensation"))
def test_ambiguous_question_does_not_choose_visible_convenient_meaning(question, governed_catalog, matrix, schema_metadata):
    result = resolve_question(question, governed_catalog, matrix, schema_metadata, "app_hr_bp")
    assert result.status is ResolutionStatus.CLARIFICATION_REQUIRED
    assert result.clarification and result.concept_ids == ()


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
    assert validate_catalog(governed_catalog, changed_schema, matrix)
    metric = governed_catalog.metrics["active_headcount"]
    changed_catalog = replace(governed_catalog, metrics=dict(governed_catalog.metrics) | {"active_headcount": replace(metric, expression="COUNT(*)")})
    assert detect_semantic_drift(governed_catalog, changed_catalog)
