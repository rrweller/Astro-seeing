"""The map layers on hand-made nights (F1 spec Module 7 map layers; ticket #65).

A 2 × 2 map near Kongsberg, with each forecast model's run written by hand on its own
grid (``AreaRun``): ICON-EU on the map grid itself, GFS and IFS on 0.25° grids whose
points fall between map cells, and MEPS, which is never on the map. The Sun is the real
one (``cell_suns``). Expected values are worked out from the hand-made clouds and
seeings, never by calling the layer code's own rules.
"""

from __future__ import annotations

import datetime as dt
import hashlib

import numpy as np
import pytest

from astroseeing.forecast.grid import MapGrid
from astroseeing.forecast.publish.layers import build_layers
from astroseeing.forecast.settings import load_settings
from astroseeing.forecast.store.areas import AreaRun
from astroseeing.forecast.tonight.sun import cell_suns
from astroseeing.physics.optics import j_from_seeing

UTC = dt.UTC
SETTINGS = load_settings()
MODELS = [SETTINGS.models[m] for m in SETTINGS.areas["kongsberg"].models]
RUN_TIME = dt.datetime(2026, 11, 26, 6, tzinfo=UTC)

# map cells: 59.75 and 59.6875° N (rows, north first) × 9.625 and 9.6875° E (columns)
GRID = MapGrid(59.75, 9.625, 0.0625, 0.0625, 2, 2)
# GFS and IFS points at 59.5/59.75° N × 9.5/9.75° E: both map rows take 59.75° N; the
# west column (9.625° E, exactly halfway) takes 9.5° E, the east column 9.75° E
COARSE = (np.array([59.75, 59.5]), np.array([9.5, 9.75]))
FINE = (np.array([59.6875, 59.75]), np.array([9.625, 9.6875]))  # ICON-EU, south first


def area_run(model, lats_lons, steps, cloud, seeing, ground=300.0, run_id=1, expected=None):
    """A run written by hand: ``cloud`` and ``seeing`` give each point's value as an
    array of the source grid's shape (the same at every step)."""
    lats, lons = lats_lons
    shape = (len(steps), lats.size, lons.size)
    m = SETTINGS.models[model]
    return AreaRun(
        area="kongsberg",
        model=model,
        run_id=run_id,
        run_time=RUN_TIME,
        steps_expected=tuple(expected if expected is not None else m.steps_h),
        steps=tuple(steps),
        lat=lats,
        lon=lons,
        total_cloud_pct=np.broadcast_to(np.asarray(cloud, float), shape).copy(),
        j_free=np.broadcast_to(j_from_seeing(np.asarray(seeing, float)), shape).copy(),
        model_ground_m=np.full((lats.size, lons.size), ground),
    )


def suns(now, ephemeris):
    """Each map cell's Sun, ``[row][column]``."""
    return cell_suns(GRID.lats, GRID.lons, now, *ephemeris)


def counted_rows(cell, now):
    """Tonight's dark rows from the current hour on (hh:00 counts until hh:30)."""
    current = (now + dt.timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
    t = cell.track
    return [h for h, a in zip(t.hours, t.altitude_deg, strict=True) if a < -18 and h >= current]


def layer(result, name):
    entry = result.entries[name]
    dtype = np.dtype(entry["dtype"]).newbyteorder("<")
    return np.frombuffer(result.files[entry["file"]], dtype=dtype).reshape(entry["shape"])


def build(runs, now, ephemeris, slider=None):
    cell_suns = suns(now, ephemeris)
    hours = slider or cell_suns[0][0].track.hours
    return build_layers(
        GRID,
        MODELS,
        runs,
        cell_suns,
        hours,
        now,
        cloud_classes=SETTINGS.cloud_classes,
        stale_after_h=SETTINGS.run_rules.stale_after_h,
    ), cell_suns


EVENING = dt.datetime(2026, 11, 26, 18, 10, tzinfo=UTC)


def four_models():
    every_hour = range(49)
    return {
        # ICON-EU: clear everywhere, seeing 0.81″
        "icon_eu": area_run("icon_eu", FINE, every_hour, 0.0, 0.81, ground=346.6),
        # GFS: its west point column clear (5 %), the east one cloudy (80 %)
        "gfs": area_run(
            "gfs",
            COARSE,
            every_hour,
            [[5.0, 80.0], [5.0, 80.0]],
            [[0.62, 0.9], [0.62, 0.9]],
            ground=327.4,
        ),
        # IFS: every third hour, clear, seeing 0.55″
        "ifs": area_run("ifs", COARSE, range(0, 49, 3), 2.0, 0.55, ground=-3.4),
        # MEPS (regional, never on the map): cloudy everywhere
        "meps": area_run("meps", FINE, every_hour, 100.0, 2.0),
    }


def test_a_clear_evening_counts_hours_by_model_agreement_in_each_cell(ephemeris):
    result, cell_suns = build(four_models(), EVENING, ephemeris)
    rows = [[counted_rows(c, EVENING) for c in r] for r in cell_suns]
    n = len(rows[0][0])
    assert 9 <= n <= 12  # a late-November night at 60° N, from 18 UTC on

    # west column: every model clear → all n counted hours mostly clear. East column:
    # GFS cloudy, so only IFS's hours (00, 03, … UTC: 2 of 3 clear) are mostly clear;
    # the hours between have 1 of 2 clear, not more than half
    clear = layer(result, "clear_left")
    for i in range(2):
        assert clear[i, 0] == len(rows[i][0])
        assert clear[i, 1] == sum(h.hour % 3 == 0 for h in rows[i][1])
    np.testing.assert_array_equal(layer(result, "counted_left"), [[n, n], [n, n]])
    np.testing.assert_array_equal(layer(result, "incomplete_left"), np.zeros((2, 2)))

    # each family's median seeing (milli-arcsec) over its counted hours
    np.testing.assert_array_equal(layer(result, "seeing_fa_icon"), np.full((2, 2), 810))
    np.testing.assert_array_equal(layer(result, "seeing_fa_gfs"), [[620, 900], [620, 900]])
    np.testing.assert_array_equal(layer(result, "seeing_fa_ifs"), np.full((2, 2), 550))

    # model ground, whole metres, from each family's own point
    np.testing.assert_array_equal(layer(result, "model_ground_icon"), np.full((2, 2), 347))
    np.testing.assert_array_equal(layer(result, "model_ground_gfs"), np.full((2, 2), 327))
    np.testing.assert_array_equal(layer(result, "model_ground_ifs"), np.full((2, 2), -3))

    # dark time left: the cells' own Sun
    dark = layer(result, "dark_left_min")
    for i in range(2):
        for j in range(2):
            assert dark[i, j] == cell_suns[i][j].dark_left_min > 500


def test_the_hour_slider_has_each_models_own_cloud_and_no_value_where_it_has_none(ephemeris):
    result, cell_suns = build(four_models(), EVENING, ephemeris)
    hours = cell_suns[0][0].track.hours
    entry = result.entries["total_cloud_ifs"]
    assert entry["hours"] == [h.strftime("%Y-%m-%dT%H:%M:%SZ") for h in hours]
    assert entry["shape"] == [24, 2, 2] and entry["codes"] == {"255": "no value"}
    ifs = layer(result, "total_cloud_ifs")
    for k, h in enumerate(hours):  # IFS's in-between hours stay without a value
        assert (ifs[k] == (2 if h.hour % 3 == 0 else 255)).all()
    gfs = layer(result, "total_cloud_gfs")
    assert (gfs[:, :, 0] == 5).all() and (gfs[:, :, 1] == 80).all()
    assert (layer(result, "total_cloud_icon") == 0).all()


def test_meps_is_not_on_the_map_and_changes_nothing(ephemeris):
    runs = four_models()
    with_meps, _ = build(runs, EVENING, ephemeris)
    without = {k: v for k, v in runs.items() if k != "meps"}
    without_meps, _ = build(without, EVENING, ephemeris)
    assert not any("meps" in name for name in with_meps.entries)
    assert with_meps.files == without_meps.files
    assert with_meps.entries == without_meps.entries


def test_one_model_alone_makes_every_counted_hour_incomplete_code_254(ephemeris):
    runs = {"gfs": four_models()["gfs"]}
    result, cell_suns = build(runs, EVENING, ephemeris)
    n = len(counted_rows(cell_suns[0][0], EVENING))
    assert result.entries["clear_left"]["codes"] == {
        "254": "all incomplete",
        "255": "no counted hours",
    }
    np.testing.assert_array_equal(layer(result, "clear_left"), np.full((2, 2), 254))
    np.testing.assert_array_equal(layer(result, "counted_left"), np.full((2, 2), n))
    np.testing.assert_array_equal(layer(result, "incomplete_left"), np.full((2, 2), n))
    # the models with no run: no seeing, no ground, no cloud; nothing filled
    for family in ("icon", "ifs"):
        assert (layer(result, f"seeing_fa_{family}") == 65535).all()
        assert (layer(result, f"model_ground_{family}") == -32768).all()
        assert (layer(result, f"total_cloud_{family}") == 255).all()
    # GFS's own seeing still shows: the seeing range doesn't need two models
    np.testing.assert_array_equal(layer(result, "seeing_fa_gfs"), [[620, 900], [620, 900]])


def test_after_dark_time_ends_there_are_no_counted_hours_code_255(ephemeris):
    dawn = dt.datetime(2026, 11, 27, 6, 40, tzinfo=UTC)  # dark ended, the Sun not yet up
    result, cell_suns = build(four_models(), dawn, ephemeris)
    assert all(c.track.night == dt.date(2026, 11, 26) for r in cell_suns for c in r)
    np.testing.assert_array_equal(layer(result, "clear_left"), np.full((2, 2), 255))
    for name in ("counted_left", "incomplete_left", "dark_left_min"):
        np.testing.assert_array_equal(layer(result, name), np.zeros((2, 2)))
    for family in ("gfs", "icon", "ifs"):  # no counted hours: no seeing median
        assert (layer(result, f"seeing_fa_{family}") == 65535).all()


def test_a_partial_run_leaves_its_missing_hours_without_a_value(ephemeris):
    runs = four_models()
    # ICON-EU's run lacks steps 13-48 (hours from 19 UTC on): those hours have GFS and
    # IFS only; the hour slider shows ICON-EU's lacking hours as no value
    runs["icon_eu"] = area_run("icon_eu", FINE, range(13), 0.0, 0.81)
    result, cell_suns = build(runs, EVENING, ephemeris)
    hours = cell_suns[0][0].track.hours
    icon = layer(result, "total_cloud_icon")
    for k, h in enumerate(hours):
        assert (icon[k] == (0 if h <= RUN_TIME + dt.timedelta(hours=12) else 255)).all()
    # east column after 19 UTC: GFS cloudy and IFS clear on IFS's hours (1 of 2), and
    # GFS alone between them (incomplete); at 18 UTC ICON-EU and IFS are clear (2 of 3)
    rows = counted_rows(cell_suns[0][1], EVENING)
    clear, incomplete = layer(result, "clear_left"), layer(result, "incomplete_left")
    assert clear[0, 1] == 1  # 18 UTC only
    assert incomplete[0, 1] == sum(h.hour % 3 != 0 for h in rows if h.hour != 18)


def test_each_entry_describes_its_file_exactly(ephemeris):
    result, _ = build(four_models(), EVENING, ephemeris)
    expected = {"clear_left", "counted_left", "incomplete_left", "dark_left_min"} | {
        f"{kind}_{family}"
        for kind in ("seeing_fa", "total_cloud", "model_ground")
        for family in ("gfs", "icon", "ifs")
    }
    assert set(result.entries) == expected
    assert set(result.files) == {e["file"] for e in result.entries.values()}
    sizes = {"uint8": 1, "uint16": 2, "int16": 2}
    for name, e in result.entries.items():
        data = result.files[e["file"]]
        assert e["file"].startswith(name + ".")
        assert len(data) == sizes[e["dtype"]] * int(np.prod(e["shape"]))
        assert e["sha256"] == hashlib.sha256(data).hexdigest()
    assert result.entries["seeing_fa_gfs"]["scale"] == pytest.approx(0.001)
    assert result.entries["seeing_fa_gfs"]["codes"] == {"65535": "none"}
    # little-endian on disk whatever the machine: 900 mas is 0x0384 → bytes 84 03
    gfs = result.files[result.entries["seeing_fa_gfs"]["file"]]
    assert gfs[2:4] == bytes([0x84, 0x03])
