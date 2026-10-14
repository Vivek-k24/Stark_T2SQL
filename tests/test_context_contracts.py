"""Role projection and frozen-baseline dependency source; no catalog connection."""
from dataclasses import replace

import pytest

from stark_t2sql.context.builder import FrozenBaselineDDL, build_context
from stark_t2sql.context.schema_filter import compile_schema
from stark_t2sql.contracts import ExecutionMode, InputRequest
from stark_t2sql.errors import HarnessSafetyStopError, MissingDependencyError


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
