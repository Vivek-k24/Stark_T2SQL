"""SQL text helpers and managed-role hardening; nothing executes this module's SQL.

The source-only authorship exception is documented by the Prompt 2 handoff.
Applying these statements later requires a distinct trusted setup connection,
a dedicated fixture database, and an atomic transaction after fixture restore.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..errors import ConfigurationError

if TYPE_CHECKING:
    from .compiler import CompileSettings
    from .loader import PolicyMatrix


def quote_identifier(value: str) -> str:
    """Quote a single PostgreSQL identifier, refusing truncation/control bytes."""
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > 63
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ConfigurationError("SQL identifiers must be nonempty and at most 63 UTF-8 bytes.")
    return '"' + value.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    """Use explicit escape-string syntax so session string settings cannot alter SQL."""
    if not isinstance(value, str) or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ConfigurationError("SQL text literals cannot contain control characters.")
    return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def qualified_name(schema: str, name: str) -> str:
    return f"{quote_identifier(schema)}.{quote_identifier(name)}"


def managed_role_names(matrix: PolicyMatrix, definer_owner: str) -> tuple[str, ...]:
    return tuple(role.name for role in matrix.roles) + tuple(
        role.login_role for role in matrix.roles
    ) + (definer_owner,)


def trusted_search_path(schema: str) -> str:
    if schema == "pg_catalog" or schema == "pg_temp" or schema.startswith("pg_"):
        raise ConfigurationError("The application schema cannot be a PostgreSQL system schema.")
    return f'"pg_catalog", {quote_identifier(schema)}, "pg_temp"'


def require_definer_name(name: str, matrix: PolicyMatrix) -> None:
    quote_identifier(name)
    runtime_names = {role.name for role in matrix.roles} | {
        role.login_role for role in matrix.roles
    }
    if (
        re.fullmatch(r"[a-z_][a-z0-9_]*", name) is None
        or name.startswith("pg_")
        or name in runtime_names | {"public", "postgres"}
    ):
        raise ConfigurationError("The definer owner must be a distinct dedicated NOLOGIN role.")


def _role_array(names: tuple[str, ...]) -> str:
    return "ARRAY[" + ", ".join(quote_literal(name) for name in names) + "]::text[]"


def role_statements(matrix: PolicyMatrix, settings: CompileSettings) -> tuple[str, ...]:
    """Create/normalize only dedicated roles, rejecting privileged role reuse."""
    names = managed_role_names(matrix, settings.definer_owner)
    name_array = _role_array(names)
    schema_literal = quote_literal(matrix.schema)
    owner_literal = quote_literal(settings.definer_owner)
    statements: list[str] = []
    # A pre-existing privileged role must never be repurposed or quietly demoted.
    statements.append(
        f"""DO $stark_role_safety$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles AS r
        WHERE r.rolname = ANY ({name_array})
          AND (r.rolsuper OR r.rolbypassrls OR r.rolcreatedb
               OR r.rolcreaterole OR r.rolreplication)
    ) THEN
        RAISE EXCEPTION 'A managed role already has privileged attributes';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_shdepend AS dependency
        JOIN pg_catalog.pg_roles AS r ON r.oid = dependency.refobjid
        WHERE dependency.refclassid = 'pg_catalog.pg_authid'::pg_catalog.regclass
          AND dependency.deptype = 'o'
          AND r.rolname = ANY ({name_array})
          AND (dependency.dbid = 0 OR dependency.dbid = (
              SELECT d.oid FROM pg_catalog.pg_database AS d
              WHERE d.datname = pg_catalog.current_database()
          ))
          AND NOT (
              r.rolname = {owner_literal}
              AND dependency.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass
              AND dependency.objid IN (
                  SELECT p.oid FROM pg_catalog.pg_proc AS p
                  JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
                  WHERE n.nspname = {schema_literal}
                    AND p.proname = 'hr_bp_current_divisions' AND p.pronargs = 0
              )
          )
    ) THEN
        RAISE EXCEPTION 'A managed role owns an unauthorized database object';
    END IF;
END
$stark_role_safety$;"""
    )
    login_names = {role.login_role for role in matrix.roles}
    for name in names:
        attributes = (
            ("LOGIN" if name in login_names else "NOLOGIN")
            + " NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION"
        )
        create_text = f"CREATE ROLE {quote_identifier(name)} {attributes}"
        statements.append(
            f"""DO $stark_create_role$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = {quote_literal(name)}) THEN
        EXECUTE {quote_literal(create_text)};
    END IF;
END
$stark_create_role$;"""
        )
        statements.append(f"ALTER ROLE {quote_identifier(name)} {attributes};")
        statements.append(f"ALTER ROLE {quote_identifier(name)} RESET ALL;")
    # PostgreSQL 16 memberships carry separate INHERIT/SET/ADMIN options.
    # Remove every grantor's edge touching managed identities before rebuilding.
    statements.append(
        f"""DO $stark_memberships$
DECLARE edge record;
BEGIN
    FOR edge IN
        SELECT parent.rolname AS parent_name, member.rolname AS member_name,
               grantor.rolname AS grantor_name
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS parent ON parent.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member ON member.oid = membership.member
        JOIN pg_catalog.pg_roles AS grantor ON grantor.oid = membership.grantor
        WHERE parent.rolname = ANY ({name_array})
           OR member.rolname = ANY ({name_array})
        ORDER BY parent.rolname, member.rolname, grantor.rolname
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE %I FROM %I GRANTED BY %I CASCADE',
            edge.parent_name, edge.member_name, edge.grantor_name
        );
    END LOOP;
END
$stark_memberships$;"""
    )
    for role in matrix.roles:
        statements.append(
            f"GRANT {quote_identifier(role.name)} TO {quote_identifier(role.login_role)} "
            "WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;"
        )
    return tuple(statements)


def schema_statements(matrix: PolicyMatrix, settings: CompileSettings) -> tuple[str, ...]:
    names = managed_role_names(matrix, settings.definer_owner)
    role_list = ", ".join(quote_identifier(name) for name in names)
    principals = "PUBLIC, " + role_list
    schema = quote_identifier(matrix.schema)
    schema_literal = quote_literal(matrix.schema)
    name_array = _role_array(names)
    statements = [
        f"REVOKE ALL PRIVILEGES ON SCHEMA {schema} FROM {role_list} CASCADE;",
        f"REVOKE CREATE ON SCHEMA {schema} FROM PUBLIC CASCADE;",
        f"GRANT USAGE ON SCHEMA {schema} TO {role_list};",
        f"""DO $stark_database_privileges$
BEGIN
    EXECUTE pg_catalog.format(
        'REVOKE CREATE, TEMPORARY ON DATABASE %I FROM %s CASCADE',
        pg_catalog.current_database(), {quote_literal(principals)}
    );
END
$stark_database_privileges$;""",
        # Other-schema CREATE is not silently repaired outside the owned boundary.
        f"""DO $stark_schema_safety$
DECLARE target record;
BEGIN
    FOR target IN
        SELECT n.nspname, r.rolname
        FROM pg_catalog.pg_namespace AS n CROSS JOIN pg_catalog.pg_roles AS r
        WHERE r.rolname = ANY ({name_array})
          AND n.nspname <> {schema_literal}
          AND pg_catalog.has_schema_privilege(r.oid, n.oid, 'CREATE')
        ORDER BY n.nspname, r.rolname
    LOOP
        RAISE EXCEPTION 'Managed role % can create objects in schema %',
            target.rolname, target.nspname;
    END LOOP;
    IF EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc AS p
        JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = {schema_literal}
          AND p.proname = 'hr_bp_current_divisions' AND p.pronargs <> 0
    ) THEN
        RAISE EXCEPTION 'An unauthorized principal-argument scope function exists';
    END IF;
END
$stark_schema_safety$;""",
    ]
    return tuple(statements)


def login_default_statements(
    matrix: PolicyMatrix, settings: CompileSettings
) -> tuple[str, ...]:
    search_path = trusted_search_path(matrix.schema)
    statements: list[str] = []
    defaults = (
        ("statement_timeout", f"{settings.statement_timeout_ms}ms"),
        ("default_transaction_read_only", "on"),
        ("row_security", "on"),
        ("work_mem", f"{settings.work_mem_kib}kB"),
        ("temp_file_limit", f"{settings.temp_file_limit_kib}kB"),
    )
    for role in matrix.roles:
        login = quote_identifier(role.login_role)
        # Role+database defaults override global role defaults: clear old overrides
        # in this fixture database, then set the same reviewed settings explicitly.
        statements.append(
            f"""DO $stark_reset_database_defaults$
BEGIN
    EXECUTE pg_catalog.format('ALTER ROLE %I IN DATABASE %I RESET ALL',
        {quote_literal(role.login_role)}, pg_catalog.current_database());
END
$stark_reset_database_defaults$;"""
        )
        for key, value in defaults:
            statements.append(f"ALTER ROLE {login} SET {key} = {quote_literal(value)};")
        statements.append(f"ALTER ROLE {login} SET search_path = {search_path};")
        per_database_commands = []
        for key, value in defaults:
            suffix = f"SET {key} = {quote_literal(value)}"
            per_database_commands.append(
                "    EXECUTE pg_catalog.format('ALTER ROLE %I IN DATABASE %I %s', "
                f"{quote_literal(role.login_role)}, pg_catalog.current_database(), "
                f"{quote_literal(suffix)});"
            )
        per_database_commands.append(
            "    EXECUTE pg_catalog.format('ALTER ROLE %I IN DATABASE %I %s', "
            f"{quote_literal(role.login_role)}, pg_catalog.current_database(), "
            f"{quote_literal('SET search_path = ' + search_path)});"
        )
        statements.append(
            "DO $stark_database_defaults$\nBEGIN\n"
            + "\n".join(per_database_commands)
            + "\nEND\n$stark_database_defaults$;"
        )
    return tuple(statements)


def set_config_statements(matrix: PolicyMatrix, settings: CompileSettings) -> tuple[str, ...]:
    """These statements belong only to administrative setup AFTER dump restore."""
    managed = ", ".join(
        quote_identifier(name) for name in managed_role_names(matrix, settings.definer_owner)
    )
    logins = ", ".join(quote_identifier(role.login_role) for role in matrix.roles)
    signature = "pg_catalog.set_config(text, text, boolean)"
    return (
        f"REVOKE ALL PRIVILEGES ON FUNCTION {signature} FROM PUBLIC, {managed} CASCADE;",
        f"GRANT EXECUTE ON FUNCTION {signature} TO {logins};",
    )
