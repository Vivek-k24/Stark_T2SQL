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
from stark_t2sql.policy.loader import PolicyMatrix, require_policy_schema
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


def build_probes(matrix: PolicyMatrix, snapshot: SchemaSnapshot) -> tuple[AuthorizationProbe,...]:
    require_policy_schema(matrix,snapshot.columns_by_table)
    probes=[]
    for role in matrix.roles:
        for table in sorted(matrix.tables):
            access=role.tables.get(table)
            columns=snapshot.columns_by_table[table]
            permitted=() if access is None else matrix.permitted_columns(role.name,table,columns)
            scope=None if access is None else access.row_scope
            for column in columns:
                probes.append(AuthorizationProbe(f"authorization.{role.name}.{table}.{column}",role.name,table,column,
                    column in permitted,f"SELECT {quote_identifier(column)} FROM {qualified_name(matrix.schema,table)} LIMIT 0;",scope))
            probes.append(AuthorizationProbe(f"authorization.{role.name}.{table}.star",role.name,table,None,
                access is not None and set(columns)<=set(permitted),
                f"SELECT * FROM {qualified_name(matrix.schema,table)} LIMIT 0;",scope))
    return tuple(probes)
