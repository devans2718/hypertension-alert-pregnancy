"""The severe-range check, including the exact thresholds."""

from datetime import datetime

import pytest

from htn_alert.contract import Reading
from htn_alert.protocol import load_protocol
from htn_alert.rules import is_severe

PROTOCOL = load_protocol()
T0 = datetime(2026, 11, 1, 8, 0)


def reading(systolic: int, diastolic: int) -> Reading:
    return Reading(patient_id="p1", time=T0, systolic=systolic, diastolic=diastolic)


@pytest.mark.parametrize(
    ("systolic", "diastolic", "expected"),
    [
        (120, 80, False),  # normal
        (159, 109, False),  # just under both thresholds
        (160, 90, True),  # systolic at threshold
        (140, 110, True),  # diastolic at threshold, systolic not severe
        (175, 115, True),  # both severe
    ],
)
def test_is_severe(systolic, diastolic, expected):
    assert is_severe(reading(systolic, diastolic), PROTOCOL) is expected
