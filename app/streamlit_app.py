"""Labor and Delivery Severe Hypertension Alert System - Demonstration App.

A research prototype exploring timely recognition, bedside repeat confirmation,
EpisodeTracker-driven event processing, AI-drafted EMR documentation with traceability,
and unit-wide patient replay.

Research prototype. Not a medical device and not for clinical use.
Designed for the Hack-A-Roo Fall 2026 Pitch-to-Build track.
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

from app.adapters import load_baseline_records
from app.playback import (
    EpisodePhase,
    calculate_countdown,
    evaluate_playback_episode,
    evaluate_unit_view,
    filter_readings_up_to,
    latest_reading_per_patient,
)
from app.scenarios import get_default_scenarios
from htn_alert.contract import Action, ActionKind, Reading
from htn_alert.emr import draft_emr_entry, verify_traceability
from htn_alert.generator import generate_bp_readings
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
if "patients_data" not in st.session_state:
    st.session_state.patients_data = {
        "Bed-01": {"readings": [], "actions": [], "confirmed_emr": [], "base_time": None},
        "Bed-02": {"readings": [], "actions": [], "confirmed_emr": [], "base_time": None},
        "Bed-03": {"readings": [], "actions": [], "confirmed_emr": [], "base_time": None},
        "Bed-04": {"readings": [], "actions": [], "confirmed_emr": [], "base_time": None},
    }
if "current_patient_id" not in st.session_state:
    st.session_state.current_patient_id = "Bed-04"
if "replay_minute" not in st.session_state:
    st.session_state.replay_minute = 0
if "replay_source" not in st.session_state:
    st.session_state.replay_source = "Unit Multi-Bed View (Beds 01–03)"


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
        f"- Medication Target: ≤ {int(protocol.treatment_target.total_seconds() // 60)} min (from onset)\n"
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

        # Patient Bed Selector
        bed_options = ["Bed-01", "Bed-02", "Bed-03", "Bed-04", "Bed-05"]
        patient_id = st.selectbox(
            "Patient Identifier / Bed Number",
            options=bed_options,
            index=bed_options.index(st.session_state.current_patient_id) if st.session_state.current_patient_id in bed_options else 3,
        )
        st.session_state.current_patient_id = patient_id

        if patient_id not in st.session_state.patients_data:
            st.session_state.patients_data[patient_id] = {
                "readings": [],
                "actions": [],
                "confirmed_emr": [],
                "base_time": None,
            }

        pdata = st.session_state.patients_data[patient_id]

        # Quick Test Case Prefill Buttons
        st.write("**Quick-Fill Clinical Test Cases:**")
        qcol1, qcol2 = st.columns(2)
        if qcol1.button("🟡 Severe Onset (168/112)"):
            st.session_state.sys_val = 168
            st.session_state.dia_val = 112
            st.session_state.sim_delta_val = 0
        if qcol2.button("🟢 Normal Routine (120/78)"):
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
            if not pdata["readings"]:
                base = datetime.now().replace(microsecond=0)
                pdata["base_time"] = base
            else:
                base = pdata["base_time"]

            reading_time = base + timedelta(minutes=sim_delta)
            new_reading = Reading(
                patient_id=patient_id,
                time=reading_time,
                systolic=int(systolic),
                diastolic=int(diastolic),
            )
            pdata["readings"].append(new_reading)
            st.success(f"Logged {systolic}/{diastolic} mmHg for {patient_id} at {reading_time.strftime('%H:%M:%S')}")

        if st.button("🔄 Reset This Bed's Episode", use_container_width=True):
            pdata["readings"] = []
            pdata["actions"] = []
            pdata["confirmed_emr"] = []
            pdata["base_time"] = None
            st.rerun()

    with col_status:
        st.markdown("### 🔔 Clinical Protocol Status & Countdown")

        readings = pdata["readings"]
        actions = pdata["actions"]

        if not readings:
            st.info(f"No blood pressure readings logged yet for {patient_id}. Enter a reading on the left to begin.")
        else:
            now_clock = readings[-1].time
            status = evaluate_playback_episode(
                readings,
                protocol,
                simulated_now=now_clock,
                actions=actions,
            )

            # Render Status Card based on EpisodeTracker events
            if status.phase == EpisodePhase.NONE:
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
                st.warning("🟠 **REPEAT BP DUE NOW** — 15 minutes reached since severe reading. Recheck vital signs.")
                st.write(status.detail)

            elif status.phase == EpisodePhase.REOPENED:
                st.warning("🟡 **EPISODE REOPENED** — Severe blood pressure observed again within repeat window.")
                st.write(status.detail)

            elif status.phase == EpisodePhase.CONFIRMED:
                st.error("🚨 **PERSISTENT SEVERE HYPERTENSION CONFIRMED**")
                st.write(status.detail)

                if status.treatment_target_time:
                    rem_sec, is_overdue, display_str = calculate_countdown(status.treatment_target_time, now_clock)
                    t_prog = max(0.0, min(1.0, 1.0 - (rem_sec / 3600.0)))
                    st.metric("60-Min Medication Target Countdown (from onset)", display_str)
                    st.progress(t_prog, text="National 60-minute time-to-treatment standard (counted from onset)")

            elif status.phase == EpisodePhase.ESCALATED:
                st.error("🚨 **ESCALATION NOTICE ACTIVE** — Provider unacknowledged after 10 minutes!")
                st.write(status.detail)

            elif status.phase == EpisodePhase.RESOLVED:
                st.success("🟢 **EPISODE RESOLVED (UNCONFIRMED)**")
                st.write(status.detail)

            # Simulated Staff Actions
            if status.phase in (EpisodePhase.CONFIRMED, EpisodePhase.ESCALATED):
                st.markdown("---")
                st.markdown("### 📞 Attending Provider Communication (Simulated)")
                st.caption("Deterministic tracking feeds staff actions into EpisodeTracker to halt escalation.")

                act_c1, act_c2 = st.columns(2)
                if act_c1.button("🩺 Simulate Provider Acknowledged", use_container_width=True):
                    ack_action = Action(patient_id, now_clock, ActionKind.PROVIDER_ACKNOWLEDGED)
                    pdata["actions"].append(ack_action)
                    st.success("✅ Provider acknowledged notification. Escalation stopped.")
                    st.rerun()

                if act_c2.button("💊 Simulate Dose Administered", use_container_width=True):
                    dose_action = Action(patient_id, now_clock, ActionKind.DOSE_GIVEN)
                    pdata["actions"].append(dose_action)
                    st.success("✅ Antihypertensive dose administered. Timely treatment recorded.")
                    st.rerun()

            # AI-Drafted EMR Review Step (Issue #17)
            if status.events:
                st.markdown("---")
                st.markdown("### 📝 AI-Drafted EMR Nursing Documentation (Issue #17)")
                st.caption(
                    "Deterministic detection & confirmation. An LLM drafts the timeline note from verified events; "
                    "bedside nurse reviews, verifies traceability, and confirms before logging."
                )

                draft_text = draft_emr_entry(status.events)
                t_result = verify_traceability(draft_text, status.events)

                st.info("⚠️ **DRAFT EMR ENTRY — PENDING NURSE REVIEW (Simulated)**")
                st.text_area("Draft Nursing Note (Editable before confirmation):", value=draft_text, height=180)

                if t_result.valid:
                    st.success(
                        f"🛡️ **Traceability Verified:** All {len(t_result.grounded_items)} clinical values, timestamps, "
                        f"and patient identifiers ({', '.join(t_result.grounded_items)}) trace directly to verified system events."
                    )
                else:
                    st.error(
                        f"⚠️ **Traceability Warning:** Untraceable tokens detected in draft: {', '.join(t_result.untraceable_items)}"
                    )

                if st.button("✅ Confirm and Log to Patient EMR", type="primary", use_container_width=True):
                    pdata["confirmed_emr"].append({
                        "logged_at": now_clock.strftime("%H:%M:%S"),
                        "text": draft_text,
                    })
                    st.success("EMR Note confirmed and successfully committed to patient medical record.")

            if pdata["confirmed_emr"]:
                st.markdown("#### 📁 Committed Patient EMR Record")
                for entry in pdata["confirmed_emr"]:
                    st.code(f"Logged at {entry['logged_at']}:\n{entry['text']}", language="text")

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
# MODE 2: Replay Readings & Scenarios (Issues #8 & #18)
# -----------------------------------------------------------------------------
elif app_mode == "⏱️ Replay Readings & Scenarios":
    st.subheader("Replay Readings Over Time & Unit Multi-Bed Simulation")
    st.caption(
        "Demonstrates Issues #8 & #18: steps through time across multiple patients, "
        "evaluates unit state through EpisodeTracker, and provides live protocol countdowns."
    )

    base_time = datetime(2026, 10, 31, 10, 0)

    replay_options = [
        "Unit Multi-Bed View (Beds 01–03)",
        "Persistent Severe (Generator)",
        "Non-Persistent Severe (Generator)",
        "Delayed / Missing Repeat (Generator)",
        "Recurrent Severe (Generator)",
        "Borderline Severe (Generator)",
    ]
    st.session_state.replay_source = st.selectbox(
        "Select Replay Source / Unit Configuration:",
        replay_options,
    )

    # Build cohort readings
    if st.session_state.replay_source == "Unit Multi-Bed View (Beds 01–03)":
        # Multi-bed unit as required by Issue #8 and Issue #18
        cohort = {
            "Bed-01": generate_bp_readings("Bed-01", base_time, duration_hours=2, interval_minutes=15, scenario="non_hypertensive", seed=101),
            "Bed-02": generate_bp_readings("Bed-02", base_time, duration_hours=2, interval_minutes=15, scenario="persistent_severe", seed=102),
            "Bed-03": generate_bp_readings("Bed-03", base_time, duration_hours=2, interval_minutes=15, scenario="nonpersistent_severe", seed=103),
        }
    else:
        # Generator scenario selected
        scen_key = {
            "Persistent Severe (Generator)": "persistent_severe",
            "Non-Persistent Severe (Generator)": "nonpersistent_severe",
            "Delayed / Missing Repeat (Generator)": "delayed_or_missing_repeat",
            "Recurrent Severe (Generator)": "recurrent_severe",
            "Borderline Severe (Generator)": "borderline_severe",
        }[st.session_state.replay_source]

        cohort = {
            "Bed-04": generate_bp_readings("Bed-04", base_time, duration_hours=2, interval_minutes=15, scenario=scen_key, seed=42),
            "Bed-05": generate_bp_readings("Bed-05", base_time, duration_hours=2, interval_minutes=15, scenario="non_hypertensive", seed=99),
        }

    # Time Scrubber
    st.markdown("---")
    max_minutes = 75
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

    # Evaluate Unit View (Issue #18)
    unit_status = evaluate_unit_view(cohort, simulated_now, protocol)
    all_readings = [r for rlist in cohort.values() for r in rlist]
    latest_per_bed = latest_reading_per_patient(all_readings, simulated_now)

    # Unit Overview Cards
    st.markdown("### 🏥 L&D Unit Overview at Virtual Clock")
    unit_cols = st.columns(len(cohort))
    for i, (bed_id, status) in enumerate(unit_status.items()):
        latest_r = latest_per_bed.get(bed_id)
        with unit_cols[i]:
            st.markdown(f"#### {bed_id}")
            if latest_r:
                severe_flag = "🚨 SEVERE" if is_severe(latest_r, protocol) else "🟢 NORMAL"
                st.write(f"**Latest BP:** {latest_r.systolic}/{latest_r.diastolic} mmHg ({severe_flag})")
                st.caption(f"Time: {latest_r.time.strftime('%H:%M')}")
            else:
                st.write("No readings yet.")

            # Badge
            phase_colors = {
                EpisodePhase.NONE: "🟢 Normal",
                EpisodePhase.REPEAT_PENDING: "🟡 Repeat Pending",
                EpisodePhase.REPEAT_DUE: "🟠 Repeat Due",
                EpisodePhase.CONFIRMED: "🚨 Confirmed Severe",
                EpisodePhase.ESCALATED: "🚨 Escalated",
                EpisodePhase.RESOLVED: "🟢 Resolved",
                EpisodePhase.REOPENED: "🟡 Reopened",
            }
            st.info(f"**State:** {phase_colors.get(status.phase, status.phase.value)}")

    st.markdown("---")
    focus_bed = st.selectbox("Inspect Bedside Detail & Events for:", list(cohort.keys()))
    focus_status = unit_status[focus_bed]
    focus_readings = filter_readings_up_to(cohort[focus_bed], simulated_now)

    r_col1, r_col2 = st.columns([1, 1], gap="large")

    with r_col1:
        st.markdown(f"### 📊 Vital Signs Timeline ({focus_bed})")
        all_df = pd.DataFrame([
            {
                "Elapsed Min": int((r.time - base_time).total_seconds() // 60),
                "Time": r.time.strftime("%H:%M"),
                "Systolic": r.systolic,
                "Diastolic": r.diastolic,
                "Status": "🚨 Severe" if is_severe(r, protocol) else "Normal",
                "Visible": "✅ Arrived" if r.time <= simulated_now else "⏳ Future",
            }
            for r in cohort[focus_bed]
        ])
        st.dataframe(all_df, use_container_width=True)

        chart_df = pd.DataFrame({
            "Elapsed Min": [int((r.time - base_time).total_seconds() // 60) for r in cohort[focus_bed]],
            "Systolic": [r.systolic for r in cohort[focus_bed]],
            "Diastolic": [r.diastolic for r in cohort[focus_bed]],
        }).set_index("Elapsed Min")
        st.line_chart(chart_df)

    with r_col2:
        st.markdown(f"### 🔔 EpisodeTracker Events ({focus_bed})")

        if focus_status.phase == EpisodePhase.NONE:
            st.success("🟢 Status: Normal reference range. Routine vitals monitoring.")
        elif focus_status.phase == EpisodePhase.REPEAT_PENDING:
            st.warning("🟡 Status: First severe reading recorded. 15-minute recheck countdown active.")
            if focus_status.repeat_target_time:
                _, _, disp = calculate_countdown(focus_status.repeat_target_time, simulated_now)
                st.metric("Repeat Due In", disp)
        elif focus_status.phase == EpisodePhase.REPEAT_DUE:
            st.warning("🟠 Status: Repeat blood pressure measurement due now!")
        elif focus_status.phase == EpisodePhase.REOPENED:
            st.warning("🟡 Status: Episode reopened within repeat window.")
        elif focus_status.phase == EpisodePhase.CONFIRMED:
            st.error("🚨 Status: Persistent severe hypertension confirmed.")
            if focus_status.treatment_target_time:
                _, _, disp = calculate_countdown(focus_status.treatment_target_time, simulated_now)
                st.metric("Time to 60-min Treatment Deadline (from onset)", disp)
        elif focus_status.phase == EpisodePhase.ESCALATED:
            st.error("🚨 Status: Escalated to on-call physician / charge nurse.")
        elif focus_status.phase == EpisodePhase.RESOLVED:
            st.success("🟢 Status: Episode resolved (non-severe reading recorded).")

        st.write(f"**Detail:** {focus_status.detail}")

        # List of emitted events
        if focus_status.events:
            st.markdown("#### Emitted Event Stream:")
            for ev in focus_status.events:
                st.write(f"- `{ev.time.strftime('%H:%M')}` **{ev.kind.value}**: {ev.detail}")

            # AI EMR Draft Preview
            st.markdown("---")
            st.markdown("#### 📝 AI-Drafted EMR Note Preview")
            emr_preview = draft_emr_entry(focus_status.events)
            st.code(emr_preview, language="text")
            trace = verify_traceability(emr_preview, focus_status.events)
            if trace.valid:
                st.caption(f"🛡️ Traceability check passed: {len(trace.grounded_items)} verified elements.")


# -----------------------------------------------------------------------------
# MODE 3: Open Benchmark Data Explorer
# -----------------------------------------------------------------------------
else:
    st.subheader("Open Clinical Benchmark Dataset Explorer")
    st.write(
        "Grounding the prototype in open, de-identified maternal health benchmark data "
        "([UCI Maternal Health Risk Dataset](https://archive.ics.uci.edu/dataset/863/maternal+health+risk))."
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
