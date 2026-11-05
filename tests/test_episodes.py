"""Tests for EpisodeTracker behavior beyond SMFM worked examples."""

from datetime import datetime, timedelta

from htn_alert.contract import Action, ActionKind, EventKind, Reading
from htn_alert.episodes import EpisodeTracker
from htn_alert.protocol import load_protocol

PROTOCOL = load_protocol()
T0 = datetime(2026, 11, 1, 8, 0)


def test_repeat_due_confirmed_escalated_fire_once():
    """Verify that REPEAT_DUE, CONFIRMED, and ESCALATED fire once each."""
    tracker = EpisodeTracker(PROTOCOL)

    # Initial severe reading at T0
    events = tracker.observe(Reading("P1", T0, 165, 112))
    assert len(events) == 1
    assert events[0].kind == EventKind.EPISODE_OPENED

    # Tick to T0 + 15 min (repeat due)
    events_15 = tracker.tick(T0 + PROTOCOL.repeat_min)
    kinds_15 = [e.kind for e in events_15]
    assert EventKind.REPEAT_DUE in kinds_15

    # Tick further: repeat overdue and confirmation (missing repeat reading)
    events_16 = tracker.tick(T0 + PROTOCOL.repeat_min + timedelta(minutes=1))
    kinds_16 = [e.kind for e in events_16]
    assert EventKind.CONFIRMED in kinds_16
    assert EventKind.REPEAT_OVERDUE in kinds_16

    # Tick again at 18 min: no duplicate REPEAT_DUE or CONFIRMED
    events_18 = tracker.tick(T0 + timedelta(minutes=18))
    assert not any(e.kind in (EventKind.REPEAT_DUE, EventKind.CONFIRMED) for e in events_18)

    # Tick to confirmed_time + 10 min: ESCALATED fires because provider has not acknowledged
    events_esc = tracker.tick(T0 + PROTOCOL.repeat_min + timedelta(minutes=1) + PROTOCOL.escalate_unacknowledged)
    assert any(e.kind == EventKind.ESCALATED for e in events_esc)

    # Tick past escalation: ESCALATED does not fire again
    events_later = tracker.tick(T0 + timedelta(minutes=50))
    assert not any(e.kind == EventKind.ESCALATED for e in events_later)


def test_provider_acknowledged_stops_escalation():
    """PROVIDER_ACKNOWLEDGED action stops ESCALATED event from firing."""
    tracker = EpisodeTracker(PROTOCOL)
    tracker.observe(Reading("P1", T0, 168, 112))

    # Advance clock to confirmation
    t_confirm = T0 + PROTOCOL.repeat_min + timedelta(minutes=1)
    tracker.tick(t_confirm)

    # Provider acknowledges 5 minutes after confirmation
    tracker.observe(Action("P1", t_confirm + timedelta(minutes=5), ActionKind.PROVIDER_ACKNOWLEDGED))

    # Advance past escalation timeout
    events_esc = tracker.tick(t_confirm + PROTOCOL.escalate_unacknowledged + timedelta(minutes=2))
    assert not any(e.kind == EventKind.ESCALATED for e in events_esc)


def test_dose_given_action_observed():
    """DOSE_GIVEN action is accepted and stored."""
    tracker = EpisodeTracker(PROTOCOL)
    tracker.observe(Reading("P1", T0, 168, 112))
    dose_action = Action("P1", T0 + timedelta(minutes=25), ActionKind.DOSE_GIVEN)
    tracker.observe(dose_action)

    state = tracker._patients["P1"]
    assert dose_action in state.actions


def test_multiple_patients_stay_separate():
    """Two patients with different readings do not cross-talk."""
    tracker = EpisodeTracker(PROTOCOL)

    # P1 has severe reading, P2 has normal reading
    e1 = tracker.observe(Reading("P1", T0, 168, 112))
    e2 = tracker.observe(Reading("P2", T0, 120, 80))

    assert len(e1) == 1 and e1[0].kind == EventKind.EPISODE_OPENED
    assert len(e2) == 0

    # Advance clock
    t15 = T0 + PROTOCOL.repeat_min
    events_t15 = tracker.tick(t15)
    p1_events = [e for e in events_t15 if e.patient_id == "P1"]
    p2_events = [e for e in events_t15 if e.patient_id == "P2"]

    assert any(e.kind == EventKind.REPEAT_DUE for e in p1_events)
    assert len(p2_events) == 0


def test_second_episode_after_60_minutes():
    """A severe reading after an episode has closed and its 60 minutes have passed opens a second episode."""
    tracker = EpisodeTracker(PROTOCOL)

    # First episode: severe at 0, non-severe at 10 -> closes
    tracker.observe(Reading("P1", T0, 168, 112))
    close_event = tracker.observe(Reading("P1", T0 + timedelta(minutes=10), 125, 82))
    assert len(close_event) == 1 and close_event[0].kind == EventKind.EPISODE_CLOSED

    # Severe reading at 75 minutes (> 60 min from T0)
    t75 = T0 + timedelta(minutes=75)
    second_onset = tracker.observe(Reading("P1", t75, 172, 114))
    assert len(second_onset) == 1
    assert second_onset[0].kind == EventKind.EPISODE_OPENED
    assert second_onset[0].time == t75
