"""Load the clinical and timing values from config/protocol.toml.

The values live in a config file, not in code, because they're assumptions
until the pitch team confirms them, and the evaluation varies them.
"""

import tomllib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "protocol.toml"


@dataclass(frozen=True)
class Protocol:
    """Thresholds and timings the episode logic runs on."""

    severe_systolic: int
    severe_diastolic: int
    repeat_min: timedelta
    repeat_max: timedelta
    treatment_target: timedelta
    escalate_unacknowledged: timedelta
    close_after: timedelta


def load_protocol(path: Path = DEFAULT_PATH) -> Protocol:
    """Read a protocol file; minutes in the file become timedeltas here."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return Protocol(
        severe_systolic=raw["severe"]["systolic"],
        severe_diastolic=raw["severe"]["diastolic"],
        repeat_min=timedelta(minutes=raw["repeat"]["min_minutes"]),
        repeat_max=timedelta(minutes=raw["repeat"]["max_minutes"]),
        treatment_target=timedelta(minutes=raw["treatment"]["target_minutes"]),
        escalate_unacknowledged=timedelta(minutes=raw["escalation"]["unacknowledged_minutes"]),
        close_after=timedelta(minutes=raw["episode"]["close_after_minutes"]),
    )
