"""Load synthetic fixture and workflow assumptions separately from clinical rules.

Loaders accept alternate files for engineering experiments without editing the
shared protocol. They do not cache configuration, so each run sees its inputs.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
GENERATOR_PATH = CONFIG_DIR / "generator.toml"
WORKFLOW_PATH = CONFIG_DIR / "workflow.toml"


def _integer(value: object, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}.")
    return value


def _range(value: object, name: str, minimum: int | None = None) -> tuple[int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(v) is not int for v in value)
        or value[0] > value[1]
        or (minimum is not None and value[0] < minimum)
    ):
        raise ValueError(f"{name} must be an ordered inclusive integer range.")
    return tuple(value)


def _bp_value(value: object, name: str) -> int | tuple[int, int]:
    return _range(value, name, 1) if isinstance(value, list) else _integer(value, name, 1)


@dataclass(frozen=True)
class ScenarioReading:
    """A fixed or uniformly sampled BP fixture relative to synthetic onset."""

    after_minutes: int
    systolic: int | tuple[int, int]
    diastolic: int | tuple[int, int]


def _reading(raw: dict, name: str) -> ScenarioReading:
    return ScenarioReading(
        after_minutes=_integer(raw["after_minutes"], f"{name}.after_minutes", 1),
        systolic=_bp_value(raw["systolic"], f"{name}.systolic"),
        diastolic=_bp_value(raw["diastolic"], f"{name}.diastolic"),
    )


@dataclass(frozen=True)
class GeneratorConfig:
    """Inputs to the synthetic generator; scenario names are not diagnoses."""

    duration_hours: int
    interval_minutes: int
    baseline_systolic: int
    baseline_diastolic: int
    minimum_template_minutes: int
    systolic_variation: tuple[int, int]
    diastolic_variation: tuple[int, int]
    non_hypertensive_max: tuple[int, int]
    onset_minutes: tuple[int, ...]
    onset_systolic: tuple[int, int]
    onset_diastolic: tuple[int, int]
    scenario_baselines: dict[str, tuple[int, int]]
    scenario_readings: dict[str, tuple[ScenarioReading, ...]]
    delayed_repeat_subtypes: dict[str, ScenarioReading]
    default_delayed_repeat_subtype: str
    cohort_delayed_repeat_subtypes: tuple[str, ...]


def load_generator_config(path: Path = GENERATOR_PATH) -> GeneratorConfig:
    """Load fixture defaults and reject malformed ranges and subtype choices."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    defaults, routine, onset = raw["defaults"], raw["routine"], raw["onset"]
    minutes = tuple(_integer(m, "onset.minutes") for m in onset["minutes"])
    if not minutes:
        raise ValueError("onset.minutes cannot be empty.")
    baselines = {}
    readings = {}
    for name, scenario in raw["scenarios"].items():
        if "baseline" in scenario:
            bp = scenario["baseline"]
            if not isinstance(bp, list) or len(bp) != 2:
                raise ValueError(f"{name}.baseline must contain two pressures.")
            baselines[name] = tuple(_integer(v, f"{name}.baseline", 1) for v in bp)
        if "readings" in scenario:
            points = tuple(_reading(r, name) for r in scenario["readings"])
            offsets = [r.after_minutes for r in points]
            if not points or offsets != sorted(set(offsets)):
                raise ValueError(f"{name}.readings must have unique increasing offsets.")
            readings[name] = points
    delayed = raw["delayed_repeat"]
    subtypes = {name: _reading(r, name) for name, r in delayed["subtypes"].items()}
    default_subtype = delayed["default_subtype"]
    cohort_subtypes = tuple(delayed["cohort_subtypes"])
    if default_subtype not in subtypes or not cohort_subtypes or any(
        name not in subtypes for name in cohort_subtypes
    ):
        raise ValueError("Delayed repeat choices must name configured subtypes.")
    caps = routine["non_hypertensive_max"]
    if not isinstance(caps, list) or len(caps) != 2:
        raise ValueError("routine.non_hypertensive_max must contain two pressures.")
    return GeneratorConfig(
        **{name: _integer(defaults[name], f"defaults.{name}", 1) for name in (
            "duration_hours", "interval_minutes", "baseline_systolic",
            "baseline_diastolic", "minimum_template_minutes",
        )},
        systolic_variation=_range(routine["systolic_variation"], "routine.systolic_variation"),
        diastolic_variation=_range(routine["diastolic_variation"], "routine.diastolic_variation"),
        non_hypertensive_max=tuple(_integer(v, "routine.non_hypertensive_max", 1) for v in caps),
        onset_minutes=minutes,
        onset_systolic=_range(onset["systolic"], "onset.systolic", 1),
        onset_diastolic=_range(onset["diastolic"], "onset.diastolic", 1),
        scenario_baselines=baselines,
        scenario_readings=readings,
        delayed_repeat_subtypes=subtypes,
        default_delayed_repeat_subtype=default_subtype,
        cohort_delayed_repeat_subtypes=cohort_subtypes,
    )


@dataclass(frozen=True)
class WorkflowConfig:
    """Assumed delay ranges; targets come from the separate shared protocol."""

    recognition_minutes: tuple[int, int]
    identification_minutes: tuple[int, int]
    acknowledgment_minutes: tuple[int, int]
    medication_minutes: tuple[int, int]
    collaboration_minutes: tuple[int, int]
    uncertainty_minutes: tuple[int, int]
    readiness_minutes: tuple[int, int]
    recheck_seed_offset: int


def load_workflow_config(path: Path = WORKFLOW_PATH) -> WorkflowConfig:
    """Load nonnegative workflow delays without introducing dependencies."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return WorkflowConfig(
        **{name: _range(raw["delays"][name], f"delays.{name}", 0) for name in (
            "recognition_minutes", "identification_minutes", "acknowledgment_minutes",
            "medication_minutes", "collaboration_minutes", "uncertainty_minutes",
            "readiness_minutes",
        )},
        recheck_seed_offset=_integer(raw["randomness"]["recheck_seed_offset"], "recheck_seed_offset"),
    )
