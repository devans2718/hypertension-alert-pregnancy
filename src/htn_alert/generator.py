"""Synthetic patients for the simulation: readings and staff actions.

Produces, in time order, the Readings and Actions a unit would generate: each
patient's whole blood pressure stream (mostly normal, some mild, some severe,
some severe readings that settle on the repeat, a share of spurious readings),
plus staff actions with realistic delays between steps.

Every parameter gets a source, as in config/protocol.toml: pitch team,
literature, or assumption. Spurious readings and other ground truth stay
here; they never go on a Reading.

Not implemented yet.
"""
