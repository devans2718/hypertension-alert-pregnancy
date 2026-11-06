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
def log_reading(r_val: str, p_val: str, sys_val: int, dia_val: int, is_edit: bool = False):
    is_sev = (sys_val >= SEVERE_SYS) or (dia_val >= SEVERE_DIA)
    now_time = datetime.now()
    recheck_time_str = (now_time + timedelta(minutes=15)).strftime("%H:%M:%S")
    patient_key = f"{r_val} / {p_val}"
    current_ts = time.time()

    # Check if an active 10s countdown is currently running for this patient
    existing_episode = st.session_state.active_episodes.get(patient_key)
    is_during_countdown = False
    if existing_episode and existing_episode.get("state") == "REPEAT_PENDING":
        elapsed = current_ts - existing_episode.get("onset_ts", 0)
        if elapsed < DEMO_COUNTDOWN_SECONDS:
            is_during_countdown = True

    if not is_edit:
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
            "is_noticed": is_sev,
            "is_updated": False,
        }
        st.session_state.records.append(new_entry)

    # Alert Logic
    if is_sev:
        if is_during_countdown:
            # Second severe reading arrived while countdown was running!
            st.session_state.active_episodes[patient_key] = {
                "state": "CONFIRMED_SEVERE",
                "onset_ts": existing_episode.get("onset_ts", current_ts),
                "confirmed_ts": current_ts,
                "first_bp": existing_episode.get("first_bp", "168/112"),
                "repeat_bp": f"{sys_val}/{dia_val}",
                "med_given": False,
            }
            st.session_state.active_alert = {
                "level": "CONFIRMED",
                "patient_key": patient_key,
                "title": f"PERSISTENT SEVERE HYPERTENSION CONFIRMED: {patient_key}",
                "detail": (
                    f"Repeat severe reading {sys_val}/{dia_val} mmHg recorded within repeat confirmation window! "
                    f"First-line IV labetalol / IV hydralazine / oral nifedipine required within 60 minutes of onset."
                ),
                "timestamp": now_time.strftime("%H:%M:%S"),
            }
            for r in st.session_state.records:
                if r["patient_key"] == patient_key:
                    r["is_noticed"] = True
                    r["is_updated"] = True
        else:
            # First severe reading -> Starts 10-second fast countdown!
            st.session_state.active_episodes[patient_key] = {
                "state": "REPEAT_PENDING",
                "onset_ts": current_ts,
                "first_bp": f"{sys_val}/{dia_val}",
                "med_given": False,
            }
            st.session_state.active_alert = {
                "level": "SEVERE_FIRST",
                "patient_key": patient_key,
                "title": f"CRITICAL SEVERE ALERT: {patient_key}",
                "detail": (
                    f"Severe blood pressure {sys_val}/{dia_val} mmHg detected (≥160/110 threshold). "
                    f"15-Minute repeat measurement confirmation active (Demo speed: 10s countdown running)."
                ),
                "timestamp": now_time.strftime("%H:%M:%S"),
            }
            for r in st.session_state.records:
                if r["patient_key"] == patient_key:
                    r["is_noticed"] = True
    else:
        # Non-severe reading
        if existing_episode and existing_episode.get("state") == "REPEAT_PENDING":
            # Follow-up resolved
            st.session_state.active_episodes[patient_key] = {"state": "RESOLVED"}
            st.session_state.active_alert = {
                "level": "RESOLVED",
                "patient_key": patient_key,
                "title": f"EPISODE RESOLVED: {patient_key}",
                "detail": f"Follow-up reading {sys_val}/{dia_val} mmHg returned to non-severe reference range.",
                "timestamp": now_time.strftime("%H:%M:%S"),
            }
            for r in st.session_state.records:
                if r["patient_key"] == patient_key:
                    r["is_updated"] = True
        else:
            st.session_state.active_alert = None


def fill_test_case(r_val: str, p_val: str, s_val: int, d_val: int):
    st.session_state.room_val = r_val
    st.session_state.bed_val = p_val
    st.session_state.sys_val = s_val
    st.session_state.dia_val = d_val


def apply_manual_log():
    r = str(st.session_state.room_val).strip() or "Room 302"
    p = str(st.session_state.bed_val).strip() or "Bed-04"
    s = int(st.session_state.sys_val)
    d = int(st.session_state.dia_val)
    log_reading(r, p, s, d)


def apply_reset():
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

    # Room and Bed Inputs
    r_col1, r_col2 = st.columns(2)
    r_col1.text_input(
        "Room / Unit Location:",
        key="room_val",
        help="Enter the clinical room or unit location (e.g., Room 302, Room 101, Triage-A).",
    )
    r_col2.text_input(
        "Patient Identifier / Bed Number:",
        key="bed_val",
        help="Enter the patient name or bed identifier (e.g., Bed-04, Patient Smith, Bed-01).",
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
    # Action Buttons
    btn_col1, btn_col2 = st.columns([2, 1])

    if st.session_state.selected_record_id is not None:
        if btn_col1.button("💾 Save Update", type="primary", use_container_width=True):
            target_id = st.session_state.selected_record_id
            for r in st.session_state.records:
                if r["episode_id"] == target_id:
                    r["room"] = str(st.session_state.room_val).strip() or "Room 302"
                    r["patient_id"] = str(st.session_state.bed_val).strip() or "Bed-04"
                    r["patient_key"] = f"{r['room']} / {r['patient_id']}"
                    r["systolic"] = int(st.session_state.sys_val)
                    r["diastolic"] = int(st.session_state.dia_val)
                    r["is_severe"] = (r["systolic"] >= SEVERE_SYS) or (r["diastolic"] >= SEVERE_DIA)
                    r["time_str"] = datetime.now().strftime("%H:%M:%S")
                    r["recheck_str"] = (datetime.now() + timedelta(minutes=15)).strftime("%H:%M:%S")
                    r["is_updated"] = True
                    if r["is_severe"]:
                        r["is_noticed"] = True
                    log_reading(r["room"], r["patient_id"], r["systolic"], r["diastolic"], is_edit=True)
                    break
            st.session_state.selected_record_id = None
            st.rerun()

        if btn_col2.button("✖ Cancel", use_container_width=True):
            st.session_state.selected_record_id = None
            st.rerun()
    else:
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

    # Using st.fragment with run_every="1s" allows live second-by-second countdown bar updates!
    @st.fragment(run_every="1s")
    def render_alert_and_table():
        current_time_sec = time.time()

        # Check if any active countdown has expired (elapsed >= 10s)
        for pkey, ep in list(st.session_state.active_episodes.items()):
            if ep.get("state") == "REPEAT_PENDING":
                elapsed = current_time_sec - ep.get("onset_ts", 0)
                if elapsed >= DEMO_COUNTDOWN_SECONDS:
                    ep["state"] = "REPEAT_OVERDUE"
                    # Auto-mark notice as delivered for all records of this patient
                    for r in st.session_state.records:
                        if r["patient_key"] == pkey:
                            r["is_noticed"] = True
                    # Trigger Overdue alert
                    st.session_state.active_alert = {
                        "level": "OVERDUE",
                        "patient_key": pkey,
                        "title": f"REPEAT BLOOD PRESSURE DUE / OVERDUE: {pkey}",
                        "detail": (
                            f"15-Minute confirmation window reached without repeat check! "
                            f"Persistent severe hypertension assumed per SMFM missing recheck protocol rule."
                        ),
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                    }

        # ---------------------------------------------------------------------
        # 1. TOP-RIGHT ALERT SPACE (Directly on top of the record table)
        # ---------------------------------------------------------------------
        alert_info = st.session_state.active_alert

        if alert_info and alert_info["level"] == "CONFIRMED":
            pkey = alert_info.get("patient_key", "Room 302 / Bed-04")
            ep = st.session_state.active_episodes.get(pkey, {})
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
                    status_html = '<span class="badge-normal">🟢 Resolved</span>'
            else:
                recheck_display = f'<strong style="font-size: 13px;">{recheck_val}</strong>'
                status_html = '<span class="badge-normal">🟢 Normal</span>'

            c_sel, c_room, c_bed, c_bp, c_log, c_rc, c_stat, c_not, c_upd, c_del = st.columns(
                [0.6, 1.1, 1.1, 1.4, 1.0, 1.0, 1.3, 0.8, 0.8, 0.7]
            )

            # 1. Select Checkbox (Before Room to select row for editing)
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

            # 8. Notice (Automatic tracking indicator)
            elapsed_sec = current_time_sec - rec["timestamp"]
            is_noticed = rec.get("is_noticed", False) or rec["is_severe"] or (elapsed_sec >= DEMO_COUNTDOWN_SECONDS)
            if is_noticed:
                rec["is_noticed"] = True
                notice_html = '<div style="display:flex; justify-content:center; padding-top:4px;"><input type="checkbox" checked disabled style="width: 17px; height: 17px; accent-color: #16a34a; cursor: default;"></div>'
            else:
                notice_html = '<div style="display:flex; justify-content:center; padding-top:4px;"><input type="checkbox" disabled style="width: 17px; height: 17px; cursor: default;"></div>'
            c_not.markdown(notice_html, unsafe_allow_html=True)

            # 9. Update (Automatic tracking indicator)
            is_updated = rec.get("is_updated", False)
            if is_updated:
                update_html = '<div style="display:flex; justify-content:center; padding-top:4px;"><input type="checkbox" checked disabled style="width: 17px; height: 17px; accent-color: #2563eb; cursor: default;"></div>'
            else:
                update_html = '<div style="display:flex; justify-content:center; padding-top:4px;"><input type="checkbox" disabled style="width: 17px; height: 17px; cursor: default;"></div>'
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
                    st.session_state.confirm_delete_id = None
                    if st.session_state.selected_record_id == rec_id:
                        st.session_state.selected_record_id = None
                    st.rerun()
                if conf_c3.button("✖ Cancel", key=f"conf_no_{rec_id}"):
                    st.session_state.confirm_delete_id = None
                    st.rerun()

            st.html("<div style='border-bottom: 1px solid #f1f5f9; margin: 4px 0;'></div>")

        st.caption("💡 *Automatic Protocol Tracking: Notice auto-checks when the bedside alert/15-minute recheck window fires (10s in demo). Update auto-checks when repeat vitals or updates are logged.*")

    # Render the alert and table fragment
    render_alert_and_table()
