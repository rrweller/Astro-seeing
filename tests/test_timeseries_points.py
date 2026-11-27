"""Surface pressure at points from the CDS time-series product (D57 item 4, D62).

Seams: the site points read from configs/sites.yaml; the NetCDF verification; the
fetcher (plan, step, run, stores) against the fake backend in tests/fakes.py; the
pressure-level gate's job list (D29, D39); and the ``astro fetch-sp`` command.
"""

from __future__ import annotations

import datetime as dt

import pytest

from astroseeing.download.timeseries import (
    PointExpectation,
    PointFetchConfig,
    PointFetcher,
    nearest_grid_point,
    plan_chunks,
    read_point_store,
    site_points,
    verify_point_file,
)
from astroseeing.manifest import Manifest

from fakes import FakeTimeseriesBackend, write_point_netcdf

PARANAL = dict(short_name="sp", lon=-70.5, lat=-24.75)
YEAR_1979 = dict(start=dt.date(1979, 1, 1), end=dt.date(1979, 12, 31))


def test_haslebacher_sites_use_their_nearest_era5_grid_points():
    points = {p.site: (p.lon, p.lat) for p in site_points("haslebacher2022")}
    # Worked by hand from Table 1's coordinates on the 0.25° grid.
    assert points == {
        "mauna_kea": (-155.5, 19.75),
        "paranal": (-70.5, -24.75),
        "la_silla": (-70.75, -29.25),
        "cerro_tololo": (-70.75, -30.25),
        "la_palma": (-18.0, 28.75),
        "siding_spring": (149.0, -31.25),
        "sutherland": (20.75, -32.5),
        "san_pedro_martir": (-115.5, 31.0),
    }
    for p in site_points("haslebacher2022"):  # the config's points are the nearest ones
        assert nearest_grid_point(p.site_lon, p.site_lat) == (p.lon, p.lat)


def test_nearest_grid_point_refuses_an_exact_tie():
    assert nearest_grid_point(-70.40, -24.63) == (-70.5, -24.75)
    with pytest.raises(ValueError, match="tie"):
        nearest_grid_point(-70.375, -24.63)


def expect_1979() -> PointExpectation:
    return PointExpectation(units="Pa", **PARANAL, **YEAR_1979)


def test_a_complete_year_passes_verification(tmp_path):
    f = tmp_path / "chunk.zip"
    write_point_netcdf(f, **PARANAL, **YEAR_1979)
    check = verify_point_file(f, expect_1979())
    assert check.ok, check.problems
    assert check.values.size == 8760  # 365 days x 24 h
    assert check.counts == {"missing_hours": 0, "extra_hours": 0, "duplicate_hours": 0, "nan": 0}


def test_a_partial_year_fails_and_counts_the_missing_hours(tmp_path):
    f = tmp_path / "chunk.zip"
    write_point_netcdf(f, **PARANAL, **YEAR_1979, behaviour="partial")
    check = verify_point_file(f, expect_1979())
    assert not check.ok
    assert check.counts["missing_hours"] == 4416  # 1 July to 31 December: 184 days x 24 h
    assert any("4416 of 8760 hours missing" in p for p in check.problems)


@pytest.mark.parametrize(
    ("behaviour", "count", "text"),
    [("nan", "nan", "3 NaN"), ("gap", "missing_hours", "1 of 8760 hours missing")],
)
def test_nan_and_gaps_fail_and_are_counted(tmp_path, behaviour, count, text):
    f = tmp_path / "chunk.zip"
    write_point_netcdf(f, **PARANAL, **YEAR_1979, behaviour=behaviour)
    check = verify_point_file(f, expect_1979())
    assert not check.ok
    assert check.counts[count] == (3 if behaviour == "nan" else 1)
    assert any(text in p for p in check.problems)


def test_the_wrong_point_or_variable_fails(tmp_path):
    f = tmp_path / "chunk.zip"
    write_point_netcdf(f, **PARANAL, **YEAR_1979, behaviour="wrong_point")
    assert any("point" in p for p in verify_point_file(f, expect_1979()).problems)
    g = tmp_path / "other.zip"
    write_point_netcdf(g, **{**PARANAL, "short_name": "t2m"}, **YEAR_1979)
    assert any("no variable 'sp'" in p for p in verify_point_file(g, expect_1979()).problems)


def test_a_bare_netcdf_and_0_to_360_longitudes_are_accepted(tmp_path):
    f = tmp_path / "chunk.nc"
    write_point_netcdf(f, **PARANAL, **YEAR_1979, zipped=False, lon_0_360=True)
    check = verify_point_file(f, expect_1979())
    assert check.ok, check.problems


def test_a_file_that_is_not_netcdf_fails_cleanly(tmp_path):
    f = tmp_path / "chunk.zip"
    f.write_text("<html>error page</html>")
    check = verify_point_file(f, expect_1979())
    assert not check.ok and "cannot read" in check.problems[0]


# --- the fetcher -----------------------------------------------------------------------


def test_chunks_are_calendar_years_and_the_ends_may_be_partial_years():
    d = dt.date
    assert plan_chunks(d(1979, 1, 1), d(2020, 12, 31), 42) == [(d(1979, 1, 1), d(2020, 12, 31))]
    assert len(plan_chunks(d(1979, 1, 1), d(2020, 12, 31), 1)) == 42
    assert plan_chunks(d(1979, 1, 1), d(2020, 12, 31), 20)[-1] == (d(2019, 1, 1), d(2020, 12, 31))
    assert plan_chunks(d(1979, 3, 1), d(1981, 6, 30), 1) == [
        (d(1979, 3, 1), d(1979, 12, 31)),
        (d(1980, 1, 1), d(1980, 12, 31)),
        (d(1981, 1, 1), d(1981, 6, 30)),
    ]
    with pytest.raises(ValueError):
        plan_chunks(d(1979, 1, 1), d(2020, 12, 31), 0)


def cfg(**kw) -> PointFetchConfig:
    base = PointFetchConfig.from_config()
    return PointFetchConfig(**{**base.__dict__, "start": dt.date(1979, 1, 1),
                               "end": dt.date(1980, 12, 31), "chunk_years": 1, **kw})  # fmt: skip


def two_sites():
    return [p for p in site_points("haslebacher2022") if p.site in ("paranal", "la_palma")]


def make(tmp_path, polls_to_finish: int = 2):
    m = Manifest(tmp_path / "state" / "manifest.sqlite")
    fake = FakeTimeseriesBackend(polls_to_finish)
    fetcher = PointFetcher(m, fake, tmp_path / "staging", tmp_path / "data")
    return m, fake, fetcher


def test_two_sites_are_fetched_one_job_at_a_time_and_stored(tmp_path):
    _, fake, f = make(tmp_path)
    f.plan(cfg(), two_sites())
    s = f.run(poll_seconds=0)
    assert s.stored == 2 and s.failed == 0
    assert len(fake.submitted) == 4 and fake.max_in_flight == 1
    assert fake.submitted[0] == (
        "reanalysis-era5-single-levels-timeseries",
        {"variable": ["surface_pressure"], "location": {"longitude": -70.5, "latitude": -24.75},
         "date": ["1979-01-01/1979-12-31"], "data_format": "netcdf"},
    )  # fmt: skip
    store = tmp_path / "data/haslebacher2022/paranal/sp_19790101-19801231.zarr"
    times, values, attrs = read_point_store(store)
    assert times.size == 17544  # 1979 (8760 h) + 1980, a leap year (8784 h)
    assert values.dtype.name == "float32" and not (values != values).any()
    assert attrs["point"] == {"lon": -70.5, "lat": -24.75}
    assert attrs["source_dataset"] == "reanalysis-era5-single-levels-timeseries"
    assert attrs["provenance"]["manifest"]["ts_request_ids"]


def planned_keys(f) -> dict[str, str]:
    """Chunk key → the fake's request key, for setting behaviours."""
    return {r.key: FakeTimeseriesBackend.req_key(r.request) for r in f.rec.by_state("planned")}


def test_a_lost_job_is_submitted_again_and_then_stored(tmp_path):
    _, fake, f = make(tmp_path)
    f.plan(cfg(), two_sites()[:1])
    keys = planned_keys(f)
    fake.behaviour[keys["haslebacher2022/paranal/sp/19790101-19791231"]] = "lost_once"
    s = f.run(poll_seconds=0)
    assert s.resubmitted == 1 and s.stored == 1 and s.failed == 0
    assert len(fake.submitted) == 3  # 2 chunks + the lost one once more


def test_a_job_lost_every_time_fails_after_two_resubmissions(tmp_path):
    _, fake, f = make(tmp_path)
    f.plan(cfg(), two_sites())
    keys = planned_keys(f)
    fake.behaviour[keys["haslebacher2022/paranal/sp/19800101-19801231"]] = "lost"
    s = f.run(poll_seconds=0, max_seconds=30)  # bounded: it must not resubmit forever
    assert s.resubmitted == 2 and s.failed == 1
    assert s.stored == 1  # La Palma; Paranal waits for its failed chunk
    (failed,) = f.rec.by_state("failed")
    assert failed.last_error.startswith("lost at the CDS 3 times")
    assert len(fake.submitted) == 6  # 4 chunks + 2 resubmissions


def test_a_partial_year_fails_verification_and_blocks_only_that_sites_store(tmp_path):
    _, fake, f = make(tmp_path)
    f.plan(cfg(), two_sites())
    keys = planned_keys(f)
    fake.behaviour[keys["haslebacher2022/paranal/sp/19790101-19791231"]] = "partial"
    s = f.run(poll_seconds=0)
    assert s.verification_failed == 1 and s.stored == 1 and s.stopped is None
    (failed,) = f.rec.by_state("failed")
    assert "4416 of 8760 hours missing" in failed.last_error
    assert failed.file_path and (tmp_path / "staging/timeseries").exists()  # kept to inspect
    assert not (tmp_path / "data/haslebacher2022/paranal").exists()
    # Once the CDS sends the whole year, a retry completes the site.
    del fake.behaviour[keys["haslebacher2022/paranal/sp/19790101-19791231"]]
    assert f.retry_failed() == 1
    assert f.run(poll_seconds=0).stored == 1


@pytest.mark.parametrize("behaviour", ["nan", "gap", "wrong_point"])
def test_any_verification_failure_keeps_the_chunk_out_of_the_store(tmp_path, behaviour):
    _, fake, f = make(tmp_path)
    f.plan(cfg(), two_sites()[:1])
    fake.behaviour[next(iter(planned_keys(f).values()))] = behaviour
    s = f.run(poll_seconds=0)
    assert s.verification_failed == 1 and s.stored == 0
    assert f.rec.counts() == {"failed": 1, "verified": 1}


def test_a_rejection_stops_submissions_and_never_touches_the_pressure_level_gate(tmp_path):
    from astroseeing.download.downloader import Downloader

    from fakes import FakeCdsBackend

    m, fake, f = make(tmp_path)
    f.plan(cfg(), two_sites())
    fake.behaviour[next(iter(planned_keys(f).values()))] = "reject"
    s = f.run(poll_seconds=0)
    assert s.rejected == 1 and s.stopped and len(fake.submitted) == 1
    assert f.rec.counts() == {"failed": 1, "planned": 3}
    # Nothing in the pressure-level tables: no request, rejection, backoff or pause.
    assert m.counts() == {} and m.rejections_since("1970") == [] and not m.cds_control()
    assert Downloader(m, FakeCdsBackend({}), tmp_path / "grib").backoff_until() is None


def test_the_accounts_cds_pause_holds_time_series_submissions(tmp_path):
    m, fake, f = make(tmp_path)
    f.plan(cfg(), two_sites()[:1])
    m.pause_cds("3 rejections (test)")
    s = f.run(poll_seconds=0)
    assert s.paused and fake.submitted == []


def test_another_time_series_job_at_the_cds_or_an_unreadable_list_blocks_submission(tmp_path):
    _, fake, f = make(tmp_path)
    f.plan(cfg(), two_sites()[:1])
    fake.other_jobs = [("someone-else", "reanalysis-era5-single-levels-timeseries")]
    assert f.step().submitted == 0
    fake.other_jobs, fake.list_error = [], RuntimeError("HTTP 503")
    assert f.step().submitted == 0
    fake.list_error = None
    assert f.step().submitted == 1


def test_a_restart_reattaches_to_the_job_at_the_cds(tmp_path):
    m, fake, f = make(tmp_path, polls_to_finish=3)
    f.plan(cfg(), two_sites()[:1])
    assert f.step().submitted == 1
    m.close()
    m2 = Manifest(tmp_path / "state" / "manifest.sqlite")
    f2 = PointFetcher(m2, fake, tmp_path / "staging", tmp_path / "data")
    assert f2.run(poll_seconds=0).stored == 1
    assert len(fake.submitted) == 2  # never submitted twice


def test_planning_and_running_again_change_nothing(tmp_path):
    _, _, f = make(tmp_path)
    f.plan(cfg(), two_sites())
    f.run(poll_seconds=0)
    again = f.plan(cfg(), two_sites())
    assert again.planned == 0 and sorted(again.already_stored) == ["la_palma", "paranal"]
    s = f.run(poll_seconds=0)
    assert s.submitted == 0 and s.stored == 0 and len(f.rec.stores()) == 2


def test_a_different_chunk_size_needs_replan_which_replaces_unfinished_chunks(tmp_path):
    m, fake, f = make(tmp_path)
    f.plan(cfg(chunk_years=2), two_sites()[:1])
    fake.behaviour[next(iter(planned_keys(f).values()))] = "reject"  # "too large"
    f.run(poll_seconds=0)
    with pytest.raises(ValueError, match="--replan"):
        f.plan(cfg(chunk_years=1), two_sites()[:1])
    r = f.plan(cfg(chunk_years=1), two_sites()[:1], replan=True)
    assert (r.planned, r.cancelled) == (2, 1)
    f2 = PointFetcher(m, fake, tmp_path / "staging", tmp_path / "data")  # a new run
    assert f2.run(poll_seconds=0).stored == 1


def test_an_existing_different_store_is_never_overwritten(tmp_path):
    _, _, f = make(tmp_path)
    f.plan(cfg(), two_sites()[:1])
    path = tmp_path / "data/haslebacher2022/paranal/sp_19790101-19801231.zarr"
    path.mkdir(parents=True)
    import zarr

    zarr.open_group(str(path), mode="w", zarr_format=3).attrs["content_sha256"] = "other"
    s = f.run(poll_seconds=0)
    assert s.stored == 0 and "not overwriting" in s.store_errors[0]
    assert f.rec.counts() == {"verified": 2}


# --- the pressure-level gate's job list (D29, D39) ---------------------------------------


class _StubJobs:
    def __init__(self, jobs):
        self.json = {"jobs": jobs}


class _StubClient:
    def __init__(self, jobs):
        self.jobs, self.calls = jobs, []

    def get_jobs(self, **kw):
        self.calls.append(kw)
        return _StubJobs(self.jobs)


def backend_with(jobs):
    from astroseeing.download.cds import DatastoresBackend

    b = DatastoresBackend.__new__(DatastoresBackend)  # no credentials, no network
    b.client = _StubClient(jobs)
    return b


def test_time_series_jobs_never_count_for_the_pressure_level_gate():
    b = backend_with([
        {"jobID": "pl-1", "processID": "reanalysis-era5-pressure-levels"},
        {"jobID": "ts-1", "processID": "reanalysis-era5-single-levels-timeseries"},
        {"jobID": "ts-2", "processID": "reanalysis-era5-pressure-levels-timeseries"},
        {"jobID": "unknown-1"},  # no dataset given: counts for both gates
    ])  # fmt: skip
    assert b.active_jobs() == ["pl-1", "unknown-1"]
    assert b.active_timeseries_jobs() == ["ts-1", "ts-2", "unknown-1"]
    assert b.client.calls[0] == {"limit": 100, "status": ["accepted", "running"]}


# --- the command -------------------------------------------------------------------------


@pytest.fixture
def ct(tmp_path, monkeypatch):
    for name in ("data", "staging", "state"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("ASTRO_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ASTRO_STAGING", str(tmp_path / "staging"))
    monkeypatch.setenv("ASTRO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ASTRO_LOG_DIR", str(tmp_path / "logs"))
    return tmp_path


def test_fetch_sp_fetches_1979_to_2020_and_reports_the_stores(ct, monkeypatch, capsys):
    import json

    from astroseeing import cli

    fake = FakeTimeseriesBackend(polls_to_finish=1)
    monkeypatch.setattr(cli, "_backend", lambda: fake)
    assert cli.main(["fetch-sp", "--sites", "paranal,la_palma", "--plan-only"]) == 0
    assert fake.submitted == []
    assert cli.main(["fetch-sp", "--sites", "paranal,la_palma", "--poll", "0"]) == 0
    assert [r["date"] for _, r in fake.submitted] == [["1979-01-01/2020-12-31"]] * 2
    capsys.readouterr()
    assert cli.main(["fetch-sp", "--status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["counts"] == {"stored": 2}
    paths = sorted(s["path"] for s in status["stores"])
    assert paths[1].endswith("data/era5/sl_timeseries/haslebacher2022/paranal/"
                             "sp_19790101-20201231.zarr")  # fmt: skip
    times, _, _ = read_point_store(paths[1])
    assert times.size == 368184  # 15341 days (42 x 365 + 11 leap days) x 24 h


def test_fetch_sp_exit_codes(ct, monkeypatch):
    from astroseeing import cli

    fake = FakeTimeseriesBackend(polls_to_finish=1)
    monkeypatch.setattr(cli, "_backend", lambda: fake)
    assert cli.main(["fetch-sp", "--sites", "nowhere"]) == 2
    cli.main(["fetch-sp", "--sites", "paranal", "--plan-only"])
    (r,) = TimeseriesRecordsFor(ct).by_state("planned")
    fake.behaviour[FakeTimeseriesBackend.req_key(r.request)] = "reject"
    assert cli.main(["fetch-sp", "--sites", "paranal", "--poll", "0"]) == 1
    # A smaller chunk size needs --replan; then the retry goes through.
    assert cli.main(["fetch-sp", "--sites", "paranal", "--chunk-years", "1", "--plan-only"]) == 2
    assert cli.main(["fetch-sp", "--sites", "paranal", "--chunk-years", "1", "--replan",
                     "--poll", "0"]) == 0  # fmt: skip
    assert len(fake.submitted) == 1 + 42


def TimeseriesRecordsFor(ct):
    from astroseeing.download.timeseries import TimeseriesRecords

    return TimeseriesRecords(Manifest(ct / "state" / "manifest.sqlite"))
