"""OFFLINE ONLY: synthetic trust operands are not owner approvals or live runs."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest

from stark_t2sql.utils.local_only import LoopbackEndpoint
from .r09_evidence import (
    EvidenceBlocked, VerificationInputs, canonical_digest, check_clone,
    check_endpoints, load_json_bytes, persona_logins, readiness, validate_manifest,
)


BASELINE = "b926a9c17a83f73800db4a3b8aa0ee03d444743c"
FILES = {"schema": "schema.sql", "seed": "seed_data.py", "fixture_manifest": "fixture_manifest.json",
         "fixture_dump": "fixture_pg_dump.sql", "policy": "policy/access_matrix.yaml",
         "catalog": "semantic/catalog.yaml", "template": "src/inference/prompt_template.txt", "frd": "STARK_T2SQL FRD 1.8.txt"}


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    monkeypatch.setenv("STARK_R09_OFFLINE_ONLY", "1")
    monkeypatch.setenv("STARK_TEST_ENABLE_DB_INTEGRATION", "0")


@pytest.fixture
def preparation(project_root, matrix):
    folder = project_root / "docs/acceptance"
    requirements = load_json_bytes((folder / "R09_ACCEPTANCE_MATRIX.json").read_bytes())
    manifest = load_json_bytes((folder / "R09_EVIDENCE_TEMPLATE.json").read_bytes())
    actual = {name: sha256((project_root / path).read_bytes()).hexdigest() for name, path in FILES.items()}
    kwargs = dict(expected_commit=BASELINE, expected_artifacts=actual, expected_personas=persona_logins(matrix))
    return manifest, requirements, kwargs


def unit_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def unit_clone(fixture_digest):
    """In-memory metadata only. No clone, token or comment is provisioned."""
    return {"source_oid": 101, "clone_oid": 202, "source_database": "unit_source", "clone_database": "unit_clone",
            "marker": {"kind": "stark_disposable_evaluation_clone", "clone_token": "TEST_ONLY_NOT_A_REAL_CLONE",
                       "source_database": "unit_source", "source_database_oid": 101, "clone_database_oid": 202,
                       "fixture_dump_sha256": fixture_digest}}


def unit_reviewed(preparation, identities=("R09-B01",)):
    """Synthetic TEST_ONLY bytes/pins exercise validation, never actual approval.

    Nothing is written to the template, private evidence store or production
    ScopeReviewStore. This helper cannot execute or authorize any live action.
    """
    original, matrix, original_kwargs = preparation
    manifest, kwargs = deepcopy(original), deepcopy(original_kwargs)
    selected = [row for row in matrix["criteria"] if row["id"] in identities]
    for criterion in selected:
        for name in criterion["required_artifacts"]:
            manifest["artifacts"][name] = sha256(("TEST_ONLY synthetic " + name).encode()).hexdigest()
    if "CLONE_CATALOG" in manifest["artifacts"]:
        manifest["artifacts"]["CLONE_CATALOG"] = canonical_digest(unit_clone(manifest["artifacts"]["fixture_dump"]))
    kwargs["expected_artifacts"] = dict(manifest["artifacts"])
    evidence, receipts, authorizations = {}, {}, {}
    endpoints = {"model": "http://127.0.0.1:18081", "postgres": "postgresql://127.0.0.1:15432", "ui": "http://127.0.0.1:18501"}
    for index, item in enumerate(manifest["items"]):
        item["artifact_set_sha256"] = canonical_digest(manifest["artifacts"])
        if item["criterion_id"] not in identities:
            continue
        criterion = next(row for row in selected if row["id"] == item["criterion_id"])
        reference, auth_reference = f"TEST_ONLY_OBSERVATION_{index}", f"TEST_ONLY_AUTH_{index}"
        payload = b'TEST_ONLY redacted synthetic observation, not an executed test or human approval'
        item.update(status=criterion["required_status"], executed_at="2026-01-01T00:00:00Z",
                    observation_reference=reference, evidence_sha256=sha256(payload).hexdigest(),
                    reviewer_reference="TEST_ONLY_REVIEWER", authorization_reference=auth_reference,
                    unresolved_prerequisites=[])
        evidence[reference] = payload
        receipts[reference] = unit_bytes({"kind": "R09_REVIEWED_EXECUTION_V1", "item_sha256": canonical_digest(item),
            "evidence_sha256": item["evidence_sha256"], "reviewer_reference": item["reviewer_reference"],
            "authorization_reference": auth_reference})
        authorizations[auth_reference] = unit_bytes({"kind": "R09_OWNER_AUTHORIZATION_V1", "authorization_reference": auth_reference,
            **{key: item[key] for key in ("criterion_id", "environment_id", "mode", "git_commit", "scope", "artifact_set_sha256", "matrix_sha256")},
            "endpoints_sha256": canonical_digest(endpoints),
            "operation": criterion["operation"]})
    endpoints = {"model": "http://127.0.0.1:18081", "postgres": "postgresql://127.0.0.1:15432", "ui": "http://127.0.0.1:18501"}
    approved = {name: LoopbackEndpoint("postgresql" if name == "postgres" else "http", "127.0.0.1", port)
                for name, port in (("model", 18081), ("postgres", 15432), ("ui", 18501))}
    trust = VerificationInputs(BASELINE, kwargs["expected_artifacts"], kwargs["expected_personas"], evidence=evidence, receipts=receipts,
        approved_receipt_sha256=frozenset(sha256(value).hexdigest() for value in receipts.values()), authorizations=authorizations,
        approved_authorization_sha256=frozenset(sha256(value).hexdigest() for value in authorizations.values()),
        endpoints=endpoints, approved_endpoints=approved, clone_observation=unit_clone(manifest["artifacts"]["fixture_dump"]))
    return manifest, matrix, dict(kwargs, trust=trust)


def test_initial_manifest_has_no_passing_or_executed_acceptance(preparation):
    manifest, matrix, kwargs = preparation
    statuses = validate_manifest(manifest, matrix, **kwargs)
    assert len(statuses) == 31 and set(statuses.values()) == {"NOT_RUN"}
    assert readiness(manifest, matrix, **kwargs) == "NO_GO"
    assert manifest["production_promotion"] == "NOT_APPROVED"


def test_matrix_has_all_phases_modes_and_concrete_go_no_go(preparation):
    _, matrix, _ = preparation
    assert {row["phase"] for row in matrix["criteria"]} == set("ABCDEF")
    assert {row["mode"] for row in matrix["criteria"]} >= {"FULL", "NO_VALIDATOR", "NO_PROMPT_FILTER", "UNCONTROLLED"}
    assert all(row["go"] and row["no_go"] and row["mandatory"] for row in matrix["criteria"])


@pytest.mark.parametrize("status", ("PASS", "GO", "PASSED", "PASSED — LIVE", "SIMULATED", "APPROVED", "", None, True))
def test_unknown_or_ambiguous_status_is_rejected(preparation, status):
    manifest, matrix, kwargs = preparation
    manifest["items"][0]["status"] = status
    with pytest.raises(EvidenceBlocked): validate_manifest(manifest, matrix, **kwargs)


@pytest.mark.parametrize("change", ("duplicate", "missing", "unknown", "requirement", "mode", "scope", "commit", "artifact_set", "procedure"))
def test_evidence_ids_and_exact_requirement_bindings_cannot_drift(preparation, change):
    manifest, matrix, kwargs = preparation
    item = manifest["items"][0]
    if change == "duplicate": manifest["items"].append(deepcopy(item))
    elif change == "missing": manifest["items"].pop()
    elif change == "unknown": item["criterion_id"] = "R09-UNKNOWN"
    else:
        key = {"requirement": "requirement", "mode": "mode", "scope": "scope", "commit": "git_commit",
               "artifact_set": "artifact_set_sha256", "procedure": "procedure_reference"}[change]
        item[key] = "TEST_ONLY_CHANGED"
    with pytest.raises(EvidenceBlocked): validate_manifest(manifest, matrix, **kwargs)


@pytest.mark.parametrize("field", ("raw_output", "question", "reference_sql", "rows", "canaries", "password", "holdout_case_ids"))
def test_public_manifest_cannot_accept_private_payload_fields(preparation, field):
    manifest, matrix, kwargs = preparation
    manifest["items"][0][field] = "PRIVATE_TEST_ONLY_SENTINEL"
    with pytest.raises(EvidenceBlocked) as captured: validate_manifest(manifest, matrix, **kwargs)
    assert "PRIVATE_TEST_ONLY_SENTINEL" not in str(captured.value)


def test_changed_frozen_hash_or_wrong_persona_login_cannot_pass(preparation):
    manifest, matrix, kwargs = preparation
    bad = deepcopy(manifest)
    bad["artifacts"]["schema"] = "0" * 64
    with pytest.raises(EvidenceBlocked): validate_manifest(bad, matrix, **kwargs)
    bad = deepcopy(manifest)
    bad["persona_logins"]["hr_2"]["login_role"] = "app_hr_bp"
    with pytest.raises(EvidenceBlocked): validate_manifest(bad, matrix, **kwargs)
    assert manifest["persona_logins"]["hr_1"] == manifest["persona_logins"]["hr_2"]


def test_status_label_without_independent_proof_never_establishes_live_acceptance(preparation):
    manifest, matrix, kwargs = unit_reviewed(preparation)
    with pytest.raises(EvidenceBlocked): validate_manifest(manifest, matrix, **dict(kwargs, trust=None))
    with pytest.raises(EvidenceBlocked): readiness(manifest, matrix, **dict(kwargs, trust=None))


@pytest.mark.parametrize("missing", ("receipts", "evidence", "approved_receipt_sha256", "authorizations", "approved_authorization_sha256"))
def test_missing_independent_review_or_owner_authorization_is_blocked(preparation, missing):
    manifest, matrix, kwargs = unit_reviewed(preparation)
    kwargs["trust"] = replace(kwargs["trust"], **{missing: frozenset() if missing.startswith("approved") else {}})
    with pytest.raises(EvidenceBlocked): validate_manifest(manifest, matrix, **kwargs)


def test_hash_alone_is_not_owner_authorization(preparation):
    manifest, matrix, kwargs = unit_reviewed(preparation)
    trust = kwargs["trust"]
    kwargs["trust"] = replace(trust, approved_authorization_sha256=frozenset())
    with pytest.raises(EvidenceBlocked): validate_manifest(manifest, matrix, **kwargs)


@pytest.mark.parametrize("kind", ("bytes", "receipt_binding", "auth_scope", "timestamp", "reviewed_commit", "missing_runtime_artifact"))
def test_tampered_execution_provenance_is_blocked(preparation, kind):
    manifest, matrix, kwargs = unit_reviewed(preparation)
    item = next(row for row in manifest["items"] if row["status"] == "PASSED_LIVE")
    trust = kwargs["trust"]
    reference = item["observation_reference"]
    if kind == "bytes": kwargs["trust"] = replace(trust, evidence={reference: b'changed'})
    elif kind == "receipt_binding":
        altered = load_json_bytes(trust.receipts[reference]); altered["item_sha256"] = "0" * 64
        payload = unit_bytes(altered)
        kwargs["trust"] = replace(trust, receipts={reference: payload}, approved_receipt_sha256=frozenset({sha256(payload).hexdigest()}))
    elif kind == "auth_scope":
        authref = item["authorization_reference"]
        altered = load_json_bytes(trust.authorizations[authref]); altered["mode"] = "UNCONTROLLED"
        payload = unit_bytes(altered)
        kwargs["trust"] = replace(trust, authorizations={authref: payload}, approved_authorization_sha256=frozenset({sha256(payload).hexdigest()}))
    elif kind == "timestamp": item["executed_at"] = "2999-01-01T00:00:00Z"
    elif kind == "reviewed_commit": kwargs["trust"] = replace(trust, git_commit="0" * 40)
    else:
        del manifest["artifacts"]["MODEL"]
        kwargs["expected_artifacts"] = manifest["artifacts"]
        for row in manifest["items"]: row["artifact_set_sha256"] = canonical_digest(manifest["artifacts"])
    with pytest.raises(EvidenceBlocked): validate_manifest(manifest, matrix, **kwargs)


def test_synthetic_valid_proof_does_not_clear_other_missing_live_items(preparation):
    manifest, matrix, kwargs = unit_reviewed(preparation)
    assert validate_manifest(manifest, matrix, **kwargs)["R09-B01"] == "PASSED_LIVE"
    assert readiness(manifest, matrix, **kwargs) == "NO_GO"


def test_complete_synthetic_contract_still_cannot_authorize_promotion(preparation):
    _, matrix, _ = preparation
    manifest, matrix, kwargs = unit_reviewed(preparation, tuple(row["id"] for row in matrix["criteria"]))
    assert readiness(manifest, matrix, **kwargs) == "EVIDENCE_COMPLETE_AWAITING_OWNER"
    manifest["production_promotion"] = "APPROVED"
    with pytest.raises(EvidenceBlocked): validate_manifest(manifest, matrix, **kwargs)


@pytest.mark.parametrize("url", ("http://example.com:8081", "http://0.0.0.0:8081", "http://127.0.0.1:8082",
    "http://user:password@127.0.0.1:8081", "https://127.0.0.1:8081", "http://127.0.0.1:8081/completion", "http://127.0.0.1:8081/?route=remote"))
def test_wrong_or_unsafe_endpoint_cannot_support_acceptance(url):
    with pytest.raises(EvidenceBlocked): check_endpoints({"model": url}, {"model": LoopbackEndpoint("http", "127.0.0.1", 8081)})


@pytest.mark.parametrize("change", ("same_oid", "same_name", "marker", "fixture", "source_oid", "extra", "bool_oid"))
def test_incorrect_clone_provenance_is_blocked(change):
    fixture = sha256(b'TEST_ONLY fixture').hexdigest()
    observed = unit_clone(fixture)
    if change == "same_oid": observed["clone_oid"] = observed["source_oid"]
    elif change == "same_name": observed["clone_database"] = observed["source_database"]
    elif change == "bool_oid": observed["source_oid"] = True
    else: observed["marker"][{"marker": "kind", "fixture": "fixture_dump_sha256", "source_oid": "source_database_oid", "extra": "extra"}[change]] = "TEST_ONLY_BAD"
    with pytest.raises(EvidenceBlocked): check_clone(observed, fixture)


def test_clone_is_required_even_with_otherwise_pinned_execution_proof(preparation):
    manifest, matrix, kwargs = unit_reviewed(preparation, ("R09-C01",))
    kwargs["trust"] = replace(kwargs["trust"], clone_observation=None)
    with pytest.raises(EvidenceBlocked): validate_manifest(manifest, matrix, **kwargs)


@pytest.mark.parametrize("wire", (b'{"status":"NOT_RUN","status":"PASSED_LIVE"}', b'[]', b'not json', b'{"count":NaN}', b'\xff'))
def test_malformed_or_duplicate_evidence_json_is_rejected(wire):
    with pytest.raises(EvidenceBlocked): load_json_bytes(wire)


def test_holdout_payload_is_denied_before_loader_access():
    from stark_t2sql.evaluation.holdout import CasePartition, FrozenCaseIndex, FrozenCaseMetadata, read_tuning_payload, split_for_id
    # Synthetic metadata only, not an actual holdout index/case/payload.
    identity = next(f'R09-TEST-ONLY-{number}' for number in range(100) if split_for_id(f'R09-TEST-ONLY-{number}') is CasePartition.HOLDOUT)
    index = FrozenCaseIndex((FrozenCaseMetadata(identity, CasePartition.HOLDOUT, sha256(b'TEST_ONLY').hexdigest()),), 'TEST_ONLY metadata')
    called = []
    with pytest.raises(PermissionError):
        read_tuning_payload(index, identity, loader=lambda entry: called.append(entry))
    assert not called


def test_contract_and_scaffold_import_cannot_start_services_or_connect(monkeypatch):
    import importlib.util
    import sys
    import socket
    import subprocess
    import psycopg2
    def forbidden(*args, **kwargs): raise AssertionError('R09 import cannot execute live actions')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(psycopg2, 'connect', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    for filename, name in (('r09_evidence.py', 'tests.integration._r09_import_only_contract'),
                           ('test_r09_live_acceptance.py', 'tests.integration._r09_import_only_scaffold')):
        spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)


@pytest.mark.parametrize('offline', ('0', '1'))
def test_environment_opt_in_alone_never_supplies_an_owner_evidence_provider(monkeypatch, offline):
    from .test_r09_live_acceptance import r09_verified_evidence
    monkeypatch.setenv('STARK_R09_OFFLINE_ONLY', offline)
    monkeypatch.setenv('STARK_R09_EVIDENCE_REPLAY', '1')
    with pytest.raises(pytest.skip.Exception):
        r09_verified_evidence.__wrapped__()


def test_blocked_and_offline_statuses_are_distinct_from_live_acceptance(preparation):
    manifest, matrix, kwargs = preparation
    manifest['items'][0]['status'] = 'BLOCKED'
    assert validate_manifest(manifest, matrix, **kwargs)['R09-A01'] == 'BLOCKED'
    manifest, matrix, kwargs = unit_reviewed(preparation, ('R09-A01',))
    assert validate_manifest(manifest, matrix, **kwargs)['R09-A01'] == 'PASSED_OFFLINE'
    assert readiness(manifest, matrix, **kwargs) == 'NO_GO'


def test_offline_success_cannot_replace_mandatory_live_evidence(preparation):
    manifest, matrix, kwargs = unit_reviewed(preparation)
    next(item for item in manifest['items'] if item['status'] == 'PASSED_LIVE')['status'] = 'PASSED_OFFLINE'
    with pytest.raises(EvidenceBlocked): validate_manifest(manifest, matrix, **kwargs)


def test_changed_matrix_cannot_reuse_reviewed_execution_receipt(preparation):
    manifest, matrix, kwargs = unit_reviewed(preparation)
    matrix = deepcopy(matrix)
    next(row for row in matrix['criteria'] if row['id'] == 'R09-B01')['phase'] = 'A'
    for item in manifest['items']: item['matrix_sha256'] = canonical_digest(matrix)
    with pytest.raises(EvidenceBlocked): validate_manifest(manifest, matrix, **kwargs)


@pytest.mark.parametrize('change', ('empty', 'removed', 'not_mandatory', 'offline_substitution'))
def test_readiness_cannot_drop_mandatory_live_criteria(preparation, change):
    manifest, matrix, kwargs = preparation
    matrix = deepcopy(matrix)
    if change == 'empty':
        matrix['criteria'] = []
        manifest['items'] = []
    elif change == 'removed':
        matrix['criteria'].pop()
        manifest['items'].pop()
    elif change == 'not_mandatory': matrix['criteria'][4]['mandatory'] = False
    else: matrix['criteria'][4]['required_status'] = 'PASSED_OFFLINE'
    for item in manifest['items']: item['matrix_sha256'] = canonical_digest(matrix)
    with pytest.raises(EvidenceBlocked): readiness(manifest, matrix, **kwargs)


def test_failed_execution_remains_failed_with_actual_bound_unit_review(preparation):
    manifest, matrix, kwargs = unit_reviewed(preparation)
    item = next(row for row in manifest['items'] if row['status'] == 'PASSED_LIVE')
    item['status'] = 'FAILED'
    item['unresolved_prerequisites'] = ['OBSERVED_TEST_ONLY_FAILURE']
    reference = item['observation_reference']
    receipt = load_json_bytes(kwargs['trust'].receipts[reference])
    receipt['item_sha256'] = canonical_digest(item)
    payload = unit_bytes(receipt)
    kwargs['trust'] = replace(kwargs['trust'], receipts={reference: payload},
        approved_receipt_sha256=frozenset({sha256(payload).hexdigest()}))
    assert validate_manifest(manifest, matrix, **kwargs)['R09-B01'] == 'FAILED'
    assert readiness(manifest, matrix, **kwargs) == 'NO_GO'
