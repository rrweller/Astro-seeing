"""The ICON-EU source adapter against saved DWD opendata samples (F1 spec Testing seam 3;
ticket #55).

The samples in ``tests/fixtures/forecast/icon_eu/`` are real ICON-EU fields from DWD's
opendata server (Deutscher Wetterdienst, CC BY 4.0), cut to a small box by us; see the
README there.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import numpy as np
import pytest

from astroseeing.forecast.grid import map_grid
from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.settings import Area, Box, load_settings
from astroseeing.forecast.sources import FormatMismatch, RunRef
from astroseeing.forecast.sources.gfs import RatePacer
from astroseeing.forecast.sources.icon_eu import IconEuAdapter
from astroseeing.forecast.tick import default_adapters

from fake_http import FakeHttpServer
from forecast_samples import small_box_settings
from icon_eu_samples import (
    ICON_RUN,
    edit_message,
    sample_messages,
    serve_icon_samples,
    whole_domain_file,
)

SETTINGS = load_settings()
ICON = SETTINGS.models["icon_eu"]
KONGSBERG = SETTINGS.areas["kongsberg"]
RUN = RunRef("icon_eu", dt.datetime(2026, 11, 26, 6, tzinfo=dt.UTC))
PREFIX = "/weather/nwp/icon-eu/grib/06"
STEM = "icon-eu_europe_regular-lat-lon"


def test_file_plan_names_one_dwd_file_per_field_level_and_step():
    plan = IconEuAdapter(ICON, http=None, areas=SETTINGS.areas).file_plan(RUN, (0, 48))
    # the model ground once per run, then per step 5 fields × 20 levels + 7 single levels
    assert len(plan) == 1 + 2 * (5 * 20 + 7)
    assert plan[0].step is None
    assert plan[0].path == f"{PREFIX}/hsurf/{STEM}_time-invariant_2026112606_HSURF.grib2.bz2"
    paths = {f.path for f in plan}
    for name in (
        f"t/{STEM}_pressure-level_2026112606_000_1000_T.grib2.bz2",
        f"fi/{STEM}_pressure-level_2026112606_048_50_FI.grib2.bz2",
        f"clc/{STEM}_pressure-level_2026112606_048_775_CLC.grib2.bz2",
        f"u/{STEM}_pressure-level_2026112606_000_200_U.grib2.bz2",
        f"v/{STEM}_pressure-level_2026112606_000_200_V.grib2.bz2",
        f"clct/{STEM}_single-level_2026112606_000_CLCT.grib2.bz2",
        f"clcl/{STEM}_single-level_2026112606_048_CLCL.grib2.bz2",
        f"clcm/{STEM}_single-level_2026112606_048_CLCM.grib2.bz2",
        f"clch/{STEM}_single-level_2026112606_048_CLCH.grib2.bz2",
        f"ps/{STEM}_single-level_2026112606_048_PS.grib2.bz2",
        f"vis/{STEM}_single-level_2026112606_048_VIS.grib2.bz2",
        f"ww/{STEM}_single-level_2026112606_048_WW.grib2.bz2",
    ):
        assert f"{PREFIX}/{name}" in paths
    # nothing else: no model levels, no 3-hourly steps, only the fields we read
    assert {f.step for f in plan[1:]} == {0, 48}
    assert not any("model-level" in p for p in paths)


def test_the_tick_registers_icon_eu_for_the_kongsberg_box():
    adapters = default_adapters(SETTINGS, HttpClient())
    assert isinstance(adapters["icon_eu"], IconEuAdapter)
    assert "icon_eu" in KONGSBERG.models
    icon = adapters["icon_eu"]
    assert icon.base_url == "https://opendata.dwd.de" and ICON.hosts.fallback is None


# -- fetch ------------------------------------------------------------------------------


@pytest.fixture
def dwd():
    with FakeHttpServer() as s:
        yield s


def adapter_for(server, settings=SETTINGS) -> IconEuAdapter:
    return IconEuAdapter(
        settings.models["icon_eu"],
        HttpClient(timeout_s=5),
        settings.areas,
        base_url=server.url,
        pacer=RatePacer(None),
    )


def test_fetch_downloads_every_planned_file_and_records_each(dwd, tmp_path):
    icon = adapter_for(dwd)
    plan = icon.file_plan(RUN, (0, 1))
    for f in plan:
        dwd.route(f.path, f.path.encode())  # any bytes: fetch doesn't decode
    fetched = icon.fetch(RUN, KONGSBERG, (0, 1), tmp_path / "raw")
    assert not fetched.missing_steps and len(fetched.files) == len(plan) == 1 + 2 * 107
    assert [f.path.name for f in fetched.files] == [f.filename for f in plan]
    assert all(f.host == "dwd-opendata" and len(f.sha256) == 64 for f in fetched.files)
    assert fetched.bytes == sum(len(f.path.encode()) for f in plan)
    assert [r.path for r in dwd.requests] == [f.path for f in plan]


def test_a_failed_file_leaves_its_step_missing_and_skips_the_rest_of_it(dwd, tmp_path):
    icon = adapter_for(dwd)
    plan = icon.file_plan(RUN, (0, 1))
    broken = next(f for f in plan if f.step == 0 and f.field.name == "CLC")
    for f in plan:
        if f is not broken:
            dwd.route(f.path, b"x")
    fetched = icon.fetch(RUN, KONGSBERG, (0, 1), tmp_path / "raw")
    assert set(fetched.missing_steps) == {0}
    assert "CLC:1000 hPa" in fetched.missing_steps[0] and "404" in fetched.missing_steps[0]
    asked = {r.path for r in dwd.requests}
    after = plan[plan.index(broken) + 1 :]
    assert not any(f.path in asked for f in after if f.step == 0)  # the step is lost anyway
    assert all(f.path in asked for f in plan if f.step == 1)


def test_without_the_model_ground_no_step_is_fetched(dwd, tmp_path):
    icon = adapter_for(dwd)
    fetched = icon.fetch(RUN, KONGSBERG, (0, 1), tmp_path / "raw")
    assert set(fetched.missing_steps) == {0, 1}
    assert all("HSURF" in why for why in fetched.missing_steps.values())
    assert len(dwd.requests) == 1 and fetched.files == ()


# -- read, against the saved samples -----------------------------------------------------


@pytest.fixture(scope="module")
def messages():
    return sample_messages()


@pytest.fixture(scope="module")
def box_settings(tmp_path_factory):
    """The real settings with the Kongsberg area cut to the samples' box, GFS and ICON-EU."""
    return small_box_settings(
        tmp_path_factory.mktemp("config"), **{"areas.kongsberg.models": ["gfs", "icon_eu"]}
    )


def read_samples(tmp_path, settings, messages, steps=(0, 7), raw=None, area=None):
    """Fetch the samples from a fake DWD and read them for the Kongsberg area, or for
    ``area`` (an extra ``Area``) if given."""
    with FakeHttpServer() as server:
        serve_icon_samples(server, messages, raw)
        icon = adapter_for(server, settings)
        fetched = icon.fetch(ICON_RUN, settings.areas["kongsberg"], steps, tmp_path / "raw")
        assert not fetched.missing_steps
        if area is not None:
            icon.areas = {**icon.areas, area.id: area}
            fetched = dataclasses.replace(fetched, area=area.id)
        return icon.read(fetched)


@pytest.mark.slow  # ~25 s: all 5244 sample files
def test_reads_every_step_0_to_48_with_the_20_levels(tmp_path, box_settings, messages):
    f = read_samples(tmp_path, box_settings, messages, steps=ICON.steps_h)
    assert f.n_steps == 49 and f.level_count == 20
    assert f.valid_times[0] == np.datetime64("2026-11-26T06:00:00")
    assert f.valid_times[-1] == np.datetime64("2026-11-28T06:00:00")
    assert list(f.pressure_hpa) == list(ICON.pressure_levels_hpa)  # bottom → top
    # ICON-EU's 0.0625° points inside the box, rows north → south: 17 × 17
    assert f.grid_shape == (17, 17)
    assert f.lat[0, 0] == 60.25 and f.lat[-1, 0] == 59.25
    assert f.lon[0, 0] == 9.25 and f.lon[0, -1] == 10.25
    assert np.allclose(np.diff(f.lat[:, 0]), -0.0625) and np.allclose(np.diff(f.lon[0]), 0.0625)
    # heights from the geopotential rise with each level; temperatures and pressures are physical
    assert (np.diff(f.geopotential_height_m, axis=-1) > 0).all()
    assert f.temperature_k.min() > 180 and f.temperature_k.max() < 320
    assert f.surface_pressure_hpa.min() > 800 and f.surface_pressure_hpa.max() < 1060
    for c in (f.total_cloud_pct, f.low_cloud_pct, f.mid_cloud_pct, f.high_cloud_pct,
              f.level_cloud_pct):  # fmt: skip
        assert c.min() >= 0 and c.max() <= 100  # the cloud range rule (D95)
    assert f.fog["visibility_m"].min() > 0
    assert set(np.unique(f.fog["weather_code"])) <= set(range(100))  # WMO 4677 codes
    assert f.fog["fog_fraction_pct"] is None and f.fog["dewpoint_depression_2m_k"] is None
    # D47's evidence: ICON-EU's ground is 347 m at 59.688° N 9.625° E (the 2026-11-05 run)
    i, j = int(np.argmin(abs(f.lat[:, 0] - 59.6875))), int(np.argmin(abs(f.lon[0] - 9.625)))
    assert f.model_ground_m[i, j] == pytest.approx(347, abs=1)


def test_the_cut_keeps_exactly_the_map_grid_points(tmp_path, box_settings, messages):
    f = read_samples(tmp_path, box_settings, messages)
    g = map_grid(box_settings.areas["kongsberg"], ICON)
    assert f.grid_shape == (g.nlat, g.nlon)
    assert f.lat[0, 0] == g.lat_north and f.lon[0, 0] == g.lon_west


def test_a_whole_domain_file_is_cut_to_the_same_points_and_values(tmp_path, box_settings, messages):
    """DWD's own whole-domain file gives the box's values unchanged: a cut, no regridding."""
    name = next(n for n in messages if n.endswith("_000_WW.grib2.bz2"))
    whole = read_samples(
        tmp_path / "a", box_settings, messages, steps=(0,), raw={name: whole_domain_file(name)}
    )
    cut = read_samples(tmp_path / "b", box_settings, messages, steps=(0,))
    np.testing.assert_array_equal(whole.lat, cut.lat)
    np.testing.assert_array_equal(whole.lon, cut.lon)
    np.testing.assert_array_equal(whole.fog["weather_code"], cut.fog["weather_code"])


def test_a_box_the_samples_do_not_cover_is_refused(tmp_path, box_settings, messages):
    elsewhere = Area("elsewhere", Box(west=9.2, east=11.0, south=59.2, north=60.3), ("icon_eu",),
                     "icon_eu")  # fmt: skip
    with pytest.raises(FormatMismatch, match=r"does not cover area elsewhere") as e:
        read_samples(tmp_path, box_settings, messages, area=elsewhere)
    assert e.value.model == "icon_eu"


def test_a_fetch_without_one_of_its_files_raises_format_mismatch_naming_it(
    tmp_path, box_settings, messages
):
    with FakeHttpServer() as server:
        serve_icon_samples(server, messages)
        icon = adapter_for(server, box_settings)
        fetched = icon.fetch(ICON_RUN, box_settings.areas["kongsberg"], (0, 7), tmp_path / "raw")
    gone = next(f for f in fetched.files if f.path.name.endswith("_007_500_T.grib2.bz2"))
    fewer = dataclasses.replace(fetched, files=tuple(f for f in fetched.files if f is not gone))
    with pytest.raises(FormatMismatch, match=r"step 7: missing T:500 hPa"):
        icon.read(fewer)


@pytest.mark.parametrize(
    ("ending", "keys", "named"),
    [
        ("_007_500_T.grib2.bz2", {"level": 400}, r"T:500 hPa.* holds T:400 hPa"),
        ("_007_CLCT.grib2.bz2", {"parameterNumber": 3}, r"CLCT.* holds \(0, 6, 3\)"),
        ("_007_PS.grib2.bz2", {"dataTime": 1200}, r"run time 2026-11-26T12Z"),
        ("_007_VIS.grib2.bz2", {"stepUnits": 1, "step": 8}, r"step 8 h, expected 7 h"),
        # low and mid cloud share a parameter: the layer's pressures tell them apart
        (
            "_007_CLCL.grib2.bz2",
            {"scaledValueOfFirstFixedSurface": 40000},
            r"CLCL.* holds \(100, 400.0, 1, 0.0\)",
        ),
    ],
)
def test_a_file_holding_another_field_level_run_or_step_raises_format_mismatch(
    tmp_path, box_settings, messages, ending, keys, named
):
    name = next(n for n in messages if n.endswith(ending))
    edited = {**messages, name: edit_message(messages[name], **keys)}
    with pytest.raises(FormatMismatch, match=named):
        read_samples(tmp_path, box_settings, edited)


def test_an_empty_file_raises_format_mismatch(tmp_path, box_settings, messages):
    name = next(n for n in messages if n.endswith("_007_WW.grib2.bz2"))
    import bz2

    with pytest.raises(FormatMismatch, match=r"WW.* no GRIB message"):
        read_samples(tmp_path, box_settings, messages, raw={name: bz2.compress(b"")})


# -- latest_published ----------------------------------------------------------------------


def test_latest_published_is_the_newest_run_with_its_last_step_listed(dwd, messages):
    icon = adapter_for(dwd)
    serve_icon_samples(dwd, messages)  # the 06z run, steps 0-48, in the 06 folder's listing
    assert icon.latest_published(dt.datetime(2026, 11, 26, 13, 40, tzinfo=dt.UTC)) == ICON_RUN
    # tried the 12z folder first (no listing: 404), then 06z; one cheap GET each
    gets = [r.path for r in dwd.requests]
    assert gets == [f"{PREFIX[:-2]}12/ww/", f"{PREFIX}/ww/"]
    n = len(dwd.requests)
    assert icon.latest_published(dt.datetime(2026, 11, 26, 5, tzinfo=dt.UTC)) is None
    # 00z today and yesterday share the 00 folder: each folder's listing is read once
    assert sorted(r.path.split("/")[-3] for r in dwd.requests[n:]) == ["00", "06", "12", "18"]


def test_a_run_whose_last_step_is_not_listed_yet_is_not_published(dwd, messages):
    icon = adapter_for(dwd)
    partial = {n: m for n, m in messages.items() if "_048_" not in n}
    serve_icon_samples(dwd, partial)
    assert icon.latest_published(dt.datetime(2026, 11, 26, 10, tzinfo=dt.UTC)) is None
