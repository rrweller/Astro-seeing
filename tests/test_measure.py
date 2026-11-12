"""Measurement-only requests (ticket #10): downloaded under the CDS gate and verified,
never ingested, never reported as refused, timings kept in the manifest like any request."""

from __future__ import annotations

import json

import pytest

from astroseeing import cli
from astroseeing.manifest import Manifest

from fakes import FakeCdsBackend


@pytest.fixture
def ct(tmp_path, monkeypatch):
    for name in ("data", "staging", "state"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("ASTRO_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ASTRO_STAGING", str(tmp_path / "staging"))
    monkeypatch.setenv("ASTRO_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def _fake_from_manifest(path) -> FakeCdsBackend:
    m = Manifest(path)
    rows = m.conn.execute("SELECT request_json, expected_json FROM requests").fetchall()
    m.close()
    exp = {FakeCdsBackend.req_key(json.loads(r[0])): json.loads(r[1]) for r in rows}
    return FakeCdsBackend(exp, polls_to_finish=1)


def test_a_measurement_is_downloaded_and_verified_but_never_stored(ct, monkeypatch, capsys):
    plan = ["plan-measure", "--kind", "pl", "--date", "2023-06-21", "--hours", "0",
            "--area=-24,-71,-25,-70", "--label", "paranal"]  # fmt: skip
    assert cli.main(plan) == 0
    manifest = ct / "state" / "manifest.sqlite"
    fake = _fake_from_manifest(manifest)
    monkeypatch.setattr(cli, "_backend", lambda: fake)

    assert cli.main(["download", "--poll", "0"]) == 0
    assert cli.main(["verify"]) == 0
    assert cli.main(["ingest"]) == 0  # nothing to ingest, nothing refused

    capsys.readouterr()
    assert cli.main(["status"]) == 0
    out = json.loads(capsys.readouterr().out.split("\n}\n")[0] + "\n}")
    assert out["counts"] == {"measured": 1}
    assert fake.submits == 1
    assert not list((ct / "data").rglob("*.zarr"))  # never stored

    m = Manifest(manifest)
    (row,) = m.conn.execute("SELECT * FROM requests").fetchall()
    assert row["key"] == "pl/measure-paranal/2023-06-21"
    for col in ("submitted_at", "cds_started_at", "cds_finished_at"):
        assert row[col], col  # the timings #11 needs
    f = m.current_file(row["id"])
    assert f["size"] > 0 and f["download_seconds"] is not None
    (ver,) = m.conn.execute("SELECT ok FROM verifications").fetchall()
    assert ver["ok"] == 1
    assert (ct / "staging").joinpath(f["path"]).exists()  # raw file kept for a person


def test_the_watcher_counts_a_measurement_as_progress_and_never_as_refused(tmp_path):
    import datetime as dt

    from astroseeing.download.requests import Area, measurement_request, plan_requests
    from astroseeing.notify import WatchState, check_once, snapshot

    now = dt.datetime(2026, 11, 12, 7, 0, tzinfo=dt.UTC)
    old = (now - dt.timedelta(hours=5)).isoformat(timespec="seconds")
    recent = (now - dt.timedelta(minutes=10)).isoformat(timespec="seconds")
    area = Area.around(-24.63, -70.40, half_width_cells=1)
    m = Manifest(tmp_path / "manifest.sqlite")
    for s in plan_requests("sl", "x", dt.date(2023, 1, 1), dt.date(2023, 2, 28), area,
                           granularity="month"):  # fmt: skip
        m.add_request(s)  # two stored requests, still waiting their turn
    rid = m.add_request(measurement_request("pl", dt.date(2023, 6, 21), (0,)))
    m.conn.execute("UPDATE requests SET created_at=?, updated_at=?", (old, old))
    for state in ("submitted", "downloaded", "measured"):
        m.transition(rid, [m.get(rid).state], state)
    m.conn.execute("UPDATE requests SET updated_at=? WHERE id=?", (recent, rid))
    m.conn.commit()

    sent = []
    check_once(m, WatchState(last_daily=now.date().isoformat()),
               lambda msg, title, prio: sent.append(title), now,
               loop_running=lambda: True)  # fmt: skip
    assert sent == []  # no "refused", and finishing the measurement is progress: no "stalled"
    assert snapshot(m, now).pending == 2  # the measurement isn't pending work


def test_one_global_hour_of_pressure_levels_is_145_fields():
    import datetime as dt

    from astroseeing.download.requests import measurement_request

    spec = measurement_request("pl", dt.date(2023, 6, 21), (0,))
    assert spec.n_fields == 145  # 29 levels × z, t, u, v, cc × 1 hour (ticket #10)
    assert spec.key == "pl/measure-global/2023-06-21"
    assert "area" not in spec.cds_request()  # the whole globe
    assert spec.expected()["grid"]["nlat"] == 721 and spec.expected()["grid"]["nlon"] == 1440
    assert spec.purpose == "measure"


def test_an_existing_manifest_gains_the_purpose_column_and_keeps_its_rows(tmp_path):
    """The CT's manifest predates #10: opening it must add the column, not lose anything."""
    import sqlite3

    from astroseeing.manifest import SCHEMA

    path = tmp_path / "manifest.sqlite"
    old_schema = SCHEMA.replace(",\n    purpose         TEXT NOT NULL DEFAULT 'store'", "")
    assert old_schema != SCHEMA
    con = sqlite3.connect(path)
    con.executescript(old_schema)
    con.execute(
        "INSERT INTO requests (key, dataset, kind, region, period, request_json, request_hash,"
        " expected_json, state, attempts, created_at, updated_at)"
        " VALUES ('pl/chile/2021-01', 'reanalysis-era5-pressure-levels', 'pl', 'chile',"
        " '2021-01', '{}', 'h1', '{}', 'ingested', 1, '2026-10-01', '2026-10-02')"
    )
    con.commit()
    con.close()

    m = Manifest(path)
    (r,) = m.by_state("ingested")
    assert (r.key, r.state, r.attempts, r.purpose) == ("pl/chile/2021-01", "ingested", 1, "store")
    m.close()
    Manifest(path).close()  # opening again is a no-op
