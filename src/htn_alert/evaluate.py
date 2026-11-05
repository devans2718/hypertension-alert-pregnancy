"""Metrics over EpisodeTracker events, timed from onset, never confirmation.

Persistence comes ONLY from CONFIRMED, doses from DOSE_RECORDED, and deadlines
from treatment_deadline(). The configured metric also accepts documented
resolution within the target without severe recurrence in that window. This is
an SMFM-shaped synthetic measure, not hospital compliance: the contract cannot
establish drug identity, exclusions or clinical indication. Unknowns stay visible.
"""

from dataclasses import dataclass, field
from datetime import datetime

from htn_alert.contract import Event, EventKind
from htn_alert.episodes import treatment_deadline
from htn_alert.protocol import Protocol, load_protocol


@dataclass(frozen=True)
class EpisodeEvaluation:
    patient_id: str
    onset: datetime
    deadline: datetime
    persistent: bool
    dose_time: datetime | None
    final_closing: datetime | None
    status: str
    timely: bool | None


@dataclass(frozen=True)
class PatientEvaluation:
    patient_id: str
    persistent_episodes: int
    timely: bool | None
    status: str


@dataclass(frozen=True)
class EventEvaluation:
    episodes: tuple[EpisodeEvaluation, ...]
    patients: tuple[PatientEvaluation, ...]

    @property
    def persistent_episodes(self) -> int:
        return sum(e.persistent for e in self.episodes)

    @property
    def timely_episodes(self) -> int:
        return sum(e.persistent and e.timely is True for e in self.episodes)

    @property
    def censored_episodes(self) -> int:
        return sum(e.status == "censored" for e in self.episodes)

    @property
    def persistent_patients(self) -> int:
        return sum(p.persistent_episodes > 0 for p in self.patients)

    @property
    def timely_patients(self) -> int:
        return sum(p.timely is True for p in self.patients)

    @property
    def patient_rate(self) -> float | None:
        """All persistent episodes must be timely; unknowns prevent a point rate."""
        if not self.persistent_patients or any(p.status in ("censored", "unsupported") for p in self.patients):
            return None
        return self.timely_patients / self.persistent_patients

    @property
    def episode_rate(self) -> float | None:
        if (not self.persistent_episodes or self.censored_episodes
                or any(p.status == "unsupported" for p in self.patients)):
            return None
        return self.timely_episodes / self.persistent_episodes


@dataclass
class _EventEpisode:
    onset: datetime
    confirmed: bool = False
    doses: list[datetime] = field(default_factory=list)
    closings: list[datetime] = field(default_factory=list)
    reopenings: list[datetime] = field(default_factory=list)


def evaluate_events(
    events: list[Event] | tuple[Event, ...], *, observed_until: datetime,
    patient_ids: tuple[str, ...] = (), protocol: Protocol | None = None,
) -> EventEvaluation:
    """Read emitted episode identities, including fold-backs and no-dose cases.

    Drive tick() through observed_until first. Observe through both the repeat
    window and treatment deadline before finalizing provisional closings. Every
    supplied patient stays visible. No persistence is inferred from readings
    or human-readable event detail strings.
    """
    protocol = protocol if protocol is not None else load_protocol()
    grouped: dict[str, list[_EventEpisode]] = {pid: [] for pid in patient_ids}
    unsupported = set()
    for event in sorted(events, key=lambda e: e.time):
        if event.time > observed_until:
            raise ValueError("Event lies after the observation horizon.")
        episodes = grouped.setdefault(event.patient_id, [])
        if event.kind is EventKind.EPISODE_OPENED:
            episodes.append(_EventEpisode(event.time))
            continue
        if not episodes:
            unsupported.add(event.patient_id)
            continue
        ep = episodes[-1]
        if event.kind is EventKind.CONFIRMED:
            ep.confirmed = True
        elif event.kind is EventKind.DOSE_RECORDED:
            ep.doses.append(event.time)
        elif event.kind is EventKind.EPISODE_CLOSED:
            ep.closings.append(event.time)
        elif event.kind is EventKind.EPISODE_REOPENED:
            ep.reopenings.append(event.time)

    evaluations = []
    patients = []
    for pid, episodes in sorted(grouped.items()):
        own = []
        for ep in episodes:
            deadline = treatment_deadline(ep.onset, protocol)
            mature_at = max(deadline, ep.onset + protocol.repeat_max)
            dose = min(ep.doses, default=None)
            closing = max(ep.closings, default=None)
            last_close = max((t for t in ep.closings if t <= deadline), default=None)
            last_reopen = max((t for t in ep.reopenings if t <= deadline), default=None)
            resolved = last_close is not None and (last_reopen is None or last_close >= last_reopen)
            if observed_until < mature_at:
                status, timely = "censored", None
            elif not ep.confirmed:
                status, timely = "nonpersistent", None
            elif dose is not None and dose <= deadline:
                status, timely = "timely_dose", True
            elif resolved:
                status, timely = "timely_resolution", True
            elif dose is not None:
                status, timely = "late_dose", False
            else:
                status, timely = "no_dose", False
            own.append(EpisodeEvaluation(pid, ep.onset, deadline, ep.confirmed,
                                        dose, closing, status, timely))
        evaluations.extend(own)
        persistent = [ep for ep in own if ep.persistent]
        if pid in unsupported:
            state, timely = "unsupported", None
        elif any(ep.status == "censored" for ep in own):
            state, timely = "censored", None
        elif not persistent:
            state, timely = ("nonpersistent" if own else "no_episode"), None
        else:
            timely = all(ep.timely for ep in persistent)
            state = "timely" if timely else "not_timely"
        patients.append(PatientEvaluation(pid, len(persistent), timely, state))
    return EventEvaluation(tuple(evaluations), tuple(patients))


def demo() -> None:
    from htn_alert.generator import generate_course_cohort
    from htn_alert.cohort_evaluation import evaluate_coupled_cohort
    result = evaluate_coupled_cohort(generate_course_cohort())
    print("SYNTHETIC EVENT EVALUATION — all workflow effects are assumptions")
    for mode, evaluation in (("Baseline", result.baseline_events), ("Tool", result.tool_events)):
        print(mode, "persistent episodes:", evaluation.persistent_episodes,
              "timely:", evaluation.timely_episodes, "censored:", evaluation.censored_episodes)
        print(mode, "persistent patients:", evaluation.persistent_patients,
              "timely:", evaluation.timely_patients, "synthetic patient rate:", evaluation.patient_rate)
    print("Includes timely resolution; not measured Mosaic performance or validated SMFM compliance.")


if __name__ == "__main__":
    demo()
