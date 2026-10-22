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

## Layout (planned; update this section when it changes)

```
src/htn_alert/        core logic: reading checks, episodes, generator, evaluation
app/                  the demo app
tests/                pytest tests
config/protocol.toml  clinical thresholds, repeat window, escalation times
```

- Keep the core logic independent of the app, so it can be tested directly.
- **Clinical and timing values live in `config/protocol.toml`, not in code.**
  Each value gets a comment naming its source: pitch team, literature, or
  assumption. Until the pitch team confirms a value, treat it as an assumption.

## Setup (once `pyproject.toml` exists)

```
uv sync          # create the environment
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
