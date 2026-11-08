"""The model calls behind the EMR note draft's summary.

Drafting runs outside the alerting loop: no model sits between a severe
reading and an alert. The draft is for the nurse to review.

The note is the template from htn_alert.emr.draft_emr_entry(): a timeline of
the episode's events, complete and traceable by construction. A model adds
one thing, the summary at the top, so its job stays narrow and every model's
note has the same timeline. Models are tried in order, then no summary:
    1. a local model through Ollama (free, on the same machine as the app)
    2. Claude through the Anthropic API
A summary counts only if the whole note passes verify_traceability();
otherwise the next model gets the job. scripts/compare_emr_drafters.py
compares the two on the same episodes.

Configuration, from the environment or the repository's `.env` (ignored by Git):
    OLLAMA_URL          default http://localhost:11434
    OLLAMA_MODEL        default qwen3.5:9b; set to "off" to skip the local model
    ANTHROPIC_API_KEY   the key the Claude call uses
    EMR_MODEL           Claude model; default claude-haiku-5-5
"""

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import anthropic

from htn_alert.contract import Event
from htn_alert.emr import draft_emr_entry, verify_traceability

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_CLAUDE_MODEL = "claude-haiku-5-5"  # Daniel, 2026-11-07: cheap; revisit if drafts look wrong
DEFAULT_OLLAMA_MODEL = "qwen3.5:9b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

# What each event means, from EventKind and src/htn_alert/episodes.py. The
# event list alone gives a model only terse labels to paraphrase.
SYSTEM = """\
You write the summary at the top of a nursing EMR note, for a research prototype \
that runs on synthetic data; it is not used on real patients. The note's timeline \
is written separately; you write only the summary.

The events come from an alerting system that follows a severe blood pressure \
episode on a labor and delivery unit. What each event means:
- episode_opened: the first severe reading (systolic 160 or more, or diastolic 110 \
or more). The episode starts here, and the treatment target is 60 minutes after it.
- repeat_due: 15 minutes have passed since the first severe reading, so a repeat \
reading is due.
- confirmed: the episode counts as persistent severe hypertension and the provider \
has been notified. The detail gives the reason: "severe again within the repeat \
window" means a second severe reading came 15 to 60 minutes after the first; "no \
reading below the severe range in time" means no reading below the severe range \
came by the 15-minute mark, so the episode was treated as persistent.
- dose_recorded: a dose of blood pressure medication was recorded.
- escalated: the notified provider had not responded in time, so the alert was \
escalated.
- episode_closed: a reading below the severe range ended the episode.
- episode_reopened: a severe reading within 60 minutes of the first one, so the \
closed episode continues; it is the same episode, not a new one.

Write at most two plain sentences, in the past tense, saying what happened and in \
what order. The timeline under the summary lists every event, so give the course of \
the episode rather than each event in turn. Use only times that appear in the events, and no other numbers, in \
digits or in words (not "fifteen minutes later"). A reading that ends an episode is \
"below the severe range", not "normal": it can still be high. Do not recommend \
treatment and do not name a diagnosis. Reply with JSON matching the given schema."""

# Numbers spelled out, which verify_traceability() can't see: it checks digits.
_NUMBER_WORDS = re.compile(
    r"\b(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|ninety|hundred|half|quarter)\b",
    re.IGNORECASE,
)

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


class DraftUnavailable(Exception):
    """A model gave no usable summary; the chain moves on to the next."""


def load_env(path: Path = ENV_PATH) -> None:
    """Read KEY=VALUE lines from `.env` into the environment, without overriding it.

    A few lines instead of a dependency: blank lines and # comments are skipped,
    and surrounding quotes are dropped.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def summary_prompt(events: list[Event]) -> str:
    """The episode as the model sees it: the patient and each event, in order."""
    lines = [f"Patient: {events[0].patient_id}", "Events:"]
    lines += [f"- {e.time:%H:%M} {e.kind.value}: {e.detail}".rstrip(": ") for e in events]
    return "\n".join(lines)


def parse_summary(raw: str) -> str:
    """The summary from a model's JSON reply."""
    try:
        summary = json.loads(raw)["summary"].strip()
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        raise DraftUnavailable("reply didn't match the schema") from e
    if not summary:
        raise DraftUnavailable("empty summary")
    spelled = sorted({m.lower() for m in _NUMBER_WORDS.findall(summary)})
    if spelled:
        raise DraftUnavailable(f"number in words: {', '.join(spelled)}")
    return summary


def assemble_note(events: list[Event], summary: str | None) -> str:
    """The template note, with the summary under its header when there is one."""
    lines = draft_emr_entry(events).split("\n")
    if summary:
        lines.insert(1, f"Summary: {summary}")
    return "\n".join(lines)


def claude_model() -> str:
    return os.environ.get("EMR_MODEL", DEFAULT_CLAUDE_MODEL)


def ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def make_claude_call() -> Callable[[str], str]:
    """A prompt -> summary function using Claude, with the schema enforced."""
    load_env()

    def call(prompt: str) -> str:
        try:
            # A short timeout: the app waits on this while the nurse watches.
            client = anthropic.Anthropic(timeout=30.0, max_retries=1)
            response = client.messages.create(
                model=claude_model(),
                max_tokens=4000,
                # A two-sentence summary needs little thinking.
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA},
                },
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.AuthenticationError as e:
            raise DraftUnavailable("no valid API key (set ANTHROPIC_API_KEY in .env)") from e
        except anthropic.RateLimitError as e:
            raise DraftUnavailable("rate limited; try again shortly") from e
        except anthropic.APIStatusError as e:
            raise DraftUnavailable(f"API error {e.status_code}") from e
        except anthropic.APIConnectionError as e:
            raise DraftUnavailable("could not reach the API") from e
        except anthropic.AnthropicError as e:
            raise DraftUnavailable(str(e) or type(e).__name__) from e
        except TypeError as e:
            # What the SDK raises when it finds no credentials at all (2.6.0).
            raise DraftUnavailable("no API key found (set ANTHROPIC_API_KEY in .env)") from e

        if response.stop_reason != "end_turn":
            raise DraftUnavailable(f"model stopped early ({response.stop_reason})")
        return parse_summary(next((b.text for b in response.content if b.type == "text"), ""))

    return call


def make_ollama_call() -> Callable[[str], str]:
    """A prompt -> summary function using a local model through Ollama's chat API.

    Ollama's own HTTP API through the standard library, so no extra dependency.
    The schema goes in `format`, which Ollama enforces while generating;
    thinking is off, since a short summary doesn't need it and it's slower.
    """
    load_env()
    url = os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL).rstrip("/") + "/api/chat"

    def call(prompt: str) -> str:
        body = json.dumps({
            "model": ollama_model(),
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "format": SUMMARY_SCHEMA,
            "think": False,
            "stream": False,
            "options": {"temperature": 0},
        }).encode()
        request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        try:
            # Generous: the first call after a while loads the model onto the GPU.
            with urllib.request.urlopen(request, timeout=60) as response:
                reply = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            raise DraftUnavailable(f"Ollama unavailable ({e})") from e
        if "error" in reply:
            raise DraftUnavailable(f"Ollama: {reply['error']}")
        return parse_summary(reply.get("message", {}).get("content", ""))

    return call


@dataclass
class Draft:
    """The note to show, who wrote its summary, and why any earlier model was passed over."""

    text: str
    source: str
    passed_over: list[str] = field(default_factory=list)


def _drafters() -> list[tuple[str, Callable[[str], str]]]:
    """The models to try, in order."""
    load_env()
    drafters = []
    if ollama_model().lower() != "off":
        drafters.append((f"{ollama_model()} (local)", make_ollama_call()))
    drafters.append((claude_model(), make_claude_call()))
    return drafters


def draft_note(events: list[Event], drafters=None) -> Draft:
    """The note with a summary from the first model whose summary holds up.

    With none, the template note alone, without a summary.
    """
    passed_over = []
    prompt = summary_prompt(events)
    for name, call in (drafters if drafters is not None else _drafters()):
        try:
            text = assemble_note(events, call(prompt))
        except DraftUnavailable as e:
            passed_over.append(f"{name}: {e}")
            continue
        check = verify_traceability(text, events)
        if not check.valid:
            passed_over.append(f"{name}: untraceable {', '.join(check.untraceable_items)}")
            continue
        return Draft(text, f"summary by {name}", passed_over)
    return Draft(assemble_note(events, None), "template, no summary", passed_over)
