"""Coupled engineering assumptions, not clinical-effectiveness tests."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from htn_alert.contract import ActionKind, EventKind
from htn_alert.episodes import EpisodeTracker, treatment_deadline
from htn_alert.generator import (
    BPPoint, PatientCourse, SCENARIOS, generate_course_cohort, generate_patient_course,
)
from htn_alert.paired_simulation import compare_patient_course, compare_workflows
from htn_alert.cohort_evaluation import evaluate_cohort, evaluate_coupled_cohort
from htn_alert.protocol import load_protocol
from htn_alert.rules import is_severe
from htn_alert.sensitivity_analysis import run_coupled_sensitivity_analysis
from htn_alert.simulation_config import load_coupled_config, load_workflow_config
from htn_alert.workflow import simulate_workflow

T0 = datetime(2026, 11, 5, 8)
PROTOCOL = load_protocol()


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def course(phases=((0, 170, 110),), cycle=60, end=180, scenario="custom"):
    return PatientCourse("P", T0, at(end), cycle, 15,
                         tuple(BPPoint(at(t), s, d) for t, s, d in phases), scenario)


def delays(**changes):
    return replace(load_workflow_config(), recognition_minutes=(20, 20),
                   readiness_minutes=(10, 10), identification_minutes=(10, 10),
                   acknowledgment_minutes=(5, 5), medication_minutes=(15, 15),
                   **changes)


def fixed_delays(**changes):
    defaults = dict(recognition_minutes=(5, 5), readiness_minutes=(0, 0),
                    identification_minutes=(5, 5), acknowledgment_minutes=(5, 5),
                    medication_minutes=(20, 20), collaboration_minutes=(7, 7),
                    uncertainty_minutes=(20, 20))
    defaults.update(changes)
    return replace(load_workflow_config(), **defaults)


def test_actual_reassessment_changes_downstream_treatment():
    pair = compare_workflows(course(), workflow_config=delays())
    assert pair.baseline.reassessments[0].actual_time == at(30)
    assert pair.tool.reassessments[0].actual_time == at(20)
    assert pair.baseline.reassessments[0].minutes_late == 15
    assert pair.tool.reassessments[0].minutes_late == 5
    assert pair.baseline.medication_time == at(60)
    assert pair.tool.medication_time == at(45)
    assert pair.medication_minutes_saved == 15
    assert pair.baseline.readings != pair.tool.readings
    assert pair.baseline.first_severe_time == pair.tool.first_severe_time == T0


def test_earlier_reassessment_does_not_guarantee_earlier_dose():
    cc = replace(load_coupled_config(), clinician_available_after_minutes=70)
    pair = compare_patient_course(course(), workflow_config=delays(), coupled_config=cc)
    assert pair.reassessment_minutes_saved == 10
    assert pair.baseline.medication_time == pair.tool.medication_time == at(85)
    assert pair.medication_minutes_saved == 0


def test_unobserved_spontaneous_resolution_cancels_dose():
    patient = course(((0, 170, 110), (30, 135, 85)))
    result = simulate_workflow(patient, config=fixed_delays())
    assert result.reassessments[0].actual_time == at(15)
    assert any(row.kind == "medication_ordered" for row in result.trace)
    assert any(row.kind == "dose_cancelled" and row.time == at(45) for row in result.trace)
    assert not any(a.kind is ActionKind.DOSE_GIVEN for a in result.actions)
    assert not any(e.kind is EventKind.DOSE_RECORDED for e in result.events)
    assert result.medication_time is None
    assert result.no_dose_reason == "resolved_before_administration"
    # The gate must not manufacture a Reading at the unobserved change point.
    assert not any(r.time == at(30) for r in result.readings)


def test_recorded_resolution_cancels_pending_administration():
    patient = course(((0, 170, 110), (30, 135, 85)), cycle=15)
    result = simulate_workflow(patient, config=fixed_delays())
    assert any(e.kind is EventKind.EPISODE_CLOSED and e.time == at(30) for e in result.events)
    assert not any(a.kind is ActionKind.DOSE_GIVEN for a in result.actions)


def test_medication_does_not_invent_bp_response():
    patient = course()
    result = simulate_workflow(patient, config=fixed_delays())
    assert result.medication_time == at(45)
    assert all(is_severe(r, PROTOCOL) for r in result.readings)
    assert is_severe(patient.sample(at(180)), PROTOCOL)
    assert len([a for a in result.actions if a.kind is ActionKind.DOSE_GIVEN]) == 1


@pytest.mark.parametrize("cycle", [15, 30, 60])
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_revised_measurement_respects_minimum_spacing(cycle, scenario):
    patient = generate_patient_course("P", T0, scenario, routine_interval_minutes=cycle)
    result = simulate_workflow(patient)
    assert all(b.time - a.time >= timedelta(minutes=15) for a, b in zip(result.readings, result.readings[1:]))
    assert len({r.time for r in result.readings}) == len(result.readings)
    assert all((r.systolic, r.diastolic) == (patient.sample(r.time).systolic, patient.sample(r.time).diastolic)
               for r in result.readings)


def test_routine_reading_can_rescue_missed_urgent_task():
    result = simulate_workflow(course(cycle=30), missing_recheck=True, config=fixed_delays())
    assert result.reassessments[0].actual_time == at(30)
    assert result.reassessments[0].source == "routine"
    assert result.reassessments[0].minutes_late == 15
    assert result.missed_reassessments == 0
    assert any(t.kind == "urgent_reassessment_missed" for t in result.trace)


def test_missing_actual_reassessment_is_not_replaced_by_confirmation():
    result = simulate_workflow(course(end=45), missing_recheck=True, config=fixed_delays())
    assert result.reassessments[0].missing
    assert result.reassessments[0].minutes_late is None
    assert any(e.kind is EventKind.CONFIRMED and e.time == at(16) for e in result.events)
    assert result.medication_time is None
    assert result.no_dose_reason == "missing_actual_reassessment"
    assert result.evaluation.patients[0].status == "censored"


def test_late_recognition_does_not_restart_targets():
    result = simulate_workflow(course(), config=fixed_delays(recognition_minutes=(40, 40)))
    task = result.reassessments[0]
    assert task.target_time == at(15)
    assert task.actual_time == at(40)
    assert task.minutes_late == 25
    assert result.evaluation.episodes[0].deadline == treatment_deadline(T0, PROTOCOL) == at(60)


def test_hidden_onset_between_routine_measurements_cannot_trigger_awareness():
    patient = course(((0, 135, 85), (15, 170, 110)), cycle=60)
    pair = compare_patient_course(patient, workflow_config=fixed_delays())
    for result in (pair.baseline, pair.tool):
        assert result.first_severe_time == at(60)
        assert result.evaluation.episodes[0].deadline == at(120)
        assert not any(row.kind == "nurse_recognized" and row.time < at(60) for row in result.trace)
        assert not any(event.time < at(60) for event in result.events)


@pytest.mark.parametrize("pathway,identified,notified,dose", [
    ("direct", 20, 20, 45), ("collaboration_required", 20, 27, 52),
    ("provider_uncertain", 40, 40, 65),
])
def test_provider_pathways_have_distinct_contact_delays(pathway, identified, notified, dose):
    result = simulate_workflow(course(), provider_pathway=pathway, config=fixed_delays())
    assert next(t.time for t in result.trace if t.kind == "provider_identified") == at(identified)
    assert next(t.time for t in result.trace if t.kind == "provider_notified") == at(notified)
    assert result.medication_time == at(dose)
    assert [a.kind for a in result.actions] == [ActionKind.PROVIDER_ACKNOWLEDGED, ActionKind.DOSE_GIVEN]


def test_provider_overlap_is_an_explicit_independent_assumption():
    serial = simulate_workflow(course(), config=fixed_delays())
    overlap = simulate_workflow(course(), config=fixed_delays(),
        coupled_config=replace(load_coupled_config(), provider_search_overlaps_reassessment=True))
    assert serial.medication_time == at(45)
    assert overlap.medication_time == at(40)
    assert serial.readings == overlap.readings


def test_late_confirmation_deadline_reminder_does_not_change_engine_or_create_dose():
    patient = course(((0, 170, 110), (15, 135, 85), (50, 170, 110)), cycle=50)
    cc = replace(load_coupled_config(), contact_succeeds=False)
    without = simulate_workflow(patient, config=fixed_delays(), coupled_config=cc)
    with_reminder = simulate_workflow(patient, config=fixed_delays(),
        coupled_config=replace(cc, deadline_escalation_enabled=True))
    assert next(e.time for e in with_reminder.events if e.kind is EventKind.CONFIRMED) == at(50)
    assert next(e.time for e in with_reminder.events if e.kind is EventKind.ESCALATED) == at(61)
    assert next(t.time for t in with_reminder.trace if t.kind == "prototype_deadline_escalation") == at(50)
    assert not any(t.kind == "prototype_deadline_escalation" for t in without.trace)
    assert without.events == with_reminder.events
    assert with_reminder.actions == ()
    assert not any(t.kind == "medication_ordered" for t in with_reminder.trace)


def test_configured_deadline_lead_moves_only_prototype_reminder():
    cc = replace(load_coupled_config(), contact_succeeds=False, deadline_escalation_enabled=True,
                 deadline_escalation_lead_minutes=20)
    result = simulate_workflow(course(), config=fixed_delays(), coupled_config=cc)
    assert next(t.time for t in result.trace if t.kind == "prototype_deadline_escalation") == at(40)
    assert result.medication_time is None


def test_late_confirming_reopening_is_already_an_actual_assessment():
    patient = course(((0, 170, 110), (15, 135, 85), (50, 170, 110)), cycle=50)
    result = simulate_workflow(patient, config=fixed_delays(
        recognition_minutes=(0, 0), identification_minutes=(0, 0),
        acknowledgment_minutes=(0, 0), medication_minutes=(5, 5)))
    assert result.medication_time == at(55)
    assert len(result.reassessments) == 1
    assert result.reassessments[0].actual_time == at(15)
    assert result.evaluation.episodes[0].deadline == at(60)
    assert result.evaluation.episodes[0].status == "timely_dose"


def test_withheld_decision_does_not_turn_acknowledgment_into_order():
    result = simulate_workflow(course(), config=fixed_delays(),
        coupled_config=replace(load_coupled_config(), treatment_authorized=False))
    assert [a.kind for a in result.actions] == [ActionKind.PROVIDER_ACKNOWLEDGED]
    assert not any(t.kind == "medication_ordered" for t in result.trace)
    assert result.no_dose_reason == "decision_withheld"


def test_recurrence_is_classified_only_by_engine_and_keeps_onset_clock():
    patient = course(((0, 170, 110), (15, 135, 85), (45, 170, 110)), cycle=15)
    result = simulate_workflow(patient, config=fixed_delays())
    assert len(result.evaluation.episodes) == 1
    assert result.evaluation.episodes[0].persistent
    assert result.evaluation.episodes[0].deadline == at(60)
    assert next(e.time for e in result.events if e.kind is EventKind.EPISODE_REOPENED) == at(45)
    assert next(e.time for e in result.events if e.kind is EventKind.CONFIRMED) == at(45)


def test_later_distinct_episode_has_its_own_dose_clock():
    patient = course(((0, 170, 110), (15, 135, 85), (90, 170, 110)), cycle=15)
    result = simulate_workflow(patient, config=fixed_delays())
    assert result.first_severe_time == T0
    assert result.medication_time == at(135)
    assert result.treatment_minutes == 45
    assert [ep.onset for ep in result.evaluation.episodes] == [T0, at(90)]
    assert result.evaluation.episodes[1].deadline == at(150)


def test_external_availability_is_not_restarted_at_a_later_episode():
    patient = course(((0, 170, 110), (15, 135, 85), (90, 170, 110)), cycle=15)
    cc = replace(load_coupled_config(), clinician_available_after_minutes=70)
    result = simulate_workflow(patient, config=fixed_delays(), coupled_config=cc)
    assert result.medication_time == at(135)  # Available since +70, not +90+70.


def test_zero_effect_has_identical_observations_actions_events_and_traces():
    for patient in generate_course_cohort(patients_per_scenario=1).values():
        pair = compare_patient_course(patient, prompt_effect=0)
        assert pair.baseline == replace(pair.tool, mode="baseline")


def test_paired_reproducibility_and_query_order_do_not_change_truth():
    patient = course()
    original = patient.points
    first = compare_patient_course(patient)
    patient.sample(at(73))
    patient.sample(at(2))
    assert patient.points == original
    assert compare_patient_course(patient) == first


def test_events_are_exact_tracker_replay_of_completed_inputs():
    result = simulate_workflow(course(), config=fixed_delays())
    tracker = EpisodeTracker(PROTOCOL)
    replayed = []
    inputs = sorted([*result.readings, *result.actions], key=lambda item: item.time)
    for minute in range(181):
        now = at(minute)
        # Scheduler processes readings, tick, then staff actions at a time tie.
        for item in inputs:
            if item.time == now and not hasattr(item, "kind"):
                replayed.extend(tracker.observe(item))
        replayed.extend(tracker.tick(now))
        for item in inputs:
            if item.time == now and hasattr(item, "kind"):
                replayed.extend(tracker.observe(item))
    assert tuple(replayed) == result.events
    assert sum(e.kind is EventKind.DOSE_RECORDED for e in result.events) == sum(a.kind is ActionKind.DOSE_GIVEN for a in result.actions)


def test_scenario_metadata_never_selects_treatment():
    a = simulate_workflow(course(scenario="persistent_severe"))
    b = simulate_workflow(course(scenario="spurious_severe"))
    assert a == b


def test_coupled_evaluation_does_not_use_archival_severe_repeat_helpers(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Archival repeat selector must not classify coupled patients")
    monkeypatch.setattr('htn_alert.workflow.find_severe_repeat_in_window', forbidden)
    monkeypatch.setattr('htn_alert.cohort_evaluation._has_severe_repeat_in_window', forbidden)
    result = evaluate_coupled_cohort({"P": course()})
    assert result.total_patients == 1
    assert result.baseline_events.persistent_patients == 1


def test_archival_projection_does_not_emit_dose_after_recorded_resolution():
    from htn_alert.generator import generate_bp_readings
    readings = generate_bp_readings("P", T0, scenario="persistent_severe", seed=44)
    result = simulate_workflow(readings, config=fixed_delays(medication_minutes=(100, 100)))
    assert result.medication_time is not None  # Explicitly a retained projection.
    assert not any(a.kind is ActionKind.DOSE_GIVEN for a in result.actions)


@pytest.mark.parametrize('subtype,delay', [('delayed', 16), ('missing_early', 30)])
@pytest.mark.parametrize('seed', [42, 43, 120, 121])
@pytest.mark.parametrize('mode', ['baseline', 'tool'])
def test_archival_subtype_replay_preserves_actual_times_without_inventing_measurements(subtype, delay, seed, mode):
    from htn_alert.generator import generate_bp_readings
    supplied = generate_bp_readings('P', T0, scenario='delayed_or_missing_repeat',
                                   delayed_repeat_subtype=subtype, seed=seed)
    result = simulate_workflow(supplied, mode=mode)
    task = result.reassessments[0]
    assert task.actual_time == result.first_severe_time + timedelta(minutes=delay)
    assert task.minutes_late == delay - 15
    assert task.source == 'archival_recorded'
    assert set(result.readings).issubset(set(supplied))
    assert all(b.time - a.time >= timedelta(minutes=15) for a,b in zip(result.readings, result.readings[1:]))
    assert any(e.kind is EventKind.CONFIRMED for e in result.events)
    assert any(e.kind is EventKind.EPISODE_CLOSED for e in result.events)
    assert not any(a.kind is ActionKind.DOSE_GIVEN for a in result.actions)


def test_all_patients_remain_visible_in_cohort_and_effect_sweep():
    cohort = generate_course_cohort(patients_per_scenario=3)
    assert {p.routine_interval_minutes for p in cohort.values()} == {15, 30, 60}
    result = evaluate_cohort(cohort)
    assert result.total_patients == len(result.baseline_events.patients) == len(result.tool_events.patients) == 24
    assert any(p.baseline.medication_time is None for p in result.patients)
    assert any(p.baseline.evaluation.patients[0].status == "nonpersistent" for p in result.patients)
    assert result.baseline_operations.patients == 24
    assert result.baseline_operations.no_dose_patients + sum(p.baseline.medication_time is not None for p in result.patients) == 24
    assert result.baseline_operations.completed_notifications > 0
    rows = run_coupled_sensitivity_analysis(cohort, effects=(0, 0.5))
    assert all(row.total_patients == 24 for row in rows)
    assert rows[0].average_medication_saved == 0
    assert rows[0].baseline_patient_rate == rows[0].tool_patient_rate
    assert rows[0].baseline_no_dose == rows[0].tool_no_dose


def test_no_dose_pair_difference_is_missing_not_zero():
    patient = course(((0, 170, 110), (50, 135, 85)))
    pair = compare_patient_course(patient, workflow_config=delays())
    assert pair.baseline.medication_time is None
    assert pair.tool.medication_time == at(45)
    assert pair.medication_minutes_saved is None
    result = evaluate_coupled_cohort({"P": patient}, workflow_config=delays())
    assert result.comparable_dose_pairs == 0
    assert result.average_medication_minutes_saved is None


@pytest.mark.parametrize("scenario,persistent,status", [
    ("non_hypertensive", 0, "no_episode"),
    ("mild_hypertension", 0, "no_episode"),
    ("borderline_severe", 0, "no_episode"),
    ("persistent_severe", 1, "not_timely"),
    ("nonpersistent_severe", 0, "nonpersistent"),
    ("recurrent_severe", 1, "not_timely"),
    ("delayed_or_missing_repeat", 1, "not_timely"),
    ("spurious_severe", 0, "nonpersistent"),
])
def test_documented_scenario_table_against_tracker(scenario, persistent, status):
    patient = generate_patient_course("P", T0, scenario, routine_interval_minutes=15)
    result = simulate_workflow(patient, config=fixed_delays(),
        coupled_config=replace(load_coupled_config(), treatment_authorized=False))
    assert result.evaluation.persistent_episodes == persistent
    assert result.evaluation.patients[0].status == status
    assert result.actions == tuple(a for a in result.actions if a.kind is not ActionKind.DOSE_GIVEN)


def test_same_resolving_course_can_change_observed_persistence():
    patient = course(((0, 170, 110), (15, 135, 85)))
    pair = compare_patient_course(patient, workflow_config=fixed_delays(readiness_minutes=(10, 10)), prompt_effect=1)
    assert pair.baseline.evaluation.episodes[0].persistent is True
    assert pair.tool.evaluation.episodes[0].persistent is False
    assert pair.baseline.medication_time is pair.tool.medication_time is None
    assert pair.medication_minutes_saved is None


def test_empty_coupled_cohort_does_not_create_a_rate():
    result = evaluate_coupled_cohort({})
    assert result.total_patients == 0
    assert result.baseline_events.patient_rate is None
    assert result.average_medication_minutes_saved is None


@pytest.mark.parametrize("kwargs", [{"mode": "invalid"}, {"prompt_effect": 1.1}, {"provider_pathway": "invalid"}])
def test_invalid_coupled_inputs_rejected(kwargs):
    with pytest.raises(ValueError):
        simulate_workflow(course(), **kwargs)
