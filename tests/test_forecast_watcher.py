"""The download watcher's forecast checks (ticket #61; D51 item 9): the tick's heartbeat
and the forecast line in the 06:00 daily message.

The real tick runs in a test world (fake NOMADS, fake clock, temp manifest) and writes
its heartbeat; ``notify.check_once`` then reads the same manifest at fake times with a
fake notifier. Nothing is ever sent for real.
"""

from __future__ import annotations

import datetime as dt

import pytest

from astroseeing.forecast.sources import RunRef
from astroseeing.notify import WatchState, check_once

from forecast_samples import SAMPLE_RUN, SAMPLES, drop_messages, retime_samples
from forecast_world import DAY, PUBLISHED, World

MIN = dt.timedelta(minutes=1)


def watch(world: World, state: WatchState, now: dt.datetime) -> list[tuple[str, str, str]]:
    """One watcher check at ``now``; returns what it sent as (title, priority, message)."""
    sent = []
    check_once(world.manifest, state, lambda msg, title, prio: sent.append((title, prio, msg)),
               now, loop_running=lambda: True)  # fmt: skip
    return sent


@pytest.fixture
def world(tmp_path, ephemeris):
    w = World(tmp_path, ephemeris)
    yield w
    w.close()


def test_a_stopped_tick_is_reported_after_1_h_not_before_and_cleared_once(world):
    state = WatchState(last_daily=DAY.date().isoformat())
    assert watch(world, state, DAY + dt.timedelta(hours=9)) == []  # no tick ever: quiet

    last = DAY + dt.timedelta(hours=10)
    world.at(last)  # the last tick before the timer stops
    for minutes in (0, 15, 30, 45, 59):
        assert watch(world, state, last + minutes * MIN) == []

    sent = watch(world, state, last + 60 * MIN)
    assert [t for t, _, _ in sent] == ["astro-seeing: forecast tick stopped"]
    _, priority, message = sent[0]
    assert priority == "high"
    assert "1.0 h" in message and "10:00 UTC" in message
    assert "systemctl status astro-forecast.timer" in message
    for minutes in (70, 120, 600):  # quiet while it stays stopped
        assert watch(world, state, last + minutes * MIN) == []

    world.at(last + 11 * dt.timedelta(hours=1))  # the timer runs again at 21:00
    sent = watch(world, state, last + 11 * dt.timedelta(hours=1) + 5 * MIN)
    assert [(t, p) for t, p, _ in sent] == [
        ("astro-seeing: forecast tick stopped cleared", "default")
    ]
    assert "21:00 UTC" in sent[0][2]
    assert watch(world, state, last + 11 * dt.timedelta(hours=1) + 20 * MIN) == []


def test_the_daily_message_gains_the_forecast_line(tmp_path, ephemeris):
    """A fake day: the 00z, 06z, 12z and 18z runs come out 3 h 40 min after their run
    times and are fetched at the next hourly tick; the 12z run is broken and fails. At
    06:00 the next day the last 24 h hold two complete runs (06z and 18z; the 00z run
    finished at 04:00 the day before), and the newest is the 18z run, 12 h old."""
    broken = retime_samples(tmp_path / "s12", 12)
    drop_messages(broken / "gfs.t12z.pgrb2.0p25.f012.grb2", lambda k: k["shortName"] == "vis")

    def at(hour: int) -> dt.datetime:
        return DAY + dt.timedelta(hours=hour)

    out = dt.timedelta(hours=3, minutes=40)
    publish = [
        (at(0) + out, RunRef("gfs", at(0)), retime_samples(tmp_path / "s00", 0)),
        (PUBLISHED, SAMPLE_RUN, SAMPLES / "box1deg"),
        (at(12) + out, RunRef("gfs", at(12)), broken),
        (at(18) + out, RunRef("gfs", at(18)), retime_samples(tmp_path / "s18", 18)),
    ]
    w = World(tmp_path / "w", ephemeris, publish=publish)
    try:
        for hour in range(24 + 6):  # hourly ticks to 05:00 the next day, then 05:45
            w.at(DAY + dt.timedelta(hours=hour))
        w.at(DAY + dt.timedelta(days=1, hours=5, minutes=45))
        assert [r["state"] for r in w.runs()] == ["processed", "processed", "failed", "processed"]

        state = WatchState(last_daily=DAY.date().isoformat())
        sent = watch(w, state, DAY + dt.timedelta(days=1, hours=6))
        assert [t for t, _, _ in sent] == ["astro-seeing: daily progress"]
        first, line = sent[0][2].split("\n")
        assert first.startswith("Daily: 0 requests done")  # the download line, as before
        assert line == (
            "Forecast, runs completed in the last 24 h (as of the 05:45 UTC tick): "
            "kongsberg GFS 0.25° 2, newest 2026-11-26 18z (12.0 h old)."
        )
    finally:
        w.close()


def test_the_daily_message_has_no_forecast_line_before_the_first_tick(world):
    sent = watch(world, WatchState(), DAY + dt.timedelta(hours=6))
    assert [t for t, _, _ in sent] == ["astro-seeing: daily progress"]
    assert "\n" not in sent[0][2] and "Forecast" not in sent[0][2]
