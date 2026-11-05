"""Per-patient episode logic: readings and staff actions in, events out.

This is the part that replaces memory on the unit. For each patient it tracks
an open episode from the first severe reading, through the repeat that
confirms persistence, to treatment and closing, and reports each step as an
Event.

Two kinds of input drive it:
    observe()  a Reading or an Action arrives
    tick()     time passes with nothing arriving, so deadlines can fire
               (a repeat that's overdue, a notification nobody acknowledged)

All clinical and timing values come from Protocol (config/protocol.toml).
"""

from dataclasses import dataclass, field
from datetime import datetime

from htn_alert.contract import Action, ActionKind, Event, EventKind, Reading
from htn_alert.protocol import Protocol
from htn_alert.rules import is_severe


@dataclass
class _PatientState:
    """Internal episode tracking state for one patient."""

    patient_id: str
    active: bool = False
    onset: datetime | None = None
    confirmed: bool = False
    confirmed_time: datetime | None = None
    repeat_due_fired: bool = False
    repeat_overdue_fired: bool = False
    escalated_fired: bool = False
    provider_acknowledged: bool = False
    non_severe_within_15: bool = False
    readings: list[Reading] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


class EpisodeTracker:
    """Tracks episodes for every patient on the unit."""

    def __init__(self, protocol: Protocol) -> None:
        self.protocol = protocol
        self._patients: dict[str, _PatientState] = {}

    def _get_patient(self, patient_id: str) -> _PatientState:
        if patient_id not in self._patients:
            self._patients[patient_id] = _PatientState(patient_id=patient_id)
        return self._patients[patient_id]

    def get_patient_events(self, patient_id: str) -> list[Event]:
        """Return all events recorded for a patient in chronological order."""
        return list(self._get_patient(patient_id).events)

    def get_latest_reading(self, patient_id: str) -> Reading | None:
        """Return the most recent reading observed for a patient."""
        readings = self._get_patient(patient_id).readings
        return readings[-1] if readings else None

    def observe(self, item: Reading | Action) -> list[Event]:
        """Take in one reading or action; return the events it causes."""
        events: list[Event] = []
        state = self._get_patient(item.patient_id)

        if isinstance(item, Action):
            state.actions.append(item)
            if item.kind == ActionKind.PROVIDER_ACKNOWLEDGED:
                state.provider_acknowledged = True
            return events

        # It is a Reading
        state.readings.append(item)
        severe = is_severe(item, self.protocol)

        if severe:
            if not state.active:
                # Check whether this severe reading folds back into an earlier episode
                # within repeat_max of the earlier onset
                if state.onset is not None and (item.time - state.onset) <= self.protocol.repeat_max:
                    # Folds back into previous episode per SMFM Figure 1 / protocol.toml
                    state.active = True
                    if not state.confirmed:
                        state.confirmed = True
                        state.confirmed_time = item.time
                        e = Event(
                            patient_id=item.patient_id,
                            time=item.time,
                            kind=EventKind.CONFIRMED,
                            detail=f"Persistent severe hypertension confirmed at {item.systolic}/{item.diastolic} mmHg (folded back into episode).",
                        )
                        events.append(e)
                        state.events.append(e)
                else:
                    # Open a new episode
                    state.active = True
                    state.onset = item.time
                    state.confirmed = False
                    state.confirmed_time = None
                    state.repeat_due_fired = False
                    state.repeat_overdue_fired = False
                    state.escalated_fired = False
                    state.provider_acknowledged = False
                    state.non_severe_within_15 = False
                    e = Event(
                        patient_id=item.patient_id,
                        time=item.time,
                        kind=EventKind.EPISODE_OPENED,
                        detail=f"Severe blood pressure observed: {item.systolic}/{item.diastolic} mmHg.",
                    )
                    events.append(e)
                    state.events.append(e)
            else:
                # Already active episode
                elapsed = item.time - state.onset
                if elapsed >= self.protocol.repeat_min:
                    if not state.confirmed:
                        state.confirmed = True
                        state.confirmed_time = item.time
                        e = Event(
                            patient_id=item.patient_id,
                            time=item.time,
                            kind=EventKind.CONFIRMED,
                            detail=f"Persistent severe hypertension confirmed: repeat {item.systolic}/{item.diastolic} mmHg at {item.time.strftime('%H:%M')}.",
                        )
                        events.append(e)
                        state.events.append(e)
        else:
            # Non-severe reading
            if state.active:
                elapsed = item.time - state.onset
                if elapsed <= self.protocol.repeat_min:
                    state.non_severe_within_15 = True
                state.active = False
                e = Event(
                    patient_id=item.patient_id,
                    time=item.time,
                    kind=EventKind.EPISODE_CLOSED,
                    detail=f"Episode closed: blood pressure below severe range ({item.systolic}/{item.diastolic} mmHg).",
                )
                events.append(e)
                state.events.append(e)

        return events

    def tick(self, now: datetime) -> list[Event]:
        """Advance the clock to `now`; return any deadline events that fire."""
        events: list[Event] = []

        for pid, state in self._patients.items():
            if state.onset is None:
                continue

            elapsed = now - state.onset

            # If the episode is currently active:
            if state.active:
                # 1. REPEAT_DUE: fires at or after repeat_min if no repeat reading has arrived
                repeat_readings = [r for r in state.readings if r.time > state.onset]
                if not state.repeat_due_fired and elapsed >= self.protocol.repeat_min:
                    if not repeat_readings:
                        state.repeat_due_fired = True
                        e = Event(
                            patient_id=pid,
                            time=state.onset + self.protocol.repeat_min,
                            kind=EventKind.REPEAT_DUE,
                            detail="Repeat blood pressure measurement due.",
                        )
                        events.append(e)
                        state.events.append(e)

                # 2. Missing recheck: when time has progressed beyond repeat_min without a non-severe check
                if elapsed > self.protocol.repeat_min:
                    if not state.repeat_overdue_fired and not repeat_readings:
                        state.repeat_overdue_fired = True
                        e = Event(
                            patient_id=pid,
                            time=now,
                            kind=EventKind.REPEAT_OVERDUE,
                            detail="Repeat measurement overdue.",
                        )
                        events.append(e)
                        state.events.append(e)
                    # SMFM Table 1: persistent if not documented below severe within 15 minutes of onset
                    if not state.confirmed and not state.non_severe_within_15:
                        state.confirmed = True
                        state.confirmed_time = now
                        e = Event(
                            patient_id=pid,
                            time=now,
                            kind=EventKind.CONFIRMED,
                            detail="Persistent severe hypertension confirmed (missing recheck documented below severe within repeat window).",
                        )
                        events.append(e)
                        state.events.append(e)

            # 3. Escalation: counts from provider notification (CONFIRMED)
            if state.confirmed and not state.escalated_fired:
                if not state.provider_acknowledged and state.confirmed_time is not None:
                    if (now - state.confirmed_time) >= self.protocol.escalate_unacknowledged:
                        state.escalated_fired = True
                        e = Event(
                            patient_id=pid,
                            time=state.confirmed_time + self.protocol.escalate_unacknowledged,
                            kind=EventKind.ESCALATED,
                            detail="Attending provider notification unacknowledged within protocol window.",
                        )
                        events.append(e)
                        state.events.append(e)

        return events
