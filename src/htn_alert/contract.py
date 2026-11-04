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

    Data limitation: readings come only from the L&D monitors, at intervals of
    15 minutes or more, as confirmed with the School of Medicine team. The
    hospital doesn't want nurses taking a reading before 15 minutes. Nothing
    here rejects a shorter gap, because SMFM's worked examples use them to test
    the definition.
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
    """What the episode logic reports, in roughly the order it happens.

    How to read a closing: it isn't final until the repeat window has passed,
    because a severe reading in that time folds back into the same episode. A
    patient's current state is the latest of OPENED, REOPENED and CLOSED, and
    an episode's end is its last CLOSED. An episode has one OPENED, whose time
    is the onset; pass it to episodes.treatment_deadline() for the target.

    CONFIRMED doubles as the notification to the provider: the escalation
    timer counts from it, and the episode logic has no separate notification
    input. A missing recheck confirms with no second reading, and its detail
    says so, which is how the app can still prompt for one.
    """

    EPISODE_OPENED = "episode_opened"  # first severe reading
    REPEAT_DUE = "repeat_due"  # time to recheck
    CONFIRMED = "confirmed"  # persistent severe hypertension; notifies the provider
    DOSE_RECORDED = "dose_recorded"  # a dose was given during the episode
    ESCALATED = "escalated"  # notification not acknowledged in time
    EPISODE_CLOSED = "episode_closed"  # resolved, or not confirmed
    EPISODE_REOPENED = "episode_reopened"  # severe again, undoing a closing


@dataclass(frozen=True)
class Event:
    """Something the episode logic reports about one patient."""

    patient_id: str
    time: datetime
    kind: EventKind
    detail: str = ""  # human-readable context, e.g. why an episode closed
