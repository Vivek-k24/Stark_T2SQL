"""Trusted future composition; no work occurs merely by importing this source.

The connected UI receives a FULL-only facade. The separate local harness must
supply an actual Prompt 2 EvaluationConnectionSource; configuration flags or
mode strings alone grant no capability. Administrators are used only during
trusted fixture/catalog startup and are closed before a request can generate
SQL. No generated statement is sent through an administrative connection.

STARK_RUNTIME_BINDINGS_PATH must identify an actual local JSON source record
whose fields match RuntimeSourceInputs below. This assignment does not create
that record, a review approval, a fixture, a model, or any measured evidence.
The actual local model-card template remains independently required. NFR-6
human-owned components are drafts under the user's explicit narrow exception.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import date
import json
import os
from pathlib import Path
from threading import Event, Lock
from typing import Iterator, Mapping

from ..config import AppConfig, DatabaseConnectionAlias, load_config, require_source_file
from ..context.builder import FrozenBaselineDDL, HarnessContextAuthority
from ..contracts import ExecutionMode, InputRequest, Outcome, Persona, SafeResponse
from ..db.catalog import SchemaSnapshot, filter_catalog, policy_state_sha256, snapshot_schema
from ..db.connections import AdminConnectionSource, EvaluationConnectionSource, RuntimeConnections
from ..db.executor import EvaluationExecutor, ProductionExecutor, ValidationAuthority
from ..db.persona import PersonaRegistry, resolve_personas
from ..errors import ConfigurationError, HarnessSafetyStopError, MissingDependencyError, SourceReadError
from ..inference.client import LocalInferenceClient, LocalModelServiceContract
from ..inference.template import PromptTemplate, ReviewedTemplateContract, load_template, require_sha256
from ..policy.loader import PolicyMatrix, load_policy, require_policy_schema
from ..security.validator import HarnessSafetyReviewer, ParserReviewApproval, ReviewedSQLValidator
from ..semantic.catalog import load_catalog, require_catalog_contract
from ..semantic.entitlements import filter_catalog_for_role
from ..semantic.models import SemanticCatalog
from ..utils.local_sources import resolve_runtime_path
from .response import SafeConcept, SafePolicyRow, safe_response, scope_note
from .trace import TraceWriter


PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class RuntimeSourceInputs:
    """Actual owner-supplied source declarations, never generated evidence.

    JSON keys are these field names. template_contract and model_service use
    the inference dataclass field names. parser_approval uses its six field
    names, with the two immutable sets represented as lists of strings.
    Passwords are excluded; only the existing environment variable name is
    accepted. The real fixture manifest's digest-key path is supplied explicitly
    because an authoritative manifest structure has not been provided.
    """

    admin_login_role: str
    admin_password_environment_variable: str
    sales_division_name: str
    fixture_hash_path: tuple[str, ...]
    installed_policy_state_sha256: str
    template_contract: ReviewedTemplateContract
    model_service: LocalModelServiceContract
    parser_approval: ParserReviewApproval

    def __post_init__(self) -> None:
        for value in (self.admin_login_role, self.admin_password_environment_variable, self.sales_division_name):
            if not isinstance(value, str) or not value.strip():
                raise MissingDependencyError("Actual trusted startup identity and fixture vocabulary are required.")
        if not self.admin_password_environment_variable.isidentifier():
            raise ConfigurationError("Trusted startup secrets must come from a named environment variable.")
        if type(self.fixture_hash_path) is not tuple or not self.fixture_hash_path or any(
            not isinstance(key, str) or not key for key in self.fixture_hash_path
        ):
            raise MissingDependencyError("The actual fixture manifest digest-key path is required.")
        require_sha256(self.installed_policy_state_sha256, label="actual installed policy state")
        if (
            type(self.template_contract) is not ReviewedTemplateContract
            or type(self.model_service) is not LocalModelServiceContract
            or type(self.parser_approval) is not ParserReviewApproval
        ):
            raise MissingDependencyError("Actual template, model deployment, and parser review bindings are required.")


def _inside_project(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ConfigurationError(f"The {label} source must reside in the project workspace.")
    return resolved


def _object(value: object, fields: set[str], label: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise ConfigurationError(f"The actual {label} source record has missing or unexpected fields.")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str or not item for item in value):
        raise ConfigurationError(f"The {label} source field must be a list of nonempty strings.")
    return tuple(value)


def load_runtime_source_inputs(path: Path, *, root: Path) -> RuntimeSourceInputs:
    """Read real local owner input later; absent records have no fallback."""
    source = require_source_file(resolve_runtime_path(path, root=root, label="runtime bindings"), label="runtime source bindings")
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate runtime binding key.")
            result[key] = value
        return result
    def nonfinite_constant(value):
        raise ValueError("Nonfinite runtime binding value.")
    try:
        with source.open("rb") as stream:
            data = stream.read(1_048_577)
        if len(data) > 1_048_576:
            raise ConfigurationError("The runtime binding source exceeds its byte bound.")
        raw = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=unique_object,
                         parse_constant=nonfinite_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SourceReadError("The actual local runtime binding source could not be read.") from exc
    raw = _object(raw, {
        "admin_login_role", "admin_password_environment_variable", "sales_division_name",
        "fixture_hash_path", "installed_policy_state_sha256", "template_contract", "model_service", "parser_approval",
    }, "runtime binding")
    template = _object(raw["template_contract"], {
        "template_sha256", "question_placeholder", "schema_placeholder", "question_open_tag",
        "question_close_tag", "as_of_line_prefix", "source_reference",
    }, "template binding")
    service = _object(raw["model_service"], {
        "model_sha256", "llama_cpp_build", "launcher_sha256", "beam_support_reviewed",
        "beam_supported", "weights_postdate_2024_02_07", "memory_limit_enforced", "slots", "prefix_cache_enabled",
    }, "model service binding")
    review = _object(raw["parser_approval"], {
        "sqlglot_version", "validator_revision", "function_policy_revision", "approved_node_shapes",
        "approved_function_rule_ids", "review_reference",
    }, "parser review")
    review = dict(review)
    review["approved_node_shapes"] = frozenset(_strings(review["approved_node_shapes"], "reviewed AST shapes"))
    review["approved_function_rule_ids"] = frozenset(_strings(review["approved_function_rule_ids"], "reviewed function rules"))
    return RuntimeSourceInputs(
        raw["admin_login_role"], raw["admin_password_environment_variable"], raw["sales_division_name"],
        _strings(raw["fixture_hash_path"], "fixture digest-key path"), raw["installed_policy_state_sha256"],
        ReviewedTemplateContract(**template), LocalModelServiceContract(**service), ParserReviewApproval(**review),
    )


@dataclass(frozen=True, slots=True)
class _HarnessComponents:
    source: EvaluationConnectionSource
    context_authority: HarnessContextAuthority
    executor: EvaluationExecutor
    baseline: FrozenBaselineDDL | None


@dataclass(frozen=True, slots=True)
class _PipelineRuntime:
    config: AppConfig
    matrix: PolicyMatrix
    personas: PersonaRegistry
    snapshot: SchemaSnapshot
    catalog: SemanticCatalog
    template: PromptTemplate
    client: LocalInferenceClient
    validation_authority: ValidationAuthority
    trace: TraceWriter
    production_executor: ProductionExecutor | None
    harness: _HarnessComponents | None = None


_HARNESS_SEAL = object()


@dataclass(frozen=True, slots=True)
class _HarnessInvocation:
    runtime: _PipelineRuntime
    mode: ExecutionMode
    prompt_version: int
    cancel_event: Event | None
    seal: object


_ACTIVE_RUNTIME: ContextVar[_PipelineRuntime | None] = ContextVar("stark_active_runtime", default=None)
_ACTIVE_HARNESS: ContextVar[_HarnessInvocation | None] = ContextVar("stark_active_harness", default=None)
_ACTIVE_CANCEL: ContextVar[Event | None] = ContextVar("stark_active_cancel", default=None)


@contextmanager
def _request_binding(
    runtime: _PipelineRuntime, invocation: _HarnessInvocation | None, cancel_event: Event | None,
) -> Iterator[None]:
    runtime_token = _ACTIVE_RUNTIME.set(runtime)
    harness_token = _ACTIVE_HARNESS.set(invocation)
    cancel_token = _ACTIVE_CANCEL.set(cancel_event)
    try:
        yield
    finally:
        _ACTIVE_CANCEL.reset(cancel_token)
        _ACTIVE_HARNESS.reset(harness_token)
        _ACTIVE_RUNTIME.reset(runtime_token)


class PersonaApplication:
    """The UI's complete capability: fixed FULL answers and safe metadata."""

    __slots__ = ("_runtime",)

    def __init__(self, runtime: _PipelineRuntime) -> None:
        if type(runtime) is not _PipelineRuntime or runtime.harness is not None or runtime.production_executor is None:
            raise ConfigurationError("The persona facade requires the production-only runtime.")
        self._runtime = runtime

    @property
    def personas(self) -> tuple[Persona, ...]:
        return tuple(self._runtime.personas.personas.values())

    def answer(self, persona: Persona, question: str, as_of_date: date) -> SafeResponse:
        from .answer import answer

        # Shadow any unrelated harness context. No UI argument can choose a
        # mode, profile, callback, raw SQL, identity, service URL or executor.
        with _request_binding(self._runtime, None, None):
            return safe_response(answer(persona, question, as_of_date, ExecutionMode.FULL))

    def semantic_view(self, persona: Persona) -> tuple[SafeConcept, ...]:
        runtime = self._runtime
        selected = runtime.personas.resolve(persona)
        projected = filter_catalog_for_role(runtime.catalog, runtime.matrix, runtime.snapshot, selected.business_role)
        concepts: list[SafeConcept] = []
        for entity in projected.entities.values():
            concepts.append(SafeConcept(
                entity.id, entity.name, entity.description, entity.kind, entity.aliases,
                None, (), tuple(projected.temporal_rules[key].description for key in entity.temporal_rule_ids), None,
            ))
        for metric in projected.metrics.values():
            concepts.append(SafeConcept(
                metric.id, metric.name, metric.description, "metric", metric.aliases, metric.units,
                tuple(str(ref) for ref in metric.grain),
                tuple(projected.temporal_rules[key].description for key in metric.temporal_rule_ids), metric.aggregation,
            ))
        return tuple(sorted(concepts, key=lambda concept: (concept.kind, concept.name)))

    def policy_view(self, persona: Persona) -> tuple[SafePolicyRow, ...]:
        runtime = self._runtime
        selected = runtime.personas.resolve(persona)
        projected = filter_catalog(runtime.snapshot, runtime.matrix, selected.business_role)
        role = runtime.matrix.role(selected.business_role)
        return tuple(SafePolicyRow(
            table.name, tuple(column.name for column in table.columns),
            role.tables[table.name].row_scope.value, scope_note(role.tables[table.name].row_scope),
        ) for table in projected.tables)


class HarnessApplication:
    """Explicit local CLI/evaluation capability; never exposed by the UI.

    This process capability cannot defend against arbitrary hostile Python in
    the same process. It prevents accidental UI/payload mode construction and
    requires the existing clone audits and safety gate for actual submission.
    No clone creation, reference execution or scoring runner is implemented.
    """

    __slots__ = ("_runtime",)

    def __init__(self, runtime: _PipelineRuntime, *, _seal: object) -> None:
        if _seal is not _HARNESS_SEAL or runtime.harness is None or runtime.production_executor is not None:
            raise HarnessSafetyStopError("A separate isolated harness runtime is required.")
        self._runtime = runtime

    def answer(
        self, persona: Persona, question: str, as_of_date: date, mode: ExecutionMode,
        *, prompt_version: int, cancel_event: Event | None = None,
    ) -> Outcome:
        from .answer import answer

        invocation = _HarnessInvocation(self._runtime, mode, prompt_version, cancel_event, _HARNESS_SEAL)
        with _request_binding(self._runtime, invocation, cancel_event):
            return answer(persona, question, as_of_date, mode)


def compose_persona_runtime(config: AppConfig, inputs: RuntimeSourceInputs) -> PersonaApplication:
    """Explicit future startup only; read real inputs before opening metadata.

    Every connection here is trusted startup metadata/fixture resolution owned
    by Prompt 2. All candidate execution is later owned by ProductionExecutor.
    The temporary administrative source/configuration is not kept in the facade.
    """
    if type(config) is not AppConfig or type(inputs) is not RuntimeSourceInputs:
        raise ConfigurationError("Typed application configuration and actual source bindings are required.")
    for path, label in (
        (config.paths.approved_frd, "approved FRD"), (config.paths.schema, "schema source"),
        (config.paths.policy_matrix, "access matrix"), (config.paths.semantic_catalog, "semantic catalog"),
        (config.paths.prompt_template, "verbatim model-card template"), (config.paths.fixture_dump, "fixture dump"),
        (config.paths.fixture_manifest, "fixture manifest"),
    ):
        require_source_file(_inside_project(path, config.paths.root, label=label), label=label)
    for path, label in ((config.paths.model_file, "GGUF model"), (config.resource_budgets.measurement_source, "resource measurements")):
        if path is None:
            raise MissingDependencyError(f"The actual {label} source path is required.")
        require_source_file(resolve_runtime_path(path, root=config.paths.root, label=label), label=label)
    config.resource_budgets.require_database_budget_inputs()
    matrix = load_policy(config.paths.policy_matrix)
    template = load_template(config.paths.prompt_template, contract=inputs.template_contract)
    client = LocalInferenceClient(config, service=inputs.model_service)
    validator = ReviewedSQLValidator(matrix, approval=inputs.parser_approval)
    reference_alias = config.database_connections[0]
    admin_alias = DatabaseConnectionAlias(
        "trusted_startup_metadata", inputs.admin_login_role, reference_alias.host, reference_alias.port,
        reference_alias.database_environment_variable, inputs.admin_password_environment_variable,
    )
    metadata_config = replace(config, database_connections=(*config.database_connections, admin_alias))
    admin = AdminConnectionSource(metadata_config, admin_alias.alias)
    try:
        with admin.connection(readonly=True) as connection:
            snapshot = snapshot_schema(connection, matrix.schema)
            require_policy_schema(matrix, snapshot.columns_by_table)
            installed = policy_state_sha256(connection, matrix)
            if installed != inputs.installed_policy_state_sha256:
                raise ConfigurationError("Installed policy differs from the actual owner-supplied installation binding.")
        personas = resolve_personas(
            admin, matrix, sales_division_name=inputs.sales_division_name,
            fixture_hash_path=inputs.fixture_hash_path, as_of_date=config.fixture_as_of_date,
        )
        catalog = load_catalog(config.paths.semantic_catalog, snapshot, matrix)
    finally:
        admin.close()
    source = RuntimeConnections(config, matrix, personas, expected_policy_state_sha256=installed)
    authority = ValidationAuthority(validator, policy_fingerprint=matrix.sha256, personas=personas)
    runtime = _PipelineRuntime(
        config, matrix, personas, snapshot, catalog, template, client, authority,
        TraceWriter(config.paths.root), ProductionExecutor(source, authority),
    )
    return PersonaApplication(runtime)


def compose_harness_runtime(
    source: EvaluationConnectionSource, *, snapshot: SchemaSnapshot, catalog: SemanticCatalog,
    template: PromptTemplate, client: LocalInferenceClient, parser_approval: ParserReviewApproval,
    baseline: FrozenBaselineDDL | None = None,
) -> HarnessApplication:
    """Future trusted harness composition over a real disposable-clone source.

    No boolean, UI value, administrator or ordinary RuntimeConnections may
    substitute for this exact source. Actual clone binding and least privilege
    are audited by HarnessContextAuthority and EvaluationExecutor per request.
    The optional E2 input is frozen original DDL, never fabricated from metadata.
    """
    if type(source) is not EvaluationConnectionSource or type(snapshot) is not SchemaSnapshot:
        raise HarnessSafetyStopError("The harness requires its exact isolated source and actual physical snapshot.")
    if (
        type(catalog) is not SemanticCatalog or type(template) is not PromptTemplate
        or type(client) is not LocalInferenceClient or type(parser_approval) is not ParserReviewApproval
        or (baseline is not None and type(baseline) is not FrozenBaselineDDL)
    ):
        raise MissingDependencyError("Actual harness context, inference and reviewed parser inputs are required.")
    if client.config != source.config or source.provenance.fixture_dump_sha256 != source.personas.fixture_dump_sha256:
        raise HarnessSafetyStopError("Model/fixture configuration differs from the isolated harness binding.")
    require_catalog_contract(catalog, snapshot, source.matrix)
    validator = ReviewedSQLValidator(source.matrix, approval=parser_approval)
    authority = ValidationAuthority(validator, policy_fingerprint=source.matrix.sha256, personas=source.personas)
    safety = HarnessSafetyReviewer(source.matrix, approval=parser_approval)
    components = _HarnessComponents(
        source, HarnessContextAuthority(source),
        EvaluationExecutor(source, safety_reviewer=safety, validation_authority=authority), baseline,
    )
    runtime = _PipelineRuntime(
        source.config, source.matrix, source.personas, snapshot, catalog, template, client,
        authority, TraceWriter(source.config.paths.root), None, components,
    )
    return HarnessApplication(runtime, _seal=_HARNESS_SEAL)


_STARTUP_LOCK = Lock()
_PERSONA_APPLICATION: PersonaApplication | None = None


def load_persona_runtime() -> PersonaApplication:
    """Future process-local source/configuration load; no model warmup occurs.

    Repeated Streamlit reruns reuse only the composed local runtime, never an
    authenticated session or candidate connection. Failed startup is not cached.
    Runtime source/evidence changes require an explicit process restart.
    """
    global _PERSONA_APPLICATION
    with _STARTUP_LOCK:
        if _PERSONA_APPLICATION is not None:
            return _PERSONA_APPLICATION
        config = load_config(root=PROJECT_ROOT)
        raw_path = os.environ.get("STARK_RUNTIME_BINDINGS_PATH")
        if not raw_path:
            raise MissingDependencyError("STARK_RUNTIME_BINDINGS_PATH must name actual local owner-supplied source bindings.")
        path = resolve_runtime_path(raw_path, root=config.paths.root, label="runtime bindings")
        inputs = load_runtime_source_inputs(path, root=config.paths.root)
        _PERSONA_APPLICATION = compose_persona_runtime(config, inputs)
        return _PERSONA_APPLICATION
