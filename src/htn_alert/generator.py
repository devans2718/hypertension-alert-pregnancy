"""Synthetic BP streams for engineering tests, not clinical decision-making.

Scenario labels and ground truth are kept outside the shared Reading objects.
Times, ranges and scenario frequencies here are TEST ASSUMPTIONS unless stated
otherwise; review with clinical mentors before any clinical interpretation.
"""

import random
from datetime import datetime, timedelta

from htn_alert.contract import Reading
from htn_alert.protocol import Protocol, load_protocol
from htn_alert.rules import is_severe
from htn_alert.simulation_config import GeneratorConfig, load_generator_config

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


def generate_bp_readings(
    patient_id: str,
    start_time: datetime,
    duration_hours: int | None = None,
    interval_minutes: int | None = None,
    baseline_systolic: int | None = None,
    baseline_diastolic: int | None = None,
    seed: int = 42,
    scenario: str = "non_hypertensive",
    *,
    delayed_repeat_subtype: str | None = None,
    config: GeneratorConfig | None = None,
    protocol: Protocol | None = None,
) -> list[Reading]:
    """Create a reproducible, time-sorted synthetic stream for one patient.

    Existing positional arguments still work; omitted numeric defaults come
    from generator.toml. Subtypes ``delayed`` (16 minutes) and ``missing_early``
    (30 minutes) are explicit fixture choices, independent of the random seed.
    Severe-case timing is for software tests, not sampled from patient data.
    """
    config = config if config is not None else load_generator_config()
    protocol = protocol if protocol is not None else load_protocol()
    duration_hours = config.duration_hours if duration_hours is None else duration_hours
    interval_minutes = config.interval_minutes if interval_minutes is None else interval_minutes
    baseline_systolic = config.baseline_systolic if baseline_systolic is None else baseline_systolic
    baseline_diastolic = config.baseline_diastolic if baseline_diastolic is None else baseline_diastolic
    if not isinstance(patient_id, str) or not patient_id.strip():
        raise ValueError("Patient ID cannot be empty.")
    if duration_hours <= 0 or interval_minutes <= 0:
        raise ValueError("Duration and interval must be positive.")
    if duration_hours * 60 % interval_minutes:
        raise ValueError("Duration must be divisible by interval.")
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario}")
    baseline = Reading(patient_id, start_time, baseline_systolic, baseline_diastolic)
    if (
        baseline_systolic + config.systolic_variation[0] <= 0
        or baseline_diastolic + config.diastolic_variation[0] <= 0
        or is_severe(baseline, protocol)
    ):
        raise ValueError("Baselines must stay positive under variation and below severe thresholds.")
    if delayed_repeat_subtype is not None and scenario != "delayed_or_missing_repeat":
        raise ValueError("delayed_repeat_subtype applies only to delayed_or_missing_repeat.")
    subtype = config.default_delayed_repeat_subtype if delayed_repeat_subtype is None else delayed_repeat_subtype
    if subtype not in config.delayed_repeat_subtypes:
        raise ValueError(f"Unknown delayed repeat subtype: {subtype}")

    total_minutes = duration_hours * 60
    has_onset = scenario not in ("non_hypertensive", "mild_hypertension", "borderline_severe")
    if has_onset and total_minutes < config.minimum_template_minutes:
        raise ValueError(
            f"Current severe scenario templates require at least {config.minimum_template_minutes} minutes."
        )

    rng = random.Random(seed)
    baseline_systolic, baseline_diastolic = config.scenario_baselines.get(
        scenario, (baseline_systolic, baseline_diastolic)
    )
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

    # Routine fixture caps follow the shared protocol, not a second severity rule.
    cap_sys, cap_dia = protocol.severe_systolic - 1, protocol.severe_diastolic - 1
    if scenario == "non_hypertensive":
        cap_sys = min(cap_sys, config.non_hypertensive_max[0])
        cap_dia = min(cap_dia, config.non_hypertensive_max[1])
    for minute in range(0, total_minutes + 1, interval_minutes):
        systolic = min(baseline_systolic + rng.randint(*config.systolic_variation), cap_sys)
        diastolic = min(baseline_diastolic + rng.randint(*config.diastolic_variation), cap_dia)
        put(minute, systolic, diastolic)

    def sample(value: int | tuple[int, int]) -> int:
        # Fixed fixtures must not consume random draws: preserve seeded streams.
        return rng.randint(*value) if isinstance(value, tuple) else value

    if has_onset:
        onset = rng.choice(config.onset_minutes)
        put(onset, rng.randint(*config.onset_systolic), rng.randint(*config.onset_diastolic))
        if scenario == "delayed_or_missing_repeat":
            point = config.delayed_repeat_subtypes[subtype]
            repeat_at = onset + point.after_minutes
            put(repeat_at, sample(point.systolic), sample(point.diastolic))
            # Omit routine observations until the explicitly selected repeat.
            for minute in list(by_minute):
                if onset < minute < repeat_at:
                    del by_minute[minute]
        else:
            # Names are fixture labels, not clinical episode classifications (#9).
            for point in config.scenario_readings[scenario]:
                put(onset + point.after_minutes, sample(point.systolic), sample(point.diastolic))

    return [by_minute[m] for m in sorted(by_minute)]


def generate_cohort(
    patients_per_scenario: int = 10,
    start_time: datetime | None = None,
    duration_hours: int | None = None,
    interval_minutes: int | None = None,
    seed: int = 42,
    *,
    config: GeneratorConfig | None = None,
    protocol: Protocol | None = None,
) -> dict[str, list[Reading]]:
    """Generate a balanced test cohort, with a seed-independent subtype cycle.

    The configured cycle includes both delayed-repeat examples. Changing the
    seed varies BP values and onset, not which subtype a patient receives.
    """
    config = config if config is not None else load_generator_config()
    protocol = protocol if protocol is not None else load_protocol()
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
                delayed_repeat_subtype=(
                    config.cohort_delayed_repeat_subtypes[
                        within % len(config.cohort_delayed_repeat_subtypes)
                    ] if scenario == "delayed_or_missing_repeat" else None
                ),
                config=config, protocol=protocol,
            )
    return cohort


def summarize_cohort(
    cohort: dict[str, list[Reading]], *, protocol: Protocol | None = None,
) -> dict[str, int]:
    """Count severe observations with the same rule used by the workflow."""
    protocol = protocol if protocol is not None else load_protocol()
    return {
        "patients": len(cohort),
        "total_readings": sum(map(len, cohort.values())),
        "severe_readings": sum(is_severe(r, protocol) for readings in cohort.values() for r in readings),
        "patients_with_severe_readings": sum(any(is_severe(r, protocol) for r in readings) for readings in cohort.values()),
    }


if __name__ == "__main__":
    start = datetime(2026, 10, 26, 8, 0)
    protocol = load_protocol()
    for i, scenario in enumerate(SCENARIOS, 1):
        patient_id = f"DEMO-{i:03d}"
        print(f"\n{scenario} | {patient_id}")
        for r in generate_bp_readings(patient_id, start, scenario=scenario, seed=42 + i):
            status = " [SEVERE]" if is_severe(r, protocol) else ""
            print(f"{r.time:%H:%M} {r.systolic}/{r.diastolic}{status}")
    print("\nBalanced cohort summary:", summarize_cohort(generate_cohort()))
