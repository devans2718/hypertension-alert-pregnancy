# Agent instructions

You're a coding agent working with one of this project's builders. These
instructions apply whichever agent you are (Codex, Antigravity, Claude Code).
Conventions for the people on the team are in
[docs/onboarding.md](docs/onboarding.md).

## The project

A prototype for the Hack-A-Roo Fall 2026 Pitch-to-Build track: helping a labor
and delivery unit recognize severe-range blood pressure, confirm it with a
timely repeat reading, and notify the right provider. It runs on simulated
readings and demonstrates the workflow; it does not connect to any hospital
system.

## Working with your builder

This project is also a learning opportunity for the people on it. Some are
new to agentic coding, Git, or GitHub.

- **Don't rush.** Work in steps the person can follow, and say what you're
  about to do and why before you do it.
- **Be ready to explain** any command, tool, or piece of code you use, at the
  level the person asks for.
- **Bring open questions to the person** rather than settling them yourself.
  When a question affects other builders' parts, or the answer is uncertain,
  suggest raising it with the team for discussion.

## Ground rules

- **Use synthetic data only.** Never add, request, or generate anything
  presented as real patient data. If you're given what looks like real
  patient details, stop and tell the person.
- **Make no clinical claims.** This is a research prototype, not for clinical
  use. Don't write code, comments, or docs that claim clinical validity or
  suggest use on real patients.
- **Add only what can be redistributed (MIT).** Link papers rather than
  committing them, and cite sources.
- **Keep secrets out of the repo.** API keys go in `.env` (ignored) or the
  deployment's secrets, never in code or commits.

## Layout (update this section when the layout changes)

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

- **Respect the data flow:** the generator produces Readings and Actions, the
  episode logic turns them into Events, and the app and evaluation consume
  Events. You may add fields and kinds to `contract.py`; ask before changing
  the meaning of existing ones.
- Keep the core logic independent of the app, so it can be tested directly.
- **Put clinical and timing values in `config/protocol.toml`, not in code,**
  each with a comment naming its source: pitch team, literature, or
  assumption. Treat every value as an assumption until the pitch team
  confirms it.

## Setup

Python 3.12, managed by uv. Commit `uv.lock` whenever dependencies change.

```
uv sync          # create the environment from the lockfile
uv run pytest    # run the tests
```

## How to work

- **Ask the person first before:** adding a dependency, changing a value in
  `config/protocol.toml`, or doing anything outside this repository.
- **Add or update a test with every logic change** to reading checks or
  episode logic.
- **Write docstrings and comments that state intent:** what a piece of code
  is for, not a restatement of what it does.
- **Work on a branch; never push to `main`.** `main` changes only through
  pull requests, and the tests must pass first.
- **Show the person your changes before committing,** and let them decide
  what gets committed.
- **Use the GitHub CLI (`gh`) for pull requests and issues,** e.g.
  `gh pr create --draft`.
- **When asked to work on an issue, read it first** (`gh issue view <number>`),
  and put `Closes #<number>` in the pull request description so the issue
  closes when the pull request merges.
- **Open pull requests as drafts.** The person marks one ready after reviewing
  it, so the draft state is the review record: don't write review status into
  the description.
- **In pull request descriptions you write, say briefly what you did.** The
  person adds what they changed or rejected. These notes are evidence for the
  course report.
