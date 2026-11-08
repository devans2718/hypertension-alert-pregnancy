"""The unit view's shifts: every seed has to tell the demo's story.

The roles in config/unit_layout.toml are promises the demo makes out loud
("one confirms and is treated, one resolves, one misses a recheck, one reaches
the treatment deadline"), and the readings and staff timings are random. These
tests replay many seeds through EpisodeTracker and check each promise holds.
"""

import pytest

from app.playback import EpisodePhase, evaluate_unit_view
from app.unit_view import build_shift, card_note, load_unit_layout
from htn_alert.contract import EventKind
from htn_alert.protocol import load_protocol

SEEDS = range(200)


@pytest.fixture(scope="module")
def protocol():
    return load_protocol()


@pytest.fixture(scope="module")
def layout():
    return load_unit_layout()


def _end_of_shift(seed, protocol, layout):
    """Each bed's role and its status at the end of the shift."""
    shift = build_shift(seed, protocol, layout)
    statuses = evaluate_unit_view(shift.readings, shift.end, protocol, shift.actions)
    return shift, statuses


def _kinds(status):
    return [e.kind for e in status.events]


def test_layout_places_every_patient_on_its_own_bed(layout):
    cells = {(b.row, b.column) for b in layout.beds}
    assert len(cells) == len(layout.beds)
    assert len(layout.patients) <= len(layout.beds)
    assert all(b.row != layout.corridor_row for b in layout.beds)


def test_every_bed_carries_its_patients_episode_type(protocol, layout):
    assert all(p.episode_type for p in layout.patients)
    shift = build_shift(3, protocol, layout)
    by_role = {p.role: p.episode_type for p in layout.patients}
    assert shift.episode_types.keys() == shift.roles.keys()
    for bed, role in shift.roles.items():
        assert shift.episode_types[bed] == by_role[role]


def test_the_same_seed_gives_the_same_shift(protocol, layout):
    first, second = build_shift(7, protocol, layout), build_shift(7, protocol, layout)
    assert first.roles == second.roles
    assert first.readings == second.readings
    assert first.actions == second.actions


def test_different_seeds_move_the_stories_between_beds(protocol, layout):
    placements = {
        tuple(sorted(build_shift(seed, protocol, layout).roles.items())) for seed in range(10)
    }
    assert len(placements) > 1


@pytest.mark.parametrize("seed", SEEDS)
def test_every_role_holds(seed, protocol, layout):
    shift, statuses = _end_of_shift(seed, protocol, layout)
    for bed, role in shift.roles.items():
        status, kinds = statuses[bed], _kinds(statuses[bed])
        if role == "treated":
            # Confirmed, acknowledged and dosed before the target; never escalated.
            assert EventKind.CONFIRMED in kinds
            assert EventKind.ESCALATED not in kinds
            dose = next(e for e in status.events if e.kind is EventKind.DOSE_RECORDED)
            assert dose.time < status.treatment_target_time
        elif role == "resolves":
            assert EventKind.EPISODE_OPENED in kinds
            assert EventKind.EPISODE_CLOSED in kinds
            assert EventKind.CONFIRMED not in kinds
        elif role == "missed_recheck":
            assert EventKind.REPEAT_DUE in kinds
            confirmed = next(e for e in status.events if e.kind is EventKind.CONFIRMED)
            assert confirmed.detail == "no reading below the severe range in time"
        elif role == "deadline":
            # Still open, unanswered and untreated when the target passes.
            assert EventKind.ESCALATED in kinds
            assert EventKind.DOSE_RECORDED not in kinds
            closed = [e.time for e in status.events if e.kind is EventKind.EPISODE_CLOSED]
            assert not closed or closed[0] > status.treatment_target_time
        elif role == "reopens":
            # Closed, then severe again inside the hour: reopened, not a new episode.
            assert kinds.count(EventKind.EPISODE_OPENED) == 1
            closed = kinds.index(EventKind.EPISODE_CLOSED)
            assert kinds.index(EventKind.EPISODE_REOPENED) > closed
            assert EventKind.CONFIRMED in kinds
        else:
            assert role == "routine"
            assert EventKind.EPISODE_OPENED not in kinds


@pytest.mark.parametrize("seed", range(20))
def test_no_reading_comes_sooner_than_the_unit_takes_one(seed, protocol, layout):
    shift = build_shift(seed, protocol, layout)
    for readings in shift.readings.values():
        gaps = [b.time - a.time for a, b in zip(readings, readings[1:])]
        assert all(gap >= layout.min_reading_gap for gap in gaps)


def test_card_note_shows_a_passed_target_for_the_deadline_bed(protocol, layout):
    shift = build_shift(0, protocol, layout)
    bed = next(b for b, role in shift.roles.items() if role == "deadline")
    probe = evaluate_unit_view(shift.readings, shift.end, protocol, shift.actions)[bed]
    now = probe.treatment_target_time
    status = evaluate_unit_view(shift.readings, now, protocol, shift.actions)[bed]
    assert status.phase is EpisodePhase.ESCALATED
    assert card_note(status, now).startswith("Treatment target passed")
