
"""Tests for OB-Response workflow sensitivity analysis."""

from datetime import datetime

import pytest

from htn_alert.generator import generate_cohort
from htn_alert.sensitivity_analysis import (
    DEFAULT_EFFECTS,
    run_sensitivity_analysis,
)


@pytest.fixture(scope="module")
def cohort():
    return generate_cohort(
        patients_per_scenario=10,
        start_time=datetime(2026, 10, 26, 8, 0),
        seed=42,
    )


def test_default_effect_levels():
    assert DEFAULT_EFFECTS == (0.0, 0.25, 0.5, 0.75, 1.0)


def test_one_row_per_effect(cohort):
    results = run_sensitivity_analysis(cohort)

    assert len(results) == 5
    assert tuple(r.prompt_effect for r in results) == DEFAULT_EFFECTS


def test_cohort_coverage_remains_constant(cohort):
    results = run_sensitivity_analysis(cohort)

    assert all(r.total_patients == 80 for r in results)
    assert all(r.supported_patients == 20 for r in results)


def test_zero_effect_has_no_improvement(cohort):
    row = run_sensitivity_analysis(
        cohort, effects=(0.0,)
    )[0]

    assert row.average_recognition_saved == 0
    assert row.average_recheck_saved == 0
    assert row.average_notification_saved == 0
    assert row.average_medication_saved == 0
    assert row.baseline_within_60 == row.tool_within_60


def test_same_seed_is_reproducible(cohort):
    first = run_sensitivity_analysis(cohort, seed=42)
    second = run_sensitivity_analysis(cohort, seed=42)

    assert first == second


def test_baseline_values_constant_across_effect_levels(cohort):
    results = run_sensitivity_analysis(cohort)

    assert len({r.baseline_within_60 for r in results}) == 1
    assert len({r.baseline_recheck_lateness for r in results}) == 1


def test_prompt_effect_does_not_worsen_projected_recheck(cohort):
    results = run_sensitivity_analysis(cohort)

    for row in results:
        assert row.tool_recheck_lateness <= row.baseline_recheck_lateness


def test_recheck_improvement_nondecreasing(cohort):
    results = run_sensitivity_analysis(cohort)

    improvements = [r.average_recheck_saved for r in results]

    assert improvements == sorted(improvements)


@pytest.mark.parametrize("invalid_effect", [-0.1, 1.1])
def test_invalid_effect_is_rejected(cohort, invalid_effect):
    with pytest.raises(ValueError):
        run_sensitivity_analysis(
            cohort,
            effects=(invalid_effect,),
        )


def test_empty_cohort_returns_missing_averages():
    results = run_sensitivity_analysis(
        {},
        effects=(0.0, 0.5),
    )

    assert len(results) == 2
    assert all(r.total_patients == 0 for r in results)
    assert all(r.supported_patients == 0 for r in results)
    assert all(r.average_recheck_saved is None for r in results)
    assert all(r.average_medication_saved is None for r in results)


def test_default_sensitivity_matches_pre_refactor_results(cohort):
    """Config extraction must not silently change the assumed simulation model."""
    rows = run_sensitivity_analysis(cohort)
    assert [r.supported_patients for r in rows] == [20] * 5
    assert [r.average_recheck_saved for r in rows] == [0.0, 2.35, 4.35, 6.5, 8.85]
    assert [r.average_medication_saved for r in rows] == [0.0, 3.75, 7.45, 11.05, 14.8]
    assert [r.tool_recheck_lateness for r in rows] == [8.85, 6.5, 4.5, 2.35, 0.0]
