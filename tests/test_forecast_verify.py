"""Run verification and the forecast manifest records (F1 spec Module 2; ticket #51)."""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import replace

import numpy as np
import pytest

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.sources import FetchedFile, RunFields
from astroseeing.forecast.sources.gfs import GfsAdapter, RatePacer
from astroseeing.forecast.verify import ForecastRecords, verify_run
from astroseeing.manifest import SCHEMA, Manifest

from fake_http import FakeHttpServer
from forecast_samples import SAMPLE_RUN, serve_samples, small_box_settings

T0 = dt.datetime(2026, 11, 26, 10, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    """The small-box sample, steps 0-3, read through the adapter."""
    tmp = tmp_path_factory.mktemp("sample")
    settings = small_box_settings(tmp)
    area = settings.areas["kongsberg"]
    with FakeHttpServer() as server:
        gfs = GfsAdapter(
            settings.models["gfs"],
            HttpClient(timeout_s=5),
            settings.areas,
            base_url=server.url,
            pacer=RatePacer(None),
        )
        serve_samples(server, gfs, area, (0, 1, 2, 3))
        return settings.models["gfs"], gfs.read(
            gfs.fetch(SAMPLE_RUN, area, (0, 1, 2, 3), tmp / "raw")
        )


def test_the_real_sample_verifies_on_every_step(sample):
    model, fields = sample
    report = verify_run(fields, model, steps_expected=(0, 1, 2, 3))
    assert report.ok and not report.problems
    assert report.steps == {0: "ok", 1: "ok", 2: "ok", 3: "ok"}
    assert report.verified_steps == (0, 1, 2, 3)
    assert all(n == 0 for n in report.nan_counts.values())
    assert "temperature_k" in report.nan_counts and "fog visibility_m" in report.nan_counts


def test_nan_values_are_counted_and_fail_only_their_step(sample):
    model, fields = sample
    t = fields.temperature_k.copy()
    t[2, 0, 0, 5] = np.nan
    t[2, 1, 1, 7] = np.nan
    report = verify_run(
        RunFields(**{**fields.__dict__, "temperature_k": t}), model, steps_expected=(0, 1, 2, 3)
    )
    assert report.ok  # the content is right; one step is unusable
    assert report.nan_counts["temperature_k"] == 2
    assert report.steps[2] == "NaN in temperature_k (2 values)"
    assert report.verified_steps == (0, 1, 3)


def test_steps_not_delivered_are_missing_with_the_reason(sample):
    model, fields = sample
    report = verify_run(
        fields, model, steps_expected=(0, 1, 2, 3, 4), missing={4: "pgrb2: HTTP 503"}
    )
    assert report.steps[4] == "not fetched: pgrb2: HTTP 503"
    assert report.verified_steps == (0, 1, 2, 3)


def test_other_levels_or_fog_signals_than_expected_fail_the_run(sample):
    model, fields = sample
    fewer = replace(model, pressure_levels_hpa=model.pressure_levels_hpa[:-1])
    report = verify_run(fields, fewer, steps_expected=(0, 1, 2, 3))
    assert not report.ok and "pressure levels" in report.problems[0]
    more_fog = replace(model, fog_signals=("visibility_m", "fog_fraction_pct"))
    report = verify_run(fields, more_fog, steps_expected=(0, 1, 2, 3))
    assert not report.ok and "fog signal fog_fraction_pct" in " ".join(report.problems)


# -- manifest records ----------------------------------------------------------------


def test_an_old_manifest_gains_the_two_forecast_tables_and_nothing_else_changes(tmp_path):
    path = tmp_path / "manifest.sqlite"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)  # a manifest from before the forecast track
    con.execute(
        "INSERT INTO requests (key, dataset, kind, region, period, request_json, request_hash,"
        " expected_json, state, attempts, created_at, updated_at)"
        " VALUES ('pl/chile/2021-01', 'reanalysis-era5-pressure-levels', 'pl', 'chile',"
        " '2021-01', '{}', 'h1', '{}', 'ingested', 1, '2026-10-01', '2026-10-02')"
    )
    con.commit()

    def snapshot(c):
        schema = dict(c.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL"))
        rows = {
            t: c.execute(f"SELECT * FROM {t}").fetchall()
            for t in schema
            if not t.startswith("sqlite_") and t in {"requests", "events", "files"}
        }
        return schema, rows

    before_schema, before_rows = snapshot(con)
    con.close()
    Manifest(path).close()
    con = sqlite3.connect(path)
    after_schema, after_rows = snapshot(con)
    con.close()
    assert set(after_schema) - set(before_schema) == {
        "forecast_runs",
        "forecast_files",
        "forecast_step_tries",
        "forecast_hosts",
        "forecast_alerts",  # ticket #61
        "forecast_heartbeat",
        "forecast_place_days",
        "ts_requests",  # the time-series point fetcher (D62)
        "ts_requests_state",
        "ts_events",
        "ts_stores",
        "eso_fetches",  # the ESO fetcher (D65)
        "eso_fetch_tries",
        "raw_archives",  # the raw GRIB archive (D64)
    }
    assert {k: after_schema[k] for k in before_schema} == before_schema
    assert after_rows == before_rows
    Manifest(path).close()  # opening again changes nothing


def test_a_run_moves_through_its_states_with_files_recorded(tmp_path):
    m = Manifest(tmp_path / "manifest.sqlite")
    rec = ForecastRecords(m)
    run_id = rec.seen("gfs", "kongsberg", SAMPLE_RUN.run_time, steps=(0, 1), at=T0)
    assert rec.seen("gfs", "kongsberg", SAMPLE_RUN.run_time, steps=(0, 1), at=T0) == run_id
    rec.transition(run_id, ("seen",), "fetching", at=T0, increment_attempts=True)
    f = FetchedFile("http://x/a", "nomads", tmp_path / "a.grb2", 10, 0.5, "0" * 64)
    rec.add_file(run_id, f, at=T0)
    rec.transition(run_id, ("fetching",), "fetched", at=T0, bytes=10, download_seconds=0.5)
    run = rec.get(run_id)
    assert (run.state, run.attempts, run.bytes, run.steps_expected) == ("fetched", 1, 10, (0, 1))
    with pytest.raises(Exception, match="expected"):
        rec.transition(run_id, ("seen",), "fetching", at=T0)  # compare-and-set
    (row,) = rec.files(run_id)
    assert (row["sha256"], row["verified"], row["raw_deleted_at"]) == ("0" * 64, 0, None)
    rec.mark_files_verified(run_id)
    rec.mark_raw_deleted(run_id, at=T0)
    (row,) = rec.files(run_id)
    assert row["verified"] == 1 and row["raw_deleted_at"] == "2026-11-26T10:00:00+00:00"
    m.close()
