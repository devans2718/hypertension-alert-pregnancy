
"""Tests for the OB-Response synthetic staff workflow simulator.

Covers:
- Reproducible synthetic workflows
- Three provider communication pathways
- Baseline versus OB-Response comparisons
- Provider acknowledgment and medication timing
- Fifteen-minute BP reassessment projections
- Missing reassessment handling

All simulated delays are assumptions, not measured hospital data.
"""

from datetime import datetime, timedelta

import pytest

from htn_alert.contract import ActionKind
from htn_alert.generator import generate_bp_readings
from htn_alert.workflow import simulate_workflow, simulate_recheck_plan


# =========================================================
# SHARED TEST PATIENT
# =========================================================

@pytest.fixture
def patient_readings():
    return generate_bp_readings(
        patient_id="TEST-001",
        start_time=datetime(2026, 10, 26, 8, 0),
        scenario="persistent_severe",
        seed=44,
    )


# =========================================================
# PART 1: EXISTING STAFF WORKFLOW TESTS
# =========================================================

def test_reproducible_results(patient_readings):
    first = simulate_workflow(patient_readings, seed=42)
    second = simulate_workflow(patient_readings, seed=42)

    assert first == second


def test_first_severe_starts_treatment_clock(patient_readings):
    result = simulate_workflow(patient_readings, seed=42)

    assert result.first_severe_time == datetime(2026, 10, 26, 9, 0)
    assert result.confirming_reading_time == datetime(
        2026, 10, 26, 9, 15
    )


def test_actions_are_in_correct_order(patient_readings):
    result = simulate_workflow(patient_readings)

    assert result.recognition_time >= result.first_severe_time
    assert (
        result.provider_identified_time
        >= result.confirming_reading_time
    )
    assert (
        result.provider_notified_time
        >= result.provider_identified_time
    )
    assert (
        result.provider_acknowledged_time
        >= result.provider_notified_time
    )
    assert (
        result.medication_time
        >= result.provider_acknowledged_time
    )

    assert (
        result.actions[0].kind
        == ActionKind.PROVIDER_ACKNOWLEDGED
    )
    assert result.actions[1].kind == ActionKind.DOSE_GIVEN


@pytest.mark.parametrize(
    "pathway",
    ["direct", "collaboration_required", "provider_uncertain"],
)
def test_all_provider_pathways_run(patient_readings, pathway):
    result = simulate_workflow(
        patient_readings,
        provider_pathway=pathway,
        seed=42,
    )

    assert result.provider_pathway == pathway


def test_collaboration_delay_is_separate(patient_readings):
    direct = simulate_workflow(
        patient_readings,
        provider_pathway="direct",
        seed=42,
    )

    collaboration = simulate_workflow(
        patient_readings,
        provider_pathway="collaboration_required",
        seed=42,
    )

    assert direct.collaboration_delay_minutes == 0
    assert collaboration.collaboration_delay_minutes > 0
    assert (
        collaboration.provider_notified_time
        > direct.provider_notified_time
    )


def test_provider_uncertainty_adds_identification_delay(
    patient_readings,
):
    direct = simulate_workflow(
        patient_readings,
        provider_pathway="direct",
        seed=42,
    )

    uncertain = simulate_workflow(
        patient_readings,
        provider_pathway="provider_uncertain",
        seed=42,
    )

    assert (
        uncertain.provider_identification_delay_minutes
        > direct.provider_identification_delay_minutes
    )


def test_tool_preserves_existing_bp_timestamps(patient_readings):
    baseline = simulate_workflow(
        patient_readings,
        mode="baseline",
        seed=42,
    )

    assisted = simulate_workflow(
        patient_readings,
        mode="tool",
        seed=42,
    )

    assert (
        baseline.first_severe_time
        == assisted.first_severe_time
    )
    assert (
        baseline.confirming_reading_time
        == assisted.confirming_reading_time
    )


def test_tool_reduces_assumed_delays(patient_readings):
    baseline = simulate_workflow(
        patient_readings,
        mode="baseline",
        seed=42,
    )

    assisted = simulate_workflow(
        patient_readings,
        mode="tool",
        seed=42,
        prompt_effect=0.5,
    )

    assert (
        assisted.recognition_delay_minutes
        <= baseline.recognition_delay_minutes
    )
    assert (
        assisted.provider_identification_delay_minutes
        <= baseline.provider_identification_delay_minutes
    )


def test_zero_prompt_effect_changes_nothing(patient_readings):
    baseline = simulate_workflow(
        patient_readings,
        mode="baseline",
        seed=42,
    )

    assisted = simulate_workflow(
        patient_readings,
        mode="tool",
        seed=42,
        prompt_effect=0.0,
    )

    assert baseline.medication_time == assisted.medication_time
    assert baseline.recognition_time == assisted.recognition_time


def test_empty_readings_rejected():
    with pytest.raises(ValueError):
        simulate_workflow([])


def test_invalid_provider_pathway_rejected(patient_readings):
    with pytest.raises(ValueError):
        simulate_workflow(
            patient_readings,
            provider_pathway="unknown",
        )


def test_invalid_prompt_effect_rejected(patient_readings):
    with pytest.raises(ValueError):
        simulate_workflow(
            patient_readings,
            prompt_effect=1.5,
        )


# =========================================================
# PART 2: FIFTEEN-MINUTE REASSESSMENT TESTS
# =========================================================

def test_recheck_target_is_15_minutes():
    first = datetime(2026, 10, 26, 9, 0)
    recognition = datetime(2026, 10, 26, 9, 5)

    result = simulate_recheck_plan(
        first_severe_time=first,
        recognition_time=recognition,
        seed=42,
    )

    assert result.target_time == first + timedelta(minutes=15)


def test_projected_recheck_never_precedes_target():
    first = datetime(2026, 10, 26, 9, 0)
    recognition = datetime(2026, 10, 26, 9, 4)

    result = simulate_recheck_plan(
        first_severe_time=first,
        recognition_time=recognition,
        seed=42,
    )

    assert result.projected_time is not None
    assert result.projected_time >= result.target_time


def test_projected_recheck_never_precedes_recognition():
    first = datetime(2026, 10, 26, 9, 0)
    recognition = datetime(2026, 10, 26, 9, 24)

    result = simulate_recheck_plan(
        first_severe_time=first,
        recognition_time=recognition,
        seed=42,
    )

    assert result.projected_time is not None
    assert result.projected_time >= recognition


def test_recheck_simulation_is_reproducible():
    first = datetime(2026, 10, 26, 9, 0)
    recognition = datetime(2026, 10, 26, 9, 7)

    first_result = simulate_recheck_plan(
        first_severe_time=first,
        recognition_time=recognition,
        seed=42,
    )

    second_result = simulate_recheck_plan(
        first_severe_time=first,
        recognition_time=recognition,
        seed=42,
    )

    assert first_result == second_result


def test_tool_can_reduce_projected_recheck_lateness():
    first = datetime(2026, 10, 26, 9, 0)
    recognition = datetime(2026, 10, 26, 9, 5)

    baseline = simulate_recheck_plan(
        first_severe_time=first,
        recognition_time=recognition,
        mode="baseline",
        seed=42,
    )

    assisted = simulate_recheck_plan(
        first_severe_time=first,
        recognition_time=recognition,
        mode="tool",
        seed=42,
        prompt_effect=0.5,
    )

    assert baseline.minutes_late is not None
    assert assisted.minutes_late is not None
    assert assisted.minutes_late <= baseline.minutes_late


def test_missing_recheck_has_no_projected_time():
    first = datetime(2026, 10, 26, 9, 0)
    recognition = datetime(2026, 10, 26, 9, 5)

    result = simulate_recheck_plan(
        first_severe_time=first,
        recognition_time=recognition,
        missing=True,
    )

    assert result.missing is True
    assert result.projected_time is None
    assert result.minutes_late is None


def test_recheck_does_not_change_recorded_confirmation(
    patient_readings,
):
    baseline = simulate_workflow(
        patient_readings,
        mode="baseline",
        seed=42,
    )

    assisted = simulate_workflow(
        patient_readings,
        mode="tool",
        seed=42,
    )

    assert (
        baseline.confirming_reading_time
        == assisted.confirming_reading_time
    )


def test_recheck_zero_prompt_effect_has_no_benefit():
    first = datetime(2026, 10, 26, 9, 0)
    recognition = datetime(2026, 10, 26, 9, 5)

    baseline = simulate_recheck_plan(
        first_severe_time=first,
        recognition_time=recognition,
        mode="baseline",
        seed=42,
    )

    assisted = simulate_recheck_plan(
        first_severe_time=first,
        recognition_time=recognition,
        mode="tool",
        seed=42,
        prompt_effect=0.0,
    )

    assert assisted == baseline
