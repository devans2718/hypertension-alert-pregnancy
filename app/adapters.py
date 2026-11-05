"""Open clinical benchmark data adapter.

Loads de-identified baseline records from data/public_baseline.csv (UCI/Kaggle
Maternal Health Risk dataset) and adapts them into contract Reading instances
for replay and demonstration.
"""

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from htn_alert.contract import Reading

DEFAULT_BASELINE_PATH = Path(__file__).resolve().parents[1] / "data" / "public_baseline.csv"


@dataclass(frozen=True)
class BaselineRecord:
    """One de-identified patient row from the open benchmark dataset."""

    row_id: int
    age: int
    systolic: int
    diastolic: int
    blood_sugar: float
    body_temp: float
    heart_rate: int
    risk_level: str


def load_baseline_records(
    csv_path: Path = DEFAULT_BASELINE_PATH,
) -> list[BaselineRecord]:
    """Read the open-data baseline CSV into typed records."""
    if not csv_path.exists():
        return []

    records = []
    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            try:
                record = BaselineRecord(
                    row_id=i,
                    age=int(float(row["Age"])),
                    systolic=int(float(row["SystolicBP"])),
                    diastolic=int(float(row["DiastolicBP"])),
                    blood_sugar=float(row["BS"]),
                    body_temp=float(row["BodyTemp"]),
                    heart_rate=int(float(row["HeartRate"])),
                    risk_level=row["RiskLevel"].strip().lower(),
                )
                records.append(record)
            except (KeyError, ValueError):
                continue
    return records


def project_record_to_readings(
    record: BaselineRecord,
    patient_id: str,
    start_time: datetime,
    trajectory: str = "confirmed",
) -> list[Reading]:
    """Project a cross-sectional benchmark record into a longitudinal time-series.

    Trajectories:
      - "confirmed": Initial reading from record; repeat at +16m remains severe if initial was severe,
                     or stays in similar range.
      - "resolved": Initial reading from record (ensured severe); repeat at +16m drops below 140/90.
      - "delayed_overdue": Initial severe reading from record with no repeat within 15-60 min.
      - "single": A single point-in-time check.
    """
    first_reading = Reading(
        patient_id=patient_id,
        time=start_time,
        systolic=record.systolic,
        diastolic=record.diastolic,
    )

    if trajectory == "single":
        return [first_reading]

    if trajectory == "delayed_overdue":
        return [first_reading]

    if trajectory == "resolved":
        # Repeat drops to normotensive / mild
        repeat_reading = Reading(
            patient_id=patient_id,
            time=start_time + timedelta(minutes=16),
            systolic=min(record.systolic, 134),
            diastolic=min(record.diastolic, 84),
        )
        return [first_reading, repeat_reading]

    # Default: confirmed persistent
    # If the initial reading is severe, repeat is also severe.
    # If initial is mild, repeat remains mild.
    repeat_sys = record.systolic if record.systolic >= 160 else max(record.systolic, 162)
    repeat_dia = record.diastolic if record.diastolic >= 110 else max(record.diastolic, 108)

    repeat_reading = Reading(
        patient_id=patient_id,
        time=start_time + timedelta(minutes=17),
        systolic=repeat_sys,
        diastolic=repeat_dia,
    )
    return [first_reading, repeat_reading]

