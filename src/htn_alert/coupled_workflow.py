"""Actual synthetic measurement tasks coupled to Daniel's EpisodeTracker.

This scheduler owns operational assumptions, not persistence or medication
guidance. Truth is sampled only at current acquisition/admin times. No drug
response is inferred. Prototype deadline reminders stay outside engine Events.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from htn_alert.contract import Action, ActionKind, Event, EventKind, Reading
from htn_alert.episodes import EpisodeTracker, treatment_deadline
from htn_alert.evaluate import EventEvaluation, evaluate_events
from htn_alert.generator import PatientCourse
from htn_alert.protocol import Protocol, load_protocol
from htn_alert.rules import is_severe
from htn_alert.simulation_config import (
    CoupledConfig, WorkflowConfig, load_coupled_config, load_workflow_config,
)


@dataclass(frozen=True)
class WorkflowTrace:
    time: datetime
    kind: str
    episode_onset: datetime | None
    detail: str = ""


@dataclass(frozen=True)
class Reassessment:
    episode_onset: datetime
    trigger_time: datetime
    target_time: datetime
    actual_time: datetime | None
    source: str | None

    @property
    def minutes_late(self) -> float | None:
        if self.actual_time is None:
            return None
        return max(0.0, (self.actual_time - self.target_time).total_seconds() / 60)

    @property
    def missing(self) -> bool:
        return self.actual_time is None


@dataclass(frozen=True)
class CoupledResult:
    patient_id: str
    mode: str
    provider_pathway: str
    readings: tuple[Reading, ...]
    actions: tuple[Action, ...]
    events: tuple[Event, ...]
    trace: tuple[WorkflowTrace, ...]
    reassessments: tuple[Reassessment, ...]
    evaluation: EventEvaluation
    observed_until: datetime
    treatment_target: timedelta
    no_dose_reason: str | None

    @property
    def first_severe_time(self) -> datetime | None:
        return next((e.time for e in self.events if e.kind is EventKind.EPISODE_OPENED), None)

    @property
    def medication_time(self) -> datetime | None:
        return next((e.time for e in self.events if e.kind is EventKind.DOSE_RECORDED), None)

    @property
    def treatment_minutes(self) -> float | None:
        """First completed dose, relative to its own engine episode's onset."""
        dose = self.medication_time
        episode = next((ep for ep in self.evaluation.episodes if dose is not None and ep.dose_time == dose), None)
        return (dose - episode.onset).total_seconds() / 60 if episode is not None else None

    @property
    def missed_reassessments(self) -> int:
        return sum(r.missing for r in self.reassessments)


@dataclass
class _Task:
    """Workflow state for an engine opening/reopening, not clinical state."""

    onset: datetime
    trigger: datetime
    target: datetime
    recognized_due: datetime
    readiness: int
    identification: int
    collaboration: int
    acknowledgment: int
    decision: int
    medication: int
    active: bool = True
    confirmed: datetime | None = None
    recognized: datetime | None = None
    actual: datetime | None = None
    source: str | None = None
    urgent_due: datetime | None = None
    identified: datetime | None = None
    notified: datetime | None = None
    acknowledged: datetime | None = None
    ordered: datetime | None = None
    attempted: bool = False
    deadline_reminded: bool = False
    requires_reassessment: bool = True


def simulate_coupled_workflow(
    course: PatientCourse, mode: str = "baseline", provider_pathway: str = "direct",
    seed: int = 42, prompt_effect: float = 0.5, missing_recheck: bool = False, *,
    protocol: Protocol | None = None, config: WorkflowConfig | None = None,
    coupled_config: CoupledConfig | None = None,
    recorded_readings: tuple[Reading, ...] | None = None,
) -> CoupledResult:
    """Run current-time acquisitions and completed actions through the tracker.

    A scripted decision requires engine confirmation, actual reassessment,
    current recorded severe BP and provider acknowledgment. It is an Assume
    policy, not a clinical rule. The idealized truth gate separately cancels
    administration after unobserved resolution; it supplies no Reading and
    changes no engine classification. Missing urgent tasks may be rescued by
    routine monitoring. No planned action is sent to observe().

    recorded_readings is only for archival observation replay: acquire at
    supplied times, filtering too-close observations, with no invented routine
    or urgent measurements. New experiments should leave it unset and build
    independent course truth instead.
    """
    if mode not in ("baseline", "tool") or not 0 <= prompt_effect <= 1:
        raise ValueError("Mode and prompt_effect must be valid.")
    if provider_pathway not in ("direct", "collaboration_required", "provider_uncertain"):
        raise ValueError("Unknown provider_pathway.")
    protocol = protocol if protocol is not None else load_protocol()
    config = config if config is not None else load_workflow_config()
    cc = coupled_config if coupled_config is not None else load_coupled_config()
    if cc.clock_step_minutes != 1 or not cc.resolution_blocks_dose:
        raise ValueError("Use a one-minute clock and the resolution safety gate.")
    tracker = EpisodeTracker(protocol)
    readings, actions, events, trace, tasks = [], [], [], [], []
    current: _Task | None = None
    current_onset = None
    confirmed_at = None
    treated_onsets = set()
    responded_onsets = set()
    min_gap = timedelta(minutes=course.minimum_measurement_minutes)
    factor = 1 - prompt_effect if mode == "tool" else 1
    replay = None
    if recorded_readings is not None:
        times = [r.time for r in recorded_readings]
        if (times != sorted(set(times)) or not times or times[0] != course.start
                or any(r.patient_id != course.patient_id or not course.start <= r.time <= course.end
                       or (r.time - course.start).total_seconds() % 60 for r in recorded_readings)):
            raise ValueError("Replay readings must be ordered, unique, whole-minute and match the course.")
        replay = {r.time: r for r in recorded_readings}

    def log(now, kind, detail=""):
        trace.append(WorkflowTrace(now, kind, current.onset if current else None, detail))

    def draw(name, bounds, epoch):
        # Named streams prevent a new task/measurement shifting unrelated draws.
        return random.Random(f"{seed}:{epoch}:{name}").randint(*bounds)

    def consume(new_events):
        nonlocal current, current_onset, confirmed_at
        events.extend(new_events)
        for event in new_events:
            if event.kind in (EventKind.EPISODE_OPENED, EventKind.EPISODE_REOPENED):
                if event.kind is EventKind.EPISODE_OPENED:
                    current_onset, confirmed_at = event.time, None
                epoch = len(tasks)
                recognition = round(draw("recognition", config.recognition_minutes, epoch) * factor)
                identification = draw("identification", config.identification_minutes, epoch)
                if provider_pathway == "provider_uncertain":
                    identification += draw("uncertainty", config.uncertainty_minutes, epoch)
                current = _Task(
                    current_onset, event.time, event.time + protocol.repeat_min,
                    event.time + timedelta(minutes=recognition),
                    round(draw("readiness", config.readiness_minutes, epoch) * factor),
                    round(identification * factor),
                    draw("collaboration", config.collaboration_minutes, epoch) if provider_pathway == "collaboration_required" else 0,
                    draw("acknowledgment", config.acknowledgment_minutes, epoch),
                    draw("decision", cc.decision_minutes, epoch),
                    draw("medication", config.medication_minutes, epoch),
                    confirmed=confirmed_at,
                    requires_reassessment=event.kind is EventKind.EPISODE_OPENED,
                )
                if not current.requires_reassessment:
                    # REOPENED came from an actual severe measurement after the
                    # original onset. It already supplies the assessment; do not
                    # impose a second confirmation window beyond Daniel's rule.
                    current.actual = event.time
                    current.source = "reopening_measurement"
                tasks.append(current)
            elif event.kind is EventKind.CONFIRMED:
                confirmed_at = event.time
                if current:
                    current.confirmed = event.time
            elif event.kind is EventKind.EPISODE_CLOSED and current:
                current.active = False
                if current.ordered is not None and not current.attempted:
                    log(event.time, "dose_cancelled", "recorded BP resolved before administration")
            elif event.kind is EventKind.DOSE_RECORDED and current:
                treated_onsets.add(current.onset)

    def acquire(now, source):
        if readings and now - readings[-1].time < min_gap:
            log(now, "measurement_deferred", "minimum spacing")
            return
        reading = course.sample(now) if replay is None else replay[now]
        # A scheduled post-trigger reading is the real reassessment even if N.
        if current and current.active and current.actual is None and now > current.trigger:
            current.actual, current.source = now, source
            log(now, "reassessment_performed", source)
        readings.append(reading)
        log(now, "measurement_performed", source)
        consume(tracker.observe(reading))

    now = course.start
    while now <= course.end:
        # Measurements precede scheduler tick/actions at a tie, preserving N at 15.
        if replay is not None:
            if now in replay:
                acquire(now, "archival_recorded")
        elif (now - course.start) % timedelta(minutes=course.routine_interval_minutes) == timedelta(0):
            acquire(now, "routine")
        if current and current.active:
            if current.recognized is None and now >= current.recognized_due:
                current.recognized = now
                log(now, "nurse_recognized")
                available = course.start + timedelta(minutes=cc.nurse_available_after_minutes)
                current.urgent_due = max(current.target, now, available) + timedelta(minutes=current.readiness)
                if missing_recheck:
                    log(now, "urgent_reassessment_missed", "routine measurements remain scheduled")
            if (replay is None and current.urgent_due is not None and current.actual is None and not missing_recheck
                    and now >= current.urgent_due):
                if not readings or now - readings[-1].time >= min_gap:
                    acquire(now, "urgent")
        consume(tracker.tick(now))
        task = current
        if task and task.active:
            # Explicit opt-in reminder; never an ESCALATED event/order/dose.
            if (cc.deadline_escalation_enabled and task.confirmed is not None
                    and task.acknowledged is None and task.onset not in responded_onsets
                    and task.onset not in treated_onsets
                    and not task.deadline_reminded
                    and now >= treatment_deadline(task.onset, protocol) - timedelta(minutes=cc.deadline_escalation_lead_minutes)):
                task.deadline_reminded = True
                log(now, "prototype_deadline_escalation", "assumed reminder only; no action implied")
            search_start = task.recognized
            if not cc.provider_search_overlaps_reassessment:
                search_start = max(task.recognized, task.actual) if task.recognized and task.actual else None
            if search_start is not None and task.identified is None and now >= search_start + timedelta(minutes=task.identification):
                task.identified = now
                log(now, "provider_identified")
            if (cc.contact_succeeds and task.identified is not None and task.confirmed is not None
                    and task.notified is None
                    and now >= max(task.identified, task.confirmed) + timedelta(minutes=task.collaboration)):
                task.notified = now
                log(now, "provider_notified", "completed staff contact; distinct from engine CONFIRMED")
            clinician_available = course.start + timedelta(minutes=cc.clinician_available_after_minutes)
            if (task.notified is not None and task.acknowledged is None
                    and now >= max(task.notified + timedelta(minutes=task.acknowledgment), clinician_available)):
                task.acknowledged = now
                responded_onsets.add(task.onset)
                action = Action(course.patient_id, now, ActionKind.PROVIDER_ACKNOWLEDGED)
                actions.append(action)
                log(now, "provider_acknowledged")
                consume(tracker.observe(action))
            if (cc.treatment_authorized and task.actual is not None and task.confirmed is not None
                    and task.acknowledged is not None and task.ordered is None
                    and task.onset not in treated_onsets and is_severe(readings[-1], protocol)
                    and now >= max(task.actual, task.acknowledged) + timedelta(minutes=task.decision)):
                task.ordered = now
                log(now, "medication_ordered", "scripted simulation decision, not inferred from an escalation")
            if task.ordered is not None and not task.attempted and now >= task.ordered + timedelta(minutes=task.medication):
                task.attempted = True
                if not is_severe(course.sample(now), protocol):
                    log(now, "dose_cancelled", "idealized current-truth gate: spontaneous resolution")
                else:
                    action = Action(course.patient_id, now, ActionKind.DOSE_GIVEN)
                    actions.append(action)
                    log(now, "medication_administered")
                    consume(tracker.observe(action))
        now += timedelta(minutes=cc.clock_step_minutes)

    evaluation = evaluate_events(events, observed_until=course.end,
                                 patient_ids=(course.patient_id,), protocol=protocol)
    no_dose = None
    if not any(e.kind is EventKind.DOSE_RECORDED for e in events):
        if not tasks:
            no_dose = "no_observed_episode"
        elif any(t.kind == "dose_cancelled" for t in trace):
            no_dose = "resolved_before_administration"
        elif any(t.active for t in tasks):
            no_dose = ("contact_failed" if not cc.contact_succeeds else
                       "decision_withheld" if not cc.treatment_authorized else
                       "missing_actual_reassessment" if any(t.actual is None for t in tasks) else
                       "unresolved_at_horizon")
        else:
            no_dose = "recorded_resolution_without_dose"
    return CoupledResult(course.patient_id, mode, provider_pathway, tuple(readings),
        tuple(actions), tuple(events), tuple(trace),
        tuple(Reassessment(t.onset, t.trigger, t.target, t.actual, t.source)
              for t in tasks if t.requires_reassessment),
        evaluation, course.end, protocol.treatment_target, no_dose)
