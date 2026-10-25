
"""Cohort-level synthetic workflow evaluation for OB-Response.

Uses the existing synthetic BP generator and paired workflow simulator.

Primary focus:
- Nurse recognition delays
- Projected 15-minute BP reassessment lateness
- Provider communication delays
- Simulated medication timing

This is a COVERAGE-AWARE engineering evaluation.

It does NOT calculate the complete SMFM patient-level quality
measure or clinically validated false-alert rates.

All intervention effects and staff delays are assumptions,
not measured outcomes from Mosaic Hospital.
"""

from dataclasses import dataclass
from datetime import datetime
from statistics import mean

from htn_alert.contract import Reading
from htn_alert.generator import (
    generate_cohort,
    is_severe,
)
from htn_alert.paired_simulation import compare_workflows
from htn_alert.workflow import PROVIDER_PATHWAYS


@dataclass(frozen=True)
class PatientEvaluation:
    """One patient's evaluation status and simulated outcomes."""

    patient_id: str
    provider_pathway: str

    severe_readings: int
    supported: bool
    reason: str

    recognition_minutes_saved: float | None = None
    projected_recheck_minutes_saved: float | None = None
    notification_minutes_saved: float | None = None
    medication_minutes_saved: float | None = None

    baseline_recheck_minutes_late: float | None = None
    tool_recheck_minutes_late: float | None = None

    baseline_treatment_minutes: float | None = None
    tool_treatment_minutes: float | None = None

    baseline_within_60: bool | None = None
    tool_within_60: bool | None = None


@dataclass(frozen=True)
class CohortEvaluation:
    """Summary of supported and unsupported patient comparisons."""

    total_patients: int
    patients_with_severe_bp: int
    supported_patients: int
    unsupported_patients: int

    no_severe_bp_patients: int
    severe_without_qualifying_repeat: int

    average_recognition_minutes_saved: float | None
    average_projected_recheck_minutes_saved: float | None
    average_notification_minutes_saved: float | None
    average_medication_minutes_saved: float | None

    average_baseline_recheck_minutes_late: float | None
    average_tool_recheck_minutes_late: float | None

    average_baseline_treatment_minutes: float | None
    average_tool_treatment_minutes: float | None

    supported_baseline_within_60: int
    supported_tool_within_60: int

    patients: tuple[PatientEvaluation, ...]


def _average(values: list[float | None]) -> float | None:
    """Average available measurements; do not treat missing as zero."""

    available = [value for value in values if value is not None]

    if not available:
        return None

    return mean(available)


def _has_qualifying_severe_repeat(
    readings: list[Reading],
) -> bool:
    """Check whether the limited paired simulator supports this stream.

    This is an engineering eligibility check, NOT a complete
    clinical persistence definition.
    """

    if not readings:
        return False

    ordered = sorted(readings, key=lambda r: r.time)

    first_severe = next(
        (
            reading
            for reading in ordered
            if is_severe(reading.systolic, reading.diastolic)
        ),
        None,
    )

    if first_severe is None:
        return False

    for reading in ordered:
        elapsed_minutes = (
            reading.time - first_severe.time
        ).total_seconds() / 60

        if (
            15 <= elapsed_minutes <= 60
            and is_severe(reading.systolic, reading.diastolic)
        ):
            return True

    return False


def evaluate_cohort(
    cohort: dict[str, list[Reading]],
    prompt_effect: float = 0.5,
    seed: int = 42,
) -> CohortEvaluation:
    """Evaluate supported synthetic patient workflows.

    The same patient observations, pathway and random seed
    are used for each baseline/tool pair.

    Provider pathways are assigned cyclically for demonstration.
    This is NOT an estimate of Mosaic's provider distribution.

    Unsupported patients remain visible in the summary.
    """

    if not 0.0 <= prompt_effect <= 1.0:
        raise ValueError(
            "prompt_effect must be between 0.0 and 1.0."
        )

    patient_results = []

    for index, (patient_id, readings) in enumerate(
        sorted(cohort.items())
    ):
        pathway = PROVIDER_PATHWAYS[index % len(PROVIDER_PATHWAYS)]

        if any(r.patient_id != patient_id for r in readings):
            raise ValueError(
                f"Patient IDs do not match for {patient_id}."
            )

        severe_count = sum(
            is_severe(r.systolic, r.diastolic)
            for r in readings
        )

        if severe_count == 0:
            patient_results.append(
                PatientEvaluation(
                    patient_id=patient_id,
                    provider_pathway=pathway,
                    severe_readings=0,
                    supported=False,
                    reason="No severe BP; not applicable to current simulator",
                )
            )
            continue

        if not _has_qualifying_severe_repeat(readings):
            patient_results.append(
                PatientEvaluation(
                    patient_id=patient_id,
                    provider_pathway=pathway,
                    severe_readings=severe_count,
                    supported=False,
                    reason=(
                        "Severe BP without qualifying repeat "
                        "for current demonstration"
                    ),
                )
            )
            continue

        result = compare_workflows(
            readings=readings,
            provider_pathway=pathway,
            seed=seed + index,
            prompt_effect=prompt_effect,
        )

        patient_results.append(
            PatientEvaluation(
                patient_id=patient_id,
                provider_pathway=pathway,
                severe_readings=severe_count,
                supported=True,
                reason="Supported by current paired simulator",
                recognition_minutes_saved=(
                    result.recognition_minutes_saved
                ),
                projected_recheck_minutes_saved=(
                    result.projected_recheck_minutes_saved
                ),
                notification_minutes_saved=(
                    result.provider_notification_minutes_saved
                ),
                medication_minutes_saved=(
                    result.medication_minutes_saved
                ),
                baseline_recheck_minutes_late=(
                    result.baseline.recheck_plan.minutes_late
                ),
                tool_recheck_minutes_late=(
                    result.tool.recheck_plan.minutes_late
                ),
                baseline_treatment_minutes=(
                    result.baseline.treatment_minutes
                ),
                tool_treatment_minutes=(
                    result.tool.treatment_minutes
                ),
                baseline_within_60=result.baseline_within_60,
                tool_within_60=result.tool_within_60,
            )
        )

    supported = [p for p in patient_results if p.supported]

    no_severe = sum(
        p.reason.startswith("No severe BP")
        for p in patient_results
    )

    without_repeat = sum(
        p.reason.startswith("Severe BP without")
        for p in patient_results
    )

    return CohortEvaluation(
        total_patients=len(patient_results),
        patients_with_severe_bp=sum(
            p.severe_readings > 0 for p in patient_results
        ),
        supported_patients=len(supported),
        unsupported_patients=len(patient_results) - len(supported),
        no_severe_bp_patients=no_severe,
        severe_without_qualifying_repeat=without_repeat,
        average_recognition_minutes_saved=_average(
            [p.recognition_minutes_saved for p in supported]
        ),
        average_projected_recheck_minutes_saved=_average(
            [p.projected_recheck_minutes_saved for p in supported]
        ),
        average_notification_minutes_saved=_average(
            [p.notification_minutes_saved for p in supported]
        ),
        average_medication_minutes_saved=_average(
            [p.medication_minutes_saved for p in supported]
        ),
        average_baseline_recheck_minutes_late=_average(
            [p.baseline_recheck_minutes_late for p in supported]
        ),
        average_tool_recheck_minutes_late=_average(
            [p.tool_recheck_minutes_late for p in supported]
        ),
        average_baseline_treatment_minutes=_average(
            [p.baseline_treatment_minutes for p in supported]
        ),
        average_tool_treatment_minutes=_average(
            [p.tool_treatment_minutes for p in supported]
        ),
        supported_baseline_within_60=sum(
            p.baseline_within_60 is True for p in supported
        ),
        supported_tool_within_60=sum(
            p.tool_within_60 is True for p in supported
        ),
        patients=tuple(patient_results),
    )


def _display(value: float | None) -> str:
    """Format a metric without converting missing data to zero."""

    return "N/A" if value is None else f"{value:.2f}"


if __name__ == "__main__":
    cohort = generate_cohort(
        patients_per_scenario=10,
        start_time=datetime(2026, 10, 26, 8, 0),
        seed=42,
    )

    evaluation = evaluate_cohort(
        cohort,
        prompt_effect=0.5,
        seed=42,
    )

    print("\n" + "=" * 60)
    print("OB-RESPONSE: SYNTHETIC COHORT EVALUATION")
    print("=" * 60)

    print("\nPATIENT COVERAGE")
    print("Total synthetic patients:", evaluation.total_patients)
    print(
        "Patients with severe BP:",
        evaluation.patients_with_severe_bp,
    )
    print(
        "Supported by paired simulator:",
        evaluation.supported_patients,
    )
    print("Not supported:", evaluation.unsupported_patients)
    print(
        "No severe BP:",
        evaluation.no_severe_bp_patients,
    )
    print(
        "Severe BP without qualifying repeat:",
        evaluation.severe_without_qualifying_repeat,
    )

    print("\nWORKFLOW COMPARISON — SUPPORTED PATIENTS ONLY")
    print(
        "Average recognition minutes saved:",
        _display(evaluation.average_recognition_minutes_saved),
    )
    print(
        "Average projected recheck minutes saved:",
        _display(
            evaluation.average_projected_recheck_minutes_saved
        ),
    )
    print(
        "Average provider notification minutes saved:",
        _display(evaluation.average_notification_minutes_saved),
    )
    print(
        "Average medication minutes saved:",
        _display(evaluation.average_medication_minutes_saved),
    )

    print("\nPROJECTED REASSESSMENT LATENESS")
    print(
        "Baseline average minutes late:",
        _display(
            evaluation.average_baseline_recheck_minutes_late
        ),
    )
    print(
        "OB-Response average minutes late:",
        _display(
            evaluation.average_tool_recheck_minutes_late
        ),
    )

    print("\nMEDICATION TIMING — SUPPORTED PATIENTS ONLY")
    print(
        "Baseline average minutes:",
        _display(
            evaluation.average_baseline_treatment_minutes
        ),
    )
    print(
        "OB-Response average minutes:",
        _display(
            evaluation.average_tool_treatment_minutes
        ),
    )
    print(
        "Baseline medication within 60 minutes:",
        evaluation.supported_baseline_within_60,
    )
    print(
        "OB-Response medication within 60 minutes:",
        evaluation.supported_tool_within_60,
    )

    print("\nUNSUPPORTED CASES")
    for patient in evaluation.patients:
        if not patient.supported:
            print(f"{patient.patient_id}: {patient.reason}")

    print("\nINTERPRETATION")
    print(
        "- Provider pathways and delays are simulation assumptions."
    )
    print(
        "- Projected reassessment improvements do not cause "
        "the modeled medication-time improvements."
    )
    print(
        "- Medication within 60 minutes is a timing indicator, "
        "not the complete SMFM patient-level compliance measure."
    )
    print(
        "- Unsupported patients are excluded from workflow "
        "averages but explicitly counted above."
    )
    print(
        "- Clinical episode classifications require "
        "integration with Daniel's rules."
    )
