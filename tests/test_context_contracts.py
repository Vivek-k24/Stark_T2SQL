"""Role projection and frozen-baseline dependency source; no catalog connection."""
from dataclasses import replace
from datetime import date, datetime
from functools import partial
import json

import pytest

from stark_t2sql.context.builder import FrozenBaselineDDL, build_context
from stark_t2sql.context.schema_filter import compile_schema
from stark_t2sql.context.semantic_filter import compile_full_semantics, compile_semantics, serialize_semantics
from stark_t2sql.contracts import ExecutionMode, InputRequest, Persona
from stark_t2sql.errors import ConfigurationError, HarnessSafetyStopError, InvalidRequestError, MissingDependencyError
from stark_t2sql.inference.prompt_builder import build_prompt
from stark_t2sql.semantic.metrics import compile_metric
from stark_t2sql.utils.fingerprints import sha256_context


def test_filtered_ddl_is_deterministic_and_contains_only_visible_columns(matrix,schema_metadata):
    first=compile_schema(schema_metadata,matrix,"app_sales_mgr")
    second=compile_schema(schema_metadata,matrix,"app_sales_mgr")
    assert first.ddl == second.ddl and first.sha256 == second.sha256
    assert '"employee_id"' in first.ddl
    assert "employee_compensation" not in first.ddl and "payroll_results" not in first.ddl
    assert "employee_number" not in first.ddl and "hire_date" not in first.ddl
    visible={table.name:set(column.name for column in table.columns) for table in first.snapshot.tables}
    for table in first.snapshot.tables:
        for key in table.foreign_keys:
            assert key.referenced_table in visible
            assert set(key.columns)<=visible[table.name]
            assert set(key.referenced_columns)<=visible[key.referenced_table]


def test_context_full_only_cannot_be_overridden_by_typed_request(payroll_persona,fixture_date,matrix,schema_metadata,governed_catalog):
    request=InputRequest(payroll_persona,"Unit explicit vocabulary",fixture_date,ExecutionMode.NO_PROMPT_FILTER)
    with pytest.raises(HarnessSafetyStopError):
        build_context(request,schema_metadata,governed_catalog,matrix)


def test_baseline_requires_recorded_actual_ddl_digest_without_guessing(project_root):
    with pytest.raises(MissingDependencyError):
        FrozenBaselineDDL.from_file(project_root/"schema.sql",recorded_sha256=None)


@pytest.fixture
def semantic_entrypoints(governed_catalog, matrix, schema_metadata):
    return {
        "serialize": partial(serialize_semantics, governed_catalog),
        "filtered": partial(compile_semantics, governed_catalog, matrix, schema_metadata, "app_payroll"),
        "full": partial(compile_full_semantics, governed_catalog, matrix),
        "metric": partial(compile_metric, "active_headcount", governed_catalog, matrix, schema_metadata, "app_payroll"),
    }


@pytest.mark.parametrize("entrypoint", ("serialize", "filtered", "full", "metric"))
@pytest.mark.parametrize("invalid", (None, "2026-10-12", datetime(2026, 10, 12), 0, True))
def test_r04_t10_semantic_entrypoints_require_date_not_timestamp(entrypoint, invalid, semantic_entrypoints):
    with pytest.raises(InvalidRequestError):
        semantic_entrypoints[entrypoint](as_of_date=invalid)


@pytest.mark.parametrize("entrypoint", ("serialize", "filtered", "full", "metric"))
def test_r04_t10_missing_date_is_a_typed_request_error(entrypoint, semantic_entrypoints):
    with pytest.raises(InvalidRequestError):
        semantic_entrypoints[entrypoint]()


@pytest.mark.parametrize("role", ("app_payroll", "app_hr_bp", "app_sales_mgr"))
@pytest.mark.parametrize("as_of", (date(2026, 10, 12), date(2024, 2, 29)))
def test_r04_t10_actual_template_receives_bound_least_privilege_semantics(role, as_of, project_root, matrix, schema_metadata, governed_catalog):
    from .test_prompt_template_exact import require_authoritative_template

    # These are request operands, not assertions of a live-resolved identity.
    persona = Persona("Unit role", role, 326, matrix.role(role).login_role)
    context = build_context(InputRequest(persona, "Unit explicit question", as_of, ExecutionMode.FULL), schema_metadata, governed_catalog, matrix)
    repeated = build_context(context.request, schema_metadata, governed_catalog, matrix)
    assert context.semantic_text == repeated.semantic_text and context.semantic_sha256 == repeated.semantic_sha256
    assert context.semantic_sha256 == sha256_context(context.semantic_text)
    prompt = build_prompt(require_authoritative_template(project_root), context)
    for text in (context.semantic_text, prompt.text):
        assert ":as_of_date" not in text and "CAST(:as_of_date" not in text
        assert f"DATE '{as_of.isoformat()}'" in text
    definitions = json.loads(context.semantic_text)
    if role != "app_payroll":
        for hidden in ("employee_compensation", "payroll_runs", "payroll_results", "payroll_earnings", "payroll_deductions", "gross_pay", "net_pay"):
            assert hidden not in prompt.text
    if role == "app_sales_mgr":
        assert "active_headcount" not in context.semantic_text
        employee = next(table for table in compile_schema(schema_metadata, matrix, role).snapshot.tables if table.name == "employees")
        assert {column.name for column in employee.columns} == {"employee_id", "first_name", "last_name", "department_id", "manager_id"}
    assert definitions["metrics"]


def test_every_semantic_sql_field_is_bound_before_serialization(governed_catalog, fixture_date):
    # Pure serializer operands cover every field, including future dated expressions.
    entity = governed_catalog.entities["employee"]
    metric = governed_catalog.metrics["annual_base_salary"]
    temporal = governed_catalog.temporal_rules["compensation_effective_as_of"]
    altered = replace(governed_catalog,
        entities=dict(governed_catalog.entities) | {entity.id: replace(entity, filters=("employees.hire_date <= :as_of_date",))},
        metrics=dict(governed_catalog.metrics) | {metric.id: replace(metric, expression="CAST(:as_of_date AS DATE)", filters=(":as_of_date = :as_of_date",))},
        temporal_rules=dict(governed_catalog.temporal_rules) | {temporal.id: replace(temporal, selection="Use :as_of_date, not the wall clock.")})
    data = json.loads(serialize_semantics(altered, as_of_date=fixture_date))
    assert ":as_of_date" not in json.dumps(data)
    assert next(item for item in data["metrics"] if item["id"] == metric.id)["expression"] == "DATE '2026-10-12'"
    assert "DATE '2026-10-12'" in next(item for item in data["temporal_rules"] if item["id"] == temporal.id)["selection"]


def test_unbound_parameters_in_prose_or_direct_context_fail_closed(governed_catalog, fixture_date, matrix, schema_metadata, payroll_persona):
    metric = governed_catalog.metrics["annual_base_salary"]
    altered = replace(governed_catalog, metrics=dict(governed_catalog.metrics) | {metric.id: replace(metric, description="Unbound :as_of_date")})
    with pytest.raises(ConfigurationError, match="unbound date"):
        serialize_semantics(altered, as_of_date=fixture_date)
    context = build_context(InputRequest(payroll_persona, "Unit question", fixture_date), schema_metadata, governed_catalog, matrix)
    raw = "CAST(:as_of_date AS DATE)"
    with pytest.raises(ConfigurationError, match="before prompt assembly"):
        replace(context, semantic_text=raw, semantic_sha256=sha256_context(raw))


def test_offline_snapshot_retains_real_ddl_keys_types_and_nullability(project_root):
    from .conftest import _offline_schema_snapshot

    snapshot = _offline_schema_snapshot(project_root)
    assert len(snapshot.tables) == 12
    employees = snapshot.table("employees")
    assert employees.primary_key == ("employee_id",)
    assert not next(c for c in employees.columns if c.name == "employee_id").nullable
    assert next(c for c in employees.columns if c.name == "manager_id").nullable
    assert next(c for c in employees.columns if c.name == "employee_number").sql_type == "varchar(6)"
    results = snapshot.table("payroll_results")
    assert ("payroll_run_id", "employee_id") in results.unique_keys
    assert next(c for c in results.columns if c.name == "gross_pay").sql_type == "numeric(14,2)"
    assert any(key.referenced_table == "payroll_runs" and key.on_update == "NO ACTION" and key.on_delete == "RESTRICT" for key in results.foreign_keys)
    assert ("employee_id",) not in snapshot.table("employee_compensation").unique_keys
