
"""Tests for the OB-Response synthetic cohort evaluation.

Verifies:
- Complete accounting of synthetic patients
- Supported and unsupported workflow scenarios
- Correct handling of patients without severe BP
- Reproducible baseline-versus-tool comparisons
- Zero intervention effect
- Cohort-level averages
- Empty cohorts
- Invalid parameters

These are engineering tests, not validation of clinical effectiveness.
"""

from datetime import datetime

import pytest

from htn_alert.cohort_evaluation import evaluate_cohort
from htn_alert.generator import generate_cohort


@pytest.fixture
def cohort():
    """Generate a reproducible 80-patient synthetic cohort."""
    return generate_cohort(
        patients_per_scenario=10,
        start_time=datetime(2026, 10, 26, 8, 0),
        seed=42,
    )


def test_total_patients_accounted_for(cohort):
    result = evaluate_cohort(cohort)

    assert result.total_patients == 80
    assert result.supported_patients + result.unsupported_patients == 80
    assert len(result.patients) == 80


def test_patients_with_severe_bp_counted(cohort):
    result = evaluate_cohort(cohort)

    assert result.patients_with_severe_bp == 50
    assert result.no_severe_bp_patients == 30


def test_supported_and_unsupported_counts(cohort):
    result = evaluate_cohort(cohort)

    assert result.supported_patients == 20
    assert result.unsupported_patients == 60

    assert (
        result.no_severe_bp_patients
        + result.severe_without_qualifying_repeat
        + result.supported_patients
        == result.total_patients
    )


def test_unsupported_patients_have_reasons(cohort):
    result = evaluate_cohort(cohort)

    unsupported = [
        patient
        for patient in result.patients
        if not patient.supported
    ]

    assert len(unsupported) == 60
    assert all(patient.reason for patient in unsupported)


def test_supported_patients_have_timing_results(cohort):
    result = evaluate_cohort(cohort)

    supported = [
        patient
        for patient in result.patients
        if patient.supported
    ]

    assert len(supported) == 20

    for patient in supported:
        assert patient.baseline_treatment_minutes is not None
        assert patient.tool_treatment_minutes is not None
        assert patient.baseline_recheck_minutes_late is not None
        assert patient.tool_recheck_minutes_late is not None


def test_reproducible_evaluation(cohort):
    first = evaluate_cohort(
        cohort,
        prompt_effect=0.5,
        seed=42,
    )

    second = evaluate_cohort(
        cohort,
        prompt_effect=0.5,
        seed=42,
    )

    assert first == second


def test_zero_prompt_effect_produces_no_improvement(cohort):
    result = evaluate_cohort(
        cohort,
        prompt_effect=0.0,
        seed=42,
    )

    assert result.average_recognition_minutes_saved == 0
    assert result.average_projected_recheck_minutes_saved == 0
    assert result.average_notification_minutes_saved == 0
    assert result.average_medication_minutes_saved == 0

    assert (
        result.average_baseline_treatment_minutes
        == result.average_tool_treatment_minutes
    )


def test_assumed_prompt_effect_cannot_increase_recheck_lateness(cohort):
    result = evaluate_cohort(
        cohort,
        prompt_effect=0.5,
        seed=42,
    )

    assert (
        result.average_tool_recheck_minutes_late
        <= result.average_baseline_recheck_minutes_late
    )


def test_average_uses_supported_patients_only(cohort):
    result = evaluate_cohort(cohort)

    supported = [
        patient
        for patient in result.patients
        if patient.supported
    ]

    expected = sum(
        patient.recognition_minutes_saved
        for patient in supported
    ) / len(supported)

    assert result.average_recognition_minutes_saved == pytest.approx(
        expected
    )


def test_medication_counts_do_not_exceed_supported_patients(cohort):
    result = evaluate_cohort(cohort)

    assert (
        0
        <= result.supported_baseline_within_60
        <= result.supported_patients
    )

    assert (
        0
        <= result.supported_tool_within_60
        <= result.supported_patients
    )


def test_empty_cohort_handled():
    result = evaluate_cohort({})

    assert result.total_patients == 0
    assert result.supported_patients == 0
    assert result.unsupported_patients == 0

    assert result.average_recognition_minutes_saved is None
    assert result.average_projected_recheck_minutes_saved is None
    assert result.average_medication_minutes_saved is None

    assert result.patients == ()


@pytest.mark.parametrize("invalid_effect", [-0.1, 1.1])
def test_invalid_prompt_effect_rejected(invalid_effect):
    with pytest.raises(ValueError):
        evaluate_cohort({}, prompt_effect=invalid_effect)


def test_patient_ids_must_match_readings(cohort):
    first_patient_id = next(iter(cohort))

    invalid_cohort = dict(cohort)
    invalid_cohort[first_patient_id] = cohort[first_patient_id + "X"] if (
        first_patient_id + "X" in cohort
    ) else cohort[first_patient_id][1:]

    # Explicitly attach readings from another patient.
    another_patient_id = next(
        pid for pid in cohort if pid != first_patient_id
    )
    invalid_cohort[first_patient_id] = cohort[another_patient_id]

    with pytest.raises(ValueError):
        evaluate_cohort(invalid_cohort)
