"""Severe-hypertension alerting prototype for a labor and delivery unit.

Research prototype on synthetic data; not for clinical use.

Modules:
    contract   the shared data types every part builds against
    protocol   clinical and timing values, loaded from config/protocol.toml
    rules      checks on a single reading
    episodes   the per-patient episode logic: readings and actions in, events out
    generator  synthetic patients, readings and staff actions
    evaluate   metrics over event streams (time to treatment, false alarms)
"""
