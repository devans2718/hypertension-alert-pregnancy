"""Per-patient episode logic: readings and staff actions in, events out.

This is the part that replaces memory on the unit. For each patient it tracks
an open episode from the first severe reading, through the repeat that
confirms persistence, to treatment and closing, and reports each step as an
Event.

Two kinds of input drive it:
    observe()  a Reading or an Action arrives
    tick()     time passes with nothing arriving, so deadlines can fire
               (a repeat that's overdue, a notification nobody acknowledged)

Not implemented yet: the step-by-step rules depend on protocol details the
pitch team is confirming (see config/protocol.toml).
"""

from datetime import datetime

from htn_alert.contract import Action, Event, Reading
from htn_alert.protocol import Protocol


class EpisodeTracker:
    """Tracks episodes for every patient on the unit."""

    def __init__(self, protocol: Protocol) -> None:
        self.protocol = protocol

    def observe(self, item: Reading | Action) -> list[Event]:
        """Take in one reading or action; return the events it causes."""
        raise NotImplementedError

    def tick(self, now: datetime) -> list[Event]:
        """Advance the clock to `now`; return any deadline events that fire."""
        raise NotImplementedError
