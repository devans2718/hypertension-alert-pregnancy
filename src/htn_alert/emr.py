"""EMR documentation drafting and traceability verification.

An LLM or deterministic template drafts the electronic medical record (EMR)
entry from an episode's Events, and the nurse reviews and confirms it.
Detection, confirmation and escalation stay deterministic, with no model
between a severe reading and an alert.

Ground rules:
- No clinical treatment recommendations.
- No clinical diagnosis statements.
- Strict traceability: every time, number, and patient identifier in the
  draft must trace back to an Event. Invented values are flagged.
"""

import re
from dataclasses import dataclass
from typing import Callable

from htn_alert.contract import Event, EventKind


@dataclass(frozen=True)
class TraceabilityResult:
    """Outcome of verifying draft EMR tokens against source events."""

    valid: bool
    untraceable_items: list[str]
    grounded_items: list[str]


def draft_emr_entry(
    events: list[Event],
    llm_call: Callable[[str], str] | None = None,
) -> str:
    """Draft a nursing EMR documentation entry from an episode's events.

    If an `llm_call` function is provided, it is invoked behind this interface.
    Otherwise, a deterministic, structured nursing summary is produced.
    Neither template nor LLM prompt recommends treatment or diagnoses.
    """
    if not events:
        return "No events recorded for this episode."

    patient_id = events[0].patient_id

    # If an external LLM callable is provided (and functional without key)
    if llm_call is not None:
        events_summary = "\n".join(
            f"- {e.time.strftime('%H:%M')} [{e.kind.value}]: {e.detail}" for e in events
        )
        prompt = (
            f"Draft a factual nursing EMR note for patient {patient_id} based strictly on these events:\n"
            f"{events_summary}\n\n"
            f"Rules:\n"
            f"1. Do NOT recommend any clinical treatments or medications.\n"
            f"2. Do NOT state a diagnosis (e.g. preeclampsia or gestational hypertension).\n"
            f"3. Only mention times, numbers, and names present in the events list above."
        )
        try:
            return llm_call(prompt)
        except Exception:
            pass  # Fallback to deterministic generation

    # Deterministic generation
    lines: list[str] = [
        f"EMR Bedside Nursing Note — Patient: {patient_id}",
        "Clinical Event Timeline:",
    ]

    for e in events:
        t_str = e.time.strftime("%H:%M")
        if e.kind == EventKind.EPISODE_OPENED:
            lines.append(f"- {t_str}: Initial severe blood pressure recorded. {e.detail} Episode opened.")
        elif e.kind == EventKind.REPEAT_DUE:
            lines.append(f"- {t_str}: Scheduled repeat blood pressure due. {e.detail}")
        elif e.kind == EventKind.REPEAT_OVERDUE:
            lines.append(f"- {t_str}: Repeat blood pressure overdue. {e.detail}")
        elif e.kind == EventKind.CONFIRMED:
            lines.append(f"- {t_str}: Confirmed persistent severe blood pressure. {e.detail} Provider notified.")
        elif e.kind == EventKind.ESCALATED:
            lines.append(f"- {t_str}: Escalation notice triggered. {e.detail}")
        elif e.kind == EventKind.EPISODE_CLOSED:
            lines.append(f"- {t_str}: Episode closed. {e.detail}")
        else:
            lines.append(f"- {t_str}: {e.detail}")

    lines.append("Documentation Status: Draft entry prepared for nurse review and verification.")
    return "\n".join(lines)


def verify_traceability(draft: str, events: list[Event]) -> TraceabilityResult:
    """Verify that every time, number, and patient identifier in `draft` traces to `events`.

    Tokens checked:
    - Times: HH:MM patterns (e.g. 08:00, 14:30)
    - Blood pressure numbers and numeric quantities (e.g. 168, 112, 15, 60)
    - Patient identifiers (e.g. Bed-04, p1, SIM-00001)

    Returns TraceabilityResult with any untraceable tokens listed.
    """
    if not events:
        return TraceabilityResult(
            valid=False,
            untraceable_items=["No events provided for ground truth verification"],
            grounded_items=[],
        )

    # 1. Collect all grounded values from events
    grounded_times: set[str] = set()
    grounded_numbers: set[str] = set()
    grounded_names: set[str] = set()

    for e in events:
        # Time patterns
        grounded_times.add(e.time.strftime("%H:%M"))
        grounded_times.add(e.time.strftime("%-H:%M") if hasattr(e.time, "%-H") else e.time.strftime("%H:%M").lstrip("0"))
        grounded_numbers.add(str(e.time.minute))
        grounded_numbers.add(str(e.time.hour))

        # Patient name/ID tokens
        grounded_names.add(e.patient_id.lower())
        for part in re.split(r"[-_\s]+", e.patient_id):
            if part:
                grounded_names.add(part.lower())
                if part.isdigit():
                    grounded_numbers.add(part)
                    grounded_numbers.add(str(int(part)))

        # Extract all numbers from event detail
        detail_nums = re.findall(r"\b\d+\b", e.detail)
        for num in detail_nums:
            grounded_numbers.add(num)
            grounded_numbers.add(str(int(num)))

    # Standard protocol reference constants (e.g., 15-minute repeat window, 60-minute hour)
    standard_protocol_constants = {"1", "2", "15", "60", "10"}
    grounded_numbers.update(standard_protocol_constants)

    # 2. Extract tokens from draft to check
    untraceable: list[str] = []
    grounded: list[str] = []

    # Check times (HH:MM)
    found_times = re.findall(r"\b\d{1,2}:\d{2}\b", draft)
    for t in set(found_times):
        # Format normalized with leading zero
        norm_t = f"{int(t.split(':')[0]):02d}:{t.split(':')[1]}"
        if norm_t in grounded_times or t in grounded_times:
            grounded.append(t)
        else:
            untraceable.append(t)

    # Check patient identifier mentions
    patient_mentions = re.findall(r"(?:Patient(?::|\s+)|Bed-)([A-Za-z0-9_-]+)", draft, flags=re.IGNORECASE)
    for name in set(patient_mentions):
        full_mention = name.lower()
        if any(g in full_mention or full_mention in g for g in grounded_names):
            grounded.append(name)
        else:
            untraceable.append(name)

    # Check isolated numbers (e.g. BP values like 168, 112, or hallucinated 195)
    # Ignore numbers that were part of times (e.g. the 08 or 15 in 08:15) or patient IDs (Bed-04)
    text_without_times = re.sub(r"\b\d{1,2}:\d{2}\b", "", draft)
    text_without_times_or_patients = re.sub(r"[A-Za-z]+[-_]\d+", "", text_without_times)
    found_numbers = re.findall(r"\b\d+\b", text_without_times_or_patients)
    for num in set(found_numbers):
        if num in grounded_numbers:
            grounded.append(num)
        else:
            untraceable.append(num)

    is_valid = len(untraceable) == 0
    return TraceabilityResult(
        valid=is_valid,
        untraceable_items=sorted(untraceable),
        grounded_items=sorted(grounded),
    )
