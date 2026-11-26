"""The MEPS source adapter against saved THREDDS samples (F1 spec Testing seam 3; ticket #57).

The samples in ``tests/fixtures/forecast/meps/`` are real OPeNDAP responses from MET
Norway's THREDDS server (MEPS deterministic, CC BY 4.0 / NLOD; see the README there).
"""

from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np
import pytest

from astroseeing.forecast.grid import nearest_point
from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.settings import Area, Box, load_settings
from astroseeing.forecast.sources import FetchResult, FormatMismatch
from astroseeing.forecast.sources.dap2 import parse_das, parse_dods
from astroseeing.forecast.sources.meps import (
    LambertConformal,
    MepsAdapter,
    Window,
    rotate_to_east_north,
)

from fake_http import FakeHttpServer
from meps_samples import (
    BOX_1DEG,
    SAMPLE_RUN,
    copy_samples,
    edit_dods,
    sample_area,
    sample_folder,
    sample_steps,
    serve_meps,
    without_level,
)

MEPS = load_settings().models["meps"]

#: MEPS's projection, from the ``projection_lambert`` attributes of its THREDDS files.
MEPS_LAMBERT = LambertConformal(
    standard_parallels_deg=(63.3, 63.3),
    central_meridian_deg=15.0,
    origin_lat_deg=63.3,
    earth_radius_m=6371000.0,
)


def rotate(u: float, v: float, lon: float) -> tuple[float, float]:
    east, north = rotate_to_east_north(np.array([u]), np.array([v]), np.array([lon]), MEPS_LAMBERT)
    return float(east[0]), float(north[0])


def test_a_tangent_cone_has_the_sine_of_its_standard_parallel_as_cone_constant():
    assert MEPS_LAMBERT.cone == pytest.approx(math.sin(math.radians(63.3)), rel=1e-15)


def test_wind_rotation_known_answer():
    # East of the central meridian by 30°/n the grid is turned by exactly 30°: the grid's
    # x axis points 30° south of east, its y axis 30° west of north (the convergence
    # angle n(λ - λ0) of the Lambert conformal conic; Snyder 1987, ch. 15).
    lon = 15.0 + 30.0 / MEPS_LAMBERT.cone
    s, c = 0.5, math.sqrt(3) / 2
    assert rotate(10.0, 0.0, lon) == pytest.approx((10 * c, -10 * s))
    assert rotate(0.0, 10.0, lon) == pytest.approx((10 * s, 10 * c))
    # on the central meridian grid and true directions agree
    assert rotate(3.0, -4.0, 15.0) == pytest.approx((3.0, -4.0))
    # west of it (Kongsberg, 9.652° E) the turn is the other way: a pure x wind gains a
    # northward part
    angle = math.radians(MEPS_LAMBERT.cone * (9.652 - 15.0))
    east, north = rotate(10.0, 0.0, 9.652)
    assert east == pytest.approx(10 * math.cos(angle))
    assert north == pytest.approx(-10 * math.sin(angle)) and north > 0


def test_rotation_keeps_the_wind_speed():
    rng = np.random.default_rng(1)
    u, v = rng.normal(0, 20, 50), rng.normal(0, 20, 50)
    lon = rng.uniform(-18, 54, 50)
    east, north = rotate_to_east_north(u, v, lon, MEPS_LAMBERT)
    np.testing.assert_allclose(np.hypot(east, north), np.hypot(u, v), rtol=1e-12)


# -- fetch and read against the saved samples ------------------------------------------


@pytest.fixture
def thredds():
    with FakeHttpServer() as s:
        yield s


def adapter_for(server, sample_set: str = "kongsberg", areas=None) -> MepsAdapter:
    return MepsAdapter(
        MEPS,
        HttpClient(timeout_s=5),
        areas or {"kongsberg": sample_area(sample_set)},
        base_url=server.url,
    )


def fetch_and_read(server, tmp_path, sample_set="kongsberg"):
    meps = adapter_for(server, sample_set)
    serve_meps(server, sample_set)
    steps = sample_steps(sample_set)
    fetched = meps.fetch(SAMPLE_RUN, sample_area(sample_set), steps, tmp_path / "raw")
    return fetched, meps.read(fetched)


def test_reads_every_step_0_to_48_round_kongsberg(thredds, tmp_path):
    fetched, f = fetch_and_read(thredds, tmp_path)
    assert not fetched.missing_steps and len(fetched.files) == 3 + 49
    assert all(x.host == "thredds" and len(x.sha256) == 64 for x in fetched.files)
    assert all(x.path.parent == tmp_path / "raw" for x in fetched.files)
    assert f.grid_shape == (5, 5) and f.n_steps == 49
    assert f.valid_times[0] == np.datetime64("2026-11-26T06:00:00")
    assert f.valid_times[-1] == np.datetime64("2026-11-28T06:00:00")
    assert f.level_count == 13 and list(f.pressure_hpa) == list(MEPS.pressure_levels_hpa)
    assert f.pressure_hpa[0] == 1000 and f.pressure_hpa[-1] == 50  # bottom → top
    assert f.regional and f.family == "meps"
    # heights rise with each level, temperatures and pressures are physical
    assert (np.diff(f.geopotential_height_m, axis=-1) > 0).all()
    assert f.temperature_k.min() > 180 and f.temperature_k.max() < 320
    assert f.surface_pressure_hpa.min() > 900 and f.surface_pressure_hpa.max() < 1060
    clouds = (f.total_cloud_pct, f.low_cloud_pct, f.mid_cloud_pct, f.high_cloud_pct)
    for c in (*clouds, f.level_cloud_pct):
        assert c.min() >= 0 and c.max() <= 100
    # MEPS's cloud fractions arrive within 0-1, so the cloud range rule sets nothing
    assert sum(f.qc.counts.values()) == 0
    assert f.fog["fog_fraction_pct"] is not None and f.fog["visibility_m"] is not None
    assert f.fog["weather_code"] is None and f.fog["dewpoint_depression_2m_k"] is None
    fog = f.fog["fog_fraction_pct"]
    assert fog.min() >= 0 and fog.max() <= 100
    assert not any(np.isnan(getattr(f, n)).any() for n in ("u_ms", "v_ms", "temperature_k"))
    # D47's evidence: Kongsberg's nearest MEPS point is 59.660° N 9.662° E, ground 231 m
    i, j = nearest_point(f.lat, f.lon, 59.669, 9.652)
    assert (f.lat[i, j], f.lon[i, j]) == pytest.approx((59.660, 9.662), abs=5e-4)
    assert f.model_ground_m[i, j] == pytest.approx(231, abs=1)


def test_the_window_holds_every_grid_point_of_the_box(thredds, tmp_path):
    _, f = fetch_and_read(thredds, tmp_path, "box1deg")
    assert f.grid_shape == (51, 29) and f.n_steps == 4
    # the window is every grid point within the box's bounding rectangle in MEPS's
    # projection: its first and last rows and columns are the grid lines just inside
    # the extremes of the box's edges (densely sampled here), so the next line out lies
    # beyond them and no point of the box is left out
    box, step = BOX_1DEG, 2500.0
    t = np.linspace(0, 1, 2001)
    along_lat = box.south + t * (box.north - box.south)
    along_lon = box.west + t * (box.east - box.west)
    edge_lat = np.concatenate([np.full_like(t, box.south), np.full_like(t, box.north),
                               along_lat, along_lat])  # fmt: skip
    edge_lon = np.concatenate([along_lon, along_lon, np.full_like(t, box.west),
                               np.full_like(t, box.east)])  # fmt: skip
    ex, ey = MEPS_LAMBERT.forward(edge_lat, edge_lon)
    wx, wy = MEPS_LAMBERT.forward(f.lat, f.lon)
    x0, x1, y0, y1 = wx[:, 0].mean(), wx[:, -1].mean(), wy[0].mean(), wy[-1].mean()
    assert ex.min() <= x0 < ex.min() + step and ex.max() - step < x1 <= ex.max()
    assert ey.min() <= y0 < ey.min() + step and ey.max() - step < y1 <= ey.max()


def test_winds_are_turned_by_the_grid_angle_the_servers_own_coordinates_show(thredds, tmp_path):
    """An independent check of the rotation's direction: the grid's x axis, as the
    server's latitudes and longitudes place neighbouring points, points θ = n(λ - λ0)
    south of east, as the rotation assumes."""
    _, f = fetch_and_read(thredds, tmp_path, "box1deg")
    lat, lon = np.radians(f.lat), np.radians(f.lon)
    d_east = (lon[:, 2:] - lon[:, :-2]) * np.cos(lat[:, 1:-1])
    d_north = lat[:, 2:] - lat[:, :-2]
    bearing_of_x = np.degrees(np.arctan2(d_north, d_east))  # from east, counter-clockwise
    theta = np.degrees(MEPS_LAMBERT.convergence_rad(f.lon[:, 1:-1]))
    np.testing.assert_allclose(bearing_of_x, -theta, atol=0.01)
    # and the winds read are the grid-relative ones turned by that angle
    raw = parse_dods((sample_folder("box1deg") / "meps_20261126T06Z_f016.dods").read_bytes())
    k = raw["x_wind_pl"].maps["pressure"].values.tolist().index(500.0)
    gx = raw["x_wind_pl"].array.values[0, k].astype(float)
    gy = raw["y_wind_pl"].array.values[0, k].astype(float)
    level = list(f.pressure_hpa).index(500.0)
    th = np.radians(MEPS_LAMBERT.cone * (f.lon - 15.0))
    np.testing.assert_allclose(f.u_ms[0, ..., level], gx * np.cos(th) + gy * np.sin(th))
    np.testing.assert_allclose(f.v_ms[0, ..., level], -gx * np.sin(th) + gy * np.cos(th))


def test_the_request_plan_asks_only_the_needed_fields_in_the_window():
    meps = MepsAdapter(MEPS, None, {"kongsberg": sample_area("kongsberg")})
    das, axes = meps.metadata_requests(SAMPLE_RUN)
    assert das.target == "/thredds/dodsC/mepslatest/meps_det_2_5km_20261126T06Z.ncml.das"
    assert axes.target.endswith(".ncml.dods?x,y")
    window = Window(y0=374, y1=378, x0=302, x1=306)
    grid, *steps = meps.request_plan(SAMPLE_RUN, window, (0, 48))
    yx = "%5B374:1:378%5D%5B302:1:306%5D"
    assert grid.target.endswith(f"?latitude{yx},longitude{yx}")
    assert [s.step for s in steps] == [0, 48]
    fields = steps[1].target.split("?", 1)[1].split(",")
    assert fields[0] == "forecast_reference_time"
    assert {f.split("%5B")[0] for f in fields[1:]} == {
        "geopotential_pl",
        "air_temperature_pl",
        "x_wind_pl",
        "y_wind_pl",
        "cloud_area_fraction_pl",
        "cloud_area_fraction",
        "low_type_cloud_area_fraction",
        "medium_type_cloud_area_fraction",
        "high_type_cloud_area_fraction",
        "surface_air_pressure",
        "surface_geopotential",
        "fog_area_fraction",
        "visibility_in_air",
    }
    assert f"air_temperature_pl%5B48:1:48%5D%5B0:1:12%5D{yx}" in fields
    assert f"cloud_area_fraction%5B48:1:48%5D%5B0:1:0%5D{yx}" in fields


def saved_metadata():
    folder = sample_folder("kongsberg")
    das = parse_das((folder / "meps_20261126T06Z.das").read_text())
    axes = parse_dods((folder / "meps_20261126T06Z_axes.dods").read_bytes())
    return das, axes


def test_the_window_round_kongsberg_holds_its_nearest_point():
    meps = MepsAdapter(MEPS, None, {"kongsberg": sample_area("kongsberg")})
    # the research found Kongsberg's nearest point at index (y 376, x 304)
    assert meps.window(sample_area("kongsberg"), *saved_metadata()) == Window(374, 378, 302, 306)


def test_a_box_across_the_central_meridian_reaches_down_to_its_south_edge_there():
    # parallels are arcs, lowest (in y) on the central meridian (15° E): a box across
    # it must reach down to its south edge's y there, below the box's corners
    das, axes = saved_metadata()
    box = Box(west=11.0, east=19.0, south=62.0, north=63.0)
    area = Area("across", box, ("meps",), "icon_eu")
    w = MepsAdapter(MEPS, None, {"across": area}).window(area, das, axes)
    y = axes["y"].array.values.astype(float)
    _, y_mid = MEPS_LAMBERT.forward(62.0, 15.0)
    _, y_corner = MEPS_LAMBERT.forward(62.0, 11.0)
    assert y_corner - y_mid > 2 * 2500.0  # more than two grid steps lower
    assert y[w.y0] >= y_mid > y[w.y0 - 1]


def read_copy(tmp_path, edit=None, steps=(0, 7)):
    """Read a copy of the Kongsberg samples, after ``edit(folder)`` changed it."""
    folder = copy_samples(tmp_path / "samples")
    if edit:
        edit(folder)
    with FakeHttpServer() as server:
        meps = adapter_for(server)
        serve_meps(server, folder=folder)
        return meps.read(meps.fetch(SAMPLE_RUN, sample_area("kongsberg"), steps, tmp_path / "raw"))


def drop_variable(name: str):
    def edit(folder):
        edit_dods(
            folder / "meps_20261126T06Z_f007.dods",
            lambda v: {k: x for k, x in v.items() if k != name},
        )

    return edit


@pytest.mark.parametrize(
    "variable",
    [
        "fog_area_fraction",
        "cloud_area_fraction",
        "surface_geopotential",
        "x_wind_pl",
        "forecast_reference_time",
    ],
)
def test_a_sample_with_a_variable_removed_raises_format_mismatch_naming_it(tmp_path, variable):
    with pytest.raises(FormatMismatch, match=f"step 7 .*missing {variable}") as e:
        read_copy(tmp_path, drop_variable(variable))
    assert e.value.model == "meps"


def test_a_sample_with_a_level_removed_raises_format_mismatch_naming_it(tmp_path):
    def edit(folder):
        def drop(v):
            v["air_temperature_pl"] = without_level(v["air_temperature_pl"], 500.0)
            return v

        edit_dods(folder / "meps_20261126T06Z_f000.dods", drop)

    match = r"step 0 .*air_temperature_pl missing level\(s\) 500 hPa"
    with pytest.raises(FormatMismatch, match=match):
        read_copy(tmp_path, edit)


def test_the_unchanged_copy_reads(tmp_path):
    """The edit helpers' round trip: a decoded and re-encoded sample reads the same."""
    plain = read_copy(tmp_path / "a")
    same = read_copy(tmp_path / "b", lambda folder: edit_dods(
        folder / "meps_20261126T06Z_f007.dods", lambda v: v))  # fmt: skip
    np.testing.assert_array_equal(plain.temperature_k, same.temperature_k)


@pytest.mark.parametrize(
    ("change", "named"),
    [
        (lambda b: b[: len(b) // 2], "the data ends"),
        (lambda b: b + b"\x00" * 8, "bytes left after the last variable"),
        (lambda b: b'Error {\n    code = 500;\n    message = "busy";\n};\n', "error"),
    ],
)
def test_a_cut_or_garbled_response_raises_format_mismatch(tmp_path, change, named):
    def edit(folder):
        p = folder / "meps_20261126T06Z_f007.dods"
        p.write_bytes(change(p.read_bytes()))

    with pytest.raises(FormatMismatch, match=f"step 7 .*{named}"):
        read_copy(tmp_path, edit)


def test_fill_values_become_nan_for_verification_to_count(tmp_path):
    def fill(folder):
        def one_fill(v):
            a = v["visibility_in_air"].array
            values = a.values.copy()
            values[0, 0, 2, 2] = np.float32(9.96921e36)
            v["visibility_in_air"] = type(v["visibility_in_air"])(
                type(a)(a.name, a.dap_type, a.dims, values), v["visibility_in_air"].maps
            )
            return v

        edit_dods(folder / "meps_20261126T06Z_f007.dods", one_fill)

    f = read_copy(tmp_path, fill)
    vis = f.fog["visibility_m"]
    assert np.isnan(vis).sum() == 1 and np.isnan(vis[1, 2, 2])


def test_an_unexpected_variable_raises_format_mismatch(tmp_path):
    def extra(folder):
        def add(v):
            v["relative_humidity_pl"] = v["air_temperature_pl"]
            return v

        edit_dods(folder / "meps_20261126T06Z_f007.dods", add)

    with pytest.raises(FormatMismatch, match=r"step 7 .*unexpected relative_humidity_pl"):
        read_copy(tmp_path, extra)


def edit_das(folder, old: str, new: str) -> None:
    das = folder / "meps_20261126T06Z.das"
    text = das.read_text()
    assert text.count(old) == 1, old
    das.write_text(text.replace(old, new))


def test_changed_units_raise_format_mismatch(tmp_path):
    def percent(folder):
        edit_das(
            folder,
            'String long_name "Cloud cover of low clouds (LCC)";\n'
            '        String standard_name "low_type_cloud_area_fraction";\n'
            '        String units "1";',
            'String long_name "Cloud cover of low clouds (LCC)";\n'
            '        String standard_name "low_type_cloud_area_fraction";\n'
            '        String units "%";',
        )

    with pytest.raises(FormatMismatch, match=r"low_type_cloud_area_fraction has units '%'"):
        read_copy(tmp_path, percent)


def test_another_projection_raises_format_mismatch(thredds, tmp_path):
    meps = adapter_for(thredds)
    serve_meps(thredds)
    fetched = meps.fetch(SAMPLE_RUN, sample_area("kongsberg"), (0,), tmp_path / "raw")
    edit_das(
        tmp_path / "raw",
        "Float64 longitude_of_central_meridian 15.0;",
        "Float64 longitude_of_central_meridian 15.5;",
    )
    with pytest.raises(FormatMismatch, match=r"not the window|stated projection"):
        meps.read(fetched)


def test_a_run_for_another_area_is_refused(thredds, tmp_path):
    areas = {"kongsberg": sample_area("kongsberg"), "other": sample_area("box1deg")}
    meps = adapter_for(thredds, areas=areas)
    serve_meps(thredds)
    fetched = meps.fetch(SAMPLE_RUN, sample_area("kongsberg"), (0,), tmp_path / "raw")
    other = FetchResult(fetched.run, "other", fetched.dest_dir, fetched.files, (0,))
    with pytest.raises(FormatMismatch, match="not the window of area other"):
        meps.read(other)


def test_a_failed_step_leaves_it_missing_with_the_reason(thredds, tmp_path):
    meps = adapter_for(thredds)
    serve_meps(thredds)
    sources = json.loads((sample_folder("kongsberg") / "SOURCES.json").read_text())
    del thredds.routes[sources["files"]["meps_20261126T06Z_f000.dods"]["target"]]
    fetched = meps.fetch(SAMPLE_RUN, sample_area("kongsberg"), (0, 1), tmp_path / "raw")
    assert set(fetched.missing_steps) == {0} and "404" in fetched.missing_steps[0]
    assert meps.read(fetched).n_steps == 1


def test_failed_metadata_leaves_every_step_missing_with_the_reason(thredds, tmp_path):
    meps = adapter_for(thredds)
    serve_meps(thredds)
    thredds.fail("/thredds/dodsC/", status=503, times=1)  # the attributes (.das)
    fetched = meps.fetch(SAMPLE_RUN, sample_area("kongsberg"), (0, 1), tmp_path / "raw")
    assert set(fetched.missing_steps) == {0, 1} and not fetched.files
    assert all("metadata" in why and "503" in why for why in fetched.missing_steps.values())
    with pytest.raises(FormatMismatch, match="no step was fetched"):
        meps.read(fetched)


def test_latest_published_is_the_newest_main_run_listed_with_all_its_steps(thredds):
    meps = adapter_for(thredds)
    serve_meps(thredds)
    # the saved catalogue lists runs up to 12z on 26 November: 12z's time axis isn't
    # served here (404) and 09z isn't one of the runs we use, so 06z (67 steps) it is
    assert meps.latest_published(dt.datetime(2026, 11, 26, 15, tzinfo=dt.UTC)) == SAMPLE_RUN
    asked = [r.path.rsplit("/", 1)[-1] for r in thredds.requests]
    assert asked == [
        "catalog.xml",
        "meps_det_2_5km_20261126T12Z.ncml.dds",
        "meps_det_2_5km_20261126T06Z.ncml.dds",
    ]
    # a listed run whose time axis doesn't reach step 48 isn't complete yet
    short = b"Dataset {\n    Float64 time[time = 30];\n} x;\n"
    thredds.route("/thredds/dodsC/mepslatest/meps_det_2_5km_20261126T06Z.ncml.dds?time", short)
    assert meps.latest_published(dt.datetime(2026, 11, 26, 8, tzinfo=dt.UTC)) is None
    # nothing listed by then
    assert meps.latest_published(dt.datetime(2026, 11, 25, 12, tzinfo=dt.UTC)) is None
