"""The run rules through the whole tick (F1 spec Testing seam 1; ticket #58, D51 items
5, 7 and 14): retries, late, partial and abandoned runs, and the fallback host.

Fake NOMADS (and a fake AWS mirror) serve the saved GFS samples, a fake clock steps the
ticks, and the manifest is a temporary SQLite file. Request spacing is read from the
fake hosts' request logs, stamped with the fake clock.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json

import pytest

from astroseeing.forecast.schemas import validate
from astroseeing.forecast.settings import load_settings
from astroseeing.forecast.sources import RunRef
from astroseeing.forecast.sources.gfs import FILTERS

from forecast_samples import SAMPLE_RUN, SAMPLES, drop_messages, retime_samples
from forecast_world import DAY, PUBLISHED, World

MIN = dt.timedelta(minutes=1)


def gets_of(server, text: str) -> list:
    """The GET requests whose target holds ``text`` (e.g. one step's file name)."""
    out = []
    for r in server.requests:
        query = "&".join(f"{k}={v[0]}" for k, v in r.query.items())
        if r.method == "GET" and text in f"{r.path}?{query}":
            out.append(r)
    return out


def ticks(world, start: dt.datetime, end: dt.datetime, every: dt.timedelta):
    t, reports = start, []
    while t <= end:
        reports.append(world.at(t))
        t += every
    return reports


def hour_values(place: dict) -> dict:
    return {h["time"]: h["models"]["gfs"] for h in place["hours"]}


@pytest.fixture
def world(tmp_path, ephemeris):
    w = World(tmp_path, ephemeris)
    yield w
    w.close()


def test_a_failing_file_is_tried_5_times_a_minute_apart_then_the_run_is_partial(world):
    """Step 12's first file always fails. Ticks every 20 s: the file is tried at most
    every minute and at most 5 times; the run counts for its other 48 steps meanwhile,
    and once the tries are used up it is final, with its raw files gone."""
    step12 = "file=gfs.t06z.pgrb2.0p25.f012"
    world.server.fail(FILTERS["pgrb2"], status=503, contains=step12)
    start = PUBLISHED + 5 * MIN  # 09:45
    world.at(start)
    world.at(start + dt.timedelta(seconds=20))
    run = world.run(6)
    assert run["state"] == "partial"  # 48 steps stored, step 12 still to try
    assert len(list(world.paths.root.rglob("*.grb2"))) == 96  # kept while retrying

    ticks(world, start + dt.timedelta(seconds=40), start + 10 * MIN, dt.timedelta(seconds=20))

    tries = gets_of(world.server, step12)
    assert len(tries) == 5
    gaps = [b.at - a.at for a, b in itertools.pairwise(tries)]
    assert all(g >= 60 for g in gaps), gaps
    # every other file was fetched exactly once; step 12's second file never (its step
    # was missing anyway)
    for step in range(49):
        for part in ("pgrb2", "pgrb2b"):
            n = len(gets_of(world.server, f"file=gfs.t06z.{part}.0p25.f{step:03d}"))
            if step == 12:
                assert n == (5 if part == "pgrb2" else 0)
            else:
                assert n == 1, (step, part, n)

    run = world.run(6)
    assert run["state"] == "partial"
    verified = json.loads(run["steps_verified"])
    assert all(verified[str(s)] == "ok" for s in range(49) if s != 12)
    assert verified["12"].startswith("not fetched: 5 tries failed")
    assert "503" in verified["12"]
    assert not any(world.paths.root.rglob("*.grb2"))  # final: raw files deleted
    files = world.manifest.conn.execute("SELECT * FROM forecast_files").fetchall()
    assert len(files) == 96 and all(f["raw_deleted_at"] for f in files)

    # the page: step 12 is 18 UTC on the 26th, shown as missing from a partial run
    place = world.place_file()
    validate(place, "f1-place/1")
    values = hour_values(place)
    assert values["2026-11-26T18:00:00Z"] == {"missing": "partial"}
    assert all("run_id" in v for t, v in values.items() if t != "2026-11-26T18:00:00Z")
    assert world.latest()["runs"]["gfs"]["state"] == "partial"


def test_a_late_run_is_logged_only_and_used_once_it_appears(tmp_path, ephemeris, caplog):
    """GFS's publish delay is 3.6 h, so the 06z run is late from 12:36 (delay + 3 h).
    Here it only appears at 13:10: the 13:00 tick logs it as late and records nothing;
    the 14:00 tick fetches it as usual."""
    late_publish = [(DAY + dt.timedelta(hours=13, minutes=10), SAMPLE_RUN, SAMPLES / "box1deg")]
    w = World(tmp_path, ephemeris, publish=late_publish)
    run06 = {"model": "gfs", "area": "kongsberg", "run_time": "2026-11-26T06:00:00Z"}
    try:
        late = {}
        for hour in (10, 12, 13, 14):
            caplog.clear()
            late[hour] = w.at(DAY + dt.timedelta(hours=hour)).late
            if hour == 13:
                assert any("gfs kongsberg 20261126T06Z is late" in m for m in caplog.messages)
                assert w.runs() == []  # nothing recorded for a run not yet out
                values = hour_values(w.place_file())
                assert all(v == {"missing": "no_run"} for v in values.values())
        assert run06 not in late[10] and run06 not in late[12]
        assert late[13] == [run06]
        assert late[14] == []  # seen now

        run = w.run(6)
        assert run["state"] == "processed" and run["attempts"] == 1
        assert run["first_seen_at"] == "2026-11-26T14:00:00+00:00"
        assert all("run_id" in v for v in hour_values(w.place_file()).values())
    finally:
        w.close()


def test_a_run_still_fetching_is_abandoned_when_the_next_run_is_complete(tmp_path, ephemeris):
    """A 00z run (the samples re-timed), out at 03:40, has a step 12 that keeps failing.
    The ticks at 03:45 and 04:00 try it twice; then the CT is off until 09:45, when the
    06z run is out and fetched whole, so the 00z run is abandoned there: it keeps its
    stored steps, its raw files go, and the page shows the 06z run."""
    run00 = RunRef("gfs", DAY)
    folder00 = retime_samples(tmp_path / "samples00", 0)
    publish = [
        (DAY + dt.timedelta(hours=3, minutes=40), run00, folder00),
        (PUBLISHED, SAMPLE_RUN, SAMPLES / "box1deg"),
    ]
    w = World(tmp_path / "w", ephemeris, publish=publish)
    step12 = "file=gfs.t00z.pgrb2.0p25.f012"
    w.server.fail(FILTERS["pgrb2"], status=503, contains=step12)
    try:
        for hhmm in ((3, 45), (4, 0)):
            w.at(DAY + dt.timedelta(hours=hhmm[0], minutes=hhmm[1]))
        assert w.run(0)["state"] == "partial"
        report = w.at(DAY + dt.timedelta(hours=9, minutes=45))

        r00, r06 = w.run(0), w.run(6)
        assert r06["state"] == "processed"
        assert r00["state"] == "abandoned"
        why = "the newer run 2026-11-26T06Z is complete"
        assert r00["last_error"] == f"abandoned: {why}"
        verified = json.loads(r00["steps_verified"])
        assert verified["12"].startswith(f"abandoned ({why}): try 2 of 5 failed")
        assert all(verified[str(s)] == "ok" for s in range(49) if s != 12)
        assert len(gets_of(w.server, step12)) == 2  # no try once abandoned
        assert {(r["run_time"], r["state"]) for r in report.runs} == {
            ("2026-11-26T06:00:00Z", "processed"),
            ("2026-11-26T00:00:00Z", "abandoned"),
        }
        assert not any(w.paths.root.rglob("*.grb2"))  # both runs' raw files gone
        files = w.manifest.conn.execute("SELECT * FROM forecast_files").fetchall()
        assert all(f["raw_deleted_at"] for f in files)

        assert w.latest()["runs"]["gfs"]["run_id"] == r06["id"]
        values = hour_values(w.place_file())
        assert {v["run_id"] for v in values.values() if "run_id" in v} == {r06["id"]}
        # the abandoned run's stored steps stay on the SSD (every run is kept)
        stored = w.paths.places / "kongsberg" / "2026-11-26" / "gfs-20261126T00Z.json"
        assert len(json.loads(stored.read_text())["steps"]) == 48
    finally:
        w.close()


def test_a_run_near_the_end_of_an_icon_eu_online_window_is_abandoned(tmp_path, ephemeris):
    """ICON-EU keeps a run online ~24 h and has no fallback host, so a run still fetching
    20 h after its run time is given up (D51 item 7). The ICON-EU adapter isn't built
    yet, so GFS runs here under ICON-EU's settings: its online window and no fallback.
    Steps 0-19 arrive at 09:45, steps 20-48 fail, then the host is down for good."""
    icon = load_settings().models["icon_eu"]
    assert (icon.online_window_h, icon.hosts.fallback) == (24, None)
    edits = {"models.gfs.online_window_h": icon.online_window_h, "models.gfs.hosts.fallback": None}
    w = World(tmp_path, ephemeris, settings_edits=edits)
    for tens in ("f02", "f03", "f04"):  # steps 20-48
        w.server.fail(FILTERS["pgrb2"], status=503, contains=f"file=gfs.t06z.pgrb2.0p25.{tens}")
    try:
        w.at(DAY + dt.timedelta(hours=9, minutes=45))
        w.server.outage()
        w.at(DAY + dt.timedelta(hours=10))
        w.at(DAY + dt.timedelta(days=1, hours=1, minutes=45))
        assert w.run(6)["state"] == "partial"  # still waiting for steps 20-48
        assert len(list(w.paths.root.rglob("*.grb2"))) == 40  # kept while waiting

        report = w.at(DAY + dt.timedelta(days=1, hours=2))  # 06z + 24 h - 4 h
        run = w.run(6)
        assert run["state"] == "abandoned"
        why = "4 h before the end of the source's 24 h online window (2026-11-27T02:00Z)"
        assert run["last_error"] == f"abandoned: {why}"
        verified = json.loads(run["steps_verified"])
        assert all(verified[str(s)] == "ok" for s in range(20))
        assert verified["20"].startswith(f"abandoned ({why}): try 1 of 5 failed")
        assert verified["48"].startswith(f"abandoned ({why}): try 1 of 5 failed")
        assert report.runs == [
            {
                "model": "gfs",
                "area": "kongsberg",
                "run_time": "2026-11-26T06:00:00Z",
                "state": "abandoned",
                "error": f"abandoned: {why}",
            }
        ]
        assert not any(w.paths.root.rglob("*.grb2"))

        # the abandoned run still counts for its verified steps: Tonight (the night of
        # the 26th) has 12-01 UTC from it, 02-11 UTC missing as partial
        latest, place = w.latest(), w.place_file()
        validate(place, "f1-place/1")
        assert latest["runs"]["gfs"]["state"] == "abandoned"
        values = hour_values(place)
        for t, v in values.items():
            step = (dt.datetime.fromisoformat(t) - DAY).total_seconds() / 3600 - 6
            if step < 20:
                assert v["run_id"] == run["id"], t
            else:
                assert v == {"missing": "partial"}, t
    finally:
        w.close()


def test_a_main_host_outage_over_an_hour_switches_to_the_fallback_and_back(
    tmp_path, ephemeris, caplog
):
    """NOMADS serves every step but 21 at 09:45, then goes down. Its failure
    counts from 10:00 (the first unanswered check); at 11:00 it has lasted 1 h, so GFS
    switches to the AWS bucket (logged) and the run is finished from there. NOMADS
    answers again at 11:15 and GFS goes back to it (logged). The values are the same as
    from NOMADS alone."""
    w = World(tmp_path / "w", ephemeris, mirror=True)
    w.server.fail(FILTERS["pgrb2"], status=503, contains="file=gfs.t06z.pgrb2.0p25.f021")
    try:
        w.at(DAY + dt.timedelta(hours=9, minutes=45))
        w.server.outage()
        for minutes in (0, 15, 30, 45):
            w.at(DAY + dt.timedelta(hours=10, minutes=minutes))
        assert w.run(6)["state"] == "partial"
        tries = w.manifest.conn.execute("SELECT * FROM forecast_step_tries").fetchall()
        assert len(tries) == 49  # one each at 09:45 (step 21 failed); a dead host costs none
        assert w.aws.requests == []  # not yet: the main host has failed for 45 min only
        hosts = dict(w.manifest.conn.execute("SELECT * FROM forecast_hosts").fetchone())
        assert hosts["current"] == "main"
        assert hosts["main_failing_since"] == "2026-11-26T10:00:00+00:00"

        caplog.clear()
        report = w.at(DAY + dt.timedelta(hours=11))
        assert any("switching to the fallback host aws" in m for m in caplog.messages)
        assert [(r["state"], r["error"]) for r in report.runs] == [("processed", None)]
        run = w.run(6)
        assert run["state"] == "processed"
        assert json.loads(run["steps_verified"]) == {str(s): "ok" for s in range(49)}
        files = w.manifest.conn.execute("SELECT host, COUNT(*) FROM forecast_files GROUP BY host")
        assert dict(files.fetchall()) == {"nomads": 96, "aws": 2}  # step 21 from AWS
        step21 = w.manifest.conn.execute(
            "SELECT host, error IS NULL FROM forecast_step_tries WHERE step = 21 ORDER BY id"
        ).fetchall()
        assert [tuple(t) for t in step21] == [("nomads", 0), ("aws", 1)]
        assert min(r.at for r in w.aws.requests) == (DAY + dt.timedelta(hours=11)).timestamp()
        hosts = dict(w.manifest.conn.execute("SELECT * FROM forecast_hosts").fetchone())
        assert (hosts["current"], hosts["switched_at"]) == ("fallback", "2026-11-26T11:00:00+00:00")
        assert not any(w.paths.root.rglob("*.grb2"))

        w.server.restore()
        caplog.clear()
        w.at(DAY + dt.timedelta(hours=11, minutes=15))
        assert any("answers again; back to it" in m for m in caplog.messages)
        hosts = dict(w.manifest.conn.execute("SELECT * FROM forecast_hosts").fetchone())
        assert (hosts["current"], hosts["main_failing_since"]) == ("main", None)
        n_aws = len(w.aws.requests)
        w.at(DAY + dt.timedelta(hours=11, minutes=30))
        assert len(w.aws.requests) == n_aws  # nothing more asked of the fallback

        mixed = json.loads(
            (w.paths.places / "kongsberg" / "2026-11-26" / "gfs-20261126T06Z.json").read_text()
        )
    finally:
        w.close()
    ref = World(tmp_path / "ref", ephemeris)
    try:
        ref.at(DAY + dt.timedelta(hours=10))
        alone = json.loads(
            (ref.paths.places / "kongsberg" / "2026-11-26" / "gfs-20261126T06Z.json").read_text()
        )
    finally:
        ref.close()
    assert mixed["steps"] == alone["steps"]
    assert mixed["meta"] == alone["meta"]


def test_a_failed_runs_raw_files_go_when_it_is_abandoned_and_nothing_else_is_touched(
    tmp_path, ephemeris
):
    """A 00z run fails its format check at 03:45 and keeps its raw files; the complete
    06z run at 09:45 is the point it would have been abandoned, so they go then (it
    stays failed). Files under /staging that aren't a forecast run's raw files (the
    historical downloads, temp files, and the forecast's own other files) are never
    deleted."""
    folder00 = retime_samples(tmp_path / "samples00", 0)
    drop_messages(folder00 / "gfs.t00z.pgrb2.0p25.f012.grb2", lambda k: k["shortName"] == "vis")
    publish = [
        (DAY + dt.timedelta(hours=3, minutes=40), RunRef("gfs", DAY), folder00),
        (PUBLISHED, SAMPLE_RUN, SAMPLES / "box1deg"),
    ]
    w = World(tmp_path / "w", ephemeris, publish=publish)
    staging = w.paths.root.parent
    keep = {
        staging / "grib" / "pl" / "chile" / "2021-01-03.grib": b"GRIB historical",
        staging / "tmp" / "request-17.part": b"half a download",
        w.paths.root / "gfs" / "notes.txt": b"not a run's raw file",
        w.paths.root / "gfs" / "20261126T00Z" / "kongsberg.grb2": b"beside a run folder",
    }
    for path, data in keep.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    try:
        w.at(DAY + dt.timedelta(hours=3, minutes=45))
        r00 = w.run(0)
        assert r00["state"] == "failed" and "VIS:surface" in r00["last_error"]
        raw00 = w.paths.root / "gfs" / "20261126T00Z" / "kongsberg"
        assert len(list(raw00.glob("*.grb2"))) == 98  # kept for the fix (D51 item 8)
        w.at(DAY + dt.timedelta(hours=6))
        assert len(list(raw00.glob("*.grb2"))) == 98  # not abandoned yet

        w.at(DAY + dt.timedelta(hours=9, minutes=45))
        assert w.run(6)["state"] == "processed"
        r00 = w.run(0)
        assert r00["state"] == "failed"  # still says why it failed
        assert not raw00.exists()
        files00 = w.manifest.conn.execute(
            "SELECT raw_deleted_at FROM forecast_files WHERE run_id = ?", (r00["id"],)
        ).fetchall()
        assert all(f[0] == "2026-11-26T09:45:00+00:00" for f in files00)
        assert not any(w.paths.root.rglob("*/kongsberg/*.grb2"))
        for path, data in keep.items():
            assert path.read_bytes() == data, path
    finally:
        w.close()
