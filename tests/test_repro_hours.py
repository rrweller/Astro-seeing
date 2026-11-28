"""Hour sets for the reproductions (D57 item 3), checked against Skyfield's own almanac."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from astroseeing.repro import all_hours, dark_time, night_mask, solar_time_window

from repro_stores import hourly

PARANAL = (-24.63, -70.40)


def _almanac_codes(ephemeris, lat, lon, unix_s):
    """Skyfield's dark_twilight_day codes (0 dark, 1 astronomical, 2 nautical …)."""
    from skyfield import almanac
    from skyfield.api import wgs84

    from astroseeing.solar.sun import unix_to_time

    eph, ts = ephemeris
    f = almanac.dark_twilight_day(eph, wgs84.latlon(lat, lon))
    return np.asarray(f(unix_to_time(ts, np.asarray(unix_s, float))))


def test_all_hours_keeps_every_hour():
    times = hourly("2023-06-01T00:00", 30)
    assert all_hours(times).tolist() == [True] * 30


def test_solar_time_windows_at_da_qaidam_by_hand():
    # Local mean solar time at 95.35° E is UTC + 6.357 h.
    times = hourly("2020-08-01T00:00", 24)
    utc = np.arange(24)
    morning = solar_time_window(times, 95.35, 4, 7)
    evening = solar_time_window(times, 95.35, 19, 23)
    assert utc[morning].tolist() == [0, 22, 23]  # 6.36, 4.36, 5.36 h
    assert utc[evening].tolist() == [13, 14, 15, 16]  # 19.36 … 22.36 h


def test_solar_time_window_includes_both_ends_and_can_wrap_midnight():
    times = hourly("2020-08-01T00:00", 24)
    utc = np.arange(24)
    assert utc[solar_time_window(times, 0.0, 4, 7)].tolist() == [4, 5, 6, 7]
    assert utc[solar_time_window(times, 0.0, 22, 2)].tolist() == [0, 1, 2, 22, 23]
    # 90° W: local mean time is UTC − 6 h.
    assert utc[solar_time_window(times, -90.0, 4, 7)].tolist() == [10, 11, 12, 13]


def test_night_mask_is_the_ingest_rule_against_skyfields_almanac(ephemeris, sun_table_2021_2025):
    times = hourly("2023-06-20T12:00", 48)
    got = night_mask(times, *PARANAL, sun=sun_table_2021_2025)
    # Independent: an hour is kept if the Sun is below −12° (almanac code ≤ 1) at any
    # minute of the hour centred on it.
    t = times.astype("datetime64[s]").astype(np.int64)
    minutes = t[:, None] + (np.arange(60) - 30 + 0.5) * 60.0
    codes = _almanac_codes(ephemeris, *PARANAL, minutes.ravel()).reshape(minutes.shape)
    want = (codes <= 1).any(axis=1)
    np.testing.assert_array_equal(got, want)
    assert 0 < got.sum() < 48


def test_dark_time_keeps_dark_hours_of_the_listed_nights_only(ephemeris, sun_table_2021_2025):
    times = hourly("2023-06-20T12:00", 72)  # three nights: 20, 21 and 22 June
    nights = [dt.date(2023, 6, 20), "2023-06-22"]
    got = dark_time(times, *PARANAL, nights, sun=sun_table_2021_2025)

    t = times.astype("datetime64[s]").astype(np.int64)
    dark = _almanac_codes(ephemeris, *PARANAL, t) == 0  # Sun below −18° at the hour
    # Nights run from local mean noon (12:00 UTC + 70.40/15 h = 16:41.6 UTC) to the next.
    noon = np.datetime64("2023-06-20T16:41:36", "s").astype(np.int64)
    night_index = (t - noon) // 86400
    listed = np.isin(night_index, [0, 2])
    np.testing.assert_array_equal(got, dark & listed)
    assert got[night_index == 1].sum() == 0 and got[night_index == 0].sum() > 0


def test_dark_time_threshold_can_be_moved_to_minus_12(ephemeris, sun_table_2021_2025):
    times = hourly("2023-06-20T12:00", 24)
    got = dark_time(times, *PARANAL, ["2023-06-20"], sun=sun_table_2021_2025, threshold_deg=-12.0)
    t = times.astype("datetime64[s]").astype(np.int64)
    want = _almanac_codes(ephemeris, *PARANAL, t) <= 1
    np.testing.assert_array_equal(got, want)


def test_a_sun_table_is_built_when_none_is_given():
    times = hourly("2023-06-20T12:00", 24)
    a = night_mask(times, *PARANAL)
    assert a.dtype == bool and 0 < a.sum() < 24


def test_selectors_refuse_times_that_are_not_datetimes():
    with pytest.raises(TypeError, match="datetime64"):
        all_hours(np.arange(5))
