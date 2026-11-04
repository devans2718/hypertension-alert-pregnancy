"""Per-patient episode logic: readings and staff actions in, events out.

This is the part that replaces memory on the unit. For each patient it tracks
an open episode from the first severe reading, through the repeat that
confirms persistence, to treatment and closing, and reports each step as an
Event. This is the one place episode rules live; the app and the evaluation
read its events.

Two kinds of input drive it:
    observe()  a Reading or an Action arrives
    tick()     time passes with nothing arriving, so deadlines can fire
               (a recheck that's missing, a notification nobody acknowledged)

Each patient's items are expected in time order. The definitions come from
SMFM, through config/protocol.toml and tests/test_smfm_examples.py. This is a
research prototype running on synthetic data, not for clinical use.
"""

from dataclasses import dataclass
from datetime import datetime

from htn_alert.contract import Action, ActionKind, Event, EventKind, Reading
from htn_alert.protocol import Protocol
from htn_alert.rules import is_severe


def treatment_deadline(onset: datetime, protocol: Protocol) -> datetime:
    """When the treatment target falls, given EPISODE_OPENED's time.

    Lives here so the app and the evaluation share one calculation. The clock
    counts from onset, not from confirmation, and a reopening doesn't move it.
    """
    return onset + protocol.treatment_target


@dataclass
class _Episode:
    """What the tracker remembers about one patient's latest episode."""

    onset: datetime
    confirmed_at: datetime | None = None
    reopened_at: datetime | None = None
    closed_at: datetime | None = None  # None while open; a reopening clears it
    repeat_due_reported: bool = False
    provider_responded: bool = False  # acknowledged, or a dose was given
    escalated: bool = False


def _should_escalate(episode: _Episode, now: datetime, protocol: Protocol) -> bool:
    """Whether a notified provider's silence should escalate by `now`.

    The single home of the escalation rule. The rule that applies to a late
    confirmation is a placeholder until the team decides it (see #16 and
    config/protocol.toml), so a different choice should only change this
    function. `onset` and `confirmed_at` are both on the episode for that
    reason, and returning True here would escalate at once, because observe()
    and tick() both ask after updating the episode.
    """
    if episode.confirmed_at is None or episode.closed_at is not None:
        return False
    if episode.provider_responded or episode.escalated:
        return False
    # CONFIRMED is the notification. A closing cancels the timer, so a
    # reopening starts it again from the reopening.
    notified = max(episode.confirmed_at, episode.reopened_at or episode.confirmed_at)
    return now - notified > protocol.escalate_unacknowledged


class EpisodeTracker:
    """Tracks episodes for every patient on the unit."""

    def __init__(self, protocol: Protocol) -> None:
        self.protocol = protocol
        self._episodes: dict[str, _Episode] = {}  # each patient's latest

    def observe(self, item: Reading | Action) -> list[Event]:
        """Take in one reading or action; return the events it causes.

        Moves only this patient's clock to the item's time first, so deadlines
        that passed before it arrived are reported before its own events.
        """
        episode = self._episodes.get(item.patient_id)
        events = (
            self._fire_due(item.patient_id, episode, item.time) if episode else []
        )
        if isinstance(item, Reading):
            events += self._take_reading(item)
        else:
            events += self._take_action(item)
        # Asked again because the item may itself have made something due.
        episode = self._episodes.get(item.patient_id)
        if episode:
            events += self._fire_due(item.patient_id, episode, item.time)
        return events

    def tick(self, now: datetime) -> list[Event]:
        """Advance the clock to `now`; return any deadline events that fire."""
        events: list[Event] = []
        for patient_id, episode in self._episodes.items():
            events += self._fire_due(patient_id, episode, now)
        return events

    def _is_current(self, episode: _Episode, now: datetime) -> bool:
        """Whether new input still belongs to this episode.

        A closed episode stays current through the repeat window, because a
        severe reading in that time folds back into it.
        """
        return (
            episode.closed_at is None
            or now - episode.onset <= self.protocol.repeat_max
        )

    def _take_reading(self, reading: Reading) -> list[Event]:
        patient_id, now = reading.patient_id, reading.time
        episode = self._episodes.get(patient_id)
        current = episode is not None and self._is_current(episode, now)

        if not is_severe(reading, self.protocol):
            if current and episode.closed_at is None:
                episode.closed_at = now
                return [Event(
                    patient_id, now, EventKind.EPISODE_CLOSED,
                    "reading below the severe range",
                )]
            return []

        events = []
        if not current:
            episode = _Episode(onset=now)
            self._episodes[patient_id] = episode
            events.append(Event(
                patient_id, now, EventKind.EPISODE_OPENED, "first severe reading",
            ))
        elif episode.closed_at is not None:
            episode.closed_at = None
            episode.reopened_at = now
            events.append(Event(
                patient_id, now, EventKind.EPISODE_REOPENED,
                "severe again within the repeat window",
            ))

        in_window = (
            self.protocol.repeat_min <= now - episode.onset <= self.protocol.repeat_max
        )
        if episode.confirmed_at is None and in_window:
            episode.confirmed_at = now
            events.append(Event(
                patient_id, now, EventKind.CONFIRMED,
                "severe again within the repeat window",
            ))
        return events

    def _take_action(self, action: Action) -> list[Event]:
        episode = self._episodes.get(action.patient_id)
        if episode is None or not self._is_current(episode, action.time):
            # Nothing for the action to belong to, so no event. That includes a
            # dose after the episode has closed and its hour has passed: a dose
            # after the blood pressure has returned to normal shouldn't happen.
            return []
        episode.provider_responded = True
        if action.kind is ActionKind.DOSE_GIVEN:
            return [Event(action.patient_id, action.time, EventKind.DOSE_RECORDED)]
        return []

    def _fire_due(
        self, patient_id: str, episode: _Episode, now: datetime,
    ) -> list[Event]:
        """Report the deadlines this episode has reached by `now`, each once."""
        if episode.closed_at is not None:
            return []  # closing cancels whatever was pending

        events = []
        elapsed = now - episode.onset
        unconfirmed = episode.confirmed_at is None
        if unconfirmed and not episode.repeat_due_reported and elapsed >= self.protocol.repeat_min:
            episode.repeat_due_reported = True
            events.append(Event(patient_id, now, EventKind.REPEAT_DUE))
        # Strictly after: a non-severe reading at exactly repeat_min still counts
        # as in time, and has to get the chance to arrive.
        if unconfirmed and elapsed > self.protocol.repeat_min:
            episode.confirmed_at = now
            events.append(Event(
                patient_id, now, EventKind.CONFIRMED,
                "no reading below the severe range in time",
            ))
        if _should_escalate(episode, now, self.protocol):
            episode.escalated = True
            events.append(Event(
                patient_id, now, EventKind.ESCALATED,
                "provider has not responded to the notification",
            ))
        return events
