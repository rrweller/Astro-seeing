"""RunFields, the one shape every forecast source adapter returns (F1 spec Module 1;
ticket #50), and the adapter interface's RunRef, FetchResult and FormatMismatch."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from astroseeing.forecast.settings import load_settings
from astroseeing.forecast.sources import (
    CLOUD_TOLERANCE_PCT,
    FetchedFile,
    FetchResult,
    FormatMismatch,
    RunFields,
    RunRef,
)

RUN = RunRef("gfs", dt.datetime(2026, 11, 26, 12, tzinfo=dt.UTC))
LEVELS = np.array([1000.0, 850.0, 500.0, 200.0, 50.0])  # bottom → top


def synthetic(
    nstep=3, grid=(2, 3), levels=LEVELS, level_cloud=True, model=None, **overrides
) -> dict:
    """Keyword arguments for a consistent RunFields on a small grid."""
    nlev = len(levels)
    rng = np.random.default_rng(0)
    if len(grid) == 1:  # a list of points
        lat, lon = np.linspace(60, 59, grid[0]), np.linspace(9, 10, grid[0])
    else:
        lat, lon = np.meshgrid(np.linspace(60, 59, grid[0]), np.linspace(9, 10, grid[1]),
                               indexing="ij")  # fmt: skip
    lvl = (nstep, *grid, nlev)
    sfc = (nstep, *grid)
    z = np.broadcast_to(np.array([100.0, 1500, 5500, 11800, 20600])[:nlev], lvl).copy()
    kw = dict(
        run=RUN,
        model=model or load_settings().models["gfs"],
        lat=lat,
        lon=lon,
        valid_times=np.array(
            [RUN.run_time.replace(tzinfo=None) + dt.timedelta(hours=h) for h in range(nstep)],
            dtype="datetime64[s]",
        ),
        pressure_hpa=levels,
        geopotential_height_m=z,
        temperature_k=np.full(lvl, 250.0),
        u_ms=rng.normal(10, 5, lvl),
        v_ms=rng.normal(0, 5, lvl),
        level_cloud_pct=np.zeros(lvl) if level_cloud else None,
        total_cloud_pct=np.full(sfc, 40.0),
        low_cloud_pct=np.full(sfc, 10.0),
        mid_cloud_pct=np.full(sfc, 20.0),
        high_cloud_pct=np.full(sfc, 30.0),
        surface_pressure_hpa=np.full(sfc, 990.0),
        model_ground_m=np.full(grid, 327.0),
        fog={"visibility_m": np.full(sfc, 20000.0)},
    )
    kw.update(overrides)
    return kw


def test_runfields_from_synthetic_arrays():
    f = RunFields(**synthetic())
    assert f.grid_shape == (2, 3)
    assert f.n_steps == 3
    assert f.level_count == 5
    assert f.family == "gfs" and not f.regional
    np.testing.assert_array_equal(f.wind_200hpa_ms[0], f.u_ms[..., 3])  # u at 200 hPa
    np.testing.assert_array_equal(f.wind_200hpa_ms[1], f.v_ms[..., 3])
    assert f.fog["visibility_m"] is not None
    assert f.fog["fog_fraction_pct"] is None  # absent, never filled
    assert f.fog["dewpoint_depression_2m_k"] is None


def test_regular_grids_may_give_1d_points_and_ifs_has_no_level_cloud():
    ifs = load_settings().models["ifs"]
    f = RunFields(**synthetic(grid=(4,), level_cloud=False, model=ifs,
                              run=RunRef("ifs", RUN.run_time), fog={}))  # fmt: skip
    assert f.grid_shape == (4,) and f.level_cloud_pct is None
    assert all(v is None for v in f.fog.values())


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"pressure_hpa": LEVELS[::-1]}, r"bottom → top"),
        ({"pressure_hpa": np.array([1000.0, 850, 850, 200, 50])}, r"bottom → top"),
        ({"pressure_hpa": np.array([1000.0, 850, 500, 250, 50])}, r"200 hPa"),
        ({"total_cloud_pct": np.full((2, 2, 3), 40.0)}, r"total_cloud_pct.*\(3, 2, 3\)"),
        ({"temperature_k": np.full((3, 2, 3, 4), 250.0)}, r"temperature_k"),
        ({"model_ground_m": np.full((3, 2), 327.0)}, r"model_ground_m"),
        ({"lon": np.zeros((3, 2))}, r"lat and lon"),
        ({"valid_times": np.array(["2026-11-26T12", "2026-11-26T14", "2026-11-26T13"],
                                  dtype="datetime64[s]")}, r"increasing"),
        ({"valid_times": np.array(["2026-11-26T11", "2026-11-26T12", "2026-11-26T13"],
                                  dtype="datetime64[s]")}, r"before the run time"),
        ({"fog": {"fog_risk": np.zeros((3, 2, 3))}}, r"unknown fog signal"),
        ({"fog": {"visibility_m": np.zeros((3, 2))}}, r"visibility_m"),
        ({"level_cloud_pct": None}, r"level cloud"),
        ({"run": RunRef("ifs", RUN.run_time)}, r"run is for 'ifs'"),
    ],
)  # fmt: skip
def test_inconsistent_shapes_are_refused(overrides, message):
    with pytest.raises(ValueError, match=message):
        RunFields(**synthetic(**overrides))


def test_wrong_step_count_is_refused():
    kw = synthetic(nstep=3)
    kw["valid_times"] = kw["valid_times"][:2]  # two valid times for three steps of data
    with pytest.raises(ValueError, match=r"step"):
        RunFields(**kw)


def test_runref_is_a_utc_run_on_the_hour():
    with pytest.raises(ValueError, match="UTC"):
        RunRef("gfs", dt.datetime(2026, 11, 26, 12))
    with pytest.raises(ValueError, match="on the hour"):
        RunRef("gfs", dt.datetime(2026, 11, 26, 12, 30, tzinfo=dt.UTC))
    assert RUN.label == "20261126T12Z"


def test_format_mismatch_names_the_model_and_the_difference():
    e = FormatMismatch("ifs", "variable 2d missing at step 12")
    assert e.model == "ifs" and e.difference == "variable 2d missing at step 12"
    assert str(e) == "ifs: format mismatch: variable 2d missing at step 12"


def test_fetch_result_records_each_file(tmp_path):
    f = FetchedFile(
        url="https://nomads.ncep.noaa.gov/x", host="nomads", path=tmp_path / "a.grib2",
        bytes=10, seconds=0.5, sha256="0" * 64,
    )  # fmt: skip
    r = FetchResult(run=RUN, area="kongsberg", dest_dir=tmp_path, files=(f,),
                    steps_h=(0, 1), missing_steps={1: "HTTP 404 after 5 tries"})  # fmt: skip
    assert r.bytes == 10 and r.fetched_steps == (0,)
    with pytest.raises(ValueError, match="step 2"):
        FetchResult(run=RUN, area="kongsberg", dest_dir=tmp_path, files=(f,),
                    steps_h=(0, 1), missing_steps={2: "?"})  # fmt: skip


# -- the cloud range rule (ticket #80, D95) ---------------------------------------------
CLOUD = ("total_cloud_pct", "low_cloud_pct", "mid_cloud_pct", "high_cloud_pct", "level_cloud_pct")


def with_cloud_value(name: str, value: float, step: int = 1) -> dict:
    """Synthetic fields whose cloud ``name`` holds ``value`` at one point of ``step``."""
    kw = synthetic()
    values = kw[name].copy()
    values[step, 1, 2, ...] = value
    kw[name] = values
    return kw


@pytest.mark.parametrize("name", CLOUD)
def test_cloud_a_hair_over_100_is_set_to_100_and_counted(name):
    kw = with_cloud_value(name, 100 + CLOUD_TOLERANCE_PCT / 2)
    given = kw[name].copy()
    f = RunFields(**kw)
    values = getattr(f, name)
    assert np.all(values[1, 1, 2, ...] == 100.0)
    assert f.qc[f"{name}_set_to_100"] == (5 if name == "level_cloud_pct" else 1)
    assert sum(f.qc.counts.values()) == f.qc[f"{name}_set_to_100"]  # nothing else counted
    np.testing.assert_array_equal(kw[name], given)  # the adapter's array is not edited


@pytest.mark.parametrize("name", CLOUD)
def test_cloud_a_hair_below_0_is_set_to_0_and_counted(name):
    f = RunFields(**with_cloud_value(name, -CLOUD_TOLERANCE_PCT / 2))
    assert np.all(getattr(f, name)[1, 1, 2, ...] == 0.0)
    assert f.qc[f"{name}_set_to_0"] == (5 if name == "level_cloud_pct" else 1)
    assert sum(f.qc.counts.values()) == f.qc[f"{name}_set_to_0"]


@pytest.mark.parametrize("name", CLOUD)
@pytest.mark.parametrize("value", [100 + 10 * CLOUD_TOLERANCE_PCT, -10 * CLOUD_TOLERANCE_PCT])
def test_cloud_further_out_of_range_fails_naming_field_step_and_value(name, value):
    with pytest.raises(FormatMismatch) as e:
        RunFields(**with_cloud_value(name, value, step=2))
    assert e.value.model == "gfs"
    assert name in e.value.difference and "step 2" in e.value.difference
    assert repr(value) in e.value.difference


@pytest.mark.parametrize("value", [0.0, 100.0])
def test_exact_0_and_100_are_unchanged_and_not_counted(value):
    kw = synthetic()
    for name in CLOUD:
        kw[name] = np.full_like(kw[name], value)
    f = RunFields(**kw)
    for name in CLOUD:
        assert getattr(f, name) is kw[name]  # the very same array: nothing set
        assert f.qc[f"{name}_set_to_0"] == f.qc[f"{name}_set_to_100"] == 0
    assert f.qc.totals["level_cloud_pct_set_to_100"] == 3 * 2 * 3 * 5  # every value checked


def test_nan_cloud_is_left_for_verification_to_count():
    f = RunFields(**with_cloud_value("total_cloud_pct", np.nan))
    assert np.isnan(f.total_cloud_pct[1, 1, 2])
    assert sum(f.qc.counts.values()) == 0


def test_fields_cut_from_a_run_keep_the_run_counts():
    run = RunFields(**with_cloud_value("high_cloud_pct", 100 + CLOUD_TOLERANCE_PCT / 2))
    kw = synthetic(grid=(1, 1), high_cloud_pct=run.high_cloud_pct[:, 1:2, 2:3])
    cut = RunFields(**kw, qc=run.qc)
    assert cut.qc is run.qc and cut.qc["high_cloud_pct_set_to_100"] == 1
    with pytest.raises(ValueError, match="still had cloud values to set"):
        RunFields(**with_cloud_value("high_cloud_pct", 100.001), qc=run.qc)
