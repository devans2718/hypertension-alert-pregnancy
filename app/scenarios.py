"""Pre-configured nurse input test scenarios for demonstration and testing.

Each scenario represents a real-world labor and delivery clinical pattern,
allowing the app to replay readings over time and verify system alerting.
"""

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.adapters import load_baseline_records, project_record_to_readings
from htn_alert.contract import Reading


@dataclass(frozen=True)
class NurseScenario:
    """A named test case representing a bedside sequence of readings."""

    id: str
    name: str
    description: str
    expected_outcome: str
    readings: list[Reading]


def get_default_scenarios(base_time: datetime | None = None) -> list[NurseScenario]:
    """Generate default test scenarios rooted at `base_time`."""
    if base_time is None:
        base_time = datetime(2026, 10, 31, 10, 0)

    # 1. Confirmed Persistent Severe HTN
    s1 = NurseScenario(
        id="scenario_confirmed",
        name="1. Confirmed Severe Hypertension",
        description="Initial reading 168/112 mmHg; repeat reading at 16 min is 164/108 mmHg.",
        expected_outcome="Starts 15-min countdown, confirms persistent severe HTN at 16 min, starts 60-min medication target.",
        readings=[
            Reading(patient_id="P-101", time=base_time, systolic=168, diastolic=112),
            Reading(patient_id="P-101", time=base_time + timedelta(minutes=16), systolic=164, diastolic=108),
        ],
    )

    # 2. Transient Severe (Resolved)
    s2 = NurseScenario(
        id="scenario_resolved",
        name="2. Transient Severe (Resolved)",
        description="Initial severe reading 162/98 mmHg; repeat reading at 18 min drops to 134/86 mmHg.",
        expected_outcome="Episode resolves and closes as unconfirmed transient elevation.",
        readings=[
            Reading(patient_id="P-102", time=base_time, systolic=162, diastolic=98),
            Reading(patient_id="P-102", time=base_time + timedelta(minutes=18), systolic=134, diastolic=86),
        ],
    )

    # 3. Repeat Overdue
    s3 = NurseScenario(
        id="scenario_overdue",
        name="3. Delayed Recheck (Repeat Overdue)",
        description="Initial severe reading 174/116 mmHg; >15 minutes elapse with no repeat reading.",
        expected_outcome="Repeat due alarm fires at 15 min prompting bedside nurse to recheck.",
        readings=[
            Reading(patient_id="P-103", time=base_time, systolic=174, diastolic=116),
        ],
    )

    # 4. Normal Routine Check (15-Minute Notice)
    s4 = NurseScenario(
        id="scenario_normal",
        name="4. Routine Normal Monitoring",
        description="Normal baseline 120/78 mmHg. Demonstrates scheduled 15-minute notice to nurse.",
        expected_outcome="Normotensive at T=0. At T=15 min, issues a scheduled routine vital re-assessment notice to nurse.",
        readings=[
            Reading(patient_id="P-NORM", time=base_time, systolic=120, diastolic=78),
        ],
    )

    # 5. Open Benchmark High-Risk Case
    baseline_records = load_baseline_records()
    high_risk_record = next((r for r in baseline_records if r.risk_level == "high risk" and r.systolic >= 140), None)
    if high_risk_record:
        s5_readings = project_record_to_readings(
            high_risk_record,
            patient_id=f"P-BENCH-{high_risk_record.row_id}",
            start_time=base_time,
            trajectory="confirmed",
        )
        desc = (
            f"From public benchmark dataset (Row #{high_risk_record.row_id}): "
            f"Age {high_risk_record.age}, HR {high_risk_record.heart_rate} bpm, "
            f"BP {high_risk_record.systolic}/{high_risk_record.diastolic} mmHg."
        )
    else:
        s5_readings = [
            Reading(patient_id="P-BENCH", time=base_time, systolic=160, diastolic=100),
            Reading(patient_id="P-BENCH", time=base_time + timedelta(minutes=15), systolic=162, diastolic=102),
        ]
        desc = "High-risk benchmark profile from open-source repository."

    s5 = NurseScenario(
        id="scenario_benchmark",
        name="5. Open Benchmark Patient Profile",
        description=desc,
        expected_outcome="Derived from open dataset distribution; simulates bedside repeat confirmation workflow.",
        readings=s5_readings,
    )

    return [s1, s2, s3, s4, s5]

