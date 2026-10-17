"""FR-3 context data for the later Prompt 4 prompt builder and answer pipeline.

Normal persona requests have exactly the E5 v2 FULL profile. Harness profiles
use a separate, issued clone-bound capability; a mode string or configuration
boolean does not authorize full-context disclosure. No prompt template, model
client, UI, or evaluation runner is implemented here. Context construction is
pure over supplied metadata. Only the explicitly invoked future harness
authority.issue() boundary performs existing trusted clone/privilege audits.

NFR-6 reserves this module to the human author. Prompt 3 specifically permits
this Codex source draft; no runtime invocation is authorized by that exception.
Context minimization remains descriptive, never an authorization boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from threading import Lock

from ..contracts import ExecutionMode, InputRequest
from ..db.catalog import SchemaSnapshot
from ..db.connections import EvaluationConnectionSource
from ..errors import (
    ConfigurationError, HarnessSafetyStopError, MissingDependencyError, SourceReadError,
)
from ..policy.loader import PolicyMatrix, require_policy_schema
from ..semantic.catalog import require_catalog_contract
from ..semantic.models import SemanticCatalog
from ..utils.fingerprints import sha256_bytes, sha256_context
from .schema_filter import SnapshotKind, compile_full_schema, compile_schema
from .semantic_filter import compile_full_semantics, compile_semantics


def _require_digest(value: str | None, *, label: str) -> str:
    if value is None:
        raise MissingDependencyError(f"The real recorded {label} is unavailable.")
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ConfigurationError(f"The recorded {label} must be an actual lowercase SHA-256 digest.")
    return value


@dataclass(frozen=True, slots=True)
class FrozenBaselineDDL:
    """Exact authoritative E2 schema bytes bound to a recorded frozen digest.

    Supply the original E2 DDL input and its recorded digest, not DDL generated
    from a role snapshot. No default path or invented baseline is substituted.
    The external baseline run/source record is a required trusted input; this
    type is not a claim that an E2 run has happened. UTF-8 bytes, BOMs and CRLFs
    are preserved. Prompt 4 must insert text verbatim without strip/reformat.
    """

    source_bytes: bytes = field(repr=False)
    recorded_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_bytes, bytes) or not self.source_bytes:
            raise MissingDependencyError("The original E2 full-schema DDL input is unavailable.")
        expected = _require_digest(self.recorded_sha256, label="E2 full-schema fingerprint")
        try:
            self.source_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise SourceReadError("The original E2 DDL input must be strict UTF-8 source.") from exc
        if sha256_bytes(self.source_bytes) != expected:
            raise ConfigurationError("The supplied E2 DDL source differs from its frozen run/source binding.")

    @property
    def text(self) -> str:
        return self.source_bytes.decode("utf-8", errors="strict")

    @classmethod
    def from_bytes(cls, source_bytes: bytes, *, recorded_sha256: str | None) -> FrozenBaselineDDL:
        return cls(source_bytes, _require_digest(recorded_sha256, label="E2 full-schema fingerprint"))

    @classmethod
    def from_file(
        cls, path: str | Path | None, *, recorded_sha256: str | None,
        max_bytes: int = 4_194_304,
    ) -> FrozenBaselineDDL:
        """Read frozen local source later, in binary mode without newline changes."""
        expected = _require_digest(recorded_sha256, label="E2 full-schema fingerprint")
        if path is None or path == "":
            raise MissingDependencyError("The original E2 DDL source path is unavailable.")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ConfigurationError("A positive E2 DDL source-size limit is required.")
        try:
            with Path(path).open("rb") as source:
                data = source.read(max_bytes + 1)
        except FileNotFoundError as exc:
            raise MissingDependencyError("The original E2 DDL source file is unavailable.") from exc
        except (OSError, ValueError, TypeError) as exc:
            raise SourceReadError("The original E2 DDL source file could not be read.") from exc
        if len(data) > max_bytes:
            raise ConfigurationError("The original E2 DDL source exceeds the configured byte limit.")
        return cls(data, expected)


@dataclass(frozen=True, slots=True)
class CompiledContext:
    """Internal context inputs, independently fingerprinted before prompt assembly."""

    request: InputRequest
    prompt_version: int
    ddl: str
    semantic_text: str
    ddl_sha256: str
    semantic_sha256: str
    policy_sha256: str
    semantic_catalog_sha256: str | None
    profile: str

    def __post_init__(self) -> None:
        if type(self.request) is not InputRequest or type(self.prompt_version) is not int:
            raise ConfigurationError("Compiled context requires a typed request and explicit prompt version.")
        if self.prompt_version not in (1, 2) or not isinstance(self.ddl, str) or not self.ddl:
            raise ConfigurationError("Compiled context requires a supported version and physical DDL.")
        if not isinstance(self.semantic_text, str):
            raise ConfigurationError("Compiled semantic context must be text.")
        if ":as_of_date" in self.semantic_text.casefold():
            raise ConfigurationError("Semantic date parameters must be bound before prompt assembly.")
        if self.prompt_version == 1 and (self.semantic_text or self.semantic_catalog_sha256 is not None):
            raise ConfigurationError("E2 version 1 cannot acquire semantic definitions.")
        for value, label in (
            (self.ddl_sha256, "emitted DDL fingerprint"),
            (self.semantic_sha256, "emitted semantic fingerprint"),
            (self.policy_sha256, "policy fingerprint"),
        ):
            _require_digest(value, label=label)
        if self.semantic_catalog_sha256 is not None:
            _require_digest(self.semantic_catalog_sha256, label="catalog source fingerprint")
        if sha256_context(self.ddl) != self.ddl_sha256 or sha256_context(self.semantic_text) != self.semantic_sha256:
            raise ConfigurationError("Context fingerprints do not describe the exact supplied text.")


def _require_request(request: InputRequest, matrix: PolicyMatrix) -> None:
    if type(request) is not InputRequest or type(matrix) is not PolicyMatrix:
        raise ConfigurationError("Context requires a typed input request and loaded access matrix.")
    if request.persona.login_role != matrix.role(request.persona.business_role).login_role:
        raise ConfigurationError("Context persona and matrix login bindings differ.")


def build_context(
    request: InputRequest, snapshot: SchemaSnapshot,
    catalog: SemanticCatalog, matrix: PolicyMatrix,
    *, snapshot_kind: SnapshotKind = SnapshotKind.FULL,
    semantic_snapshot: SchemaSnapshot | None = None,
) -> CompiledContext:
    """E5 v2 role-filtered inputs for FULL persona requests only.

    Prompt 4 must complete governed resolution before generation and refuse to
    call its model for CLARIFICATION_REQUIRED. This module supplies context data
    and does not infer meanings from the user's question. When physical metadata
    is already role-filtered, a separate full semantic_snapshot is required for
    whole-catalog schema/policy contract validation; no catalog is read here.
    """
    _require_request(request, matrix)
    if request.mode is not ExecutionMode.FULL:
        raise HarnessSafetyStopError("Persona context accepts only FULL; harness profiles require a separate issued capability.")
    if snapshot_kind is SnapshotKind.ROLE_FILTERED and semantic_snapshot is None:
        raise MissingDependencyError("Full trusted physical metadata is required for semantic contract validation.")
    full_snapshot = snapshot if semantic_snapshot is None else semantic_snapshot
    require_catalog_contract(catalog, full_snapshot, matrix)
    physical = compile_schema(snapshot, matrix, request.persona.business_role, snapshot_kind=snapshot_kind)
    if semantic_snapshot is not None:
        expected_physical = compile_schema(full_snapshot, matrix, request.persona.business_role)
        if physical.snapshot != expected_physical.snapshot:
            raise ConfigurationError("Physical and semantic metadata do not share the same role projection.")
    semantic = compile_semantics(catalog, matrix, full_snapshot, request.persona.business_role, as_of_date=request.as_of_date)
    return CompiledContext(
        request=request, prompt_version=2, ddl=physical.ddl, semantic_text=semantic.text,
        ddl_sha256=physical.sha256, semantic_sha256=semantic.sha256,
        policy_sha256=matrix.sha256, semantic_catalog_sha256=catalog.sha256,
        profile="E5_ROLE_FILTERED",
    )


@dataclass(frozen=True, slots=True)
class HarnessContextRequest:
    """One-use internal receipt; constructing the dataclass grants no authority."""

    request: InputRequest
    prompt_version: int
    policy_sha256: str
    clone_identity: tuple[str, str, str, str, str]
    _issuer: object = field(repr=False, compare=False)
    _nonce: object = field(repr=False, compare=False)


class HarnessContextAuthority:
    """Issue context receipts only after existing live clone/privilege audits.

    Future trusted local harness configuration owns this object. Its issuer seal
    blocks ordinary payload/dataclass construction; it is a process capability,
    not user authentication or protection from arbitrary malicious Python code.
    No config flag, administrator source or ordinary business source substitutes
    for exact EvaluationConnectionSource and actual clone provenance/audits.
    Nothing performs those audits on import or authority construction.
    """

    def __init__(self, source: EvaluationConnectionSource) -> None:
        if type(source) is not EvaluationConnectionSource:
            raise ConfigurationError("Harness context requires the separate audited evaluation source.")
        self._source = source
        self._seal = object()
        self._issued: dict[object, HarnessContextRequest] = {}
        self._lock = Lock()

    def _identity(self) -> tuple[str, str, str, str, str]:
        provenance = self._source.provenance
        return (
            self._source.clone_alias, provenance.clone_database, provenance.clone_token,
            provenance.fixture_dump_sha256, provenance.policy_state_sha256,
        )

    def _require_open(self) -> None:
        source = self._source
        if (
            source._closed or not source.config.isolation.evaluation_enabled
            or source.config.isolation.evaluation_connection_alias != source.clone_alias
        ):
            raise HarnessSafetyStopError("The separate isolated context harness is unavailable.")

    def issue(self, request: InputRequest, *, prompt_version: int) -> HarnessContextRequest:
        """Explicit future audit boundary; never invoked in this source assignment.

        Opens an audited SELECT-only lease on the real disposable clone using the
        existing Prompt 2 source. The lease submits no candidate SQL. Source-owned
        metadata audits establish clone identity and effective least privilege.
        """
        self._require_open()
        _require_request(request, self._source.matrix)
        if type(prompt_version) is not int or (
            prompt_version == 1 and request.mode is not ExecutionMode.UNCONTROLLED
        ) or (
            prompt_version == 2 and request.mode not in {
                ExecutionMode.FULL, ExecutionMode.NO_PROMPT_FILTER, ExecutionMode.NO_VALIDATOR,
            }
        ) or prompt_version not in (1, 2):
            raise HarnessSafetyStopError("The requested harness context profile is not explicitly defined.")
        selected = self._source.personas.resolve(request.persona)
        resolved_request = replace(request, persona=selected)
        identity = self._identity()
        policy_digest = self._source.matrix.sha256
        with self._source.connection(persona=None if prompt_version == 1 else selected):
            pass
        if identity != self._identity() or policy_digest != self._source.matrix.sha256:
            raise HarnessSafetyStopError("Harness provenance changed during the context audit.")
        receipt = HarnessContextRequest(
            resolved_request, prompt_version, policy_digest, identity, self._seal, object(),
        )
        with self._lock:
            self._issued[receipt._nonce] = receipt
        return receipt

    def _consume(self, receipt: HarnessContextRequest, matrix: PolicyMatrix) -> InputRequest:
        self._require_open()
        if type(receipt) is not HarnessContextRequest:
            raise HarnessSafetyStopError("An issued harness context receipt is required.")
        with self._lock:
            issued = self._issued.pop(receipt._nonce, None)
        if (
            issued is not receipt or receipt._issuer is not self._seal
            or receipt.clone_identity != self._identity()
            or receipt.policy_sha256 != self._source.matrix.sha256
            or receipt.policy_sha256 != matrix.sha256
            or self._source.personas.resolve(receipt.request.persona) != receipt.request.persona
        ):
            raise HarnessSafetyStopError("Harness context receipt is stale, foreign, altered or consumed.")
        return receipt.request

    def discard(self, receipt: HarnessContextRequest) -> None:
        """Release an unused context receipt when a later pipeline step stops."""
        if type(receipt) is not HarnessContextRequest or receipt._issuer is not self._seal:
            raise HarnessSafetyStopError("The unused harness context receipt has a foreign issuer.")
        with self._lock:
            if self._issued.get(receipt._nonce) is receipt:
                del self._issued[receipt._nonce]


def build_harness_context(
    authority: HarnessContextAuthority, receipt: HarnessContextRequest,
    snapshot: SchemaSnapshot, matrix: PolicyMatrix,
    *, catalog: SemanticCatalog | None = None,
    baseline: FrozenBaselineDDL | None = None,
) -> CompiledContext:
    """Consume a clone-bound capability and compile supplied harness metadata.

    v1 UNCONTROLLED: frozen original full DDL, no semantic block, E2 unchanged.
    v2 FULL / NO_VALIDATOR: role-filtered physical and semantic definitions.
    v2 NO_PROMPT_FILTER: full physical/semantic context, the declared context
    ablation. Other version/mode combinations fail closed. Full semantics must
    come from governed definitions, never held-out questions or expected rows.
    Prompt assembly and execution safety remain separate later owners.
    """
    if type(authority) is not HarnessContextAuthority:
        raise HarnessSafetyStopError("Harness context requires its separate authority object.")
    request = authority._consume(receipt, matrix)
    _require_request(request, matrix)
    if receipt.prompt_version == 1:
        if type(snapshot) is not SchemaSnapshot or snapshot.schema != matrix.schema:
            raise ConfigurationError("The E2 baseline requires full typed application metadata.")
        require_policy_schema(matrix, snapshot.columns_by_table)
        if request.mode is not ExecutionMode.UNCONTROLLED:
            raise HarnessSafetyStopError("The E2 baseline is an isolated UNCONTROLLED harness profile.")
        if type(baseline) is not FrozenBaselineDDL:
            raise MissingDependencyError("Original frozen E2 full-schema bytes and recorded digest are required.")
        if catalog is not None:
            raise ConfigurationError("E2 version 1 accepts no semantic catalog input.")
        return CompiledContext(
            request=request, prompt_version=1, ddl=baseline.text, semantic_text="",
            ddl_sha256=baseline.recorded_sha256, semantic_sha256=sha256_context(""),
            policy_sha256=matrix.sha256, semantic_catalog_sha256=None,
            profile="E2_FROZEN_BASELINE",
        )
    if baseline is not None:
        raise ConfigurationError("Frozen E2 baseline input belongs only to prompt version 1.")
    if type(catalog) is not SemanticCatalog:
        raise MissingDependencyError("The governed semantic catalog is required for E5 contexts.")
    require_catalog_contract(catalog, snapshot, matrix)
    if request.mode is ExecutionMode.NO_PROMPT_FILTER:
        physical = compile_full_schema(snapshot, matrix)
        semantic = compile_full_semantics(catalog, matrix, as_of_date=request.as_of_date)
        profile = "E5_NO_PROMPT_FILTER"
    elif request.mode in {ExecutionMode.FULL, ExecutionMode.NO_VALIDATOR}:
        physical = compile_schema(snapshot, matrix, request.persona.business_role)
        semantic = compile_semantics(catalog, matrix, snapshot, request.persona.business_role, as_of_date=request.as_of_date)
        profile = "E5_ROLE_FILTERED"
    else:
        raise HarnessSafetyStopError("The requested E5 harness context profile is undefined.")
    return CompiledContext(
        request=request, prompt_version=2, ddl=physical.ddl, semantic_text=semantic.text,
        ddl_sha256=physical.sha256, semantic_sha256=semantic.sha256,
        policy_sha256=matrix.sha256, semantic_catalog_sha256=catalog.sha256, profile=profile,
    )
