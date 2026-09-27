"""Darkness tests: against Skyfield's almanac.dark_twilight_day (RESEARCH §4.1, §4.9)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from astroseeing.solar import darkness
from astroseeing.solar.sun import sun_gha_dec, to_unix, unix_to_time

UTC = dt.UTC

# (name, lat, lon): observatories plus latitudes near the 2-hour and zero-darkness limits
SITES = [
    ("paranal", -24.63, -70.40),
    ("mauna_kea", 19.82, -155.47),
    ("la_palma", 28.76, -17.89),
    ("equator_dateline", 0.0, 179.9),
    ("lat47.3", 47.3, 8.5),
    ("lat55", 55.0, -3.0),
    ("lat60", 60.0, 25.0),
    ("lat65", 65.0, -20.0),
    ("dome_c", -75.1, 123.3),
]
DATES = ["2021-03-20", "2022-06-21", "2023-09-23", "2024-12-21", "2025-02-14", "2025-11-03"]


def skyfield_dark_intervals(eph, ts, lat, lon, t0, t1):
    from skyfield import almanac
    from skyfield.api import wgs84

    f = almanac.dark_twilight_day(eph, wgs84.latlon(lat, lon))
    ta, tb = unix_to_time(ts, t0), unix_to_time(ts, t1)
    times, codes = almanac.find_discrete(ta, tb, f)
    state = int(f(ta)) == 0
    cur = t0 if state else None
    out = []
    for t, code in zip(times, codes, strict=True):
        u = (t.tt - ta.tt) * 86400.0 + t0
        now_dark = int(code) == 0
        if now_dark and not state:
            cur = u
        elif state and not now_dark:
            out.append((cur, u))
        state = now_dark
    if state:
        out.append((cur, t1))
    return out


def test_unix_to_time_has_no_leap_second_offset(ephemeris):
    _, ts = ephemeris
    for d in (
        dt.datetime(2016, 12, 31, 23, 59, 0, tzinfo=UTC),
        dt.datetime(2023, 6, 21, 3, 17, tzinfo=UTC),
    ):
        a = ts.from_datetime(d)
        b = unix_to_time(ts, float(to_unix(d)))
        assert abs((b.tt - a.tt) * 86400.0) < 1e-3


def test_sun_table_interpolation_error_is_negligible(ephemeris, sun_table_2021_2025):
    eph, ts = ephemeris
    rng = np.random.default_rng(0)
    u = rng.uniform(
        to_unix(dt.datetime(2021, 1, 1, tzinfo=UTC)),
        to_unix(dt.datetime(2025, 12, 31, tzinfo=UTC)),
        400,
    )
    gha_d, dec_d = sun_gha_dec(u, eph, ts)
    gha_i, dec_i = sun_table_2021_2025.at(u)
    dgha = (gha_i - gha_d + 180.0) % 360.0 - 180.0
    assert np.max(np.abs(dgha)) * 3600 < 0.5  # arcsec
    assert np.max(np.abs(dec_i - dec_d)) * 3600 < 0.5


def test_night_window_is_local_mean_noon_keyed_by_evening():
    starts = darkness.night_start_unix(
        np.array(["2023-06-21"], dtype="datetime64[D]"), np.array([0.0, 90.0, -120.0])
    )
    base = to_unix(dt.datetime(2023, 6, 21, tzinfo=UTC))
    np.testing.assert_allclose(starts[:, 0] - base, [12 * 3600, 6 * 3600, 20 * 3600])


@pytest.mark.parametrize(("name", "lat", "lon"), SITES)
def test_darkness_matches_skyfield(ephemeris, sun_table_2021_2025, name, lat, lon):
    eph, ts = ephemeris
    dates = np.array(DATES, dtype="datetime64[D]")
    ours_min = darkness.dark_minutes([lat], [lon], dates, sun_table_2021_2025)[0]
    starts = darkness.night_start_unix(dates, np.array([lon]))[0]
    for n, t0 in enumerate(starts):
        t1 = t0 + 86400.0
        sky = skyfield_dark_intervals(eph, ts, lat, lon, t0, t1)
        ours = darkness.dark_intervals(lat, lon, t0, t1, sun_table_2021_2025)
        assert len(ours) == len(sky), (name, DATES[n], ours, sky)
        for (a0, a1), (b0, b1) in zip(ours, sky, strict=True):
            assert abs(a0 - b0) < 10.0 and abs(a1 - b1) < 10.0, (name, DATES[n])
        sky_minutes = sum(b - a for a, b in sky) / 60.0
        assert abs(ours_min[n] - sky_minutes) <= 1.0, (name, DATES[n], ours_min[n], sky_minutes)


def test_polar_extremes(sun_table_2021_2025):
    # June solstice: at 89°S the noon Sun stays below −18° (needs |φ − δ| > 108°);
    # at 65°N it never gets below −1.6°. Dome C (75°S) is only partly dark
    # (noon altitude ≈ −8.5°), which the Skyfield comparison covers.
    d = np.array(["2022-06-21"], dtype="datetime64[D]")
    m = darkness.dark_minutes([-89.0, 65.0], [0.0, -20.0], d, sun_table_2021_2025)
    assert m[0, 0] == 1440 and m[1, 0] == 0


def test_declination_formula_limits():
    # RESEARCH §4.1: at the solstice, <2 dark hours above ~47.3°, none above ~48.6°.
    dec = 23.44
    lats = np.linspace(45.0, 50.0, 5001)
    hours = darkness.dark_hours_declination(lats, dec)
    lat_2h = lats[np.argmax(hours < 2.0)]
    lat_0h = lats[np.argmax(hours <= 0.0)]
    assert 47.2 < lat_2h < 47.4
    assert lat_0h == pytest.approx(90.0 - dec - 18.0, abs=1e-3)  # 48.56°


def test_night_mask_keeps_every_hour_touching_astronomical_darkness(sun_table_2021_2025):
    lat = np.array([-24.63, 19.82, 47.3, 60.0, -75.1])
    lon = np.array([-70.40, -155.47, 8.5, 25.0, 123.3])
    t0 = to_unix(dt.datetime(2023, 6, 18, tzinfo=UTC))
    hours = t0 + 3600.0 * np.arange(24 * 7)
    dark_any = darkness.minute_fraction_below(lat, lon, hours, sun_table_2021_2025, -18.0) > 0
    keep = darkness.night_hours_to_keep(lat, lon, hours, sun_table_2021_2025)
    assert not np.any(dark_any & ~keep)
    assert keep.sum() > dark_any.sum()  # the −12° margin keeps extra hours
