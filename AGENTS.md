# Agent instructions

Shared instructions for every coding agent on this project (Codex, Antigravity,
Claude Code). Keep this file short: every agent reads all of it every session.

## The project

A prototype for the Hack-A-Roo Fall 2026 Pitch-to-Build track: helping a labor
and delivery unit recognize severe-range blood pressure, confirm it with a
timely repeat reading, and notify the right provider. It runs on simulated
readings and demonstrates the workflow; it does not connect to any hospital
system.

## Ground rules

- **Synthetic data only.** Never add, request, or generate anything presented
  as real patient data. Don't paste real patient details into prompts.
- **Research prototype, not for clinical use.** No code, comments, or docs
  should claim clinical validity or suggest use on real patients.
- **Open source (MIT).** Only add code, data, or assets we're allowed to
  redistribute. Link papers rather than committing them; cite sources.
- **No secrets in the repo.** API keys go in `.env` (ignored) or the
  deployment's secrets, never in code or commits.

## Layout (update this section when it changes)

```
src/htn_alert/        core logic
  contract.py         shared data types: Reading, Action, Event
  protocol.py         loads config/protocol.toml
  rules.py            checks on a single reading
  episodes.py         per-patient episode logic: readings and actions in, events out
  generator.py        synthetic patients, readings and staff actions
  evaluate.py         metrics over event streams
app/                  the demo app (planned)
tests/                pytest tests
config/protocol.toml  clinical thresholds, repeat window, escalation times
```

- **The data flow is fixed:** the generator produces Readings and Actions, the
  episode logic turns them into Events, and the app and evaluation consume
  Events. Add fields and kinds to `contract.py`; don't change the meaning of
  existing ones without asking.
- Keep the core logic independent of the app, so it can be tested directly.
- **Clinical and timing values live in `config/protocol.toml`, not in code.**
  Each value gets a comment naming its source: pitch team, literature, or
  assumption. Until the pitch team confirms a value, treat it as an assumption.

## Setup

Python 3.12, managed by uv. Commit `uv.lock` whenever dependencies change.

```
uv sync          # create the environment from the lockfile
uv run pytest    # run the tests
```

## How we work

- **Ask the human before:** adding a dependency, changing a value in
  `config/protocol.toml`, or anything outside this repository.
- **Tests come with logic changes.** Any change to reading checks or episode
  logic adds or updates a test.
- **Docstrings and comments state intent:** what a piece of code is for, not a
  restatement of what it does.
- **Each person commits their own work from their own account,** on a branch,
  merged to `main` through a pull request.
- **AI-assisted work is reviewed by a person before it's committed.** In the
  pull request description, note briefly what the agent did and what you
  changed or rejected. These notes are evidence for the course report.
