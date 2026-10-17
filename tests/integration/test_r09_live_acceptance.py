"""Opt-in evidence replay scaffold; contains NO live executor or setup routine.

Future owner-authorized collection happens under the runbook, not pytest import
or this module. A separately reviewed fixture provider must supply independent
verification inputs; an environment flag alone never supplies that authority.
"""
import os

import pytest

from .r09_evidence import validate_manifest


@pytest.fixture(scope="module")
def r09_verified_evidence():
    if os.environ.get("STARK_R09_OFFLINE_ONLY") == "1":
        pytest.skip("R09 OFFLINE_ONLY: live acceptance not executed; no external evidence provider.")
    if os.environ.get("STARK_R09_EVIDENCE_REPLAY") != "1":
        pytest.skip("R09 NOT_RUN: separate owner authorization and reviewed evidence replay opt-in required.")
    # No dynamic module import, environment-loaded approval, default trust pins,
    # private-file search, service launch, database setup or holdout loader.
    pytest.skip("R09 BLOCKED: independently reviewed owner evidence provider is not supplied; no live actions executed.")


@pytest.mark.parametrize("phase", tuple("ABCDEF"))
def test_owner_controlled_phase_evidence(r09_verified_evidence, phase):
    manifest, matrix, verification_inputs = r09_verified_evidence
    statuses = validate_manifest(manifest, matrix, **verification_inputs)
    for criterion in matrix["criteria"]:
        if criterion["phase"] == phase:
            assert statuses[criterion["id"]] == criterion["required_status"]
