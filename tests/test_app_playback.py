"""Unit tests for app/playback.py helper functions.

Tests playback filtering, countdown calculations, protocol state evaluations,
and automated SBAR handoff formatting.
"""

from datetime import datetime, timedelta

import pytest

from app.playback import (
    EpisodePhase,
    calculate_countdown,
    evaluate_playback_episode,
    filter_readings_up_to,
    generate_sbar_handoff,
)
from htn_alert.contract import Reading
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
        close_after=timedelta(minutes=120),
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
    assert "Normal range" in status.detail


def test_evaluate_playback_routine_due(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    readings = [
        Reading(patient_id="P1", time=t0, systolic=120, diastolic=80),
    ]
    status = evaluate_playback_episode(readings, test_protocol, simulated_now=t0 + timedelta(minutes=16))
    assert status.phase == EpisodePhase.ROUTINE_DUE
    assert "Nurse Notice" in status.detail


def test_evaluate_playback_critical_emergency(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r = Reading(patient_id="P1", time=t0, systolic=192, diastolic=124)
    status = evaluate_playback_episode([r], test_protocol)
    assert status.phase == EpisodePhase.CRITICAL_EMERGENCY
    assert "CRITICAL DANGER ALARM" in status.detail
    sbar = generate_sbar_handoff("P1", status, [r])
    assert "STAT CRITICAL EMERGENCY ALERT" in sbar


def test_evaluate_playback_repeat_pending(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P1", time=t0, systolic=165, diastolic=100)  # systolic severe
    now = t0 + timedelta(minutes=7)

    status = evaluate_playback_episode([r1], test_protocol, simulated_now=now)
    assert status.phase == EpisodePhase.REPEAT_PENDING
    assert status.first_severe_reading == r1
    assert status.repeat_target_time == t0 + timedelta(minutes=15)
    assert status.repeat_deadline_time == t0 + timedelta(minutes=60)


def test_evaluate_playback_repeat_due(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P1", time=t0, systolic=155, diastolic=115)  # diastolic severe
    now = t0 + timedelta(minutes=22)  # between 15 and 60 minutes

    status = evaluate_playback_episode([r1], test_protocol, simulated_now=now)
    assert status.phase == EpisodePhase.REPEAT_DUE
    assert "Repeat overdue" in status.detail


def test_evaluate_playback_expired(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P1", time=t0, systolic=170, diastolic=110)
    now = t0 + timedelta(minutes=65)  # > 60 minutes

    status = evaluate_playback_episode([r1], test_protocol, simulated_now=now)
    assert status.phase == EpisodePhase.EXPIRED


def test_evaluate_playback_too_early_repeat_ignored(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P1", time=t0, systolic=168, diastolic=112)
    # A reading at 8 minutes is too early to satisfy the 15-minute repeat protocol
    r_early = Reading(patient_id="P1", time=t0 + timedelta(minutes=8), systolic=165, diastolic=110)

    now = t0 + timedelta(minutes=10)
    status = evaluate_playback_episode([r1, r_early], test_protocol, simulated_now=now)
    # Still pending because valid repeat must be >= 15 min
    assert status.phase == EpisodePhase.REPEAT_PENDING


def test_evaluate_playback_confirmed_persistent(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P1", time=t0, systolic=165, diastolic=105)
    r2 = Reading(patient_id="P1", time=t0 + timedelta(minutes=18), systolic=162, diastolic=108)

    status = evaluate_playback_episode([r1, r2], test_protocol)
    assert status.phase == EpisodePhase.CONFIRMED
    assert status.first_severe_reading == r1
    assert status.repeat_reading == r2
    assert status.treatment_target_time == r2.time + timedelta(minutes=60)
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


def test_generate_sbar_handoff(test_protocol):
    t0 = datetime(2026, 10, 31, 10, 0)
    r1 = Reading(patient_id="P101", time=t0, systolic=165, diastolic=112)
    r2 = Reading(patient_id="P101", time=t0 + timedelta(minutes=18), systolic=162, diastolic=108)

    confirmed_status = evaluate_playback_episode([r1, r2], test_protocol)
    sbar = generate_sbar_handoff("P101", confirmed_status, [r1, r2])

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

