# Hypertension Alert System for Pregnancy

A prototype for the Hack-A-Roo Fall 2026 Pitch-to-Build track at UMKC: supporting
timely recognition, confirmation, and provider notification of persistent
severe-range blood pressure on a labor and delivery unit.

> **Research prototype. Not a medical device and not for clinical use.**
> All data in this repository is synthetic. No patient data is used or accepted.

## Setup

Requires [Git](https://git-scm.com/) and [uv](https://docs.astral.sh/uv/getting-started/installation/).
uv installs the right Python (3.12) itself if it's missing.

```
git clone https://github.com/devans2718/hypertension-alert-pregnancy.git
cd hypertension-alert-pregnancy
uv sync          # create the environment from the lockfile
uv run pytest    # run the tests
```

New to the project? Work through the [onboarding checklist](docs/onboarding.md).

## Builders

- Daniel Evans (Data Science), build lead

## Status

Scaffold: the shared data contract (`src/htn_alert/contract.py`), the protocol
values (`config/protocol.toml`), and the severe-range check are in place. The
episode logic, generator, evaluation, and app are next.

## Using a coding agent

Agents read [AGENTS.md](AGENTS.md) for the project's ground rules and
conventions. To check yours did, ask it what its project instructions say.

## License

MIT; see [LICENSE](LICENSE).
