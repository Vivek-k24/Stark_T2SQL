"""S8.4 boundary test definitions only; no holdout contents or actual exposures.

Metadata below is explicitly an in-memory unit operand assembled only when a
future test runs. It is never written as an exposure ledger or owner schedule.
"""

import json

import pytest

from stark_t2sql.evaluation.holdout import DefinedBoundarySchedule, FrozenCaseIndex, HoldoutAuthority, PriorE8Exposure
from stark_t2sql.utils.fingerprints import sha256_bytes


def unit_index():
    return FrozenCaseIndex((), "In-memory unit index; no benchmark payload or actual freeze")


def unit_prior_e8(index):
    # Unit metadata has no case question, reference SQL, expected answer or
    # forbidden value. The unit digest is calculated from these exact bytes.
    payload = json.dumps({
        "record_type": "HOLDOUT_EXPOSURE",
        "run_id": "unit-prior-e8",
        "epic": "E8",
        "case_id": None,
        "index_sha256": index.sha256,
        "authorization_reference": "In-memory unit authorization; not a real exposure decision",
        "event": "BOUNDARY_END",
    }, sort_keys=True).encode("utf-8")
    return PriorE8Exposure.from_bytes(payload, exposure_reference="In-memory unit prior record; not an actual ledger", recorded_sha256=sha256_bytes(payload))


def unit_schedule(index, prior, *, epics=("E9",)):
    payload = json.dumps({
        "version": "fr9-holdout-boundaries-v1",
        "defined_epics": list(epics),
        "index_sha256": index.sha256,
        "prior_e8_exposure_reference": prior.exposure_reference,
        "prior_e8_record_sha256": prior.record_sha256,
    }, sort_keys=True).encode("utf-8")
    return DefinedBoundarySchedule.from_bytes(payload, schedule_reference="In-memory unit schedule; not an owner decision", recorded_sha256=sha256_bytes(payload))


@pytest.mark.parametrize("epic", ("E2", "E3", "E4", "E5", "E6", "E7", "E9"))
def test_first_holdout_boundary_requires_e8_before_exposure_record(epic):
    exposures = []
    authority = HoldoutAuthority(unit_index(), record_exposure=exposures.append)
    with pytest.raises(ValueError):
        authority.begin_boundary(epic=epic, run_id="unit-first-boundary", authorization_reference="Unit metadata decision only")
    assert exposures == []


def test_initial_e8_can_close_but_cannot_repeat_without_actual_history_schedule_inputs():
    exposures = []
    authority = HoldoutAuthority(unit_index(), record_exposure=exposures.append)
    permit = authority.begin_boundary(epic="E8", run_id="unit-initial-e8", authorization_reference="Unit metadata decision only")
    authority.end_boundary(permit)
    assert tuple(event.event for event in exposures) == ("BOUNDARY_BEGIN", "BOUNDARY_END")
    with pytest.raises(ValueError):
        authority.begin_boundary(epic="E8", run_id="unit-repeat-e8", authorization_reference="Unit metadata decision only")
    with pytest.raises(ValueError):
        authority.begin_boundary(epic="E9", run_id="unit-later-e9", authorization_reference="Unit metadata decision only")


def test_active_and_closed_permits_are_guarded():
    authority = HoldoutAuthority(unit_index(), record_exposure=lambda event: None)
    permit = authority.begin_boundary(epic="E8", run_id="unit-active-e8", authorization_reference="Unit metadata decision only")
    with pytest.raises(PermissionError):
        authority.begin_boundary(epic="E8", run_id="unit-overlapping-e8", authorization_reference="Unit metadata decision only")
    authority.end_boundary(permit)
    with pytest.raises(PermissionError):
        authority.end_boundary(permit)


def test_owner_defined_later_boundary_requires_byte_bound_e8_history_and_schedule():
    index = unit_index()
    prior = unit_prior_e8(index)
    schedule = unit_schedule(index, prior)
    exposures = []
    authority = HoldoutAuthority(index, record_exposure=exposures.append, prior_e8_exposure=prior, boundary_schedule=schedule)
    permit = authority.begin_boundary(epic="E9", run_id="unit-later-e9", authorization_reference="Unit metadata decision only")
    authority.end_boundary(permit)
    assert exposures[0].epic == "E9"
    with pytest.raises(ValueError):
        authority.begin_boundary(epic="E6", run_id="unit-unscheduled-e6", authorization_reference="Unit metadata decision only")
    with pytest.raises(PermissionError):
        authority.begin_boundary(epic="E9", run_id=prior.run_id, authorization_reference="Unit metadata decision only")


def test_direct_metadata_construction_cannot_invent_recorded_e8_provenance():
    index = unit_index()
    actual_unit_prior = unit_prior_e8(index)
    schedule = unit_schedule(index, actual_unit_prior)
    unbound = PriorE8Exposure(actual_unit_prior.run_id, actual_unit_prior.index_sha256, actual_unit_prior.exposure_reference, actual_unit_prior.record_sha256)
    with pytest.raises(ValueError):
        HoldoutAuthority(index, record_exposure=lambda event: None, prior_e8_exposure=unbound, boundary_schedule=schedule)


def test_schedule_and_prior_record_are_both_required():
    index = unit_index()
    prior = unit_prior_e8(index)
    with pytest.raises(ValueError):
        HoldoutAuthority(index, record_exposure=lambda event: None, prior_e8_exposure=prior)
    with pytest.raises(ValueError):
        HoldoutAuthority(index, record_exposure=lambda event: None, boundary_schedule=unit_schedule(index, prior))


def test_later_schedule_requires_the_current_frozen_index_binding():
    index = unit_index()
    prior = unit_prior_e8(index)
    other_index = FrozenCaseIndex((), "In-memory different unit freeze reference")
    # Freeze reference does not change the index's case content digest. Use
    # an actual alternative metadata index entry rather than a fake hash.
    from stark_t2sql.evaluation.holdout import FrozenCaseMetadata, split_for_id

    source_bytes = b"Opaque unit metadata bytes; no holdout question or answer"
    case_id = "unit-later-schedule-index-member"
    other_index = other_index.extend((FrozenCaseMetadata(case_id, split_for_id(case_id), sha256_bytes(source_bytes)),), freeze_reference="In-memory unit index extension")
    schedule = unit_schedule(other_index, prior)
    with pytest.raises(ValueError):
        HoldoutAuthority(index, record_exposure=lambda event: None, prior_e8_exposure=prior, boundary_schedule=schedule)


def test_prior_e8_reference_requires_a_completed_e8_metadata_record():
    index = unit_index()
    for epic, event in (("E7", "BOUNDARY_END"), ("E8", "BOUNDARY_BEGIN")):
        payload = json.dumps({
            "run_id": "unit-incomplete-boundary", "epic": epic, "event": event,
            "case_id": None, "index_sha256": index.sha256,
            "authorization_reference": "In-memory unit decision only",
        }, sort_keys=True).encode("utf-8")
        with pytest.raises(ValueError):
            PriorE8Exposure.from_bytes(payload, exposure_reference="In-memory unit record only", recorded_sha256=sha256_bytes(payload))


def test_boundary_byte_hash_binding_rejects_changed_metadata():
    original = b'{"unit":"original metadata"}'
    changed = b'{"unit":"changed metadata"}'
    with pytest.raises(ValueError):
        PriorE8Exposure.from_bytes(changed, exposure_reference="In-memory unit record only", recorded_sha256=sha256_bytes(original))

