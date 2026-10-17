"""Explicit future administrative application of compiler-produced policy text.

Nothing is applied on import. Fixture restore and measured settings are required
inputs; acknowledgments do not attest that database rows match a fixture dump.
Administrative connections are never passed to the model query executors.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from ..errors import ConfigurationError
from ..policy.compiler import CompiledPolicy, compile_policy
from ..policy.loader import PolicyMatrix, load_policy
from ..utils.fingerprints import sha256_file
from .catalog import policy_state_sha256, snapshot_schema
from .connections import AdminConnectionSource
from .persona import fixture_digest


@dataclass(frozen=True, slots=True)
class PolicyApplyRequest:
    """A trusted administrator's explicit scope and restore-order declaration."""

    expected_database: str
    fixture_hash_path: tuple[str, ...]
    expected_fixture_dump_sha256: str
    fixture_restore_completed: bool = False
    dedicated_fixture_database: bool = False


@dataclass(frozen=True, slots=True)
class InstallationBinding:
    """Future setup output, passed through trusted local runtime configuration.

    No instance or artifact is created during this source-authoring assignment.
    This binds metadata provenance; it is not an authorization-test result.
    """

    matrix_sha256: str
    database_name: str
    policy_state_sha256: str


def _require_evaluation_clone(cursor, request: PolicyApplyRequest) -> None:
    """Baseline SELECT policies may be installed only on a marked live clone.

    The marker is provisioned independently, not inferred from a database name
    or the dedicated_fixture_database acknowledgment. Match the existing
    EvaluationConnectionSource marker format and actual same-instance OIDs.
    """
    cursor.execute(
        "SELECT oid, datname, pg_catalog.shobj_description(oid, 'pg_database') "
        "FROM pg_catalog.pg_database WHERE datname = pg_catalog.current_database()"
    )
    row = cursor.fetchone()
    if row is None:
        raise ConfigurationError("Evaluation policy setup requires actual clone metadata.")
    clone_oid, clone_name, marker_text = row
    try:
        marker = json.loads(marker_text)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("Evaluation baseline policy setup requires a trusted clone marker.") from exc
    if (
        not isinstance(marker, dict)
        or set(marker) != {"kind", "clone_token", "source_database", "source_database_oid",
                           "clone_database_oid", "fixture_dump_sha256"}
        or marker["kind"] != "stark_disposable_evaluation_clone"
        or type(marker["clone_token"]) is not str
        or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", marker["clone_token"]) is None
        or type(marker["source_database"]) is not str
        or not marker["source_database"]
        or marker["source_database"] == clone_name
        or clone_name != request.expected_database
        or type(marker["source_database_oid"]) is not int
        or type(marker["clone_database_oid"]) is not int
        or marker["clone_database_oid"] != clone_oid
        or marker["fixture_dump_sha256"] != request.expected_fixture_dump_sha256
    ):
        raise ConfigurationError("Evaluation baseline policy setup has inconsistent clone provenance.")
    cursor.execute("SELECT oid FROM pg_catalog.pg_database WHERE datname = %s", (marker["source_database"],))
    source = cursor.fetchone()
    if source is None or source[0] != marker["source_database_oid"] or source[0] == clone_oid:
        raise ConfigurationError("Evaluation baseline requires a physically distinct recorded source database.")


def policy_apply(
    plan: CompiledPolicy,
    administrator: AdminConnectionSource,
    matrix: PolicyMatrix,
    *,
    request: PolicyApplyRequest,
) -> InstallationBinding:
    """Apply an exact, freshly reproduced plan later in one administrative transaction.

    The generator hardens a built-in function's PUBLIC permission, so applying
    before restore or to an unrelated database is deliberately refused. Baseline
    plans additionally require the independently provisioned live clone marker;
    production plans must use baseline_eval_login=None.
    SQL text supplied by callers is never a substitute for compiler output.
    """
    if type(administrator) is not AdminConnectionSource:
        raise ConfigurationError("Policy setup requires the dedicated administrative source type.")
    if request.fixture_restore_completed is not True or request.dedicated_fixture_database is not True:
        raise ConfigurationError("Policy application requires explicit post-restore dedicated-database scope.")
    if not request.expected_database or not request.fixture_hash_path:
        raise ConfigurationError("Database identity and actual manifest hash location are required.")
    config = administrator.config
    current_matrix = load_policy(config.paths.policy_matrix)
    if current_matrix.sha256 != matrix.sha256 or plan.matrix_sha256 != matrix.sha256:
        raise ConfigurationError("Policy source changed or compiled-plan provenance differs.")
    actual_dump_digest = fixture_digest(config.paths, request.fixture_hash_path)
    if actual_dump_digest != request.expected_fixture_dump_sha256:
        raise ConfigurationError("Required fixture dump and manifest provenance differ.")
    budgets = config.resource_budgets.require_database_budget_inputs()
    if (
        plan.settings.work_mem_kib != budgets.database_work_mem_kib
        or plan.settings.temp_file_limit_kib != budgets.database_temp_file_limit_kib
        or plan.settings.measurement_sha256 != sha256_file(budgets.measurement_source)
        or plan.settings.statement_timeout_ms != max(1, int(config.limits.statement_timeout_seconds * 1000))
    ):
        raise ConfigurationError("Compiled login settings differ from supplied measured configuration.")
    with administrator.connection(readonly=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.current_database(), current_user, session_user")
            database_name, current_role, login_role = cursor.fetchone()
            managed = {role.name for role in matrix.roles} | {role.login_role for role in matrix.roles}
            managed.add(plan.settings.definer_owner)
            if plan.settings.baseline_eval_login is not None:
                managed.add(plan.settings.baseline_eval_login)
            if database_name != request.expected_database or current_role in managed or login_role in managed:
                raise ConfigurationError("Administrative policy application has the wrong database or identity.")
            if current_role != login_role:
                raise ConfigurationError("Policy application must start as its explicit administrative login.")
            if plan.settings.baseline_eval_login is not None:
                _require_evaluation_clone(cursor, request)
            snapshot = snapshot_schema(connection, schema=matrix.schema)
            reproduced = compile_policy(current_matrix, snapshot.columns_by_table, plan.settings)
            if plan.schema != reproduced.schema or plan.statements != reproduced.statements:
                raise ConfigurationError("Policy plan is stale or was not produced by the authoritative compiler.")
            for statement in reproduced.statements:
                cursor.execute(statement)
            binding = InstallationBinding(matrix.sha256, database_name, policy_state_sha256(connection, matrix))
        # The administrative source owns commit/rollback and closes the session.
    return binding
