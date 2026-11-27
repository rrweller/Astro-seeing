"""The forecast's phone alerts through the whole tick (F1 spec Module 8, Testing seam 1;
ticket #61; D51 item 9, D52 item 10).

Each condition is driven through the tick with fakes: the world's fake clock, fake
NOMADS and a fake web server, a fake free-space function for ``/staging`` and a fake
notifier (no real alert is ever sent). Every condition must send exactly one alert when
it starts and one when it clears, however many ticks it lasts.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.sources import RunRef

from fake_http import FakeHttpServer
from forecast_samples import SAMPLE_RUN, SAMPLES, drop_messages, retime_samples
from forecast_world import DAY, PUBLISHED, World

GB = 1e9
QUARTER = dt.timedelta(minutes=15)


class Phone:
    """A fake notifier: records every alert as (title, priority, message)."""

    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    def __call__(self, message: str, title: str, priority: str) -> None:
        self.sent.append((title, priority, message))

    def titles(self) -> list[str]:
        return [t for t, _, _ in self.sent]


def phone_world(tmp_path, ephemeris, **kw) -> World:
    """A test world whose ticks alert to a fake phone, with plenty of free disk."""
    w = World(tmp_path, ephemeris, **kw)
    w.phone = Phone()
    w.notify = w.phone
    w.free_bytes = lambda path: 100 * GB
    return w


@pytest.fixture
def world(tmp_path, ephemeris):
    w = phone_world(tmp_path, ephemeris)
    yield w
    w.close()


def ticks(world, start: dt.datetime, end: dt.datetime, every: dt.timedelta = QUARTER):
    t = start
    while t <= end:
        world.at(t)
        t += every


def test_low_disk_alerts_once_when_it_starts_and_once_when_it_clears(world):
    """/staging drops to 12 GB free from 09:00 to 11:00: the tick skips fetching (the
    06z run, out at 09:40, waits) and alerts once; at 11:00 the space is back, the run is
    fetched and the clear is sent once."""
    free = {"gb": 100.0}
    world.free_bytes = lambda path: free["gb"] * GB
    ticks(world, DAY + dt.timedelta(hours=8), DAY + dt.timedelta(hours=8, minutes=45))
    assert world.phone.sent == []

    free["gb"] = 12.0
    ticks(world, DAY + dt.timedelta(hours=9), DAY + dt.timedelta(hours=10, minutes=45))
    assert world.phone.titles() == ["astro-seeing: forecast disk low"]
    _, priority, message = world.phone.sent[0]
    assert priority == "high"
    assert "12.0 GB free" in message and "20 GB" in message
    assert world.run(6)["state"] == "seen"  # published at 09:40, not fetched

    free["gb"] = 30.0
    ticks(world, DAY + dt.timedelta(hours=11), DAY + dt.timedelta(hours=12))
    assert world.phone.titles() == [
        "astro-seeing: forecast disk low",
        "astro-seeing: forecast disk low cleared",
    ]
    assert world.phone.sent[1][1] == "default"
    assert "30.0 GB free" in world.phone.sent[1][2]
    assert world.run(6)["state"] == "processed"


def test_a_failed_run_alerts_once_naming_the_model_and_the_difference(tmp_path, ephemeris):
    """The 00z run (out at 03:40) lacks visibility at step 12 and fails: one alert, kept
    quiet over the next six hours of ticks; the 06z run (out at 09:40) passes its checks
    and the clear goes out once."""
    broken = retime_samples(tmp_path / "samples00", 0)
    drop_messages(broken / "gfs.t00z.pgrb2.0p25.f012.grb2", lambda k: k["shortName"] == "vis")
    publish = [
        (DAY + dt.timedelta(hours=3, minutes=40), RunRef("gfs", DAY), broken),
        (PUBLISHED, SAMPLE_RUN, SAMPLES / "box1deg"),
    ]
    w = phone_world(tmp_path / "w", ephemeris, publish=publish)
    try:
        ticks(w, DAY + dt.timedelta(hours=3), DAY + dt.timedelta(hours=9, minutes=30))
        assert w.run(0)["state"] == "failed"
        assert w.phone.titles() == ["astro-seeing: forecast run failed"]
        _, priority, message = w.phone.sent[0]
        assert priority == "high"
        assert "GFS" in message and "2026-11-26 00z" in message and "kongsberg" in message
        assert "VIS:surface" in message and "step 12" in message  # the difference

        ticks(w, DAY + dt.timedelta(hours=9, minutes=45), DAY + dt.timedelta(hours=11))
        assert w.run(6)["state"] == "processed"
        assert w.phone.titles() == [
            "astro-seeing: forecast run failed",
            "astro-seeing: forecast run failed cleared",
        ]
        assert "2026-11-26 06z" in w.phone.sent[1][2]
    finally:
        w.close()


def test_a_model_with_no_complete_run_for_24_h_alerts_once_then_clears(tmp_path, ephemeris):
    """The ticks start at midnight with nothing published (a new install: not stale);
    the 06z run is complete from 09:45. The next day it turns 24 h old after 06:00 and
    no newer run comes: one alert, kept quiet for two hours of ticks; the 18z run, out
    late at 08:10, clears it once."""
    run18 = RunRef("gfs", DAY + dt.timedelta(hours=18))
    publish = [
        (PUBLISHED, SAMPLE_RUN, SAMPLES / "box1deg"),
        (
            DAY + dt.timedelta(days=1, hours=8, minutes=10),
            run18,
            retime_samples(tmp_path / "s18", 18),
        ),
    ]
    w = phone_world(tmp_path / "w", ephemeris, publish=publish)
    try:
        ticks(w, DAY, DAY + dt.timedelta(hours=10))
        assert w.run(6)["state"] == "processed"
        ticks(
            w,
            DAY + dt.timedelta(hours=11),
            DAY + dt.timedelta(days=1, hours=5),
            every=dt.timedelta(hours=1),
        )
        ticks(
            w, DAY + dt.timedelta(days=1, hours=5, minutes=15), DAY + dt.timedelta(days=1, hours=6)
        )
        assert w.phone.sent == []  # 24.0 h old at 06:00 is not yet more than 24 h

        ticks(
            w, DAY + dt.timedelta(days=1, hours=6, minutes=15), DAY + dt.timedelta(days=1, hours=8)
        )
        assert w.phone.titles() == ["astro-seeing: forecast model stale"]
        _, priority, message = w.phone.sent[0]
        assert priority == "high"
        assert "GFS 0.25°" in message and "kongsberg" in message
        assert "2026-11-26 06z, 24.2 h old" in message

        ticks(
            w, DAY + dt.timedelta(days=1, hours=8, minutes=15), DAY + dt.timedelta(days=1, hours=9)
        )
        assert w.phone.titles() == [
            "astro-seeing: forecast model stale",
            "astro-seeing: forecast model stale cleared",
        ]
        assert "2026-11-26 18z" in w.phone.sent[1][2]
    finally:
        w.close()


def test_a_page_not_being_served_alerts_once_and_clears_once(tmp_path, ephemeris):
    """A fake web server serves the products folder. It drops every connection from
    09:45 to 10:30 (one alert, one clear at 10:45); from 11:00 to 11:45 it serves an
    old latest.json (one alert naming both sets, one clear at 12:00)."""
    products = tmp_path / "w" / "staging" / "forecast" / "products"
    with FakeHttpServer(root=products.parent) as web:
        url = web.url + "/products/latest.json"
        w = phone_world(tmp_path / "w", ephemeris, settings_edits={"alerts.served_latest_url": url})
        w.page_http = HttpClient(timeout_s=5)
        try:
            ticks(w, DAY + dt.timedelta(hours=9), DAY + dt.timedelta(hours=9, minutes=30))
            assert w.phone.sent == []
            old = w.paths.latest.read_bytes()  # before the 06z run is in

            web.outage()
            ticks(
                w, DAY + dt.timedelta(hours=9, minutes=45), DAY + dt.timedelta(hours=10, minutes=30)
            )
            assert w.phone.titles() == ["astro-seeing: forecast page not served"]
            _, priority, message = w.phone.sent[0]
            assert priority == "high" and url in message and "no complete answer" in message

            web.restore()
            ticks(
                w,
                DAY + dt.timedelta(hours=10, minutes=45),
                DAY + dt.timedelta(hours=10, minutes=45),
            )
            assert w.phone.titles()[1:] == ["astro-seeing: forecast page not served cleared"]

            web.route("/products/latest.json", old)
            ticks(w, DAY + dt.timedelta(hours=11), DAY + dt.timedelta(hours=11))
            # the alert names the set written when it started: each tick now writes a
            # new set, as the verdict's run ages move on (ticket #63, D84 item 5)
            written = w.latest()["set_id"]
            ticks(
                w,
                DAY + dt.timedelta(hours=11, minutes=15),
                DAY + dt.timedelta(hours=11, minutes=45),
            )
            assert w.phone.titles()[2:] == ["astro-seeing: forecast page not served"]
            message = w.phone.sent[2][2]
            assert "different latest.json" in message
            assert json.loads(old)["set_id"] in message and written in message

            del web.routes["/products/latest.json"]
            ticks(w, DAY + dt.timedelta(hours=12), DAY + dt.timedelta(hours=12, minutes=30))
            assert w.phone.titles()[3:] == ["astro-seeing: forecast page not served cleared"]
        finally:
            w.close()


def test_late_retried_and_partial_runs_stay_quiet(tmp_path, ephemeris):
    """The 06z run comes out late (13:40, after its expected delay + 3 h) and its step 12
    keeps failing: the run is late for hours, step 12 is tried 5 times, and the run ends
    partial. None of it alerts (D51 item 7)."""
    late = DAY + dt.timedelta(hours=13, minutes=40)
    w = phone_world(tmp_path, ephemeris, publish=[(late, SAMPLE_RUN, SAMPLES / "box1deg")])
    w.server.fail("/cgi-bin/", status=503, contains="file=gfs.t06z.pgrb2.0p25.f012")
    try:
        reports = []
        t = DAY + dt.timedelta(hours=9)
        while t <= DAY + dt.timedelta(hours=15, minutes=30):
            reports.append(w.at(t))
            t += QUARTER
        assert any(r.late for r in reports)  # logged as late
        assert w.run(6)["state"] == "partial"
        assert json.loads(w.run(6)["steps_verified"])["12"].startswith("not fetched: 5 tries")
        assert w.phone.sent == []
    finally:
        w.close()


def test_an_alert_whose_send_fails_is_sent_at_the_next_tick(world):
    """The phone service is down at the first low-disk tick: nothing is recorded, and the
    alert goes out (once) at the next tick."""
    world.free_bytes = lambda path: 5 * GB
    calls = {"n": 0}

    def flaky(message, title, priority):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("ntfy.sh unreachable")
        world.phone(message, title, priority)

    world.notify = flaky
    ticks(world, DAY + dt.timedelta(hours=8), DAY + dt.timedelta(hours=9))
    assert world.phone.titles() == ["astro-seeing: forecast disk low"]
    assert calls["n"] == 2
