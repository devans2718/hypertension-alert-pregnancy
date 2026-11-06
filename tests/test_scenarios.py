"""Unit tests for app/scenarios.py test cases."""

from datetime import datetime

from app.scenarios import get_default_scenarios


def test_get_default_scenarios():
    t0 = datetime(2026, 10, 31, 10, 0)
    scenarios = get_default_scenarios(t0)

    assert len(scenarios) == 5
    ids = [s.id for s in scenarios]
    assert "scenario_confirmed" in ids
    assert "scenario_resolved" in ids
    assert "scenario_overdue" in ids
    assert "scenario_normal" in ids
    assert "scenario_benchmark" in ids

    for s in scenarios:
        assert s.name
        assert s.description
        assert s.expected_outcome
        assert len(s.readings) >= 1

