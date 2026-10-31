# Synthetic simulation configuration

This is a research prototype for engineering tests, not for clinical use.
The balanced cohort does not estimate hospital prevalence. Its delay ranges
and intervention effects are assumptions, not measured hospital outcomes.

## Where values come from

| File | Purpose | Source |
| --- | --- | --- |
| `config/protocol.toml` | Shared severe thresholds, repeat window, treatment duration | Existing Pitch/Lit/Assume comments; unchanged in this refactor |
| `config/generator.toml` | Default duration/cadence/baselines, variation, onset, scenario readings, delayed-repeat choices | Every value is marked Assume; retained from PR #7 |
| `config/workflow.toml` | Inclusive uniform staff delay ranges and reassessment RNG offset | Every value is marked Assume; retained from PR #7 |

Scenario readings are test fixtures, including the entries at +10, +15 and
+30 minutes. They do not define clinical persistence. Integer BP values are
fixed fixtures; two-element arrays are inclusive uniform ranges. Fixed values
do not consume random draws, preserving the seeded observation streams.
Do not relabel a value Pitch or Lit without an actual source.

The loaders in `htn_alert.simulation_config` accept alternate TOML paths and
validate ranges, offsets and subtype choices. They resolve default paths from
the repository, independently of the working directory, and do not cache files.
`load_protocol()` and `rules.is_severe(reading, protocol)` supply the one shared
severity rule. Change protocol values only with team approval.

## Explicit delayed-repeat subtypes

```python
from datetime import datetime
from htn_alert.generator import generate_bp_readings

readings = generate_bp_readings(
    patient_id="SIM-EXAMPLE",
    start_time=datetime(2026, 10, 26, 8),
    scenario="delayed_or_missing_repeat",
    delayed_repeat_subtype="missing_early",  # configured repeat at +30 minutes
    seed=43,
)
```

The `delayed` subtype supplies a nonsevere repeat at +16 minutes; `missing_early`
supplies one at +30 minutes. The single-patient default is `delayed`, independent
of seed. Change the seed to vary BP samples and onset, while retaining the
selected subtype. Passing a subtype to another scenario is rejected.

`generate_cohort()` explicitly cycles `missing_early`, then `delayed`, within
the delayed-repeat family. The cycle is independent of seed and patient count.
It preserves the existing default 80-patient, seed-42 cohort exactly. Older
calls that relied on seed parity must now choose their subtype explicitly.

## Alternate configuration for experiments

```python
from pathlib import Path
from htn_alert.simulation_config import load_generator_config, load_workflow_config
from htn_alert.protocol import load_protocol
from htn_alert.generator import generate_cohort
from htn_alert.cohort_evaluation import evaluate_cohort

protocol = load_protocol()
generator_config = load_generator_config(Path("config/generator.toml"))
workflow_config = load_workflow_config(Path("config/workflow.toml"))
cohort = generate_cohort(config=generator_config, protocol=protocol)
result = evaluate_cohort(cohort, workflow_config=workflow_config, protocol=protocol)
```

Existing positional generator/workflow arguments still work. Omitted generator
duration, interval and baselines now use the TOML defaults; explicit arguments
override those defaults. `seed` and `prompt_effect` remain caller-controlled
experiment inputs. The existing 0–100% sensitivity levels are unchanged.
Workflow and reassessment simulation accept `config=` and `protocol=`;
paired comparison and cohort evaluation accept `workflow_config=` and `protocol=`.

## Limited repeat lookup and compatibility

`workflow.find_severe_repeat_in_window()` selects an existing severe observation
in the protocol window after the first severe BP, currently +15 through +60
minutes inclusive. Cohort eligibility reuses this lookup. This does **not**
implement all persistence rules: in particular, it does not classify the absence
of a below-severe reading within 15 minutes. Clinical persistence, episode
boundaries and the SMFM worked examples belong to Daniel's episode engine in
[issue #9](https://github.com/devans2718/hypertension-alert-pregnancy/issues/9).

Both delayed-repeat subtypes therefore remain unsupported by this limited
simulator. The default denominator remains 20 supported patients out of 80,
with every unsupported patient reported. Unsupported does not mean clinically
nonpersistent. No SMFM patient-level rate is calculated here.

The clearer accessor `severe_repeat_in_window_time` preserves the public
`confirming_reading_time` field for callers. `severe_without_repeat_in_window`
similarly preserves `severe_without_qualifying_repeat`. These compatibility
names do not imply full episode confirmation.

`within_treatment_target` uses the protocol's treatment duration, captured in
each result; `within_60_minutes` remains its compatibility alias. Existing paired
and cohort `within_60` fields likewise refer to that configured target, currently
60 minutes. This refactor retains the simulator's clock from the **first severe
BP** and does not change the episode engine's clock or the wording in the shared
protocol file. Clock alignment with the team is separate from loading the duration.

Projected reassessments remain separate from recorded BP observations. They do
not determine the recorded severe-repeat time or cause the modeled medication
timing differences. Recognition remains in its original assumed range. Connecting
the workflow to actual synthetic observations is a later design discussion.

## Demonstrations

```bash
uv run pytest -v
uv run python -m htn_alert.generator
uv run python -m htn_alert.workflow
uv run python -m htn_alert.paired_simulation
uv run python -m htn_alert.cohort_evaluation
uv run python -m htn_alert.sensitivity_analysis
```

These commands print results and do not export `data/` files. CSV export remains
available separately and uses the shared severity rule. Its test writes only to
a temporary test directory.
