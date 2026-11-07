"""Tests for EMR entry drafting and traceability checking (Issue #17)."""

from datetime import datetime

from htn_alert.contract import Event, EventKind
from htn_alert.emr import draft_emr_entry, verify_traceability

T0 = datetime(2026, 11, 1, 8, 0)
T15 = datetime(2026, 11, 1, 8, 15)
T16 = datetime(2026, 11, 1, 8, 16)


def sample_events() -> list[Event]:
    return [
        Event(
            patient_id="Bed-04",
            time=T0,
            kind=EventKind.EPISODE_OPENED,
            detail="Severe blood pressure observed: 168/112 mmHg.",
        ),
        Event(
            patient_id="Bed-04",
            time=T15,
            kind=EventKind.REPEAT_DUE,
            detail="Repeat blood pressure measurement due.",
        ),
        Event(
            patient_id="Bed-04",
            time=T16,
            kind=EventKind.CONFIRMED,
            detail="Persistent severe hypertension confirmed: repeat 164/108 mmHg at 08:16.",
        ),
    ]


def test_draft_no_treatment_no_diagnosis():
    """Verify that draft does not recommend treatment or state a diagnosis."""
    events = sample_events()
    draft = draft_emr_entry(events)

    # Must contain patient and timestamps
    assert "Bed-04" in draft
    assert "08:00" in draft
    assert "168/112" in draft
    assert "164/108" in draft

    # Must not contain treatment recommendations
    forbidden_terms = [
        "give", "administer", "labetalol", "hydralazine", "nifedipine", "mg", "iv",
        "treatment recommended", "order", "diagnosed with preeclampsia", "diagnosis:",
    ]
    draft_lower = draft.lower()
    for term in forbidden_terms:
        assert term not in draft_lower, f"Forbidden clinical term '{term}' found in draft!"


def test_traceability_verified_on_valid_draft():
    """A draft built from events passes traceability verification."""
    events = sample_events()
    draft = draft_emr_entry(events)
    res = verify_traceability(draft, events)

    assert res.valid is True
    assert res.untraceable_items == []
    assert "168" in res.grounded_items
    assert "112" in res.grounded_items
    assert "08:00" in res.grounded_items


def test_traceability_detects_invented_values():
    """Invented blood pressure numbers, unrecorded times, or hallucinated patient IDs are flagged."""
    events = sample_events()
    draft_with_hallucination = (
        "EMR Bedside Nursing Note — Patient: Bed-04\n"
        "- 08:00: Initial severe blood pressure recorded: 168/112 mmHg.\n"
        "- 08:16: Repeat BP recorded: 195/125 mmHg.\n"  # 195 and 125 are invented!
        "- 09:45: Future check.\n"  # 09:45 is an unrecorded time!
    )
    res = verify_traceability(draft_with_hallucination, events)

    assert res.valid is False
    assert "195" in res.untraceable_items
    assert "125" in res.untraceable_items
    assert "09:45" in res.untraceable_items


def test_custom_llm_callable_interface():
    """Verify that an external LLM callable can be passed behind the interface."""
    events = sample_events()

    def mock_llm(prompt: str) -> str:
        assert "Bed-04" in prompt
        return "Patient Bed-04 recorded BP 168/112 at 08:00 and 164/108 at 08:16."

    draft = draft_emr_entry(events, llm_call=mock_llm)
    assert "168/112" in draft
    res = verify_traceability(draft, events)
    assert res.valid is True

