"""Metrics over event streams, comparing the unit with and without the tool.

Planned measures:
    time to treatment   share of confirmed episodes treated within 15, 30 and
                        60 minutes of confirmation
    false alarms        alerts per patient per shift on patients who never
                        have a confirmed episode (the no-added-burden question)

Results hold only under the simulator's assumptions; sensitivity analysis
varies the uncertain ones.

Not implemented yet.
"""
