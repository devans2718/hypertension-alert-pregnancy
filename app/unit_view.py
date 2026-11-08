"""The unit view: a shift of synthetic patients on an illustrative floor.

Builds one shift from config/unit_layout.toml: which patient is in which bed,
their readings (from the generator) and their staff actions (drawn from
config/workflow.toml's assumed delays). The app replays a shift through
playback.evaluate_unit_view(), so the floor runs on EpisodeTracker like the
bedside view. A seed fixes a shift, so a good run can be shown again.

Everything here is a demonstration on synthetic data; no clinical claims.
"""

import random
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.playback import EpisodePhase, EpisodeStatus, evaluate_playback_episode
from htn_alert.contract import Action, ActionKind, EventKind, Reading
from htn_alert.generator import generate_bp_readings
from htn_alert.protocol import Protocol
from htn_alert.rules import is_severe
from htn_alert.simulation_config import (
    GeneratorConfig,
    WorkflowConfig,
    load_generator_config,
    load_workflow_config,
)

LAYOUT_PATH = Path(__file__).resolve().parents[1] / "config" / "unit_layout.toml"

# Tries at drawing a treated patient's actions before giving up; with the
# shipped ranges, nearly every first draw already fits.
_MAX_DRAWS = 200


@dataclass(frozen=True)
class Bed:
    """A bed's place on the floor grid."""

    label: str
    row: int
    column: int


@dataclass(frozen=True)
class FixtureReading:
    """A story reading that replaces the generator's, relative to onset."""

    after_minutes: int
    systolic: tuple[int, int]
    diastolic: tuple[int, int]


@dataclass(frozen=True)
class PatientSpec:
    """Who a patient is in the demo: a role, a generator scenario, and extras."""

    role: str
    scenario: str
    episode_type: str  # the card's label: which SMFM episode type this patient shows
    delayed_repeat_subtype: str | None = None
    drawn_actions: bool = False
    readings: tuple[FixtureReading, ...] = ()


@dataclass(frozen=True)
class UnitLayout:
    """The floor, the shift's start, and the patients to place on it."""

    columns: int
    rows: int
    corridor_row: int
    station: str
    beds: tuple[Bed, ...]
    shift_start: tuple[int, int]  # hour, minute
    min_reading_gap: timedelta
    patients: tuple[PatientSpec, ...]


@dataclass(frozen=True)
class Shift:
    """One seeded shift: each bed's patient, readings and actions."""

    seed: int
    start: datetime
    end: datetime
    roles: dict[str, str]  # bed label -> role
    episode_types: dict[str, str]  # bed label -> the card's episode-type label
    readings: dict[str, list[Reading]]
    actions: dict[str, list[Action]]


def _pair(value: object, name: str) -> tuple[int, int]:
    """A fixed value or an inclusive [low, high] range, as a range."""
    if isinstance(value, int):
        return (value, value)
    if isinstance(value, list) and len(value) == 2 and value[0] <= value[1]:
        return (value[0], value[1])
    raise ValueError(f"{name} must be an integer or an ordered [low, high] range.")


def load_unit_layout(path: Path = LAYOUT_PATH) -> UnitLayout:
    """Load the floor and patients, rejecting a layout the app couldn't draw."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    floor = raw["floor"]
    beds = tuple(Bed(b["label"], b["row"], b["column"]) for b in raw["beds"])
    cells = [(b.row, b.column) for b in beds]
    if len(set(cells)) != len(cells):
        raise ValueError("Two beds share a grid cell.")
    if any(
        not (1 <= b.row <= floor["rows"] and 1 <= b.column <= floor["columns"])
        or b.row == floor["corridor_row"]
        for b in beds
    ):
        raise ValueError("Every bed must sit on the grid, off the corridor row.")
    patients = tuple(
        PatientSpec(
            role=p["role"],
            scenario=p["scenario"],
            episode_type=p["episode_type"],
            delayed_repeat_subtype=p.get("delayed_repeat_subtype"),
            drawn_actions=p.get("actions") == "drawn",
            readings=tuple(
                FixtureReading(
                    r["after_minutes"],
                    _pair(r["systolic"], "systolic"),
                    _pair(r["diastolic"], "diastolic"),
                )
                for r in p.get("readings", [])
            ),
        )
        for p in raw["patients"]
    )
    if len(patients) > len(beds):
        raise ValueError("More patients than beds.")
    hour, minute = (int(part) for part in raw["shift"]["start"].split(":"))
    return UnitLayout(
        columns=floor["columns"],
        rows=floor["rows"],
        corridor_row=floor["corridor_row"],
        station=floor["station"],
        beds=beds,
        shift_start=(hour, minute),
        min_reading_gap=timedelta(minutes=raw["shift"]["min_reading_gap_minutes"]),
        patients=patients,
    )


def _apply_fixture(
    readings: list[Reading], fixture: tuple[FixtureReading, ...], rng: random.Random,
    protocol: Protocol,
) -> list[Reading]:
    """Replace or add the story's readings, placed relative to onset."""
    if not fixture:
        return readings
    onset = next(r.time for r in readings if is_severe(r, protocol))
    by_time = {r.time: r for r in readings}
    patient_id = readings[0].patient_id
    for point in fixture:
        when = onset + timedelta(minutes=point.after_minutes)
        by_time[when] = Reading(
            patient_id, when, rng.randint(*point.systolic), rng.randint(*point.diastolic),
        )
    return [by_time[t] for t in sorted(by_time)]


def _spaced(readings: list[Reading], gap: timedelta) -> list[Reading]:
    """Only the readings the unit would take: each at least `gap` after the last kept.

    The generator's fixtures include readings 10 minutes apart, which the unit
    avoids (a reading that early can't confirm persistence, and a severe one
    means coming back again). Dropped here for the floor only; the generator
    and the simulations that use it are unchanged.
    """
    kept: list[Reading] = []
    for reading in readings:
        if not kept or reading.time - kept[-1].time >= gap:
            kept.append(reading)
    return kept


def _draw_actions(
    patient_id: str, readings: list[Reading], rng: random.Random,
    workflow: WorkflowConfig, protocol: Protocol,
) -> list[Action]:
    """Acknowledgment and dose for a treated patient, from the assumed delays.

    Counted from notification (CONFIRMED) and from acknowledgment, as in
    config/workflow.toml. Redrawn until the dose comes before the first reading
    below the severe range, so the dose precedes the blood pressure coming down.
    """
    status = evaluate_playback_episode(readings, protocol)
    confirmed = next(e.time for e in status.events if e.kind is EventKind.CONFIRMED)
    closed = next(
        (e.time for e in status.events if e.kind is EventKind.EPISODE_CLOSED and e.time > confirmed),
        None,
    )
    for _ in range(_MAX_DRAWS):
        acknowledged = confirmed + timedelta(minutes=rng.randint(*workflow.acknowledgment_minutes))
        dosed = acknowledged + timedelta(minutes=rng.randint(*workflow.medication_minutes))
        if closed is None or dosed < closed:
            return [
                Action(patient_id, acknowledged, ActionKind.PROVIDER_ACKNOWLEDGED),
                Action(patient_id, dosed, ActionKind.DOSE_GIVEN),
            ]
    raise ValueError("No drawn dose came before the blood pressure fell; check the delay ranges.")


def build_shift(
    seed: int,
    protocol: Protocol,
    layout: UnitLayout | None = None,
    generator: GeneratorConfig | None = None,
    workflow: WorkflowConfig | None = None,
    day: datetime | None = None,
) -> Shift:
    """One shift: patients assigned to beds, with readings and actions, from `seed`."""
    layout = layout or load_unit_layout()
    generator = generator or load_generator_config()
    workflow = workflow or load_workflow_config()
    day = day or datetime(2026, 11, 13)
    start = day.replace(hour=layout.shift_start[0], minute=layout.shift_start[1])
    rng = random.Random(seed)

    beds = list(layout.beds)
    rng.shuffle(beds)
    roles, episode_types, readings, actions = {}, {}, {}, {}
    for index, (spec, bed) in enumerate(zip(layout.patients, beds)):
        stream = generate_bp_readings(
            bed.label, start, seed=seed * 100 + index, scenario=spec.scenario,
            delayed_repeat_subtype=spec.delayed_repeat_subtype,
            config=generator, protocol=protocol,
        )
        stream = _apply_fixture(stream, spec.readings, rng, protocol)
        stream = _spaced(stream, layout.min_reading_gap)
        roles[bed.label] = spec.role
        episode_types[bed.label] = spec.episode_type
        readings[bed.label] = stream
        if spec.drawn_actions:
            actions[bed.label] = _draw_actions(bed.label, stream, rng, workflow, protocol)
    return Shift(
        seed=seed,
        start=start,
        end=start + timedelta(hours=generator.duration_hours),
        roles=roles,
        episode_types=episode_types,
        readings=readings,
        actions=actions,
    )


# Card colours by phase: background, border, label text. Matches the bedside
# badges' hues. The label is a darker shade than the border, so it reads at
# 4.8:1 or better against its background; the border colours alone fell as
# low as 1.3:1 (Routine).
PHASE_COLOURS = {
    EpisodePhase.NONE: ("#f0fdf4", "#86efac", "#15803d"),
    EpisodePhase.RESOLVED: ("#f0fdf4", "#16a34a", "#15803d"),
    EpisodePhase.REPEAT_PENDING: ("#fefce8", "#eab308", "#a16207"),
    EpisodePhase.REPEAT_DUE: ("#fff7ed", "#f97316", "#c2410c"),
    EpisodePhase.CONFIRMED: ("#fef2f2", "#dc2626", "#b91c1c"),
    EpisodePhase.ESCALATED: ("#fdf2f8", "#9d174d", "#9d174d"),
}

PHASE_LABELS = {
    EpisodePhase.NONE: "Routine",
    EpisodePhase.RESOLVED: "Resolved",
    EpisodePhase.REPEAT_PENDING: "Repeat pending",
    EpisodePhase.REPEAT_DUE: "Repeat due",
    EpisodePhase.CONFIRMED: "Confirmed",
    EpisodePhase.ESCALATED: "Escalated",
}


def card_note(status: EpisodeStatus | None, now: datetime) -> str:
    """The bed's next deadline, or what just happened, in a few words.

    Read from the status's own target times and events; no rule lives here.
    """
    if status is None or status.phase is EpisodePhase.NONE:
        return ""
    if status.phase is EpisodePhase.REPEAT_PENDING:
        return f"Repeat due {status.repeat_target_time:%H:%M}"
    if status.phase is EpisodePhase.REPEAT_DUE:
        return "Repeat reading due now"
    if status.phase is EpisodePhase.RESOLVED:
        return f"Closed {status.latest_event.time:%H:%M}" if status.latest_event else ""
    # Confirmed or escalated: the current episode's dose, or the treatment target.
    opened_at = max(i for i, e in enumerate(status.events) if e.kind is EventKind.EPISODE_OPENED)
    dose = next(
        (e for e in status.events[opened_at:] if e.kind is EventKind.DOSE_RECORDED), None,
    )
    if dose:
        return f"Dose given {dose.time:%H:%M}"
    target = status.treatment_target_time
    if now >= target:
        return f"Treatment target passed {target:%H:%M}"
    return f"Treatment target {target:%H:%M}"
