"""Independent, human-reviewed reference and fixed authorization-probe sources.

Generated SQL cannot obtain a reference receipt: actual frozen reference bytes,
case/persona/date/mode, fixture and scope-review bindings are all required.
Business reference computations use the trusted administrative read path with
explicit independently reviewed scope predicates, not the policy's RLS helper.
That helper intentionally trusts business session_user, not an administrator.
UNCONTROLLED references use the existing SELECT-only disposable-clone executor.
No database is opened, query submitted, review created or result stored now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from threading import Event, Timer
from time import monotonic
import traceback
from typing import Callable

from ..contracts import ColumnMetadata, Diagnostic, ExecutionMode, OutcomeStatus, Persona, ResultValue, RowScopeKind
from ..db.catalog import SchemaSnapshot, policy_state_sha256, snapshot_schema
from ..db.connections import AdminConnectionSource, EvaluationConnectionSource
from ..db.executor import EvaluationExecutor
from ..db.persona import fixture_digest
from ..errors import ConfigurationError, MissingDependencyError, StatementTimeoutError
from ..utils.fingerprints import sha256_context
from ..semantic.models import ColumnRef
from .cases import Case, require_distinctive_canary, require_sha256
from .comparator import ResultTable, canonical_cell
from .wallclock import WallClockReview, lint_wallclock


@dataclass(frozen=True, slots=True)
class ReferenceReview:
    """Actual independent human review metadata supplied by the local owner.

    Marker strings describe positions reviewed in the frozen template; values
    inserted there are typed principal/date literals only. No model output,
    question, alias guess or automatically produced approval fills this record.
    All human evidence references must point to actual owner-held records.
    """

    case_id: str
    mode: ExecutionMode
    persona: str
    principal_id: int
    as_of_date: date
    template_sha256: str
    projection: tuple[ColumnMetadata, ...]
    row_scope: RowScopeKind
    fixture_dump_sha256: str
    source_policy_state_sha256: str
    review_reference: str
    scope_review_reference: str
    select_only_reviewed: bool
    principal_marker: str | None = None
    as_of_marker: str | None = None
    data_tables: tuple[str, ...] = ()
    data_columns: tuple[ColumnRef, ...] = ()
    literal_only: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "projection", tuple(self.projection))
        object.__setattr__(self, "data_tables", tuple(self.data_tables))
        object.__setattr__(self, "data_columns", tuple(self.data_columns))
        for value in (self.case_id, self.persona, self.review_reference, self.scope_review_reference):
            if not isinstance(value, str) or not value.strip():
                raise MissingDependencyError("Actual independent reference and entitlement review records are required.")
        if type(self.mode) is not ExecutionMode or type(self.row_scope) is not RowScopeKind or type(self.as_of_date) is not date:
            raise ConfigurationError("Reference review binds an exact typed mode, row scope and date.")
        if type(self.principal_id) is not int or self.principal_id <= 0 or self.select_only_reviewed is not True:
            raise MissingDependencyError("Reference computation needs actual principal and reviewed SELECT-only provenance.")
        for digest in (self.template_sha256, self.fixture_dump_sha256, self.source_policy_state_sha256):
            require_sha256(digest, "Actual reference source binding")
        if not self.projection or any(type(column) is not ColumnMetadata or not column.canonical_identity for column in self.projection):
            raise MissingDependencyError("Independent reference projection needs approved canonical column identities.")
        identities = tuple(column.canonical_identity for column in self.projection)
        if len(set(identities)) != len(identities):
            raise ConfigurationError("Reference projection slots need distinct stable semantic identities.")
        markers = tuple(marker for marker in (self.principal_marker, self.as_of_marker) if marker is not None)
        if any(type(marker) is not str or not marker for marker in markers) or len(set(markers)) != len(markers):
            raise ConfigurationError("Reference literal markers must be explicit distinct reviewed strings.")
        if type(self.literal_only) is not bool or (not self.data_tables and not self.literal_only):
            raise MissingDependencyError("Actual independent data lineage or an explicitly reviewed literal-only reference is required.")
        if self.literal_only and (self.data_tables or self.data_columns):
            raise ConfigurationError("A literal-only reference cannot declare physical data lineage.")
        if any(type(ref) is not ColumnRef or ref.table not in self.data_tables for ref in self.data_columns):
            raise ConfigurationError("Reviewed reference column lineage must belong to its declared data tables.")


@dataclass(frozen=True, slots=True)
class ReferenceResult:
    available: bool
    table: ResultTable | None
    reason: str
    proves_legitimate: bool = False
    truncated: bool = False
    latency_ms: float | None = None
    diagnostics: tuple[Diagnostic, ...] = ()


def _private_error(exc: Exception) -> Diagnostic:
    state = getattr(exc, "pgcode", None)
    return Diagnostic(
        "REFERENCE_OR_PROBE", f"{type(exc).__module__}.{type(exc).__qualname__}: {exc}",
        state if isinstance(state, str) else None,
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )


def _render_reference(sql: str, review: ReferenceReview, persona: Persona, as_of_date: date) -> str:
    if sha256_context(sql) != review.template_sha256:
        raise MissingDependencyError("Frozen independent reference SQL differs from its actual human review binding.")
    substitutions = []
    for marker, literal in (
        (review.principal_marker, str(persona.principal_id)),
        (review.as_of_marker, "DATE '" + as_of_date.isoformat() + "'"),
    ):
        if marker is None:
            continue
        if sql.count(marker) != 1:
            raise ConfigurationError("Each reviewed reference literal slot must occur exactly once.")
        substitutions.append((sql.index(marker), marker, literal))
    position, pieces = 0, []
    for start, marker, literal in sorted(substitutions):
        if start < position:
            raise ConfigurationError("Reviewed reference literal slots overlap.")
        pieces.extend((sql[position:start], literal))
        position = start + len(marker)
    pieces.append(sql[position:])
    return "".join(pieces)


class _ReferenceDeadline:
    """Cancel only this fresh trusted read connection on its bounded deadline."""

    def __init__(self, connection: object, seconds: float) -> None:
        self.connection, self.expired = connection, Event()
        self.timer = Timer(seconds, self._cancel)
        self.timer.daemon = True

    def _cancel(self) -> None:
        self.expired.set()
        try:
            self.connection.cancel()
        except Exception:
            # The source still discards the connection; elapsed state remains
            # explicit and no alternate/admin candidate connection is acquired.
            pass

    def __enter__(self) -> _ReferenceDeadline:
        self.timer.start()
        return self

    def require_time(self) -> None:
        if self.expired.is_set():
            raise StatementTimeoutError("The trusted reference/probe deadline expired.")

    def __exit__(self, *unused: object) -> None:
        self.timer.cancel()
        self.timer.join(timeout=0.1)
        self.require_time()


class ReferenceAuthority:
    """No arbitrary-SQL execution method; only frozen reviewed case references.

    The human reference must independently express the same business persona's
    scope (or all known fixture rows for the isolated baseline). This supplies
    an oracle independent of prompt generation and authorization validation.
    It is not protection from malicious Python running in the same process.
    """

    def __init__(
        self, source: EvaluationConnectionSource, admin_source: AdminConnectionSource,
        *, lookup_review: Callable[[str, ExecutionMode], ReferenceReview | None],
        baseline_executor: EvaluationExecutor,
        wallclock_review: WallClockReview | None = None,
    ) -> None:
        if type(source) is not EvaluationConnectionSource or type(admin_source) is not AdminConnectionSource:
            raise ConfigurationError("References require exact isolated and separate trusted administrative sources.")
        if source._admin_source is not admin_source or not callable(lookup_review) or type(baseline_executor) is not EvaluationExecutor:
            raise ConfigurationError("Reference review and clone capabilities must share the actual trusted source binding.")
        if baseline_executor._source is not source:
            raise ConfigurationError("The baseline reference executor must use the same SELECT-only clone source.")
        self.source, self.admin_source = source, admin_source
        self._lookup, self._baseline_executor = lookup_review, baseline_executor
        self._wallclock_review = wallclock_review

    def evaluate(self, case: Case, mode: ExecutionMode) -> ReferenceResult:
        """Explicit future reference computation; candidate output is never input."""
        started = monotonic()
        try:
            if type(case) is not Case or type(mode) is not ExecutionMode or case.reference_sql is None:
                raise MissingDependencyError("This case has no frozen independent reference SQL.")
            review = self._lookup(case.id, mode)
            if type(review) is not ReferenceReview:
                raise MissingDependencyError("Actual independent reference review is unavailable for this case and mode.")
            persona = self.source.personas.resolve(case.persona)
            role_pol = self.source.matrix.role(persona.business_role)
            if mode is ExecutionMode.UNCONTROLLED:
                allowed_scopes = {RowScopeKind.ALL}
            else:
                emp_scope = role_pol.tables["employees"].row_scope
                table_scopes = {role_pol.tables[t].row_scope for t in review.data_tables if t in role_pol.tables}
                allowed_scopes = {emp_scope} | table_scopes
            if (
                review.case_id != case.id or review.mode is not mode or review.persona != case.persona
                or review.principal_id != persona.principal_id or review.as_of_date != case.as_of_date
                or review.row_scope not in allowed_scopes
            ):
                raise MissingDependencyError("Reference review does not bind this actual persona/date/mode and scope.")
            # These are actual human-reviewed lineage declarations bound to the
            # frozen SQL, not lineage guessed from aliases or returned values.
            # Independent HR scope-control reads belong to scope_review_reference;
            # data lineage includes all business projections/filters/joins.
            role = self.source.matrix.role(persona.business_role)
            permitted_tables = self.source.matrix.tables if mode is ExecutionMode.UNCONTROLLED else role.tables
            if any(table not in permitted_tables for table in review.data_tables):
                raise MissingDependencyError("Reference data lineage exceeds the nominal persona/mode's table entitlements.")
            digest = fixture_digest(self.source.config.paths, self.source.provenance.manifest_hash_path)
            if digest != review.fixture_dump_sha256 or digest != self.source.personas.fixture_dump_sha256:
                raise MissingDependencyError("Independent reference and clone do not share the authoritative actual fixture dump.")
            rendered = _render_reference(case.reference_sql, review, persona, case.as_of_date)
            clock = lint_wallclock(rendered, review=self._wallclock_review)
            if not clock.available or clock.uses_wallclock:
                raise MissingDependencyError("Independent reference requires actual guarded as-of lint without wall-clock constructs.")
            self.source.config.resource_budgets.require_database_budget_inputs()
            if mode is ExecutionMode.UNCONTROLLED:
                # The existing mandatory safety gate and least-privilege clone
                # enforce the baseline. A reference has no admin shortcut here.
                result = self._baseline_executor.execute(persona, rendered, mode=mode)
                if result.status is not OutcomeStatus.ANSWERED or result.executed_sql is None or result.truncated:
                    return ReferenceResult(False, None, "Isolated reference is unavailable or incomplete.", truncated=result.truncated, diagnostics=result.diagnostics)
                actual_columns, rows, executed_sql = result.columns, result.rows, result.executed_sql
            else:
                # Audit the actual clone capability before trusted source reads.
                with self.source.connection(persona=persona):
                    pass
                with self.admin_source.connection(readonly=True) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT current_database(), rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = session_user")
                        database, is_super, bypasses = cursor.fetchone()
                        if database != self.source.provenance.source_database or not (is_super or bypasses):
                            raise MissingDependencyError("Trusted reference path must establish complete FORCE-RLS fixture visibility.")
                    if policy_state_sha256(connection, self.source.matrix) != review.source_policy_state_sha256:
                        raise MissingDependencyError("Trusted reference source policy changed from its actual review binding.")
                    actual_schema = snapshot_schema(connection, self.source.matrix.schema)
                    for ref in review.data_columns:
                        allowed_columns = self.source.matrix.permitted_columns(persona.business_role, ref.table, actual_schema.columns_by_table[ref.table])
                        if ref.column not in allowed_columns:
                            raise MissingDependencyError("Independent reference data lineage exceeds the role's actual matrix column entitlements.")
                    budgets, limits = self.source.config.resource_budgets, self.source.config.limits
                    with _ReferenceDeadline(connection, limits.statement_timeout_seconds) as deadline:
                        with connection.cursor() as cursor:
                            # Fixed trusted setup, never derived from a question.
                            for setting, value in (
                                ("statement_timeout", str(int(limits.statement_timeout_seconds * 1000))),
                                ("work_mem", str(budgets.database_work_mem_kib) + "kB"),
                                ("temp_file_limit", str(budgets.database_temp_file_limit_kib) + "kB"),
                            ):
                                cursor.execute("SELECT pg_catalog.set_config(%s, %s, true)", (setting, value))
                            deadline.require_time()
                            cursor.execute(rendered)
                            if cursor.description is None:
                                raise ConfigurationError("Reviewed independent SELECT produced no projection.")
                            actual_columns = tuple(ColumnMetadata(column.name) for column in cursor.description)
                            fetched = cursor.fetchmany(limits.output_row_cap + 1)
                            if len(fetched) > limits.output_row_cap:
                                return ReferenceResult(False, None, "Independent reference exceeds the complete-comparison row cap.", truncated=True)
                            rows, executed_sql = tuple(tuple(row) for row in fetched), rendered
                            deadline.require_time()
            if tuple(column.name for column in actual_columns) != tuple(column.name for column in review.projection):
                raise MissingDependencyError("Actual independent reference projection differs from its reviewed canonical slots.")
            table = ResultTable(review.projection, rows, sha256_context(executed_sql))
            return ReferenceResult(True, table, "Independent reviewed persona/mode reference available.", True, False, (monotonic() - started) * 1000.0)
        except Exception as exc:
            return ReferenceResult(False, None, "Independent reference dependency or computation is unavailable.", latency_ms=(monotonic() - started) * 1000.0, diagnostics=(_private_error(exc),))


@dataclass(frozen=True, slots=True)
class AuthorizationObservation:
    allowed: bool | None
    sqlstate: str | None
    expected_access: bool
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class ScopedCountObservation:
    count: int | None
    diagnostics: tuple[Diagnostic, ...] = ()


class AuthorizationObserver:
    """Fixed least-privilege read probes, not an arbitrary candidate SQL lane.

    LIMIT 0 probes only the finite actual schema's table/column permissions.
    Scoped counts read only the two source-defined RLS relations. No model,
    question, caller SQL, function name, schema name or admin connection is
    accepted. Unlike generated candidates these harmless source-controlled
    probes intentionally reach DB grants even for a matrix-denied column.
    """

    def __init__(self, source: EvaluationConnectionSource, snapshot: SchemaSnapshot) -> None:
        if type(source) is not EvaluationConnectionSource or type(snapshot) is not SchemaSnapshot or snapshot.schema != source.matrix.schema:
            raise ConfigurationError("Authorization observations require the exact isolated source and actual schema snapshot.")
        self.source, self.snapshot = source, snapshot

    def _read(self, persona: Persona, query: object, *, count: bool = False) -> int | None:
        from psycopg2 import sql

        limits = self.source.config.limits
        self.source.config.resource_budgets.require_database_budget_inputs()
        with self.source.connection(persona=persona) as connection:
            with _ReferenceDeadline(connection, limits.statement_timeout_seconds) as deadline:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_catalog.set_config('app.principal_id', %s::text, true)", (str(persona.principal_id),))
                    cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(persona.business_role)))
                    deadline.require_time()
                    cursor.execute(query)
                    value = cursor.fetchone()[0] if count else None
                    deadline.require_time()
                    if count and type(value) is not int:
                        raise ConfigurationError("The source-defined scoped COUNT did not return an integer.")
                    return value

    def observe(self, persona: Persona | str, *, table: str, column: str | None) -> AuthorizationObservation:
        selected = self.source.personas.resolve(persona)
        actual = self.snapshot.table(table)
        if column is not None and column not in {item.name for item in actual.columns}:
            raise ConfigurationError("An authorization probe must name an actual finite schema column.")
        role = self.source.matrix.role(selected.business_role)
        allowed = self.source.matrix.permitted_columns(role.name, table, self.snapshot.columns_by_table[table]) if table in role.tables else ()
        expected = (len(allowed) == len(actual.columns)) if column is None else column in allowed
        try:
            from psycopg2 import sql

            projection = sql.SQL("*") if column is None else sql.Identifier(column)
            query = sql.SQL("SELECT {} FROM {}.{} LIMIT 0").format(projection, sql.Identifier(self.snapshot.schema), sql.Identifier(table))
            self._read(selected, query)
            return AuthorizationObservation(True, None, expected)
        except Exception as exc:
            state = getattr(exc, "pgcode", None)
            return AuthorizationObservation(False if state == "42501" else None, state if isinstance(state, str) else None, expected, (_private_error(exc),))

    def scoped_count(self, persona: Persona | str, *, table: str = "employees") -> ScopedCountObservation:
        if table not in {"employees", "leave_balances"}:
            raise ConfigurationError("Scoped observations are limited to the two source-defined RLS relations.")
        selected = self.source.personas.resolve(persona)
        self.snapshot.table(table)
        try:
            from psycopg2 import sql

            query = sql.SQL("SELECT COUNT(*) FROM {}.{}").format(sql.Identifier(self.snapshot.schema), sql.Identifier(table))
            return ScopedCountObservation(self._read(selected, query, count=True))
        except Exception as exc:
            return ScopedCountObservation(None, (_private_error(exc),))


@dataclass(frozen=True, slots=True)
class CanarySelection:
    """Actual fixture selectors, not planted forbidden values or guessed IDs."""

    case_id: str
    persona: str
    employee_ids: tuple[int, ...]
    fields: tuple[str, ...]
    fixture_dump_sha256: str
    selector_review_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "employee_ids", tuple(self.employee_ids))
        object.__setattr__(self, "fields", tuple(self.fields))
        require_sha256(self.fixture_dump_sha256, "Actual canary-selector fixture")
        if not self.employee_ids or len(self.employee_ids) > 64 or len(set(self.employee_ids)) != len(self.employee_ids) or any(type(value) is not int or value <= 0 for value in self.employee_ids):
            raise ConfigurationError("Canaries require a bounded set of actual fixture-selected employee IDs.")
        if not self.fields or not set(self.fields) <= {"email", "employee_number", "base_salary"}:
            raise ConfigurationError("Canary reads are limited to the three FR-9 distinctive source fields.")
        if any(type(value) is not str or not value.strip() for value in (self.case_id, self.persona, self.selector_review_reference)):
            raise MissingDependencyError("Actual case/persona and selector review provenance are required.")


@dataclass(frozen=True, slots=True)
class CanaryResult:
    available: bool
    fixture_dump_sha256: str | None
    reason: str
    values: tuple[ResultValue, ...] = field(default=(), repr=False)
    diagnostics: tuple[Diagnostic, ...] = ()


class FixtureCanaryProvider:
    """Compute distinctive canaries from actual data only, in a trusted read lane.

    Owner selectors name actual employees; allowed cells are rejected as
    canaries. Row visibility is observed through the business clone, while the
    frozen synthetic source supplies forbidden text/salary values. Values are
    kept private in memory and never inserted into model context or records.
    No arbitrary SQL/field/schema/function interface or data-generation path.
    """

    def __init__(
        self, source: EvaluationConnectionSource, snapshot: SchemaSnapshot,
        *, lookup_selection: Callable[[str], CanarySelection | None],
    ) -> None:
        if type(source) is not EvaluationConnectionSource or type(snapshot) is not SchemaSnapshot or not callable(lookup_selection):
            raise ConfigurationError("Canaries require actual clone/schema and owner selector inputs.")
        self.source, self.snapshot, self._lookup = source, snapshot, lookup_selection
        self._observer = AuthorizationObserver(source, snapshot)

    def for_case(self, case: Case) -> CanaryResult:
        try:
            from psycopg2 import sql

            selection = self._lookup(case.id)
            if type(selection) is not CanarySelection or selection.case_id != case.id or selection.persona != case.persona:
                raise MissingDependencyError("Actual canary selectors are unavailable for this case and persona.")
            persona = self.source.personas.resolve(case.persona)
            digest = fixture_digest(self.source.config.paths, self.source.provenance.manifest_hash_path)
            if digest != selection.fixture_dump_sha256 or digest != self.source.personas.fixture_dump_sha256:
                raise MissingDependencyError("Canary selector and actual source/clone fixture bindings differ.")
            role = self.source.matrix.role(persona.business_role)
            visibility: dict[int, bool] = {}
            for employee_id in selection.employee_ids:
                probe = sql.SQL("SELECT COUNT(*) FROM {}.employees WHERE employee_id = {}").format(
                    sql.Identifier(self.snapshot.schema), sql.Literal(employee_id),
                )
                visibility[employee_id] = self._observer._read(persona, probe, count=True) != 0
            values = []
            self.source.config.resource_budgets.require_database_budget_inputs()
            with self.source._admin_source.connection(readonly=True) as connection:
                with _ReferenceDeadline(connection, self.source.config.limits.statement_timeout_seconds):
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = session_user")
                        flags = cursor.fetchone()
                        if flags is None or not any(flags):
                            raise MissingDependencyError("Trusted canary read must establish complete FORCE-RLS source visibility.")
                        cursor.execute(sql.SQL("SELECT employee_id FROM {}.employees WHERE employee_id = ANY(%s)").format(sql.Identifier(self.snapshot.schema)), (list(selection.employee_ids),))
                        found = {row[0] for row in cursor.fetchall()}
                        if found != set(selection.employee_ids):
                            raise MissingDependencyError("Canary selectors name employees absent from the actual fixture.")
                        for field_name in selection.fields:
                            table = "employee_compensation" if field_name == "base_salary" else "employees"
                            allowed = self.source.matrix.permitted_columns(role.name, table, self.snapshot.columns_by_table[table])
                            # A field granted on visible rows is not forbidden.
                            if field_name in allowed and any(visibility.values()):
                                raise ConfigurationError("A selector includes a cell permitted to this persona; it cannot serve as a forbidden canary.")
                            order_clause = "ORDER BY employee_id, effective_date DESC, compensation_id ASC" if table == "employee_compensation" else "ORDER BY employee_id"
                            query = sql.SQL(f"SELECT {{}} FROM {{}}.{{}} WHERE employee_id = ANY(%s) {order_clause}").format(
                                sql.Identifier(field_name), sql.Identifier(self.snapshot.schema), sql.Identifier(table),
                            )
                            cursor.execute(query, (list(selection.employee_ids),))
                            rows = cursor.fetchmany(self.source.config.limits.output_row_cap + 1)
                            if len(rows) > self.source.config.limits.output_row_cap:
                                raise MissingDependencyError("Canary read was incomplete at the configured row cap.")
                            for row in rows:
                                value = row[0]
                                require_distinctive_canary(value)
                                values.append(value)
            unique = {}
            for value in values:
                unique.setdefault(canonical_cell(value), value)
            if not unique:
                raise MissingDependencyError("No actual distinctive forbidden values were available from the reviewed selector.")
            return CanaryResult(True, digest, "Actual forbidden fixture values computed in the trusted lane.", tuple(unique.values()))
        except Exception as exc:
            return CanaryResult(False, None, "Actual canary inputs/computation are unavailable.", diagnostics=(_private_error(exc),))
