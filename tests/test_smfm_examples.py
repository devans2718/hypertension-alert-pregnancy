"""SMFM's worked examples of severe-hypertension episodes, as test cases.

Source: SMFM Special Statement, quality metric for timely treatment of severe
hypertension, Am J Obstet Gynecol 2022;226:B2-B9, Figure 1 and p. B3. These
pin down the episode definitions before the episode logic is written.

Each sequence is written as in the figure: "S" a severe reading, "N" a
non-severe one, times in minutes from the first severe reading. Several
examples have readings less than 15 minutes apart, which the L&D monitors we
expect data from don't produce. They stay as the figure gives them, because
they test the definition, not the data.

Expected to fail until EpisodeTracker is implemented (see #9).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from htn_alert.contract import EventKind, Reading
from htn_alert.episodes import EpisodeTracker
from htn_alert.protocol import load_protocol

pytestmark = pytest.mark.xfail(
    raises=NotImplementedError,
    strict=True,
    reason="EpisodeTracker not implemented yet",
)

PROTOCOL = load_protocol()
T0 = datetime(2026, 11, 1, 8, 0)  # minute 0: the first severe reading
SEVERE = (170, 100)  # severe by systolic
NON_SEVERE = (140, 90)


def minutes(t: int) -> datetime:
    return T0 + timedelta(minutes=t)


def readings(sequence: str) -> list[Reading]:
    """Build readings from the figure's notation, e.g. "S 0, N 10, N 30"."""
    result = []
    for item in sequence.split(","):
        kind, t = item.split()
        systolic, diastolic = SEVERE if kind == "S" else NON_SEVERE
        result.append(Reading("p1", minutes(int(t)), systolic, diastolic))
    return result


@dataclass
class Episode:
    """An episode in the figure's terms, read back from the events."""

    onset: int  # minutes
    persistent: bool = False
    ends: int | None = None  # None: no closing reading


def run(sequence: str, until: int | None = None) -> list[Episode]:
    """Feed the readings to the episode logic and summarize its events.

    The one place that knows how EpisodeTracker is driven, so the tests below
    state only what the figure shows. The clock advances to each reading
    before it arrives, so deadlines between readings can fire, then on to
    `until` for examples that end without a closing reading.

    The tests don't check when CONFIRMED fires (e.g. at 15 minutes, or when
    the next reading arrives): that's for the episode logic to decide.
    """
    tracker = EpisodeTracker(PROTOCOL)
    events = []
    for reading in readings(sequence):
        events += tracker.tick(reading.time)
        events += tracker.observe(reading)
    if until is not None:
        events += tracker.tick(minutes(until))

    episodes: list[Episode] = []
    for event in events:
        t = int((event.time - T0) / timedelta(minutes=1))
        if event.kind is EventKind.EPISODE_OPENED:
            episodes.append(Episode(onset=t))
        elif event.kind is EventKind.CONFIRMED:
            episodes[-1].persistent = True
        elif event.kind is EventKind.EPISODE_CLOSED:
            episodes[-1].ends = t
    return episodes


@pytest.mark.parametrize(
    ("sequence", "until", "expected"),
    [
        pytest.param(
            "S 0, N 10, N 30, N 50", None,
            Episode(onset=0, persistent=False, ends=10),
            id="A",
        ),
        pytest.param(
            # One episode, not three: severe again 15-60 minutes after onset.
            "S 0, N 10, S 30, N 40, S 50, N 60, N 80", None,
            Episode(onset=0, persistent=True, ends=60),
            id="B",
        ),
        pytest.param(
            # No non-severe reading within 15 minutes.
            "N -20, S 0, N 20, N 40, N 60, N 80", None,
            Episode(onset=0, persistent=True, ends=20),
            id="C",
        ),
        pytest.param(
            "S 0, N 50", None,
            Episode(onset=0, persistent=True, ends=50),
            id="D",
        ),
        pytest.param(
            "N -10, S 0, S 20, S 30, N 50, N 70", None,
            Episode(onset=0, persistent=True, ends=50),
            id="E1",
        ),
        pytest.param(
            # The figure's E3 has a severe reading at -20 in the emergency
            # department. Only obstetric-unit readings count, and readings
            # from elsewhere never reach this system, so it isn't here.
            "S 0, S 10, N 30, N 50", None,
            Episode(onset=0, persistent=True, ends=30),
            id="E3",
        ),
        pytest.param(
            # No recheck within 15 minutes.
            "S 0, N 80", None,
            Episode(onset=0, persistent=True, ends=80),
            id="F",
        ),
        pytest.param(
            # Confirmed only at 70 minutes, which is why the treatment clock
            # starts at onset.
            "S 0, S 70, N 80", None,
            Episode(onset=0, persistent=True, ends=80),
            id="G",
        ),
        pytest.param(
            # The patient left at 10 minutes: no closing reading.
            "N -10, S 0", 30,
            Episode(onset=0, persistent=True, ends=None),
            id="H",
        ),
    ],
)
def test_figure_1(sequence, until, expected):
    assert run(sequence, until) == [expected]


E2 = "S -20, S 0, S 10, N 30, N 50"


def test_figure_1_E2_no_onset_at_0():
    """The reading at 0 isn't the first consecutive severe one (stated)."""
    assert 0 not in [episode.onset for episode in run(E2)]


def test_figure_1_E2_onset_at_minus_20():
    """Onset at -20, the first consecutive severe reading.

    Our interpretation: the figure's window starts at -20, but the paper
    doesn't state the onset.
    """
    assert [episode.onset for episode in run(E2)] == [-20]


@pytest.mark.parametrize(
    ("sequence", "persistent"),
    [
        pytest.param("S 0, N 15", False, id="N at 15"),
        pytest.param("S 0, N 16", True, id="N at 16"),
    ],
)
def test_within_15_minutes_includes_15(sequence, persistent):
    """p. B3: a non-severe reading within 15 minutes, 15 included, means the
    severe reading wasn't persistent."""
    [episode] = run(sequence)
    assert episode.persistent is persistent
