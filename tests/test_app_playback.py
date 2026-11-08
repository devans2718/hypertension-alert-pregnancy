"""Unit tests for app/playback.py helper functions.

Tests playback filtering, latest reading per patient, countdown calculations,
EpisodeTracker-backed unit views and states, and simulated SBAR formatting.
"""

from datetime import datetime, timedelta

import pytest

from app.playback import (
    EpisodePhase,
    calculate_countdown,
    evaluate_playback_episode,
    evaluate_unit_view,
    filter_readings_up_to,
    generate_sbar_handoff,
    latest_reading_per_patient,
    most_urgent_status,
)
from htn_alert.contract import Action, ActionKind, EventKind, Reading
from htn_alert.protocol import Protocol


@pytest.fixture
def test_protocol() -> Protocol:
    """Standard test protocol matching config/protocol.toml values."""
    return Protocol(
        severe_systolic=160,
        severe_diastolic=110,
        repeat_min=timedelta(minutes=15),
        repeat_max=timedelta(minutes=60),
        treatment_target=timedelta(minutes=60),
        escalate_unacknowledged=timedelta(minutes=10),
        escalate_before_deadline=timedelta(minutes=10),
    )


def test_filter_readings_up_to():
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P1", time=t0, systolic=120, diastolic=80)
    r2 = Reading(patient_id="P1", time=t0 + timedelta(minutes=10), systolic=165, diastolic=112)
    r3 = Reading(patient_id="P1", time=t0 + timedelta(minutes=25), systolic=162, diastolic=108)

    readings = [r3, r1, r2]  # unordered input

    # Before r2 arrives
    filtered_5m = filter_readings_up_to(readings, t0 + timedelta(minutes=5))
    assert filtered_5m == [r1]

    # Exactly at r2
    filtered_10m = filter_readings_up_to(readings, t0 + timedelta(minutes=10))
    assert filtered_10m == [r1, r2]

    # After r3
    filtered_30m = filter_readings_up_to(readings, t0 + timedelta(minutes=30))
    assert filtered_30m == [r1, r2, r3]


def test_latest_reading_per_patient():
    """Verify latest reading per patient at time t (Issue #8 requirement)."""
    t0 = datetime(2026, 10, 31, 10, 0)
    r_p1_0 = Reading("Bed-01", t0, 120, 80)
    r_p1_10 = Reading("Bed-01", t0 + timedelta(minutes=10), 165, 112)
    r_p2_0 = Reading("Bed-02", t0, 118, 76)
    r_p3_0 = Reading("Bed-03", t0, 170, 114)
    r_p3_15 = Reading("Bed-03", t0 + timedelta(minutes=15), 168, 110)

    all_readings = [r_p1_0, r_p2_0, r_p3_0, r_p1_10, r_p3_15]

    # At T=5 min
    latest_t5 = latest_reading_per_patient(all_readings, t0 + timedelta(minutes=5))
    assert latest_t5["Bed-01"] == r_p1_0
    assert latest_t5["Bed-02"] == r_p2_0
    assert latest_t5["Bed-03"] == r_p3_0

    # At T=20 min
    latest_t20 = latest_reading_per_patient(all_readings, t0 + timedelta(minutes=20))
    assert latest_t20["Bed-01"] == r_p1_10
    assert latest_t20["Bed-02"] == r_p2_0
    assert latest_t20["Bed-03"] == r_p3_15


def test_calculate_countdown():
    t0 = datetime(2026, 10, 31, 10, 0)
    target = t0 + timedelta(minutes=15)

    # 10 minutes remaining
    rem_secs, is_overdue, display = calculate_countdown(target, t0 + timedelta(minutes=5))
    assert rem_secs == 600
    assert not is_overdue
    assert display == "10:00"

    # Exactly on target
    rem_secs, is_overdue, display = calculate_countdown(target, target)
    assert rem_secs == 0
    assert not is_overdue
    assert display == "00:00"

    # 3 minutes 45 seconds overdue
    overdue_time = target + timedelta(minutes=3, seconds=45)
    rem_secs, is_overdue, display = calculate_countdown(target, overdue_time)
    assert rem_secs == 0
    assert is_overdue
    assert display == "+03:45"


def test_evaluate_playback_empty(test_protocol):
    status = evaluate_playback_episode([], test_protocol)
    assert status.phase == EpisodePhase.NONE


def test_evaluate_playback_normal_readings(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    readings = [
        Reading(patient_id="P1", time=t0, systolic=120, diastolic=80),
    ]
    status = evaluate_playback_episode(readings, test_protocol, simulated_now=t0 + timedelta(minutes=5))
    assert status.phase == EpisodePhase.NONE
    assert "Normal reference range" in status.detail


def test_evaluate_playback_repeat_pending(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    readings = [
        Reading(patient_id="P1", time=t0, systolic=168, diastolic=112),
    ]
    status = evaluate_playback_episode(readings, test_protocol, simulated_now=t0 + timedelta(minutes=5))
    assert status.phase == EpisodePhase.REPEAT_PENDING
    assert status.first_severe_reading == readings[0]
    assert status.repeat_target_time == t0 + test_protocol.repeat_min


def test_evaluate_playback_repeat_due(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    readings = [
        Reading(patient_id="P1", time=t0, systolic=168, diastolic=112),
    ]
    status = evaluate_playback_episode(readings, test_protocol, simulated_now=t0 + test_protocol.repeat_min)
    assert status.phase == EpisodePhase.REPEAT_DUE
    assert "due now" in status.detail


def test_evaluate_playback_confirmed_persistent(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P1", time=t0, systolic=165, diastolic=105)
    r2 = Reading(patient_id="P1", time=t0 + timedelta(minutes=18), systolic=162, diastolic=108)

    status = evaluate_playback_episode([r1, r2], test_protocol)
    assert status.phase == EpisodePhase.CONFIRMED
    assert status.first_severe_reading == r1
    assert status.repeat_reading == r2
    assert status.treatment_target_time == r1.time + timedelta(minutes=60)
    assert "Persistent severe HTN confirmed" in status.detail


def test_evaluate_playback_resolved(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P1", time=t0, systolic=175, diastolic=115)
    r2 = Reading(patient_id="P1", time=t0 + timedelta(minutes=16), systolic=135, diastolic=85)

    status = evaluate_playback_episode([r1, r2], test_protocol)
    assert status.phase == EpisodePhase.RESOLVED
    assert status.first_severe_reading == r1
    assert status.repeat_reading == r2
    assert "below severe range" in status.detail


def test_evaluate_playback_escalated(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P1", time=t0, systolic=168, diastolic=112)
    r2 = Reading(patient_id="P1", time=t0 + timedelta(minutes=16), systolic=164, diastolic=108)

    # 12 minutes after confirmation without provider acknowledgment -> ESCALATED
    now = t0 + timedelta(minutes=16) + test_protocol.escalate_unacknowledged + timedelta(minutes=2)
    status = evaluate_playback_episode([r1, r2], test_protocol, simulated_now=now)
    assert status.phase == EpisodePhase.ESCALATED


def test_evaluate_unit_view(test_protocol):
    """Verify unit view across multiple patients at time t (Issue #18)."""
    t0 = datetime(2026, 10, 31, 10, 0)
    cohort = {
        "Bed-01": [Reading("Bed-01", t0, 120, 80)],
        "Bed-02": [
            Reading("Bed-02", t0, 168, 112),
            Reading("Bed-02", t0 + timedelta(minutes=16), 164, 108),
        ],
        "Bed-03": [
            Reading("Bed-03", t0, 172, 114),
            Reading("Bed-03", t0 + timedelta(minutes=16), 128, 82),
        ],
    }

    unit = evaluate_unit_view(cohort, t0 + timedelta(minutes=20), test_protocol)
    assert unit["Bed-01"].phase == EpisodePhase.NONE
    assert unit["Bed-02"].phase == EpisodePhase.CONFIRMED
    assert unit["Bed-03"].phase == EpisodePhase.RESOLVED


def test_evaluate_unit_view_passes_each_patients_actions(test_protocol):
    """An acknowledgment reaches only its own patient: that one doesn't escalate."""
    t0 = datetime(2026, 10, 31, 10, 0)
    cohort = {
        bed: [Reading(bed, t0, 168, 112), Reading(bed, t0 + timedelta(minutes=16), 164, 108)]
        for bed in ("Bed-01", "Bed-02")
    }
    actions = {"Bed-01": [Action("Bed-01", t0 + timedelta(minutes=20), ActionKind.PROVIDER_ACKNOWLEDGED)]}

    unit = evaluate_unit_view(cohort, t0 + timedelta(minutes=40), test_protocol, actions)
    assert unit["Bed-01"].phase == EpisodePhase.CONFIRMED
    assert unit["Bed-02"].phase == EpisodePhase.ESCALATED


def test_generate_sbar_handoff(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P101", time=t0, systolic=165, diastolic=112)
    r2 = Reading(patient_id="P101", time=t0 + timedelta(minutes=18), systolic=162, diastolic=108)

    confirmed_status = evaluate_playback_episode([r1, r2], test_protocol)
    sbar = generate_sbar_handoff("P101", confirmed_status, [r1, r2])

    assert "**SIMULATED ATTENDING PHYSICIAN NOTIFICATION" in sbar
    assert "**SITUATION:**" in sbar
    assert "**BACKGROUND:**" in sbar
    assert "**ASSESSMENT:**" in sbar
    assert "**RECOMMENDATION:**" in sbar
    assert "P101" in sbar
    assert "165/112" in sbar
    assert "162/108" in sbar
    assert "ACOG/SMFM" in sbar


def test_generate_sbar_handoff_unconfirmed(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P102", time=t0, systolic=120, diastolic=80)
    normal_status = evaluate_playback_episode([r1], test_protocol)

    sbar = generate_sbar_handoff("P102", normal_status, [r1])
    assert "only generated upon confirmed" in sbar


def _event_times(status, kind):
    return [e.time for e in status.events if e.kind is kind]


def test_missed_recheck_events_keep_the_minute_they_fell_due(test_protocol):
    """A replay stamps deadline events with when they fell due, whatever the clock.

    The live app replays every second with a later clock; the confirmation of a
    missed recheck has to stay at onset + 16 so the escalation timer can run.
    """
    t0 = datetime(2026, 11, 7, 10, 0)
    onset = [Reading(patient_id="P1", time=t0, systolic=168, diastolic=112)]

    at_20 = evaluate_playback_episode(onset, test_protocol, t0 + timedelta(minutes=20))
    at_25 = evaluate_playback_episode(onset, test_protocol, t0 + timedelta(minutes=25))

    assert _event_times(at_20, EventKind.REPEAT_DUE) == [t0 + timedelta(minutes=15)]
    assert _event_times(at_20, EventKind.CONFIRMED) == [t0 + timedelta(minutes=16)]
    assert _event_times(at_25, EventKind.CONFIRMED) == [t0 + timedelta(minutes=16)]


def test_missed_recheck_escalates_on_the_timeout(test_protocol):
    """Confirmed at 16 with no response, the 10-minute timeout escalates at 27."""
    t0 = datetime(2026, 11, 7, 10, 0)
    onset = [Reading(patient_id="P1", time=t0, systolic=168, diastolic=112)]

    status = evaluate_playback_episode(onset, test_protocol, t0 + timedelta(minutes=30))

    assert status.phase == EpisodePhase.ESCALATED
    assert _event_times(status, EventKind.ESCALATED) == [t0 + timedelta(minutes=27)]


def test_acknowledgment_in_the_replay_stops_the_escalation(test_protocol):
    t0 = datetime(2026, 11, 7, 10, 0)
    onset = [Reading(patient_id="P1", time=t0, systolic=168, diastolic=112)]
    ack = [Action(patient_id="P1", time=t0 + timedelta(minutes=20), kind=ActionKind.PROVIDER_ACKNOWLEDGED)]

    status = evaluate_playback_episode(onset, test_protocol, t0 + timedelta(minutes=30), actions=ack)

    assert status.phase == EpisodePhase.CONFIRMED
    assert _event_times(status, EventKind.ESCALATED) == []


def test_most_urgent_status_ranks_phases_and_expires_resolutions(test_protocol):
    t0 = datetime(2026, 11, 7, 10, 0)
    now = t0 + timedelta(minutes=20)
    severe, normal = (168, 112), (120, 78)

    def patient(pid, *timed):
        readings = [
            Reading(patient_id=pid, time=t0 + timedelta(minutes=m), systolic=bp[0], diastolic=bp[1])
            for m, bp in timed
        ]
        return evaluate_playback_episode(readings, test_protocol, now)

    pending = patient("pending", (10, severe))          # opened at 10, repeat due at 25
    resolved = patient("resolved", (0, severe), (15, normal))
    confirmed = patient("confirmed", (0, severe), (15, severe))

    unit = {"pending": pending, "resolved": resolved, "confirmed": confirmed}
    assert most_urgent_status(unit, now, timedelta(minutes=20)) is confirmed

    unit = {"pending": pending, "resolved": resolved}
    assert most_urgent_status(unit, now, timedelta(minutes=20)) is pending

    # Closed at 15: shown for 10 minutes, it's still news at 20; for 2, it isn't.
    assert most_urgent_status({"resolved": resolved}, now, timedelta(minutes=10)) is resolved
    assert most_urgent_status({"resolved": resolved}, now, timedelta(minutes=2)) is None
