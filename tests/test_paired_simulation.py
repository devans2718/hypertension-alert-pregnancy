
"""Tests for paired baseline-versus-OB-Response simulations."""

from datetime import datetime

import pytest

from htn_alert.generator import generate_bp_readings
from htn_alert.paired_simulation import compare_workflows


@pytest.fixture
def patient_readings():
    return generate_bp_readings(
        patient_id="PAIR-TEST-001",
        start_time=datetime(2026, 10, 26, 8, 0),
        scenario="persistent_severe",
        seed=44,
    )


def test_paired_simulation_is_reproducible(patient_readings):
    first = compare_workflows(patient_readings, seed=42)
    second = compare_workflows(patient_readings, seed=42)

    assert first == second


def test_same_recorded_bp_timeline(patient_readings):
    result = compare_workflows(patient_readings)

    assert (
        result.baseline.first_severe_time
        == result.tool.first_severe_time
    )
    assert (
        result.baseline.confirming_reading_time
        == result.tool.confirming_reading_time
    )


def test_input_readings_are_not_modified(patient_readings):
    original = list(patient_readings)

    compare_workflows(patient_readings)

    assert patient_readings == original


@pytest.mark.parametrize(
    "pathway",
    ["direct", "collaboration_required", "provider_uncertain"],
)
def test_all_communication_pathways(patient_readings, pathway):
    result = compare_workflows(
        patient_readings,
        provider_pathway=pathway,
    )

    assert result.provider_pathway == pathway


def test_no_improvement_when_effect_is_zero(patient_readings):
    result = compare_workflows(
        patient_readings,
        prompt_effect=0.0,
    )

    assert result.recognition_minutes_saved == 0
    assert result.projected_recheck_minutes_saved == 0
    assert result.provider_notification_minutes_saved == 0
    assert result.medication_minutes_saved == 0


def test_improved_recognition_with_assumed_effect(patient_readings):
    result = compare_workflows(
        patient_readings,
        prompt_effect=0.5,
        seed=42,
    )

    assert result.recognition_minutes_saved >= 0


def test_missing_recheck_is_recorded_as_missing(patient_readings):
    result = compare_workflows(
        patient_readings,
        missing_recheck=True,
    )

    assert result.baseline.recheck_plan.missing is True
    assert result.tool.recheck_plan.missing is True

    assert result.projected_recheck_minutes_saved is None


def test_projected_rechecks_do_not_change_recorded_bp(
    patient_readings,
):
    result = compare_workflows(patient_readings)

    assert (
        result.baseline.confirming_reading_time
        == result.tool.confirming_reading_time
    )

    assert (
        result.baseline.recheck_plan.projected_time
        is not None
    )


def test_treatment_benchmark_starts_at_first_severe(patient_readings):
    result = compare_workflows(patient_readings)

    baseline_minutes = (
        result.baseline.medication_time
        - result.baseline.first_severe_time
    ).total_seconds() / 60

    assert baseline_minutes == result.baseline.treatment_minutes


def test_invalid_provider_pathway_rejected(patient_readings):
    with pytest.raises(ValueError):
        compare_workflows(
            patient_readings,
            provider_pathway="invalid",
        )


def test_empty_patient_stream_rejected():
    with pytest.raises(ValueError):
        compare_workflows([])
