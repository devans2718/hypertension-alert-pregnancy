"""Console demonstrations of the coupled path; no exports or hospital claims."""

from statistics import mean

from htn_alert.cohort_evaluation import evaluate_coupled_cohort
from htn_alert.generator import generate_course_cohort
from htn_alert.protocol import load_protocol
from htn_alert.sensitivity_analysis import run_coupled_sensitivity_analysis


def show_result(result):
    print(result.mode, "first severe:", result.first_severe_time,
          "completed medication:", result.medication_time, "no-dose reason:", result.no_dose_reason)
    for task in result.reassessments:
        print(" Actual reassessment:", task.actual_time, "target:", task.target_time,
              "minutes late:", task.minutes_late, "missing:", task.missing, "source:", task.source)
    for row in result.trace:
        if row.kind in ("nurse_recognized", "provider_notified", "provider_acknowledged",
                        "medication_ordered", "medication_administered", "dose_cancelled",
                        "prototype_deadline_escalation"):
            print(" ", row.time, row.kind, row.detail)


def demo(view):
    protocol = load_protocol()
    cohort = generate_course_cohort(protocol=protocol)
    print("COUPLED SYNTHETIC SIMULATION — assumptions, not hospital outcomes")
    print(f"Reassessment target: {protocol.repeat_min.total_seconds() / 60:g} minutes; "
          f"treatment target: {protocol.treatment_target.total_seconds() / 60:g} minutes from first recorded severe BP")
    if view == "generator":
        for course in cohort.values():
            print(course.patient_id, course.scenario, "routine cycle:", course.routine_interval_minutes,
                  "UNOBSERVED change points:", course.points)
        return
    if view == "sensitivity_analysis":
        for row in run_coupled_sensitivity_analysis(cohort, protocol=protocol):
            print(row)
        print("Dose differences use comparable pairs only; denominators and no-dose counts remain visible.")
        return
    result = evaluate_coupled_cohort(cohort, protocol=protocol)
    if view in ("workflow", "paired_simulation"):
        pair = next(p for p in result.patients if p.baseline.first_severe_time is not None)
        print("Patient:", pair.patient_id, "pathway:", pair.provider_pathway)
        show_result(pair.baseline)
        show_result(pair.tool)
        print("Reassessment minutes saved:", pair.reassessment_minutes_saved,
              "comparable medication minutes saved:", pair.medication_minutes_saved)
    else:
        print("Preselected patients:", result.total_patients,
              "comparable dose pairs:", result.comparable_dose_pairs,
              "classification differences:", result.discordant_classifications)
        for mode, evaluation in (("baseline", result.baseline_events), ("tool", result.tool_events)):
            print(mode, "operations:", getattr(result, f"{mode}_operations"))
            arms = [getattr(p, mode) for p in result.patients]
            lateness = [r.minutes_late for arm in arms for r in arm.reassessments if r.minutes_late is not None]
            print(mode, "actual readings:", sum(len(a.readings) for a in arms),
                  "missed reassessments:", sum(a.missed_reassessments for a in arms),
                  "mean minutes late:", mean(lateness) if lateness else None)
            print(mode, "completed doses:", sum(len([a for a in arm.actions if a.kind.value == "dose_given"]) for arm in arms),
                  "no-dose patients:", sum(a.medication_time is None for a in arms),
                  "patient statuses:", {status: sum(p.status == status for p in evaluation.patients)
                                        for status in sorted({p.status for p in evaluation.patients})})
            print(mode, "persistent episodes:", evaluation.persistent_episodes,
                  "timely:", evaluation.timely_episodes, "censored:", evaluation.censored_episodes,
                  "synthetic patient rate:", evaluation.patient_rate)
        print("Every patient is retained; task traces include actual notification times and no-dose reasons.")
    print("No drug-response model. Resolution gate is idealized; no effectiveness or Mosaic comparison.")
