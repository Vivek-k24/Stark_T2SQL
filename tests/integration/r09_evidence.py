"""Offline validation of redacted R09 evidence, never execution permission.

Trust inputs must be supplied independently of the public manifest. Approved
hash pins bind bytes after owner/reviewer approval; they are NOT signatures or
proof that a human approved anything. No default trust store or live adapter is
provided. This module has no file loading, process, network or database calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Mapping
from urllib.parse import urlsplit

from stark_t2sql.utils.local_only import LoopbackEndpoint, require_allowed_url


STATUSES = frozenset({"PASSED_LIVE", "PASSED_OFFLINE", "BLOCKED", "FAILED", "NOT_RUN"})
ITEM_FIELDS = frozenset({
    "criterion_id", "requirement", "environment_id", "mode", "git_commit",
    "artifact_set_sha256", "matrix_sha256", "procedure_reference", "status", "executed_at",
    "observation_reference", "evidence_sha256", "reviewer_reference",
    "authorization_reference", "scope", "unresolved_prerequisites",
})
_TOKEN = re.compile(r"[A-Z][A-Z0-9_-]{0,95}")
_HASH = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
FROZEN_ARTIFACTS = frozenset({"schema", "seed", "fixture_manifest", "fixture_dump", "policy", "catalog", "template", "frd"})
CRITERION_IDS = frozenset(f"R09-{phase}{number:02d}" for phase, count in (("A", 4), ("B", 5), ("C", 8), ("D", 10), ("E", 2), ("F", 2)) for number in range(1, count + 1))


class EvidenceBlocked(ValueError):
    """Invalid or unverified metadata cannot establish acceptance."""


def canonical_digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvidenceBlocked(code)  # Static code only; never echo private input.


def _exact(value: object, keys: set | frozenset, code: str) -> None:
    _require(type(value) is dict and set(value) == keys, code)


def _token(value: object) -> bool:
    return type(value) is str and _TOKEN.fullmatch(value) is not None


def _digest(value: object) -> bool:
    return type(value) is str and _HASH.fullmatch(value) is not None


def load_json_bytes(payload: bytes) -> dict:
    """Explicit bounded parsing only; reject duplicate keys and nonfinite JSON."""
    _require(type(payload) is bytes and len(payload) <= 1_048_576, "EVIDENCE_BYTE_BOUND")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    def invalid_constant(value):
        raise EvidenceBlocked("NONFINITE_JSON")
    try:
        result = json.loads(payload.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceBlocked("MALFORMED_JSON") from error
    _require(type(result) is dict, "JSON_OBJECT_REQUIRED")
    return result


def persona_logins(matrix) -> dict[str, dict[str, str]]:
    """Public role names from actual policy metadata, not credentials/principals."""
    roles = {"payroll": "app_payroll", "hr_1": "app_hr_bp", "hr_2": "app_hr_bp", "sales": "app_sales_mgr"}
    return {name: {"business_role": role, "login_role": matrix.role(role).login_role} for name, role in roles.items()}


def check_endpoints(observed: Mapping[str, str], approved: Mapping[str, LoopbackEndpoint]) -> None:
    _require(set(observed) == set(approved) and bool(observed), "ENDPOINT_SET_MISMATCH")
    for name, url in observed.items():
        _require(name in {"model", "postgres", "ui"}, "UNKNOWN_SERVICE")
        endpoint = approved[name]
        _require(type(endpoint) is LoopbackEndpoint, "EXACT_ENDPOINT_REQUIRED")
        try:
            canonical = require_allowed_url(url, allowed_endpoints=(endpoint,))
            parsed = urlsplit(canonical)
        except Exception as error:
            raise EvidenceBlocked("UNSAFE_ENDPOINT") from error
        scheme = "postgresql" if name == "postgres" else "http"
        _require(parsed.scheme == scheme and parsed.hostname in {"127.0.0.1", "::1"}
                 and parsed.path in {"", "/"} and not parsed.query, "UNSAFE_ENDPOINT")


def check_clone(observation: dict, fixture_digest: str) -> None:
    """Check recorded catalog metadata; this does not query or certify a clone."""
    _exact(observation, {"source_oid", "clone_oid", "source_database", "clone_database", "marker"}, "CLONE_OBSERVATION_FIELDS")
    source_oid, clone_oid = observation["source_oid"], observation["clone_oid"]
    _require(type(source_oid) is int and type(clone_oid) is int and 0 < source_oid != clone_oid > 0, "CLONE_OIDS")
    source, clone = observation["source_database"], observation["clone_database"]
    _require(type(source) is str and type(clone) is str and bool(source) and bool(clone) and source != clone, "CLONE_NAMES")
    marker = observation["marker"]
    _exact(marker, {"kind", "clone_token", "source_database", "source_database_oid", "clone_database_oid", "fixture_dump_sha256"}, "CLONE_MARKER_FIELDS")
    _require(marker["kind"] == "stark_disposable_evaluation_clone" and type(marker["clone_token"]) is str
             and re.fullmatch(r"[A-Za-z0-9_-]{16,128}", marker["clone_token"]) is not None, "CLONE_MARKER")
    _require(type(marker["source_database_oid"]) is int and type(marker["clone_database_oid"]) is int
             and marker["source_database_oid"] == source_oid and marker["clone_database_oid"] == clone_oid
             and marker["source_database"] == source and marker["fixture_dump_sha256"] == fixture_digest, "CLONE_BINDING")


@dataclass(frozen=True)
class VerificationInputs:
    """Owner-composed private inputs, never populated from the manifest itself.

    Evidence/receipt/authorization bytes may only be supplied after independent
    collection and review. Separate approved pin sets must arrive out of band.
    Constructing this Python value is not approval and cannot grant execution.
    """
    git_commit: str
    artifacts: Mapping[str, str]
    persona_logins: Mapping[str, dict]
    evidence: Mapping[str, bytes] = field(default_factory=dict, repr=False)
    receipts: Mapping[str, bytes] = field(default_factory=dict, repr=False)
    approved_receipt_sha256: frozenset[str] = frozenset()
    authorizations: Mapping[str, bytes] = field(default_factory=dict, repr=False)
    approved_authorization_sha256: frozenset[str] = frozenset()
    endpoints: Mapping[str, str] = field(default_factory=dict)
    approved_endpoints: Mapping[str, LoopbackEndpoint] = field(default_factory=dict)
    clone_observation: dict | None = field(default=None, repr=False)


def _executed_item(item: dict, criterion: dict, trust: VerificationInputs | None, artifacts: dict) -> None:
    _require(type(trust) is VerificationInputs, "INDEPENDENT_VERIFICATION_INPUTS_MISSING")
    _require(set(criterion["required_artifacts"]) <= set(artifacts), "REQUIRED_RUNTIME_ARTIFACTS_MISSING")
    _require(trust.git_commit == item["git_commit"] and dict(trust.artifacts) == artifacts, "REVIEWED_INPUT_DRIFT")
    for key in ("observation_reference", "reviewer_reference"):
        _require(_token(item[key]), "EXECUTION_PROVENANCE_MISSING")
    _require(_digest(item["evidence_sha256"]), "EVIDENCE_DIGEST_MISSING")
    try:
        stamp = item["executed_at"]
        _require(type(stamp) is str and stamp.endswith("Z"), "UTC_TIMESTAMP_REQUIRED")
        observed_at = datetime.fromisoformat(stamp[:-1] + "+00:00")
        _require(observed_at <= datetime.now(timezone.utc), "FUTURE_EXECUTION_TIMESTAMP")
    except (TypeError, ValueError) as error:
        raise EvidenceBlocked("UTC_TIMESTAMP_REQUIRED") from error
    reference = item["observation_reference"]
    evidence = trust.evidence.get(reference)
    _require(type(evidence) is bytes and len(evidence) <= 1_048_576
             and sha256(evidence).hexdigest() == item["evidence_sha256"], "EVIDENCE_HASH_MISMATCH")
    receipt_bytes = trust.receipts.get(reference)
    _require(type(receipt_bytes) is bytes and sha256(receipt_bytes).hexdigest() in trust.approved_receipt_sha256, "INDEPENDENT_REVIEW_PIN_MISSING")
    receipt = load_json_bytes(receipt_bytes)
    expected = {"kind": "R09_REVIEWED_EXECUTION_V1", "item_sha256": canonical_digest(item),
                "evidence_sha256": item["evidence_sha256"], "reviewer_reference": item["reviewer_reference"],
                "authorization_reference": item["authorization_reference"]}
    _require(receipt == expected, "REVIEW_RECEIPT_BINDING_MISMATCH")
    if item["status"] == "PASSED_LIVE":
        auth_reference = item["authorization_reference"]
        _require(_token(auth_reference), "OWNER_AUTHORIZATION_MISSING")
        auth_bytes = trust.authorizations.get(auth_reference)
        _require(type(auth_bytes) is bytes and sha256(auth_bytes).hexdigest() in trust.approved_authorization_sha256, "OWNER_AUTHORIZATION_PIN_MISSING")
        auth = load_json_bytes(auth_bytes)
        expected_auth = {"kind": "R09_OWNER_AUTHORIZATION_V1", "authorization_reference": auth_reference,
                         **{key: item[key] for key in ("criterion_id", "environment_id", "mode", "git_commit", "scope", "artifact_set_sha256", "matrix_sha256")},
                         "endpoints_sha256": canonical_digest(dict(trust.endpoints)),
                         "operation": criterion["operation"]}
        _require(auth == expected_auth, "OWNER_AUTHORIZATION_SCOPE_MISMATCH")
        if criterion["phase"] in {"B", "C", "D", "E"}:
            check_endpoints(trust.endpoints, trust.approved_endpoints)
            needed = {"B": "model", "C": "postgres", "D": "postgres", "E": "ui"}[criterion["phase"]]
            _require(needed in trust.endpoints, "SERVICE_ENDPOINT_MISSING")
        if criterion["phase"] in {"C", "D"}:
            _require(trust.clone_observation is not None, "CLONE_OBSERVATION_MISSING")
            check_clone(trust.clone_observation, artifacts["fixture_dump"])
            _require(canonical_digest(trust.clone_observation) == artifacts.get("CLONE_CATALOG"), "CLONE_OBSERVATION_HASH_MISMATCH")


def validate_manifest(manifest: dict, matrix: dict, *, expected_commit: str,
                      expected_artifacts: dict, expected_personas: dict,
                      trust: VerificationInputs | None = None) -> dict[str, str]:
    """Return criterion statuses after validation; never start any live action."""
    _exact(matrix, {"schema_version", "criteria"}, "MATRIX_FIELDS")
    _require(matrix["schema_version"] == "stark-r09-matrix-v1" and type(matrix["criteria"]) is list, "MATRIX_VERSION")
    row_fields = {"id", "phase", "requirement", "environment_id", "mode", "required_status", "operation", "required_artifacts",
                  "scope", "procedure_reference", "mandatory", "go", "no_go"}
    for row in matrix["criteria"]:
        _exact(row, row_fields, "MATRIX_CRITERION_FIELDS")
        _require(type(row["id"]) is str and row["id"] in CRITERION_IDS and row["mandatory"] is True
                 and row["phase"] == row["id"][4] and row["procedure_reference"] == "R09_PHASE_" + row["phase"], "MANDATORY_MATRIX_SCOPE")
        required_status = "PASSED_OFFLINE" if row["id"] in {"R09-A01", "R09-A04"} else "PASSED_LIVE"
        _require(row["required_status"] == required_status and type(row["required_artifacts"]) is list
                 and all(_token(name) for name in row["required_artifacts"]), "MATRIX_EVIDENCE_LEVEL")
    _exact(manifest, {"schema_version", "git_commit", "artifacts", "persona_logins", "items", "production_promotion"}, "MANIFEST_FIELDS")
    _require(manifest["schema_version"] == "stark-r09-evidence-v1", "MANIFEST_VERSION")
    _require(type(expected_commit) is str and _COMMIT.fullmatch(expected_commit) is not None
             and manifest["git_commit"] == expected_commit, "COMMIT_MISMATCH")
    _require(type(expected_artifacts) is dict and bool(expected_artifacts)
             and all(_token(key) or key in {"schema", "seed", "fixture_manifest", "fixture_dump", "policy", "catalog", "template", "frd"} for key in expected_artifacts)
             and all(_digest(value) for value in expected_artifacts.values()), "ARTIFACT_DIGESTS")
    _require(FROZEN_ARTIFACTS <= set(expected_artifacts), "FROZEN_ARTIFACTS_MISSING")
    _require(manifest["artifacts"] == expected_artifacts, "ARTIFACT_HASH_MISMATCH")
    _require(manifest["persona_logins"] == expected_personas and set(expected_personas) == {"payroll", "hr_1", "hr_2", "sales"}, "PERSONA_LOGIN_MISMATCH")
    if trust is not None:
        _require(dict(trust.persona_logins) == expected_personas, "OBSERVED_PERSONA_MISMATCH")
    _require(manifest["production_promotion"] == "NOT_APPROVED", "PROMOTION_NOT_AUTHORIZED_BY_MANIFEST")
    criteria = {row["id"]: row for row in matrix["criteria"]}
    _require(len(criteria) == len(matrix["criteria"]), "DUPLICATE_CRITERION_ID")
    _require(set(criteria) == CRITERION_IDS, "MANDATORY_MATRIX_INCOMPLETE")
    _require(type(manifest["items"]) is list, "ITEMS_REQUIRED")
    statuses = {}
    for item in manifest["items"]:
        _exact(item, ITEM_FIELDS, "ITEM_FIELDS")
        identity = item["criterion_id"]
        _require(type(identity) is str and identity in criteria and identity not in statuses, "DUPLICATE_OR_UNKNOWN_EVIDENCE_ID")
        criterion = criteria[identity]
        expected = {"requirement": criterion["requirement"], "environment_id": criterion["environment_id"],
                    "mode": criterion["mode"], "git_commit": expected_commit, "artifact_set_sha256": canonical_digest(expected_artifacts),
                    "matrix_sha256": canonical_digest(matrix),
                    "procedure_reference": criterion["procedure_reference"], "scope": criterion["scope"]}
        _require(all(item[key] == value for key, value in expected.items()), "CRITERION_BINDING_MISMATCH")
        _require(type(item["status"]) is str and item["status"] in STATUSES, "DISALLOWED_STATUS")
        pending = item["unresolved_prerequisites"]
        _require(item["authorization_reference"] is None or _token(item["authorization_reference"]), "AUTHORIZATION_REFERENCE_FORMAT")
        _require(type(pending) is list and all(_token(value) for value in pending) and len(set(pending)) == len(pending), "PREREQUISITE_CODES_REQUIRED")
        if item["status"] in {"NOT_RUN", "BLOCKED"}:
            _require(bool(pending), "UNEXECUTED_PREREQUISITES_MISSING")
            _require(all(item[key] is None for key in ("executed_at", "observation_reference", "evidence_sha256", "reviewer_reference", "authorization_reference")), "FABRICATED_UNEXECUTED_EVIDENCE")
        else:
            if item["status"].startswith("PASSED"):
                _require(not pending and (item["status"] == criterion["required_status"]), "PASS_SCOPE_MISMATCH")
            _executed_item(item, criterion, trust, expected_artifacts)
        statuses[identity] = item["status"]
    _require(set(statuses) == set(criteria), "INCOMPLETE_ACCEPTANCE_MATRIX")
    return statuses


def readiness(manifest: dict, matrix: dict, **verification_inputs) -> str:
    """Evidence completeness is not a production promotion permission."""
    statuses = validate_manifest(manifest, matrix, **verification_inputs)
    return "EVIDENCE_COMPLETE_AWAITING_OWNER" if all(statuses[row["id"]] == row["required_status"] for row in matrix["criteria"]) else "NO_GO"
