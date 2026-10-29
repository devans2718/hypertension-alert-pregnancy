# Issue #11 / PR #7 local implementation and validation

Completed locally on `akwasianing/synthetic-bp-generator`, based on commit
`fa7d804a86e25f67b0b31eff87ca6bd8c6efa6f6`. PR #7 remains open and draft.
No commits, pushes, merges, issue updates or PR edits were performed.

## Requested changes

1. Removed the generator's duplicate severity implementation. Generator,
   workflow, cohort evaluation and CSV export now use `rules.is_severe` with
   a loaded `Protocol`. Reassessment target, repeat-window bounds and treatment
   duration come from `config/protocol.toml`; that file's values are unchanged.
2. Extracted generator defaults, variation, onset and scenario fixtures into
   `config/generator.toml`, and staff delays into `config/workflow.toml`.
   Every parameter has an `Assume` source comment; none claims a clinical source.
3. Named the shared lookup `find_severe_repeat_in_window` and the cohort gate
   `_has_severe_repeat_in_window`. Both document their limited scope and issue
   #9. They inspect existing severe repeats in the configured +15–60-minute
   window, rather than defining full clinical persistence. Both delayed-repeat
   subtypes remain unsupported; the evaluation denominator has not expanded.
4. Added explicit `delayed_repeat_subtype=` selection (`delayed` at +16 minutes,
   `missing_early` at +30). The default and cohort subtype cycle do not depend
   on seed parity. Seed changes still vary BP samples and onset.

## P2 demonstration label correction

All four timing demonstrations now load one protocol and pass it to fixture
generation and calculations. Workflow labels use the actual result's captured
treatment duration and projected target offset. Paired labels use each result's
captured duration; cohort and sensitivity labels use the same protocol supplied
to their evaluations. Sensitivity analysis now accepts an optional `protocol=`
and shares it across every effect level. Existing calls and calculations remain
compatible.

The table header, timing indicators, reassessment target label and explanatory
limitation text all use the configured durations. Fractional minutes are displayed
without truncation to whole minutes. All five default stdout outputs are exactly
unchanged, including spacing and numerical results.

The 14 cases in `tests/test_demo_output.py` cover:

- All four timing demos with a 20-minute repeat target and 35-minute treatment
  target, checking labels against calculated booleans/counts and loading once.
- All four with fractional 20.5-minute repeat and 35.5-minute treatment targets.
- The reported P2 example: medication at 44 minutes with a 35-minute target now
  prints `Medication within 35 minutes: False`; it does not claim a 60-minute check.
- Exact pre-fix default stdout fingerprints for all five demonstration programs.

Existing positional call patterns and result fields remain available.
Generator numeric defaults now resolve from TOML when omitted. Workflow results
capture the treatment target used for that run. Clearer accessors coexist with
legacy `confirming_reading_time`, `severe_without_qualifying_repeat` and
`within_60_minutes` names. See [simulation.md](simulation.md) for examples and
compatibility details.

## Files changed

The complete issue #11 change set contains **17 files**. This display follow-up
changes the four timing-demo modules, adds `tests/test_demo_output.py`, and updates
this report; the other listed files are from the initial issue #11 implementation.

| File | Change |
| --- | --- |
| `AGENTS.md` | Updated the required layout listing for the new configuration files and loader. |
| `config/generator.toml` (new) | Original synthetic defaults, BP variation, onset choices, scenario points and explicit subtype defaults/cycle, each sourced as Assume. |
| `config/workflow.toml` (new) | Original staff-delay ranges and independent recheck RNG offset, each sourced as Assume. |
| `src/htn_alert/simulation_config.py` (new) | Typed TOML loaders and validation for ranges, point offsets and subtype choices; accepts alternate files. |
| `src/htn_alert/generator.py` | Shared severity rule and protocol-based caps/validation; configured fixtures; explicit subtypes and seed-independent cohort cycling. |
| `src/htn_alert/workflow.py` | Shared severity, protocol targets, configured delays, narrowly named existing-repeat lookup, target captured in each result, compatibility accessors and labels based on actual result targets. |
| `src/htn_alert/cohort_evaluation.py` | Reuses the narrow lookup and shared severity; passes one loaded protocol/delay configuration through a cohort; clearer unsupported reasons and accessor; demonstration labels use its calculation protocol. |
| `src/htn_alert/paired_simulation.py` | Passes the same protocol and delay settings to both baseline and tool runs; demonstration labels use their captured targets. |
| `src/htn_alert/sensitivity_analysis.py` | Accepts a shared optional protocol across effect levels; demonstration headers and limitation text display that configured treatment target. |
| `src/htn_alert/export_data.py` | CSV severity labels use the shared protocol/rule; optional protocol override. |
| `tests/test_demo_output.py` (new) | 14 regressions for nondefault labels/results, one loaded protocol, fractional targets, the 35-minute P2 example and exact default outputs. |
| `tests/test_generator.py` | Migrated to shared severity; tests both explicit subtypes across four seeds, default/cycle independence, invalid choices and exact cohort regression. |
| `tests/test_shared_simulation_rules.py` (new) | Tests alternate thresholds/windows/targets across generation, workflow, pairing, cohort summary/evaluation and CSV; repeat boundaries and deliberate unsupported scope. |
| `tests/test_simulation_config.py` (new) | Tests default/alternate TOML inputs, actual use of parameters, invalid ranges/choices, working-directory independence and source comments. |
| `tests/test_sensitivity_analysis.py` | Adds a regression check for all five original sensitivity rows. |
| `docs/simulation.md` (new) | Configuration usage, explicit subtype examples, compatibility and scope limits. |
| `docs/issue-11-validation.md` (new) | This local implementation report, full passing-test inventory and proposed PR note. |

## Test results

Baseline before editing: `uv run pytest -v` — **95 passed**.
After the initial refactor: **154 passed**.
After the P2 label correction, the final verbose run was:
`uv run pytest -v --junitxml=.pytest_cache/issue-11-results.xml` —
**168 passed in 12.05s**, zero failed, zero errors, zero skipped.
The XML is inside the existing ignored pytest cache, not a proposed PR file.
`git diff --check` also passed, including a separate whitespace check of new files.

| Test file | Passed cases |
| --- | ---: |
| `tests/test_cohort_evaluation.py` | 14 |
| `tests/test_demo_output.py` | 14 |
| `tests/test_generator.py` | 41 |
| `tests/test_paired_simulation.py` | 13 |
| `tests/test_protocol.py` | 2 |
| `tests/test_rules.py` | 5 |
| `tests/test_sensitivity_analysis.py` | 12 |
| `tests/test_shared_simulation_rules.py` | 25 |
| `tests/test_simulation_config.py` | 20 |
| `tests/test_workflow.py` | 22 |

## Demonstration checks

All five commands completed with exit code 0 through `uv run`, using the existing environment:

```bash
uv run python -m htn_alert.generator
uv run python -m htn_alert.workflow
uv run python -m htn_alert.paired_simulation
uv run python -m htn_alert.cohort_evaluation
uv run python -m htn_alert.sensitivity_analysis
```

- Generator: all eight scenario families printed; default summary remained
  80 patients, 1,085 readings, 100 severe readings and 50 patients with severe BP.
- Exact default cohort observation fingerprint remained
  `b7506e069fe2d084ebdfe9fa6743ccf744110c643128d23bb6f593ee4283efd3`,
  captured before editing and asserted by a regression test.
- Workflow: all three provider pathways ran in both modes. Existing recorded
  BP anchors and the separation from reassessment projections were preserved.
- Paired simulation: the same observations and seeds were used in both modes.
- Cohort evaluation: still 20 supported and 60 unsupported patients; the latter
  include 30 without severe BP and 30 without an existing severe repeat in the
  configured window. Every unsupported patient remains visible.
- Sensitivity analysis: all five effect levels retained the same supported
  patients and pre-refactor timing summaries. The regression test checks the
  original projected-recheck and medication timing differences at every level.

These checks establish software behavior preservation, not clinical effectiveness.
Projected reassessments still do not create actual BP observations or determine
medication timing. No full patient-level SMFM rate is computed. No comparison
with Mosaic's measured treatment percentage was introduced.

All five default outputs match the stdout fingerprints captured before the
P2 fix, byte for byte. The nondefault demonstrations are also exercised directly
through their real `__main__` blocks by the regression tests.

## Preserved boundaries

`episodes.py`, `contract.py`, `config/protocol.toml`, the app, dependencies and
`uv.lock` were not changed. Existing untracked `data/` and
`src/htn_alert/smfm_cases.py` were not edited, staged or included. No export
command wrote into `data/`; the export integration test used a temporary test
file. No redesign connecting projected reassessments to observations was added.

## Remaining shared-protocol follow-up — comment intentionally unchanged

`config/protocol.toml:27–29` incorrectly describes the treatment clock as starting
from confirmation, whereas Daniel's PR #7 guidance and the existing simulator
start it at the **first severe BP**. Flag this wording for Daniel/the team to
correct in the shared clinical protocol separately. It was not changed in this
label task. The configured target duration is still read consistently; no clock
logic, protocol values or episode rules were changed. No other remaining issue
was found for this P2 display fix.

## Proposed PR description addition — not published

```text
Closes #11

Codex replaced the duplicate severity rule with the shared protocol-based check,
extracted synthetic generator and workflow assumptions into sourced TOML files,
shared and clarified the limited existing-severe-repeat lookup with references
to #9, and made delayed-repeat subtype selection independent of seed. Demonstration
labels now display the same configured targets used in calculations.

Validation: 168 tests passed; generator, workflow, paired comparison, cohort
and sensitivity demonstrations completed. Default observations and supported
cohort coverage were preserved. All results remain synthetic engineering checks.
```

This note can be added to the existing draft PR after approval. The contributor
adds their own account of any agent changes they modified or rejected.

## Exact passing test inventory

Every parameterized case below passed in the final recorded run.

```text
tests/test_cohort_evaluation.py::test_total_patients_accounted_for PASSED
tests/test_cohort_evaluation.py::test_patients_with_severe_bp_counted PASSED
tests/test_cohort_evaluation.py::test_supported_and_unsupported_counts PASSED
tests/test_cohort_evaluation.py::test_unsupported_patients_have_reasons PASSED
tests/test_cohort_evaluation.py::test_supported_patients_have_timing_results PASSED
tests/test_cohort_evaluation.py::test_reproducible_evaluation PASSED
tests/test_cohort_evaluation.py::test_zero_prompt_effect_produces_no_improvement PASSED
tests/test_cohort_evaluation.py::test_assumed_prompt_effect_cannot_increase_recheck_lateness PASSED
tests/test_cohort_evaluation.py::test_average_uses_supported_patients_only PASSED
tests/test_cohort_evaluation.py::test_medication_counts_do_not_exceed_supported_patients PASSED
tests/test_cohort_evaluation.py::test_empty_cohort_handled PASSED
tests/test_cohort_evaluation.py::test_invalid_prompt_effect_rejected[-0.1] PASSED
tests/test_cohort_evaluation.py::test_invalid_prompt_effect_rejected[1.1] PASSED
tests/test_cohort_evaluation.py::test_patient_ids_must_match_readings PASSED
tests/test_demo_output.py::test_demo_labels_match_nondefault_protocol[20-35-workflow] PASSED
tests/test_demo_output.py::test_demo_labels_match_nondefault_protocol[20-35-paired_simulation] PASSED
tests/test_demo_output.py::test_demo_labels_match_nondefault_protocol[20-35-cohort_evaluation] PASSED
tests/test_demo_output.py::test_demo_labels_match_nondefault_protocol[20-35-sensitivity_analysis] PASSED
tests/test_demo_output.py::test_demo_labels_match_nondefault_protocol[20.5-35.5-workflow] PASSED
tests/test_demo_output.py::test_demo_labels_match_nondefault_protocol[20.5-35.5-paired_simulation] PASSED
tests/test_demo_output.py::test_demo_labels_match_nondefault_protocol[20.5-35.5-cohort_evaluation] PASSED
tests/test_demo_output.py::test_demo_labels_match_nondefault_protocol[20.5-35.5-sensitivity_analysis] PASSED
tests/test_demo_output.py::test_35_minute_label_does_not_claim_a_60_minute_result PASSED
tests/test_demo_output.py::test_default_demo_output_is_unchanged[generator] PASSED
tests/test_demo_output.py::test_default_demo_output_is_unchanged[workflow] PASSED
tests/test_demo_output.py::test_default_demo_output_is_unchanged[paired_simulation] PASSED
tests/test_demo_output.py::test_default_demo_output_is_unchanged[cohort_evaluation] PASSED
tests/test_demo_output.py::test_default_demo_output_is_unchanged[sensitivity_analysis] PASSED
tests/test_generator.py::test_original_default_13_readings PASSED
tests/test_generator.py::test_one_hour_five_readings PASSED
tests/test_generator.py::test_reproducible PASSED
tests/test_generator.py::test_all_eight_present PASSED
tests/test_generator.py::test_chronological_and_patient_id[non_hypertensive] PASSED
tests/test_generator.py::test_chronological_and_patient_id[mild_hypertension] PASSED
tests/test_generator.py::test_chronological_and_patient_id[persistent_severe] PASSED
tests/test_generator.py::test_chronological_and_patient_id[nonpersistent_severe] PASSED
tests/test_generator.py::test_chronological_and_patient_id[recurrent_severe] PASSED
tests/test_generator.py::test_chronological_and_patient_id[borderline_severe] PASSED
tests/test_generator.py::test_chronological_and_patient_id[delayed_or_missing_repeat] PASSED
tests/test_generator.py::test_chronological_and_patient_id[spurious_severe] PASSED
tests/test_generator.py::test_nosevere_categories[non_hypertensive] PASSED
tests/test_generator.py::test_nosevere_categories[mild_hypertension] PASSED
tests/test_generator.py::test_nosevere_categories[borderline_severe] PASSED
tests/test_generator.py::test_mild_every_reading_hypertensive PASSED
tests/test_generator.py::test_persistent_repeat_at_ten PASSED
tests/test_generator.py::test_transient_normal_repeat PASSED
tests/test_generator.py::test_recurrent_severe PASSED
tests/test_generator.py::test_delayed_recheck_has_no_early_reading[42-delayed-16] PASSED
tests/test_generator.py::test_delayed_recheck_has_no_early_reading[42-missing_early-30] PASSED
tests/test_generator.py::test_delayed_recheck_has_no_early_reading[43-delayed-16] PASSED
tests/test_generator.py::test_delayed_recheck_has_no_early_reading[43-missing_early-30] PASSED
tests/test_generator.py::test_delayed_recheck_has_no_early_reading[120-delayed-16] PASSED
tests/test_generator.py::test_delayed_recheck_has_no_early_reading[120-missing_early-30] PASSED
tests/test_generator.py::test_delayed_recheck_has_no_early_reading[121-delayed-16] PASSED
tests/test_generator.py::test_delayed_recheck_has_no_early_reading[121-missing_early-30] PASSED
tests/test_generator.py::test_default_delayed_subtype_is_seed_independent[42] PASSED
tests/test_generator.py::test_default_delayed_subtype_is_seed_independent[43] PASSED
tests/test_generator.py::test_invalid_delayed_subtype_rejected[kwargs0] PASSED
tests/test_generator.py::test_invalid_delayed_subtype_rejected[kwargs1] PASSED
tests/test_generator.py::test_cohort_subtype_cycle_is_independent_of_seed PASSED
tests/test_generator.py::test_default_cohort_matches_pre_refactor_observations PASSED
tests/test_generator.py::test_spurious_is_ground_truth_only PASSED
tests/test_generator.py::test_cohort_80_and_summary PASSED
tests/test_generator.py::test_5000_cohort_possible PASSED
tests/test_generator.py::test_invalid[kwargs0] PASSED
tests/test_generator.py::test_invalid[kwargs1] PASSED
tests/test_generator.py::test_invalid[kwargs2] PASSED
tests/test_generator.py::test_invalid[kwargs3] PASSED
tests/test_generator.py::test_invalid[kwargs4] PASSED
tests/test_paired_simulation.py::test_paired_simulation_is_reproducible PASSED
tests/test_paired_simulation.py::test_same_recorded_bp_timeline PASSED
tests/test_paired_simulation.py::test_input_readings_are_not_modified PASSED
tests/test_paired_simulation.py::test_all_communication_pathways[direct] PASSED
tests/test_paired_simulation.py::test_all_communication_pathways[collaboration_required] PASSED
tests/test_paired_simulation.py::test_all_communication_pathways[provider_uncertain] PASSED
tests/test_paired_simulation.py::test_no_improvement_when_effect_is_zero PASSED
tests/test_paired_simulation.py::test_improved_recognition_with_assumed_effect PASSED
tests/test_paired_simulation.py::test_missing_recheck_is_recorded_as_missing PASSED
tests/test_paired_simulation.py::test_projected_rechecks_do_not_change_recorded_bp PASSED
tests/test_paired_simulation.py::test_treatment_benchmark_starts_at_first_severe PASSED
tests/test_paired_simulation.py::test_invalid_provider_pathway_rejected PASSED
tests/test_paired_simulation.py::test_empty_patient_stream_rejected PASSED
tests/test_protocol.py::test_default_protocol_loads PASSED
tests/test_protocol.py::test_repeat_window_is_ordered PASSED
tests/test_rules.py::test_is_severe[120-80-False] PASSED
tests/test_rules.py::test_is_severe[159-109-False] PASSED
tests/test_rules.py::test_is_severe[160-90-True] PASSED
tests/test_rules.py::test_is_severe[140-110-True] PASSED
tests/test_rules.py::test_is_severe[175-115-True] PASSED
tests/test_sensitivity_analysis.py::test_default_effect_levels PASSED
tests/test_sensitivity_analysis.py::test_one_row_per_effect PASSED
tests/test_sensitivity_analysis.py::test_cohort_coverage_remains_constant PASSED
tests/test_sensitivity_analysis.py::test_zero_effect_has_no_improvement PASSED
tests/test_sensitivity_analysis.py::test_same_seed_is_reproducible PASSED
tests/test_sensitivity_analysis.py::test_baseline_values_constant_across_effect_levels PASSED
tests/test_sensitivity_analysis.py::test_prompt_effect_does_not_worsen_projected_recheck PASSED
tests/test_sensitivity_analysis.py::test_recheck_improvement_nondecreasing PASSED
tests/test_sensitivity_analysis.py::test_invalid_effect_is_rejected[-0.1] PASSED
tests/test_sensitivity_analysis.py::test_invalid_effect_is_rejected[1.1] PASSED
tests/test_sensitivity_analysis.py::test_empty_cohort_returns_missing_averages PASSED
tests/test_sensitivity_analysis.py::test_default_sensitivity_matches_pre_refactor_results PASSED
tests/test_shared_simulation_rules.py::test_shared_rule_uses_loaded_thresholds[169-119-False] PASSED
tests/test_shared_simulation_rules.py::test_shared_rule_uses_loaded_thresholds[170-80-True] PASSED
tests/test_shared_simulation_rules.py::test_shared_rule_uses_loaded_thresholds[130-120-True] PASSED
tests/test_shared_simulation_rules.py::test_generator_baseline_validation_uses_shared_protocol PASSED
tests/test_shared_simulation_rules.py::test_routine_caps_follow_shared_thresholds PASSED
tests/test_shared_simulation_rules.py::test_summary_uses_shared_protocol PASSED
tests/test_shared_simulation_rules.py::test_existing_severe_repeat_window_boundaries[14-False] PASSED
tests/test_shared_simulation_rules.py::test_existing_severe_repeat_window_boundaries[15-True] PASSED
tests/test_shared_simulation_rules.py::test_existing_severe_repeat_window_boundaries[60-True] PASSED
tests/test_shared_simulation_rules.py::test_existing_severe_repeat_window_boundaries[61-False] PASSED
tests/test_shared_simulation_rules.py::test_existing_repeat_uses_loaded_window[15-False] PASSED
tests/test_shared_simulation_rules.py::test_existing_repeat_uses_loaded_window[20-True] PASSED
tests/test_shared_simulation_rules.py::test_existing_repeat_uses_loaded_window[45-True] PASSED
tests/test_shared_simulation_rules.py::test_existing_repeat_uses_loaded_window[46-False] PASSED
tests/test_shared_simulation_rules.py::test_existing_repeat_check_is_not_full_persistence PASSED
tests/test_shared_simulation_rules.py::test_no_existing_severe_repeat_returns_none[readings0] PASSED
tests/test_shared_simulation_rules.py::test_no_existing_severe_repeat_returns_none[readings1] PASSED
tests/test_shared_simulation_rules.py::test_no_existing_severe_repeat_returns_none[readings2] PASSED
tests/test_shared_simulation_rules.py::test_delayed_subtypes_remain_unsupported_until_episode_integration[delayed] PASSED
tests/test_shared_simulation_rules.py::test_delayed_subtypes_remain_unsupported_until_episode_integration[missing_early] PASSED
tests/test_shared_simulation_rules.py::test_workflow_and_cohort_use_one_loaded_protocol PASSED
tests/test_shared_simulation_rules.py::test_result_keeps_target_used_during_simulation PASSED
tests/test_shared_simulation_rules.py::test_recheck_projection_uses_loaded_target[False] PASSED
tests/test_shared_simulation_rules.py::test_recheck_projection_uses_loaded_target[True] PASSED
tests/test_shared_simulation_rules.py::test_csv_export_uses_shared_protocol PASSED
tests/test_simulation_config.py::test_default_generator_config_loads PASSED
tests/test_simulation_config.py::test_default_workflow_config_loads PASSED
tests/test_simulation_config.py::test_config_paths_are_independent_of_working_directory PASSED
tests/test_simulation_config.py::test_alternate_generator_defaults_and_variation_are_used PASSED
tests/test_simulation_config.py::test_alternate_onset_and_scenario_values_are_used PASSED
tests/test_simulation_config.py::test_alternate_scenario_baseline_is_used PASSED
tests/test_simulation_config.py::test_alternate_delayed_subtype_default_is_used PASSED
tests/test_simulation_config.py::test_alternate_workflow_delays_are_used[direct-0] PASSED
tests/test_simulation_config.py::test_alternate_workflow_delays_are_used[collaboration_required-2] PASSED
tests/test_simulation_config.py::test_alternate_workflow_delays_are_used[provider_uncertain-2] PASSED
tests/test_simulation_config.py::test_invalid_generator_config_rejected[systolic_variation = [-5, 5]-systolic_variation = [5, -5]] PASSED
tests/test_simulation_config.py::test_invalid_generator_config_rejected[minutes = [45, 60, 75, 90]-minutes = []] PASSED
tests/test_simulation_config.py::test_invalid_generator_config_rejected[default_subtype = "delayed"-default_subtype = "unknown"] PASSED
tests/test_simulation_config.py::test_invalid_generator_config_rejected[cohort_subtypes = ["missing_early", "delayed"]-cohort_subtypes = []] PASSED
tests/test_simulation_config.py::test_invalid_generator_config_rejected[systolic = [162, 178]-systolic = [-1, 178]] PASSED
tests/test_simulation_config.py::test_invalid_workflow_range_rejected[[-1, 5]] PASSED
tests/test_simulation_config.py::test_invalid_workflow_range_rejected[[15, 3]] PASSED
tests/test_simulation_config.py::test_invalid_workflow_range_rejected[[true, 15]] PASSED
tests/test_simulation_config.py::test_each_simulation_parameter_has_a_source[path0] PASSED
tests/test_simulation_config.py::test_each_simulation_parameter_has_a_source[path1] PASSED
tests/test_workflow.py::test_reproducible_results PASSED
tests/test_workflow.py::test_first_severe_starts_treatment_clock PASSED
tests/test_workflow.py::test_actions_are_in_correct_order PASSED
tests/test_workflow.py::test_all_provider_pathways_run[direct] PASSED
tests/test_workflow.py::test_all_provider_pathways_run[collaboration_required] PASSED
tests/test_workflow.py::test_all_provider_pathways_run[provider_uncertain] PASSED
tests/test_workflow.py::test_collaboration_delay_is_separate PASSED
tests/test_workflow.py::test_provider_uncertainty_adds_identification_delay PASSED
tests/test_workflow.py::test_tool_preserves_existing_bp_timestamps PASSED
tests/test_workflow.py::test_tool_reduces_assumed_delays PASSED
tests/test_workflow.py::test_zero_prompt_effect_changes_nothing PASSED
tests/test_workflow.py::test_empty_readings_rejected PASSED
tests/test_workflow.py::test_invalid_provider_pathway_rejected PASSED
tests/test_workflow.py::test_invalid_prompt_effect_rejected PASSED
tests/test_workflow.py::test_recheck_target_is_15_minutes PASSED
tests/test_workflow.py::test_projected_recheck_never_precedes_target PASSED
tests/test_workflow.py::test_projected_recheck_never_precedes_recognition PASSED
tests/test_workflow.py::test_recheck_simulation_is_reproducible PASSED
tests/test_workflow.py::test_tool_can_reduce_projected_recheck_lateness PASSED
tests/test_workflow.py::test_missing_recheck_has_no_projected_time PASSED
tests/test_workflow.py::test_recheck_does_not_change_recorded_confirmation PASSED
tests/test_workflow.py::test_recheck_zero_prompt_effect_has_no_benefit PASSED
```
