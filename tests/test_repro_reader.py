"""The site time-series reader for the paper reproductions (roadmap C9, D57, D66).

Every test goes through ``astroseeing.repro.read_site`` on synthetic Zarr stores
written by the real ingest writer (``tests/repro_stores.py``).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from astroseeing.repro import HourGrid, Nearest, SiteReadError, read_site
from astroseeing.synthetic import ERA5_LEVELS_HPA

from repro_stores import axis, hourly, write_pl_store, write_static_store

# A 5 × 5 box, north → south and west → east, as the CDS delivers it.
LAT = axis(-24.0, 5, -0.25)  # -24.00 … -25.00
LON = axis(-71.0, 5, 0.25)  # -71.00 … -70.00
START = dt.datetime(2023, 6, 1, tzinfo=dt.UTC)


def _t_field(t, p, la, lo):
    # Distinct at every point and level: 200 K + 10·lat + 1·lon + p/100.
    return 200.0 + 10.0 * la + 1.0 * lo + p / 100.0 + 0.0 * t


def test_nearest_reads_the_nearest_grid_point_in_time_order(tmp_path):
    times = hourly("2023-06-01T00:00", 24)
    store = write_pl_store(
        tmp_path / "pl.zarr", times=times, lat=LAT, lon=LON, fields={"t": _t_field}
    )
    static = write_static_store(tmp_path / "static.zarr", lat=LAT, lon=LON, orography_m=0.0)

    cols = read_site(
        [store],
        lat=-24.63,
        lon=-70.40,
        rule=Nearest(),
        start=START,
        end=START + dt.timedelta(days=1),
        static_store=static,
    )

    # Paranal's nearest 0.25° point is (-24.75, -70.50): 0.12° and 0.10° away.
    np.testing.assert_array_equal(cols.times, times)
    np.testing.assert_array_equal(cols.p_hpa, ERA5_LEVELS_HPA)
    want = 200.0 + 10.0 * -24.75 + 1.0 * -70.50 + ERA5_LEVELS_HPA / 100.0
    np.testing.assert_allclose(cols.t_k, np.broadcast_to(want, (24, 29)), rtol=1e-6)
    assert cols.points == ((-24.75, -70.50),)


def _site_box_cells(lat, lon, centre, half=2):
    """Cells-layout mask: the (2·half+1)² box round ``centre`` (lat, lon), like an area's."""
    la = np.asarray(lat)[:, None]
    lo = np.asarray(lon)[None, :]
    return (np.abs(la - centre[0]) <= half * 0.25 + 1e-9) & (
        np.abs(lo - centre[1]) <= half * 0.25 + 1e-9
    )


def test_cells_stores_in_any_order_and_0_360_longitudes_read_like_a_grid(tmp_path):
    # An area rectangle 9 × 9, of which only the 5 × 5 box round the site is stored,
    # with longitudes as the CDS may return them (0..360), split over two stores
    # passed in reverse time order.
    lat = axis(-23.5, 9, -0.25)
    lon = axis(288.5, 9, 0.25)  # 288.50 … 290.50 == -71.50 … -69.50
    cells = _site_box_cells(lat, lon, (-24.75, 289.50))
    day1 = hourly("2023-06-01T00:00", 24)
    day2 = hourly("2023-06-02T00:00", 24)
    s1 = write_pl_store(
        tmp_path / "a.zarr", times=day1, lat=lat, lon=lon, fields={"t": _t_field}, cells=cells
    )
    s2 = write_pl_store(
        tmp_path / "b.zarr", times=day2, lat=lat, lon=lon, fields={"t": _t_field}, cells=cells
    )
    static = write_static_store(tmp_path / "st.zarr", lat=lat, lon=lon, cells=cells)

    cols = read_site(
        [s2, s1],
        lat=-24.63,
        lon=-70.40,
        rule=Nearest(),
        start=START,
        end=START + dt.timedelta(days=2),
        static_store=static,
    )

    np.testing.assert_array_equal(cols.times, np.concatenate([day1, day2]))
    # 289.50 is -70.50; the field saw the stored longitude, 289.50.
    want = 200.0 + 10.0 * -24.75 + 289.50 + ERA5_LEVELS_HPA / 100.0
    np.testing.assert_allclose(cols.t_k, np.broadcast_to(want, (48, 29)), rtol=1e-6)
    assert cols.points == ((-24.75, -70.50),)
    assert [r.store for r in cols.inputs] == [
        str(s2.resolve()),
        str(s1.resolve()),
        str(static.resolve()),
    ]


def test_only_the_time_range_is_kept_and_stores_outside_it_are_not_inputs(tmp_path):
    s1 = write_pl_store(tmp_path / "a.zarr", times=hourly("2023-06-01T00:00", 24), lat=LAT, lon=LON)
    s2 = write_pl_store(tmp_path / "b.zarr", times=hourly("2023-06-02T00:00", 24), lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON)
    cols = read_site(
        [s1, s2],
        lat=-24.63,
        lon=-70.40,
        rule=Nearest(),
        start="2023-06-02T06:00",
        end="2023-06-02T12:00",
        static_store=static,
    )
    np.testing.assert_array_equal(cols.times, hourly("2023-06-02T06:00", 6))
    assert [r.store for r in cols.inputs] == [str(s2.resolve()), str(static.resolve())]


def _read(stores, static, **kw):
    args = dict(lat=-24.63, lon=-70.40, rule=Nearest(), static_store=static)
    return read_site(stores, **{**args, **kw})


def test_a_duplicate_hour_across_stores_is_an_error(tmp_path):
    s1 = write_pl_store(tmp_path / "a.zarr", times=hourly("2023-06-01T00:00", 24), lat=LAT, lon=LON)
    s2 = write_pl_store(tmp_path / "b.zarr", times=hourly("2023-06-01T23:00", 2), lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON)
    with pytest.raises(SiteReadError, match=r"1 duplicate hours.*2023-06-01T23:00:00Z"):
        _read([s1, s2], static, start="2023-06-01", end="2023-06-02T01:00")


def test_a_missing_hour_is_an_error(tmp_path):
    times = np.delete(hourly("2023-06-01T00:00", 24), 7)
    s1 = write_pl_store(tmp_path / "a.zarr", times=times, lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON)
    with pytest.raises(SiteReadError, match="1 expected hours missing, first 2023-06-01T07:00:00Z"):
        _read([s1], static, start="2023-06-01", end="2023-06-02")


def test_an_hour_outside_the_expected_grid_is_an_error(tmp_path):
    s1 = write_pl_store(tmp_path / "a.zarr", times=hourly("2023-06-01T00:00", 24), lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON)
    night = HourGrid(utc_hours=(23, *range(12)))
    with pytest.raises(SiteReadError, match="11 hours not in the expected hour grid"):
        _read([s1], static, start="2023-06-01", end="2023-06-02", expected=night)


def test_a_night_window_on_every_fourth_day_reads_when_complete(tmp_path):
    # Chile-like night window (23–11 UTC), Timau-like every 4th day.
    hours = (23, *range(12))
    days = [np.datetime64("2023-06-01") + np.timedelta64(4 * k, "D") for k in range(3)]
    times = np.sort(
        np.array(
            [np.datetime64(d, "s") + np.timedelta64(h * 3600, "s") for d in days for h in hours]
        )
    )
    s1 = write_pl_store(tmp_path / "a.zarr", times=times, lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON)
    cols = _read(
        [s1], static, start="2023-06-01", end="2023-06-10", expected=HourGrid(hours, day_step=4)
    )
    np.testing.assert_array_equal(cols.times, times)
    assert cols.settings["expected_hours"] == {"utc_hours": sorted(hours), "day_step": 4}


def _oro(la, lo):
    # 1500 m at the site's nearest point (-24.75, -70.50); 3000 m everywhere else.
    return np.where(np.isclose(la, -24.75) & np.isclose(lo, -70.50), 1500.0, 3000.0)


def test_levels_at_or_below_the_cells_orography_are_masked_and_counted(tmp_path):
    s1 = write_pl_store(tmp_path / "a.zarr", times=hourly("2023-06-01T00:00", 24), lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON, orography_m=_oro)

    cols = _read([s1], static, start="2023-06-01", end="2023-06-02")

    # Standard-atmosphere heights: 850 hPa is 1457 m (masked), 825 hPa 1700 m (kept).
    assert cols.orography_m == pytest.approx(1500.0, abs=0.01)
    assert cols.surface_height_m == cols.orography_m
    assert cols.z_m[0, 6] == pytest.approx(1457.3, abs=0.1)  # metres, not geopotential
    assert cols.masked_levels == 7 * 24
    assert not cols.level_valid[:, :7].any() and cols.level_valid[:, 7:].all()
    assert cols.qc["level_below_orography"] == 7 * 24
    # Values are returned as read, not blanked.
    assert np.isfinite(cols.t_k).all()


def test_the_unmasked_variant_keeps_every_level_and_still_reports_the_orography(tmp_path):
    s1 = write_pl_store(tmp_path / "a.zarr", times=hourly("2023-06-01T00:00", 24), lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON, orography_m=_oro)

    cols = _read([s1], static, start="2023-06-01", end="2023-06-02", mask_underground=False)

    assert cols.masked_levels == 0
    assert cols.level_valid.all()
    assert cols.surface_height_m is None
    assert cols.orography_m == pytest.approx(1500.0, abs=0.01)
    assert cols.settings["mask_underground"] is False


def test_masking_needs_the_static_store(tmp_path):
    s1 = write_pl_store(tmp_path / "a.zarr", times=hourly("2023-06-01T00:00", 24), lat=LAT, lon=LON)
    with pytest.raises(ValueError, match="static store"):
        _read([s1], None, start="2023-06-01", end="2023-06-02")
    cols = _read([s1], None, start="2023-06-01", end="2023-06-02", mask_underground=False)
    assert np.isnan(cols.orography_m) and cols.level_valid.all()


def test_cloud_fraction_is_returned_when_every_store_has_it(tmp_path):
    def cc(t, p, la, lo):
        return 0.5 + 0.0 * t + 0.0 * la + 0.0 * lo + 0.0 * p

    times = hourly("2023-06-01T00:00", 24)
    with_cc = write_pl_store(tmp_path / "a.zarr", times=times, lat=LAT, lon=LON, cc=cc)
    without = write_pl_store(
        tmp_path / "b.zarr", times=hourly("2023-06-02T00:00", 24), lat=LAT, lon=LON
    )
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON)

    one = _read([with_cc], static, start="2023-06-01", end="2023-06-02")
    assert one.cc is not None and one.cc.shape == (24, 29)
    np.testing.assert_allclose(one.cc, 0.5)
    both = _read([with_cc, without], static, start="2023-06-01", end="2023-06-03")
    assert both.cc is None


def test_select_keeps_the_chosen_hours_and_their_masked_counts(tmp_path):
    s1 = write_pl_store(tmp_path / "a.zarr", times=hourly("2023-06-01T00:00", 24), lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON, orography_m=_oro)
    cols = _read([s1], static, start="2023-06-01", end="2023-06-02")
    keep = np.zeros(24, bool)
    keep[[2, 5, 9]] = True

    sub = cols.select(keep)

    np.testing.assert_array_equal(sub.times, cols.times[[2, 5, 9]])
    np.testing.assert_array_equal(sub.t_k, cols.t_k[[2, 5, 9]])
    assert sub.masked_levels == 7 * 3
    assert sub.inputs == cols.inputs and sub.settings == cols.settings
    with pytest.raises(ValueError, match="shape"):
        cols.select(keep[:5])


def test_every_fourth_day_restarts_each_month_as_the_downloads_do(tmp_path):
    # The planner keeps days 1, 5, 9, … 29 of each month (download/requests.py), so
    # after 29 January the next stored day is 1 February, not 2 February.
    days = [np.datetime64(f"2023-01-{d:02d}") for d in (1, 5, 9, 13, 17, 21, 25, 29)]
    days += [np.datetime64(f"2023-02-{d:02d}") for d in (1, 5)]
    times = np.array(
        [np.datetime64(d, "s") + np.timedelta64(h * 3600, "s") for d in days for h in range(24)]
    )
    s1 = write_pl_store(tmp_path / "a.zarr", times=times, lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON)
    cols = _read([s1], static, start="2023-01-01", end="2023-02-06", expected=HourGrid(day_step=4))
    np.testing.assert_array_equal(cols.times, times)


def test_the_planner_and_the_hour_grid_keep_the_same_days():
    # The every-4th-day rule lives in two places; they must agree over a whole year.
    from astroseeing.download.requests import Area, plan_requests

    plans = plan_requests(
        "pl",
        "timau@every4d",
        dt.date(2003, 1, 1),
        dt.date(2003, 12, 31),
        Area(-9.5, 123.5, -10.0, 124.0),
        day_step=4,
    )
    planned = sorted({t for p in plans for t in p.expected()["times"]})
    start = np.datetime64("2003-01-01T00:00", "s").astype(np.int64)
    end = np.datetime64("2004-01-01T00:00", "s").astype(np.int64)
    grid = HourGrid(day_step=4).times(int(start), int(end))
    assert [str(np.datetime64(int(t), "s"))[:16] for t in grid] == planned


def test_levels_can_be_chosen_and_must_be_stored(tmp_path):
    s1 = write_pl_store(tmp_path / "a.zarr", times=hourly("2023-06-01T00:00", 24), lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON)
    no70 = [p for p in ERA5_LEVELS_HPA if p != 70.0]  # Haslebacher's 28 levels
    cols = _read([s1], static, start="2023-06-01", end="2023-06-02", levels=no70)
    np.testing.assert_array_equal(cols.p_hpa, no70)
    assert cols.t_k.shape == (24, 28)
    assert cols.settings["levels_hpa"] == no70
    with pytest.raises(SiteReadError, match=r"\[1\.0\] hPa are not stored"):
        _read([s1], static, start="2023-06-01", end="2023-06-02", levels=[1000.0, 1.0])


def test_a_missing_orography_is_an_error_not_a_column_masked_without_count(tmp_path):
    s1 = write_pl_store(tmp_path / "a.zarr", times=hourly("2023-06-01T00:00", 24), lat=LAT, lon=LON)
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON, orography_m=np.nan)
    with pytest.raises(SiteReadError, match="orography at the site is not finite"):
        _read([s1], static, start="2023-06-01", end="2023-06-02")


def test_non_finite_values_are_counted_not_hidden(tmp_path):
    def t_with_gap(t, p, la, lo):
        return np.where((p == 500.0) & (t == t.min()), np.nan, 250.0 + 0.0 * la + 0.0 * lo)

    def cc(t, p, la, lo):
        return np.where(p == 300.0, np.nan, 0.1 + 0.0 * t + 0.0 * la + 0.0 * lo)

    s1 = write_pl_store(
        tmp_path / "a.zarr",
        times=hourly("2023-06-01T00:00", 24),
        lat=LAT,
        lon=LON,
        fields={"t": t_with_gap},
        cc=cc,
    )
    static = write_static_store(tmp_path / "st.zarr", lat=LAT, lon=LON)
    cols = _read([s1], static, start="2023-06-01", end="2023-06-02")
    assert cols.qc["level_nonfinite"] == 1
    assert cols.qc["cc_nonfinite"] == 24
    assert not cols.level_valid[0, 15] and cols.level_valid[1:, 15].all()
