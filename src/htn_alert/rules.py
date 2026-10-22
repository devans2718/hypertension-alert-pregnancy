"""Checks on a single reading, with no memory of earlier ones.

Anything that depends on earlier readings (persistence, timing) belongs in
episodes.py.
"""

from htn_alert.contract import Reading
from htn_alert.protocol import Protocol


def is_severe(reading: Reading, protocol: Protocol) -> bool:
    """True if either pressure is in the severe range; either one alone counts."""
    return (
        reading.systolic >= protocol.severe_systolic
        or reading.diastolic >= protocol.severe_diastolic
    )
