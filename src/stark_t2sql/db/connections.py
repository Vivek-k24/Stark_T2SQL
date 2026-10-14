"""Separate trusted setup, business, and disposable evaluation connections.

This is source only. psycopg2 is imported lazily at an explicitly invoked future
connection boundary. Every candidate connection is fresh, bound to one login,
audited before use, read-only, and discarded on exit. No DSN, arbitrary driver
factory, administrative fallback, or unaudited pool is accepted by runtime code.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import importlib
import json
import os
import re
from typing import TYPE_CHECKING, Any

from stark_t2sql.config import AppConfig, DatabaseConnectionAlias, DatabaseCredentials
from stark_t2sql.contracts import Persona
from stark_t2sql.errors import ConfigurationError, DatabaseExecutionError, MissingDependencyError
from stark_t2sql.utils.local_only import require_allowed_host_port, require_loopback_host
from .persona import PersonaRegistry, fixture_digest

if TYPE_CHECKING:
    from stark_t2sql.policy.loader import PolicyMatrix, RolePolicy


def _driver() -> Any:
    try:
        return importlib.import_module("psycopg2")
    except ImportError as exc:
        raise MissingDependencyError("The local psycopg2 runtime dependency is unavailable.") from exc


def _open(config: AppConfig, credentials: DatabaseCredentials) -> Any:
    endpoint = require_allowed_host_port(
        credentials.host, credentials.port,
        scheme="postgresql", allowed_endpoints=config.allowed_runtime_endpoints,
    )
    # An inherited libpq service can consult a service file/LDAP. Endpoint
    # keyword overrides alone do not authorize that lookup. Fail before connect.
    if any(os.environ.get(name) for name in ("PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR")):
        raise ConfigurationError("Inherited libpq service configuration is forbidden.")
    driver = _driver()
    connection = None
    try:
        connection = driver.connect(
            host=endpoint.host,
            hostaddr=endpoint.host,  # PGHOSTADDR cannot override the loopback guard.
            port=endpoint.port,
            dbname=credentials.database,
            user=credentials.login_role,
            password=credentials.password,
            connect_timeout=5,
            sslmode="disable",
            gssencmode="disable",
            options="",  # Do not inherit PGOPTIONS, principal or search_path.
            application_name="stark_t2sql",
            target_session_attrs="any",
        )
        connection.autocommit = False
        return connection
    except driver.Error as exc:
        if connection is not None:
            _discard(connection)
        raise DatabaseExecutionError("Local PostgreSQL connection failed: " + str(exc)) from exc


def _discard(connection: Any) -> None:
    """Never return a failed or dirty connection to another persona."""
    try:
        if not connection.closed:
            connection.rollback()
    except Exception:
        # Cleanup failure cannot make the lease reusable and must not obscure
        # the original SQLSTATE/diagnostic. Closing a fresh lease is mandatory.
        pass
    finally:
        try:
            connection.close()
        except Exception:
            # No pool retains this connection; it is never yielded again.
            pass


def _one(cursor: Any, query: str, parameters: tuple[object, ...] = ()) -> tuple[Any, ...]:
    cursor.execute(query, parameters)
    row = cursor.fetchone()
    if row is None:
        raise ConfigurationError("Required PostgreSQL privilege metadata is unavailable.")
    return row


def _settings(cursor: Any, config: AppConfig, login_role: str, schema: str) -> None:
    """Require effective settings and persistent defaults on the LOGIN itself."""
    config.resource_budgets.require_database_budget_inputs()
    cursor.execute(
        "SELECT name, setting FROM pg_catalog.pg_settings "
        "WHERE name = ANY(%s) ORDER BY name",
        (["default_transaction_read_only", "statement_timeout", "work_mem", "temp_file_limit", "search_path", "row_security"],),
    )
    values = dict(cursor.fetchall())
    required = {"default_transaction_read_only", "statement_timeout", "work_mem", "temp_file_limit", "search_path", "row_security"}
    if set(values) != required:
        raise ConfigurationError("Required database resource settings are unavailable.")
    normalized_path = tuple(part.strip().strip('"') for part in values["search_path"].split(","))
    expected_timeout = int(config.limits.statement_timeout_seconds * 1000)
    if (
        values["default_transaction_read_only"] != "on"
        or values["row_security"] != "on"
        or not 0 < int(values["statement_timeout"]) <= expected_timeout
        or int(values["work_mem"]) != config.resource_budgets.database_work_mem_kib
        or int(values["temp_file_limit"]) != config.resource_budgets.database_temp_file_limit_kib
        or normalized_path != ("pg_catalog", schema, "pg_temp")
    ):
        raise ConfigurationError("Candidate login settings differ from required read-only/resource controls.")
    defaults = _one(cursor, "SELECT rolconfig FROM pg_catalog.pg_roles WHERE rolname = %s", (login_role,))[0] or []
    declared = dict(setting.split("=", 1) for setting in defaults if "=" in setting)
    if not {"default_transaction_read_only", "statement_timeout", "search_path", "work_mem", "temp_file_limit"}.issubset(declared):
        raise ConfigurationError("Read-only and measured resource defaults must be pinned on the login role.")
    if declared["default_transaction_read_only"] != "on":
        raise ConfigurationError("The candidate login lacks a persistent read-only default.")


def _role_flags(cursor: Any, role_name: str, *, login: bool) -> int:
    row = _one(
        cursor,
        "SELECT oid, rolcanlogin, rolinherit, rolsuper, rolbypassrls, rolcreatedb, "
        "rolcreaterole, rolreplication FROM pg_catalog.pg_roles WHERE rolname = %s",
        (role_name,),
    )
    oid, can_login, inherit, *elevated = row
    if can_login != login or (login and inherit) or any(elevated):
        raise ConfigurationError("Candidate identity has an unsafe login, inheritance, or administrative capability.")
    return oid


def _deny_ddl(cursor: Any, role_name: str, role_oid: int, *, owned_scope_function: int | None = None) -> None:
    """Audit effective capabilities, including PUBLIC and ownership shortcuts."""
    unsafe_db = _one(
        cursor,
        "SELECT d.datdba = %s OR pg_catalog.has_database_privilege(%s, d.oid, 'CREATE') "
        "OR pg_catalog.has_database_privilege(%s, d.oid, 'TEMP') "
        "FROM pg_catalog.pg_database AS d WHERE d.datname = pg_catalog.current_database()",
        (role_oid, role_name, role_name),
    )[0]
    unsafe_schema = _one(
        cursor,
        "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_namespace AS n "
        "WHERE n.nspowner = %s OR pg_catalog.has_schema_privilege(%s, n.oid, 'CREATE'))",
        (role_oid, role_name),
    )[0]
    owns_object = _one(
        cursor,
        "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_shdepend AS dependency "
        "WHERE dependency.refclassid = 'pg_catalog.pg_authid'::pg_catalog.regclass "
        "AND dependency.refobjid = %s AND dependency.deptype = 'o' "
        "AND dependency.dbid IN (0, (SELECT dbrow.oid FROM pg_catalog.pg_database AS dbrow "
        "WHERE dbrow.datname = pg_catalog.current_database())) "
        "AND NOT (dependency.classid = 'pg_catalog.pg_proc'::pg_catalog.regclass "
        "AND dependency.objid = COALESCE(%s::oid, 0::oid) AND dependency.dbid <> 0))",
        (role_oid, owned_scope_function),
    )[0]
    if unsafe_db or unsafe_schema or owns_object:
        raise ConfigurationError("Candidate identity owns objects or has database/schema creation privileges.")


def _relation_privileges(cursor: Any, matrix: PolicyMatrix, role_name: str, *, baseline: bool = False, direct_login: bool = False, helper_owner: bool = False) -> None:
    """Compare every live application column with the one authoritative matrix."""
    cursor.execute(
        "SELECT c.oid, n.nspname, c.relname, c.relkind, c.relrowsecurity, c.relforcerowsecurity "
        "FROM pg_catalog.pg_class AS c JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') "
        "AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp_%' "
        "AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') ORDER BY n.nspname, c.relname"
    )
    relations = cursor.fetchall()
    live_tables = {name for _, schema, name, kind, _, _ in relations if schema == matrix.schema and kind in ("r", "p")}
    if live_tables != set(matrix.tables):
        raise ConfigurationError("The application relation inventory differs from the policy matrix.")
    business = None if baseline or direct_login or helper_owner else matrix.role(role_name)
    for oid, schema, name, kind, rls, force_rls in relations:
        is_fixture_table = schema == matrix.schema and name in matrix.tables and kind in ("r", "p")
        if schema == matrix.schema and kind != "S" and not is_fixture_table:
            raise ConfigurationError("An unmanaged application relation is outside the policy matrix.")
        if kind == "S":
            if _one(cursor, "SELECT pg_catalog.has_sequence_privilege(%s, %s, 'USAGE,SELECT,UPDATE')", (role_name, oid))[0]:
                raise ConfigurationError("Candidate identities must not have sequence privileges.")
            continue
        table_select = _one(cursor, "SELECT pg_catalog.has_table_privilege(%s, %s, 'SELECT')", (role_name, oid))[0]
        if _one(cursor, "SELECT pg_catalog.has_table_privilege(%s, %s, 'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')", (role_name, oid))[0]:
            raise ConfigurationError("Candidate identity has a non-SELECT table privilege.")
        cursor.execute("SELECT attname FROM pg_catalog.pg_attribute WHERE attrelid = %s AND attnum > 0 AND NOT attisdropped ORDER BY attnum", (oid,))
        columns = tuple(row[0] for row in cursor.fetchall())
        access = business.tables.get(name) if business is not None and is_fixture_table else None
        permitted = set(columns) if baseline and is_fixture_table else set()
        if helper_owner and is_fixture_table and name == "hr_bp_assignments":
            permitted = {"employee_id", "division_id", "effective_to"}
        if access is not None:
            permitted = set(columns) if access.columns is None else set(access.columns)
            if not permitted.issubset(columns):
                raise ConfigurationError("The matrix references unavailable physical columns.")
        if not permitted and table_select:
            raise ConfigurationError("A table-level SELECT privilege overrides a column restriction.")
        if table_select and permitted != set(columns):
            has_table_level_acl = _one(
                cursor,
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.aclexplode((SELECT relacl FROM pg_catalog.pg_class WHERE oid = %s)) AS acl "
                "JOIN pg_catalog.pg_roles AS r ON r.oid = acl.grantee "
                "WHERE r.rolname = %s AND acl.privilege_type = 'SELECT')",
                (oid, role_name),
            )[0]
            if has_table_level_acl:
                raise ConfigurationError("A table-level SELECT privilege overrides a column restriction.")
        for column in columns:
            observed = _one(cursor, "SELECT pg_catalog.has_column_privilege(%s, %s, %s, 'SELECT')", (role_name, oid, column))[0]
            if observed != (column in permitted):
                raise ConfigurationError("Candidate column SELECT access differs from the matrix.")
            if _one(cursor, "SELECT pg_catalog.has_column_privilege(%s, %s, %s, 'INSERT,UPDATE,REFERENCES')", (role_name, oid, column))[0]:
                raise ConfigurationError("Candidate identity has a non-SELECT column privilege.")
        if not baseline and is_fixture_table and name in matrix.rls_tables and (not rls or not force_rls):
            raise ConfigurationError("Required employee/leave row security is not enabled and forced.")
        # PUBLIC application grants are never a substitute for role grants.
        if is_fixture_table:
            public_acl = _one(
                cursor,
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.aclexplode((SELECT relacl FROM pg_catalog.pg_class WHERE oid = %s)) AS acl WHERE acl.grantee = 0) "
                "OR EXISTS (SELECT 1 FROM pg_catalog.pg_attribute AS a, LATERAL pg_catalog.aclexplode(a.attacl) AS acl WHERE a.attrelid = %s AND acl.grantee = 0)",
                (oid, oid),
            )[0]
            if public_acl:
                raise ConfigurationError("PUBLIC application table or column privileges are forbidden.")


def _function_privileges(cursor: Any, matrix: PolicyMatrix, role_name: str, *, baseline: bool = False, login: bool = False) -> None:
    cursor.execute(
        "SELECT p.oid, n.nspname, p.proname, p.pronargs, p.prosecdef, p.provolatile, p.proconfig, p.proowner, p.prosrc "
        "FROM pg_catalog.pg_proc AS p JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace "
        "WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') ORDER BY n.nspname, p.proname, p.oid"
    )
    for oid, schema, name, nargs, definer, volatility, settings, owner_oid, source in cursor.fetchall():
        executable = _one(cursor, "SELECT pg_catalog.has_function_privilege(%s, %s, 'EXECUTE')", (role_name, oid))[0]
        allowed = not baseline and not login and role_name == "app_hr_bp" and schema == matrix.schema and name == "hr_bp_current_divisions" and nargs == 0
        if executable != allowed:
            raise ConfigurationError("Candidate identity has unexpected application-function execution rights.")
        if allowed:
            owner = _one(cursor, "SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolreplication FROM pg_catalog.pg_roles WHERE oid = %s", (owner_oid,))
            declared = dict(setting.split("=", 1) for setting in (settings or []) if "=" in setting)
            helper_path = tuple(part.strip().strip('"') for part in declared.get("search_path", "").split(","))
            if not definer or volatility != "s" or any(owner[1:]) or helper_path != ("pg_catalog", matrix.schema, "pg_temp"):
                raise ConfigurationError("The HR scope helper lacks its trusted stable definer boundary.")
            if _one(cursor, "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members WHERE member = %s)", (owner_oid,))[0]:
                raise ConfigurationError("The HR scope helper owner must not inherit or assume additional roles.")
            _deny_ddl(cursor, owner[0], owner_oid, owned_scope_function=oid)
            _relation_privileges(cursor, matrix, owner[0], helper_owner=True)
            if _one(cursor, "SELECT pg_catalog.has_function_privilege(%s, 'pg_catalog.set_config(text,text,boolean)', 'EXECUTE')", (owner[0],))[0]:
                raise ConfigurationError("The HR scope helper owner must not acquire principal-setting privileges.")
            from stark_t2sql.policy.rls import scope_function_statements

            # pg_proc.prosrc retains the SQL function body. Match the generator's
            # source rather than accepting a stale/replaced definer SQL body.
            definition = scope_function_statements(matrix, definer_owner=owner[0])[0]
            expected_source = definition.split("$stark_hr_scope$", 2)[1]
            if source.strip() != expected_source.strip():
                raise ConfigurationError("The HR scope helper body differs from the authoritative generator.")
    set_config = _one(cursor, "SELECT pg_catalog.has_function_privilege(%s, 'pg_catalog.set_config(text,text,boolean)', 'EXECUTE')", (role_name,))[0]
    if set_config != (login and not baseline):
        raise ConfigurationError("Principal-setting function privileges differ from the reviewed boundary.")


def _audit(connection: Any, config: AppConfig, matrix: PolicyMatrix, credentials: DatabaseCredentials, business: RolePolicy | None) -> None:
    """No model text reaches this fixed introspection path."""
    connection.readonly = True
    with connection.cursor() as cursor:
        session_user, current_user, database, address, port = _one(cursor, "SELECT session_user, current_user, pg_catalog.current_database(), pg_catalog.host(pg_catalog.inet_server_addr()), pg_catalog.inet_server_port()")
        if session_user != credentials.login_role or current_user != session_user or database != credentials.database:
            raise ConfigurationError("Candidate connection did not authenticate as its declared login/database.")
        if address is None or require_loopback_host(address) != credentials.host or port != credentials.port:
            raise ConfigurationError("Candidate connection destination differs from its explicit loopback endpoint.")
        login_oid = _role_flags(cursor, credentials.login_role, login=True)
        _deny_ddl(cursor, credentials.login_role, login_oid)
        cursor.execute(
            "SELECT role.rolname, membership.admin_option, membership.inherit_option, membership.set_option "
            "FROM pg_catalog.pg_auth_members AS membership JOIN pg_catalog.pg_roles AS role ON role.oid = membership.roleid "
            "WHERE membership.member = %s ORDER BY role.rolname",
            (login_oid,),
        )
        membership = cursor.fetchall()
        expected = [] if business is None else [(business.name, False, False, True)]
        if membership != expected:
            raise ConfigurationError("Candidate login membership widens or differs from its declared business role.")
        _settings(cursor, config, credentials.login_role, matrix.schema)
        _relation_privileges(cursor, matrix, credentials.login_role, baseline=business is None, direct_login=business is not None)
        _function_privileges(cursor, matrix, credentials.login_role, baseline=business is None, login=True)
        if business is not None:
            business_oid = _role_flags(cursor, business.name, login=False)
            _deny_ddl(cursor, business.name, business_oid)
            if _one(cursor, "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_auth_members WHERE member = %s)", (business_oid,))[0]:
                raise ConfigurationError("Business roles must not assume additional roles.")
            _relation_privileges(cursor, matrix, business.name)
            _function_privileges(cursor, matrix, business.name)
    # The executor starts a fresh read-only transaction as login, sets principal,
    # and only then assumes the business role. Introspection leaves no open txn.
    connection.rollback()
    connection.readonly = True


def _require_policy_state(connection: Any, matrix: PolicyMatrix, expected: str) -> None:
    """Reject installed policy/function drift against trusted setup metadata.

    The administrative applier establishes this digest only after executing the
    exact generated plan. A caller must provide that real deployment binding;
    the access matrix digest alone cannot establish the installed RLS predicates.
    This does not assert that row behavior or adversarial cases were measured.
    """
    from stark_t2sql.db.catalog import policy_state_sha256

    if policy_state_sha256(connection, matrix) != expected:
        raise ConfigurationError("Installed RLS/function metadata differs from its trusted setup binding.")
    connection.rollback()
    connection.readonly = True


def _required_digest(value: str | None, *, label: str) -> str:
    if value is None:
        raise MissingDependencyError(label + " is unavailable; trusted setup must establish it first.")
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ConfigurationError(label + " must be an actual lowercase SHA-256 digest.")
    return value


class AdminConnectionSource:
    """Trusted setup/reference/identity capability; never a candidate source.

    The alias must be explicitly supplied separately from business logins. SQL
    provenance remains the caller's responsibility: fixed setup plans and trusted
    reference routines only. Executors accept exact Runtime/Evaluation types.
    """

    def __init__(self, config: AppConfig, alias_name: str) -> None:
        self.config = config
        self.alias = config.database_alias(alias_name)
        if self.alias.login_role in {"stark_payroll_login", "stark_hr_login", "stark_sales_login"}:
            raise ConfigurationError("Trusted administrative work requires a separate explicitly configured alias.")
        self._closed = False

    @contextmanager
    def connection(self, *, readonly: bool = True) -> Iterator[Any]:
        if self._closed or type(readonly) is not bool:
            raise ConfigurationError("Administrative source is closed or has an invalid transaction mode.")
        connection = _open(self.config, self.alias.load_credentials())
        try:
            connection.readonly = readonly
            yield connection
            if not readonly:
                connection.commit()
        finally:
            _discard(connection)

    def close(self) -> None:
        self._closed = True


class RuntimeConnections:
    """Per-request, per-login connections for the four resolved business personas."""

    def __init__(
        self,
        config: AppConfig,
        matrix: PolicyMatrix,
        personas: PersonaRegistry,
        *,
        expected_policy_state_sha256: str | None = None,
    ) -> None:
        if type(personas) is not PersonaRegistry:
            raise ConfigurationError("Runtime connections require fixture-derived predefined personas.")
        self.config, self.matrix, self.personas = config, matrix, personas
        self.expected_policy_state_sha256 = _required_digest(expected_policy_state_sha256, label="Installed business policy-state binding")
        self._closed = False

    def _alias(self, persona: Persona) -> DatabaseConnectionAlias:
        matches = [alias for alias in self.config.database_connections if alias.login_role == persona.login_role]
        if len(matches) != 1:
            raise ConfigurationError("Each runtime login requires exactly one configured role-specific alias.")
        return matches[0]

    @contextmanager
    def connection(self, persona: Persona) -> Iterator[Any]:
        if self._closed:
            raise ConfigurationError("Runtime connection source is closed.")
        resolved = self.personas.resolve(persona)
        role = self.matrix.role(resolved.business_role)
        if resolved.login_role != role.login_role:
            raise ConfigurationError("Persona and policy matrix login roles differ.")
        credentials = self._alias(resolved).load_credentials()
        connection = _open(self.config, credentials)
        try:
            _audit(connection, self.config, self.matrix, credentials, role)
            _require_policy_state(connection, self.matrix, self.expected_policy_state_sha256)
            yield connection
        finally:
            _discard(connection)

    def close(self) -> None:
        self._closed = True


@dataclass(frozen=True, slots=True)
class EvaluationCloneProvenance:
    """Required future trusted setup inputs, corroborated against live catalogs.

    A disposable clone must have a trusted database COMMENT containing a JSON
    object with kind='stark_disposable_evaluation_clone', clone_token,
    source_database, source_database_oid, clone_database_oid, fixture_dump_sha256.
    This module never creates a database, comment, manifest, or token. The marker
    is supplied only by a separately authorized administrative clone/restore
    path. It is trusted setup evidence, not real user authentication.
    """

    source_database: str
    clone_database: str
    clone_token: str
    fixture_dump_sha256: str
    manifest_hash_path: tuple[str, ...]
    policy_state_sha256: str

    def __post_init__(self) -> None:
        if not self.source_database or not self.clone_database or self.source_database == self.clone_database:
            raise ConfigurationError("Evaluation requires a separately named disposable clone database.")
        if re.fullmatch(r"[A-Za-z0-9_-]{16,128}", self.clone_token) is None:
            raise ConfigurationError("A unique trusted clone marker token is required.")
        if re.fullmatch(r"[0-9a-f]{64}", self.fixture_dump_sha256) is None:
            raise ConfigurationError("The actual fixture dump digest is required for evaluation provenance.")
        _required_digest(self.policy_state_sha256, label="Installed evaluation clone policy-state binding")


class EvaluationConnectionSource:
    """Isolated harness capability, independently audited from business runtime.

    persona=None gives the dedicated SELECT-only baseline identity, with no role
    membership and no set_config capability. A persona uses its business login
    on the same disposable clone to preserve the DB boundary during ablations.
    No booleans, candidate credentials, or administrative connections can stand
    in for actual clone provenance and effective least-privilege introspection.
    """

    def __init__(
        self,
        config: AppConfig,
        matrix: PolicyMatrix,
        personas: PersonaRegistry,
        *,
        clone_alias: str,
        provenance: EvaluationCloneProvenance,
        admin_source: AdminConnectionSource,
    ) -> None:
        if not config.isolation.evaluation_enabled or config.isolation.evaluation_connection_alias != clone_alias:
            raise ConfigurationError("The separate local evaluation harness is not explicitly configured.")
        if type(admin_source) is not AdminConnectionSource or type(provenance) is not EvaluationCloneProvenance or type(personas) is not PersonaRegistry:
            raise ConfigurationError("Evaluation requires exact separate trusted provenance and persona capabilities.")
        self.config, self.matrix, self.personas = config, matrix, personas
        self.clone_alias, self.provenance = clone_alias, provenance
        self._admin_source = admin_source
        self._closed = False
        alias = config.database_alias(clone_alias)
        runtime_logins = {role.login_role for role in matrix.roles}
        if alias.login_role in runtime_logins or alias.login_role == admin_source.alias.login_role:
            raise ConfigurationError("The uncontrolled baseline requires a separate non-administrative login identity.")

    def _establish_clone(self) -> DatabaseCredentials:
        provenance = self.provenance
        actual_digest = fixture_digest(self.config.paths, provenance.manifest_hash_path)
        if actual_digest != provenance.fixture_dump_sha256 or actual_digest != self.personas.fixture_dump_sha256:
            raise ConfigurationError("Evaluation provenance and resolved personas refer to different fixture dumps.")
        credentials = self.config.database_alias(self.clone_alias).load_credentials()
        source_credentials = self._admin_source.alias.load_credentials()
        if credentials.database != provenance.clone_database or source_credentials.database != provenance.source_database:
            raise ConfigurationError("Evaluation/source aliases do not match the declared clone provenance.")
        if (credentials.host, credentials.port) != (source_credentials.host, source_credentials.port):
            raise ConfigurationError("Clone provenance requires the same explicit local PostgreSQL instance.")
        for role in self.matrix.roles:
            aliases = [alias for alias in self.config.database_connections if alias.login_role == role.login_role]
            if len(aliases) != 1:
                raise ConfigurationError("Clone isolation requires exactly one declared alias per business login.")
            business_credentials = aliases[0].load_credentials()
            if business_credentials.database != provenance.source_database or (business_credentials.host, business_credentials.port) != (credentials.host, credentials.port):
                raise ConfigurationError("The clone must be separate from every ordinary business database alias.")
        with self._admin_source.connection(readonly=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT oid, datname, pg_catalog.shobj_description(oid, 'pg_database') "
                    "FROM pg_catalog.pg_database WHERE datname = ANY(%s) ORDER BY datname",
                    ([provenance.source_database, provenance.clone_database],),
                )
                databases = {name: (oid, marker) for oid, name, marker in cursor.fetchall()}
        if set(databases) != {provenance.source_database, provenance.clone_database}:
            raise ConfigurationError("The actual source and disposable clone databases are unavailable.")
        source_oid = databases[provenance.source_database][0]
        clone_oid, marker_text = databases[provenance.clone_database]
        if clone_oid == source_oid:
            raise ConfigurationError("Evaluation clone and business database are the same physical database.")
        try:
            marker = json.loads(marker_text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ConfigurationError("A trusted live disposable-clone provenance marker is required.") from exc
        expected = {
            "kind": "stark_disposable_evaluation_clone",
            "clone_token": provenance.clone_token,
            "source_database": provenance.source_database,
            "source_database_oid": source_oid,
            "clone_database_oid": clone_oid,
            "fixture_dump_sha256": actual_digest,
        }
        if marker != expected:
            raise ConfigurationError("The live database marker does not establish the declared disposable fixture clone.")
        return credentials

    @contextmanager
    def connection(self, *, persona: Persona | None = None) -> Iterator[Any]:
        if self._closed:
            raise ConfigurationError("Evaluation connection source is closed.")
        baseline_credentials = self._establish_clone()
        role = None
        credentials = baseline_credentials
        if persona is not None:
            resolved = self.personas.resolve(persona)
            role = self.matrix.role(resolved.business_role)
            aliases = [alias for alias in self.config.database_connections if alias.login_role == resolved.login_role]
            if len(aliases) != 1 or resolved.login_role != role.login_role:
                raise ConfigurationError("The cloned business login differs from the policy persona.")
            original = aliases[0].load_credentials()
            credentials = DatabaseCredentials(original.host, original.port, baseline_credentials.database, original.login_role, original.password)
        connection = _open(self.config, credentials)
        try:
            _audit(connection, self.config, self.matrix, credentials, role)
            _require_policy_state(connection, self.matrix, self.provenance.policy_state_sha256)
            yield connection
        finally:
            _discard(connection)

    def close(self) -> None:
        self._closed = True
