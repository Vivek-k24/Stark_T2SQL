"""Authored future fixture-source contracts; no generated fixture is embedded.

These definitions were not invoked during the source-authoring assignment.
Negative input examples below are deliberately incomplete configuration input,
not authoritative employee/reference rows, a fixture manifest or fake hashes.
"""

from pathlib import Path
from types import MappingProxyType

import pytest

import seed_data


def test_fixed_business_date_seed_and_cardinalities_are_explicit():
    assert seed_data.FIXTURE_DATE.isoformat() == "2026-10-12"
    assert seed_data.FIXTURE_SEED == 42
    assert seed_data.FIXTURE_VERSION == "spb_2026_10_12"
    assert seed_data.EMPLOYEE_COUNT == 500
    assert seed_data.DIVISION_COUNT == 10
    assert seed_data.DEPARTMENT_COUNT == 37
    assert seed_data.ACTIVE_EMPLOYEE_COUNT == 435


def test_eighteen_operational_invariant_functions_have_distinct_names():
    invariants = seed_data.OPERATIONAL_INVARIANTS
    assert len(invariants) == 18
    assert len({invariant.__name__ for invariant in invariants}) == 18
    assert [function.__name__.split("_")[1] for function in invariants] == [
        str(index).zfill(2) for index in range(1, 19)
    ]


def test_physical_contract_contains_only_the_twelve_draft_tables():
    assert set(seed_data.TABLE_COLUMNS) == {
        "divisions", "locations", "departments", "positions", "employees",
        "employee_compensation", "payroll_runs", "payroll_results",
        "payroll_earnings", "payroll_deductions", "leave_balances",
        "hr_bp_assignments",
    }
    assert set(seed_data.TABLE_PRIMARY_KEYS) == set(seed_data.TABLE_COLUMNS)
    assert all(columns[0] == seed_data.TABLE_PRIMARY_KEYS[table]
               for table, columns in seed_data.TABLE_COLUMNS.items())


def test_table_contract_mapping_is_immutable():
    with pytest.raises(TypeError):
        seed_data.TABLE_COLUMNS["another_table"] = ("id",)


def test_empty_owner_configuration_has_no_invented_schema_defaults(tmp_path):
    configuration = tmp_path / "incomplete-owner-input.json"
    configuration.write_text("{}", encoding="utf-8")
    with pytest.raises(seed_data.MissingSeedInputError, match="schema_fidelity"):
        seed_data.load_seed_configuration(configuration, project_root=tmp_path)


def test_missing_owner_configuration_is_an_explicit_dependency(tmp_path):
    with pytest.raises(seed_data.MissingSeedInputError, match="Authoritative seed configuration"):
        seed_data.load_seed_configuration(tmp_path / "unavailable-owner-input.json", project_root=tmp_path)


def test_owner_configuration_cannot_resolve_outside_workspace(tmp_path):
    outside = tmp_path.parent / "outside-owner-input.json"
    with pytest.raises(seed_data.MissingSeedInputError, match="workspace"):
        seed_data.load_seed_configuration(outside, project_root=tmp_path)


def test_historical_fidelity_inputs_are_required_before_reference_data(tmp_path):
    configuration = tmp_path / "incomplete-owner-input.json"
    configuration.write_text('{"schema_fidelity": {}}', encoding="utf-8")
    with pytest.raises(seed_data.MissingSeedInputError, match="project_schema_path"):
        seed_data.load_seed_configuration(configuration, project_root=tmp_path)


def test_missing_historical_schema_is_not_substituted_with_current_schema(tmp_path):
    config = tmp_path / "incomplete-owner-input.json"
    # Negative layout input only; no real/source hashes or review evidence.
    config.write_text(
        '{"schema_fidelity": {"project_schema_path": "schema.sql", '
        '"historical_schema_path": "schema.sql"}}', encoding="utf-8"
    )
    with pytest.raises(seed_data.MissingSeedInputError, match="distinct actual historical DDL"):
        seed_data.load_seed_configuration(config, project_root=tmp_path)


def test_generator_rejects_an_absent_typed_owner_configuration():
    with pytest.raises(seed_data.MissingSeedInputError, match="owner configuration"):
        seed_data.generate_fixture(None)


def test_loader_rejects_non_administrative_capability_before_reading_inputs(tmp_path):
    with pytest.raises(seed_data.MissingSeedInputError, match="administrative source"):
        seed_data.create_fixture(tmp_path / "unavailable-owner-input.json",
                                 project_root=tmp_path, admin_source=object())


def test_no_real_dump_manifest_or_output_file_writer_is_exposed():
    # API ownership: exporting the authoritative dump/manifest is deliberately
    # a separate task and must not be implied by the source generator.
    assert not hasattr(seed_data, "write_fixture_dump")
    assert not hasattr(seed_data, "write_fixture_manifest")
    assert not hasattr(seed_data, "export_fixture")


def test_empty_row_contract_cannot_be_taken_as_a_complete_fixture():
    empty = seed_data.GeneratedFixture(
        MappingProxyType({table: () for table in seed_data.TABLE_COLUMNS}),
        configuration_sha256="", fidelity=None,
    )
    employee_result = seed_data.check_03_employee_identity(empty, None)
    lifecycle_result = seed_data.check_05_employee_lifecycle(empty, None)
    assert employee_result.invariant_id == "DRAFT-FIXTURE-03"
    assert employee_result.satisfied is False
    assert lifecycle_result.invariant_id == "DRAFT-FIXTURE-05"
    assert lifecycle_result.satisfied is False


def test_empty_table_inventory_and_shape_are_separate_from_cardinality():
    empty = seed_data.GeneratedFixture(
        MappingProxyType({table: () for table in seed_data.TABLE_COLUMNS}),
        configuration_sha256="", fidelity=None,
    )
    shape = seed_data.check_01_table_contract(empty, None)
    cardinality = seed_data.check_02_reference_cardinality(empty, None)
    assert shape.invariant_id == "DRAFT-FIXTURE-01"
    assert shape.satisfied is True
    assert cardinality.invariant_id == "DRAFT-FIXTURE-02"
    assert cardinality.satisfied is False


def test_unknown_table_returns_no_rows_and_no_fixture_answer():
    empty = seed_data.GeneratedFixture(MappingProxyType({}), "", None)
    assert empty.table("unavailable_table") == ()


def test_operational_invariant_results_explicitly_identify_draft_provenance():
    result = seed_data.InvariantResult("DRAFT-FIXTURE-18", "Authored definition", False, "Missing external input")
    assert result.invariant_id.startswith("DRAFT-FIXTURE-")
    assert result.satisfied is False
    assert result.detail == "Missing external input"
