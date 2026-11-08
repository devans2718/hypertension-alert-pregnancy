"""Synthetic BP streams for engineering tests, not clinical decision-making.

Scenario labels and ground truth are kept outside the shared Reading objects.
Times, ranges and scenario frequencies here are TEST ASSUMPTIONS unless stated
otherwise; review with clinical mentors before any clinical interpretation.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from htn_alert.contract import Reading
from htn_alert.protocol import Protocol, load_protocol
from htn_alert.rules import is_severe
from htn_alert.simulation_config import (
    CourseConfig, GeneratorConfig, load_course_config, load_generator_config,
)

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


@dataclass(frozen=True)
class BPPoint:
    """An unobserved change in an assumed piecewise-constant BP course."""

    time: datetime
    systolic: int
    diastolic: int


@dataclass(frozen=True)
class PatientCourse:
    """Synthetic truth, never passed to EpisodeTracker or interpreted as data.

    Measurement timing is owned by the workflow. Medication does not modify
    this exogenous course: there is no assumed drug-response model. Scenario
    metadata is for reporting only and is never a treatment predicate.
    """

    patient_id: str
    start: datetime
    end: datetime
    routine_interval_minutes: int
    minimum_measurement_minutes: int
    points: tuple[BPPoint, ...]
    scenario: str = "custom"

    def __post_init__(self):
        if not self.patient_id.strip() or self.end <= self.start:
            raise ValueError("Course needs a patient and a positive horizon.")
        if self.minimum_measurement_minutes <= 0 or self.routine_interval_minutes < self.minimum_measurement_minutes:
            raise ValueError("Routine interval must respect minimum measurement spacing.")
        times = [p.time for p in self.points]
        if not times or times[0] != self.start or times != sorted(set(times)):
            raise ValueError("Course points must start at start and have unique increasing times.")
        if any(p.time > self.end or p.systolic <= 0 or p.diastolic <= 0 for p in self.points):
            raise ValueError("Course points must be positive and inside the horizon.")
        if any((t - self.start).total_seconds() % 60 for t in [self.end, *times]):
            raise ValueError("Coupled courses currently use whole-minute timestamps.")

    def sample(self, when: datetime) -> Reading:
        """Query current truth without random draws or a recorded observation."""
        if not self.start <= when <= self.end:
            raise ValueError("Cannot sample outside the course horizon.")
        point = next(p for p in reversed(self.points) if p.time <= when)
        return Reading(self.patient_id, when, point.systolic, point.diastolic)


def generate_patient_course(
    patient_id: str, start_time: datetime, scenario: str = "persistent_severe",
    seed: int = 42, *, routine_interval_minutes: int | None = None,
    config: GeneratorConfig | None = None, course_config: CourseConfig | None = None,
    protocol: Protocol | None = None,
) -> PatientCourse:
    """Build shared unobserved truth independently of either staff workflow.

    All phase timings and BP samples are sourced assumptions. In particular,
    spontaneous resolution is exogenous; a dose never manufactures resolution.
    The old generate_bp_readings() remains an archival fixture API.
    """
    config = config if config is not None else load_generator_config()
    cc = course_config if course_config is not None else load_course_config()
    protocol = protocol if protocol is not None else load_protocol()
    if scenario not in SCENARIOS or scenario not in cc.profiles:
        raise ValueError(f"Unknown course scenario: {scenario}")
    rng = random.Random(seed)
    baseline = config.scenario_baselines.get(scenario, (config.baseline_systolic, config.baseline_diastolic))
    normal = (
        min(baseline[0] + rng.randint(*config.systolic_variation), protocol.severe_systolic - 1),
        min(baseline[1] + rng.randint(*config.diastolic_variation), protocol.severe_diastolic - 1),
    )
    severe = (
        max(rng.randint(*config.onset_systolic), protocol.severe_systolic),
        rng.randint(*config.onset_diastolic),
    )
    resolved = (min(cc.resolved_bp[0], protocol.severe_systolic - 1),
                min(cc.resolved_bp[1], protocol.severe_diastolic - 1))
    onset = rng.choice(cc.onset_minutes)
    end = start_time + timedelta(hours=config.duration_hours)
    points = {start_time: BPPoint(start_time, *normal)}
    for after, is_high in cc.profiles[scenario]:
        when = start_time + timedelta(minutes=onset + after)
        if when <= end:
            points[when] = BPPoint(when, *(severe if is_high else resolved))
    cycle = cc.routine_intervals_minutes[0] if routine_interval_minutes is None else routine_interval_minutes
    return PatientCourse(patient_id, start_time, end, cycle, cc.minimum_measurement_minutes,
                         tuple(points[t] for t in sorted(points)), scenario)


def generate_course_cohort(
    patients_per_scenario: int = 10, start_time: datetime | None = None, seed: int = 42,
    *, config: GeneratorConfig | None = None, course_config: CourseConfig | None = None,
    protocol: Protocol | None = None,
) -> dict[str, PatientCourse]:
    """Balance labels and cycle lengths for engineering coverage, not prevalence."""
    if patients_per_scenario <= 0:
        raise ValueError("patients_per_scenario must be positive.")
    cc = course_config if course_config is not None else load_course_config()
    config = config if config is not None else load_generator_config()
    protocol = protocol if protocol is not None else load_protocol()
    start_time = start_time or datetime(2026, 10, 26, 8)
    result = {}
    for index, scenario in enumerate(SCENARIOS):
        for within in range(patients_per_scenario):
            n = index * patients_per_scenario + within + 1
            pid = f"SIM-{n:05d}"
            result[pid] = generate_patient_course(pid, start_time, scenario, seed + n,
                routine_interval_minutes=cc.routine_intervals_minutes[within % len(cc.routine_intervals_minutes)],
                config=config, course_config=cc, protocol=protocol)
    return result


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
    import sys
    if "--legacy" not in sys.argv:
        from htn_alert.simulation_demo import demo
        demo("generator")
        raise SystemExit
    start = datetime(2026, 10, 26, 8, 0)
    protocol = load_protocol()
    for i, scenario in enumerate(SCENARIOS, 1):
        patient_id = f"DEMO-{i:03d}"
        print(f"\n{scenario} | {patient_id}")
        for r in generate_bp_readings(patient_id, start, scenario=scenario, seed=42 + i):
            status = " [SEVERE]" if is_severe(r, protocol) else ""
            print(f"{r.time:%H:%M} {r.systolic}/{r.diastolic}{status}")
    print("\nBalanced cohort summary:", summarize_cohort(generate_cohort()))
