"""Severe Hypertension Alert System - Demonstration App.

Real-time recognition, 15-minute repeat confirmation (fast demo mode: 15m = 10s),
live flowsheet monitoring across multiple rooms and beds, and automated clinical alerts.

The app holds only what was entered: each patient's readings and staff actions.
Episode states come from EpisodeTracker (src/htn_alert/episodes.py), replayed
through app/playback.py on every refresh, so the app and the evaluation run on
the same rules. No episode rules live in this file.
"""

import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

# Ensure repository root is on sys.path regardless of how Streamlit is invoked
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import streamlit as st
from app.playback import (
    EpisodePhase,
    calculate_countdown,
    evaluate_playback_episode,
    most_urgent_status,
)
from htn_alert.contract import Action, ActionKind, EventKind, Reading
from htn_alert.emr import draft_emr_entry, verify_traceability
from htn_alert.protocol import load_protocol

# Page Configuration
st.set_page_config(
    page_title="Severe Hypertension Alert System",
    page_icon="🩺",
    layout="wide",
)

protocol = load_protocol()

# Protocol Thresholds
SEVERE_SYS = protocol.severe_systolic    # 160 mmHg
SEVERE_DIA = protocol.severe_diastolic   # 110 mmHg
REPEAT_MIN_MINUTES = protocol.repeat_min // timedelta(minutes=1)        # 15
REPEAT_MAX_MINUTES = protocol.repeat_max // timedelta(minutes=1)        # 60
TREATMENT_MINUTES = protocol.treatment_target // timedelta(minutes=1)   # 60
DEMO_NOTICE_SECONDS = 10.0               # Notice auto-checks at 10s (bedside notification delivered)

# Fast demo clock: 15 simulated minutes pass in 10 real seconds. Every time the
# app shows or hands to EpisodeTracker is simulated time, so the protocol's
# minutes (repeat window, treatment target, escalation) play out on screen.
SIM_SPEEDUP = (15 * 60) / 10.0
# How long a resolved episode keeps the alert banner, in simulated time.
RESOLVED_BANNER = timedelta(minutes=20)


# Session State Initialization
if "records" not in st.session_state:
    st.session_state.records = []
if "inputs" not in st.session_state:
    # Key: "Room / Bed". Value: that patient's readings and actions, in the
    # order entered. This is the app's only episode-related state.
    st.session_state.inputs = {}
if "clock_start" not in st.session_state:
    # (real start, simulated start): simulated time runs from the session's start.
    st.session_state.clock_start = (time.time(), datetime.now().replace(microsecond=0))
if "active_alert" not in st.session_state:
    st.session_state.active_alert = None
if "room_val" not in st.session_state:
    st.session_state.room_val = "Room 302"
if "bed_val" not in st.session_state:
    st.session_state.bed_val = "Bed-04"
if "sys_val" not in st.session_state:
    st.session_state.sys_val = 120
if "dia_val" not in st.session_state:
    st.session_state.dia_val = 80
if "selected_record_id" not in st.session_state:
    st.session_state.selected_record_id = None
if "confirm_delete_id" not in st.session_state:
    st.session_state.confirm_delete_id = None


# Custom CSS for Tooltips, Progress Bar, and Tables
st.html("""
<style>
div[data-testid="stCheckbox"] {
    display: flex;
    justify-content: center;
    align-items: center;
    margin-top: 2px;
}
.record-table {
    width: 100%;
    border-collapse: collapse;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 14px;
    background: #ffffff;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05);
}
.record-table th {
    background-color: #f1f5f9;
    color: #1e293b;
    padding: 10px 14px;
    text-align: left;
    border-bottom: 2px solid #cbd5e1;
    font-weight: 700;
}
.record-table td {
    padding: 10px 14px;
    border-bottom: 1px solid #e2e8f0;
    vertical-align: middle;
}
.record-table tr:hover {
    background-color: #f8fafc;
}
.badge-severe {
    background-color: #fee2e2;
    color: #dc2626;
    padding: 4px 10px;
    border-radius: 14px;
    font-weight: 700;
    font-size: 12px;
    display: inline-block;
}
.badge-normal {
    background-color: #dcfce7;
    color: #16a34a;
    padding: 4px 10px;
    border-radius: 14px;
    font-weight: 600;
    font-size: 12px;
    display: inline-block;
}
.alert-box-severe {
    background: #fef2f2;
    border: 2px solid #ef4444;
    border-left: 8px solid #dc2626;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 16px;
    color: #991b1b;
    box-shadow: 0 4px 6px -1px rgba(220, 38, 38, 0.1);
}
.alert-box-normal {
    background: #f0fdf4;
    border: 1px solid #86efac;
    border-left: 6px solid #16a34a;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 16px;
    color: #166534;
}
</style>
""")


# =============================================================================
# CORE BUSINESS LOGIC & EVENT HANDLERS (Defined before widget instantiation)
# =============================================================================
def clear_all_selections():
    """Clear active edit selection and reset all row select checkbox states."""
    st.session_state.selected_record_id = None
    if "records" in st.session_state:
        for r in st.session_state.records:
            k = f"sel_{r['episode_id']}"
            if k in st.session_state:
                st.session_state[k] = False


def sim_now() -> datetime:
    """The demo's simulated time: the session's start plus elapsed real time, sped up."""
    real_start, sim_start = st.session_state.clock_start
    return sim_start + timedelta(seconds=(time.time() - real_start) * SIM_SPEEDUP)


def patient_inputs(patient_key: str) -> dict:
    """This patient's readings and actions, creating the empty lists on first use."""
    return st.session_state.inputs.setdefault(patient_key, {"readings": [], "actions": []})


def record_action(patient_key: str, kind: ActionKind):
    """Hand a staff action (acknowledgment, dose) to the episode logic's inputs."""
    patient_inputs(patient_key)["actions"].append(Action(patient_key, sim_now(), kind))


def rename_patient(old_key: str, new_key: str):
    """Move a patient's inputs to a new Room / Bed key when an edit changes it.

    The inputs carry the key as patient_id, so each one is re-labelled; otherwise
    the old key's history would keep producing alerts with no row in the table.
    """
    if old_key == new_key or old_key not in st.session_state.inputs:
        return
    old = st.session_state.inputs.pop(old_key)
    st.session_state.inputs[new_key] = {
        "readings": [replace(r, patient_id=new_key) for r in old["readings"]],
        "actions": [replace(a, patient_id=new_key) for a in old["actions"]],
    }


def patient_status(patient_key: str, now: datetime):
    """This patient's episode status at `now`, replayed through EpisodeTracker."""
    entered = st.session_state.inputs.get(patient_key)
    if not entered or not entered["readings"]:
        return None
    return evaluate_playback_episode(
        readings=entered["readings"],
        protocol=protocol,
        simulated_now=now,
        actions=entered["actions"],
    )


def current_episode_events(status) -> list:
    """The events of the patient's latest episode, from its EPISODE_OPENED on.

    A patient's event list covers every episode they've had; the banner and the
    EMR draft are about the current one only.
    """
    opened_at = max(i for i, e in enumerate(status.events) if e.kind is EventKind.EPISODE_OPENED)
    return status.events[opened_at:]


def onset_reading(patient_key: str, opened) -> Reading | None:
    """The reading that opened an episode: the one logged at EPISODE_OPENED's time."""
    readings = st.session_state.inputs[patient_key]["readings"]
    return next((r for r in readings if r.time == opened.time), None)


def log_reading(r_val: str, p_val: str, sys_val: int, dia_val: int, is_edit: bool = False):
    """Log or update a blood pressure measurement for a specific patient.

    Guarantees strict per-patient separation and eliminates duplicates:
    - If the patient already exists in the flowsheet, their vitals are updated in place.
    - If the patient is new, a separate record is created with Notice and Update starting unchecked.

    The reading also goes to the patient's inputs, timed on the demo clock; what
    it means for the episode is EpisodeTracker's call, made at render time.
    """
    is_sev = (sys_val >= SEVERE_SYS) or (dia_val >= SEVERE_DIA)
    now_time = sim_now()
    recheck_time_str = (now_time + timedelta(minutes=15)).strftime("%H:%M")
    patient_key = f"{r_val} / {p_val}"
    current_ts = time.time()

    # Locate existing patient record to prevent duplicate rows
    existing_record = None
    for r in st.session_state.records:
        if r["patient_key"] == patient_key:
            existing_record = r
            break

    if existing_record is not None:
        # Existing patient -> Update vitals in place and mark Update checked
        existing_record["room"] = r_val
        existing_record["patient_id"] = p_val
        existing_record["systolic"] = int(sys_val)
        existing_record["diastolic"] = int(dia_val)
        existing_record["time_str"] = now_time.strftime("%H:%M")
        existing_record["recheck_str"] = recheck_time_str
        existing_record["timestamp"] = current_ts
        existing_record["is_severe"] = is_sev
        existing_record["is_updated"] = True  # Follow-up reading / nurse update recorded
    else:
        # New separate patient -> Add fresh record with its own timestamp and unchecked boxes
        new_entry = {
            "room": r_val,
            "patient_id": p_val,
            "patient_key": patient_key,
            "systolic": int(sys_val),
            "diastolic": int(dia_val),
            "time_str": now_time.strftime("%H:%M"),
            "recheck_str": recheck_time_str,
            "timestamp": current_ts,
            "is_severe": is_sev,
            "episode_id": int(time.time() * 1000) + len(st.session_state.records),
            "is_noticed": False,  # Starts unchecked; auto-checks at 10s based on this record's timer
            "is_updated": False,  # Starts unchecked; checks when updated by nurse
        }
        st.session_state.records.append(new_entry)

    # The episode logic sees every reading as it arrives, on the demo clock.
    patient_inputs(patient_key)["readings"].append(
        Reading(patient_key, now_time, int(sys_val), int(dia_val))
    )


def fill_test_case(r_val: str, p_val: str, s_val: int, d_val: int):
    """Fill form inputs from Quick Test Case button.
    
    If a patient record is currently selected for editing:
    - Retains the selected patient's Room and Bed ID!
    - Updates Systolic and Diastolic with test case values.
    - Keeps 'Save Update' active so user can immediately save to this patient.
    If no record is selected:
    - Fills default Room, Bed ID, Systolic, and Diastolic.
    """
    if st.session_state.selected_record_id is None:
        st.session_state.room_val = r_val
        st.session_state.bed_val = p_val
    st.session_state.sys_val = s_val
    st.session_state.dia_val = d_val


def apply_manual_log():
    """Handler for 'Log Blood Pressure' button."""
    r = str(st.session_state.room_val).strip() or "Room 302"
    p = str(st.session_state.bed_val).strip() or "Bed-04"
    s = int(st.session_state.sys_val)
    d = int(st.session_state.dia_val)
    clear_all_selections()
    log_reading(r, p, s, d)


def apply_reset():
    """Reset all records, active episodes, and selections."""
    clear_all_selections()
    st.session_state.records = []
    st.session_state.inputs = {}
    st.session_state.active_alert = None
    st.session_state.room_val = "Room 302"
    st.session_state.bed_val = "Bed-04"
    st.session_state.sys_val = 120
    st.session_state.dia_val = 80
    st.session_state.selected_record_id = None
    st.session_state.confirm_delete_id = None


# =============================================================================
# HEADER
# =============================================================================
header_col1, header_col2 = st.columns([1.3, 1], gap="medium")

with header_col1:
    st.title("🩺 Severe Hypertension Alert System")

with header_col2:
    st.html("""
    <div style="display: flex; flex-direction: column; align-items: flex-end; justify-content: center; height: 100%; padding-top: 8px; gap: 4px;">
        <div style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px;">ACOG / SMFM Clinical Thresholds</div>
        <div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap; justify-content: flex-end;">
            <span style="background: #fee2e2; color: #b91c1c; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 700; border: 1px solid #fca5a5;">
                🚨 Severe: &ge;160 / &ge;110 mmHg
            </span>
            <span style="background: #fef3c7; color: #92400e; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 700; border: 1px solid #fcd34d;">
                ⏱️ Re-check: 15–60 min
            </span>
            <span style="background: #e0e7ff; color: #3730a3; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 700; border: 1px solid #c7d2fe;">
                💊 Med Target: &le;60 min
            </span>
        </div>
    </div>
    """)

st.markdown("---")


# =============================================================================
# MAIN 2-COLUMN WORKFLOW
# =============================================================================
col_left, col_right = st.columns([1, 1.4], gap="large")


# -----------------------------------------------------------------------------
# LEFT COLUMN: Patient Inputs, Vital Signs, and Test Cases
# -----------------------------------------------------------------------------
with col_left:
    st.markdown("### 📝 Patient & Vital Signs Entry")

    # If a patient record is selected in the flowsheet for editing, show visual context
    if st.session_state.selected_record_id is not None:
        target_rec = next((r for r in st.session_state.records if r["episode_id"] == st.session_state.selected_record_id), None)
        if target_rec:
            st.info(f"✏️ **Editing Patient:** `{target_rec['room']} / {target_rec['patient_id']}` — Adjust values and click **Save Update**, or click **Cancel**.")

    # Room and Bed Inputs
    r_col1, r_col2 = st.columns(2)
    r_col1.text_input(
        "Room / Unit Location:",
        key="room_val",
        help="Enter the clinical room or unit location (e.g., Room 302, Room 301, Triage-A).",
    )
    r_col2.text_input(
        "Patient Identifier / Bed Number:",
        key="bed_val",
        help="Enter the patient name or bed identifier (e.g., Bed-04, Bed-05, Bed-01).",
    )

    # Blood Pressure Inputs
    bp_c1, bp_c2 = st.columns(2)
    bp_c1.number_input(
        "Systolic BP (mmHg):",
        min_value=60,
        max_value=260,
        key="sys_val",
        step=1,
    )
    bp_c2.number_input(
        "Diastolic BP (mmHg):",
        min_value=40,
        max_value=160,
        key="dia_val",
        step=1,
    )

    # Test Cases Buttons placed right under Vitals
    st.markdown("---")
    st.write("**Quick Test Cases:** *(Click to fill values)*")
    tc1, tc2, tc3 = st.columns(3)

    tc1.button(
        "🟡 Severe Onset\n(168/112)",
        use_container_width=True,
        on_click=fill_test_case,
        args=("Room 302", "Bed-04", 168, 112),
    )
    tc2.button(
        "🟠 Repeat Severe\n(162/108)",
        use_container_width=True,
        on_click=fill_test_case,
        args=("Room 302", "Bed-04", 162, 108),
    )
    tc3.button(
        "🟢 Normal Routine\n(120/78)",
        use_container_width=True,
        on_click=fill_test_case,
        args=("Room 302", "Bed-04", 120, 78),
    )

    st.markdown("---")
    # Action Buttons: Edit Mode vs Standard Logging Mode
    if st.session_state.selected_record_id is not None:
        btn_c1, btn_c2, btn_c3 = st.columns([1.5, 1.4, 1])
        if btn_c1.button("💾 Save Update", type="primary", use_container_width=True):
            target_id = st.session_state.selected_record_id
            for r in st.session_state.records:
                if r["episode_id"] == target_id:
                    # An update is the patient's next reading, logged now. If the
                    # edit changed Room or Bed, the history moves with the row.
                    old_key = r["patient_key"]
                    r["room"] = str(st.session_state.room_val).strip() or "Room 302"
                    r["patient_id"] = str(st.session_state.bed_val).strip() or "Bed-04"
                    r["patient_key"] = f"{r['room']} / {r['patient_id']}"
                    rename_patient(old_key, r["patient_key"])
                    r["systolic"] = int(st.session_state.sys_val)
                    r["diastolic"] = int(st.session_state.dia_val)
                    is_sev = (r["systolic"] >= SEVERE_SYS) or (r["diastolic"] >= SEVERE_DIA)
                    r["is_severe"] = is_sev
                    logged_at = sim_now()
                    r["time_str"] = logged_at.strftime("%H:%M")
                    r["recheck_str"] = (logged_at + timedelta(minutes=15)).strftime("%H:%M")
                    r["timestamp"] = time.time()
                    r["is_updated"] = True
                    patient_inputs(r["patient_key"])["readings"].append(
                        Reading(r["patient_key"], logged_at, r["systolic"], r["diastolic"])
                    )
                    break
            clear_all_selections()
            st.rerun()

        if btn_c2.button("➕ Add as New", use_container_width=True, help="Log entered room/bed as a new separate patient"):
            clear_all_selections()
            apply_manual_log()
            st.rerun()

        if btn_c3.button("✖ Cancel", use_container_width=True):
            clear_all_selections()
            st.rerun()
    else:
        btn_col1, btn_col2 = st.columns([2, 1])
        btn_col1.button(
            "➕ Log Blood Pressure",
            type="primary",
            use_container_width=True,
            on_click=apply_manual_log,
        )
        btn_col2.button(
            "🔄 Reset Data",
            use_container_width=True,
            on_click=apply_reset,
        )


# -----------------------------------------------------------------------------
# RIGHT COLUMN: Alert Space (Top) & Multi-Patient Record Table (Bottom)
# -----------------------------------------------------------------------------
with col_right:

    # st.fragment with run_every="1s" provides live second-by-second countdown and alert refresh
    @st.fragment(run_every="1s")
    def render_alert_and_table():
        current_time_sec = time.time()
        now = sim_now()

        # Check automated protocol tracking (Notice auto-checks at 10s) per individual record
        for r in st.session_state.records:
            elapsed = current_time_sec - r["timestamp"]
            if elapsed >= DEMO_NOTICE_SECONDS:
                r["is_noticed"] = True

        # Each patient's episode status at the demo clock's `now`. Deadlines (a
        # missed recheck, an unanswered notification) fire here as time passes.
        statuses = {}
        for r in st.session_state.records:
            status = patient_status(r["patient_key"], now)
            if status is not None:
                statuses[r["patient_key"]] = status

        def bp(reading) -> str:
            return f"{reading.systolic}/{reading.diastolic}" if reading else "—"

        def hhmm(t) -> str:
            return t.strftime("%H:%M") if t else "—"

        def severe_banner(title: str, detail: str, footer: str):
            st.html(f"""<div class="alert-box-severe">
                <div style="font-size: 16px; font-weight: 800; display: flex; align-items: center; gap: 8px;">
                    <span>🚨</span>
                    <span>{title}</span>
                </div>
                <div style="font-size: 13.5px; margin-top: 6px; font-weight: 500; line-height: 1.45;">
                    {detail}
                </div>
                <div style="font-size: 11.5px; color: #b91c1c; margin-top: 4px; font-weight: 600;">
                    {footer}
                </div>
            </div>""")

        # ---------------------------------------------------------------------
        # 1. TOP-RIGHT ALERT SPACE: Evaluates Highest Priority Clinical Alert
        # ---------------------------------------------------------------------
        top = most_urgent_status(statuses, now, RESOLVED_BANNER)

        def next_deadline(status) -> str:
            """The time the most urgent patient's next step falls due, in a few words.

            Read from the status's own target times; the app computes no deadline
            itself. Escalation's time isn't shown, since its rule belongs to
            EpisodeTracker and is still being decided.
            """
            if status is None:
                return ""
            pid = status.patient_id
            if status.phase is EpisodePhase.REPEAT_PENDING:
                return f"Next: repeat reading for {pid} due {hhmm(status.repeat_target_time)}"
            if status.phase is EpisodePhase.REPEAT_DUE:
                return f"Now: repeat reading for {pid} is due"
            if status.phase in (EpisodePhase.CONFIRMED, EpisodePhase.ESCALATED):
                if any(e.kind is EventKind.DOSE_RECORDED for e in current_episode_events(status)):
                    return ""
                _, passed, _ = calculate_countdown(status.treatment_target_time, now)
                verb = "passed at" if passed else "at"
                return f"Next: treatment target for {pid} {verb} {hhmm(status.treatment_target_time)}"
            if status.phase is EpisodePhase.RESOLVED:
                return f"Watch: {pid} reopens if severe again by {hhmm(status.repeat_deadline_time)}"
            return ""

        # The demo clock, shown because every countdown, deadline and logged
        # time on the page is in simulated time; without it, when a button
        # needs pressing isn't visible.
        upcoming = next_deadline(top)
        st.html(f"""<div style="background: #0f172a; color: #f8fafc; border-radius: 8px; padding: 8px 16px; margin-bottom: 12px;">
            <div style="display: flex; align-items: baseline; gap: 10px;">
                <span style="font-size: 12px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; color: #94a3b8;">🕒 Simulated time (24-hour)</span>
                <span style="font-size: 26px; font-weight: 800; font-variant-numeric: tabular-nums;">{now.strftime("%H:%M")}</span>
                <span style="font-size: 12px; color: #94a3b8; margin-left: auto;">90× speed · 15 min = 10 s</span>
            </div>
            {f'<div style="font-size: 14px; font-weight: 600; color: #fde68a; margin-top: 2px;">{upcoming}</div>' if upcoming else ""}
        </div>""")

        if top is not None and top.phase in (EpisodePhase.CONFIRMED, EpisodePhase.ESCALATED):
            pkey = top.patient_id
            episode_events = current_episode_events(top)
            onset = episode_events[0]
            confirmed = next(e for e in episode_events if e.kind is EventKind.CONFIRMED)
            dose = next((e for e in episode_events if e.kind is EventKind.DOSE_RECORDED), None)
            acked = any(
                a.kind is ActionKind.PROVIDER_ACKNOWLEDGED and a.time >= onset.time
                for a in st.session_state.inputs[pkey]["actions"]
            )
            _, target_passed, left = calculate_countdown(top.treatment_target_time, now)

            if top.phase is EpisodePhase.ESCALATED:
                title = f"ESCALATED, NOTIFICATION NOT ANSWERED: {pkey}"
            else:
                title = f"PERSISTENT SEVERE HYPERTENSION CONFIRMED: {pkey}"
            target_line = (
                f"Treatment target passed at {hhmm(top.treatment_target_time)} ({left})."
                if target_passed
                else f"Treatment target: {hhmm(top.treatment_target_time)}, {TREATMENT_MINUTES} minutes from onset ({left} left)."
            )
            severe_banner(
                title,
                f"First severe reading {bp(onset_reading(pkey, onset))} mmHg at {hhmm(onset.time)}. "
                f"Confirmed at {hhmm(confirmed.time)}: {confirmed.detail}; provider notified. "
                + (f"Dose recorded at {hhmm(dose.time)}." if dose else target_line),
                f"Confirmed: {hhmm(confirmed.time)}",
            )

            # Staff actions go to the episode logic as Actions; an acknowledgment or
            # a dose stops the escalation timer.
            act_col1, act_col2, act_col3 = st.columns(3)
            if acked or dose:
                act_col1.success("✅ Provider responded")
            elif act_col1.button("📟 Provider Acknowledged", use_container_width=True):
                record_action(pkey, ActionKind.PROVIDER_ACKNOWLEDGED)
                st.rerun()
            if dose:
                act_col2.success(f"✅ Dose recorded ({hhmm(dose.time)})")
            elif act_col2.button("💊 Record Medication Dose", use_container_width=True, type="secondary"):
                record_action(pkey, ActionKind.DOSE_GIVEN)
                st.rerun()

            with act_col3.popover("📋 EMR Note Draft", use_container_width=True):
                draft = draft_emr_entry(episode_events)
                check = verify_traceability(draft, episode_events)
                st.markdown("**EMR nursing note draft, from this episode's events**")
                st.caption("*Drafted outside the alerting loop, for the nurse to review. Template for now; no model is called yet.*")
                st.code(draft, language="markdown")
                if check.valid:
                    st.caption("✅ Every time and number in the draft traces to an event.")
                else:
                    st.caption("⚠️ Not traceable to an event: " + ", ".join(check.untraceable_items))

        elif top is not None and top.phase is EpisodePhase.REPEAT_DUE:
            onset = current_episode_events(top)[0]
            severe_banner(
                f"REPEAT BLOOD PRESSURE DUE: {top.patient_id}",
                f"{REPEAT_MIN_MINUTES} minutes since the first severe reading ({bp(onset_reading(top.patient_id, onset))} mmHg at {hhmm(onset.time)}). "
                f"Without a reading below the severe range in this minute, the episode confirms as persistent "
                f"and the provider is notified.",
                f"Due: {hhmm(top.repeat_target_time)}",
            )

        elif top is not None and top.phase is EpisodePhase.REPEAT_PENDING:
            onset = current_episode_events(top)[0]
            _, _, left = calculate_countdown(top.repeat_target_time, now)
            severe_banner(
                f"CRITICAL SEVERE ALERT: {top.patient_id}",
                f"Severe blood pressure {bp(onset_reading(top.patient_id, onset))} mmHg detected (≥160/110 threshold). "
                f"Repeat reading due at {hhmm(top.repeat_target_time)} ({left} left).",
                f"Alert Time: {hhmm(onset.time)}",
            )

        elif top is not None and top.phase is EpisodePhase.RESOLVED:
            closed = top.latest_event
            st.html(f"""<div class="alert-box-normal">
                <div style="font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px;">
                    <span>🟢</span>
                    <span>EPISODE RESOLVED: {top.patient_id}</span>
                </div>
                <div style="font-size: 13px; margin-top: 4px;">
                    Reading {bp(top.latest_reading)} mmHg: {closed.detail} (at {hhmm(closed.time)}).
                    A severe reading within {REPEAT_MAX_MINUTES} minutes of onset reopens the episode.
                </div>
            </div>""")
        else:
            st.html("""<div class="alert-box-normal">
                <span style="font-weight: 700;">🟢 Routine Monitoring</span>
                <span style="font-size: 13px; margin-left: 8px;">All monitored patient vitals within target reference range.</span>
            </div>""")

        # ---------------------------------------------------------------------
        # 2. MULTI-PATIENT RECORD TABLE (With Select, Notice, Update, Delete)
        # ---------------------------------------------------------------------
        st.markdown("### 📋 Patient Record")

        if not st.session_state.records:
            st.info("No blood pressure readings logged yet. Use the left form or click a Test Case to begin.")
            return

        # Table Header Row
        h_sel, h_room, h_bed, h_bp, h_log, h_rc, h_stat, h_not, h_upd, h_del = st.columns(
            [0.6, 1.1, 1.1, 1.4, 1.0, 1.0, 1.3, 0.8, 0.8, 0.7]
        )
        h_sel.markdown("<div style='font-weight:700; font-size:13px; color:#1e293b;'>Select</div>", unsafe_allow_html=True)
        h_room.markdown("<div style='font-weight:700; font-size:13px; color:#1e293b;'>Room</div>", unsafe_allow_html=True)
        h_bed.markdown("<div style='font-weight:700; font-size:13px; color:#1e293b;'>Bed ID</div>", unsafe_allow_html=True)
        h_bp.markdown("<div style='font-weight:700; font-size:13px; color:#1e293b;'>Blood Pressure</div>", unsafe_allow_html=True)
        h_log.markdown("<div style='font-weight:700; font-size:13px; color:#1e293b;'>Logged</div>", unsafe_allow_html=True)
        h_rc.markdown("<div style='font-weight:700; font-size:13px; color:#1e293b;'>Re-check</div>", unsafe_allow_html=True)
        h_stat.markdown("<div style='font-weight:700; font-size:13px; color:#1e293b;'>Status</div>", unsafe_allow_html=True)
        h_not.markdown("<div style='font-weight:700; font-size:13px; color:#1e293b;'>Notice</div>", unsafe_allow_html=True)
        h_upd.markdown("<div style='font-weight:700; font-size:13px; color:#1e293b;'>Update</div>", unsafe_allow_html=True)
        h_del.markdown("<div style='font-weight:700; font-size:13px; color:#1e293b;'>Delete</div>", unsafe_allow_html=True)

        st.html("<div style='border-bottom: 2px solid #cbd5e1; margin-bottom: 8px;'></div>")

        for rec in reversed(st.session_state.records):
            rec_id = rec["episode_id"]
            pkey = rec["patient_key"]
            status = statuses.get(pkey)
            phase = status.phase if status else EpisodePhase.NONE

            # Determine Re-check Time
            recheck_val = rec.get("recheck_str") or "—"

            if rec["is_severe"]:
                recheck_display = f'<strong style="color: #dc2626; font-size: 13px;">{recheck_val}</strong>'
            else:
                recheck_display = f'<strong style="font-size: 13px;">{recheck_val}</strong>'
            # The badge is the episode's phase, not this one reading's range: an
            # episode stays confirmed until a reading below the severe range.
            status_html = {
                EpisodePhase.ESCALATED: '<span class="badge-severe">🚨 Escalated</span>',
                EpisodePhase.CONFIRMED: '<span class="badge-severe">🚨 Confirmed</span>',
                EpisodePhase.REPEAT_DUE: '<span class="badge-severe">🟠 Repeat Due</span>',
                EpisodePhase.REPEAT_PENDING: '<span class="badge-severe">🟡 Repeat Pending</span>',
                EpisodePhase.RESOLVED: '<span class="badge-normal">🟢 Resolved</span>',
            }.get(phase, '<span class="badge-normal">🟢 Normal</span>')

            c_sel, c_room, c_bed, c_bp, c_log, c_rc, c_stat, c_not, c_upd, c_del = st.columns(
                [0.6, 1.1, 1.1, 1.4, 1.0, 1.0, 1.3, 0.8, 0.8, 0.7]
            )

            # 1. Select Checkbox (Selects record for updating in the left form)
            is_cur_selected = (st.session_state.selected_record_id == rec_id)
            if c_sel.checkbox("Select", value=is_cur_selected, key=f"sel_{rec_id}", label_visibility="collapsed"):
                if not is_cur_selected:
                    st.session_state.selected_record_id = rec_id
                    st.session_state.room_val = rec["room"]
                    st.session_state.bed_val = rec["patient_id"]
                    st.session_state.sys_val = rec["systolic"]
                    st.session_state.dia_val = rec["diastolic"]
                    st.rerun()
            else:
                if is_cur_selected:
                    st.session_state.selected_record_id = None
                    st.rerun()

            # 2. Room
            c_room.markdown(f"<div style='font-size:13px; font-weight:700; padding-top:4px;'>{rec['room']}</div>", unsafe_allow_html=True)

            # 3. Patient Bed ID
            c_bed.markdown(f"<div style='font-size:13px; padding-top:4px;'>{rec['patient_id']}</div>", unsafe_allow_html=True)

            # 4. Blood Pressure
            c_bp.markdown(f"<div style='font-size:13px; font-weight:700; padding-top:4px;'>{rec['systolic']} / {rec['diastolic']} <span style='font-size:11px; font-weight:normal; color:#64748b;'>mmHg</span></div>", unsafe_allow_html=True)

            # 5. Logged Time
            c_log.markdown(f"<div style='font-size:13px; padding-top:4px;'>{rec['time_str']}</div>", unsafe_allow_html=True)

            # 6. Re-check Time
            c_rc.markdown(f"<div style='padding-top:4px;'>{recheck_display}</div>", unsafe_allow_html=True)

            # 7. Status Badge
            c_stat.markdown(f"<div style='padding-top:2px;'>{status_html}</div>", unsafe_allow_html=True)

            # 8. Notice: Auto-checks after 10s based on this specific record's timestamp
            is_noticed = rec.get("is_noticed", False)
            if is_noticed:
                notice_html = f'<div style="display:flex; justify-content:center; padding-top:4px;"><input type="checkbox" id="not_{rec_id}" checked disabled style="width: 17px; height: 17px; accent-color: #16a34a; cursor: default;"></div>'
            else:
                notice_html = f'<div style="display:flex; justify-content:center; padding-top:4px;"><input type="checkbox" id="not_{rec_id}" disabled style="width: 17px; height: 17px; cursor: default;"></div>'
            c_not.markdown(notice_html, unsafe_allow_html=True)

            # 9. Update: Checked ONLY when the record is actually updated by the nurse
            is_updated = rec.get("is_updated", False)
            if is_updated:
                update_html = f'<div style="display:flex; justify-content:center; padding-top:4px;"><input type="checkbox" id="upd_{rec_id}" checked disabled style="width: 17px; height: 17px; accent-color: #2563eb; cursor: default;"></div>'
            else:
                update_html = f'<div style="display:flex; justify-content:center; padding-top:4px;"><input type="checkbox" id="upd_{rec_id}" disabled style="width: 17px; height: 17px; cursor: default;"></div>'
            c_upd.markdown(update_html, unsafe_allow_html=True)

            # 10. Delete Button (Trash bin with confirmation)
            if c_del.button("🗑️", key=f"del_{rec_id}", help="Delete record"):
                st.session_state.confirm_delete_id = rec_id
                st.rerun()

            # Confirmation prompt if this row was marked for deletion
            if st.session_state.get("confirm_delete_id") == rec_id:
                conf_c1, conf_c2, conf_c3 = st.columns([2.5, 1, 1])
                conf_c1.warning(f"⚠️ Confirm delete **{rec['room']} / {rec['patient_id']}** ({rec['systolic']}/{rec['diastolic']} mmHg)?")
                if conf_c2.button("✔️ Yes, Delete", key=f"conf_yes_{rec_id}", type="primary"):
                    st.session_state.records = [r for r in st.session_state.records if r["episode_id"] != rec_id]
                    st.session_state.inputs.pop(pkey, None)
                    st.session_state.confirm_delete_id = None
                    if st.session_state.selected_record_id == rec_id:
                        st.session_state.selected_record_id = None
                    clear_all_selections()
                    st.rerun()
                if conf_c3.button("✖ Cancel", key=f"conf_no_{rec_id}"):
                    st.session_state.confirm_delete_id = None
                    st.rerun()

            st.html("<div style='border-bottom: 1px solid #f1f5f9; margin: 4px 0;'></div>")

        st.caption("💡 *Protocol Tracking: Notice auto-checks at 10s (bedside notification delivered). Update checks when the record is updated by the nurse.*")

    # Render the alert and table fragment
    render_alert_and_table()
