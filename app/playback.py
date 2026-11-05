"""Replaying readings over time and calculating protocol countdowns.

This module provides plain, testable helper functions for the demonstration app:
filtering readings visible at a simulated point in time, replaying readings through
the shared EpisodeTracker, determining unit-wide patient status at time t, and
calculating protocol countdown timers.

All episode rules live in EpisodeTracker (src/htn_alert/episodes.py) and timings
come from Protocol (config/protocol.toml). No episode rules live in app/.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from htn_alert.contract import Action, Event, EventKind, Reading
from htn_alert.episodes import EpisodeTracker
from htn_alert.protocol import Protocol
from htn_alert.rules import is_severe


class EpisodePhase(str, Enum):
    """Clinical progression phases mapped directly from EpisodeTracker events."""

    NONE = "none"                      # No episode opened / routine baseline
    REPEAT_PENDING = "repeat_pending"  # EPISODE_OPENED: 15-min countdown active
    REPEAT_DUE = "repeat_due"          # REPEAT_DUE: 15-min repeat due now
    REPEAT_OVERDUE = "repeat_overdue"  # REPEAT_OVERDUE: repeat overdue
    CONFIRMED = "confirmed"            # CONFIRMED: persistent severe hypertension
    ESCALATED = "escalated"            # ESCALATED: unacknowledged escalation
    RESOLVED = "resolved"              # EPISODE_CLOSED: closed below severe range


@dataclass(frozen=True)
class EpisodeStatus:
    """The current state of a patient's episode at a specific point in time."""

    phase: EpisodePhase
    patient_id: str = ""
    latest_reading: Reading | None = None
    first_severe_reading: Reading | None = None
    repeat_reading: Reading | None = None
    repeat_target_time: datetime | None = None
    repeat_deadline_time: datetime | None = None
    treatment_target_time: datetime | None = None
    confirmed_time: datetime | None = None
    escalation_deadline_time: datetime | None = None
    events: list[Event] = field(default_factory=list)
    latest_event: Event | None = None
    detail: str = ""


def filter_readings_up_to(
    readings: list[Reading],
    simulated_now: datetime,
) -> list[Reading]:
    """Return readings that have arrived by `simulated_now`, in chronological order.

    Intent: Allows the replay scrubber to reconstruct what the unit saw at
    any given minute of a patient's timeline.
    """
    sorted_readings = sorted(readings, key=lambda r: r.time)
    return [r for r in sorted_readings if r.time <= simulated_now]


def latest_reading_per_patient(
    readings: list[Reading],
    simulated_now: datetime | None = None,
) -> dict[str, Reading]:
    """Return the most recent reading for each patient at or before `simulated_now`.

    Plain, testable function fulfilling Issue #8 and Issue #18 requirements.
    """
    sorted_readings = sorted(readings, key=lambda r: r.time)
    if simulated_now is not None:
        sorted_readings = [r for r in sorted_readings if r.time <= simulated_now]

    latest: dict[str, Reading] = {}
    for r in sorted_readings:
        latest[r.patient_id] = r
    return latest


def calculate_countdown(
    target_time: datetime,
    current_time: datetime,
) -> tuple[int, bool, str]:
    """Calculate remaining seconds until `target_time`.

    Returns:
        (remaining_seconds, is_overdue, display_text)
        If current_time is past target_time, remaining_seconds is 0 and
        display_text shows the overdue amount prefixed with '+'.
    """
    diff = target_time - current_time
    total_seconds = int(diff.total_seconds())

    if total_seconds >= 0:
        minutes, seconds = divmod(total_seconds, 60)
        return total_seconds, False, f"{minutes:02d}:{seconds:02d}"

    overdue_seconds = abs(total_seconds)
    minutes, seconds = divmod(overdue_seconds, 60)
    return 0, True, f"+{minutes:02d}:{seconds:02d}"


def evaluate_playback_episode(
    readings: list[Reading],
    protocol: Protocol,
    simulated_now: datetime | None = None,
    actions: list[Action] | None = None,
) -> EpisodeStatus:
    """Evaluate patient episode status strictly using EpisodeTracker.

    Replaces ad-hoc playback evaluation with events from EpisodeTracker, so
    the app and evaluation can never disagree on an episode definition.
    """
    if not readings:
        return EpisodeStatus(phase=EpisodePhase.NONE, detail="No readings recorded.")

    patient_id = readings[0].patient_id
    sorted_readings = sorted(readings, key=lambda r: r.time)

    if simulated_now is not None:
        visible_readings = [r for r in sorted_readings if r.time <= simulated_now]
        clock = simulated_now
    else:
        visible_readings = sorted_readings
        clock = sorted_readings[-1].time

    if not visible_readings:
        return EpisodeStatus(
            phase=EpisodePhase.NONE,
            patient_id=patient_id,
            detail="No readings yet at simulated time.",
        )

    tracker = EpisodeTracker(protocol)
    events: list[Event] = []

    # Interleave readings and actions chronologically
    items: list[tuple[datetime, Reading | Action]] = [(r.time, r) for r in visible_readings]
    if actions:
        items += [(a.time, a) for a in actions if a.time <= clock]
    items.sort(key=lambda x: x[0])

    for item_time, item in items:
        events += tracker.tick(item_time)
        events += tracker.observe(item)

    # Advance clock to simulated_now
    events += tracker.tick(clock)

    latest_r = visible_readings[-1]
    patient_events = tracker.get_patient_events(patient_id)
    latest_event = patient_events[-1] if patient_events else None

    # Determine onset, repeat readings, and target timestamps
    first_severe = next((r for r in visible_readings if is_severe(r, protocol)), None)
    repeat_r = None
    onset_time = None
    target_time = None
    deadline_time = None
    treatment_target_time = None

    # Check opening event
    opened_events = [e for e in patient_events if e.kind == EventKind.EPISODE_OPENED]
    if opened_events:
        onset_time = opened_events[-1].time
        target_time = onset_time + protocol.repeat_min
        deadline_time = onset_time + protocol.repeat_max
        treatment_target_time = onset_time + protocol.treatment_target

        # Find repeat reading after onset
        repeat_r = next((r for r in visible_readings if r.time > onset_time), None)

    # Map current tracker state to EpisodePhase
    if not opened_events:
        return EpisodeStatus(
            phase=EpisodePhase.NONE,
            patient_id=patient_id,
            latest_reading=latest_r,
            events=patient_events,
            detail=f"Normal reference range ({latest_r.systolic}/{latest_r.diastolic} mmHg). Routine monitoring continues.",
        )

    # If episode closed
    last_event_kind = latest_event.kind if latest_event else None
    if last_event_kind == EventKind.EPISODE_CLOSED:
        return EpisodeStatus(
            phase=EpisodePhase.RESOLVED,
            patient_id=patient_id,
            latest_reading=latest_r,
            first_severe_reading=first_severe,
            repeat_reading=repeat_r,
            repeat_target_time=target_time,
            repeat_deadline_time=deadline_time,
            treatment_target_time=treatment_target_time,
            events=patient_events,
            latest_event=latest_event,
            detail=f"Resolved: reading {latest_r.systolic}/{latest_r.diastolic} mmHg is below severe range.",
        )

    # Active states
    confirmed_events = [e for e in patient_events if e.kind == EventKind.CONFIRMED]
    escalated_events = [e for e in patient_events if e.kind == EventKind.ESCALATED]

    if escalated_events:
        return EpisodeStatus(
            phase=EpisodePhase.ESCALATED,
            patient_id=patient_id,
            latest_reading=latest_r,
            first_severe_reading=first_severe,
            repeat_reading=repeat_r,
            repeat_target_time=target_time,
            repeat_deadline_time=deadline_time,
            treatment_target_time=treatment_target_time,
            confirmed_time=confirmed_events[-1].time if confirmed_events else None,
            events=patient_events,
            latest_event=latest_event,
            detail="Escalated: provider notification unacknowledged within protocol escalation window.",
        )

    if confirmed_events:
        return EpisodeStatus(
            phase=EpisodePhase.CONFIRMED,
            patient_id=patient_id,
            latest_reading=latest_r,
            first_severe_reading=first_severe,
            repeat_reading=repeat_r,
            repeat_target_time=target_time,
            repeat_deadline_time=deadline_time,
            treatment_target_time=treatment_target_time,
            confirmed_time=confirmed_events[-1].time,
            events=patient_events,
            latest_event=latest_event,
            detail=(
                f"Persistent severe HTN confirmed: initial {first_severe.systolic}/{first_severe.diastolic} "
                f"at {first_severe.time.strftime('%H:%M')}"
                + (f", repeat {repeat_r.systolic}/{repeat_r.diastolic} at {repeat_r.time.strftime('%H:%M')}." if repeat_r else " (missing repeat).")
            ),
        )

    overdue_events = [e for e in patient_events if e.kind == EventKind.REPEAT_OVERDUE]
    if overdue_events:
        return EpisodeStatus(
            phase=EpisodePhase.REPEAT_OVERDUE,
            patient_id=patient_id,
            latest_reading=latest_r,
            first_severe_reading=first_severe,
            repeat_reading=repeat_r,
            repeat_target_time=target_time,
            repeat_deadline_time=deadline_time,
            treatment_target_time=treatment_target_time,
            events=patient_events,
            latest_event=latest_event,
            detail="Repeat blood pressure measurement overdue. Immediate recheck required.",
        )

    due_events = [e for e in patient_events if e.kind == EventKind.REPEAT_DUE]
    if due_events:
        return EpisodeStatus(
            phase=EpisodePhase.REPEAT_DUE,
            patient_id=patient_id,
            latest_reading=latest_r,
            first_severe_reading=first_severe,
            repeat_reading=repeat_r,
            repeat_target_time=target_time,
            repeat_deadline_time=deadline_time,
            treatment_target_time=treatment_target_time,
            events=patient_events,
            latest_event=latest_event,
            detail="Repeat blood pressure measurement due now (15 minutes reached).",
        )

    # Otherwise repeat is pending (first severe detected)
    return EpisodeStatus(
        phase=EpisodePhase.REPEAT_PENDING,
        patient_id=patient_id,
        latest_reading=latest_r,
        first_severe_reading=first_severe,
        repeat_reading=repeat_r,
        repeat_target_time=target_time,
        repeat_deadline_time=deadline_time,
        treatment_target_time=treatment_target_time,
        events=patient_events,
        latest_event=latest_event,
        detail=(
            f"Severe reading {first_severe.systolic}/{first_severe.diastolic} mmHg. "
            f"Repeat due in 15 minutes (at {target_time.strftime('%H:%M')})."
        ),
    )


def evaluate_unit_view(
    cohort_readings: dict[str, list[Reading]],
    simulated_now: datetime,
    protocol: Protocol,
) -> dict[str, EpisodeStatus]:
    """Evaluate current episode status across all patients on the unit at `simulated_now`.

    Plain, testable unit view function as specified in Issue #18.
    """
    statuses: dict[str, EpisodeStatus] = {}
    for patient_id, readings in cohort_readings.items():
        statuses[patient_id] = evaluate_playback_episode(
            readings=readings,
            protocol=protocol,
            simulated_now=simulated_now,
        )
    return statuses


def generate_sbar_handoff(
    patient_id: str,
    status: EpisodeStatus,
    readings: list[Reading],
) -> str:
    """Generate a simulated SBAR clinical handoff communication draft for the attending provider.

    Labeled as simulated handoff draft per Issue #17.
    """
    if status.phase not in (EpisodePhase.CONFIRMED, EpisodePhase.ESCALATED) or not status.first_severe_reading:
        return "SBAR handoff is only generated upon confirmed persistent severe hypertension."

    r1 = status.first_severe_reading
    r2 = status.repeat_reading
    rx_target_str = (
        status.treatment_target_time.strftime("%H:%M")
        if status.treatment_target_time
        else "within 60 min"
    )

    r2_str = (
        f"{r2.systolic}/{r2.diastolic} mmHg at {r2.time.strftime('%H:%M')}"
        if r2
        else "Missing repeat reading within 15-min window"
    )

    return (
        f"**SIMULATED ATTENDING PHYSICIAN NOTIFICATION (SBAR DRAFT):**\n\n"
        f"**SITUATION:**\n"
        f"Urgent notification: Patient {patient_id} has confirmed persistent severe-range hypertension on L&D.\n\n"
        f"**BACKGROUND:**\n"
        f"- Initial severe BP: {r1.systolic}/{r1.diastolic} mmHg at {r1.time.strftime('%H:%M')}\n"
        f"- Repeat confirmatory BP: {r2_str}\n\n"
        f"**ASSESSMENT:**\n"
        f"Patient meets ACOG/SMFM criteria for persistent severe gestational hypertension / preeclampsia with severe features. "
        f"Immediate antihypertensive therapy is indicated.\n\n"
        f"**RECOMMENDATION:**\n"
        f"- Attending provider evaluation requested.\n"
        f"- Hospital formulary options: IV labetalol, IV hydralazine, or oral nifedipine per unit protocol.\n"
        f"- Time-to-treatment target: administer medication before {rx_target_str} (60 minutes from onset)."
    )
