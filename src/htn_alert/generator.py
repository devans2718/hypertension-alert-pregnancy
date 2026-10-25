"""Synthetic BP streams for engineering tests, not clinical decision-making.

Scenario labels and ground truth are kept outside the shared Reading objects.
Times, ranges and scenario frequencies here are TEST ASSUMPTIONS unless stated
otherwise; review with clinical mentors before any clinical interpretation.
"""

import random
from datetime import datetime, timedelta

from htn_alert.contract import Reading

SCENARIOS = (
    "non_hypertensive",
    "mild_hypertension",
    "persistent_severe",
    "nonpersistent_severe",
    "recurrent_severe",
    "borderline_severe",
    "delayed_or_missing_repeat",
    "spurious_severe",
)


def is_severe(systolic: int, diastolic: int) -> bool:
    return systolic >= 160 or diastolic >= 110


def generate_bp_readings(
    patient_id: str,
    start_time: datetime,
    duration_hours: int = 3,
    interval_minutes: int = 15,
    baseline_systolic: int = 120,
    baseline_diastolic: int = 80,
    seed: int = 42,
    scenario: str = "non_hypertensive",
) -> list[Reading]:
    """Create a reproducible, time-sorted synthetic stream for one patient.

    Retains the earlier public function signature. Severe-case timing is
    constructed for software tests, NOT sampled from patient-derived data.
    """
    if not isinstance(patient_id, str) or not patient_id.strip():
        raise ValueError("Patient ID cannot be empty.")
    if duration_hours <= 0 or interval_minutes <= 0:
        raise ValueError("Duration and interval must be positive.")
    if duration_hours * 60 % interval_minutes:
        raise ValueError("Duration must be divisible by interval.")
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    if not (5 < baseline_systolic < 160 and 4 < baseline_diastolic < 110):
        raise ValueError("Baselines must be positive and below severe thresholds.")

    total_minutes = duration_hours * 60
    if scenario not in ("non_hypertensive", "mild_hypertension", "borderline_severe") and total_minutes < 180:
        raise ValueError("Current severe scenario templates require at least 3 hours.")

    rng = random.Random(seed)
    # Scenario-specific baselines prevent contradictory labels.
    if scenario == "mild_hypertension":
        baseline_systolic, baseline_diastolic = 145, 95
    elif scenario == "borderline_severe":
        baseline_systolic, baseline_diastolic = 155, 105

    by_minute: dict[int, Reading] = {}

    def put(minute: int, systolic: int, diastolic: int) -> None:
        if minute < 0 or minute > total_minutes:
            raise ValueError("Scenario time outside simulation.")
        by_minute[minute] = Reading(
            patient_id=patient_id,
            time=start_time + timedelta(minutes=minute),
            systolic=systolic,
            diastolic=diastolic,
        )

    # Smoothly varying routine readings are simple controlled assumptions.
    for minute in range(0, total_minutes + 1, interval_minutes):
        systolic = baseline_systolic + rng.randint(-5, 5)
        diastolic = baseline_diastolic + rng.randint(-4, 4)
        if scenario == "non_hypertensive":
            systolic, diastolic = min(systolic, 139), min(diastolic, 89)
        elif scenario == "mild_hypertension":
            systolic, diastolic = min(systolic, 159), min(diastolic, 109)
        elif scenario == "borderline_severe":
            systolic, diastolic = min(systolic, 159), min(diastolic, 109)
        else:
            systolic, diastolic = min(systolic, 159), min(diastolic, 109)
        put(minute, systolic, diastolic)

    if scenario in ("persistent_severe", "nonpersistent_severe", "recurrent_severe", "delayed_or_missing_repeat", "spurious_severe"):
        # Vary onset between 45 and 90 minutes. The timing range is an assumption.
        onset = rng.choice((45, 60, 75, 90))
        high_sys = rng.randint(162, 178)
        high_dia = rng.randint(108, 118)
        put(onset, high_sys, high_dia)

        if scenario == "persistent_severe":
            put(onset + 10, rng.randint(161, 174), rng.randint(105, 117))
            put(onset + 15, rng.randint(161, 170), rng.randint(104, 115))
            put(onset + 30, rng.randint(161, 168), rng.randint(102, 113))
            put(onset + 45, rng.randint(140, 152), rng.randint(88, 99))

        elif scenario == "nonpersistent_severe":
            put(onset + 10, rng.randint(125, 145), rng.randint(75, 95))

        elif scenario == "recurrent_severe":
            put(onset + 10, 135, 85)
            # Second severe within 60 min, even after a nonsevere reading.
            put(onset + 45, rng.randint(162, 175), rng.randint(108, 117))
            put(onset + 55, rng.randint(162, 175), rng.randint(107, 117))
            put(onset + 60, 145, 92)

        elif scenario == "delayed_or_missing_repeat":
            # Two subtypes: a 16-minute nonsevere repeat, or no early repeat.
            if seed % 2 == 0:
                put(onset + 16, 135, 85)
            else:
                put(onset + 30, 135, 85)
            # Remove any routine readings *after onset* and *before the repeat*.
            repeat_at = onset + (16 if seed % 2 == 0 else 30)
            for minute in list(by_minute):
                if onset < minute < repeat_at:
                    del by_minute[minute]

        elif scenario == "spurious_severe":
            # The generator knows this was deliberately injected as spurious;
            # Reading carries no such ground-truth flag.
            put(onset + 10, rng.randint(118, 135), rng.randint(75, 89))

    return [by_minute[m] for m in sorted(by_minute)]


def generate_cohort(
    patients_per_scenario: int = 10,
    start_time: datetime | None = None,
    duration_hours: int = 3,
    interval_minutes: int = 15,
    seed: int = 42,
) -> dict[str, list[Reading]]:
    """Generate an equally balanced scenario cohort for testing, not prevalence."""
    if patients_per_scenario <= 0:
        raise ValueError("patients_per_scenario must be positive.")
    if start_time is None:
        start_time = datetime(2026, 10, 26, 8, 0)
    cohort: dict[str, list[Reading]] = {}
    for index, scenario in enumerate(SCENARIOS):
        for within in range(patients_per_scenario):
            n = index * patients_per_scenario + within + 1
            pid = f"SIM-{n:05d}"
            cohort[pid] = generate_bp_readings(
                pid, start_time, duration_hours=duration_hours,
                interval_minutes=interval_minutes,
                seed=seed + n, scenario=scenario,
            )
    return cohort


def summarize_cohort(cohort: dict[str, list[Reading]]) -> dict[str, int]:
    return {
        "patients": len(cohort),
        "total_readings": sum(map(len, cohort.values())),
        "severe_readings": sum(is_severe(r.systolic, r.diastolic) for readings in cohort.values() for r in readings),
        "patients_with_severe_readings": sum(any(is_severe(r.systolic, r.diastolic) for r in readings) for readings in cohort.values()),
    }


if __name__ == "__main__":
    start = datetime(2026, 10, 26, 8, 0)
    for i, scenario in enumerate(SCENARIOS, 1):
        patient_id = f"DEMO-{i:03d}"
        print(f"\n{scenario} | {patient_id}")
        for r in generate_bp_readings(patient_id, start, scenario=scenario, seed=42 + i):
            status = " [SEVERE]" if is_severe(r.systolic, r.diastolic) else ""
            print(f"{r.time:%H:%M} {r.systolic}/{r.diastolic}{status}")
    print("\nBalanced cohort summary:", summarize_cohort(generate_cohort()))
