"""The Sun over Tonight (ticket #53): ``sun_track`` picks Tonight by the glossary's rule,
gives the Sun's altitude at each hh:00 row and Tonight's sunset and sunrise from a
1-minute scan, checked against Skyfield's own almanac. Uses DE440s (the ``ephemeris``
fixture, as the solar module's tests do)."""

from __future__ import annotations

import datetime as dt

import pytest
from skyfield import almanac
from skyfield.api import wgs84

from astroseeing.forecast.settings import CloudClasses
from astroseeing.forecast.tonight import HourTable, HourValue, ModelHours, RunInfo, tonight
from astroseeing.forecast.tonight.sun import sun_track

UTC = dt.UTC
KONGSBERG = (59.669, 9.652)
PARANAL = (-24.6272, -70.4042)


def utc(*args) -> dt.datetime:
    return dt.datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "night"),
    [
        (utc(2026, 12, 10, 18), dt.date(2026, 12, 10)),  # evening
        (utc(2026, 12, 11, 3), dt.date(2026, 12, 10)),  # after midnight, before sunrise
        (utc(2026, 12, 11, 10), dt.date(2026, 12, 11)),  # after sunrise: the coming Night
        (utc(2026, 12, 11, 11, 30), dt.date(2026, 12, 11)),  # after local mean noon
    ],
)
def test_tonight_is_the_night_not_yet_at_its_sunrise(ephemeris, now, night):
    s = sun_track(*KONGSBERG, now, *ephemeris)
    assert s.night == night
    assert s.sunset < s.sunrise
    assert now < s.sunrise


def test_rows_run_from_local_mean_noon_and_altitudes_match_skyfield(ephemeris):
    eph, ts = ephemeris
    s = sun_track(*PARANAL, utc(2026, 12, 10, 20), eph, ts)
    # Local mean noon at 70.4042° W: 12:00 UTC + 4 h 41 min 37 s.
    assert abs(s.start - utc(2026, 12, 10, 16, 41, 37, 8000)) < dt.timedelta(milliseconds=1)
    assert s.hours[0] == utc(2026, 12, 10, 17) and s.hours[-1] == utc(2026, 12, 11, 16)
    site = eph["earth"] + wgs84.latlon(*PARANAL)
    for t, alt in zip(s.hours, s.altitude_deg, strict=True):
        a, _, _ = site.at(ts.from_datetime(t)).observe(eph["sun"]).apparent().altaz()
        assert alt == pytest.approx(a.degrees, abs=0.01)  # geocentric vs topocentric


@pytest.mark.parametrize(
    ("place", "now"),
    [
        (KONGSBERG, utc(2026, 12, 10, 18)),
        (KONGSBERG, utc(2026, 6, 21, 18)),
        (PARANAL, utc(2026, 12, 10, 20)),
        (PARANAL, utc(2026, 6, 21, 20)),
    ],
)
def test_sunset_and_sunrise_match_skyfields_almanac(ephemeris, place, now):
    eph, ts = ephemeris
    s = sun_track(*place, now, eph, ts)
    site = eph["earth"] + wgs84.latlon(*place)
    t0, t1 = ts.from_datetime(s.start), ts.from_datetime(s.end)
    sets, _ = almanac.find_settings(site, eph["sun"], t0, t1)
    rises, _ = almanac.find_risings(site, eph["sun"], t0, t1)
    assert abs((s.sunset - sets[0].utc_datetime()).total_seconds()) < 60
    assert abs((s.sunrise - rises[0].utc_datetime()).total_seconds()) < 60


def basis_on(ephemeris, now):
    s = sun_track(*KONGSBERG, now, *ephemeris)
    run = RunInfo(1, now - dt.timedelta(hours=1))
    clear = tuple(HourValue(0.0, None) for _ in range(24))
    hours = HourTable(s.night, s.hours, (ModelHours("gfs", "gfs", False, run, clear),))
    return tonight(hours, s, now, cloud_classes=CloudClasses(10, 50), stale_after_h=24).basis


def test_kongsberg_from_dark_time_to_its_fallbacks(ephemeris):
    # D43 evidence: no astronomical darkness at Kongsberg from 22 April to 19 August,
    # and the Sun never below -12° from 13 May to 29 July.
    assert basis_on(ephemeris, utc(2026, 4, 10, 18)) == "dark"
    assert basis_on(ephemeris, utc(2026, 5, 5, 18)) == "sun_below_12"
    assert basis_on(ephemeris, utc(2026, 6, 21, 18)) == "sun_down"
