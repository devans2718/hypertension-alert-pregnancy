
"""Paired baseline-versus-OB-Response workflow simulation.

PatientCourse inputs/default demos share hidden BP truth and exogenous factors,
while allowing actual measurements to differ. List inputs below preserve the
archival projected comparison; use course inputs for new event-based results.

Uses identical synthetic patient readings and random seeds
to compare hypothetical staff workflow outcomes.

Based on Mosaic's clinical feedback:
- Recognition of initial severe BP
- Reassessment timing
- Identification and communication with the appropriate provider

IMPORTANT:
Projected reassessments are not recorded BP measurements.
Treatment timing uses existing synthetic BP observations.
These comparisons do not establish clinical effectiveness.
"""

from dataclasses import dataclass
from datetime import datetime

from htn_alert.contract import Reading
from htn_alert.generator import PatientCourse, generate_bp_readings
from htn_alert.protocol import Protocol, load_protocol
from htn_alert.simulation_config import WorkflowConfig, load_workflow_config
from htn_alert.workflow import WorkflowResult, simulate_workflow
from htn_alert.coupled_workflow import CoupledResult
from htn_alert.simulation_config import CoupledConfig


def _first_trace(result: CoupledResult, kind: str) -> datetime | None:
    return next((row.time for row in result.trace if row.kind == kind), None)


def _optional_difference(baseline: datetime | None, tool: datetime | None) -> float | None:
    if baseline is None or tool is None:
        return None
    return (baseline - tool).total_seconds() / 60


@dataclass(frozen=True)
class CoupledPairedResult:
    """Shared truth and exogenous factors; actual observations may differ."""

    patient_id: str
    provider_pathway: str
    prompt_effect: float
    baseline: CoupledResult
    tool: CoupledResult

    @property
    def recognition_minutes_saved(self) -> float | None:
        return _optional_difference(_first_trace(self.baseline, "nurse_recognized"),
                                    _first_trace(self.tool, "nurse_recognized"))

    @property
    def reassessment_minutes_saved(self) -> float | None:
        if not self.baseline.reassessments or not self.tool.reassessments:
            return None
        return _optional_difference(self.baseline.reassessments[0].actual_time,
                                    self.tool.reassessments[0].actual_time)

    @property
    def provider_notification_minutes_saved(self) -> float | None:
        return _optional_difference(_first_trace(self.baseline, "provider_notified"),
                                    _first_trace(self.tool, "provider_notified"))

    @property
    def medication_minutes_saved(self) -> float | None:
        # Match engine episode identities, not merely each arm's first dose.
        baseline = self.baseline.evaluation.episodes
        tool = self.tool.evaluation.episodes
        if (not baseline or not tool or baseline[0].onset != tool[0].onset
                or baseline[0].persistent != tool[0].persistent):
            return None
        return _optional_difference(baseline[0].dose_time, tool[0].dose_time)


def compare_patient_course(
    course: PatientCourse, provider_pathway: str = "direct", seed: int = 42,
    prompt_effect: float = 0.5, missing_recheck: bool = False, *,
    protocol: Protocol | None = None, workflow_config: WorkflowConfig | None = None,
    coupled_config: CoupledConfig | None = None,
) -> CoupledPairedResult:
    """Couple measurement decisions without changing truth or unrelated draws."""
    protocol = protocol if protocol is not None else load_protocol()
    workflow_config = workflow_config if workflow_config is not None else load_workflow_config()
    from htn_alert.simulation_config import load_coupled_config
    cc = coupled_config if coupled_config is not None else load_coupled_config()
    baseline = simulate_workflow(course, "baseline", provider_pathway, seed,
        prompt_effect, missing_recheck, protocol=protocol, config=workflow_config, coupled_config=cc)
    tool = simulate_workflow(course, "tool", provider_pathway, seed,
        prompt_effect, missing_recheck, protocol=protocol, config=workflow_config, coupled_config=cc)
    return CoupledPairedResult(course.patient_id, provider_pathway, prompt_effect, baseline, tool)


@dataclass(frozen=True)
class PairedResult:
    """Baseline and tool results for the same synthetic patient."""

    patient_id: str
    provider_pathway: str
    prompt_effect: float

    baseline: WorkflowResult
    tool: WorkflowResult

    recognition_minutes_saved: float
    projected_recheck_minutes_saved: float | None
    provider_notification_minutes_saved: float
    medication_minutes_saved: float

    @property
    def baseline_within_60(self) -> bool:
        """Medication-timing indicator, not full SMFM compliance."""
        return self.baseline.within_60_minutes

    @property
    def tool_within_60(self) -> bool:
        """Medication-timing indicator, not full SMFM compliance."""
        return self.tool.within_60_minutes


def _minutes_between(later: datetime, earlier: datetime) -> float:
    """Return the elapsed time in minutes."""
    return (later - earlier).total_seconds() / 60


def compare_workflows(
    readings: list[Reading] | PatientCourse,
    provider_pathway: str = "direct",
    seed: int = 42,
    prompt_effect: float = 0.5,
    missing_recheck: bool = False,
    *,
    protocol: Protocol | None = None,
    workflow_config: WorkflowConfig | None = None,
    coupled_config: CoupledConfig | None = None,
) -> PairedResult | CoupledPairedResult:
    """Compare baseline and tool workflows using the same readings.

    Random seed and provider pathway are held constant.

    Recheck benefits represent projected workflow improvements.
    Medication differences reflect assumed recognition and
    communication changes using the same recorded severe repeat.
    They must not be attributed to the projected recheck.
    """

    if isinstance(readings, PatientCourse):
        return compare_patient_course(readings, provider_pathway, seed, prompt_effect,
            missing_recheck, protocol=protocol, workflow_config=workflow_config,
            coupled_config=coupled_config)

    # Preserve caller-owned data, even if readings are not sorted.
    patient_readings = list(readings)
    protocol = protocol if protocol is not None else load_protocol()
    workflow_config = workflow_config if workflow_config is not None else load_workflow_config()

    baseline = simulate_workflow(
        patient_readings,
        mode="baseline",
        provider_pathway=provider_pathway,
        seed=seed,
        prompt_effect=prompt_effect,
        missing_recheck=missing_recheck,
        protocol=protocol,
        config=workflow_config,
    )

    assisted = simulate_workflow(
        patient_readings,
        mode="tool",
        provider_pathway=provider_pathway,
        seed=seed,
        prompt_effect=prompt_effect,
        missing_recheck=missing_recheck,
        protocol=protocol,
        config=workflow_config,
    )

    if isinstance(baseline, CoupledResult) and isinstance(assisted, CoupledResult):
        return CoupledPairedResult(baseline.patient_id, provider_pathway, prompt_effect, baseline, assisted)

    # Confirm that the two models use identical BP anchors.
    if (
        baseline.patient_id != assisted.patient_id
        or baseline.first_severe_time != assisted.first_severe_time
        or baseline.confirming_reading_time
        != assisted.confirming_reading_time
    ):
        raise ValueError(
            "Baseline and tool must use the same recorded BP timeline."
        )

    recognition_saved = _minutes_between(
        baseline.recognition_time,
        assisted.recognition_time,
    )

    notification_saved = _minutes_between(
        baseline.provider_notified_time,
        assisted.provider_notified_time,
    )

    medication_saved = _minutes_between(
        baseline.medication_time,
        assisted.medication_time,
    )

    baseline_late = baseline.recheck_plan.minutes_late
    assisted_late = assisted.recheck_plan.minutes_late

    if baseline_late is None or assisted_late is None:
        recheck_saved = None
    else:
        recheck_saved = baseline_late - assisted_late

    return PairedResult(
        patient_id=baseline.patient_id,
        provider_pathway=provider_pathway,
        prompt_effect=prompt_effect,
        baseline=baseline,
        tool=assisted,
        recognition_minutes_saved=recognition_saved,
        projected_recheck_minutes_saved=recheck_saved,
        provider_notification_minutes_saved=notification_saved,
        medication_minutes_saved=medication_saved,
    )


if __name__ == "__main__":
    import sys
    if "--legacy" not in sys.argv:
        from htn_alert.simulation_demo import demo
        demo("paired_simulation")
        raise SystemExit
    protocol = load_protocol()
    start = datetime(2026, 10, 26, 8, 0)

    readings = generate_bp_readings(
        patient_id="PAIR-001",
        start_time=start,
        scenario="persistent_severe",
        seed=44,
        protocol=protocol,
    )

    print("\nPAIRED WORKFLOW SIMULATION")
    print("Patient:", readings[0].patient_id)
    print("Same synthetic BP readings in both modes")
    print("Reminder effectiveness assumption: 50%\n")

    for pathway in (
        "direct",
        "collaboration_required",
        "provider_uncertain",
    ):
        result = compare_workflows(
            readings,
            provider_pathway=pathway,
            seed=42,
            prompt_effect=0.5,
            protocol=protocol,
        )

        print("=" * 58)
        print("Provider pathway:", pathway)
        print("=" * 58)

        print(
            "Recognition minutes saved:",
            result.recognition_minutes_saved,
        )
        print(
            "Projected recheck minutes saved:",
            result.projected_recheck_minutes_saved,
        )
        print(
            "Provider notification minutes saved:",
            result.provider_notification_minutes_saved,
        )
        print(
            "Medication minutes saved:",
            result.medication_minutes_saved,
        )

        print(
            "Baseline medication time (minutes):",
            result.baseline.treatment_minutes,
        )
        print(
            "Tool medication time (minutes):",
            result.tool.treatment_minutes,
        )
        print(
            f"Baseline within {result.baseline.treatment_target.total_seconds() / 60:g} minutes:",
            result.baseline_within_60,
        )
        print(
            f"Tool within {result.tool.treatment_target.total_seconds() / 60:g} minutes:",
            result.tool_within_60,
        )

        print(
            "NOTE: Medication changes are NOT caused by "
            "the projected reassessment."
        )
        print()
