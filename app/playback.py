"""Replaying readings over time and calculating protocol countdowns.

This module provides plain, testable helper functions for the demonstration app:
filtering readings visible at a simulated point in time, determining whether an
episode is open, pending repeat, confirmed or resolved, and calculating
countdown timers toward protocol targets.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from htn_alert.contract import Reading
from htn_alert.protocol import Protocol
from htn_alert.rules import is_severe


class EpisodePhase(str, Enum):
    """Clinical progression phases for severe hypertension tracking."""

    NONE = "none"
    CRITICAL_EMERGENCY = "critical_emergency"  # extreme danger range (>=180 or >=120 mmHg) -> immediate alarm
    ROUTINE_DUE = "routine_due"                # routine 15-min interval reached -> notice to nurse
    REPEAT_PENDING = "repeat_pending"          # severe reading recorded; waiting for the 15-min repeat window
    REPEAT_DUE = "repeat_due"                  # >=15 min and <=60 min since first severe; recheck is due
    CONFIRMED = "confirmed"                    # second severe reading confirmed within 15-60 min
    RESOLVED = "resolved"                      # repeat reading was non-severe; episode closed
    EXPIRED = "expired"                        # >60 min elapsed without a repeat reading


@dataclass(frozen=True)
class EpisodeStatus:
    """The current state of a patient's episode at a specific point in time."""

    phase: EpisodePhase
    first_severe_reading: Reading | None = None
    repeat_reading: Reading | None = None
    repeat_target_time: datetime | None = None
    repeat_deadline_time: datetime | None = None
    treatment_target_time: datetime | None = None
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
) -> EpisodeStatus:
    """Evaluate patient episode status across a stream of readings up to `simulated_now`.

    Intent: Replaces manual calculation for the UI timeline, evaluating whether
    a first severe reading has initiated a 15-minute countdown, whether a repeat
    reading confirmed persistence, or whether the window has expired.
    """
    if not readings:
        return EpisodeStatus(phase=EpisodePhase.NONE, detail="No readings recorded.")

    sorted_readings = sorted(readings, key=lambda r: r.time)
    if simulated_now is not None:
        sorted_readings = [r for r in sorted_readings if r.time <= simulated_now]
        clock = simulated_now
    else:
        clock = sorted_readings[-1].time if sorted_readings else datetime.now()

    if not sorted_readings:
        return EpisodeStatus(phase=EpisodePhase.NONE, detail="No readings yet at simulated time.")

    latest = sorted_readings[-1]

    # Extreme dangerous crisis range (systolic >= 180 or diastolic >= 120 mmHg)
    # Triggers an immediate bedside alarm for the nurse!
    if latest.systolic >= 180 or latest.diastolic >= 120:
        return EpisodeStatus(
            phase=EpisodePhase.CRITICAL_EMERGENCY,
            first_severe_reading=latest,
            detail=(
                f"🚨 CRITICAL DANGER ALARM ({latest.systolic}/{latest.diastolic} mmHg) — "
                f"Extreme danger threshold exceeded! Immediate bedside nurse intervention and stat provider notification required!"
            ),
        )

    # Find first severe reading
    first_severe_idx = next(
        (i for i, r in enumerate(sorted_readings) if is_severe(r, protocol)),
        None,
    )
    if first_severe_idx is None:
        first_reading = sorted_readings[0]
        elapsed_routine = clock - first_reading.time
        target_routine = first_reading.time + timedelta(minutes=15)
        if elapsed_routine >= timedelta(minutes=15):
            return EpisodeStatus(
                phase=EpisodePhase.ROUTINE_DUE,
                repeat_target_time=target_routine,
                detail=(
                    f"🔔 Nurse Notice: 15 minutes elapsed since routine baseline ({first_reading.systolic}/{first_reading.diastolic} mmHg). "
                    f"Scheduled vital signs re-check due now."
                ),
            )
        return EpisodeStatus(
            phase=EpisodePhase.NONE,
            repeat_target_time=target_routine,
            detail=f"Normal range ({latest.systolic}/{latest.diastolic} mmHg). Scheduled 15-minute notice active (due at {target_routine.strftime('%H:%M')}).",
        )

    first_severe = sorted_readings[first_severe_idx]
    target_time = first_severe.time + protocol.repeat_min
    deadline_time = first_severe.time + protocol.repeat_max

    # Look for subsequent repeat readings
    subsequent_readings = sorted_readings[first_severe_idx + 1:]

    for repeat in subsequent_readings:
        elapsed = repeat.time - first_severe.time

        # If repeat is taken earlier than repeat_min, protocol requires another repeat at >=15 min
        if elapsed < protocol.repeat_min:
            continue

        if elapsed <= protocol.repeat_max:
            if is_severe(repeat, protocol):
                treatment_deadline = repeat.time + protocol.treatment_target
                return EpisodeStatus(
                    phase=EpisodePhase.CONFIRMED,
                    first_severe_reading=first_severe,
                    repeat_reading=repeat,
                    repeat_target_time=target_time,
                    repeat_deadline_time=deadline_time,
                    treatment_target_time=treatment_deadline,
                    detail=(
                        f"Persistent severe HTN confirmed: initial {first_severe.systolic}/{first_severe.diastolic} "
                        f"at {first_severe.time.strftime('%H:%M')}, repeat {repeat.systolic}/{repeat.diastolic} "
                        f"at {repeat.time.strftime('%H:%M')}."
                    ),
                )
            else:
                return EpisodeStatus(
                    phase=EpisodePhase.RESOLVED,
                    first_severe_reading=first_severe,
                    repeat_reading=repeat,
                    repeat_target_time=target_time,
                    repeat_deadline_time=deadline_time,
                    detail=(
                        f"Resolved: repeat reading {repeat.systolic}/{repeat.diastolic} mmHg "
                        f"at {repeat.time.strftime('%H:%M')} is below severe range."
                    ),
                )

    # No valid repeat reading in 15-60 min window yet. Check current clock against deadlines.
    elapsed_now = clock - first_severe.time
    if elapsed_now < protocol.repeat_min:
        return EpisodeStatus(
            phase=EpisodePhase.REPEAT_PENDING,
            first_severe_reading=first_severe,
            repeat_target_time=target_time,
            repeat_deadline_time=deadline_time,
            detail=(
                f"Severe reading {first_severe.systolic}/{first_severe.diastolic} mmHg. "
                f"Repeat due in 15 minutes (at {target_time.strftime('%H:%M')})."
            ),
        )
    elif elapsed_now <= protocol.repeat_max:
        return EpisodeStatus(
            phase=EpisodePhase.REPEAT_DUE,
            first_severe_reading=first_severe,
            repeat_target_time=target_time,
            repeat_deadline_time=deadline_time,
            detail=(
                f"Repeat overdue: {int(elapsed_now.total_seconds() // 60)} minutes since first severe reading. "
                f"Recheck required by {deadline_time.strftime('%H:%M')}."
            ),
        )
    else:
        return EpisodeStatus(
            phase=EpisodePhase.EXPIRED,
            first_severe_reading=first_severe,
            repeat_target_time=target_time,
            repeat_deadline_time=deadline_time,
            detail="Repeat window expired (>60 minutes without confirmed repeat). Episode lapsed.",
        )


def generate_sbar_handoff(
    patient_id: str,
    status: EpisodeStatus,
    readings: list[Reading],
) -> str:
    """Generate an SBAR clinical handoff communication draft for the attending provider.

    Intent: Demonstrates autonomous agent communication capability upon
    confirmation of severe range blood pressure.
    """
    if status.phase == EpisodePhase.CRITICAL_EMERGENCY and status.first_severe_reading:
        r = status.first_severe_reading
        return (
            f"**🚨 STAT CRITICAL EMERGENCY ALERT:**\n"
            f"**SITUATION:** Immediate bedside physician alert for Patient {patient_id}. Extreme hypertensive crisis ({r.systolic}/{r.diastolic} mmHg).\n\n"
            f"**BACKGROUND:** Recorded at {r.time.strftime('%H:%M')}. Systolic ≥ 180 or Diastolic ≥ 120 mmHg represents an acute hypertensive emergency.\n\n"
            f"**ASSESSMENT:** Extreme maternal stroke and eclampsia risk. Immediate action required without waiting for a repeat observation window.\n\n"
            f"**RECOMMENDATION:**\n"
            f"- Attending physician bedside arrival STAT.\n"
            f"- Order immediate first-line IV antihypertensive (IV labetalol / hydralazine).\n"
            f"- Initiate seizure precautions and IV magnesium sulfate protocol."
        )

    if status.phase != EpisodePhase.CONFIRMED or not status.first_severe_reading or not status.repeat_reading:
        return "SBAR handoff is only generated upon confirmed persistent severe hypertension or critical crisis."

    r1 = status.first_severe_reading
    r2 = status.repeat_reading
    rx_target_str = (
        status.treatment_target_time.strftime("%H:%M")
        if status.treatment_target_time
        else "within 60 min"
    )

    return (
        f"**SITUATION:**\n"
        f"Urgent notification: Patient {patient_id} has confirmed persistent severe-range hypertension on L&D.\n\n"
        f"**BACKGROUND:**\n"
        f"- Initial severe BP: {r1.systolic}/{r1.diastolic} mmHg at {r1.time.strftime('%H:%M')}\n"
        f"- Repeat confirmatory BP: {r2.systolic}/{r2.diastolic} mmHg at {r2.time.strftime('%H:%M')}\n\n"
        f"**ASSESSMENT:**\n"
        f"Patient meets ACOG/SMFM criteria for persistent severe gestational hypertension / preeclampsia with severe features. "
        f"Immediate antihypertensive therapy is indicated.\n\n"
        f"**RECOMMENDATION:**\n"
        f"- Provider evaluation requested immediately.\n"
        f"- Order first-line IV labetalol, hydralazine, or oral nifedipine per unit protocol.\n"
        f"- Time-to-treatment target: administer medication before {rx_target_str}."
    )

