"""ISS-22: Authorization probes share the canonical policy expectations.

These tests use policy/schema metadata only; they never execute SQL or open a
database session. Probe identities and their generation order are public
benchmark contracts and must remain stable.
"""

from benchmarks.authorization.spec import build_probes
from stark_t2sql.policy.loader import authorization_specs
from stark_t2sql.policy.privileges import qualified_name, quote_identifier


def test_every_column_probe_matches_authoritative_policy_spec(matrix, schema_metadata):
    specs = authorization_specs(matrix, schema_metadata.columns_by_table)
    probes = build_probes(matrix, schema_metadata)
    by_id = {probe.id: probe for probe in probes}
    assert len(probes) == len(by_id)
    for spec in specs:
        if spec.column is None:
            # Spec's None column means a table-level privilege. A star query
            # requires EVERY projected column instead and is tested below.
            continue
        key = f"authorization.{spec.business_role}.{spec.table}.{spec.column}"
        probe = by_id[key]
        assert probe.expected_access is spec.expected_select
        assert probe.row_scope is spec.row_scope
        assert probe.sql == (
            f"SELECT {quote_identifier(spec.column)} "
            f"FROM {qualified_name(matrix.schema, spec.table)} LIMIT 0;"
        )
        assert probe.observes_rows is False


def test_star_probe_is_based_on_all_columns_not_table_level_acl(matrix, schema_metadata):
    specs = authorization_specs(matrix, schema_metadata.columns_by_table)
    probes = {probe.id: probe for probe in build_probes(matrix, schema_metadata)}
    for role in matrix.roles:
        for table in sorted(matrix.tables):
            matching_columns = tuple(
                spec for spec in specs
                if spec.business_role == role.name
                and spec.table == table and spec.column is not None
            )
            assert matching_columns
            star = probes[f"authorization.{role.name}.{table}.star"]
            assert star.expected_access is all(
                spec.expected_select for spec in matching_columns
            )
            assert star.row_scope is matching_columns[0].row_scope
            assert star.sql == (
                f"SELECT * FROM {qualified_name(matrix.schema, table)} LIMIT 0;"
            )
            assert star.observes_rows is False


def test_probe_ids_and_original_order_remain_stable(matrix, schema_metadata):
    actual = tuple(probe.id for probe in build_probes(matrix, schema_metadata))
    expected = tuple(
        item
        for role in matrix.roles
        for table in sorted(matrix.tables)
        for item in (
            *(
                f"authorization.{role.name}.{table}.{column}"
                for column in schema_metadata.columns_by_table[table]
            ),
            f"authorization.{role.name}.{table}.star",
        )
    )
    assert actual == expected


def test_all_column_grants_can_allow_star_without_table_select(matrix, schema_metadata):
    """Synthetic in-memory policy variant; no grants/files are changed."""
    from dataclasses import replace
    payroll = matrix.role("app_payroll")
    access = payroll.tables["employees"]
    explicit_columns = replace(access, columns=schema_metadata.columns_by_table["employees"])
    role = replace(payroll, tables={**payroll.tables, "employees": explicit_columns})
    unit_matrix = replace(matrix, roles=tuple(role if item.name == payroll.name else item for item in matrix.roles))
    specs = authorization_specs(unit_matrix, schema_metadata.columns_by_table)
    table_spec = next(spec for spec in specs if (spec.business_role, spec.table, spec.column) == (payroll.name, "employees", None))
    star = next(probe for probe in build_probes(unit_matrix, schema_metadata) if probe.id == "authorization.app_payroll.employees.star")
    assert table_spec.expected_select is False and star.expected_access is True
    assert star.row_scope is access.row_scope


def test_probe_generation_preserves_role_and_physical_column_order(matrix, schema_metadata):
    from dataclasses import replace
    # Canonical specs sort role names; public probes must retain matrix order.
    unit_matrix = replace(matrix, roles=tuple(reversed(matrix.roles)))
    ids = tuple(probe.id for probe in build_probes(unit_matrix, schema_metadata))
    assert ids == tuple(
        name for role in unit_matrix.roles for table in sorted(unit_matrix.tables)
        for name in (*(f"authorization.{role.name}.{table}.{column}" for column in schema_metadata.columns_by_table[table]), f"authorization.{role.name}.{table}.star")
    )


def test_probe_expectations_use_the_canonical_specification_api(monkeypatch, matrix, schema_metadata):
    from dataclasses import replace
    from benchmarks.authorization import spec as module
    specifications = authorization_specs(matrix, schema_metadata.columns_by_table)
    key = ("app_payroll", "employees", "email")
    # A synthetic changed specification verifies that no duplicated policy
    # computation silently overrides the canonical API's column expectation.
    synthetic = tuple(replace(item, expected_select=False) if (item.business_role, item.table, item.column) == key else item for item in specifications)
    calls = []
    def canonical(selected_matrix, columns):
        calls.append((selected_matrix, columns))
        return synthetic
    monkeypatch.setattr(module, "authorization_specs", canonical)
    probes = {probe.id: probe for probe in build_probes(matrix, schema_metadata)}
    assert len(calls) == 1 and calls[0] == (matrix, schema_metadata.columns_by_table)
    assert probes["authorization.app_payroll.employees.email"].expected_access is False
    assert probes["authorization.app_payroll.employees.star"].expected_access is False


def test_probe_generation_needs_no_database_connection(monkeypatch, matrix, schema_metadata):
    import psycopg2
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError("Authorization probe generation must remain offline")
    monkeypatch.setattr(psycopg2, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    probes = build_probes(matrix, schema_metadata)
    assert probes and all(probe.observes_rows is False for probe in probes)
