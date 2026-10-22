"""The protocol file loads, and its values convert to the expected types."""

from datetime import timedelta

from htn_alert.protocol import load_protocol


def test_default_protocol_loads():
    protocol = load_protocol()
    assert protocol.severe_systolic == 160
    assert protocol.severe_diastolic == 110
    assert protocol.repeat_min == timedelta(minutes=15)


def test_repeat_window_is_ordered():
    protocol = load_protocol()
    assert protocol.repeat_min < protocol.repeat_max
