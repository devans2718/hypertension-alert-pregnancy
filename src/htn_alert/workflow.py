
"""Synthetic staff workflow simulation for OB-Response.

Designed around Mosaic's latest clinical feedback and the
revised Hack-A-Roo team plan.

Models:
- Nurse recognition delays
- Projected 15-minute reassessment timing
- Direct provider communication
- Physician collaboration
- Provider identification uncertainty
- Provider acknowledgment
- Medication administration

IMPORTANT:
Recorded synthetic BP observations and projected workflow
events are distinct.

Projected rechecks do not create BP observations and must
not be used to establish clinical confirmation.

All delays are assumptions, not measured Mosaic performance.
Clinical episode classification belongs to Daniel's rules.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from htn_alert.contract import Action, ActionKind, Reading
from htn_alert.generator import generate_bp_readings
from htn_alert.protocol import Protocol, load_protocol
from htn_alert.rules import is_severe
from htn_alert.simulation_config import WorkflowConfig, load_workflow_config


PROVIDER_PATHWAYS = (
    "direct",
    "collaboration_required",
    "provider_uncertain",
)

@dataclass(frozen=True)
class RecheckPlan:
    """Projected reassessment workflow, not a BP observation."""

    target_time: datetime
    projected_time: datetime | None
    minutes_late: float | None
    missing: bool


@dataclass(frozen=True)
class WorkflowResult:
    """Simulated staff response using recorded BP observations."""

    patient_id: str
    mode: str
    provider_pathway: str

    first_severe_time: datetime
    recognition_time: datetime

    # Compatibility name: an existing severe repeat in the configured window,
    # NOT a complete clinical confirmation/persistence determination (issue #9).
    confirming_reading_time: datetime

    provider_identified_time: datetime
    provider_notified_time: datetime
    provider_acknowledged_time: datetime
    medication_time: datetime

    recognition_delay_minutes: int
    provider_identification_delay_minutes: int
    collaboration_delay_minutes: int

    # Separate hypothetical reassessment projection.
    recheck_plan: RecheckPlan

    actions: tuple[Action, ...]

    # Capture the run's target, so later config changes cannot rewrite a result.
    treatment_target: timedelta = field(
        default_factory=lambda: load_protocol().treatment_target
    )

    @property
    def severe_repeat_in_window_time(self) -> datetime:
        """Recorded repeat used by this limited demo, not episode confirmation."""
        return self.confirming_reading_time

    @property
    def within_treatment_target(self) -> bool:
        """Timing indicator using the protocol duration, from first severe BP."""
        return self.medication_time - self.first_severe_time <= self.treatment_target

    @property
    def treatment_minutes(self) -> float:
        """Medication timing relative to first severe BP."""
        return (
            self.medication_time - self.first_severe_time
        ).total_seconds() / 60

    @property
    def within_60_minutes(self) -> bool:
        """Compatibility alias for the configured target (currently 60 minutes)."""
        return self.within_treatment_target

    @property
    def projected_recheck_matches_recorded(self) -> bool:
        """Whether projection equals the recorded severe repeat time."""
        return (
            self.recheck_plan.projected_time
            == self.confirming_reading_time
        )

    @property
    def recheck_timeline_status(self) -> str:
        """Explain the relationship between the two timelines."""
        if self.recheck_plan.missing:
            return (
                "Projected reassessment is missing; an existing "
                "recorded severe repeat remains in the input data."
            )

        if self.projected_recheck_matches_recorded:
            return (
                "Projected reassessment time equals the recorded "
                "severe repeat time. This does not establish that "
                "the projection generated the observation."
            )

        return (
            "Projected reassessment differs from the recorded "
            "severe repeat. Treatment timing uses the recorded "
            "reading, NOT the projected reassessment."
        )


def find_severe_repeat_in_window(
    readings: list[Reading], protocol: Protocol | None = None,
) -> Reading | None:
    """Find an existing severe repeat 15–60 min after the first severe BP.

    Bounds come from protocol.toml. This is only simulator input eligibility:
    it does not handle the absence of a below-severe reading within 15 minutes.
    Full persistence and SMFM examples belong to episodes.py in issue #9:
    https://github.com/devans2718/hypertension-alert-pregnancy/issues/9
    """
    protocol = protocol if protocol is not None else load_protocol()
    ordered = sorted(readings, key=lambda r: r.time)
    first = next((r for r in ordered if is_severe(r, protocol)), None)
    if first is None:
        return None
    return next((
        r for r in ordered
        if protocol.repeat_min <= r.time - first.time <= protocol.repeat_max
        and is_severe(r, protocol)
    ), None)


def simulate_recheck_plan(
    first_severe_time: datetime,
    recognition_time: datetime,
    mode: str = "baseline",
    seed: int = 42,
    prompt_effect: float = 0.5,
    missing: bool = False,
    *,
    protocol: Protocol | None = None,
    config: WorkflowConfig | None = None,
) -> RecheckPlan:
    """Project a nurse's reassessment timing.

    The target comes from protocol.repeat_min (currently 15 minutes after
    first severe BP); it is not a new observation or persistence decision.

    The projection models:
    - Recognition time
    - An assumed workload/readiness delay
    - An assumed improvement from reminders

    It does not create a Reading or claim a recheck occurred.
    """

    if mode not in ("baseline", "tool"):
        raise ValueError("Mode must be 'baseline' or 'tool'.")

    if not 0.0 <= prompt_effect <= 1.0:
        raise ValueError(
            "prompt_effect must be between 0.0 and 1.0."
        )

    if recognition_time < first_severe_time:
        raise ValueError(
            "Recognition cannot precede the first severe BP."
        )

    protocol = protocol if protocol is not None else load_protocol()
    config = config if config is not None else load_workflow_config()
    target_time = first_severe_time + protocol.repeat_min

    if missing:
        return RecheckPlan(
            target_time=target_time,
            projected_time=None,
            minutes_late=None,
            missing=True,
        )

    # Independent RNG preserves earlier workflow random draws.
    rng = random.Random(seed + config.recheck_seed_offset)
    readiness_delay = rng.randint(*config.readiness_minutes)

    if mode == "tool":
        readiness_delay = round(
            readiness_delay * (1.0 - prompt_effect)
        )

    projected_time = max(
        target_time,
        recognition_time,
    ) + timedelta(minutes=readiness_delay)

    minutes_late = max(
        0.0,
        (projected_time - target_time).total_seconds() / 60,
    )

    return RecheckPlan(
        target_time=target_time,
        projected_time=projected_time,
        minutes_late=minutes_late,
        missing=False,
    )


def simulate_workflow(
    readings: list[Reading],
    mode: str = "baseline",
    provider_pathway: str = "direct",
    seed: int = 42,
    prompt_effect: float = 0.5,
    missing_recheck: bool = False,
    *,
    protocol: Protocol | None = None,
    config: WorkflowConfig | None = None,
) -> WorkflowResult:
    """Simulate response to an existing synthetic severe-BP case.

    This initial demonstration requires an already-recorded
    severe repeat 15-60 minutes after first severe BP (configured window).

    It is not the complete clinical persistence algorithm.

    Provider and medication timelines use that recorded reading.
    Projected recheck delays are reported separately.
    """

    if not readings:
        raise ValueError("Readings cannot be empty.")

    if mode not in ("baseline", "tool"):
        raise ValueError("Mode must be 'baseline' or 'tool'.")

    if provider_pathway not in PROVIDER_PATHWAYS:
        raise ValueError(
            f"provider_pathway must be one of {PROVIDER_PATHWAYS}"
        )

    if not 0.0 <= prompt_effect <= 1.0:
        raise ValueError(
            "prompt_effect must be between 0.0 and 1.0."
        )

    protocol = protocol if protocol is not None else load_protocol()
    config = config if config is not None else load_workflow_config()
    patient_id = readings[0].patient_id

    if any(r.patient_id != patient_id for r in readings):
        raise ValueError(
            "All readings must belong to the same patient."
        )

    readings = sorted(readings, key=lambda r: r.time)

    first = next(
        (
            reading
            for reading in readings
            if is_severe(reading, protocol)
        ),
        None,
    )

    if first is None:
        raise ValueError(
            "No severe BP reading found in the patient stream."
        )

    # Share only this limited observation lookup; episode persistence is issue #9.
    severe_repeat = find_severe_repeat_in_window(readings, protocol)

    if severe_repeat is None:
        raise ValueError(
            "No existing severe repeat in the configured "
            "window for this demonstration; full persistence is issue #9."
        )

    rng = random.Random(seed)

    recognition_delay = rng.randint(*config.recognition_minutes)
    identification_delay = rng.randint(*config.identification_minutes)
    acknowledgment_delay = rng.randint(*config.acknowledgment_minutes)
    medication_delay = rng.randint(*config.medication_minutes)

    collaboration_delay = 0

    if provider_pathway == "collaboration_required":
        collaboration_delay = rng.randint(*config.collaboration_minutes)

    elif provider_pathway == "provider_uncertain":
        identification_delay += rng.randint(*config.uncertainty_minutes)

    if mode == "tool":
        recognition_delay = round(
            recognition_delay * (1.0 - prompt_effect)
        )

        identification_delay = round(
            identification_delay * (1.0 - prompt_effect)
        )

    recognition_time = first.time + timedelta(
        minutes=recognition_delay
    )

    # Projection belongs to the hypothetical workflow timeline.
    recheck_plan = simulate_recheck_plan(
        first_severe_time=first.time,
        recognition_time=recognition_time,
        mode=mode,
        seed=seed,
        prompt_effect=prompt_effect,
        missing=missing_recheck,
        protocol=protocol,
        config=config,
    )

    # Provider/treatment actions belong to the recorded-input
    # demonstration timeline. Do not use recheck_plan.projected_time
    # as a substitute for an actual measurement.
    provider_identified_time = max(
        recognition_time,
        severe_repeat.time,
    ) + timedelta(minutes=identification_delay)

    provider_notified_time = (
        provider_identified_time
        + timedelta(minutes=collaboration_delay)
    )

    provider_acknowledged_time = (
        provider_notified_time
        + timedelta(minutes=acknowledgment_delay)
    )

    medication_time = (
        provider_acknowledged_time
        + timedelta(minutes=medication_delay)
    )

    actions = (
        Action(
            patient_id=patient_id,
            time=provider_acknowledged_time,
            kind=ActionKind.PROVIDER_ACKNOWLEDGED,
        ),
        Action(
            patient_id=patient_id,
            time=medication_time,
            kind=ActionKind.DOSE_GIVEN,
        ),
    )

    return WorkflowResult(
        patient_id=patient_id,
        mode=mode,
        provider_pathway=provider_pathway,
        first_severe_time=first.time,
        recognition_time=recognition_time,
        confirming_reading_time=severe_repeat.time,
        provider_identified_time=provider_identified_time,
        provider_notified_time=provider_notified_time,
        provider_acknowledged_time=provider_acknowledged_time,
        medication_time=medication_time,
        recognition_delay_minutes=recognition_delay,
        provider_identification_delay_minutes=identification_delay,
        collaboration_delay_minutes=collaboration_delay,
        recheck_plan=recheck_plan,
        actions=actions,
        treatment_target=protocol.treatment_target,
    )


if __name__ == "__main__":
    protocol = load_protocol()
    start = datetime(2026, 10, 26, 8, 0)

    patient_readings = generate_bp_readings(
        patient_id="SIM-001",
        start_time=start,
        scenario="persistent_severe",
        seed=44,
        protocol=protocol,
    )

    for pathway in PROVIDER_PATHWAYS:
        print("\n" + "=" * 60)
        print("PROVIDER PATHWAY:", pathway.upper())
        print("=" * 60)

        for mode in ("baseline", "tool"):
            result = simulate_workflow(
                patient_readings,
                mode=mode,
                provider_pathway=pathway,
                seed=42,
                prompt_effect=0.5,
                protocol=protocol,
            )
            recheck_minutes = (
                result.recheck_plan.target_time - result.first_severe_time
            ).total_seconds() / 60
            treatment_minutes = result.treatment_target.total_seconds() / 60

            print(f"\n{mode.upper()}")

            print("\nA. RECORDED SYNTHETIC BP OBSERVATIONS")
            print("First severe BP:", result.first_severe_time)
            print(
                "Recorded severe repeat:",
                result.confirming_reading_time,
            )

            print("\nB. PROJECTED REASSESSMENT WORKFLOW")
            print(
                "Nurse recognition:",
                result.recognition_time,
            )
            print(
                f"{recheck_minutes:g}-minute target:",
                result.recheck_plan.target_time,
            )
            print(
                "Projected recheck:",
                result.recheck_plan.projected_time,
            )
            print(
                "Projected minutes late:",
                result.recheck_plan.minutes_late,
            )
            print(
                "Projected recheck missing:",
                result.recheck_plan.missing,
            )
            print(
                "Projection matches recorded repeat:",
                result.projected_recheck_matches_recorded,
            )

            print("\nC. STAFF ACTIONS")
            print(
                "Provider identified:",
                result.provider_identified_time,
            )
            print(
                "Provider notified:",
                result.provider_notified_time,
            )
            print(
                "Provider acknowledged:",
                result.provider_acknowledged_time,
            )
            print(
                "Medication administered:",
                result.medication_time,
            )
            print(
                "Minutes from first severe BP to medication:",
                result.treatment_minutes,
            )
            print(
                f"Medication within {treatment_minutes:g} minutes:",
                result.within_60_minutes,
            )

            print("\nD. TIMELINE VALIDATION")
            print(result.recheck_timeline_status)
            print(
                "NOTE: Medication timing is simulated from the "
                "recorded repeat, not the projected recheck."
            )
