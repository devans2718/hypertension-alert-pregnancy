"""Shared protocol integration and deliberately limited repeat eligibility."""

import csv
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from htn_alert.cohort_evaluation import evaluate_cohort
from htn_alert.contract import Reading
from htn_alert.export_data import export_cohort_csv
from htn_alert.generator import generate_bp_readings, summarize_cohort
from htn_alert.paired_simulation import compare_workflows
from htn_alert.protocol import DEFAULT_PATH, load_protocol
from htn_alert.rules import is_severe
from htn_alert.workflow import find_severe_repeat_in_window, simulate_recheck_plan, simulate_workflow

START = datetime(2026, 10, 26, 8)


def reading(minute, systolic, diastolic):
    return Reading('P', START + timedelta(minutes=minute), systolic, diastolic)


@pytest.fixture
def alternate_protocol(tmp_path):
    """Test-only thresholds/windows; the shared protocol file is unchanged."""
    text = DEFAULT_PATH.read_text()
    for old, new in [
        ('systolic = 160', 'systolic = 170'),
        ('diastolic = 110', 'diastolic = 120'),
        ('min_minutes = 15', 'min_minutes = 20'),
        ('max_minutes = 60', 'max_minutes = 45'),
        ('target_minutes = 60', 'target_minutes = 35'),
    ]:
        text = text.replace(old, new)
    path = tmp_path / 'protocol.toml'
    path.write_text(text)
    return load_protocol(path)


@pytest.mark.parametrize('systolic,diastolic,expected', [
    (169, 119, False), (170, 80, True), (130, 120, True),
])
def test_shared_rule_uses_loaded_thresholds(alternate_protocol, systolic, diastolic, expected):
    assert is_severe(reading(0, systolic, diastolic), alternate_protocol) is expected


def test_generator_baseline_validation_uses_shared_protocol(alternate_protocol):
    # A baseline formerly rejected by the hard-coded 160 cutoff is valid here.
    readings = generate_bp_readings('P', START, baseline_systolic=165,
        protocol=alternate_protocol)
    assert readings
    with pytest.raises(ValueError, match='Baselines'):
        generate_bp_readings('P', START, baseline_systolic=170,
            protocol=alternate_protocol)


def test_routine_caps_follow_shared_thresholds():
    protocol = replace(load_protocol(), severe_systolic=150, severe_diastolic=100)
    readings = generate_bp_readings('P', START, scenario='borderline_severe', protocol=protocol)
    assert all(r.systolic < 150 and r.diastolic < 100 for r in readings)
    assert not any(is_severe(r, protocol) for r in readings)


def test_summary_uses_shared_protocol(alternate_protocol):
    cohort = {'P': [reading(0, 165, 115), reading(20, 170, 80), reading(40, 130, 120)]}
    assert summarize_cohort(cohort, protocol=alternate_protocol) == {
        'patients': 1, 'total_readings': 3, 'severe_readings': 2,
        'patients_with_severe_readings': 1,
    }


@pytest.mark.parametrize('minute,expected', [(14, False), (15, True), (60, True), (61, False)])
def test_existing_severe_repeat_window_boundaries(minute, expected):
    first, repeat = reading(0, 160, 90), reading(minute, 130, 110)
    found = find_severe_repeat_in_window([repeat, first])
    assert (found == repeat) is expected


@pytest.mark.parametrize('minute,expected', [(15, False), (20, True), (45, True), (46, False)])
def test_existing_repeat_uses_loaded_window(alternate_protocol, minute, expected):
    repeat = reading(minute, 170, 90)
    found = find_severe_repeat_in_window([reading(0, 170, 90), repeat], alternate_protocol)
    assert (found == repeat) is expected


def test_existing_repeat_check_is_not_full_persistence():
    # Do not decide episode boundaries or SMFM persistence here (issue #9).
    repeat = reading(45, 165, 90)
    readings = [reading(0, 160, 90), reading(10, 130, 85), repeat]
    assert find_severe_repeat_in_window(readings) == repeat


@pytest.mark.parametrize('readings', [[], [reading(0, 120, 80)], [reading(0, 160, 90)]])
def test_no_existing_severe_repeat_returns_none(readings):
    assert find_severe_repeat_in_window(readings) is None


@pytest.mark.parametrize('subtype', ['delayed', 'missing_early'])
def test_delayed_subtypes_remain_unsupported_until_episode_integration(subtype):
    readings = generate_bp_readings('P', START, scenario='delayed_or_missing_repeat',
        delayed_repeat_subtype=subtype)
    assert find_severe_repeat_in_window(readings) is None
    with pytest.raises(ValueError, match='existing severe repeat'):
        simulate_workflow(readings)
    result = evaluate_cohort({'P': readings})
    assert result.total_patients == 1
    assert result.supported_patients == 0
    assert result.severe_without_repeat_in_window == result.severe_without_qualifying_repeat == 1
    assert result.average_baseline_treatment_minutes is None
    assert 'issue #9' in result.patients[0].reason


def test_workflow_and_cohort_use_one_loaded_protocol(alternate_protocol):
    # The first observation was severe under the old thresholds, but not these.
    readings = [reading(0, 160, 110), reading(5, 170, 100),
                reading(20, 169, 119), reading(25, 130, 120)]
    paired = compare_workflows(readings, protocol=alternate_protocol)
    result = paired.baseline
    assert result.first_severe_time == START + timedelta(minutes=5)
    assert result.severe_repeat_in_window_time == START + timedelta(minutes=25)
    assert result.confirming_reading_time == result.severe_repeat_in_window_time
    assert result.recheck_plan.target_time == START + timedelta(minutes=25)
    assert result.treatment_minutes == 49
    assert result.treatment_target == timedelta(minutes=35)
    assert result.within_treatment_target is result.within_60_minutes is False
    assert paired.tool.treatment_target == result.treatment_target
    evaluation = evaluate_cohort({'P': readings}, protocol=alternate_protocol)
    assert evaluation.supported_patients == 1
    assert evaluation.patients[0].severe_readings == 2
    assert evaluation.average_baseline_treatment_minutes == result.treatment_minutes
    assert evaluation.supported_baseline_within_60 == 0


def test_result_keeps_target_used_during_simulation(alternate_protocol, monkeypatch):
    readings = [reading(0, 170, 90), reading(20, 170, 90)]
    result = simulate_workflow(readings, protocol=alternate_protocol)
    monkeypatch.setattr('htn_alert.workflow.load_protocol', lambda: load_protocol())
    assert result.treatment_target == timedelta(minutes=35)
    assert result.within_treatment_target is False


@pytest.mark.parametrize('missing', [False, True])
def test_recheck_projection_uses_loaded_target(alternate_protocol, missing):
    result = simulate_recheck_plan(START, START + timedelta(minutes=5),
        protocol=alternate_protocol, missing=missing)
    assert result.target_time == START + timedelta(minutes=20)


def test_csv_export_uses_shared_protocol(tmp_path):
    protocol = replace(load_protocol(), severe_systolic=200, severe_diastolic=140)
    path = tmp_path / 'synthetic.csv'
    export_cohort_csv(patients_per_scenario=1, output_path=path, protocol=protocol)
    with path.open(newline='') as f:
        rows = list(csv.DictReader(f))
    assert len({r['patient_id'] for r in rows}) == 8
    assert any(int(r['systolic']) >= 160 for r in rows)
    assert all(r['severe'] == 'False' for r in rows)
