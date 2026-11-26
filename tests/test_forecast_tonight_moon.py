"""The Moon over Tonight (ticket #53; D43 item 7): ``moon_track``'s rise, set and phase
match Skyfield's own almanac functions at Kongsberg and Paranal on two dates, and its
hourly altitude is the topocentric altitude at each hh:00 row."""

from __future__ import annotations

import datetime as dt

import pytest
from skyfield import almanac
from skyfield.api import wgs84

from astroseeing.forecast.schemas import check_document, load_schema
from astroseeing.forecast.tonight.moon import moon_track
from astroseeing.forecast.tonight.sun import sun_track

UTC = dt.UTC
KONGSBERG = (59.669, 9.652)
PARANAL = (-24.6272, -70.4042)
NOWS = (
    dt.datetime(2026, 12, 10, 18, tzinfo=UTC),
    dt.datetime(2027, 3, 20, 18, tzinfo=UTC),
)


@pytest.mark.parametrize("place", [KONGSBERG, PARANAL], ids=["kongsberg", "paranal"])
@pytest.mark.parametrize("now", NOWS, ids=["2026-12-10", "2027-03-20"])
def test_moon_rise_set_and_phase_match_skyfields_almanac(ephemeris, place, now):
    eph, ts = ephemeris
    sun = sun_track(*place, now, eph, ts)
    m = moon_track(*place, sun, eph, ts)
    site = eph["earth"] + wgs84.latlon(*place)
    t0, t1 = ts.from_datetime(sun.start), ts.from_datetime(sun.end)

    rises, real_r = almanac.find_risings(site, eph["moon"], t0, t1)
    sets, real_s = almanac.find_settings(site, eph["moon"], t0, t1)
    rises = [t.utc_datetime() for t, ok in zip(rises, real_r, strict=True) if ok]
    sets = [t.utc_datetime() for t, ok in zip(sets, real_s, strict=True) if ok]
    if rises:
        assert m.rise is not None
        assert abs((m.rise - rises[0]).total_seconds()) < 60
    else:
        assert m.rise is None
    if sets:
        assert m.set is not None
        assert abs((m.set - sets[0]).total_seconds()) < 60
    else:
        assert m.set is None

    middle = ts.from_datetime(sun.start + dt.timedelta(hours=12))
    assert m.phase_deg == pytest.approx(almanac.moon_phase(eph, middle).degrees, abs=1e-6)
    assert m.illuminated_fraction == pytest.approx(
        almanac.fraction_illuminated(eph, "moon", middle), abs=1e-6
    )

    assert m.hours == sun.hours
    for t, alt in zip(m.hours, m.altitude_deg, strict=True):
        a, _, _ = site.at(ts.from_datetime(t)).observe(eph["moon"]).apparent().altaz()
        assert alt == pytest.approx(a.degrees, abs=1e-6)


def test_the_test_dates_see_both_a_rise_and_a_set(ephemeris):
    # Guard: at least one case per place has a rise and a set inside Tonight, so the
    # comparison above is not vacuous.
    eph, ts = ephemeris
    for place in (KONGSBERG, PARANAL):
        tracks = [moon_track(*place, sun_track(*place, now, eph, ts), eph, ts) for now in NOWS]
        assert any(t.rise is not None for t in tracks)
        assert any(t.set is not None for t in tracks)


def test_the_json_form_is_the_place_files_moon_block(ephemeris):
    eph, ts = ephemeris
    m = moon_track(*KONGSBERG, sun_track(*KONGSBERG, NOWS[0], eph, ts), eph, ts)
    schema = load_schema("f1-place/1")
    assert (
        check_document(m.to_json(), {"$defs": schema["$defs"], **schema["properties"]["moon"]})
        == []
    )
