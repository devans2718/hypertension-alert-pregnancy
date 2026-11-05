"""New simulation controls stay configurable and explicitly sourced."""

import pytest

from htn_alert.simulation_config import (
    GENERATOR_PATH, WORKFLOW_PATH, load_course_config, load_coupled_config,
)


def edited(tmp_path, original, old, new):
    text = original.read_text()
    assert old in text
    path = tmp_path / original.name
    path.write_text(text.replace(old, new))
    return path


def test_coupled_configuration_loads_independently_of_cwd(tmp_path, monkeypatch):
    course, workflow = load_course_config(), load_coupled_config()
    monkeypatch.chdir(tmp_path)
    assert load_course_config() == course
    assert load_coupled_config() == workflow
    assert course.minimum_measurement_minutes == 15
    assert course.routine_intervals_minutes == (15, 30, 60)
    assert workflow.deadline_escalation_enabled is False
    assert workflow.provider_search_overlaps_reassessment is False


def test_alternate_course_phases_and_cycles_load(tmp_path):
    path = edited(tmp_path, GENERATOR_PATH, '[[0, true], [90, false]]', '[[0, true], [120, false]]')
    assert load_course_config(path).profiles['delayed_or_missing_repeat'] == ((0, True), (120, False))
    path = edited(tmp_path, GENERATOR_PATH, '[15, 30, 60]', '[30, 60]')
    assert load_course_config(path).routine_intervals_minutes == (30, 60)


@pytest.mark.parametrize('old,new', [
    ('routine_intervals_minutes = [15, 30, 60]', 'routine_intervals_minutes = []'),
    ('routine_intervals_minutes = [15, 30, 60]', 'routine_intervals_minutes = [10]'),
    ('minimum_measurement_minutes = 15', 'minimum_measurement_minutes = 0'),
    ('onset_minutes = [0]', 'onset_minutes = []'),
    ('resolved_bp = [135, 85]', 'resolved_bp = [135]'),
    ('[[0, true], [90, false]]', '[[0, true], [0, false]]'),
    ('[[0, true], [90, false]]', '[[0, true], [90, 0]]'),
    ('[[0, true], [90, false]]', '[[0, true], [90]]'),
])
def test_bad_course_settings_rejected(tmp_path, old, new):
    with pytest.raises(ValueError):
        load_course_config(edited(tmp_path, GENERATOR_PATH, old, new))


@pytest.mark.parametrize('old,new', [
    ('clock_step_minutes = 1', 'clock_step_minutes = 2'),
    ('deadline_escalation_lead_minutes = 10', 'deadline_escalation_lead_minutes = -1'),
    ('provider_search_overlaps_reassessment = false', 'provider_search_overlaps_reassessment = 1'),
    ('decision_minutes = [0, 0]', 'decision_minutes = [-1, 1]'),
    ('resolution_blocks_dose = true', 'resolution_blocks_dose = false'),
])
def test_bad_workflow_settings_rejected(tmp_path, old, new):
    with pytest.raises(ValueError):
        load_coupled_config(edited(tmp_path, WORKFLOW_PATH, old, new))


@pytest.mark.parametrize('path', [GENERATOR_PATH, WORKFLOW_PATH])
def test_every_parameter_including_new_controls_has_source(path):
    for line in path.read_text().splitlines():
        if '=' in line.split('#', 1)[0]:
            assert any(f'# {source}:' in line for source in ('Pitch', 'Lit', 'Assume')), line
