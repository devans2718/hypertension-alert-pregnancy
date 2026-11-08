"""The EMR draft's model chain: the first draft that holds up is shown, else the template.

Every model call here is a stand-in, so these tests make no network calls
and spend nothing.
"""

import json
import os
from datetime import datetime
from types import SimpleNamespace

import pytest

import app.llm as llm
from htn_alert.contract import Event, EventKind

T = datetime(2026, 11, 13, 8, 0)
EVENTS = [
    Event("Bed-04", T, EventKind.EPISODE_OPENED, "first severe reading"),
    Event("Bed-04", T.replace(minute=15), EventKind.CONFIRMED, "severe again within the repeat window"),
]


def _reply(summary="Severe blood pressure at 08:00 was confirmed at 08:15."):
    """A model's JSON reply, as the schema asks for."""
    return json.dumps({"summary": summary})


GOOD = "Severe blood pressure at 08:00 was confirmed at 08:15."
INVENTED = "Severe blood pressure at 08:00 was confirmed at 08:42."


def _raises(message):
    def call(prompt):
        raise llm.DraftUnavailable(message)
    return call


def test_a_traceable_summary_from_the_first_model_is_shown():
    draft = llm.draft_note(EVENTS, [("local", lambda p: GOOD)])
    assert draft.source == "summary by local"
    lines = draft.text.splitlines()
    assert lines[1] == f"Summary: {GOOD}"
    assert lines[2] == "Clinical Event Timeline:"  # the template's timeline follows
    assert draft.passed_over == []


def test_an_unavailable_model_passes_to_the_next():
    draft = llm.draft_note(EVENTS, [("local", _raises("Ollama unavailable")), ("claude", lambda p: GOOD)])
    assert draft.source == "summary by claude"
    assert draft.passed_over == ["local: Ollama unavailable"]


def test_an_untraceable_summary_passes_to_the_next():
    draft = llm.draft_note(EVENTS, [("local", lambda p: INVENTED), ("claude", lambda p: GOOD)])
    assert draft.source == "summary by claude"
    assert "untraceable" in draft.passed_over[0] and "08:42" in draft.passed_over[0]


def test_with_no_model_left_the_template_is_shown_without_a_summary():
    draft = llm.draft_note(EVENTS, [("local", _raises("down")), ("claude", _raises("no key"))])
    assert draft.source == "template, no summary"
    assert "Summary:" not in draft.text
    assert len(draft.passed_over) == 2


def test_the_prompt_lists_every_event_in_order():
    prompt = llm.summary_prompt(EVENTS)
    assert prompt.splitlines() == [
        "Patient: Bed-04", "Events:",
        "- 08:00 episode_opened: first severe reading",
        "- 08:15 confirmed: severe again within the repeat window",
    ]


@pytest.mark.parametrize("raw", [
    '{"note": "wrong key"}', "not json", '{"summary": "  "}',
    '{"summary": "Confirmed fifteen minutes later."}',  # a number the digit check can't see
])
def test_a_reply_off_the_schema_is_unavailable(raw):
    with pytest.raises(llm.DraftUnavailable):
        llm.parse_summary(raw)


def _claude_client(response=None, error=None):
    """A stand-in for anthropic.Anthropic whose messages.create returns or raises."""

    def create(**kwargs):
        if error is not None:
            raise error
        return response

    return lambda **kwargs: SimpleNamespace(messages=SimpleNamespace(create=create))


def test_claude_call_renders_its_json(monkeypatch):
    response = SimpleNamespace(stop_reason="end_turn", content=[
        SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=_reply()),
    ])
    monkeypatch.setattr(llm.anthropic, "Anthropic", _claude_client(response))
    assert llm.make_claude_call()("prompt") == GOOD


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_claude_call_unfinished_is_unavailable(monkeypatch, stop_reason):
    response = SimpleNamespace(stop_reason=stop_reason, content=[])
    monkeypatch.setattr(llm.anthropic, "Anthropic", _claude_client(response))
    with pytest.raises(llm.DraftUnavailable):
        llm.make_claude_call()("prompt")


def test_claude_connection_failure_says_so(monkeypatch):
    error = llm.anthropic.APIConnectionError(request=SimpleNamespace())
    monkeypatch.setattr(llm.anthropic, "Anthropic", _claude_client(error=error))
    with pytest.raises(llm.DraftUnavailable, match="could not reach"):
        llm.make_claude_call()("prompt")


def test_claude_without_credentials_is_unavailable_not_a_crash(monkeypatch):
    # The SDK raises a plain TypeError when it can't resolve any credentials.
    error = TypeError("Could not resolve authentication method.")
    monkeypatch.setattr(llm.anthropic, "Anthropic", _claude_client(error=error))
    with pytest.raises(llm.DraftUnavailable, match="no API key"):
        llm.make_claude_call()("prompt")


def test_ollama_unreachable_is_unavailable(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")  # nothing listens on the discard port
    with pytest.raises(llm.DraftUnavailable, match="Ollama unavailable"):
        llm.make_ollama_call()("prompt")


def test_env_file_fills_gaps_without_overriding(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\nEMR_TEST_A="from file"\nEMR_TEST_B=from file\n', encoding="utf-8")
    monkeypatch.delenv("EMR_TEST_A", raising=False)
    monkeypatch.setenv("EMR_TEST_B", "already set")
    llm.load_env(env)
    assert os.environ["EMR_TEST_A"] == "from file"
    assert os.environ["EMR_TEST_B"] == "already set"
    monkeypatch.delenv("EMR_TEST_A")
