"""Draft the same episodes' EMR notes with each model, to check they're comparable.

The episodes are the unit view's story patients over a few seeds (synthetic,
from config/unit_layout.toml). For each model the report gives how often a
draft came back on the schema and passed verify_traceability(), how long it
took, and each episode's events with every model's summary beneath, for a
person to read. The timeline below a summary is the template's, the same for
every model, so only the summaries are shown.

    uv run python scripts/compare_emr_drafters.py [--seeds 3] [--out notes/emr-compare.md]

Calls Claude once per episode (Haiku: a fraction of a cent each) unless
--local-only. The report goes to notes/ by default, which Git ignores.
"""

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import app.llm as llm  # noqa: E402
from app.playback import evaluate_unit_view  # noqa: E402
from app.unit_view import build_shift  # noqa: E402
from htn_alert.emr import verify_traceability  # noqa: E402
from htn_alert.protocol import load_protocol  # noqa: E402


def episodes(seeds: int) -> list[tuple[str, list]]:
    """(label, events) for every story patient at the end of each seed's shift."""
    protocol = load_protocol()
    found = []
    for seed in range(1, seeds + 1):
        shift = build_shift(seed, protocol)
        statuses = evaluate_unit_view(shift.readings, shift.end, protocol, shift.actions)
        for bed, role in sorted(shift.roles.items()):
            if role != "routine":
                found.append((f"seed {seed}, {bed} ({role})", statuses[bed].events))
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--out", default=str(REPO_ROOT / "notes" / "emr-compare.md"))
    parser.add_argument("--local-only", action="store_true", help="skip the Claude calls")
    args = parser.parse_args()

    llm.load_env()
    models = [(f"{llm.ollama_model()} (local)", llm.make_ollama_call())]
    if not args.local_only:
        models.append((llm.claude_model(), llm.make_claude_call()))

    cases = episodes(args.seeds)
    tallies = {name: {"ok": 0, "seconds": 0.0, "problems": []} for name, _ in models}
    sections = []
    for label, events in cases:
        sections.append(f"## {label}\n\n```\n{llm.summary_prompt(events)}\n```\n")
        for name, call in models:
            start = time.time()
            try:
                summary = call(llm.summary_prompt(events))
                text = llm.assemble_note(events, summary)
                check = verify_traceability(text, events)
                verdict = "passes" if check.valid else f"untraceable: {', '.join(check.untraceable_items)}"
            except llm.DraftUnavailable as e:
                text, summary, verdict = "", "", f"unavailable: {e}"
            seconds = time.time() - start
            tally = tallies[name]
            tally["seconds"] += seconds
            if verdict == "passes":
                tally["ok"] += 1
            else:
                tally["problems"].append(f"{label}: {verdict}")
            sections.append(f"**{name}**, {seconds:.1f} s, {verdict}\n\n> {summary}\n")
        print(f"done: {label}")

    report = ["# EMR summaries: local model vs Claude\n", f"{len(cases)} episodes, seeds 1–{args.seeds}.\n",
              "| Model | Usable summaries | Mean time |", "| --- | --- | --- |"]
    for name, tally in tallies.items():
        report.append(f"| {name} | {tally['ok']} / {len(cases)} | {tally['seconds'] / len(cases):.1f} s |")
    for name, tally in tallies.items():
        if tally["problems"]:
            report.append(f"\n**{name}, not usable:**\n")
            report += [f"- {p}" for p in tally["problems"]]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(report) + "\n\n" + "\n".join(sections), encoding="utf-8")
    print("\n".join(report))
    print(f"\nfull report: {out}")


if __name__ == "__main__":
    main()
