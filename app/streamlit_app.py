"""Severe Hypertension Alert System - Demonstration App.

Real-time recognition, 15-minute repeat confirmation (fast demo mode: 15m = 10s),
live flowsheet monitoring across multiple rooms and beds, and automated clinical alerts.
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Ensure repository root is on sys.path regardless of how Streamlit is invoked
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import streamlit as st
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
DEMO_COUNTDOWN_SECONDS = 10.0            # 15 minutes treated as 10 seconds for demo
DEMO_NOTICE_SECONDS = 10.0               # Notice auto-checks at 10s (bedside notification delivered)


# Session State Initialization
if "records" not in st.session_state:
    st.session_state.records = []
if "active_episodes" not in st.session_state:
    # Key: "Room / Bed", Value: dict with episode state
    st.session_state.active_episodes = {}
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


def log_reading(r_val: str, p_val: str, sys_val: int, dia_val: int, is_edit: bool = False):
    """Log or update a blood pressure measurement for a specific patient.
    
    Guarantees strict per-patient separation and eliminates duplicates:
    - If the patient already exists in the flowsheet, their vitals are updated in place.
    - If the patient is new, a separate record is created with Notice and Update starting unchecked.
    """
    is_sev = (sys_val >= SEVERE_SYS) or (dia_val >= SEVERE_DIA)
    now_time = datetime.now()
    recheck_time_str = (now_time + timedelta(minutes=15)).strftime("%H:%M:%S")
    patient_key = f"{r_val} / {p_val}"
    current_ts = time.time()

    # Locate existing patient record to prevent duplicate rows
    existing_record = None
    for r in st.session_state.records:
        if r["patient_key"] == patient_key:
            existing_record = r
            break

    existing_episode = st.session_state.active_episodes.get(patient_key)

    if existing_record is not None:
        # Existing patient -> Update vitals in place and mark Update checked
        existing_record["room"] = r_val
        existing_record["patient_id"] = p_val
        existing_record["systolic"] = int(sys_val)
        existing_record["diastolic"] = int(dia_val)
        existing_record["time_str"] = now_time.strftime("%H:%M:%S")
        existing_record["recheck_str"] = recheck_time_str
        existing_record["timestamp"] = current_ts
        existing_record["is_severe"] = is_sev
        existing_record["is_updated"] = True  # Follow-up reading / nurse update recorded
        target_rec = existing_record
    else:
        # New separate patient -> Add fresh record with its own timestamp and unchecked boxes
        new_entry = {
            "room": r_val,
            "patient_id": p_val,
            "patient_key": patient_key,
            "systolic": int(sys_val),
            "diastolic": int(dia_val),
            "time_str": now_time.strftime("%H:%M:%S"),
            "recheck_str": recheck_time_str,
            "timestamp": current_ts,
            "is_severe": is_sev,
            "countdown_start": current_ts if is_sev else None,
            "episode_id": int(time.time() * 1000) + len(st.session_state.records),
            "is_noticed": False,  # Starts unchecked; auto-checks at 10s based on this record's timer
            "is_updated": False,  # Starts unchecked; checks when updated by nurse
        }
        st.session_state.records.append(new_entry)
        target_rec = new_entry

    # Patient Episode State Machine
    if is_sev:
        if existing_episode and existing_episode.get("state") in ("REPEAT_PENDING", "REPEAT_OVERDUE"):
            # Second severe reading recorded -> Persistent Severe Hypertension confirmed!
            st.session_state.active_episodes[patient_key] = {
                "state": "CONFIRMED_SEVERE",
                "onset_ts": existing_episode.get("onset_ts", current_ts),
                "confirmed_ts": current_ts,
                "first_bp": existing_episode.get("first_bp", f"{sys_val}/{dia_val}"),
                "repeat_bp": f"{sys_val}/{dia_val}",
                "med_given": False,
                "confirmed_time_str": now_time.strftime("%H:%M:%S"),
            }
            target_rec["is_noticed"] = True
            target_rec["is_updated"] = True
        elif existing_episode and existing_episode.get("state") == "CONFIRMED_SEVERE":
            # Subsequent reading during active confirmed episode
            existing_episode["repeat_bp"] = f"{sys_val}/{dia_val}"
            target_rec["is_noticed"] = True
            target_rec["is_updated"] = True
        else:
            # First severe reading -> Starts 15-minute repeat window (10s in fast demo)
            st.session_state.active_episodes[patient_key] = {
                "state": "REPEAT_PENDING",
                "onset_ts": current_ts,
                "first_bp": f"{sys_val}/{dia_val}",
                "med_given": False,
                "onset_time_str": now_time.strftime("%H:%M:%S"),
            }
            target_rec["countdown_start"] = current_ts
    else:
        # Non-severe reading
        if existing_episode and existing_episode.get("state") in ("REPEAT_PENDING", "REPEAT_OVERDUE"):
            # Follow-up resolved
            st.session_state.active_episodes[patient_key] = {
                "state": "RESOLVED",
                "resolved_ts": current_ts,
                "first_bp": existing_episode.get("first_bp", "168/112"),
                "repeat_bp": f"{sys_val}/{dia_val}",
                "resolved_time_str": now_time.strftime("%H:%M:%S"),
            }
            target_rec["is_updated"] = True
        elif existing_episode and existing_episode.get("state") == "CONFIRMED_SEVERE":
            pass
        else:
            # Normal routine monitoring for this patient
            if patient_key in st.session_state.active_episodes:
                del st.session_state.active_episodes[patient_key]


def fill_test_case(r_val: str, p_val: str, s_val: int, d_val: int):
    """Fill form inputs from Quick Test Case button. Clears active selection."""
    clear_all_selections()
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
    st.session_state.active_episodes = {}
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
        args=("Room 105", "Bed-02", 120, 78),
    )

    st.markdown("---")
    # Action Buttons: Edit Mode vs Standard Logging Mode
    if st.session_state.selected_record_id is not None:
        btn_c1, btn_c2, btn_c3 = st.columns([1.5, 1.4, 1])
        if btn_c1.button("💾 Save Update", type="primary", use_container_width=True):
            target_id = st.session_state.selected_record_id
            for r in st.session_state.records:
                if r["episode_id"] == target_id:
                    r["room"] = str(st.session_state.room_val).strip() or "Room 302"
                    r["patient_id"] = str(st.session_state.bed_val).strip() or "Bed-04"
                    r["patient_key"] = f"{r['room']} / {r['patient_id']}"
                    r["systolic"] = int(st.session_state.sys_val)
                    r["diastolic"] = int(st.session_state.dia_val)
                    is_sev = (r["systolic"] >= SEVERE_SYS) or (r["diastolic"] >= SEVERE_DIA)
                    r["is_severe"] = is_sev
                    r["time_str"] = datetime.now().strftime("%H:%M:%S")
                    r["recheck_str"] = (datetime.now() + timedelta(minutes=15)).strftime("%H:%M:%S")
                    r["timestamp"] = time.time()
                    r["is_updated"] = True

                    # Update episode state if severe
                    ep = st.session_state.active_episodes.get(r["patient_key"])
                    if is_sev:
                        if ep and ep.get("state") in ("REPEAT_PENDING", "REPEAT_OVERDUE"):
                            ep["state"] = "CONFIRMED_SEVERE"
                            ep["repeat_bp"] = f"{r['systolic']}/{r['diastolic']}"
                            r["is_noticed"] = True
                        else:
                            st.session_state.active_episodes[r["patient_key"]] = {
                                "state": "REPEAT_PENDING",
                                "onset_ts": time.time(),
                                "first_bp": f"{r['systolic']}/{r['diastolic']}",
                                "med_given": False,
                                "onset_time_str": datetime.now().strftime("%H:%M:%S"),
                            }
                    else:
                        if ep and ep.get("state") in ("REPEAT_PENDING", "REPEAT_OVERDUE"):
                            ep["state"] = "RESOLVED"
                            ep["resolved_ts"] = time.time()
                            ep["repeat_bp"] = f"{r['systolic']}/{r['diastolic']}"
                            ep["resolved_time_str"] = datetime.now().strftime("%H:%M:%S")
                        elif r["patient_key"] in st.session_state.active_episodes:
                            del st.session_state.active_episodes[r["patient_key"]]
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

        # Check automated protocol tracking (Notice auto-checks at 10s) per individual record
        for r in st.session_state.records:
            elapsed = current_time_sec - r["timestamp"]
            if elapsed >= DEMO_NOTICE_SECONDS:
                r["is_noticed"] = True

        # Check severe countdowns across active episodes for each individual patient
        for pkey, ep in list(st.session_state.active_episodes.items()):
            if ep.get("state") == "REPEAT_PENDING":
                elapsed = current_time_sec - ep.get("onset_ts", 0)
                if elapsed >= DEMO_COUNTDOWN_SECONDS:
                    ep["state"] = "REPEAT_OVERDUE"
                    for r in st.session_state.records:
                        if r["patient_key"] == pkey:
                            r["is_noticed"] = True

        # ---------------------------------------------------------------------
        # 1. TOP-RIGHT ALERT SPACE: Evaluates Highest Priority Clinical Alert
        # ---------------------------------------------------------------------
        alert_info = None

        # Priority 1: Persistent Severe Hypertension Confirmed
        for pkey, ep in st.session_state.active_episodes.items():
            if ep.get("state") == "CONFIRMED_SEVERE":
                alert_info = {
                    "level": "CONFIRMED",
                    "patient_key": pkey,
                    "title": f"PERSISTENT SEVERE HYPERTENSION CONFIRMED: {pkey}",
                    "detail": (
                        f"Repeat severe reading {ep.get('repeat_bp', '')} mmHg recorded within repeat confirmation window! "
                        f"First-line IV labetalol / IV hydralazine / oral nifedipine required within 60 minutes of onset."
                    ),
                    "timestamp": ep.get("confirmed_time_str", datetime.now().strftime("%H:%M:%S")),
                    "ep_ref": ep,
                }
                break

        # Priority 2: Repeat Blood Pressure Overdue
        if not alert_info:
            for pkey, ep in st.session_state.active_episodes.items():
                if ep.get("state") == "REPEAT_OVERDUE":
                    alert_info = {
                        "level": "OVERDUE",
                        "patient_key": pkey,
                        "title": f"REPEAT BLOOD PRESSURE DUE / OVERDUE: {pkey}",
                        "detail": (
                            f"15-Minute confirmation window reached without repeat check! "
                            f"Persistent severe hypertension assumed per SMFM missing recheck protocol rule."
                        ),
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "ep_ref": ep,
                    }
                    break

        # Priority 3: Severe Onset / Repeat Pending (Countdown running)
        if not alert_info:
            for pkey, ep in st.session_state.active_episodes.items():
                if ep.get("state") == "REPEAT_PENDING":
                    rem_sec = max(0.0, DEMO_COUNTDOWN_SECONDS - (current_time_sec - ep.get("onset_ts", 0)))
                    alert_info = {
                        "level": "SEVERE_FIRST",
                        "patient_key": pkey,
                        "title": f"CRITICAL SEVERE ALERT: {pkey}",
                        "detail": (
                            f"Severe blood pressure {ep.get('first_bp', '')} mmHg detected (≥160/110 threshold). "
                            f"15-Minute repeat measurement confirmation active ({rem_sec:.1f}s remaining in demo mode)."
                        ),
                        "timestamp": ep.get("onset_time_str", datetime.now().strftime("%H:%M:%S")),
                        "ep_ref": ep,
                    }
                    break

        # Priority 4: Recently Resolved Episode
        if not alert_info:
            for pkey, ep in st.session_state.active_episodes.items():
                if ep.get("state") == "RESOLVED":
                    if (current_time_sec - ep.get("resolved_ts", 0)) < 15.0:
                        alert_info = {
                            "level": "RESOLVED",
                            "patient_key": pkey,
                            "title": f"EPISODE RESOLVED: {pkey}",
                            "detail": f"Follow-up reading {ep.get('repeat_bp', '')} mmHg returned to non-severe reference range.",
                            "timestamp": ep.get("resolved_time_str", datetime.now().strftime("%H:%M:%S")),
                            "ep_ref": ep,
                        }
                        break

        # Render Alert Banner
        if alert_info and alert_info["level"] == "CONFIRMED":
            pkey = alert_info["patient_key"]
            ep = alert_info["ep_ref"]
            st.html(f"""<div class="alert-box-severe">
                <div style="font-size: 16px; font-weight: 800; display: flex; align-items: center; gap: 8px;">
                    <span>🚨</span>
                    <span>{alert_info['title']}</span>
                </div>
                <div style="font-size: 13.5px; margin-top: 6px; font-weight: 500; line-height: 1.45;">
                    {alert_info['detail']}
                </div>
                <div style="font-size: 11.5px; color: #b91c1c; margin-top: 4px; font-weight: 600;">
                    Alert Time: {alert_info['timestamp']} &bull; Speed Mode: 15 min = 10s &bull; Medication Target: &le;60 min
                </div>
            </div>""")

            # Interactive Medication Administration & EMR Documentation
            act_col1, act_col2 = st.columns(2)
            if not ep.get("med_given"):
                if act_col1.button("💊 Record Medication Dose", use_container_width=True, type="secondary"):
                    ep["med_given"] = True
                    ep["med_time"] = datetime.now().strftime("%H:%M:%S")
                    st.rerun()
            else:
                act_col1.success(f"✅ Dose Given: IV Labetalol 20mg ({ep.get('med_time')})")

            with act_col2.popover("📋 AI-Drafted EMR Note", use_container_width=True):
                st.markdown("**AI-Drafted EMR Nursing Documentation (Traceable SBAR)**")
                st.caption("*Generated strictly outside the safety loop for post-event documentation.*")
                onset_str = ep.get("first_bp", "168/112")
                rpt_str = ep.get("repeat_bp", "162/108")
                t_str = alert_info['timestamp']
                med_line = f"- {ep.get('med_time')}: Antihypertensive medication dose recorded (IV Labetalol 20mg)." if ep.get("med_given") else "- Pending: First-line antihypertensive administration."
                st.code(f"""EMR Bedside Nursing Note — Patient: {pkey}
Clinical Event Timeline:
- {t_str}: Initial severe blood pressure recorded ({onset_str} mmHg). Episode opened.
- {t_str}: Scheduled repeat blood pressure due within 15-minute window.
- {t_str}: Confirmed persistent severe blood pressure ({rpt_str} mmHg). Provider notified.
{med_line}
Documentation Status: Draft entry prepared for nurse review and verification. Zero hallucinated tokens.""", language="markdown")

        elif alert_info and alert_info["level"] in ("SEVERE_FIRST", "OVERDUE"):
            st.html(f"""<div class="alert-box-severe">
                <div style="font-size: 16px; font-weight: 800; display: flex; align-items: center; gap: 8px;">
                    <span>🚨</span>
                    <span>{alert_info['title']}</span>
                </div>
                <div style="font-size: 13.5px; margin-top: 6px; font-weight: 500; line-height: 1.45;">
                    {alert_info['detail']}
                </div>
                <div style="font-size: 11.5px; color: #b91c1c; margin-top: 4px; font-weight: 600;">
                    Alert Time: {alert_info['timestamp']} &bull; Speed Mode: 15 min = 10s
                </div>
            </div>""")
        elif alert_info and alert_info["level"] == "RESOLVED":
            st.html(f"""<div class="alert-box-normal">
                <div style="font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px;">
                    <span>🟢</span>
                    <span>{alert_info['title']}</span>
                </div>
                <div style="font-size: 13px; margin-top: 4px;">
                    {alert_info['detail']} (Logged at {alert_info['timestamp']})
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
            ep = st.session_state.active_episodes.get(pkey, {})
            ep_state = ep.get("state", "NONE")

            # Determine Re-check Time
            if rec.get("recheck_str") and rec["recheck_str"] != "—":
                recheck_val = rec["recheck_str"]
            else:
                recheck_val = (datetime.fromtimestamp(rec["timestamp"]) + timedelta(minutes=15)).strftime("%H:%M:%S")

            if rec["is_severe"]:
                recheck_display = f'<strong style="color: #dc2626; font-size: 13px;">{recheck_val}</strong>'
                if ep_state == "CONFIRMED_SEVERE":
                    status_html = '<span class="badge-severe">🚨 Confirmed</span>'
                elif ep_state == "REPEAT_PENDING":
                    status_html = '<span class="badge-severe">🟡 Repeat Due</span>'
                elif ep_state == "REPEAT_OVERDUE":
                    status_html = '<span class="badge-severe">🟠 Overdue</span>'
                else:
                    status_html = '<span class="badge-severe">🟡 Severe</span>'
            else:
                recheck_display = f'<strong style="font-size: 13px;">{recheck_val}</strong>'
                if ep_state == "RESOLVED":
                    status_html = '<span class="badge-normal">🟢 Resolved</span>'
                else:
                    status_html = '<span class="badge-normal">🟢 Normal</span>'

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
                    if pkey in st.session_state.active_episodes:
                        del st.session_state.active_episodes[pkey]
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
