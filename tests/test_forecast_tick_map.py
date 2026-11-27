"""The map layers through the whole tick (F1 spec Testing seam 1, Module 7 map layers;
ticket #65).

The tick test's CT in miniature (``forecast_world``): the GFS samples of the 2026-11-26
06z run on a small box round Kongsberg, and in the slow test ICON-EU beside it. Each
cell's expected values come from ``tonight()`` called directly on that cell's own hours,
built here from the area grid file the tick stored (read with numpy, not the tick's
reader) at the cell's nearest grid point, and the cell's own ``sun_track``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging

import numpy as np
import pytest

from astroseeing.forecast.grid import nearest_point
from astroseeing.forecast.schemas import validate
from astroseeing.forecast.tonight import (
    HourTable,
    HourValue,
    Missing,
    ModelHours,
    RunInfo,
    sun_track,
    tonight,
)
from astroseeing.physics.optics import seeing_arcsec

from forecast_world import DAY, World
from icon_eu_samples import IconWorld

SIZES = {"uint8": 1, "uint16": 2, "int16": 2}


@pytest.fixture
def world(tmp_path, ephemeris):
    w = World(tmp_path, ephemeris)
    yield w
    w.close()


def read_layers(w) -> dict[str, np.ndarray]:
    """Every layer of the current set, read as its ``latest.json`` entry describes it,
    after checking the entry against the file."""
    latest = w.latest()
    folder = w.paths.products / latest["set_path"]
    out = {}
    for name, e in latest["layers"].items():
        data = (folder / e["file"]).read_bytes()
        assert e["sha256"] == hashlib.sha256(data).hexdigest(), name
        assert len(data) == SIZES[e["dtype"]] * int(np.prod(e["shape"])), name
        dtype = np.dtype(e["dtype"]).newbyteorder("<")
        out[name] = np.frombuffer(data, dtype=dtype).reshape(e["shape"])
    return out


def stored_area_run(w, model: str) -> dict:
    """The newest area grid the tick stored for ``model``, read straight from its file."""
    (path,) = sorted((w.paths.products / "areas" / "kongsberg").glob(f"{model}-*.npz"))[-1:]
    with np.load(path) as z:
        meta = json.loads(str(z["meta"]))
        return {**meta, **{k: z[k] for k in z.files if k != "meta"}}


def cell_tonight(w, models, i: int, j: int, now: dt.datetime):
    """``tonight()`` on map cell (i, j)'s own hours: each model's stored values at the
    grid point nearest the cell centre (the place rule), and the cell's own Sun."""
    g = w.latest()["grid"]
    lat, lon = g["lat_north"] - i * g["dlat"], g["lon_west"] + j * g["dlon"]
    sun = sun_track(lat, lon, now, *w.ephemeris)
    table = []
    for m in models:
        r = stored_area_run(w, m.id)
        lat2, lon2 = np.meshgrid(r["lat"], r["lon"], indexing="ij")
        p, q = nearest_point(lat2, lon2, lat, lon)
        run_time = dt.datetime.fromisoformat(r["run_time"].replace("Z", "+00:00"))
        expected, values = r["steps_expected"], []
        for t in sun.hours:  # the place store's rules for a run's hours (store.hours_for)
            step = (t - run_time) / dt.timedelta(hours=1)
            if not expected[0] <= step <= expected[-1]:
                values.append(Missing("no_run"))
            elif step not in expected:
                values.append(Missing("off_step"))
            elif step not in r["steps"]:
                values.append(Missing("partial"))
            else:
                k = r["steps"].index(step)
                jf = float(r["j_free"][k, p, q])
                values.append(HourValue(float(r["total_cloud_pct"][k, p, q]),
                                        None if np.isnan(jf) else jf))  # fmt: skip
        info = RunInfo(r["run_id"], run_time)
        table.append(ModelHours(m.id, m.family, m.regional, info, tuple(values)))
    s = w.settings
    return tonight(
        HourTable(sun.night, sun.hours, tuple(table)),
        sun,
        now,
        cloud_classes=s.cloud_classes,
        stale_after_h=s.run_rules.stale_after_h,
    ), (p, q)


def check_cells(w, layers, models, now, cells):
    for i, j in cells:
        t, _ = cell_tonight(w, models, i, j, now)
        if t.counted_hours == 0:
            assert layers["clear_left"][i, j] == 255
        elif t.nothing_to_count is not None:
            assert layers["clear_left"][i, j] == 254
        else:
            assert layers["clear_left"][i, j] == t.clear_hours
        assert layers["counted_left"][i, j] == t.counted_hours
        assert layers["incomplete_left"][i, j] == t.incomplete_hours
        for m in models:
            got = layers[f"seeing_fa_{m.family}"][i, j]
            if t.seeing is None or m.family not in t.seeing.per_family:
                assert got == 65535
            else:
                assert got == round(t.seeing.per_family[m.family] * 1000)


def test_the_map_layers_equal_tonight_called_on_each_cells_hours(world, caplog):
    caplog.set_level(logging.INFO, logger="astroseeing.forecast.tick")
    for hour in range(24):
        report = world.at(DAY + dt.timedelta(hours=hour))
        assert report.skipped is None and report.map_seconds > 0
    now = DAY + dt.timedelta(hours=23)
    latest = world.latest()
    validate(latest, "f1-latest/1")
    layers = read_layers(world)
    g = latest["grid"]
    assert (g["nlat"], g["nlon"]) == (5, 5)  # the samples' GFS points: the map grid here
    gfs = world.settings.models["gfs"]
    assert set(layers) == {
        "clear_left", "counted_left", "incomplete_left", "dark_left_min",
        "seeing_fa_gfs", "total_cloud_gfs", "model_ground_gfs",
    }  # fmt: skip

    # GFS alone: every counted hour has one family, so every cell is "all incomplete"
    assert (layers["clear_left"] == 254).all()
    assert (layers["incomplete_left"] == layers["counted_left"]).all()
    assert (layers["counted_left"] > 0).all()
    check_cells(world, layers, [gfs], now, [(i, j) for i in range(5) for j in range(5)])

    # the cell at GFS's point 59.75° N 9.75° E is where Kongsberg's own values come
    # from, and Kongsberg (162 m) is raised to that point's ground (327 m): so the map's
    # J there is the place's J, hour by hour (map and table can't disagree)
    r = stored_area_run(world, "gfs")
    _, (p, q) = cell_tonight(world, [gfs], 2, 2, now)
    assert (r["lat"][p], r["lon"][q]) == (59.75, 9.75)
    place = world.place_file()
    run_time = dt.datetime.fromisoformat(r["run_time"].replace("Z", "+00:00"))
    for h in place["hours"]:
        t = dt.datetime.fromisoformat(h["time"].replace("Z", "+00:00"))
        k = r["steps"].index(round((t - run_time) / dt.timedelta(hours=1)))
        fa = h["models"]["gfs"]["seeing"]["osborn_sarazin"]["free_atmosphere_arcsec"]
        assert float(seeing_arcsec(r["j_free"][k, p, q])) == pytest.approx(fa, rel=1e-9)
        assert r["total_cloud_pct"][k, p, q] == h["models"]["gfs"]["cloud"]["total_pct"]
        # the hour slider shows the same cloud in whole percent
        slider = latest["layers"]["total_cloud_gfs"]["hours"]
        assert layers["total_cloud_gfs"][slider.index(h["time"]), 2, 2] == int(
            np.floor(h["models"]["gfs"]["cloud"]["total_pct"] + 0.5)
        )
    assert layers["model_ground_gfs"][2, 2] == round(place["models"]["gfs"]["model_ground_m"])
    assert [h["time"] for h in place["hours"]] == latest["layers"]["total_cloud_gfs"]["hours"]

    # each tick logs how long the map took
    assert any("map layers" in rec.getMessage() for rec in caplog.records)


def test_before_any_run_the_map_has_no_values_and_after_dark_time_no_counted_hours(world):
    early = world.at(DAY + dt.timedelta(hours=8))  # before the run is out
    assert early.skipped is None
    layers = read_layers(world)
    for name in ("total_cloud_gfs",):
        assert (layers[name] == 255).all()
    assert (layers["seeing_fa_gfs"] == 65535).all()
    assert (layers["model_ground_gfs"] == -32768).all()

    for hour in (10, 30):  # the run arrives at 10 UTC; 06 UTC on the 27th is after dark
        world.at(DAY + dt.timedelta(hours=hour))
    layers = read_layers(world)
    assert (layers["clear_left"] == 255).all()
    assert (layers["counted_left"] == 0).all() and (layers["dark_left_min"] == 0).all()
    assert (layers["seeing_fa_gfs"] == 65535).all()  # no counted hours, no median


@pytest.mark.slow  # ~40 s: 5244 files from the fake DWD
def test_icon_eu_sets_the_map_grid_and_gfs_shows_as_blocks(tmp_path, ephemeris):
    w = IconWorld(tmp_path, ephemeris)
    try:
        for hour in (9, 10, 19):
            assert w.at(DAY + dt.timedelta(hours=hour)).skipped is None
        now = DAY + dt.timedelta(hours=19)
        latest = w.latest()
        validate(latest, "f1-latest/1")
        g = latest["grid"]
        assert (g["nlat"], g["nlon"], g["dlat"]) == (17, 17, 0.0625)  # ICON-EU's own points
        layers = read_layers(w)
        models = [w.settings.models["gfs"], w.settings.models["icon_eu"]]
        cells = [(0, 0), (0, 16), (16, 0), (16, 16), (8, 8), (2, 2), (3, 2), (5, 11), (10, 6)]
        check_cells(w, layers, models, now, cells)
        assert not (layers["clear_left"] == 254).all()  # two families: hours are complete

        # GFS's values come in blocks: a map cell takes the GFS point nearest its centre,
        # the southern/western one when exactly halfway, so each GFS point covers 4 × 4
        # map cells inside the box. The GFS latitude (longitude) for a centre c is
        # ceil((c - 0.125) / 0.25) × 0.25: exactly halfway, that is the lower point.
        r = stored_area_run(w, "gfs")

        def gfs_index(centres, coords):
            want = np.ceil((np.asarray(centres) - 0.125) / 0.25 - 1e-9) * 0.25
            return [int(np.flatnonzero(np.isclose(coords, c))[0]) for c in want]

        lats = g["lat_north"] - g["dlat"] * np.arange(g["nlat"])
        lons = g["lon_west"] + g["dlon"] * np.arange(g["nlon"])
        rows, cols = gfs_index(lats, r["lat"]), gfs_index(lons, r["lon"])
        expected = np.floor(r["model_ground_m"][np.ix_(rows, cols)] + 0.5)
        np.testing.assert_array_equal(layers["model_ground_gfs"], expected)
        assert sorted(np.unique(rows, return_counts=True)[1]) == [2, 3, 4, 4, 4]
        assert len(np.unique(layers["model_ground_icon"])) > 25
    finally:
        w.close()
