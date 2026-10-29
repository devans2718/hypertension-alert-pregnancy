"""Configuration experiments use synthetic values, not new clinical guidance."""

from datetime import datetime, timedelta

import pytest

from htn_alert.generator import generate_bp_readings
from htn_alert.protocol import load_protocol
from htn_alert.rules import is_severe
from htn_alert.simulation_config import (
    GENERATOR_PATH,
    WORKFLOW_PATH,
    load_generator_config,
    load_workflow_config,
)
from htn_alert.workflow import simulate_workflow

START = datetime(2026, 10, 26, 8)


def edited_config(tmp_path, original, *replacements):
    """Vary test inputs without changing the repository's shared assumptions."""
    text = original.read_text()
    for old, new in replacements:
        assert old in text
        text = text.replace(old, new)
    path = tmp_path / original.name
    path.write_text(text)
    return path


def test_default_generator_config_loads():
    config = load_generator_config()
    assert (config.baseline_systolic, config.baseline_diastolic) == (120, 80)
    assert config.systolic_variation == (-5, 5)
    assert config.onset_minutes == (45, 60, 75, 90)
    assert config.scenario_baselines['mild_hypertension'] == (145, 95)
    assert config.delayed_repeat_subtypes['delayed'].after_minutes == 16
    assert config.delayed_repeat_subtypes['missing_early'].after_minutes == 30


def test_default_workflow_config_loads():
    config = load_workflow_config()
    assert config.recognition_minutes == (3, 15)
    assert config.identification_minutes == (5, 16)
    assert config.acknowledgment_minutes == (3, 10)
    assert config.medication_minutes == (12, 28)
    assert config.collaboration_minutes == (5, 12)
    assert config.uncertainty_minutes == (8, 18)
    assert config.readiness_minutes == (0, 18)
    assert config.recheck_seed_offset == 1000


def test_config_paths_are_independent_of_working_directory(tmp_path, monkeypatch):
    expected_generator = load_generator_config()
    expected_workflow = load_workflow_config()
    monkeypatch.chdir(tmp_path)
    assert load_generator_config() == expected_generator
    assert load_workflow_config() == expected_workflow


def test_alternate_generator_defaults_and_variation_are_used(tmp_path):
    path = edited_config(tmp_path, GENERATOR_PATH,
        ('duration_hours = 3', 'duration_hours = 1'),
        ('interval_minutes = 15', 'interval_minutes = 20'),
        ('baseline_systolic = 120', 'baseline_systolic = 125'),
        ('baseline_diastolic = 80', 'baseline_diastolic = 85'),
        ('systolic_variation = [-5, 5]', 'systolic_variation = [0, 0]'),
        ('diastolic_variation = [-4, 4]', 'diastolic_variation = [0, 0]'),
    )
    readings = generate_bp_readings('P', START, config=load_generator_config(path))
    assert [r.time for r in readings] == [START + timedelta(minutes=m) for m in (0, 20, 40, 60)]
    assert all((r.systolic, r.diastolic) == (125, 85) for r in readings)
    # Explicit caller overrides keep working as they did before config extraction.
    overridden = generate_bp_readings('P', START, baseline_systolic=130,
        config=load_generator_config(path))
    assert all(r.systolic == 130 for r in overridden)


def test_alternate_onset_and_scenario_values_are_used(tmp_path):
    path = edited_config(tmp_path, GENERATOR_PATH,
        ('minutes = [45, 60, 75, 90]', 'minutes = [60]'),
        ('systolic = [162, 178]', 'systolic = [180, 180]'),
        ('diastolic = [108, 118]', 'diastolic = [120, 120]'),
        ('systolic = [125, 145]', 'systolic = [130, 130]'),
        ('after_minutes = 10', 'after_minutes = 11'),
    )
    readings = generate_bp_readings('P', START, scenario='nonpersistent_severe',
        config=load_generator_config(path))
    onset = next(r for r in readings if is_severe(r, load_protocol()))
    assert onset.time == START + timedelta(minutes=60)
    assert (onset.systolic, onset.diastolic) == (180, 120)
    repeat = next(r for r in readings if r.time > onset.time)
    assert repeat.time == onset.time + timedelta(minutes=11)
    assert repeat.systolic == 130


def test_alternate_scenario_baseline_is_used(tmp_path):
    path = edited_config(tmp_path, GENERATOR_PATH,
        ('baseline = [145, 95]', 'baseline = [142, 92]'),
        ('systolic_variation = [-5, 5]', 'systolic_variation = [0, 0]'),
        ('diastolic_variation = [-4, 4]', 'diastolic_variation = [0, 0]'),
    )
    readings = generate_bp_readings('P', START, scenario='mild_hypertension',
        config=load_generator_config(path))
    assert all((r.systolic, r.diastolic) == (142, 92) for r in readings)


def test_alternate_delayed_subtype_default_is_used(tmp_path):
    path = edited_config(tmp_path, GENERATOR_PATH,
        ('default_subtype = "delayed"', 'default_subtype = "missing_early"'),
    )
    readings = generate_bp_readings('P', START, scenario='delayed_or_missing_repeat',
        config=load_generator_config(path))
    first = next(r for r in readings if is_severe(r, load_protocol()))
    repeat = next(r for r in readings if r.time > first.time)
    assert repeat.time - first.time == timedelta(minutes=30)


@pytest.mark.parametrize('pathway,extra', [
    ('direct', 0), ('collaboration_required', 2), ('provider_uncertain', 2),
])
def test_alternate_workflow_delays_are_used(tmp_path, pathway, extra):
    path = edited_config(tmp_path, WORKFLOW_PATH,
        ('[3, 15]', '[2, 2]'), ('[5, 16]', '[2, 2]'),
        ('[3, 10]', '[2, 2]'), ('[12, 28]', '[2, 2]'),
        ('[5, 12]', '[2, 2]'), ('[8, 18]', '[2, 2]'),
        ('[0, 18]', '[2, 2]'),
    )
    readings = generate_bp_readings('P', START, scenario='persistent_severe')
    result = simulate_workflow(readings, provider_pathway=pathway,
        config=load_workflow_config(path))
    assert result.recognition_delay_minutes == 2
    assert result.treatment_minutes == 21 + extra
    assert result.recheck_plan.minutes_late == 2


@pytest.mark.parametrize('old,new', [
    ('systolic_variation = [-5, 5]', 'systolic_variation = [5, -5]'),
    ('minutes = [45, 60, 75, 90]', 'minutes = []'),
    ('default_subtype = "delayed"', 'default_subtype = "unknown"'),
    ('cohort_subtypes = ["missing_early", "delayed"]', 'cohort_subtypes = []'),
    ('systolic = [162, 178]', 'systolic = [-1, 178]'),
])
def test_invalid_generator_config_rejected(tmp_path, old, new):
    with pytest.raises(ValueError):
        load_generator_config(edited_config(tmp_path, GENERATOR_PATH, (old, new)))


@pytest.mark.parametrize('value', ['[-1, 5]', '[15, 3]', '[true, 15]'])
def test_invalid_workflow_range_rejected(tmp_path, value):
    path = edited_config(tmp_path, WORKFLOW_PATH, ('[3, 15]', value))
    with pytest.raises(ValueError, match='recognition_minutes'):
        load_workflow_config(path)


@pytest.mark.parametrize('path', [GENERATOR_PATH, WORKFLOW_PATH])
def test_each_simulation_parameter_has_a_source(path):
    for line in path.read_text().splitlines():
        if '=' in line.split('#', 1)[0]:
            assert any(f'# {source}:' in line for source in ('Pitch', 'Lit', 'Assume')), line
