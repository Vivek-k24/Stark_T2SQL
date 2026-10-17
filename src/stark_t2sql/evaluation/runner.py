"""Source-only FR-9 orchestration over guarded cases and existing boundaries.

No benchmark, fixture, holdout, service, test or writer is invoked on import.
The ordinary CLI can compose only TUNING jobs. HOLDOUT requires a separate
boundary permit, exposure ledger and sealed trace lane; only a current target
QUESTION reaches inference, never reference SQL, answers or few-shot content.
The user's NFR-6 authorship exception is drafting only, not execution/review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from threading import Event, Lock
from typing import Callable

from ..contracts import ExecutionMode, ExpectedOutcome, OutcomeStatus
from ..errors import ConfigurationError, MissingDependencyError, SourceReadError
from ..semantic.contracts import ResolutionStatus
from ..semantic.resolver import resolve_question
from ..utils.fingerprints import sha256_context, sha256_file
from .ablation import AblationHarness, ModeProfile, require_run_change_discipline
from .attribution import AccuracyHistogram, LayerObservation, accuracy_histogram, attribute_layers, changed_cases, leakage_by_mode
from .cases import Case, CaseSet
from .comparator import ApprovedColumnMapping, CaseAssessment, evaluate_expected
from .failure_classes import ManualTriage, classify_failure
from .holdout import CasePartition, FrozenCaseIndex, FrozenCaseMetadata, HoldoutAuthority, HoldoutPermit, read_tuning_payload
from .records import (
    CaseRunRecord, EvaluationRecordWriter, RunFingerprints, RunRecord, RunSettings,
    UnavailableInput, WarmupRecord, case_record, validate_case_accounting,
)
from .reference import FixtureCanaryProvider, ReferenceAuthority, ReferenceResult, physical_reference_tables
from .wallclock import WallClockReview, lint_wallclock


_CASE_SEAL = object()


@dataclass(frozen=True, slots=True)
class GuardedCase:
    """A frozen payload read through the appropriate partition authority."""

    metadata: FrozenCaseMetadata
    case: Case = field(repr=False)
    column_approval: ApprovedColumnMapping | None = field(default=None, repr=False)
    _seal: object = field(default=None, repr=False, compare=False)
    _boundary_run_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._seal is not _CASE_SEAL or type(self.case) is not Case or self.case.id != self.metadata.id:
            raise ConfigurationError("Cases must be loaded through their immutable partition and payload guards.")


def _parse_guarded(payload: bytes, metadata: FrozenCaseMetadata, case_set: CaseSet, *, boundary_run_id: str | None = None) -> GuardedCase:
    # The benchmark parser itself performs no reads. It accepts only already
    # guarded bytes; imported code supplies no embedded question dataset.
    from benchmarks.accuracy.spec import parse_case_payload

    loaded = parse_case_payload(payload, expected_set=case_set, expected_id=metadata.id)
    if loaded.payload_sha256 != metadata.payload_sha256:
        raise ConfigurationError("Parsed case source differs from its actual frozen payload binding.")
    return GuardedCase(metadata, loaded.case, loaded.column_approval, _CASE_SEAL, boundary_run_id)


def load_tuning_case(
    index: FrozenCaseIndex, case_id: str, case_set: CaseSet, *, loader: Callable[[FrozenCaseMetadata], bytes],
) -> GuardedCase:
    payload = read_tuning_payload(index, case_id, loader=loader)
    return _parse_guarded(payload, index.by_id[case_id], case_set)


def load_sealed_case(
    authority: HoldoutAuthority, permit: HoldoutPermit, case_id: str, case_set: CaseSet,
    *, loader: Callable[[FrozenCaseMetadata], bytes],
) -> GuardedCase:
    # The authority records exposure before invoking the external reader.
    payload = authority.read_payload(permit, case_id, loader=loader)
    return _parse_guarded(payload, permit._index.by_id[case_id], case_set, boundary_run_id=permit._run_id)


@dataclass(frozen=True, slots=True)
class ColumnReviewEntry:
    case_id: str
    mode: ExecutionMode
    approval: ApprovedColumnMapping


@dataclass(frozen=True, slots=True)
class RunPlan:
    run_id: str
    mode: ExecutionMode
    partition: CasePartition
    index: FrozenCaseIndex
    settings: RunSettings
    fingerprints: RunFingerprints
    column_reviews: tuple[ColumnReviewEntry, ...] = ()
    canonical_expectations: tuple[tuple[str, str], ...] = ()
    triage_entries: tuple[tuple[str, ManualTriage], ...] = ()
    previous_run: RunRecord | None = None
    previous_observations: tuple[LayerObservation, ...] = ()
    new_baseline: bool = False
    baseline_change_reference: str | None = None
    sealed_owner_authorization_reference: str | None = None
    holdout_authority: HoldoutAuthority | None = field(default=None, repr=False)
    holdout_permit: HoldoutPermit | None = field(default=None, repr=False)
    never_execute_case_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.mode) is not ExecutionMode or type(self.partition) is not CasePartition
            or type(self.index) is not FrozenCaseIndex or type(self.settings) is not RunSettings
            or type(self.fingerprints) is not RunFingerprints
        ):
            raise ConfigurationError("Run planning requires exact typed mode/partition and actual frozen metadata.")
        ModeProfile(self.mode, self.settings.prompt_version)
        if self.fingerprints.case_set_sha256 != self.index.sha256:
            raise MissingDependencyError("Run case-set fingerprint must describe the actual immutable index.")
        for name in ("column_reviews", "canonical_expectations", "triage_entries", "previous_observations", "never_execute_case_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if (
            any(type(case_id) is not str or case_id not in self.index.by_id for case_id in self.never_execute_case_ids)
            or len(set(self.never_execute_case_ids)) != len(self.never_execute_case_ids)
        ):
            raise ConfigurationError("Never-execute IDs must be unique actual frozen case identifiers.")
        if len({entry.case_id for entry in self.column_reviews if entry.mode is self.mode}) != sum(entry.mode is self.mode for entry in self.column_reviews):
            raise ConfigurationError("Each case/mode has at most one actual SQL-bound projection review.")
        if len(dict(self.canonical_expectations)) != len(self.canonical_expectations) or len(dict(self.triage_entries)) != len(self.triage_entries):
            raise ConfigurationError("Canonical expectation and manual-triage case IDs must be unique.")
        if self.new_baseline and not self.baseline_change_reference:
            raise MissingDependencyError("A new baseline requires actual independent baseline/change provenance.")
        if self.partition is CasePartition.HOLDOUT and not self.sealed_owner_authorization_reference:
            raise MissingDependencyError("Sealed runtime evaluation requires the owner's actual boundary/exposure authorization.")
        if self.partition is CasePartition.HOLDOUT:
            if type(self.holdout_authority) is not HoldoutAuthority or type(self.holdout_permit) is not HoldoutPermit:
                raise MissingDependencyError("A live issued holdout authority/permit is required for sealed case submission.")
            self.holdout_authority._permit(self.holdout_permit)
            if self.holdout_permit._run_id != self.run_id or self.holdout_permit._index is not self.index:
                raise ConfigurationError("The sealed permit belongs to a different run/frozen index.")


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    mode: ExecutionMode
    partition: CasePartition
    observations: tuple[LayerObservation, ...]
    histogram: AccuracyHistogram
    records: tuple[CaseRunRecord, ...]
    complete: bool
    unavailable_inputs: tuple[UnavailableInput, ...]
    source_limits: tuple[str, ...]
    unsubmitted_case_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("observations", "records", "unavailable_inputs", "source_limits", "unsubmitted_case_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        observed = tuple(row.case_id for row in self.observations)
        if len(set(observed)) != len(observed) or len(set(self.unsubmitted_case_ids)) != len(self.unsubmitted_case_ids) or set(observed) & set(self.unsubmitted_case_ids):
            raise ConfigurationError("Case accounting cannot duplicate or resubmit an observed case.")
        if self.histogram != accuracy_histogram(self.observations) or tuple(record.case_id for record in self.records) != observed:
            raise ConfigurationError("Run summary must describe its actual observations and case records.")
        if any(row.triage_pending and row.passed is not False for row in self.observations):
            raise ConfigurationError("Pending triage belongs only to failed scored cases.")
        validate_case_accounting(self.accounting)
        if self.complete and (self.pending_cases or self.pending_triage_cases or self.unavailable_inputs):
            raise ConfigurationError("An incomplete or pending run cannot claim completion.")

    @property
    def total_cases(self) -> int:
        return len(self.observations) + self.unsubmitted_cases

    @property
    def scored_cases(self) -> int:
        return self.histogram.scored

    @property
    def pending_cases(self) -> int:
        return self.unscored_cases + self.unsubmitted_cases

    @property
    def unscored_cases(self) -> int:
        return self.histogram.unscored

    @property
    def pending_triage_cases(self) -> int:
        return self.histogram.pending_triage_count

    @property
    def unsubmitted_cases(self) -> int:
        return len(self.unsubmitted_case_ids)

    @property
    def accounting(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in (
            "total_cases", "scored_cases", "unscored_cases", "pending_triage_cases", "unsubmitted_cases", "pending_cases",
        )}


def _candidate_matches_reference(candidate: str | None, reference: ReferenceResult, matrix) -> bool:
    """Only outer whitespace and ONE terminal semicolon may vary.

    A real available, legitimate reference and its unchanged executed-SQL hash
    remain necessary. Strict relation parsing rejects multi/empty statements
    and malformed or write-bearing SQL even when a test supplies a matching
    hash. This creates no parser or reference approval and executes no SQL.
    """
    if reference.available is not True or reference.proves_legitimate is not True or reference.table is None or not isinstance(candidate, str):
        return False
    try:
        physical_reference_tables(candidate, matrix)
        import sqlglot
        from sqlglot.tokens import TokenType

        trimmed = candidate.strip()
        tokens = sqlglot.tokenize(trimmed, read="postgres")
        terminators = [token for token in tokens if token.token_type is TokenType.SEMICOLON]
        if len(terminators) > 1:
            return False
        variants = {candidate, trimmed}
        if terminators:
            if tokens[-1] is terminators[0] and terminators[0].end == len(trimmed) - 1:
                stem = trimmed[:-1].rstrip()
                variants.update((stem, stem + ";"))
        else:
            appended = sqlglot.tokenize(trimmed + ";", read="postgres")
            if appended and appended[-1].token_type is TokenType.SEMICOLON and appended[-1].end == len(trimmed):
                variants.add(trimmed + ";")
    except Exception:
        return False
    return any(sha256_context(text) == reference.table.sql_sha256 for text in variants)


@dataclass(frozen=True, slots=True)
class RuntimeRecordInputs:
    """Actual owner declarations absent from the existing client contract.

    None means unavailable. These fields are not inferred from a model name,
    source branch, CPU count, environment package list or assumed service flags.
    They describe future supplied launch/revision provenance, not measurements
    made by this source-authoring assignment.
    """

    model_context_size: int | None = None
    model_threads: int | None = None
    validator_commit: str | None = None
    baseline_reference: str | None = None
    exclusive_model_service_reference: str | None = None


def collect_run_metadata(
    harness: AblationHarness, index: FrozenCaseIndex, profile: ModeProfile,
    *, supplied: RuntimeRecordInputs | None = None,
) -> tuple[RunFingerprints, RunSettings]:
    """Future read-only collection from actual composed objects/source bytes.

    Does not connect to a service/database, import a parser for version discovery,
    read case payloads, execute SQL, create an output or invent a missing hash.
    The fixture digest comes from the registry's existing real manifest binding.
    Source bytes alone do not establish historical schema fidelity. Per-case
    filtered DDL and semantic-block hashes come from the candidate outcome;
    its request ID links the separate internal rendered-prompt trace metadata.
    """
    if type(harness) is not AblationHarness or type(index) is not FrozenCaseIndex or type(profile) is not ModeProfile:
        raise ConfigurationError("Run metadata requires the actual composed harness, frozen index and profile.")
    if supplied is None:
        supplied = RuntimeRecordInputs()
    if type(supplied) is not RuntimeRecordInputs:
        raise ConfigurationError("Additional run provenance must be explicit typed owner declarations.")
    runtime = harness._runtime
    config = runtime.config
    root = config.paths.root.resolve()

    def optional_digest(path: Path | None) -> str | None:
        if path is None:
            return None
        source = Path(path).resolve()
        if not source.is_relative_to(root):
            raise ConfigurationError("Run artifact reads must stay within the existing project root.")
        try:
            return sha256_file(source)
        except (MissingDependencyError, SourceReadError):
            return None

    approval = runtime.validation_authority._reviewer.approval
    if harness.model_available:
        decoding = runtime.client.decoding
        model_hash = runtime.client.service.model_sha256
        launcher_hash = runtime.client.service.launcher_sha256
        template_hash = runtime.template.sha256
        catalog = getattr(runtime, "catalog", None)
        semantic_hash = catalog.sha256 if catalog is not None else None
        measurement_hash = runtime.client.measurement_sha256
        build = runtime.client.service.llama_cpp_build
    else:
        from ..inference.client import DecodingDefaults

        # Recorded source defaults only; no direct-SQL request calls a model.
        decoding = DecodingDefaults()
        model_hash = launcher_hash = template_hash = semantic_hash = build = None
        measurement_hash = optional_digest(config.resource_budgets.measurement_source)
    fingerprints = RunFingerprints(
        fixture_dump_sha256=runtime.personas.fixture_dump_sha256,
        access_matrix_sha256=runtime.matrix.sha256,
        semantic_catalog_sha256=semantic_hash,
        prompt_template_sha256=template_hash,
        model_gguf_sha256=model_hash,
        llama_launcher_sha256=launcher_hash,
        parser_review_sha256=approval.fingerprint if approval is not None else None,
        validator_source_sha256=optional_digest(root / "src" / "stark_t2sql" / "security" / "validator.py"),
        case_set_sha256=index.sha256,
        source_schema_sha256=optional_digest(config.paths.schema),
        resource_measurements_sha256=measurement_hash,
    )
    settings = RunSettings(
        prompt_version=profile.prompt_version,
        llama_cpp_build=build,
        model_context_size=supplied.model_context_size if harness.model_available else None,
        model_threads=supplied.model_threads if harness.model_available else None,
        sqlglot_version=approval.sqlglot_version if approval is not None else None,
        validator_revision=runtime.validation_authority._reviewer.revision,
        validator_commit=supplied.validator_commit,
        temperature=decoding.temperature, seed=decoding.seed,
        max_tokens=decoding.max_tokens, stop=decoding.stop,
        generation_timeout_seconds=config.limits.generation_timeout_seconds,
        statement_timeout_seconds=config.limits.statement_timeout_seconds,
        output_row_cap=config.limits.output_row_cap,
        database_work_mem_kib=config.resource_budgets.database_work_mem_kib,
        database_temp_file_limit_kib=config.resource_budgets.database_temp_file_limit_kib,
        model_memory_limit_mib=config.resource_budgets.model_memory_limit_mib,
        baseline_reference=supplied.baseline_reference,
        exclusive_model_service_reference=supplied.exclusive_model_service_reference if harness.model_available else None,
    )
    return fingerprints, settings


_RUN_FLIGHT = Lock()


class EvaluationRunner:
    """No UI dependency; candidate execution is always the isolated harness.

    Missing oracle/projection/canary/lint inputs produce explicitly unscored
    records. Intent mismatch needs an actual manual taxonomy decision; no
    diagnosis or regression result is invented merely to finish a run.
    """

    def __init__(
        self, harness: AblationHarness, *, references: ReferenceAuthority | None,
        wallclock_review: WallClockReview | None,
        canaries: FixtureCanaryProvider | None = None,
    ) -> None:
        if type(harness) is not AblationHarness:
            raise ConfigurationError("Evaluation requires the source-controlled isolated harness facade.")
        if references is not None and (type(references) is not ReferenceAuthority or references.source is not harness.source):
            raise ConfigurationError("Independent references must bind the exact same fixture clone and personas.")
        if wallclock_review is not None and type(wallclock_review) is not WallClockReview:
            raise ConfigurationError("Wall-clock lint needs its actual independently supplied parser review.")
        self.harness, self.references, self.wallclock_review = harness, references, wallclock_review
        if canaries is not None and (type(canaries) is not FixtureCanaryProvider or canaries.source is not harness.source):
            raise ConfigurationError("Computed canaries must bind the exact same actual fixture clone.")
        self.canaries = canaries

    def _guard(self, cases: tuple[GuardedCase, ...], plan: RunPlan, writer: EvaluationRecordWriter) -> None:
        if type(plan) is not RunPlan or type(writer) is not EvaluationRecordWriter:
            raise ConfigurationError("Actual run planning and bound internal writer are required.")
        if writer.run_id != plan.run_id or writer.partition is not plan.partition:
            raise ConfigurationError("The writer belongs to a different run or partition.")
        if not cases or any(type(loaded) is not GuardedCase for loaded in cases):
            raise ConfigurationError("A run needs guarded case source objects, never bare/untyped payloads.")
        if len({loaded.case.id for loaded in cases}) != len(cases):
            raise ConfigurationError("A run needs a nonempty unique set of guarded actual cases.")
        for loaded in cases:
            if type(loaded) is not GuardedCase or loaded._seal is not _CASE_SEAL:
                raise ConfigurationError("Ungoverned case objects cannot enter the evaluator.")
            metadata = plan.index.by_id.get(loaded.case.id)
            if metadata != loaded.metadata or metadata.partition is not plan.partition:
                raise ConfigurationError("A case belongs to a different immutable index or partition.")
            if plan.partition is CasePartition.HOLDOUT and loaded._boundary_run_id != plan.run_id:
                raise ConfigurationError("Every sealed case must have been exposed within this exact boundary run.")
            if loaded.case.id in plan.never_execute_case_ids and loaded.case.sql is None:
                raise ConfigurationError("A prepared direct-SQL safety stop cannot submit a question to the model.")
        runtime = self.harness._runtime
        actual = {
            "fixture_dump_sha256": runtime.personas.fixture_dump_sha256,
            "access_matrix_sha256": runtime.matrix.sha256,
        }
        if self.harness.model_available:
            actual.update({
                "model_gguf_sha256": runtime.client.service.model_sha256,
                "prompt_template_sha256": runtime.template.sha256,
                "semantic_catalog_sha256": getattr(runtime, "catalog", None).sha256 if getattr(runtime, "catalog", None) is not None else None,
                "resource_measurements_sha256": runtime.client.measurement_sha256,
                "llama_launcher_sha256": runtime.client.service.launcher_sha256,
            })
            if plan.settings.llama_cpp_build != runtime.client.service.llama_cpp_build or plan.settings.seed != runtime.client.decoding.seed:
                raise ConfigurationError("Run model/build/decoding declarations differ from the actual composed client.")
            for setting in ("temperature", "max_tokens", "stop"):
                if getattr(plan.settings, setting) != getattr(runtime.client.decoding, setting):
                    raise ConfigurationError("Run decoding fields differ from the actual fixed local client.")
        for setting in ("generation_timeout_seconds", "statement_timeout_seconds", "output_row_cap"):
            if getattr(plan.settings, setting) != getattr(runtime.config.limits, setting):
                raise ConfigurationError("Recorded request limits differ from the actual source configuration.")
        for setting in ("database_work_mem_kib", "database_temp_file_limit_kib", "model_memory_limit_mib"):
            if getattr(plan.settings, setting) != getattr(runtime.config.resource_budgets, setting):
                raise ConfigurationError("Recorded budgets differ from the actual measured source declarations.")
        approval = runtime.validation_authority._reviewer.approval
        if approval is not None and (
            plan.fingerprints.parser_review_sha256 != approval.fingerprint
            or plan.settings.sqlglot_version != approval.sqlglot_version
            or plan.settings.validator_revision != runtime.validation_authority._reviewer.revision
        ):
            raise ConfigurationError("Parser/revision records differ from the actual supplied review profile.")
        for field_name, digest in actual.items():
            if getattr(plan.fingerprints, field_name) != digest:
                raise MissingDependencyError("Run fingerprints differ from actual source/model/fixture bindings.")
        # Actual current source bytes, never a fabricated commit hash.
        source_root = Path(__file__).resolve().parents[3]
        for field_name, path in (
            ("validator_source_sha256", source_root / "src" / "stark_t2sql" / "security" / "validator.py"),
            ("source_schema_sha256", source_root / "schema.sql"),
        ):
            recorded = getattr(plan.fingerprints, field_name)
            if recorded is not None and recorded != sha256_file(path):
                raise MissingDependencyError("Recorded run source bytes differ from actual local source inputs.")
        if plan.partition is CasePartition.HOLDOUT:
            plan.holdout_authority._permit(plan.holdout_permit)
            # Canonical answer records raw QUESTION internally. Sealed runs
            # therefore require a separately composed trace root, not the
            # ordinary playground/tuning events.jsonl. No prior file is edited.
            trace_root = runtime.trace.root.resolve()
            if trace_root == source_root or not trace_root.is_relative_to(source_root):
                raise ConfigurationError("Sealed targets require an explicit distinct internal trace root inside the project.")
            if not writer.directory.resolve().is_relative_to(trace_root):
                raise ConfigurationError("Sealed case metadata and raw internal traces must share the owner-restricted lane.")

    def run(
        self, cases: tuple[GuardedCase, ...], plan: RunPlan, writer: EvaluationRecordWriter,
        *, warmup_case: GuardedCase | None = None, cancel_event: Event | None = None,
    ) -> RunSummary:
        self._guard(cases, plan, writer)
        if not _RUN_FLIGHT.acquire(blocking=False):
            raise ConfigurationError("Another evaluation run owns the process measurement guard.")
        try:
            profile = ModeProfile(plan.mode, plan.settings.prompt_version)
            unavailable = list(plan.fingerprints.unavailable)
            for field_name in ("model_context_size", "model_threads", "sqlglot_version", "validator_commit", "exclusive_model_service_reference"):
                if self.harness.model_available and getattr(plan.settings, field_name) is None:
                    unavailable.append(UnavailableInput(field_name, "Actual runtime/build/measurement declaration is unavailable."))
            if any(loaded.case.question is not None for loaded in cases):
                if not self.harness.model_available or warmup_case is None:
                    raise MissingDependencyError("A model run requires its actual local model and unscored tuning warmup input.")
                if (
                    type(warmup_case) is not GuardedCase or warmup_case._seal is not _CASE_SEAL
                    or warmup_case.metadata.partition is not CasePartition.TUNING
                    or plan.index.by_id.get(warmup_case.case.id) != warmup_case.metadata
                ):
                    raise ConfigurationError("Warmup must be an independently guarded TUNING case from the immutable index.")
                try:
                    warmup_record = self.harness.warmup(warmup_case.case, profile, cancel_event=cancel_event)
                except Exception:
                    # A failed warmup is a real run-input failure, not a case
                    # observation. Record actual unavailable metadata and the
                    # IDs never submitted; invent no per-case status/results.
                    unavailable.append(UnavailableInput("warmup", "The actual unscored warmup could not complete; no measured cases were submitted."))
                    warmup_record = WarmupRecord(False, unavailable_reason=unavailable[-1].reason)
                    aborted = RunRecord(
                        plan.run_id, plan.mode, plan.partition, plan.fingerprints, plan.settings,
                        warmup_record, tuple(unavailable), never_execute_case_ids=plan.never_execute_case_ids,
                    )
                    writer.write_run(aborted)
                    histogram = accuracy_histogram(())
                    unsubmitted = tuple(loaded.case.id for loaded in cases)
                    summary = RunSummary(plan.run_id, plan.mode, plan.partition, (), histogram, (), False, tuple(unavailable), ("Warmup unavailable; scoring did not begin.",), unsubmitted)
                    writer.write_summary({"accuracy": asdict(histogram), "accounting": summary.accounting, "complete": False, "unavailable_inputs": [asdict(item) for item in unavailable], "unsubmitted_case_ids": unsubmitted})
                    writer.append_project_log(aborted, scored_cases=summary.scored_cases, pending_cases=summary.pending_cases, accounting=summary.accounting)
                    return summary
            else:
                warmup_record = WarmupRecord(False, unavailable_reason="Not applicable: deterministic direct-SQL run has no model request.")
                # Direct-only runs deliberately have no model artifacts/settings.
                unavailable = [item for item in unavailable if item.field not in {
                    "model_gguf_sha256", "llama_launcher_sha256", "prompt_template_sha256", "semantic_catalog_sha256",
                }]
            run_record = RunRecord(
                plan.run_id, plan.mode, plan.partition, plan.fingerprints, plan.settings,
                warmup_record, tuple(unavailable), plan.previous_run.run_id if plan.previous_run is not None else None,
                plan.baseline_change_reference, plan.never_execute_case_ids,
            )
            if plan.previous_run is not None and not plan.new_baseline:
                require_run_change_discipline(plan.previous_run, run_record)
            writer.write_run(run_record)
            observations, records = [], []
            reviews = {entry.case_id: entry.approval for entry in plan.column_reviews if entry.mode is plan.mode}
            expectations, triage = dict(plan.canonical_expectations), dict(plan.triage_entries)
            unsubmitted = ()
            for case_index, loaded in enumerate(cases):
                case = loaded.case
                if plan.partition is CasePartition.HOLDOUT:
                    plan.holdout_authority._permit(plan.holdout_permit)
                if cancel_event is not None and cancel_event.is_set():
                    unsubmitted = tuple(remaining.case.id for remaining in cases[case_index:])
                    unavailable.append(UnavailableInput("cancellation", "Evaluation was cancelled; remaining cases were not submitted."))
                    break
                # Compute the frozen human reference BEFORE candidate inference,
                # so model output can never become administrative reference SQL.
                reference = (
                    self.references.evaluate(case, plan.mode) if self.references is not None and case.reference_sql is not None
                    else ReferenceResult(False, None, "Independent reviewed reference is unavailable.")
                )
                provider = getattr(self, "canaries", None)
                computed_canaries = provider.for_case(case) if provider is not None and case.requires_forbidden_values else None
                outcome = (
                    self.harness.question(case, profile, cancel_event=cancel_event) if case.question is not None
                    else self.harness.direct(case, profile, never_execute=case.id in plan.never_execute_case_ids)
                )
                try:
                    assessment = evaluate_expected(
                        case, outcome, reference=reference.table if reference.available else None,
                        column_approval=reviews.get(case.id, loaded.column_approval),
                        forbidden_values=computed_canaries.values if computed_canaries is not None and computed_canaries.available else None,
                        forbidden_values_fixture_sha256=computed_canaries.fixture_dump_sha256 if computed_canaries is not None and computed_canaries.available else None,
                    )
                except (TypeError, ValueError, ArithmeticError):
                    assessment = CaseAssessment(None, "Typed scalar/projection comparison capability is unavailable.")
                if computed_canaries is not None and not computed_canaries.available and not assessment.leak_found:
                    assessment = replace(assessment, passed=None, reason=computed_canaries.reason, canary_check_available=False)
                # An oracle for a legitimate intent does not prove that a
                # different generated SQL statement is legitimate. Exact
                # independently executed reference bytes supply that proof;
                # other projections remain eligible for explicitly pending
                # human triage rather than a fabricated validator defect.
                actual_candidate = outcome.regenerated_sql or outcome.extracted_sql
                candidate_proved = _candidate_matches_reference(actual_candidate, reference, self.harness._runtime.matrix)
                assessment = replace(assessment, reference_proves_legitimate=candidate_proved)
                if case.expected_outcome in {ExpectedOutcome.MATCH_REFERENCE, ExpectedOutcome.SCOPED_RESULT, ExpectedOutcome.CANONICAL_RESOLUTION} and not reference.available:
                    # Keep independently observable extraction/DB syntax failures,
                    # but do not infer legitimate over-blocking from an absent oracle.
                    if outcome.status in {OutcomeStatus.ANSWERED, OutcomeStatus.BLOCKED_DB, OutcomeStatus.BLOCKED_VALIDATOR, OutcomeStatus.CLARIFICATION_REQUIRED} and not assessment.leak_found:
                        assessment = replace(assessment, passed=None, reason=reference.reason, reference_proves_legitimate=False)
                candidate_sql = outcome.executed_sql or outcome.regenerated_sql or outcome.extracted_sql
                clock = None
                if candidate_sql is not None and outcome.status is not OutcomeStatus.HARNESS_SAFETY_STOP:
                    clock = lint_wallclock(candidate_sql, review=self.wallclock_review)
                    if not clock.available and outcome.status is OutcomeStatus.ANSWERED and not assessment.leak_found:
                        assessment = replace(assessment, passed=None, reason="Actual guarded wall-clock lint input is unavailable.")
                    elif clock.uses_wallclock and not assessment.leak_found:
                        assessment = replace(assessment, passed=False, reason="Prohibited wall-clock AST use was observed.")
                if case.expected_outcome is ExpectedOutcome.CANONICAL_RESOLUTION and assessment.passed is True:
                    expected_id = expectations.get(case.id)
                    runtime = self.harness._runtime
                    catalog, snapshot = getattr(runtime, "catalog", None), getattr(runtime, "snapshot", None)
                    if not self.harness.model_available or expected_id is None or case.question is None or catalog is None or snapshot is None:
                        assessment = replace(assessment, passed=None, reason="Actual canonical-definition expectation is unavailable.")
                    else:
                        resolution = resolve_question(case.question, catalog, runtime.matrix, snapshot, runtime.personas.resolve(case.persona).business_role)
                        if resolution.status is not ResolutionStatus.RESOLVED or resolution.concept_ids != (expected_id,):
                            assessment = replace(assessment, passed=False, reason="Observed governed resolution differs from the unique reviewed definition.")
                classification = classify_failure(outcome, assessment, wallclock=clock, manual_triage=triage.get(case.id))
                leak = None if outcome.status is OutcomeStatus.HARNESS_SAFETY_STOP else (
                    True if assessment.leak_found else False if assessment.canary_check_available else None
                )
                # Compare identical source candidates for causal attribution;
                # extraction/regeneration remain internal distinct facts.
                candidate_digest = sha256_context(outcome.extracted_sql) if outcome.extracted_sql is not None else None
                observation = LayerObservation(
                    case.id, plan.mode, outcome.status, outcome.stopping_layer, assessment.passed, leak,
                    classification.failure_class, classification.triage_pending, case.set, candidate_digest,
                )
                record = case_record(
                    case, outcome, run_id=plan.run_id, partition=plan.partition,
                    assessment=assessment.passed, assessment_reason=assessment.reason, leakage_observed=leak,
                    failure_class=classification.failure_class, triage_pending=classification.triage_pending,
                    candidate_sha256=candidate_digest,
                )
                writer.write_case(record)
                observations.append(observation)
                records.append(record)
                if assessment.passed is None:
                    unavailable.append(UnavailableInput("case:" + case.id, assessment.reason))
            histogram = accuracy_histogram(observations)
            complete = not unavailable and not histogram.unscored and not histogram.pending_triage_count and not unsubmitted
            limits = (
                "Prepared hazardous statements/functions/resource attacks remain unexecuted safety stops.",
                "NO_VALIDATOR bypasses application table entitlements, retaining mandatory structure safety and the persona's database identity.",
                "Direct SQL has no prompt context to ablate; through-model candidates may differ across profiles.",
                "Source-schema bytes do not establish historical fidelity; actual owner fidelity inputs remain separate.",
                "Recorded model declarations are actual owner inputs, not proof of deployed resource enforcement.",
            )
            summary = RunSummary(plan.run_id, plan.mode, plan.partition, tuple(observations), histogram, tuple(records), complete, tuple(unavailable), limits, unsubmitted)
            writer.write_summary({
                "accuracy": asdict(histogram), "accounting": summary.accounting, "leakage": [asdict(item) for item in leakage_by_mode(observations)],
                "attribution": [asdict(item) for item in attribute_layers(observations)],
                "changed_cases": [asdict(item) for item in changed_cases(plan.previous_observations, observations)],
                "complete": complete, "source_limits": limits,
                "unavailable_inputs": [asdict(item) for item in unavailable],
                "unsubmitted_case_ids": unsubmitted,
            })
            writer.append_project_log(run_record, scored_cases=summary.scored_cases, pending_cases=summary.pending_cases, accounting=summary.accounting)
            return summary
        finally:
            _RUN_FLIGHT.release()


@dataclass(frozen=True, slots=True)
class EvaluationJob:
    """Actual owner composition returned to the TUNING-only local entrypoint."""

    runner: EvaluationRunner
    cases: tuple[GuardedCase, ...]
    plan: RunPlan
    writer: EvaluationRecordWriter
    warmup_case: GuardedCase | None = None
    cancel_event: Event | None = None

    def execute(self) -> RunSummary:
        if type(self.runner) is not EvaluationRunner:
            raise ConfigurationError("An evaluation job requires the exact source-controlled runner.")
        return self.runner.run(self.cases, self.plan, self.writer, warmup_case=self.warmup_case, cancel_event=self.cancel_event)


def combine_ablation_observations(summaries: tuple[RunSummary, ...]) -> tuple[LayerObservation, ...]:
    """Pair only actual supplied run observations, never presumed baseline leaks."""
    if any(type(summary) is not RunSummary for summary in summaries):
        raise ConfigurationError("Attribution requires actual typed run summaries.")
    modes = tuple(summary.mode for summary in summaries)
    if len(set(modes)) != len(modes):
        raise ConfigurationError("An attribution collection has at most one run per mode.")
    return tuple(observation for summary in summaries for observation in summary.observations)
