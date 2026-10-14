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
