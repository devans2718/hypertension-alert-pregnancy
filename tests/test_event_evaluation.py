"""Read the engine's events; do not add another persistence classifier."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from htn_alert.contract import Action, ActionKind, Event, EventKind, Reading
from htn_alert.episodes import EpisodeTracker, treatment_deadline
from htn_alert.evaluate import evaluate_events
from htn_alert.protocol import load_protocol

T0 = datetime(2026, 11, 5, 8)


def at(minute):
    return T0 + timedelta(minutes=minute)


def run(sequence, doses=(), end=180, protocol=None):
    protocol = protocol or load_protocol()
    tracker = EpisodeTracker(protocol)
    inputs = [Reading("P", at(minute), *( (170, 110) if kind == "S" else (135, 85)))
              for minute, kind in sequence]
    inputs += [Action("P", at(minute), ActionKind.DOSE_GIVEN) for minute in doses]
    events = []
    for item in sorted(inputs, key=lambda i: i.time):
        events.extend(tracker.observe(item))
    events.extend(tracker.tick(at(end)))
    return evaluate_events(events, observed_until=at(end), patient_ids=("P",), protocol=protocol)


@pytest.mark.parametrize("dose,status,timely", [(59, "timely_dose", True), (60, "timely_dose", True), (61, "late_dose", False)])
def test_dose_deadline_uses_onset_not_confirmation(dose, status, timely):
    result = run([(0, "S"), (50, "S")], doses=(dose,))
    ep = result.episodes[0]
    assert ep.deadline == treatment_deadline(T0, load_protocol()) == at(60)
    assert ep.status == status
    assert ep.timely is timely
    assert result.patient_rate == float(timely)


def test_resolution_can_meet_metric_without_medication():
    result = run([(0, "S"), (30, "N"), (60, "N")])
    assert result.episodes[0].status == "timely_resolution"
    assert result.episodes[0].dose_time is None
    assert result.patient_rate == 1


def test_reopening_invalidates_provisional_resolution():
    result = run([(0, "S"), (15, "N"), (45, "S"), (75, "N")])
    assert len(result.episodes) == 1
    assert result.episodes[0].status == "no_dose"
    assert result.episodes[0].final_closing == at(75)
    assert result.patient_rate == 0


def test_last_closing_at_target_is_timely_after_recurrence():
    result = run([(0, "S"), (15, "N"), (45, "S"), (60, "N")])
    assert result.episodes[0].status == "timely_resolution"
    assert result.patient_rate == 1


def test_all_patient_episodes_must_be_timely():
    result = run([(0, "S"), (15, "S"), (30, "N"), (90, "S"), (105, "S")], end=180)
    assert result.persistent_episodes == 2
    assert result.timely_episodes == 1
    assert result.episode_rate == 0.5
    assert result.persistent_patients == 1
    assert result.timely_patients == 0
    assert result.patient_rate == 0


def test_nonpersistent_and_no_episode_patients_not_added_to_denominator():
    result = run([(0, "S"), (15, "N")])
    assert result.persistent_patients == 0
    assert result.patient_rate is None
    empty = evaluate_events([], observed_until=at(180), patient_ids=("no-observed-severe",))
    assert empty.patients[0].status == "no_episode"
    assert empty.patient_rate is None


def test_missing_dose_is_failure_after_full_window_not_silently_excluded():
    result = run([(0, "S"), (15, "S")], end=180)
    assert result.persistent_episodes == 1
    assert result.episodes[0].status == "no_dose"
    assert result.patient_rate == result.episode_rate == 0


@pytest.mark.parametrize("end", [10, 20, 59])
def test_short_observation_is_censored_even_if_episode_closes_early(end):
    sequence = [(0, "S")] if end == 10 else [(0, "S"), (15, "N")]
    result = run(sequence, end=end)
    assert result.patients[0].status == "censored"
    assert result.patient_rate is None
    assert result.episodes[0].timely is None


def test_alternate_target_uses_shared_deadline_helper():
    protocol = replace(load_protocol(), treatment_target=timedelta(minutes=35))
    result = run([(0, "S"), (15, "S")], doses=(36,), protocol=protocol)
    assert result.episodes[0].deadline == at(35)
    assert result.episodes[0].status == "late_dose"
    assert result.patient_rate == 0


def test_cannot_claim_unemitted_dose_or_infer_confirmation_from_detail():
    events = [Event("P", T0, EventKind.EPISODE_OPENED, "confirmed and dose given")]
    result = evaluate_events(events, observed_until=at(180))
    assert result.persistent_episodes == 0
    assert result.episodes[0].dose_time is None


def test_orphan_event_is_explicitly_unsupported():
    result = evaluate_events([Event("P", T0, EventKind.DOSE_RECORDED)], observed_until=at(180))
    assert result.patients[0].status == "unsupported"
    assert result.patient_rate is None


def test_future_event_rejected():
    with pytest.raises(ValueError, match="horizon"):
        evaluate_events([Event("P", at(60), EventKind.EPISODE_OPENED)], observed_until=at(30))
