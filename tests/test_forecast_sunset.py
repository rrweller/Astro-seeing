"""Sunset maps (F1 spec Module 7, D60 item 3; ticket #67): at the first tick after
sunset at the default saved place, the product set current at sunset (the latest one
written at or before it) has its map layers and ``latest.json`` copied to
``sunset/<night>/``; seven are kept, the oldest deleted first.

A fake clock steps every 15 minutes, as the tick does. Each step publishes a product
set with ``sets.publish`` (a place file and two layers whose bytes name the step, so
every step writes a new set) and then asks ``sunset.take_sunset_map`` for the map, with
Tonight's Sun at Kongsberg. The expected set is worked out here from the steps' own
write times and Skyfield's sunsets, not by the code under test.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from astroseeing.forecast.publish.sets import publish
from astroseeing.forecast.publish.sunset import sunset_maps, take_sunset_map
from astroseeing.forecast.schemas import validate
from astroseeing.forecast.tonight import sun_track

from forecast_world import DAY, World

KONGSBERG = (59.669, 9.652)
START = dt.datetime(2026, 11, 20, tzinfo=dt.UTC)
STEP = dt.timedelta(minutes=15)


@pytest.fixture(scope="module")
def nights(ephemeris):
    """Kongsberg's Sun over the Nights of 19-30 November (each Night asked at its own
    local noon, when it is Tonight)."""
    out = []
    for d in range(19, 31):
        noon = dt.datetime(2026, 11, d, 11, 30, tzinfo=dt.UTC)
        out.append(sun_track(*KONGSBERG, noon, *ephemeris))
    assert [s.night for s in out] == [dt.date(2026, 11, d) for d in range(19, 31)]
    return out


def tonight_sun(nights, now):
    """Tonight's Sun at ``now``: the first Night whose sunrise is still to come."""
    return next(s for s in nights if s.sunrise > now)


class Clock:
    """Publishes a set at each tick and remembers each set's write time."""

    def __init__(self, products: Path):
        self.products = products
        self.written: list[tuple[dt.datetime, str]] = []  # (write time, set id)

    def publish(self, now: dt.datetime) -> str:
        files = {
            "place-kongsberg.json": b'{"place": "kongsberg"}',
            "clear_left.u8": f"clear {now:%Y%m%dT%H%M}".encode(),
            "dark_left_min.u16": f"dark {now:%Y%m%dT%H%M}".encode(),
        }
        latest = {
            "schema": "f1-latest/1",
            "layers": {
                "clear_left": {"file": "clear_left.u8", "dtype": "uint8"},
                "dark_left_min": {"file": "dark_left_min.u16", "dtype": "uint16"},
            },
            "sunset_maps": sunset_maps(self.products),
        }
        result = publish(self.products, files, latest, now)
        assert result.new
        self.written.append((now, result.set_id))
        return result.set_id

    def current_at(self, t: dt.datetime) -> str | None:
        """The set current at ``t``: the latest written at or before it."""
        before = [s for when, s in self.written if when <= t]
        return before[-1] if before else None


def run(clock: Clock, nights, ticks) -> dict[dt.date, tuple[dt.datetime, object]]:
    """At each tick, take the sunset map if due, then publish (the tick's order, so the
    new map is listed in the tick's own ``latest.json``); return each night's take."""
    taken = {}
    for now in ticks:
        result = take_sunset_map(clock.products, tonight_sun(nights, now), now)
        clock.publish(now)
        if result is not None:
            assert result.night not in taken, f"{result.night} taken twice"
            taken[result.night] = (now, result)
    return taken


def every_tick(start, end):
    t = start
    while t < end:
        yield t
        t += STEP


def folder(products: Path, night: dt.date) -> Path:
    return products / "sunset" / night.isoformat()


def test_nine_days_take_one_map_a_night_from_the_set_current_at_sunset_and_keep_seven(
    tmp_path, nights
):
    products = tmp_path / "products"
    clock = Clock(products)
    end = dt.datetime(2026, 11, 29, 12, tzinfo=dt.UTC)
    taken = run(clock, nights, every_tick(START, end))

    # 19 November's sunset came before the first set: nothing was current then, so
    # nothing is taken for it (never a later set). Then one map each of 20-28 November.
    nine = [dt.date(2026, 11, d) for d in range(20, 29)]
    assert sorted(taken) == nine
    for sun in nights[1:10]:
        when, result = taken[sun.night]
        first_after = min(t for t, _ in clock.written if t > sun.sunset)
        assert when == first_after  # the first tick after Kongsberg's sunset
        assert result.set_id == clock.current_at(sun.sunset)
        assert result.set_id != clock.current_at(when)  # not the set of the tick itself

    # after nine nights exactly seven remain, the oldest two gone
    kept = sorted(p.name for p in (products / "sunset").iterdir())
    assert kept == [d.isoformat() for d in nine[2:]]
    for sun in nights[3:10]:
        f = folder(products, sun.night)
        expected = clock.current_at(sun.sunset)
        latest = json.loads((f / "latest.json").read_text())
        assert latest["set_id"] == expected
        # the layers as that set held them, and nothing else (no place file)
        assert sorted(p.name for p in f.iterdir()) == [
            "clear_left.u8",
            "dark_left_min.u16",
            "latest.json",
        ]
        stamp = dt.datetime.strptime(expected[:15], "%Y%m%dT%H%M%S").replace(tzinfo=dt.UTC)
        assert (f / "clear_left.u8").read_bytes() == f"clear {stamp:%Y%m%dT%H%M}".encode()

    # latest.json lists them, newest first
    assert sunset_maps(products) == [
        {"night": d.isoformat(), "path": f"sunset/{d.isoformat()}/"} for d in reversed(nine[2:])
    ]


def test_a_missed_tick_around_sunset_still_takes_the_set_written_at_or_before_it(tmp_path, nights):
    sun = nights[1]  # 20 November
    clock = Clock(tmp_path / "products")
    # no tick from 40 minutes before sunset to 50 minutes after it
    gap = (sun.sunset - dt.timedelta(minutes=40), sun.sunset + dt.timedelta(minutes=50))
    ticks = [t for t in every_tick(START, START + dt.timedelta(days=1))
             if not gap[0] < t < gap[1]]  # fmt: skip
    taken = run(clock, nights, ticks)
    when, result = taken[sun.night]
    assert when == min(t for t in ticks if t > sun.sunset)
    before_gap = max(t for t in ticks if t <= sun.sunset)
    assert sun.sunset - before_gap >= dt.timedelta(minutes=40)
    assert result.set_id == clock.current_at(sun.sunset) == clock.current_at(before_gap)


def test_a_restart_after_ticks_that_published_but_took_no_map_takes_the_set_at_sunset(
    tmp_path, nights
):
    sun = nights[1]
    products = tmp_path / "products"
    clock = Clock(products)
    ticks = list(every_tick(START, START + dt.timedelta(days=1)))
    before = [t for t in ticks if t <= sun.sunset]
    after = [t for t in ticks if t > sun.sunset]
    run(clock, nights, before)
    # two ticks after sunset published their sets, then stopped before the sunset map
    # (a crash, say); the service restarts with nothing but what is on disk
    for t in after[:2]:
        clock.publish(t)
    assert not (products / "sunset").exists()
    taken = run(clock, nights, after[2:])
    when, result = taken[sun.night]
    assert when == after[2]
    assert result.set_id == clock.current_at(sun.sunset) == clock.current_at(before[-1])
    kept = json.loads((folder(products, sun.night) / "latest.json").read_text())
    assert kept["written_at"] == f"{before[-1]:%Y-%m-%dT%H:%M:%SZ}"


def test_no_map_is_taken_once_the_set_at_sunset_is_gone_never_a_later_one(tmp_path, nights, caplog):
    sun = nights[1]
    products = tmp_path / "products"
    clock = Clock(products)
    ticks = list(every_tick(START, START + dt.timedelta(days=1)))
    run(clock, nights, [t for t in ticks if t <= sun.sunset])
    after = [t for t in ticks if t > sun.sunset]
    for t in after[:3]:  # three sets after sunset: the one at sunset is pruned
        clock.publish(t)
    assert clock.current_at(sun.sunset) not in {p.name for p in (products / "sets").iterdir()}
    taken = run(clock, nights, after[3:])
    assert sun.night not in taken
    assert not folder(products, sun.night).exists()
    assert "no sunset map for the night of 2026-11-20" in caplog.text


def test_each_set_keeps_its_own_latest_json_and_refuses_files_of_that_name(tmp_path):
    products = tmp_path / "products"
    now = START + dt.timedelta(hours=1)
    sid = Clock(products).publish(now)
    own = (products / "sets" / sid / "latest.json").read_bytes()
    assert own == (products / "latest.json").read_bytes()
    assert json.loads(own)["written_at"] == "2026-11-20T01:00:00Z"
    with pytest.raises(ValueError, match=r"latest\.json"):
        publish(products, {"latest.json": b"{}"}, {"schema": "f1-latest/1"}, now)


def test_a_tick_at_or_before_sunset_takes_nothing(tmp_path, nights):
    sun = nights[1]
    products = tmp_path / "products"
    clock = Clock(products)
    t = sun.sunset - dt.timedelta(seconds=1)
    clock.publish(t)
    assert take_sunset_map(products, sun, t) is None
    assert take_sunset_map(products, sun, sun.sunset) is None  # at sunset: not after it
    assert sunset_maps(products) == []


# -- through the whole tick (Testing seam 1's sunset case) ------------------------------


def test_the_tick_takes_the_sunset_map_at_its_first_tick_after_kongsbergs_sunset(
    tmp_path, ephemeris
):
    world = World(tmp_path, ephemeris)
    try:
        place = world.settings.places[world.settings.default_place]
        sun = sun_track(place.lat, place.lon, DAY + dt.timedelta(hours=12), *ephemeris)
        assert sun.night == dt.date(2026, 11, 26)
        world.at(DAY + dt.timedelta(hours=10))
        before = world.at(sun.sunset - dt.timedelta(minutes=5))
        assert before.sunset is None and world.latest()["sunset_maps"] == []
        at_sunset = before.set_id  # the set current at sunset

        after = world.at(sun.sunset + dt.timedelta(minutes=10))
        assert after.sunset == {"night": "2026-11-26", "set_id": at_sunset, "deleted": []}
        latest = world.latest()
        validate(latest, "f1-latest/1")
        assert latest["sunset_maps"] == [{"night": "2026-11-26", "path": "sunset/2026-11-26/"}]
        assert latest["set_id"] != at_sunset

        kept = world.paths.products / "sunset" / "2026-11-26"
        own = json.loads((kept / "latest.json").read_text())
        validate(own, "f1-latest/1")
        assert own["set_id"] == at_sunset and own["sunset_maps"] == []
        assert sorted(p.name for p in kept.iterdir()) == sorted(
            [e["file"] for e in own["layers"].values()] + ["latest.json"]
        )
        for e in own["layers"].values():
            assert (kept / e["file"]).read_bytes() == (
                world.paths.sets / at_sunset / e["file"]
            ).read_bytes()
        assert not (world.paths.data / "sunset").exists()  # nothing goes to /data

        later = world.at(sun.sunset + dt.timedelta(minutes=25))
        assert later.sunset is None  # taken once a night
        assert world.latest()["sunset_maps"] == latest["sunset_maps"]
    finally:
        world.close()
