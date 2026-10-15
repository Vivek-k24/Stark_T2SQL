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

from dataclasses import asdict, dataclass, field
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
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
from ..policy.loader import PolicyMatrix, require_identifier
from ..security.validator import HarnessSafetyReviewer
from ..utils.fingerprints import sha256_context
from ..semantic.models import ColumnRef
from .cases import Case, require_distinctive_canary, require_sha256
from .comparator import ResultTable, canonical_cell
from .wallclock import WallClockReview, lint_wallclock


_RELATION_PARSER_VERSION = "30.22.0"


def _relation_tree(sql: str, matrix: PolicyMatrix):
    """Bound metadata inspection, not execution or parser approval.

    CTE/derived sources are resolved by the inspected parser's lexical scopes.
    Unknown relations, qualifications and duplicate source aliases are errors.
    This does not replace the separately reviewed execution safety gate.
    """
    try:
        import sqlglot
        from sqlglot import exp
        from sqlglot.optimizer.normalize_identifiers import normalize_identifiers
        from sqlglot.optimizer.scope import Scope, traverse_scope

        if sqlglot.__version__ != _RELATION_PARSER_VERSION:
            raise ValueError("Relation metadata requires SQLGlot 30.22.0.")
        if type(sql) is not str or not sql.strip() or len(sql.encode("utf-8")) > 131_072:
            raise ValueError("Missing or oversized relation SQL.")
        parsed = sqlglot.parse(sql, read="postgres", error_level=sqlglot.errors.ErrorLevel.RAISE)
        if type(parsed) is not list or len(parsed) != 1 or type(parsed[0]) not in {exp.Select, exp.Union, exp.Intersect, exp.Except}:
            raise ValueError("Relation metadata needs one SELECT-family statement.")
        tree = normalize_identifiers(parsed[0], dialect="postgres")
        nodes = tuple(tree.walk())
        if len(nodes) > 10_000:
            raise ValueError("Relation metadata exceeds the AST limit.")
        if any(isinstance(node, (exp.DML, exp.DDL, exp.Command, exp.Into, exp.Lock)) for node in nodes):
            raise ValueError("Executable commands are not relation metadata.")
        if any(isinstance(node, exp.With) and node.args.get("recursive") for node in nodes):
            raise ValueError("Recursive relation scopes are not reviewed.")
        scopes = traverse_scope(tree)
        if not scopes:
            raise ValueError("No bound query scope is available.")
        physical, accounted = set(), set()
        for scope in scopes:
            for node, source in scope.selected_sources.values():
                if isinstance(node, exp.Table):
                    accounted.add(id(node))
                if type(source) is exp.Table:
                    if type(source.this) is not exp.Identifier or source.catalog or source.db not in {"", matrix.schema}:
                        raise ValueError("Unreviewed physical relation identity.")
                    if source.name not in matrix.tables:
                        raise ValueError("Unknown physical fixture relation.")
                    physical.add(source.name)
                    accounted.add(id(source))
                elif not isinstance(source, Scope):
                    raise ValueError("Unbound or table-function relation scope.")
            if scope.columns and not scope.selected_sources and scope.parent is None:
                raise ValueError("Unbound root column references.")
        if any(id(node) not in accounted for node in nodes if isinstance(node, exp.Table)):
            raise ValueError("A relation was not resolved by a lexical source scope.")
        return tree, tuple(sorted(physical))
    except Exception as exc:
        raise MissingDependencyError("Physical relation scope is unavailable or ambiguous.") from exc


def physical_reference_tables(sql: str, matrix: PolicyMatrix) -> tuple[str, ...]:
    return _relation_tree(sql, matrix)[1]


def reference_row_scope(tables: tuple[str, ...], matrix: PolicyMatrix, persona: Persona, mode: ExecutionMode) -> RowScopeKind:
    """Reduce known physical table scopes without an employees default.

    VIA_EMPLOYEES plus its actual employee scope is one known policy chain.
    Other conflicting restricted scopes have no truthful single enum value.
    A verified relation-free SELECT has no row-level restriction to attribute.
    """
    if type(mode) is not ExecutionMode or any(table not in matrix.tables for table in tables):
        raise MissingDependencyError("Unknown table or execution scope.")
    if mode is ExecutionMode.UNCONTROLLED:
        return RowScopeKind.ALL
    role = matrix.role(persona.business_role)
    if any(table not in role.tables for table in tables):
        raise MissingDependencyError("A physical reference table is outside persona entitlements.")
    if any(table not in matrix.rls_tables and role.tables[table].row_scope is not RowScopeKind.ALL for table in tables):
        raise MissingDependencyError("A non-RLS table declares an unverified restricted scope.")
    scopes = {role.tables[table].row_scope for table in tables} - {RowScopeKind.ALL}
    if not scopes:
        return RowScopeKind.ALL
    if len(scopes) == 1:
        return next(iter(scopes))
    if (
        set(tables) & {"employees", "leave_balances"} == {"employees", "leave_balances"}
        and role.tables["leave_balances"].row_scope is RowScopeKind.VIA_EMPLOYEES
        and scopes == {RowScopeKind.VIA_EMPLOYEES, role.tables["employees"].row_scope}
        and role.tables["employees"].row_scope in {RowScopeKind.ASSIGNED_DIVISIONS, RowScopeKind.DIRECT_REPORTS}
    ):
        return RowScopeKind.VIA_EMPLOYEES
    raise MissingDependencyError("Referenced tables have conflicting row scopes.")


def _reference_columns(sql: str, matrix: PolicyMatrix, snapshot: SchemaSnapshot) -> frozenset[ColumnRef]:
    """Resolve physical column reads, including stars, filters and join keys.

    Unbound/ambiguous columns fail rather than borrowing identity from values.
    Metadata analysis rewrites a copy only; its SQL is never executed.
    """
    try:
        from sqlglot import exp
        from sqlglot.optimizer.qualify import qualify
        from sqlglot.optimizer.scope import Scope, traverse_scope

        tree, _ = _relation_tree(sql, matrix)
        schema = {matrix.schema: {table.name: {column.name: column.sql_type for column in table.columns} for table in snapshot.tables}}
        qualified = qualify(tree, dialect="postgres", db=matrix.schema, schema=schema, allow_partial_qualification=False)
        result = set()
        for scope in traverse_scope(qualified):
            for column in scope.columns:
                current = scope
                while current is not None and column.table not in current.sources:
                    current = current.parent
                if current is None:
                    raise ValueError("Unbound physical column.")
                source = current.sources[column.table]
                if type(source) is exp.Table:
                    if column.name not in snapshot.columns_by_table[source.name]:
                        raise ValueError("Unknown physical column.")
                    result.add(ColumnRef(source.name, column.name))
                elif not isinstance(source, Scope):
                    raise ValueError("Column source is not a reviewed relation.")
        return frozenset(result)
    except Exception as exc:
        raise MissingDependencyError("Reference physical column lineage is unavailable or ambiguous.") from exc


def _require_reference_lineage(sql: str, review: ReferenceReview, matrix: PolicyMatrix, snapshot: SchemaSnapshot, persona: Persona) -> None:
    if set(physical_reference_tables(sql, matrix)) != set(review.data_tables):
        raise MissingDependencyError("Actual reference relations differ from reviewed data lineage.")
    actual = _reference_columns(sql, matrix, snapshot)
    if actual != frozenset(review.data_columns):
        raise MissingDependencyError("Actual reference column reads differ from reviewed lineage.")
    for ref in actual:
        allowed = matrix.permitted_columns(persona.business_role, ref.table, snapshot.columns_by_table[ref.table])
        if ref.column not in allowed:
            raise MissingDependencyError("Independent reference data lineage exceeds the role's actual matrix column entitlements.")


@dataclass(frozen=True, slots=True)
class ScopeReviewStore:
    """Owner-held files pinned by a SEPARATELY approved trusted digest set.

    No digest is inferred from an evidence file, model output, or review string.
    The owner must approve these bytes out of band after independent predicate
    review. A record states analysis; its hash pin supplies the trust binding.
    This is not a signature verifier or proof that a human review occurred.
    No records, owner approval, or default production store ship with R06.
    """

    root: Path
    approved_sha256: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).resolve())
        if type(self.approved_sha256) is not frozenset or not self.approved_sha256:
            raise MissingDependencyError("Separately owner-approved scope record hashes are required.")
        for digest in self.approved_sha256:
            require_sha256(digest, "Owner-approved scope record")

    def require(self, review: ReferenceReview, matrix: PolicyMatrix) -> None:
        try:
            relative = Path(review.scope_review_reference)
            path = (self.root / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError("Scope record must be an existing file within its trusted root.")
            with path.open("rb") as source:
                payload = source.read(1_048_577)
            if len(payload) > 1_048_576 or sha256(payload).hexdigest() not in self.approved_sha256:
                raise ValueError("Scope evidence bytes lack separate owner approval.")

            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate scope evidence keys.")
                    result[key] = value
                return result

            record = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_pairs)
            if type(record) is not dict or set(record) != {"kind", "review_binding_sha256", "matrix_sha256", "reviewer", "scope_analysis"}:
                raise ValueError("Unknown scope evidence format.")
            if record["kind"] != "OWNER_APPROVED_REFERENCE_SCOPE_V1":
                raise ValueError("Test-only or unknown evidence cannot authorize references.")
            if record["review_binding_sha256"] != review.binding_sha256 or record["matrix_sha256"] != matrix.sha256:
                raise ValueError("Scope evidence belongs to different reference/policy inputs.")
            if any(type(record[key]) is not str or not record[key].strip() for key in ("reviewer", "scope_analysis")):
                raise ValueError("Independent reviewer and predicate analysis are unavailable.")
        except Exception as exc:
            raise MissingDependencyError("Genuine owner-approved reference scope evidence is unavailable.") from exc


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
        if not self.projection or any(type(column) is not ColumnMetadata or type(column.canonical_identity) is not str
                                      or not column.canonical_identity.strip() for column in self.projection):
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
        if len(set(self.data_tables)) != len(self.data_tables) or len(set(self.data_columns)) != len(self.data_columns):
            raise ConfigurationError("Reference lineage must contain unique tables and columns.")
        for table in self.data_tables:
            require_identifier(table, label="reference table")
        if any(type(ref) is not ColumnRef or ref.table not in self.data_tables for ref in self.data_columns):
            raise ConfigurationError("Reviewed reference column lineage must belong to its declared data tables.")

    @property
    def binding_sha256(self) -> str:
        """Bind every immutable review field, including principal/date/lineage."""
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), default=lambda value: value.isoformat())
        return sha256(payload.encode("utf-8")).hexdigest()


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
        scope_reviews: ScopeReviewStore | None = None,
    ) -> None:
        if type(source) is not EvaluationConnectionSource or type(admin_source) is not AdminConnectionSource:
            raise ConfigurationError("References require exact isolated and separate trusted administrative sources.")
        if source._admin_source is not admin_source or not callable(lookup_review) or type(baseline_executor) is not EvaluationExecutor:
            raise ConfigurationError("Reference review and clone capabilities must share the actual trusted source binding.")
        if baseline_executor._source is not source:
            raise ConfigurationError("The baseline reference executor must use the same SELECT-only clone source.")
        if scope_reviews is not None and type(scope_reviews) is not ScopeReviewStore:
            raise ConfigurationError("Scope review evidence requires a trusted hash-pinned local store.")
        self.source, self.admin_source = source, admin_source
        self._lookup, self._baseline_executor = lookup_review, baseline_executor
        self._wallclock_review = wallclock_review
        self._scope_reviews = scope_reviews

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
            if (
                review.case_id != case.id or review.mode is not mode or review.persona != case.persona
                or review.principal_id != persona.principal_id or review.as_of_date != case.as_of_date
            ):
                raise MissingDependencyError("Reference review does not bind this actual persona/date/mode and scope.")
            role = self.source.matrix.role(persona.business_role)
            permitted_tables = self.source.matrix.tables if mode is ExecutionMode.UNCONTROLLED else role.tables
            if any(table not in permitted_tables for table in review.data_tables):
                raise MissingDependencyError("Reference data lineage exceeds the nominal persona/mode's table entitlements.")
            rendered = _render_reference(case.reference_sql, review, persona, case.as_of_date)
            physical = physical_reference_tables(rendered, self.source.matrix)
            if set(physical) != set(review.data_tables) or bool(physical) == review.literal_only:
                raise MissingDependencyError("Actual reference relations differ from reviewed data lineage.")
            expected_scope = reference_row_scope(physical, self.source.matrix, persona, mode)
            if review.row_scope is not expected_scope:
                raise MissingDependencyError("Reference row scope differs from its actual physical tables.")
            restricted = mode is not ExecutionMode.UNCONTROLLED and any(
                table in self.source.matrix.rls_tables and role.tables[table].row_scope is not RowScopeKind.ALL
                for table in physical
            )
            if restricted and review.principal_marker != "{{principal}}":
                raise MissingDependencyError("Restricted reference SQL requires its exact principal literal slot.")
            if mode is not ExecutionMode.UNCONTROLLED:
                store = getattr(self, "_scope_reviews", None)
                if type(store) is not ScopeReviewStore:
                    raise MissingDependencyError("Owner-approved scope evidence files and separately approved hashes are unavailable.")
                store.require(review, self.source.matrix)
            digest = fixture_digest(self.source.config.paths, self.source.provenance.manifest_hash_path)
            if digest != review.fixture_dump_sha256 or digest != self.source.personas.fixture_dump_sha256:
                raise MissingDependencyError("Independent reference and clone do not share the authoritative actual fixture dump.")
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
                reviewer = self._baseline_executor._reviewer
                if type(reviewer) is not HarnessSafetyReviewer:
                    raise MissingDependencyError("The independently reviewed reference safety gate is unavailable.")
                safety = reviewer.review_candidate(
                    rendered, persona=persona, mode=mode, policy_fingerprint=self.source.matrix.sha256,
                    clone_token=self.source.provenance.clone_token, fixture_dump_fingerprint=digest,
                )
                rendered = safety.regenerated_sql
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
                    _require_reference_lineage(rendered, review, self.source.matrix, actual_schema, persona)
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
        if not self.fields or len(set(self.fields)) != len(self.fields) or not set(self.fields) <= {"email", "employee_number", "base_salary"}:
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

            if type(case) is not Case:
                raise MissingDependencyError("Canary computation requires an exact bound case.")
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
                observed = self._observer._read(persona, probe, count=True)
                if type(observed) is not int or observed not in {0, 1}:
                    raise MissingDependencyError("Employee-cell visibility was not conclusively observed.")
                visibility[employee_id] = observed == 1
            candidates = {}
            for field_name in selection.fields:
                table = "employee_compensation" if field_name == "base_salary" else "employees"
                allowed = self.source.matrix.permitted_columns(role.name, table, self.snapshot.columns_by_table[table])
                candidates[field_name] = tuple(employee_id for employee_id in selection.employee_ids
                    if not (field_name in allowed and visibility[employee_id]))
            if not any(candidates.values()):
                raise MissingDependencyError("No forbidden cells remain in this selector.")
            values = []
            self.source.config.resource_budgets.require_database_budget_inputs()
            with self.source._admin_source.connection(readonly=True) as connection:
                with _ReferenceDeadline(connection, self.source.config.limits.statement_timeout_seconds):
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = session_user")
                        flags = cursor.fetchone()
                        if flags is None or len(flags) != 2 or any(type(flag) is not bool for flag in flags) or not any(flags):
                            raise MissingDependencyError("Trusted canary read must establish complete FORCE-RLS source visibility.")
                        cursor.execute(sql.SQL("SELECT employee_id FROM {}.employees WHERE employee_id = ANY(%s)").format(sql.Identifier(self.snapshot.schema)), (list(selection.employee_ids),))
                        found = {row[0] for row in cursor.fetchall()}
                        if found != set(selection.employee_ids):
                            raise MissingDependencyError("Canary selectors name employees absent from the actual fixture.")
                        for field_name in selection.fields:
                            table = "employee_compensation" if field_name == "base_salary" else "employees"
                            candidate_ids = candidates[field_name]
                            if not candidate_ids:
                                continue  # Never read a permitted cell's value.
                            salary = field_name == "base_salary"
                            distinct = "DISTINCT ON (employee_id) " if salary else ""
                            temporal = " AND effective_date <= %s AND (effective_to IS NULL OR effective_to > %s)" if salary else ""
                            order_clause = "ORDER BY employee_id, effective_date DESC, compensation_id ASC" if salary else "ORDER BY employee_id"
                            query = sql.SQL(f"SELECT {distinct}{{}} FROM {{}}.{{}} WHERE employee_id = ANY(%s){temporal} {order_clause}").format(
                                sql.Identifier(field_name), sql.Identifier(self.snapshot.schema), sql.Identifier(table),
                            )
                            parameters = (list(candidate_ids), case.as_of_date, case.as_of_date) if salary else (list(candidate_ids),)
                            cursor.execute(query, parameters)
                            rows = cursor.fetchmany(self.source.config.limits.output_row_cap + 1)
                            if len(rows) > self.source.config.limits.output_row_cap:
                                raise MissingDependencyError("Canary read was incomplete at the configured row cap.")
                            for row in rows:
                                value = row[0]
                                try:
                                    require_distinctive_canary(value)
                                except ValueError:
                                    continue  # Nondistinctive cells are not leak evidence.
                                values.append(value)
            unique = {}
            for value in values:
                unique.setdefault(canonical_cell(value), value)
            if not unique:
                raise MissingDependencyError("No actual distinctive forbidden values were available from the reviewed selector.")
            return CanaryResult(True, digest, "Actual forbidden fixture values computed in the trusted lane.", tuple(unique.values()))
        except Exception as exc:
            return CanaryResult(False, None, "Actual canary inputs/computation are unavailable.", diagnostics=(_private_error(exc),))
