"""The shared data contract between the generator, the episode logic, the app
and the evaluation.

The flow:

    generator  --Reading, Action-->  episodes  --Event-->  app, evaluate

The generator produces what happens on the unit: blood pressure readings and
staff actions. The episode logic sees only those, as a real system would, and
emits events. The app and the evaluation consume events.

Expected to grow after the pitch team confirms the workflow: new fields on
Reading (e.g. who took it, bedside verification, patient status) and new
ActionKind / EventKind members. Add to these types; don't change the meaning
of what's already here.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


@dataclass(frozen=True)
class Reading:
    """One blood pressure measurement, as the system would receive it.

    Ground truth the system can't know (e.g. that a reading is spurious
    because the cuff was misplaced) stays with the generator, not here.
    """

    patient_id: str
    time: datetime
    systolic: int  # mmHg
    diastolic: int  # mmHg


class ActionKind(Enum):
    """Things staff do that the episode logic needs to know about."""

    PROVIDER_ACKNOWLEDGED = "provider_acknowledged"
    DOSE_GIVEN = "dose_given"


@dataclass(frozen=True)
class Action:
    """A staff action on one patient, at a point in time."""

    patient_id: str
    time: datetime
    kind: ActionKind


class EventKind(Enum):
    """What the episode logic reports, in roughly the order it happens."""

    EPISODE_OPENED = "episode_opened"  # first severe reading
    REPEAT_DUE = "repeat_due"  # time to recheck
    REPEAT_OVERDUE = "repeat_overdue"  # recheck still missing
    CONFIRMED = "confirmed"  # persistent severe hypertension
    ESCALATED = "escalated"  # notification not acknowledged in time
    EPISODE_CLOSED = "episode_closed"  # resolved, or not confirmed


@dataclass(frozen=True)
class Event:
    """Something the episode logic reports about one patient."""

    patient_id: str
    time: datetime
    kind: EventKind
    detail: str = ""  # human-readable context, e.g. why an episode closed
