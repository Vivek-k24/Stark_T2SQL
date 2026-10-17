"""Fixed grant observations for the future controlled AuthorizationObserver.

These are metadata-derived trusted probes, never model/caller SQL. LIMIT 0
observes projection privileges without extracting forbidden employee values.
The caller must supply actual fixture-resolved role/persona associations and
use audited isolated business credentials. This module opens no connection.
Row-scope evidence is a separate actual-reference requirement, not inferred
from column ACLs or from an empty LIMIT 0 projection.
"""
from dataclasses import dataclass

from stark_t2sql.contracts import RowScopeKind
from stark_t2sql.db.catalog import SchemaSnapshot
from stark_t2sql.policy.loader import PolicyMatrix, authorization_specs
from stark_t2sql.policy.privileges import qualified_name, quote_identifier


@dataclass(frozen=True,slots=True)
class AuthorizationProbe:
    id: str
    business_role: str
    table: str
    column: str | None
    expected_access: bool
    sql: str
    row_scope: RowScopeKind | None
    observes_rows: bool = False


def build_probes(matrix: PolicyMatrix, snapshot: SchemaSnapshot) -> tuple[AuthorizationProbe, ...]:
    """Derive expected column access from the policy loader's canonical specs.

    AuthorizationSpec.column=None records table-level SELECT privilege, which
    is different from whether SELECT * is possible through column-level grants.
    Accordingly, the star probe succeeds only if ALL column specs permit SELECT.
    Keep the original role/table/column/star probe IDs and ordering stable.
    """
    expectations = {
        (spec.business_role, spec.table, spec.column): spec
        for spec in authorization_specs(matrix, snapshot.columns_by_table)
    }
    probes = []
    for role in matrix.roles:
        for table in sorted(matrix.tables):
            columns = snapshot.columns_by_table[table]
            table_spec = expectations[(role.name, table, None)]
            column_specs = [expectations[(role.name, table, column)] for column in columns]
            scope = table_spec.row_scope
            for spec in column_specs:
                probes.append(AuthorizationProbe(
                    f"authorization.{role.name}.{table}.{spec.column}",
                    role.name, table, spec.column, spec.expected_select,
                    f"SELECT {quote_identifier(spec.column)} FROM {qualified_name(matrix.schema, table)} LIMIT 0;",
                    spec.row_scope,
                ))
            probes.append(AuthorizationProbe(
                f"authorization.{role.name}.{table}.star",
                role.name, table, None,
                all(spec.expected_select for spec in column_specs),
                f"SELECT * FROM {qualified_name(matrix.schema, table)} LIMIT 0;",
                scope,
            ))
    return tuple(probes)
