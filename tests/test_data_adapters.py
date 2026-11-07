"""Unit tests for app/adapters.py open data adapter."""

from datetime import datetime, timedelta
from pathlib import Path

from app.adapters import (
    BaselineRecord,
    load_baseline_records,
    project_record_to_readings,
)


def test_load_baseline_records_real_file():
    records = load_baseline_records()
    assert len(records) > 0
    # Spot-check the first record
    first = records[0]
    assert first.age > 0
    assert first.systolic > 0
    assert first.diastolic > 0
    assert first.risk_level in ("high risk", "mid risk", "low risk")


def test_load_baseline_records_missing_file(tmp_path):
    missing = tmp_path / "non_existent.csv"
    assert load_baseline_records(missing) == []


def test_project_record_to_readings_trajectories():
    t0 = datetime(2026, 10, 31, 10, 0)
    record = BaselineRecord(
        row_id=1,
        age=30,
        systolic=165,
        diastolic=112,
        blood_sugar=7.5,
        body_temp=98.0,
        heart_rate=78,
        risk_level="high risk",
    )

    # Confirmed trajectory
    confirmed_readings = project_record_to_readings(record, "P_TEST", t0, trajectory="confirmed")
    assert len(confirmed_readings) == 2
    assert confirmed_readings[0].systolic == 165
    assert confirmed_readings[1].time == t0 + timedelta(minutes=17)
    assert confirmed_readings[1].systolic >= 160 or confirmed_readings[1].diastolic >= 110

    # Resolved trajectory
    resolved_readings = project_record_to_readings(record, "P_TEST", t0, trajectory="resolved")
    assert len(resolved_readings) == 2
    assert resolved_readings[0].systolic == 165
    assert resolved_readings[1].systolic <= 134
    assert resolved_readings[1].diastolic <= 84

    # Delayed overdue trajectory
    overdue_readings = project_record_to_readings(record, "P_TEST", t0, trajectory="delayed_overdue")
    assert len(overdue_readings) == 1

    # Single check trajectory
    single_readings = project_record_to_readings(record, "P_TEST", t0, trajectory="single")
    assert len(single_readings) == 1

