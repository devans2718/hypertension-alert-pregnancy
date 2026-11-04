"""What the SMFM examples don't cover: when events fire, and staff actions.

tests/test_smfm_examples.py pins down what an episode is. These pin down the
rest of EpisodeTracker's behaviour, in the same notation: "S" a severe reading,
"N" a non-severe one, times in minutes from the first severe reading.
"""

from dataclasses import replace
from datetime import datetime, timedelta

from htn_alert.contract import Action, ActionKind, Event, EventKind, Reading
from htn_alert.episodes import EpisodeTracker, treatment_deadline
from htn_alert.protocol import load_protocol

PROTOCOL = load_protocol()
T0 = datetime(2026, 11, 1, 8, 0)


def minutes(t: int) -> datetime:
    return T0 + timedelta(minutes=t)


def severe(t: int, patient: str = "p1") -> Reading:
    return Reading(patient, minutes(t), 170, 100)


def non_severe(t: int, patient: str = "p1") -> Reading:
    return Reading(patient, minutes(t), 140, 90)


def acknowledged(t: int, patient: str = "p1") -> Action:
    return Action(patient, minutes(t), ActionKind.PROVIDER_ACKNOWLEDGED)


def dose(t: int, patient: str = "p1") -> Action:
    return Action(patient, minutes(t), ActionKind.DOSE_GIVEN)


def summary(events: list[Event]) -> list[tuple[EventKind, int]]:
    """Each event as (kind, minute), so a test can state the whole stream."""
    return [(e.kind, int((e.time - T0) / timedelta(minutes=1))) for e in events]


def run(*steps: Reading | Action | int, protocol=PROTOCOL) -> list[Event]:
    """Feed items in order; a bare number is a tick to that minute."""
    tracker = EpisodeTracker(protocol)
    events: list[Event] = []
    for step in steps:
        if isinstance(step, int):
            events += tracker.tick(minutes(step))
        else:
            events += tracker.observe(step)
    return events


def count(events: list[Event], kind: EventKind) -> int:
    return sum(event.kind is kind for event in events)


# When the deadlines fire


def test_repeat_due_fires_at_15_and_confirmed_only_after():
    assert summary(run(severe(0), 14, 15, 16)) == [
        (EventKind.EPISODE_OPENED, 0),
        (EventKind.REPEAT_DUE, 15),
        (EventKind.CONFIRMED, 16),
    ]


def test_a_late_tick_reports_both_in_order():
    assert summary(run(severe(0), 30)) == [
        (EventKind.EPISODE_OPENED, 0),
        (EventKind.REPEAT_DUE, 30),
        (EventKind.CONFIRMED, 30),
    ]


def test_severe_reading_at_15_confirms_from_observe():
    assert summary(run(severe(0), 15, severe(15))) == [
        (EventKind.EPISODE_OPENED, 0),
        (EventKind.REPEAT_DUE, 15),
        (EventKind.CONFIRMED, 15),
    ]


def test_escalates_only_after_the_timeout():
    # Confirmed at 16, so 10 minutes later is 26: exactly that doesn't escalate.
    events = run(severe(0), 16, 26)
    assert count(events, EventKind.ESCALATED) == 0
    assert (EventKind.ESCALATED, 27) in summary(run(severe(0), 16, 26, 27))


def test_each_deadline_fires_once_per_episode():
    events = run(severe(0), 15, 16, 16, 27, 40, severe(45), 60, 200)
    for kind in (EventKind.REPEAT_DUE, EventKind.CONFIRMED, EventKind.ESCALATED):
        assert count(events, kind) == 1, kind


def test_observe_reports_deadlines_that_passed_with_no_tick():
    assert summary(run(severe(0), severe(30))) == [
        (EventKind.EPISODE_OPENED, 0),
        (EventKind.REPEAT_DUE, 30),
        (EventKind.CONFIRMED, 30),
    ]


def test_nothing_is_due_once_closed():
    # The recheck is due at 15 even if the reading that answers it arrives then.
    events = run(severe(0), non_severe(15), 16, 60, 200)
    assert summary(events) == [
        (EventKind.EPISODE_OPENED, 0),
        (EventKind.REPEAT_DUE, 15),
        (EventKind.EPISODE_CLOSED, 15),
    ]


def test_times_come_from_the_protocol():
    shorter = replace(
        PROTOCOL,
        repeat_min=timedelta(minutes=5),
        escalate_unacknowledged=timedelta(minutes=2),
    )
    assert summary(run(severe(0), 5, 6, 8, 9, protocol=shorter)) == [
        (EventKind.EPISODE_OPENED, 0),
        (EventKind.REPEAT_DUE, 5),
        (EventKind.CONFIRMED, 6),
        (EventKind.ESCALATED, 9),
    ]


def test_severity_comes_from_the_protocol():
    higher = replace(PROTOCOL, severe_systolic=180)
    assert run(severe(0), protocol=higher) == []


# Staff actions


def test_acknowledgment_stops_escalation():
    events = run(severe(0), 16, acknowledged(20), 200)
    assert count(events, EventKind.ESCALATED) == 0


def test_acknowledgment_before_confirmation_also_stops_it():
    events = run(severe(0), acknowledged(5), 16, 200)
    assert count(events, EventKind.CONFIRMED) == 1
    assert count(events, EventKind.ESCALATED) == 0


def test_dose_is_recorded_and_stops_escalation():
    events = run(severe(0), 16, dose(20), 200)
    assert (EventKind.DOSE_RECORDED, 20) in summary(events)
    assert count(events, EventKind.ESCALATED) == 0


def test_dose_during_a_closed_episodes_window_is_recorded():
    events = run(severe(0), non_severe(15), dose(20))
    assert (EventKind.DOSE_RECORDED, 20) in summary(events)


def test_actions_with_no_episode_to_belong_to_report_nothing():
    assert run(dose(0), acknowledged(1)) == []
    assert count(run(severe(0), non_severe(15), dose(61)), EventKind.DOSE_RECORDED) == 0


def test_dose_on_a_still_open_episode_counts_after_the_window():
    events = run(severe(0), 16, dose(70))
    assert (EventKind.DOSE_RECORDED, 70) in summary(events)


# Closing and reopening


def test_closing_cancels_a_pending_escalation():
    events = run(severe(0), 16, non_severe(20), 200)
    assert count(events, EventKind.ESCALATED) == 0


def test_reopening_restarts_the_escalation_timer():
    events = run(severe(0), 16, non_severe(20), severe(30), 40, 41)
    assert (EventKind.ESCALATED, 41) in summary(events)
    assert count(events, EventKind.ESCALATED) == 1


def test_reopening_after_acknowledgment_does_not_escalate():
    events = run(severe(0), 16, acknowledged(18), non_severe(20), severe(30), 200)
    assert count(events, EventKind.ESCALATED) == 0


def test_every_fold_back_reports_a_reopening():
    """Figure 1's example B, as the full stream a consumer sees."""
    events = run(
        severe(0), non_severe(10), severe(30), non_severe(40),
        severe(50), non_severe(60), non_severe(80),
    )
    assert summary(events) == [
        (EventKind.EPISODE_OPENED, 0),
        (EventKind.EPISODE_CLOSED, 10),
        (EventKind.EPISODE_REOPENED, 30),
        (EventKind.CONFIRMED, 30),
        (EventKind.EPISODE_CLOSED, 40),
        (EventKind.EPISODE_REOPENED, 50),
        (EventKind.EPISODE_CLOSED, 60),
    ]


def test_severe_at_exactly_60_folds_back():
    events = run(severe(0), non_severe(15), severe(60))
    assert count(events, EventKind.EPISODE_OPENED) == 1
    assert (EventKind.EPISODE_REOPENED, 60) in summary(events)


def test_severe_after_closing_and_60_minutes_opens_a_second_episode():
    events = run(severe(0), non_severe(15), severe(61), 76, 77)
    assert summary(events) == [
        (EventKind.EPISODE_OPENED, 0),
        (EventKind.REPEAT_DUE, 15),
        (EventKind.EPISODE_CLOSED, 15),
        (EventKind.EPISODE_OPENED, 61),
        (EventKind.REPEAT_DUE, 76),
        (EventKind.CONFIRMED, 77),
    ]


# Several patients


def test_patients_stay_separate():
    events = run(
        severe(0, "p1"),
        severe(10, "p2"),
        acknowledged(12, "p1"),
        non_severe(15, "p2"),
        16,
        27,
    )
    by_patient = {
        patient: summary([e for e in events if e.patient_id == patient])
        for patient in ("p1", "p2")
    }
    assert by_patient == {
        "p1": [
            (EventKind.EPISODE_OPENED, 0),
            (EventKind.REPEAT_DUE, 16),
            (EventKind.CONFIRMED, 16),
        ],
        "p2": [
            (EventKind.EPISODE_OPENED, 10),
            (EventKind.EPISODE_CLOSED, 15),
        ],
    }


def test_one_patients_item_does_not_move_anothers_clock():
    tracker = EpisodeTracker(PROTOCOL)
    tracker.observe(severe(0, "p1"))
    events = tracker.observe(severe(100, "p2"))
    assert summary(events) == [(EventKind.EPISODE_OPENED, 100)]


# The treatment deadline


def test_treatment_deadline_counts_from_onset():
    assert treatment_deadline(minutes(0), PROTOCOL) == minutes(60)
    longer = replace(PROTOCOL, treatment_target=timedelta(minutes=30))
    assert treatment_deadline(minutes(10), longer) == minutes(40)


def test_a_reopening_leaves_the_onset_for_the_deadline_where_it_was():
    events = run(severe(0), non_severe(15), severe(50))
    [opened] = [e for e in events if e.kind is EventKind.EPISODE_OPENED]
    assert treatment_deadline(opened.time, PROTOCOL) == minutes(60)


# Late confirmation


def test_late_confirmation_placeholder():
    """PLACEHOLDER, not a decision: the team is choosing this rule (see #16).

    Confirming at 50 and allowing the same 10 minutes escalates just after 60,
    when the treatment window has closed. If the team picks something else,
    change _should_escalate in episodes.py and this test.
    """
    events = run(severe(0), 15, non_severe(15), 50, severe(50), 60, 61)
    assert summary(events) == [
        (EventKind.EPISODE_OPENED, 0),
        (EventKind.REPEAT_DUE, 15),
        (EventKind.EPISODE_CLOSED, 15),
        (EventKind.EPISODE_REOPENED, 50),
        (EventKind.CONFIRMED, 50),
        (EventKind.ESCALATED, 61),
    ]
