"""The GFS source adapter against saved NOMADS samples (F1 spec Testing seam 3; ticket #51).

The samples in ``tests/fixtures/forecast/gfs/`` are real NOMADS grib-filter responses
(NOAA/NCEP GFS, US-government open data; see the README there).
"""

from __future__ import annotations

import datetime as dt
import itertools

import numpy as np
import pytest

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.settings import load_settings
from astroseeing.forecast.sources import FetchResult, FormatMismatch, RunRef
from astroseeing.forecast.sources.gfs import GfsAdapter, RatePacer

from fake_http import FakeHttpServer
from forecast_samples import (
    SAMPLE_RUN,
    copy_samples,
    drop_messages,
    serve_samples,
    small_box_settings,
)

SETTINGS = load_settings()
GFS = SETTINGS.models["gfs"]
KONGSBERG = SETTINGS.areas["kongsberg"]
RUN = RunRef("gfs", dt.datetime(2026, 11, 26, 6, tzinfo=dt.UTC))


class FakeClock:
    """A monotonic clock whose sleep only moves time forward."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def test_request_plan_asks_two_filtered_files_per_step_for_the_area_only():
    plan = GfsAdapter(GFS, http=None, areas=SETTINGS.areas).request_plan(RUN, KONGSBERG, (0, 1, 48))
    assert [(r.step, r.part) for r in plan] == [
        (0, "pgrb2"), (0, "pgrb2b"), (1, "pgrb2"), (1, "pgrb2b"), (48, "pgrb2"), (48, "pgrb2b"),
    ]  # fmt: skip
    a, b = plan[-2], plan[-1]
    assert a.path == "/cgi-bin/filter_gfs_0p25_1hr.pl"
    assert b.path == "/cgi-bin/filter_gfs_0p25b.pl"
    qa, qb = dict(a.params), dict(b.params)
    assert qa["dir"] == "/gfs.20261126/06/atmos" and qa["file"] == "gfs.t06z.pgrb2.0p25.f048"
    assert qb["file"] == "gfs.t06z.pgrb2b.0p25.f048"
    # the area box, cut on the server (longitudes 0-360 as GFS stores them)
    for q in (qa, qb):
        assert (q["leftlon"], q["rightlon"], q["bottomlat"], q["toplat"]) == (
            "4.65", "14.65", "54.67", "64.67",
        )  # fmt: skip
    # only the needed fields: 23 + 16 = 39 pressure levels between the two files
    lev_a = {k for k in qa if k.startswith("lev_") and k.endswith("_mb")}
    lev_b = {k for k in qb if k.startswith("lev_") and k.endswith("_mb")}
    assert len(lev_a) == 23 and len(lev_b) == 17  # b also asks 70 mb for its cloud cover
    assert {k for k in qa if k.startswith("var_")} == {
        "var_HGT", "var_TMP", "var_UGRD", "var_VGRD", "var_TCDC", "var_LCDC", "var_MCDC",
        "var_HCDC", "var_VIS", "var_PRES",
    }  # fmt: skip
    assert {k for k in qb if k.startswith("var_")} == {
        "var_HGT", "var_TMP", "var_UGRD", "var_VGRD", "var_TCDC",
    }  # fmt: skip


def test_west_longitudes_are_asked_in_gfs_0_to_360_convention():
    paranal = SETTINGS.areas["paranal"]
    q = dict(
        GfsAdapter(GFS, http=None, areas=SETTINGS.areas).request_plan(RUN, paranal, (0,))[0].params
    )
    assert (q["leftlon"], q["rightlon"]) == ("289.1", "290.1")


def test_the_pacer_keeps_requests_at_most_one_a_second():
    clock = FakeClock()
    pacer = RatePacer(max_per_s=1.0, monotonic=clock.monotonic, sleep=clock.sleep)
    starts = []
    for _ in range(5):
        pacer.wait()
        starts.append(clock.t)
        clock.t += 0.3  # the request itself takes 0.3 s
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    assert all(g >= 1.0 - 1e-9 for g in gaps)
    assert gaps == pytest.approx([1.0] * 4)


# -- fetch and read against the saved samples ------------------------------------------


@pytest.fixture
def nomads():
    with FakeHttpServer() as s:
        yield s


def adapter_for(server, settings=SETTINGS, pacer=None) -> GfsAdapter:
    return GfsAdapter(settings.models["gfs"], HttpClient(timeout_s=5), settings.areas,
                      base_url=server.url, pacer=pacer or RatePacer(None))  # fmt: skip


def test_reads_the_whole_kongsberg_box_with_all_39_levels(nomads, tmp_path):
    gfs = adapter_for(nomads)
    serve_samples(nomads, gfs, KONGSBERG, (0, 1), "kongsberg")
    fetched = gfs.fetch(SAMPLE_RUN, KONGSBERG, (0, 1), tmp_path / "raw")
    assert not fetched.missing_steps and len(fetched.files) == 4
    assert all(f.host == "nomads" and len(f.sha256) == 64 and f.bytes > 0 for f in fetched.files)
    assert all(f.path.parent == tmp_path / "raw" for f in fetched.files)

    f = gfs.read(fetched)
    assert f.grid_shape == (40, 40)  # 54.75-64.5° N × 4.75-14.5° E, as the research found
    assert f.lat[0, 0] == 64.5 and f.lat[-1, 0] == 54.75  # rows north → south
    assert f.lon[0, 0] == 4.75 and f.lon[0, -1] == 14.5
    assert f.level_count == 39
    assert list(f.pressure_hpa) == list(GFS.pressure_levels_hpa)
    assert f.valid_times.tolist() == [dt.datetime(2026, 11, 26, 6), dt.datetime(2026, 11, 26, 7)]
    # heights rise with each level, temperatures and pressures are physical
    assert (np.diff(f.geopotential_height_m, axis=-1) > 0).all()
    assert f.temperature_k.min() > 180 and f.temperature_k.max() < 320
    assert f.surface_pressure_hpa.min() > 800 and f.surface_pressure_hpa.max() < 1060
    for c in (f.total_cloud_pct, f.low_cloud_pct, f.mid_cloud_pct, f.high_cloud_pct,
              f.level_cloud_pct):  # fmt: skip
        assert c.min() >= 0 and c.max() <= 100
    assert f.fog["visibility_m"] is not None and f.fog["fog_fraction_pct"] is None
    # D47's evidence: GFS's ground is 327 m at 59.75° N 9.75° E (the 2026-11-05 run)
    i, j = int(np.argmin(abs(f.lat[:, 0] - 59.75))), int(np.argmin(abs(f.lon[0] - 9.75)))
    assert f.model_ground_m[i, j] == pytest.approx(327, abs=1)


def test_reads_every_step_0_to_48_of_the_small_box(nomads, tmp_path):
    settings = small_box_settings(tmp_path)
    area = settings.areas["kongsberg"]
    gfs = adapter_for(nomads, settings)
    serve_samples(nomads, gfs, area, GFS.steps_h)
    f = gfs.read(gfs.fetch(SAMPLE_RUN, area, GFS.steps_h, tmp_path / "raw"))
    assert f.grid_shape == (5, 5) and f.n_steps == 49
    assert f.valid_times[-1] == np.datetime64("2026-11-28T06:00:00")


def read_copy(tmp_path, steps=(0, 7), edit=None):
    """Read a copy of the small-box samples, after ``edit(folder)`` changed it."""
    settings = small_box_settings(tmp_path)
    area = settings.areas["kongsberg"]
    folder = copy_samples(tmp_path / "samples")
    if edit:
        edit(folder)
    with FakeHttpServer() as server:
        gfs = adapter_for(server, settings)
        serve_samples(server, gfs, area, steps, folder=folder)
        return gfs.read(gfs.fetch(SAMPLE_RUN, area, steps, tmp_path / "raw"))


def test_never_reads_the_average_cloud_covers(tmp_path):
    # step 7 carries both the instantaneous cloud covers and the 6-7 h averages
    def no_averages(folder):
        assert drop_messages(folder / "gfs.t06z.pgrb2.0p25.f007.grb2",
                             lambda k: k["stepType"] == "avg") == 4  # fmt: skip

    def no_instant_total(folder):
        drop_messages(
            folder / "gfs.t06z.pgrb2.0p25.f007.grb2",
            lambda k: k["typeOfLevel"] == "atmosphere" and k["stepType"] == "instant",
        )

    with_avg = read_copy(tmp_path / "a")
    without_avg = read_copy(tmp_path / "b", edit=no_averages)
    np.testing.assert_array_equal(with_avg.total_cloud_pct, without_avg.total_cloud_pct)
    with pytest.raises(FormatMismatch, match=r"step 7 .*missing TCDC:entire atmosphere"):
        read_copy(tmp_path / "c", edit=no_instant_total)


@pytest.mark.parametrize(
    ("file", "drop", "named"),
    [
        ("gfs.t06z.pgrb2.0p25.f000.grb2", lambda k: k["shortName"] == "vis", "VIS:surface"),
        ("gfs.t06z.pgrb2.0p25.f007.grb2",
         lambda k: k["shortName"] == "t" and k["level"] == 500, "TMP:500 mb"),
        ("gfs.t06z.pgrb2b.0p25.f000.grb2",
         lambda k: k["shortName"] == "gh" and k["level"] == 875, "HGT:875 mb"),
    ],
)  # fmt: skip
def test_a_sample_with_a_variable_or_level_removed_raises_format_mismatch(tmp_path, file, drop,
                                                                          named):  # fmt: skip
    def edit(folder):
        assert drop_messages(folder / file, drop) == 1

    with pytest.raises(FormatMismatch, match=f"missing {named}") as e:
        read_copy(tmp_path, edit=edit)
    assert e.value.model == "gfs"


def test_a_run_from_another_area_is_refused(nomads, tmp_path):
    gfs = adapter_for(nomads)
    serve_samples(nomads, gfs, KONGSBERG, (0,), "kongsberg")
    fetched = gfs.fetch(SAMPLE_RUN, KONGSBERG, (0,), tmp_path / "raw")
    other = FetchResult(fetched.run, "paranal", fetched.dest_dir, fetched.files, (0,))
    with pytest.raises(FormatMismatch, match=r"grid .* area paranal"):
        gfs.read(other)


def test_a_failed_file_leaves_its_step_missing_with_the_reason(nomads, tmp_path):
    gfs = adapter_for(nomads)
    serve_samples(nomads, gfs, KONGSBERG, (0, 1), "kongsberg")
    nomads.fail("/cgi-bin/filter_gfs_0p25b.pl", status=503, times=1)
    fetched = gfs.fetch(SAMPLE_RUN, KONGSBERG, (0, 1), tmp_path / "raw")
    assert set(fetched.missing_steps) == {0} and "503" in fetched.missing_steps[0]
    assert gfs.read(fetched).n_steps == 1


def test_latest_published_is_the_newest_run_with_its_last_step_indexed(nomads):
    gfs = adapter_for(nomads)
    serve_samples(nomads, gfs, KONGSBERG, (0,), "kongsberg")  # indexes the 06z run's f048
    assert gfs.latest_published(dt.datetime(2026, 11, 26, 13, 40, tzinfo=dt.UTC)) == SAMPLE_RUN
    # tried 12z first (not there: 404), then 06z
    heads = [r.path.split("/")[-1] for r in nomads.requests if r.method == "HEAD"]
    assert heads[0] == "gfs.t12z.pgrb2.0p25.f048.idx" and heads[-1].startswith("gfs.t06z")
    assert gfs.latest_published(dt.datetime(2026, 11, 26, 5, tzinfo=dt.UTC)) is None


def test_requests_to_nomads_stay_at_most_one_a_second(nomads, tmp_path):
    """Real time: the pacer spaces the requests the fake host actually receives."""
    gfs = adapter_for(nomads, pacer=RatePacer(GFS.hosts.main.max_requests_per_s))
    serve_samples(nomads, gfs, KONGSBERG, (0, 1), "kongsberg")
    gfs.fetch(SAMPLE_RUN, KONGSBERG, (0, 1), tmp_path / "raw")
    arrivals = [r.at for r in nomads.requests]
    assert len(arrivals) == 4
    assert min(b - a for a, b in itertools.pairwise(arrivals)) >= 0.99
