"""Generate application SELECT grants from the loaded matrix, never apply them."""

from __future__ import annotations

from typing import Mapping, TYPE_CHECKING

from .privileges import managed_role_names, qualified_name, quote_identifier, quote_literal

if TYPE_CHECKING:
    from .loader import PolicyMatrix


def grant_statements(
    matrix: PolicyMatrix,
    schema_columns: Mapping[str, tuple[str, ...]],
    *,
    definer_owner: str,
    baseline_eval_login: str | None = None,
) -> tuple[str, ...]:
    """Remove stale table AND column ACLs before granting the exact entitlement.

    The dynamic column revoke also clears existing unexpected relations in the
    controlled application schema. PostgreSQL table revocation alone does not
    remove column ACLs. No runtime login receives direct application privileges.
    """
    principals = "PUBLIC, " + ", ".join(
        quote_identifier(name) for name in managed_role_names(matrix, definer_owner)
    )
    schema = quote_identifier(matrix.schema)
    statements = [
        f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA {schema} FROM {principals} CASCADE;",
        f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {schema} FROM {principals} CASCADE;",
        f"""DO $stark_column_revokes$
DECLARE target record;
BEGIN
    FOR target IN
        SELECT c.relname,
               pg_catalog.string_agg(pg_catalog.quote_ident(a.attname), ', ' ORDER BY a.attnum)
                   AS column_names
        FROM pg_catalog.pg_class AS c
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
        JOIN pg_catalog.pg_attribute AS a ON a.attrelid = c.oid
        WHERE n.nspname = {quote_literal(matrix.schema)}
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND a.attnum > 0 AND NOT a.attisdropped
        GROUP BY c.oid, c.relname ORDER BY c.relname
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES (%s) ON TABLE %I.%I FROM %s CASCADE',
            target.column_names, {quote_literal(matrix.schema)}, target.relname,
            {quote_literal(principals)}
        );
    END LOOP;
END
$stark_column_revokes$;""",
    ]
    for role in matrix.roles:
        for table in matrix.permitted_tables(role.name):
            access = role.tables[table]
            target = qualified_name(matrix.schema, table)
            grantee = quote_identifier(role.name)
            columns = matrix.permitted_columns(role.name, table, schema_columns[table])
            if access.columns is None:
                statements.append(f"GRANT SELECT ON TABLE {target} TO {grantee};")
            else:
                column_list = ", ".join(quote_identifier(column) for column in columns)
                statements.append(f"GRANT SELECT ({column_list}) ON TABLE {target} TO {grantee};")
    # Only these backing columns are needed by the non-runtime function owner.
    assignment_columns = ", ".join(
        quote_identifier(name) for name in ("employee_id", "division_id", "effective_to")
    )
    statements.append(
        f"GRANT SELECT ({assignment_columns}) ON TABLE "
        f"{qualified_name(matrix.schema, 'hr_bp_assignments')} "
        f"TO {quote_identifier(definer_owner)};"
    )
    if baseline_eval_login is not None:
        eval_target = quote_identifier(baseline_eval_login)
        for table in matrix.tables:
            statements.append(f"GRANT SELECT ON TABLE {qualified_name(matrix.schema, table)} TO {eval_target};")
    return tuple(statements)
