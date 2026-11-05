"""Labor and Delivery Severe Hypertension Alert System - Demonstration App.

A research prototype exploring timely recognition, bedside repeat confirmation,
countdown tracking, and autonomous downstream communication workflows on L&D units.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure repository root is on sys.path regardless of how Streamlit is invoked
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd
import streamlit as st

from app.adapters import load_baseline_records, project_record_to_readings
from app.playback import (
    EpisodePhase,
    calculate_countdown,
    evaluate_playback_episode,
    filter_readings_up_to,
    generate_sbar_handoff,
)
from app.scenarios import get_default_scenarios
from htn_alert.contract import Reading
from htn_alert.protocol import load_protocol
from htn_alert.rules import is_severe

# Page Configuration
st.set_page_config(
    page_title="L&D Severe HTN Alert System",
    page_icon="🩺",
    layout="wide",
)

protocol = load_protocol()

# Session State Initialization
if "readings_history" not in st.session_state:
    st.session_state.readings_history = []
if "current_patient_id" not in st.session_state:
    st.session_state.current_patient_id = "Bed-04"
if "episode_start_time" not in st.session_state:
    st.session_state.episode_start_time = None
if "replay_minute" not in st.session_state:
    st.session_state.replay_minute = 0


# Header
st.title("🩺 L&D Severe Hypertension Alert System")
st.caption(
    "Research prototype. Not a medical device and not for clinical use. "
    "Designed for the Hack-A-Roo Fall 2026 Pitch-to-Build track."
)

# Sidebar: Protocol Configuration & Mode Selection
with st.sidebar:
    st.header("⚙️ Protocol Rules (ACOG/SMFM)")
    st.info(
        f"**Severe Thresholds:**\n"
        f"- Systolic: ≥ {protocol.severe_systolic} mmHg\n"
        f"- Diastolic: ≥ {protocol.severe_diastolic} mmHg\n\n"
        f"**Timelines:**\n"
        f"- Repeat Window: {int(protocol.repeat_min.total_seconds() // 60)}–{int(protocol.repeat_max.total_seconds() // 60)} min\n"
        f"- Medication Target: ≤ {int(protocol.treatment_target.total_seconds() // 60)} min\n"
        f"- Escalation Delay: {int(protocol.escalate_unacknowledged.total_seconds() // 60)} min"
    )

    st.markdown("---")
    app_mode = st.radio(
        "Select Workflow Mode:",
        [
            "👩‍⚕️ Nurse Bedside Entry & Countdown",
            "⏱️ Replay Readings & Scenarios",
            "📊 Open Benchmark Data Explorer",
        ],
    )


# -----------------------------------------------------------------------------
# MODE 1: Nurse Bedside Entry & 15-Minute Countdown
# -----------------------------------------------------------------------------
if app_mode == "👩‍⚕️ Nurse Bedside Entry & Countdown":
    st.subheader("Bedside Blood Pressure Entry & Active Episode Monitor")

    col_entry, col_status = st.columns([1, 1], gap="large")

    with col_entry:
        st.markdown("### 📝 Bedside Vital Signs Entry")

        patient_id = st.text_input(
            "Patient Identifier / Bed Number",
            value=st.session_state.current_patient_id,
        )
        st.session_state.current_patient_id = patient_id

        # Quick Test Case Prefill Buttons
        st.write("**Quick-Fill Clinical Test Cases:**")
        qcol1, qcol2 = st.columns(2)
        if qcol1.button("🟡 1. Severe Onset (168/112)"):
            st.session_state.sys_val = 168
            st.session_state.dia_val = 112
            st.session_state.sim_delta_val = 0
        if qcol2.button("🟢 2. Normal Routine (120/78)"):
            st.session_state.sys_val = 120
            st.session_state.dia_val = 78
            st.session_state.sim_delta_val = 0

        sys_default = st.session_state.get("sys_val", 120)
        dia_default = st.session_state.get("dia_val", 80)
        delta_default = st.session_state.get("sim_delta_val", 0)

        systolic = st.number_input("Systolic BP (mmHg)", min_value=60, max_value=260, value=sys_default, step=1)
        diastolic = st.number_input("Diastolic BP (mmHg)", min_value=40, max_value=160, value=dia_default, step=1)

        sim_delta = st.number_input(
            "Simulate reading at +N minutes from first check:",
            min_value=0,
            max_value=120,
            value=delta_default,
            step=1,
        )

        if st.button("➕ Log Blood Pressure Reading", type="primary", use_container_width=True):
            if not st.session_state.readings_history:
                base = datetime.now()
                st.session_state.episode_start_time = base
            else:
                base = st.session_state.episode_start_time

            reading_time = base + timedelta(minutes=sim_delta)
            new_reading = Reading(
                patient_id=patient_id,
                time=reading_time,
                systolic=int(systolic),
                diastolic=int(diastolic),
            )
            st.session_state.readings_history.append(new_reading)
            st.success(f"Logged {systolic}/{diastolic} mmHg at {reading_time.strftime('%H:%M:%S')}")

        if st.button("🔄 Reset Patient Episode", use_container_width=True):
            st.session_state.readings_history = []
            st.session_state.episode_start_time = None
            st.session_state.sim_elapsed_val = 0
            st.rerun()

    with col_status:
        st.markdown("### 🔔 Clinical Protocol Status & Countdown")

        readings = st.session_state.readings_history
        if not readings:
            st.info("No blood pressure readings logged yet. Enter a reading on the left to begin.")
        else:
            now_clock = readings[-1].time
            status = evaluate_playback_episode(readings, protocol, simulated_now=now_clock)

            # Render Status Card
            if status.phase == EpisodePhase.ROUTINE_DUE:
                st.info("🔔 **15-MINUTE NURSE NOTICE: ROUTINE RE-CHECK DUE**")
                st.markdown(
                    "15 minutes have elapsed since the baseline normal check. "
                    "Notice to nurse: please conduct scheduled vital signs re-assessment."
                )
                st.write(status.detail)

            elif status.phase == EpisodePhase.NONE:
                st.success("🟢 **BP Within Target Limits** — Normal vital signs. Routine monitoring continues.")

            elif status.phase == EpisodePhase.REPEAT_PENDING:
                st.warning("🟡 **FIRST SEVERE READING DETECTED — 15-MINUTE REPEAT COUNTDOWN ACTIVE**")
                st.write(status.detail)

                if status.repeat_target_time:
                    rem_sec, is_overdue, display_str = calculate_countdown(status.repeat_target_time, now_clock)
                    progress = max(0.0, min(1.0, 1.0 - (rem_sec / 900.0)))

                    c_m1, c_m2 = st.columns(2)
                    c_m1.metric("Countdown to Repeat BP", display_str)
                    c_m2.metric("Target Repeat Time", status.repeat_target_time.strftime("%H:%M"))
                    st.progress(progress, text="15-minute repeat measurement confirmation window")

            elif status.phase == EpisodePhase.REPEAT_DUE:
                st.error("🔴 **REPEAT BP OVERDUE** — Recheck is required immediately to confirm persistence!")
                st.write(status.detail)
                if status.repeat_target_time:
                    _, _, display_str = calculate_countdown(status.repeat_target_time, now_clock)
                    st.metric("Time Overdue", display_str)

            elif status.phase == EpisodePhase.CONFIRMED:
                st.error("🚨 **PERSISTENT SEVERE HYPERTENSION CONFIRMED**")
                st.write(status.detail)

                if status.treatment_target_time:
                    rem_sec, is_overdue, display_str = calculate_countdown(status.treatment_target_time, now_clock)
                    t_prog = max(0.0, min(1.0, 1.0 - (rem_sec / 3600.0)))
                    st.metric("60-Min Medication Target Countdown", display_str)
                    st.progress(t_prog, text="National 60-minute time-to-treatment standard (from onset)")

            elif status.phase == EpisodePhase.RESOLVED:
                st.success("🟢 **EPISODE RESOLVED (UNCONFIRMED)**")
                st.write(status.detail)

            # Downstream Agentic Communication
            if status.phase == EpisodePhase.CONFIRMED:
                st.markdown("---")
                st.markdown("### 🤖 Autonomous Agent Downstream Communication")
                sbar_text = generate_sbar_handoff(patient_id, status, readings)
                st.markdown(sbar_text)

                b_col1, b_col2 = st.columns(2)
                if b_col1.button("📲 Transmit SBAR to On-Call OBGYN", use_container_width=True):
                    st.toast("✅ SBAR alert transmitted to attending physician pager/EHR.")
                if b_col2.button("💊 Log Antihypertensive Administered", use_container_width=True):
                    st.toast("✅ Medication administered; treatment target achieved.")

            # Table of readings
            st.markdown("---")
            st.write("**Reading History:**")
            df = pd.DataFrame([
                {
                    "Bed / Patient": r.patient_id,
                    "Entry Time": r.time.strftime("%H:%M:%S"),
                    "15' Re-check Time": (r.time + timedelta(minutes=15)).strftime("%H:%M:%S"),
                    "Systolic (mmHg)": r.systolic,
                    "Diastolic (mmHg)": r.diastolic,
                    "Severe?": "🚨 Yes" if is_severe(r, protocol) else "No",
                }
                for r in readings
            ])
            st.dataframe(df, use_container_width=True, hide_index=True)


# -----------------------------------------------------------------------------
# MODE 2: Replay Readings & Scenarios (Issue #8)
# -----------------------------------------------------------------------------
elif app_mode == "⏱️ Replay Readings & Scenarios":
    st.subheader("Replay Readings Over Time & Scenario Simulation")
    st.write(
        "Demonstrates Issue #8 playback capabilities: scrub through time-series readings, "
        "observe countdown transitions, and inspect automated alerting."
    )

    base_time = datetime(2026, 10, 31, 10, 0)
    scenarios = get_default_scenarios(base_time)
    scenario_map = {s.name: s for s in scenarios}

    selected_name = st.selectbox("Select Test Scenario:", list(scenario_map.keys()))
    scenario = scenario_map[selected_name]

    st.markdown(f"**Scenario Description:** {scenario.description}")
    st.markdown(f"**Expected Outcome:** `{scenario.expected_outcome}`")

    # Time Scrubber
    st.markdown("---")
    max_minutes = 70
    minute_val = st.slider(
        "⏱️ Replay Timeline (Simulated Minutes from T=0):",
        min_value=0,
        max_value=max_minutes,
        value=st.session_state.replay_minute,
        step=1,
    )
    st.session_state.replay_minute = minute_val

    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 4])
    if col_btn1.button("⏪ Reset (T=0)"):
        st.session_state.replay_minute = 0
        st.rerun()
    if col_btn2.button("⏩ Step (+5 min)"):
        st.session_state.replay_minute = min(max_minutes, st.session_state.replay_minute + 5)
        st.rerun()

    simulated_now = base_time + timedelta(minutes=minute_val)
    st.markdown(f"**Virtual Clock:** `{simulated_now.strftime('%H:%M')} (T + {minute_val} min)`")

    # Filter visible readings
    visible_readings = filter_readings_up_to(scenario.readings, simulated_now)
    status = evaluate_playback_episode(visible_readings, protocol, simulated_now=simulated_now)

    r_col1, r_col2 = st.columns([1, 1], gap="large")

    with r_col1:
        st.markdown("### 📊 Vital Signs Timeline")
        all_df = pd.DataFrame([
            {
                "Elapsed Min": int((r.time - base_time).total_seconds() // 60),
                "Time": r.time.strftime("%H:%M"),
                "Systolic": r.systolic,
                "Diastolic": r.diastolic,
                "Visible": "✅ Arrived" if r.time <= simulated_now else "⏳ Future",
            }
            for r in scenario.readings
        ])
        st.dataframe(all_df, use_container_width=True)

        # Plot blood pressure chart
        chart_df = pd.DataFrame({
            "Elapsed Min": [int((r.time - base_time).total_seconds() // 60) for r in scenario.readings],
            "Systolic": [r.systolic for r in scenario.readings],
            "Diastolic": [r.diastolic for r in scenario.readings],
        }).set_index("Elapsed Min")
        st.line_chart(chart_df)

    with r_col2:
        st.markdown("### 🔔 Active Protocol Alerts at Current Minute")

        if status.phase == EpisodePhase.ROUTINE_DUE:
            st.info("🔔 Status: 15-Minute Routine Vital Re-check Notice to Nurse.")
        elif status.phase == EpisodePhase.NONE:
            st.success("🟢 Status: Normal reference range.")
        elif status.phase == EpisodePhase.REPEAT_PENDING:
            st.warning("🟡 Status: First severe reading recorded. 15-minute countdown active.")
            if status.repeat_target_time:
                _, _, disp = calculate_countdown(status.repeat_target_time, simulated_now)
                st.metric("Repeat Due In", disp)
        elif status.phase == EpisodePhase.REPEAT_DUE:
            st.error("🔴 Status: Repeat BP overdue!")
            if status.repeat_target_time:
                _, _, disp = calculate_countdown(status.repeat_target_time, simulated_now)
                st.metric("Time Overdue", disp)
        elif status.phase == EpisodePhase.CONFIRMED:
            st.error("🚨 Status: Persistent severe hypertension confirmed.")
            if status.treatment_target_time:
                _, _, disp = calculate_countdown(status.treatment_target_time, simulated_now)
                st.metric("Time to 60-min Treatment Deadline (from onset)", disp)
        elif status.phase == EpisodePhase.RESOLVED:
            st.success("🟢 Status: Episode resolved (non-severe repeat).")
        elif status.phase == EpisodePhase.EXPIRED:
            st.info("⚪ Status: Repeat window expired without confirmation.")

        st.write(f"**Detail:** {status.detail}")

        if status.phase == EpisodePhase.CONFIRMED:
            st.markdown("---")
            st.markdown("#### 🤖 Downstream Autonomous Notification")
            st.markdown(generate_sbar_handoff(scenario.readings[0].patient_id, status, visible_readings))


# -----------------------------------------------------------------------------
# MODE 3: Open Benchmark Data Explorer
# -----------------------------------------------------------------------------
else:
    st.subheader("Open Clinical Benchmark Dataset Explorer")
    st.write(
        "Grounding the prototype in open, de-identified maternal health benchmark data "
        "([UCI / Kaggle Maternal Health Risk Dataset](https://archive.ics.uci.edu/dataset/863/maternal+health+risk))."
    )

    records = load_baseline_records()
    if not records:
        st.error("No benchmark records found at data/public_baseline.csv.")
    else:
        st.write(f"Total benchmark records loaded: **{len(records)}**")

        risk_filter = st.multiselect(
            "Filter by Risk Category:",
            options=["high risk", "mid risk", "low risk"],
            default=["high risk", "mid risk", "low risk"],
        )

        filtered = [r for r in records if r.risk_level in risk_filter]

        df_records = pd.DataFrame([
            {
                "Row": r.row_id,
                "Age": r.age,
                "Systolic BP": r.systolic,
                "Diastolic BP": r.diastolic,
                "Heart Rate": r.heart_rate,
                "Blood Sugar (mmol/L)": r.blood_sugar,
                "Body Temp (°F)": r.body_temp,
                "Risk Level": r.risk_level,
            }
            for r in filtered
        ])

        st.dataframe(df_records, use_container_width=True, height=400)

        st.markdown("### 📥 Test a Benchmark Row in Bedside Entry")
        row_choice = st.selectbox(
            "Select a benchmark record to load into the Nurse Bedside Entry form:",
            options=[r.row_id for r in filtered[:50]],
            format_func=lambda rid: f"Row #{rid}: {next(r.systolic for r in filtered if r.row_id == rid)}/{next(r.diastolic for r in filtered if r.row_id == rid)} mmHg ({next(r.risk_level for r in filtered if r.row_id == rid)})",
        )

        if st.button("Load Selected Patient into Bedside Workflow"):
            chosen = next(r for r in filtered if r.row_id == row_choice)
            st.session_state.sys_val = chosen.systolic
            st.session_state.dia_val = chosen.diastolic
            st.session_state.current_patient_id = f"Bench-{chosen.row_id}"
            st.success(f"Loaded Row #{chosen.row_id} (BP: {chosen.systolic}/{chosen.diastolic} mmHg) into Nurse Bedside Entry! Switch to the Bedside tab to test.")
