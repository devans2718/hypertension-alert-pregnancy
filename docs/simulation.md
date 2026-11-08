# Synthetic BP and workflow simulation

This research prototype uses synthetic data only and is not for clinical use.
The balanced cohort, staff delays, decisions and tool effects are engineering
assumptions. They are not measured Mosaic outcomes or estimates of clinical
effectiveness; they must not be compared directly with Mosaic's 69% baseline.

The coupled model addresses [issue #20](https://github.com/devans2718/hypertension-alert-pregnancy/issues/20)
and consumes Daniel's tracker from [PR #19](https://github.com/devans2718/hypertension-alert-pregnancy/pull/19).

## Running the coupled model

```bash
uv run pytest -v
uv run python -m htn_alert.generator
uv run python -m htn_alert.workflow
uv run python -m htn_alert.paired_simulation
uv run python -m htn_alert.cohort_evaluation
uv run python -m htn_alert.sensitivity_analysis
uv run python -m htn_alert.evaluate
```

These demonstrations use the coupled path by default, print to the terminal,
and do not export files to `data/`. The first five commands also accept
`--legacy` to reproduce the earlier fixture/projection demonstration. CSV
export remains a separate, archival fixture API.

```python
from datetime import datetime
from htn_alert.generator import generate_patient_course, generate_course_cohort
from htn_alert.paired_simulation import compare_patient_course
from htn_alert.cohort_evaluation import evaluate_coupled_cohort

course = generate_patient_course(
    "SIM-EXAMPLE", datetime(2026, 11, 5, 8), "persistent_severe",
    routine_interval_minutes=60, seed=42,
)
pair = compare_patient_course(course, prompt_effect=0.5)
print(pair.baseline.reassessments, pair.tool.reassessments)
print(pair.baseline.actions, pair.tool.actions)
print(pair.medication_minutes_saved)  # None when doses are not comparable
summary = evaluate_coupled_cohort(generate_course_cohort())
print(summary.baseline_events, summary.tool_events)
```

`simulate_workflow(course)`, `compare_workflows(course)`, `evaluate_cohort(course_dict)`
and `run_sensitivity_analysis(course_dict)` also dispatch to the coupled model.
Use the explicit coupled functions for empty cohorts to avoid ambiguity with
archival list-based APIs. A `PatientCourse` and its change points are synthetic
truth; only actual acquisitions become shared `Reading` objects.

## What is modeled

The generator creates a deterministic piecewise-constant, unobserved BP course.
The scheduler independently takes routine measurements on assumed 15-, 30- or
60-minute schedules. A severe observation opens an engine episode, starts the
first-recorded-severe treatment clock and schedules nurse recognition. Recognition
and nurse availability determine an urgent task. The task samples BP when
performed, rather than projecting a measurement that never happened.

All actual acquisitions, routine or urgent, respect the configured minimum
15-minute spacing. A routine measurement can satisfy an outstanding reassessment;
a too-close routine measurement is skipped, not shifted into an extra observation.
An opening starts an operational reassessment task at the shared repeat target.
A reopening comes from an actual severe measurement, which already supplies an
assessment; the scheduler does not demand another confirmation reading. It starts
a new nurse/provider response, preserving the original treatment deadline. Targets and thresholds are loaded from the shared
protocol, never copied into a second clinical classifier.

At a time tie, acquisitions precede scheduler ticks and staff actions. The clock
advances in whole minutes, so a non-severe observation at +15 is processed before
the missing-repeat confirmation at +16. Missing urgent tasks remain visible;
routine monitoring may rescue them later. `minutes_late` compares the actual
measurement with the original due time; a task without a measurement by the
horizon has `None` lateness and a separate missing count, never zero lateness.

Three provider pathways remain: direct, collaboration required and provider
uncertainty. Lookup starts after recognition and reassessment by default. A
configuration flag explicitly allows lookup to overlap reassessment. Physical
nurse/clinician availability is anchored to simulation start and shared by both
arms. Notification, acknowledgment, scripted medication decision and completed
administration are separate stages. Failed contact or a withheld decision can
prevent a dose. An escalation alone never authorizes medication.

The prototype decision requires an actual reassessment, engine confirmation,
a latest recorded severe reading and provider acknowledgment. This is an
**Assume** simulation policy, not an approved clinical indication rule. A
confirmation caused by missing documentation is not itself a dose order.

**Resolution gate:** an idealized, current-truth check cancels administration
when the underlying BP has spontaneously resolved, including between recorded
measurements. It creates no extra `Reading`, does not alter the tracker, and
is not information a real alert system can assume it has. This deliberately
optimistic cancellation assumption prevents implausible synthetic doses and
needs team agreement before drawing conclusions about decision performance.
An observed normal reading also cancels pending work. There is at most one
completed first dose per engine episode and one administration attempt per
opening/reopening task; retries and dosing regimens are not modeled.

Doses do not manufacture lower BP. Persistent fixtures remain severe unless an
explicit exogenous spontaneous-resolution point occurs. The same exogenous
course is retained after a dose for bookkeeping, without claiming a drug response
or interpreting subsequent readings as treatment effectiveness. There is no
pharmacodynamic model, shared staffing queue or validated provider-routing model.

## One episode engine and two escalation meanings

Only `EpisodeTracker.observe()` and `tick()` classify persistence, recurrence,
opening and closing. Actual readings and completed acknowledgment/dose actions
are passed to it. Its `DOSE_RECORDED` events establish recorded doses, and
`treatment_deadline(EPISODE_OPENED.time, protocol)` supplies the original deadline.
Human-readable event details are never parsed to infer clinical state.

The shared contract makes `CONFIRMED` the engine's logical notification. The
scheduler's `provider_notified` trace means completed simulated staff contact;
it may occur later. Both are retained, with different names. No contract meaning
is changed to conceal the difference.

The engine's existing `ESCALATED` rule remains untouched, including its
late-confirmation placeholder. An optional, **disabled by default**, prototype
reminder appears as `prototype_deadline_escalation` in the workflow trace when
an open, confirmed, unanswered episode approaches its treatment deadline. A
late confirmation may therefore trigger it immediately. Its configurable lead
is an assumption. It creates neither an engine `ESCALATED` event nor an
acknowledgment, medication order or administered dose. It currently reports
urgency; it does not assume escalation improves response time.

## Configuration and reproducibility

| File | Contents and sources |
| --- | --- |
| `config/protocol.toml` | Shared clinical thresholds, repeat bounds, treatment deadline and engine escalation; existing Pitch/Lit/Assume sources. Change only with team approval. |
| `config/generator.toml` | Archival observations plus `[course]` change points and routine-cycle experiment. All new physiology/cadence settings are Assume; minimum measurement spacing is Pitch, from Daniel's issue and the shared Reading contract. |
| `config/workflow.toml` | Assumed staff delay ranges plus `[coupled]` decision, availability, overlap and prototype-reminder controls. Every value is labeled Assume. |

Loaders accept alternate paths, validate inputs and resolve default paths
independently of the working directory. No dependency was added. Custom clinical
targets, such as 35 minutes, are engineering stress tests, not alternate approved
SMFM definitions. Both labels and results use the same supplied protocol.

Paired arms share the course, horizon, routine schedule, pathway, seed and external
availability assumptions. Named random streams by seed/task/mechanism keep an
extra measurement from shifting unrelated draws. Tool effect scales assumed
recognition, readiness and lookup delays; other stages remain unchanged. Zero
effect produces identical observations, traces, actions and events. Subsequent
measurement times can differ between arms, so recorded classifications and
eligibility can also differ. The analysis exposes those differences.

## Evaluation and denominators

`evaluate.py` consumes events, not scenario labels or a severe-repeat lookup.
Persistent episodes are those with `CONFIRMED`. A dose qualifies only through
`DOSE_RECORDED`, timed from the episode's first severe BP. The documented shared
metric also permits a below-severe closing within the treatment window without
a later reopening in that window. Reopenings undo provisional resolution; all
persistent episodes must be timely for a patient to be counted timely.

Report dose-based success and resolution-based success separately. Do not call
all timely outcomes medication treatment. Observation must extend through both
the repeat window and treatment deadline to finalize an episode. Before then,
its outcome is censored; rates are `None` when incomplete/unsupported patients
prevent a complete point estimate. Confirmed episodes without a timely dose or
qualifying resolution are failures after the full window, not excluded patients.

The preselected cohort is retained regardless of observed persistence or dose.
Results expose per-arm episode/patient denominators, no-episode/nonpersistent,
no-dose, unresolved/censored outcomes and classification differences. Task traces
provide actual reassessment lateness/missingness and provider contact times.
Paired medication savings are computed only for the same first engine episode,
with matching onset/persistence and doses in both arms. No-dose and noncomparable
pairs remain counted separately; their savings are `None`, not zero. Averages
are conditional on available comparable observations and do not establish an
overall causal effect. Episode rates and all-episodes-timely patient rates are
different measures.

This implements the documented timing/resolution portion of an SMFM-shaped
synthetic measure. `Action` does not identify a drug, and the model does not
encode real eligibility exclusions, clinical indication or hospital completeness.
Do not describe these numbers as validated SMFM compliance, false-alert accuracy,
clinical effectiveness or an improvement over Mosaic's measured baseline.

## Scenario table used for engine regression tests

The following expectations use the **new coupled courses**, an onset at 0,
15-minute routine monitoring, no administered doses and a full horizon. S/N
mean readings classified by the shared single-reading severity check. These
are tested against the engine; scenario names do not determine classification.

| Intended label | Actual canonical observations | Engine classification / synthetic outcome |
| --- | --- | --- |
| non_hypertensive | N throughout | No episode; outside persistent-patient denominator |
| mild_hypertension | N throughout | No episode; outside denominator |
| persistent_severe | S0, S15, S30, ... | Persistent; no-dose failure after deadline |
| nonpersistent_severe | S0, N15 and thereafter | Nonpersistent; outside denominator |
| recurrent_severe | S0, N15, N30, S45, S60, N75 | One persistent episode after fold-back; no-dose failure, resolution after deadline |
| borderline_severe | N throughout, capped below configured thresholds | No episode; outside denominator |
| delayed_or_missing_repeat | S0 through S75, N90 | Persistent; no-dose failure in this canonical course |
| spurious_severe | S0, N15 and thereafter | Same observed classification as nonpersistent; no validated artifact distinction |

Longer cycles, delayed tasks and tool effects may change these recorded patterns
and thus the engine's classification. For example, a course resolving at +15
but first remeasured at +30 is persistent under the tracker's missing-documentation
rule and can qualify through timely resolution. That is an observation effect,
not evidence of changed physiology. The delayed family supplies a prolonged
course on which staff can miss or delay reassessment; the workflow supplies the
actual delay, rather than the label forcing a clinical outcome.

## Archived fixture/projection compatibility

`generate_bp_readings()` / `generate_cohort()` still supply the original recorded
fixtures, including their short timestamp gaps and explicit seed-independent
`delayed` (+16) / `missing_early` (+30) examples. They are not the revised workflow
measurement scheduler. SMFM reference tests and their original timestamps remain
unchanged. The new coupled measurements never inherit those short gaps.

For list-based calls, earlier severe-repeat selectors remain only as deprecated
archival projection helpers, not persistence classifiers or new evaluation gates.
The archived cohort's 20-of-80 coverage is a property of that projection, not the
new engine denominator. Delayed list streams now fall back to a clearly limited
piecewise-constant observation replay instead of raising an eligibility error;
new experiments should construct independent course truth instead.
Replay acquires only at supplied observation times: it does not invent an earlier
+15 reassessment or replace either explicit +16/+30 subtype. Supplied observations
closer than the minimum spacing are skipped with a trace entry, so subsequent
archival short gaps do not become new workflow measurements. Both subtypes are
replay fixtures; the default coupled cohort uses the separate prolonged course
in the table above and does not assign subtype labels.

In the archival result, `medication_time` remains a projected timestamp for
compatibility. It is not evidence of completion: a projected dose is withheld
from `actions` after a recorded resolution or beyond the observation horizon.
The legacy demonstration labels it as a projection. Use the coupled result and
its emitted events for actual simulated administration and evaluation.

## Decisions still requiring team review

- Whether actual reassessment and the scripted clinician decision represent the
  intended workflow, especially for confirmations due to missing documentation.
- The idealized resolution gate and the absence of drug-response/retry models.
- Whether provider search overlaps reassessment, realistic contact failures,
  staffing/availability distributions, and plausible reminder adoption/effects.
- Whether and how a deadline-aware reminder should affect response; Daniel's
  clinical late-confirmation rule remains a separate team decision.
- Observed-classification differences and eligibility assumptions before using
  patient rates in a presentation. The first-dose simulation cannot validate
  a complete clinical quality measure or prove benefit.
