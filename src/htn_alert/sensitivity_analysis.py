
"""Sensitivity analysis for OB-Response synthetic workflows.

Default demos and course cohorts use the coupled event model. The older list
cohort path below remains available for projection regression comparisons.

Compares hypothetical prompt effectiveness across the same cohort.

Only cases supported by the current paired simulator contribute
to workflow averages and medication timing indicators.

Not a clinical effectiveness study or the full SMFM quality metric.
"""

from dataclasses import dataclass
from datetime import datetime

from htn_alert.cohort_evaluation import evaluate_cohort
from htn_alert.contract import Reading
from htn_alert.generator import PatientCourse, generate_cohort
from htn_alert.protocol import Protocol, load_protocol


DEFAULT_EFFECTS = (0.0, 0.25, 0.50, 0.75, 1.0)


@dataclass(frozen=True)
class CoupledSensitivityRow:
    prompt_effect: float
    total_patients: int
    comparable_dose_pairs: int
    average_reassessment_saved: float | None
    average_medication_saved: float | None
    baseline_patient_rate: float | None
    tool_patient_rate: float | None
    baseline_persistent_patients: int
    tool_persistent_patients: int
    classification_differences: int
    baseline_no_dose: int
    tool_no_dose: int
    baseline_missed_reassessments: int
    tool_missed_reassessments: int


def run_coupled_sensitivity_analysis(
    cohort: dict[str, PatientCourse], effects: tuple[float, ...] = DEFAULT_EFFECTS,
    seed: int = 42, *, protocol: Protocol | None = None, workflow_config=None,
    coupled_config=None,
) -> tuple[CoupledSensitivityRow, ...]:
    """Vary assumed effects without selecting on observed persistence or dose."""
    from htn_alert.cohort_evaluation import evaluate_coupled_cohort
    protocol = protocol if protocol is not None else load_protocol()
    rows = []
    for effect in effects:
        result = evaluate_coupled_cohort(cohort, effect, seed, protocol=protocol,
            workflow_config=workflow_config, coupled_config=coupled_config)
        rows.append(CoupledSensitivityRow(effect, result.total_patients,
            result.comparable_dose_pairs, result.average_reassessment_minutes_saved,
            result.average_medication_minutes_saved, result.baseline_events.patient_rate,
            result.tool_events.patient_rate, result.baseline_events.persistent_patients,
            result.tool_events.persistent_patients, result.discordant_classifications,
            sum(p.baseline.medication_time is None for p in result.patients),
            sum(p.tool.medication_time is None for p in result.patients),
            sum(p.baseline.missed_reassessments for p in result.patients),
            sum(p.tool.missed_reassessments for p in result.patients)))
    return tuple(rows)


@dataclass(frozen=True)
class SensitivityRow:
    prompt_effect: float
    total_patients: int
    supported_patients: int
    average_recognition_saved: float | None
    average_recheck_saved: float | None
    average_notification_saved: float | None
    average_medication_saved: float | None
    baseline_recheck_lateness: float | None
    tool_recheck_lateness: float | None
    baseline_within_60: int
    tool_within_60: int


def run_sensitivity_analysis(
    cohort: dict[str, list[Reading]] | dict[str, PatientCourse],
    effects: tuple[float, ...] = DEFAULT_EFFECTS,
    seed: int = 42,
    *,
    protocol: Protocol | None = None,
) -> tuple[SensitivityRow, ...] | tuple[CoupledSensitivityRow, ...]:
    """Evaluate the same synthetic patients at each assumed effect."""

    if cohort and all(isinstance(v, PatientCourse) for v in cohort.values()):
        return run_coupled_sensitivity_analysis(cohort, effects, seed, protocol=protocol)
    protocol = protocol if protocol is not None else load_protocol()
    rows = []

    for effect in effects:
        if not 0.0 <= effect <= 1.0:
            raise ValueError(
                "Each prompt effect must be between 0 and 1."
            )

        result = evaluate_cohort(
            cohort=cohort,
            prompt_effect=effect,
            seed=seed,
            protocol=protocol,
        )

        rows.append(
            SensitivityRow(
                prompt_effect=effect,
                total_patients=result.total_patients,
                supported_patients=result.supported_patients,
                average_recognition_saved=(
                    result.average_recognition_minutes_saved
                ),
                average_recheck_saved=(
                    result.average_projected_recheck_minutes_saved
                ),
                average_notification_saved=(
                    result.average_notification_minutes_saved
                ),
                average_medication_saved=(
                    result.average_medication_minutes_saved
                ),
                baseline_recheck_lateness=(
                    result.average_baseline_recheck_minutes_late
                ),
                tool_recheck_lateness=(
                    result.average_tool_recheck_minutes_late
                ),
                baseline_within_60=(
                    result.supported_baseline_within_60
                ),
                tool_within_60=(
                    result.supported_tool_within_60
                ),
            )
        )

    return tuple(rows)


def fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f}"


if __name__ == "__main__":
    import sys
    if "--legacy" not in sys.argv:
        from htn_alert.simulation_demo import demo
        demo("sensitivity_analysis")
        raise SystemExit
    protocol = load_protocol()
    cohort = generate_cohort(
        patients_per_scenario=10,
        start_time=datetime(2026, 10, 26, 8, 0),
        seed=42,
        protocol=protocol,
    )

    rows = run_sensitivity_analysis(cohort, seed=42, protocol=protocol)
    treatment_minutes = protocol.treatment_target.total_seconds() / 60
    timing_header = f"Within {treatment_minutes:g} B/T"

    print("\nOB-RESPONSE SENSITIVITY ANALYSIS")
    print("Same 80 synthetic patients at each effect level")
    print("Supported cases only; all effects are assumptions\n")

    print(
        f"{'Effect':>7} "
        f"{'Supported':>10} "
        f"{'Recheck saved':>15} "
        f"{'Notify saved':>14} "
        f"{'Med saved':>12} "
        f"{timing_header:>16}"
    )

    for row in rows:
        timing_count = (
            f"{row.baseline_within_60}/"
            f"{row.tool_within_60}"
        )

        print(
            f"{row.prompt_effect:>6.0%} "
            f"{row.supported_patients:>10} "
            f"{fmt(row.average_recheck_saved):>15} "
            f"{fmt(row.average_notification_saved):>14} "
            f"{fmt(row.average_medication_saved):>12} "
            f"{timing_count:>16}"
        )

    print("\nIMPORTANT LIMITATIONS")
    print("- Recheck benefits are projected, not observed BP readings.")
    print("- Treatment timing uses existing synthetic severe repeats.")
    print("- Workflow effects do not establish clinical effectiveness.")
    print(f"- Within-{treatment_minutes:g} counts are not the full SMFM patient-level rate.")
    print("- The cohort is balanced for testing, not hospital prevalence.")
