"""Load exact external TUNING payloads after immutable-index guards.

Never call this loader while drafting. The hash index contains metadata only.
Holdout payloads cannot pass read_tuning_payload, even when a caller supplies
their path. No initial case assignment, question dataset or reference answer is
materialized in this source. Separate actual projection review is required for
cursor labels; matching model aliases alone cannot produce an approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
import json
from typing import Callable

from stark_t2sql.contracts import ExpectedOutcome
from stark_t2sql.evaluation.cases import Case, CaseSet
from stark_t2sql.evaluation.comparator import ApprovedColumnMapping
from stark_t2sql.evaluation.holdout import FrozenCaseIndex, FrozenCaseMetadata, read_tuning_payload
from stark_t2sql.utils.fingerprints import sha256_bytes


@dataclass(frozen=True, slots=True)
class LoadedCase:
    case: Case
    payload_sha256: str
    column_approval: ApprovedColumnMapping | None = None


def _cell(raw):
    if isinstance(raw, dict) and set(raw) == {"decimal"}:
        return Decimal(raw["decimal"])
    if raw is None or type(raw) in {str,int,bool,float}:
        return raw
    raise ValueError("External case scalar is not supported")


def parse_case_payload(payload: bytes, *, expected_set: CaseSet, expected_id: str) -> LoadedCase:
    raw = json.loads(payload.decode("utf-8"))
    if not isinstance(raw,dict): raise ValueError("A case payload must be an object")
    allowed = {"id","set","persona","as_of_date","expected_outcome","question","sql","reference_sql","category",
        "forbidden_values","notes","forbidden_values_fixture_sha256","requires_forbidden_values","column_approval"}
    if set(raw)-allowed: raise ValueError("External case fields are outside the governed contract")
    if raw.get("id") != expected_id or CaseSet(raw.get("set")) is not expected_set:
        raise ValueError("Payload ID/set differs from its immutable index and selected suite")
    approval_raw = raw.pop("column_approval",None)
    if approval_raw is not None:
        approval_required={"reference_identities","candidate_identities","candidate_to_reference","review_reference"}
        if not isinstance(approval_raw,dict) or not approval_required<=set(approval_raw) or set(approval_raw)-approval_required-{"candidate_sql_sha256","reference_sql_sha256"}:
            raise ValueError("Actual projection review requires exact governed fields")
        approval = ApprovedColumnMapping(**approval_raw)
    else: approval = None
    raw["set"] = expected_set
    raw["as_of_date"] = date.fromisoformat(raw["as_of_date"])
    raw["expected_outcome"] = ExpectedOutcome(raw["expected_outcome"])
    raw["forbidden_values"] = tuple(_cell(value) for value in raw.get("forbidden_values",()))
    raw["notes"] = tuple(raw.get("notes",()))
    return LoadedCase(Case(**raw),sha256_bytes(payload),approval)


def load_tuning_cases(index: FrozenCaseIndex, case_ids: tuple[str,...], *, expected_set: CaseSet,
                      loader: Callable[[FrozenCaseMetadata],bytes]) -> tuple[LoadedCase,...]:
    """Guard partition before the supplied local reader can see payload bytes."""
    if len(set(case_ids)) != len(case_ids): raise ValueError("Duplicate selected case IDs")
    return tuple(parse_case_payload(read_tuning_payload(index,case_id,loader=loader),
        expected_set=expected_set,expected_id=case_id) for case_id in case_ids)


def local_payload_reader(root: Path, paths_by_id: dict[str,Path]) -> Callable[[FrozenCaseMetadata],bytes]:
    workspace = Path(root).resolve()
    def read(metadata: FrozenCaseMetadata) -> bytes:
        path = Path(paths_by_id[metadata.id]).resolve()
        if not path.is_relative_to(workspace): raise ValueError("Case payload must remain inside the workspace")
        with path.open("rb") as stream: payload=stream.read(1_048_577)
        if len(payload)>1_048_576: raise ValueError("External case exceeds source-defined size bound")
        return payload
    return read


def load_accuracy(index: FrozenCaseIndex, case_ids: tuple[str,...], *, loader) -> tuple[LoadedCase,...]:
    return load_tuning_cases(index,case_ids,expected_set=CaseSet.ACCURACY,loader=loader)
