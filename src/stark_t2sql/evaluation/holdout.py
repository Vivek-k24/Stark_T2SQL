"""Metadata-only immutable splitting and opaque epic-boundary holdout access.

No dataset is bundled. No payload is read at import, during assignment, or by
the tuning iterator. A future restricted evaluator must supply the external
frozen index, boundary authorization, and an exposure recorder before bytes
can be read. Held-out payloads never enter Codex context, tuning, examples,
persona UI, or additional prompt context. Only the current case's question may
reach the assessed local SQL model under an explicitly authorized sealed run;
reference SQL, expected answers, and other held-out cases never reach it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from threading import Lock
from types import MappingProxyType
from typing import Callable, Mapping

from .cases import require_sha256


SPLIT_VERSION = "fr9-case-id-sha256-v1"


class CasePartition(str, Enum):
    TUNING = "TUNING"
    HOLDOUT = "HOLDOUT"


def split_for_id(case_id: str) -> CasePartition:
    """The fixed domain and ID establish an immutable, population-free bucket.

The first 64 digest bits are compared with an exact integer 70% threshold.
No existing assignment changes when cases are added; small sets need not have
an exact 70/30 count. IDs are never stripped/case-folded behind the caller.
"""
    if not isinstance(case_id, str) or not case_id.strip() or case_id != case_id.strip():
        raise ValueError("Split requires an immutable nonempty exact case ID")
    digest = sha256((SPLIT_VERSION + "\0" + case_id).encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big")
    return CasePartition.TUNING if bucket * 10 < (1 << 64) * 7 else CasePartition.HOLDOUT


@dataclass(frozen=True, slots=True)
class FrozenCaseMetadata:
    id: str
    partition: CasePartition
    payload_sha256: str

    def __post_init__(self) -> None:
        if type(self.partition) is not CasePartition or split_for_id(self.id) is not self.partition:
            raise ValueError("Frozen assignment must equal the immutable ID hash bucket")
        require_sha256(self.payload_sha256, "Actual external case payload")


@dataclass(frozen=True, slots=True)
class FrozenCaseIndex:
    entries: tuple[FrozenCaseMetadata, ...]
    freeze_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))
        if any(type(entry) is not FrozenCaseMetadata for entry in self.entries):
            raise TypeError("The frozen index contains metadata only")
        if len({entry.id for entry in self.entries}) != len(self.entries):
            raise ValueError("Frozen case IDs must be unique")
        if not isinstance(self.freeze_reference, str) or not self.freeze_reference.strip():
            raise ValueError("Actual case-set freeze evidence is required")

    @property
    def by_id(self) -> Mapping[str, FrozenCaseMetadata]:
        return MappingProxyType({entry.id: entry for entry in self.entries})

    @property
    def sha256(self) -> str:
        payload = [{"id": entry.id, "partition": entry.partition.value, "payload_sha256": entry.payload_sha256} for entry in sorted(self.entries, key=lambda entry: entry.id)]
        return sha256(json.dumps({"split_version": SPLIT_VERSION, "entries": payload}, separators=(",", ":"), sort_keys=True).encode("utf-8")).hexdigest()

    def extend(self, additions: tuple[FrozenCaseMetadata, ...], *, freeze_reference: str) -> FrozenCaseIndex:
        """Append IDs without replacing, reassigning, or rewriting old cases."""
        if any(entry.id in self.by_id for entry in additions):
            raise ValueError("An existing frozen case cannot be replaced; regressions require new immutable IDs")
        return FrozenCaseIndex(self.entries + tuple(additions), freeze_reference)


@dataclass(frozen=True, slots=True)
class HoldoutExposure:
    run_id: str
    epic: str
    case_id: str | None
    index_sha256: str
    authorization_reference: str
    event: str


_BOUNDARY_METADATA_SEAL = object()


def _metadata_bytes(payload: bytes, recorded_sha256: str, label: str) -> dict:
    require_sha256(recorded_sha256, label)
    if type(payload) is not bytes or sha256(payload).hexdigest() != recorded_sha256:
        raise ValueError("Actual boundary metadata bytes differ from the recorded digest")
    try:
        values = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Actual boundary metadata must be a single UTF-8 JSON object") from exc
    if type(values) is not dict:
        raise ValueError("Boundary metadata must be an object, never a case payload")
    return values


@dataclass(frozen=True, slots=True)
class PriorE8Exposure:
    """Actual completed E8 exposure metadata, created only from recorded bytes.

The referenced record may belong to an earlier index before immutable case
additions. The subsequent schedule separately binds the current index and this
exact historical record. No questions, reference SQL, or answers are accepted.
"""

    run_id: str
    index_sha256: str
    exposure_reference: str
    record_sha256: str
    _provenance_seal: object = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def from_bytes(cls, record_bytes: bytes, *, exposure_reference: str, recorded_sha256: str) -> PriorE8Exposure:
        values = _metadata_bytes(record_bytes, recorded_sha256, "Actual prior E8 exposure record")
        required = {"run_id", "epic", "case_id", "index_sha256", "authorization_reference", "event"}
        if set(values) not in (required, required | {"record_type"}):
            raise ValueError("Prior E8 exposure must contain only the recorded exposure metadata fields")
        if "record_type" in values and values["record_type"] != "HOLDOUT_EXPOSURE":
            raise ValueError("The prior reference must be an actual holdout exposure record")
        if values["epic"] != "E8" or values["event"] != "BOUNDARY_END" or values["case_id"] is not None:
            raise ValueError("Subsequent exposure requires an actual completed initial E8 boundary")
        for text in (values["run_id"], values["authorization_reference"], exposure_reference):
            if not isinstance(text, str) or not text.strip():
                raise ValueError("The prior E8 run, authorization and actual record reference are required")
        require_sha256(values["index_sha256"], "Prior E8 frozen-index record")
        evidence = cls(values["run_id"], values["index_sha256"], exposure_reference, recorded_sha256)
        object.__setattr__(evidence, "_provenance_seal", _BOUNDARY_METADATA_SEAL)
        return evidence


@dataclass(frozen=True, slots=True)
class DefinedBoundarySchedule:
    """Actual owner-defined later epic schedule; no default schedule is invented.

The required external metadata has version 'fr9-holdout-boundaries-v1',
defined_epics, index_sha256, prior_e8_exposure_reference, and
prior_e8_record_sha256. Construction opens no file; from_bytes binds bytes
that a separately authorized owner composition has actually read.
"""

    defined_epics: tuple[str, ...]
    index_sha256: str
    prior_e8_exposure_reference: str
    prior_e8_record_sha256: str
    schedule_reference: str
    schedule_sha256: str
    _provenance_seal: object = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def from_bytes(cls, schedule_bytes: bytes, *, schedule_reference: str, recorded_sha256: str) -> DefinedBoundarySchedule:
        values = _metadata_bytes(schedule_bytes, recorded_sha256, "Actual later boundary schedule")
        if set(values) != {"version", "defined_epics", "index_sha256", "prior_e8_exposure_reference", "prior_e8_record_sha256"} or values["version"] != "fr9-holdout-boundaries-v1":
            raise ValueError("The actual owner schedule must use the defined metadata-only boundary contract")
        epics = values["defined_epics"]
        if type(epics) is not list or not epics or any(not isinstance(epic, str) or not epic.startswith("E") or not epic[1:].isdigit() for epic in epics) or len(set(epics)) != len(epics):
            raise ValueError("The owner must define unique actual epic boundaries explicitly")
        for text in (schedule_reference, values["prior_e8_exposure_reference"]):
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Actual schedule and prior E8 record references are required")
        require_sha256(values["index_sha256"], "Scheduled current frozen index")
        require_sha256(values["prior_e8_record_sha256"], "Scheduled actual prior E8 exposure")
        schedule = cls(tuple(epics), values["index_sha256"], values["prior_e8_exposure_reference"], values["prior_e8_record_sha256"], schedule_reference, recorded_sha256)
        object.__setattr__(schedule, "_provenance_seal", _BOUNDARY_METADATA_SEAL)
        return schedule


_PERMIT_SEAL = object()


class HoldoutPermit:
    """Process-local capability; no payload, serializer, or prompt interface."""

    __slots__ = ("_owner", "_epic", "_run_id", "_authorization", "_index", "_consumed", "_closed")

    def __init__(self, seal: object, owner: object, epic: str, run_id: str, authorization: str, index: FrozenCaseIndex) -> None:
        if seal is not _PERMIT_SEAL:
            raise TypeError("Only the restricted boundary authority can issue holdout permits")
        self._owner = owner
        self._epic = epic
        self._run_id = run_id
        self._authorization = authorization
        self._index = index
        self._consumed: set[str] = set()
        self._closed = False

    def __repr__(self) -> str:
        return "<HoldoutPermit: opaque restricted evaluation capability>"


class HoldoutAuthority:
    """Not an application/UI dependency: only restricted future evaluation."""

    def __init__(
        self, index: FrozenCaseIndex, *, record_exposure: Callable[[HoldoutExposure], None],
        prior_e8_exposure: PriorE8Exposure | None = None,
        boundary_schedule: DefinedBoundarySchedule | None = None,
    ) -> None:
        if type(index) is not FrozenCaseIndex or not callable(record_exposure):
            raise TypeError("Actual frozen metadata and a durable exposure recorder are required")
        self._index = index
        self._record = record_exposure
        self._lock = Lock()
        self._initial_boundary_started = False
        self._active: HoldoutPermit | None = None
        self._run_ids: set[str] = set()
        self._prior_e8: PriorE8Exposure | None = None
        self._schedule: DefinedBoundarySchedule | None = None
        if prior_e8_exposure is not None or boundary_schedule is not None:
            self.configure_subsequent_boundaries(prior_e8_exposure=prior_e8_exposure, boundary_schedule=boundary_schedule)

    def configure_subsequent_boundaries(
        self, *, prior_e8_exposure: PriorE8Exposure | None,
        boundary_schedule: DefinedBoundarySchedule | None,
    ) -> None:
        """Bind actual history and owner schedule before any later exposure."""
        with self._lock:
            if self._active is not None:
                raise PermissionError("Boundary metadata cannot change during an active sealed run")
            if type(prior_e8_exposure) is not PriorE8Exposure or type(boundary_schedule) is not DefinedBoundarySchedule:
                raise ValueError("Later boundaries require both actual prior E8 exposure and owner schedule metadata")
            if prior_e8_exposure._provenance_seal is not _BOUNDARY_METADATA_SEAL or boundary_schedule._provenance_seal is not _BOUNDARY_METADATA_SEAL:
                raise ValueError("Boundary evidence must be bound from actual recorded bytes")
            if boundary_schedule.index_sha256 != self._index.sha256:
                raise ValueError("The owner schedule is bound to a different current frozen index")
            if boundary_schedule.prior_e8_exposure_reference != prior_e8_exposure.exposure_reference or boundary_schedule.prior_e8_record_sha256 != prior_e8_exposure.record_sha256:
                raise ValueError("The schedule does not reference the actual supplied prior E8 exposure")
            self._prior_e8, self._schedule = prior_e8_exposure, boundary_schedule
            self._run_ids.add(prior_e8_exposure.run_id)

    def begin_boundary(self, *, epic: str, run_id: str, authorization_reference: str) -> HoldoutPermit:
        """S8.4: first exposure is E8; later exposures require actual scheduled history."""
        if any(not isinstance(value, str) or not value.strip() for value in (run_id, authorization_reference)):
            raise ValueError("An actual run ID and explicit boundary authorization are required")
        with self._lock:
            if self._active is not None or run_id in self._run_ids:
                raise PermissionError("Each sealed boundary requires a new run ID and no active permit")
            if self._prior_e8 is None:
                if self._initial_boundary_started or epic != "E8":
                    raise ValueError("The first sealed exposure must be E8; later boundaries require actual prior E8 and schedule inputs")
            elif self._schedule is None or epic not in self._schedule.defined_epics:
                raise ValueError("This later epic boundary is absent from the actual owner-defined schedule")
            self._record(HoldoutExposure(run_id, epic, None, self._index.sha256, authorization_reference, "BOUNDARY_BEGIN"))
            permit = HoldoutPermit(_PERMIT_SEAL, self, epic, run_id, authorization_reference, self._index)
            self._initial_boundary_started = True
            self._run_ids.add(run_id)
            self._active = permit
            return permit

    def _permit(self, permit: HoldoutPermit) -> None:
        if type(permit) is not HoldoutPermit or permit._owner is not self or permit._index is not self._index or permit._closed or self._active is not permit:
            raise PermissionError("A live permit from this exact frozen-index authority is required")

    def read_payload(self, permit: HoldoutPermit, case_id: str, *, loader: Callable[[FrozenCaseMetadata], bytes]) -> bytes:
        """Record the attempted exposure before opening bytes; require exact hash."""
        with self._lock:
            self._permit(permit)
            entry = self._index.by_id.get(case_id)
            if entry is None or entry.partition is not CasePartition.HOLDOUT:
                raise PermissionError("Holdout reads require an indexed HOLDOUT case ID")
            if case_id in permit._consumed:
                raise PermissionError("Each case exposure requires its own new boundary run")
            if not callable(loader):
                raise TypeError("An explicit external payload loader is required")
            self._record(HoldoutExposure(permit._run_id, permit._epic, case_id, self._index.sha256, permit._authorization, "PAYLOAD_READ_ATTEMPT"))
            permit._consumed.add(case_id)
            payload = loader(entry)
            if type(payload) is not bytes or sha256(payload).hexdigest() != entry.payload_sha256:
                raise ValueError("External holdout payload differs from the immutable frozen content")
            return payload

    def end_boundary(self, permit: HoldoutPermit) -> None:
        with self._lock:
            self._permit(permit)
            self._record(HoldoutExposure(permit._run_id, permit._epic, None, self._index.sha256, permit._authorization, "BOUNDARY_END"))
            permit._closed = True
            self._active = None


def read_tuning_payload(index: FrozenCaseIndex, case_id: str, *, loader: Callable[[FrozenCaseMetadata], bytes]) -> bytes:
    """Guard metadata before opening the external tuning payload."""
    if type(index) is not FrozenCaseIndex:
        raise TypeError("Actual frozen case metadata is required")
    entry = index.by_id.get(case_id)
    if entry is None or entry.partition is not CasePartition.TUNING or split_for_id(case_id) is not CasePartition.TUNING:
        raise PermissionError("A holdout payload cannot be read by the tuning interface")
    payload = loader(entry)
    if type(payload) is not bytes or sha256(payload).hexdigest() != entry.payload_sha256:
        raise ValueError("External tuning payload differs from the immutable frozen content")
    return payload

