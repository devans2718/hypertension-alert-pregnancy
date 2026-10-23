# Onboarding checklist

Everything a builder needs before starting on their part. Work through it in
order; each step says how to check it worked. Stuck on a step? Ask on Discord.
That's what this is for.

## 1. Accounts and access

- [ ] **GitHub account**, with your username sent to Daniel.
- [ ] **Repository invite accepted** (from GitHub's email, or
      [the invitations page](https://github.com/devans2718/hypertension-alert-pregnancy/invitations)).
      *Check:* the repo page shows you can create branches. You won't see the
      Settings tab; on a personal repository only the owner does.
- [ ] **On the team Discord.**

## 2. Tools on your machine

- [ ] **Git.** *Check:* `git --version` prints a version.
      Windows: `winget install --id Git.Git -e`. macOS: `xcode-select --install`.
- [ ] **Git signed in to GitHub.** On Windows, Git Credential Manager (included
      with Git) opens a browser the first time you push. Alternatively, install
      the [GitHub CLI](https://cli.github.com/) and run `gh auth login`.
- [ ] **uv.** *Check:* `uv --version` prints a version. Close and reopen your
      terminal (and your agent) after installing, so it's on your PATH.
      - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
      - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- [ ] **Your coding agent, updated** (Codex, Antigravity, or Claude Code).

## 3. The code runs

```
git clone https://github.com/devans2718/hypertension-alert-pregnancy.git
cd hypertension-alert-pregnancy
uv sync
uv run pytest
```

- [ ] *Check:* every test passes. uv downloads Python 3.12 itself if needed.

## 4. Your agent has the project instructions

- [ ] Open the repository with your agent and ask: **"What do your project
      instructions say?"** *Check:* the answer mentions synthetic data only and
      not for clinical use. If it doesn't, your agent isn't reading `AGENTS.md`;
      update it, or ask on Discord.

## 5. Read the ground rules

- [ ] **[AGENTS.md](../AGENTS.md)**, the ground rules section especially:
      synthetic data only, no clinical claims, no secrets in the repo,
      only redistributable content.
- [ ] **[`src/htn_alert/contract.py`](../src/htn_alert/contract.py)**: the data
      types every part shares. Know which part is yours and what it consumes
      and produces.

## 6. Practice the workflow once

`main` only changes through pull requests, and the tests must pass first. Run
the whole loop once on something harmless: adding yourself to the Builders
list in the README.

```
git switch -c <your-name>/add-to-builders
# edit README.md: add a line for yourself under "Builders"
git add README.md
git commit -m "Add <your name> to Builders"
git push -u origin <your-name>/add-to-builders
```

- [ ] **Open the pull request** on GitHub (it offers a button after the push).
      In the description, note what your agent did, if anything.
- [ ] *Check:* the `pytest` check passes on the pull request.
- [ ] **Merge it**, then update your copy: `git switch main` and `git pull`.

You're ready to work.

## How we work

Your agent follows [AGENTS.md](../AGENTS.md). These are the matching
conventions for people:

- **Commit your own work from your own account.** The course grades individual
  contributions, and the commit history is the record.
- **Review what your agent wrote before it's committed.** You're responsible
  for everything in your commits, whoever typed it.
- **Agents open pull requests as drafts.** Mark one **Ready for review** only
  after you've reviewed it; that click is the review record.
- **Add to the pull request description what you changed or rejected** from
  the agent's work. With the agent's note on what it did, this is the
  Human–AI Co-Design evidence for the course report.
