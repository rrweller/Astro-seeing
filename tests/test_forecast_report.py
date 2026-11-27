"""``astro forecast status`` and ``astro forecast size-report`` (ticket #60, F1-11).

Both commands read the forecast manifest tables and the store folders, and write
neither. The main fixture is a fake week: the end-to-end tick world (``forecast_world``)
publishes one GFS 06z run a day from 26 November to 2 December 2026, and the ticks give
those runs every kind of record the report must show:

- 26 Nov: processed, seen at 10:00 (4 h after its run time);
- 27 Nov: partial, step 48's ``pgrb2b`` file never answers (48 of 49 steps);
- 28 Nov: failed, a variable missing at step 12 (no steps verified, no derived size);
- 29 Nov: processed;
- 30 Nov: processed, first seen at 13:00 (7 h after its run time);
- 1 Dec: processed;
- 2 Dec: seen only, the tick found /staging short of space (nothing fetched).

The same ticks write the real heartbeat (ticket #61) and the per-place day stores on
/data (ticket #59) that the commands read.

Expected numbers come from the sample files' own sizes and the fake clock, never from
the manifest the commands read.
"""

from __future__ import annotations

import datetime as dt
import multiprocessing
import os
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from astroseeing import cli
from astroseeing.forecast.alerts import write_heartbeat
from astroseeing.forecast.report import ReadOnlyManifest
from astroseeing.forecast.sources import RunRef
from astroseeing.forecast.verify import ForecastRecords
from astroseeing.manifest import Manifest

from forecast_samples import SAMPLES, drop_messages, retime_samples, small_box_settings
from forecast_world import DAY, World

NOW = DAY + dt.timedelta(days=6, hours=12)  # 2 Dec 12:00 UTC, the end of the fake week
FAILING_48B = "dir=/gfs.20261127/06/atmos&file=gfs.t06z.pgrb2b.0p25.f048"  # as unquoted


def _week_folder(base, d: int):
    day = (DAY + dt.timedelta(days=d)).date()
    if d == 0:
        return SAMPLES / "box1deg"
    folder = retime_samples(base / f"samples-{day}", 6, day=day)
    if d == 2:
        drop_messages(folder / "gfs.t06z.pgrb2.0p25.f012.grb2", lambda k: k["shortName"] == "vis")
    return folder


@pytest.fixture(scope="module")
def week(tmp_path_factory, ephemeris):
    base = tmp_path_factory.mktemp("week")
    spawn = multiprocessing.get_context("spawn")  # not fork: the test process has threads
    with ProcessPoolExecutor(min(6, os.cpu_count() or 1), mp_context=spawn) as pool:  # ~8 s each
        folders = dict(zip(range(7), pool.map(_week_folder, [base] * 7, range(7)), strict=True))
    schedule = [
        (
            DAY + dt.timedelta(days=d, hours=9, minutes=40),
            RunRef("gfs", DAY + dt.timedelta(days=d, hours=6)),
            folders[d],
        )
        for d in range(7)
    ]
    w = World(base / "ct", ephemeris, publish=schedule)
    w.server.fail("/", status=503, contains=FAILING_48B)  # 27 Nov step 48, every try
    w.folders = folders
    # each run's SSD files, measured the day they were stored (later purged): its place
    # file and its map area grid (ticket #65), both counted in its derived bytes
    w.stored_bytes = {}
    for d in range(7):
        day = DAY + dt.timedelta(days=d)
        if d == 6:
            w.free_bytes = lambda path: 0.0  # 2 Dec: seen, but no room to fetch
        first = day + dt.timedelta(hours=13 if d == 4 else 10)
        times = [first]
        if d == 1:  # step 48's five tries, a minute or more apart: then the run is final
            times += [first + dt.timedelta(minutes=5 * k) for k in range(1, 5)]
        for t in times:
            w.at(t)
        run_time = day + dt.timedelta(hours=6)
        stored = w.paths.places / "kongsberg" / f"{run_time:%Y-%m-%d}"
        stored = stored / f"gfs-{run_time:%Y%m%dT%HZ}.json"
        area = w.paths.areas / "kongsberg" / f"gfs-{run_time:%Y%m%dT%HZ}.npz"
        if stored.exists():
            w.stored_bytes[run_time] = stored.stat().st_size + area.stat().st_size
    yield w
    w.close()


def _size(path) -> int:
    return path.stat().st_size


def _tree_bytes(path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _folder_bytes(folder) -> int:
    return sum(_size(f) for f in folder.glob("*.grb2"))


@pytest.fixture
def env(week, monkeypatch):
    base = week.paths.root.parent.parent  # the World's tmp folder
    monkeypatch.setenv("ASTRO_DATA_ROOT", str(base / "data"))
    monkeypatch.setenv("ASTRO_STAGING", str(base / "staging"))
    monkeypatch.setenv("ASTRO_STATE_DIR", str(base / "state"))
    monkeypatch.setenv("ASTRO_LOG_DIR", str(base / "logs"))
    return week


def _settings_arg(w: World) -> list[str]:
    return ["--settings", str(w.paths.root.parent.parent / "config" / "forecast.yaml")]


@pytest.mark.slow  # the fake week's ticks, ~1 min once per module
def test_status_lists_each_models_latest_runs_with_state_age_steps_and_staleness(env, capsys):
    code = cli.main(["forecast", "status", *_settings_arg(env), "--now", "2026-12-02T12:00:00Z"])
    out = capsys.readouterr().out
    assert code == 0
    # the newest usable run is 1 Dec 06z (2 Dec's was never fetched): 30 h old, stale
    assert (
        "gfs kongsberg: newest usable run 2026-12-01T06:00:00Z, 30.0 h old, stale (over 24 h)"
        in out
    )
    lines = [line.split() for line in out.splitlines() if line.startswith("  2026-")]
    assert lines == [
        ["2026-12-02T06:00:00Z", "seen", "6.0", "missing"],
        ["2026-12-01T06:00:00Z", "processed", "30.0", "49/49"],
        ["2026-11-30T06:00:00Z", "processed", "54.0", "49/49"],
        ["2026-11-29T06:00:00Z", "processed", "78.0", "49/49"],
    ]
    # the heartbeat the tick itself wrote: its last tick was 2 Dec 10:00
    assert "last tick: 2026-12-02T10:00:00Z, 120 min ago" in out


def _table(text: str, heading: str) -> list[list[str]]:
    """The body rows of the Markdown table under ``## heading``, as lists of cells."""
    lines = text.splitlines()
    i = lines.index(f"## {heading}")
    rows, started = [], False
    for line in lines[i + 1 :]:
        if line.startswith("|"):
            started = True
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif started:
            break
    return rows[2:]  # without the header and the |---| line


def _expected_week(w: World) -> dict[str, dict]:
    """Each run's numbers, worked out from the sample files and the fake clock."""
    f = w.folders
    partial = _folder_bytes(f[1]) - _size(f[1] / "gfs.t06z.pgrb2b.0p25.f048.grb2")
    exp = {}
    for d, (state, nbytes, steps) in enumerate(
        [
            ("processed", _folder_bytes(f[0]), "49/49"),
            ("partial", partial, "48/49"),
            ("failed", _folder_bytes(f[2]), "missing"),
            ("processed", _folder_bytes(f[3]), "49/49"),
            ("processed", _folder_bytes(f[4]), "49/49"),
            ("processed", _folder_bytes(f[5]), "49/49"),
            ("seen", None, "missing"),
        ]
    ):
        run_time = DAY + dt.timedelta(days=d, hours=6)
        stored = w.stored_bytes.get(run_time)
        exp[f"{run_time:%Y-%m-%dT%H:%M:%SZ}"] = {
            "state": state,
            "delay": "7.00" if d == 4 else "4.00",
            "bytes": "missing" if nbytes is None else str(nbytes),
            "steps": steps,
            "derived": str(stored) if state in ("processed", "partial") else "missing",
        }
    return exp


@pytest.mark.slow  # the fake week's ticks, ~1 min once per module
def test_size_report_prints_and_writes_each_runs_numbers_and_the_totals(env, tmp_path, capsys):
    out_file = tmp_path / "size.md"
    code = cli.main(
        [
            "forecast",
            "size-report",
            *_settings_arg(env),
            "--now",
            "2026-12-02T12:00:00Z",
            "--out",
            str(out_file),
        ]
    )
    printed = capsys.readouterr().out
    assert code == 0
    report = out_file.read_text()
    assert report in printed  # printed in full, then where it went
    assert "2026-11-25T12:00:00Z to 2026-12-02T12:00:00Z" in report  # the last 7 days

    exp = _expected_week(env)
    rows = _table(report, "Runs")
    head = [
        "model",
        "area",
        "run time",
        "state",
        "first seen",
        "delay h",
        "steps verified",
        "bytes",
        "download s",
        "processing s",
        "derived bytes",
        "run id",
    ]
    got = {r[2]: dict(zip(head, r, strict=True)) for r in rows}
    assert list(got) == list(exp)  # all seven runs, oldest first
    for run_time, e in exp.items():
        g = got[run_time]
        assert (g["model"], g["area"]) == ("gfs", "kongsberg")
        assert (g["state"], g["delay h"], g["steps verified"]) == (
            e["state"],
            e["delay"],
            e["steps"],
        )
        assert (g["bytes"], g["derived bytes"]) == (e["bytes"], e["derived"])
    # a run that never got that far shows its seconds as missing, never as zero
    assert got["2026-12-02T06:00:00Z"]["download s"] == "missing"
    assert got["2026-11-28T06:00:00Z"]["processing s"] == "missing"
    assert float(got["2026-11-26T06:00:00Z"]["download s"]) > 0

    # the per-model totals, checked by hand against the sample sizes
    (gfs,) = _table(report, "Per model")
    total_bytes = sum(int(e["bytes"]) for e in exp.values() if e["bytes"] != "missing")
    total_derived = sum(int(e["derived"]) for e in exp.values() if e["derived"] != "missing")
    cells = dict(
        zip(
            [
                "model",
                "area",
                "runs",
                "steps verified",
                "bytes",
                "median bytes per run",
                "median delay h",
                "max delay h",
                "download s",
                "processing s",
                "derived bytes",
            ],
            gfs,
            strict=True,
        )
    )
    assert cells["runs"] == "7"
    assert cells["steps verified"] == f"{4 * 49 + 48} of {5 * 49} (5 of 7 runs)"
    assert cells["bytes"] == f"{total_bytes} (6 of 7 runs)"
    assert cells["derived bytes"] == f"{total_derived} (5 of 7 runs)"
    assert (cells["median delay h"], cells["max delay h"]) == ("4.00", "7.00")

    # the day stores the tick wrote to /data (ticket #59): 26 Nov to 1 Dec are final (2
    # Dec's 12 and 18z runs could still come), but 28 Nov's only run failed and stored
    # nothing, so it has no store; each is measured on disk
    days = env.manifest.conn.execute(
        "SELECT day, outcome, path, bytes FROM forecast_place_days ORDER BY day"
    ).fetchall()
    assert [(d["day"], d["outcome"]) for d in days] == [
        (day, "written")
        for day in ("2026-11-26", "2026-11-27", "2026-11-29", "2026-11-30", "2026-12-01")
    ]
    on_disk = sum(_tree_bytes(Path(d["path"])) for d in days)
    assert on_disk == sum(d["bytes"] for d in days)  # as F1-10 recorded them
    (store,) = _table(report, "Saved places' day stores on /data")
    assert store == ["kongsberg", "5", str(on_disk), str(round(on_disk / 5)), "5", str(on_disk)]

    # the comparison with the estimates (D45 item 5, D51 item 3)
    estimates = {r[0]: r for r in _table(report, "Against the estimates")}
    assert estimates["Store per saved place per day"][2] == "~46 KB"
    assert estimates["Store per saved place per day"][3].endswith(" KB (5 days)")
    assert "missing" in estimates["ICON-EU raw per 48 h run"][3]  # no ICON-EU in this week


@pytest.mark.slow  # the fake week's ticks, ~1 min once per module
def test_size_report_takes_a_range(env, tmp_path, capsys):
    out_file = tmp_path / "range.md"
    cli.main(
        [
            "forecast",
            "size-report",
            *_settings_arg(env),
            "--now",
            "2026-12-02T12:00:00Z",
            "--start",
            "2026-11-29",
            "--end",
            "2026-12-01",
            "--out",
            str(out_file),
        ]
    )
    rows = _table(out_file.read_text(), "Runs")
    assert [r[2] for r in rows] == ["2026-11-29T06:00:00Z", "2026-11-30T06:00:00Z"]


def _cell(value, kind: str) -> str:
    """How the report must show a manifest value: ``missing`` for NULL, exact integers,
    seconds to the millisecond."""
    if value is None:
        return "missing"
    return f"{value:.3f}" if kind == "s" else str(value)


@pytest.mark.slow  # the fake week's ticks, ~1 min once per module
def test_size_report_runs_table_matches_the_manifest_exactly(env, tmp_path):
    out_file = tmp_path / "exact.md"
    cli.main(
        [
            "forecast",
            "size-report",
            *_settings_arg(env),
            "--now",
            "2026-12-02T12:00:00Z",
            "--out",
            str(out_file),
        ]
    )
    rows = {r[2]: r for r in _table(out_file.read_text(), "Runs")}
    db = env.manifest.conn.execute("SELECT * FROM forecast_runs ORDER BY run_time").fetchall()
    assert len(db) == len(rows) == 7
    for r in db:
        run_time = dt.datetime.fromisoformat(r["run_time"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        first = dt.datetime.fromisoformat(r["first_seen_at"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = rows[run_time]
        assert row[:5] == [r["model"], r["area"], run_time, r["state"], first]
        assert row[7:] == [
            _cell(r["bytes"], "b"),
            _cell(r["download_seconds"], "s"),
            _cell(r["processing_seconds"], "s"),
            _cell(r["derived_bytes"], "b"),
            str(r["id"]),
        ]


def _tree(root) -> dict:
    """Every file under ``root``: its bytes and modification time."""
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _manifest_state(w: World) -> dict:
    """The manifest's main file and write-ahead log, byte for byte, and every row. (The
    ``-shm`` index is left out: SQLite readers mark their reads in it by design.)"""
    path = w.manifest.path
    wal = path.with_name(path.name + "-wal")
    tables = [
        r[0] for r in w.manifest.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    ]
    return {
        "main": path.read_bytes(),
        "wal": wal.read_bytes() if wal.exists() else None,
        "rows": {
            t: [tuple(r) for r in w.manifest.conn.execute(f"SELECT * FROM {t}")] for t in tables
        },
    }


@pytest.mark.slow  # the fake week's ticks, ~1 min once per module
def test_neither_command_writes_to_the_manifest_or_to_data(env, tmp_path, capsys):
    data = env.paths.root.parent.parent / "data"
    before_data, before_manifest = _tree(data), _manifest_state(env)
    assert any(".zarr" in p for p in before_data)  # there is something to protect
    cli.main(["forecast", "status", *_settings_arg(env), "--now", "2026-12-02T12:00:00Z"])
    cli.main(
        [
            "forecast",
            "size-report",
            *_settings_arg(env),
            "--now",
            "2026-12-02T12:00:00Z",
            "--out",
            str(tmp_path / "r.md"),
        ]
    )
    assert _tree(data) == before_data
    assert _manifest_state(env) == before_manifest


@pytest.mark.slow  # the fake week's ticks, ~1 min once per module
def test_the_read_only_manifest_refuses_writes(env):
    with ReadOnlyManifest(env.manifest.path) as m, pytest.raises(sqlite3.OperationalError):
        m.conn.execute("DELETE FROM forecast_runs")


# -- a hand-filled manifest: two models, every kind of missing value -------------------


@pytest.fixture
def small(tmp_path, monkeypatch):
    """A manifest filled through ``ForecastRecords`` with exact numbers: GFS with two runs
    (one processed, one failed), ICON-EU with none."""
    for name in ("data", "staging", "state", "logs"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("ASTRO_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ASTRO_STAGING", str(tmp_path / "staging"))
    monkeypatch.setenv("ASTRO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ASTRO_LOG_DIR", str(tmp_path / "logs"))
    small_box_settings(tmp_path / "config", **{"areas.kongsberg.models": ["gfs", "icon_eu"]})
    m = Manifest(tmp_path / "state" / "manifest.sqlite")
    rec = ForecastRecords(m)
    t00, t06 = DAY, DAY + dt.timedelta(hours=6)
    at = t00 + dt.timedelta(hours=4)
    steps = range(49)
    a = rec.seen("gfs", "kongsberg", t00, steps, at=t00 + dt.timedelta(hours=3, minutes=30))
    rec.transition(a, ("seen",), "fetching", at=at)
    rec.transition(a, ("fetching",), "fetched", at=at, bytes=20_000_000, download_seconds=98.25)
    rec.transition(a, ("fetched",), "verified", at=at, steps_verified={s: "ok" for s in steps})
    rec.transition(
        a, ("verified",), "processed", at=at, derived_bytes=150_000, processing_seconds=12.5
    )
    b = rec.seen("gfs", "kongsberg", t06, steps, at=t06 + dt.timedelta(hours=4, minutes=30))
    rec.transition(b, ("seen",), "failed", at=t06 + dt.timedelta(hours=4), last_error="x")
    m.close()
    return tmp_path


def _small_settings(base) -> list[str]:
    return ["--settings", str(base / "config" / "forecast.yaml")]


def test_status_shows_a_model_with_no_runs_and_a_fresh_one_as_not_stale(small, capsys):
    code = cli.main(
        ["forecast", "status", *_small_settings(small), "--now", "2026-11-26T12:00:00Z"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "gfs kongsberg: newest usable run 2026-11-26T00:00:00Z, 12.0 h old, not stale" in out
    lines = [line.split() for line in out.splitlines() if line.startswith("  2026-")]
    assert lines == [
        ["2026-11-26T06:00:00Z", "failed", "6.0", "missing"],
        ["2026-11-26T00:00:00Z", "processed", "12.0", "49/49"],
    ]
    assert "icon_eu kongsberg: no usable run" in out
    assert "  no runs recorded" in out


def test_status_shows_the_last_tick_from_the_heartbeat(small, capsys):
    """The heartbeat in the manifest's real table, written as the tick writes it."""
    m = Manifest(small / "state" / "manifest.sqlite")
    write_heartbeat(m, DAY + dt.timedelta(hours=11), no_tick_h=1.0, health=[])
    write_heartbeat(m, DAY + dt.timedelta(hours=11, minutes=45), no_tick_h=1.0, health=[])
    m.close()
    cli.main(["forecast", "status", *_small_settings(small), "--now", "2026-11-26T12:00:00Z"])
    assert "last tick: 2026-11-26T11:45:00Z, 15 min ago" in capsys.readouterr().out


def test_status_without_a_manifest_fails_and_creates_none(small, capsys):
    (small / "state" / "manifest.sqlite").unlink()
    code = cli.main(["forecast", "status", *_small_settings(small)])
    assert code == 1
    assert "no manifest at" in capsys.readouterr().err
    assert list((small / "state").iterdir()) == []


def test_size_report_totals_say_over_how_many_runs_and_show_absent_things_as_missing(
    small, tmp_path, capsys
):
    out_file = tmp_path / "small.md"
    code = cli.main(
        [
            "forecast",
            "size-report",
            *_small_settings(small),
            "--now",
            "2026-11-27T00:00:00Z",
            "--out",
            str(out_file),
        ]
    )
    assert code == 0
    report = out_file.read_text()
    assert [r[2:] for r in _table(report, "Runs")] == [
        [
            "2026-11-26T00:00:00Z",
            "processed",
            "2026-11-26T03:30:00Z",
            "3.50",
            "49/49",
            "20000000",
            "98.250",
            "12.500",
            "150000",
            "1",
        ],
        [
            "2026-11-26T06:00:00Z",
            "failed",
            "2026-11-26T10:30:00Z",
            "4.50",
            "missing",
            "missing",
            "missing",
            "missing",
            "missing",
            "2",
        ],
    ]
    assert _table(report, "Per model") == [
        [
            "gfs",
            "kongsberg",
            "2",
            "49 of 49 (1 of 2 runs)",
            "20000000 (1 of 2 runs)",
            "20000000",
            "4.00",
            "4.50",
            "98.250 (1 of 2 runs)",
            "12.500 (1 of 2 runs)",
            "150000 (1 of 2 runs)",
        ],
        [
            "icon_eu",
            "kongsberg",
            "0",
            "missing (0 of 0 runs)",
            "missing (0 of 0 runs)",
            "missing",
            "missing",
            "missing",
            "missing (0 of 0 runs)",
            "missing (0 of 0 runs)",
            "missing (0 of 0 runs)",
        ],
    ]
    # no /data stores and no SSD products yet: missing, not zero
    assert _table(report, "Saved places' day stores on /data") == [["kongsberg", *["missing"] * 5]]
    assert _table(report, "SSD products") == [["missing", "missing", "missing"]]
    estimates = {r[0]: r[2:4] for r in _table(report, "Against the estimates")}
    assert estimates["GFS raw per run"] == ["~30 MB", "20.0 MB (median of 1 runs)"]
    assert estimates["F1 area grids"][1].startswith("missing")
    assert estimates["Store per saved place per day"][1].startswith("missing")


def test_size_report_measures_the_ssd_products_folder(small, tmp_path):
    products = small / "staging" / "forecast" / "products"
    (products / "sets" / "a").mkdir(parents=True)
    (products / "sets" / "a" / "x.u8").write_bytes(b"0" * 600)
    (products / "sets" / "a" / "y.json").write_bytes(b"0" * 400)
    (products / "latest.json").write_bytes(b"0" * 50)
    out_file = tmp_path / "ssd.md"
    cli.main(
        [
            "forecast",
            "size-report",
            *_small_settings(small),
            "--now",
            "2026-11-27T00:00:00Z",
            "--out",
            str(out_file),
        ]
    )
    report = out_file.read_text()
    assert _table(report, "SSD products") == [
        ["latest.json", "1", "50"],
        ["sets", "2", "1000"],
        ["total", "3", "1050"],
    ]
    estimates = {r[0]: r[2:4] for r in _table(report, "Against the estimates")}
    assert estimates["F1 area grids"] == ["under 1 GB", "1.1 KB"]


def test_size_report_reads_the_recorded_day_stores_and_records_its_provenance(small, tmp_path):
    import astroseeing

    places = small / "data" / "forecast" / "places" / "kongsberg"
    (places / "2026-11-26.zarr").mkdir(parents=True)
    (places / "2026-11-26.zarr" / "zarr.json").write_bytes(b"0" * 700)
    (places / "2026-11-25.zarr").mkdir()  # another store's content: refused
    (places / ".2026-11-27.zarr.tmp").mkdir()  # a write in progress
    m = Manifest(small / "state" / "manifest.sqlite")
    rec = ForecastRecords(m)
    for day, outcome, nbytes in [("2026-11-26", "written", 700), ("2026-11-25", "refused", None),
                                 ("2026-11-24", "written", 900)]:  # fmt: skip
        rec.record_place_day("kongsberg", dt.date.fromisoformat(day), outcome,
                             str(places / f"{day}.zarr"), nbytes, "0" * 64, None,
                             at=DAY)  # fmt: skip
    m.close()
    out_file = tmp_path / "prov.md"
    cli.main(["forecast", "size-report", *_small_settings(small), "--now",
              "2026-11-27T00:00:00Z", "--out", str(out_file)])  # fmt: skip
    report = out_file.read_text()
    assert _table(report, "Saved places' day stores on /data") == [
        ["kongsberg", "1", "700", "700", "1", "700"]
    ]
    assert "Recorded as stored but not on disk, kongsberg: 2026-11-24." in report
    assert "Refused (another store with other content is there), kongsberg: 2026-11-25." in report
    assert "Not counted (not in the manifest), kongsberg: .2026-11-27.zarr.tmp." in report
    settings = small_box_settings(
        tmp_path / "again", **{"areas.kongsberg.models": ["gfs", "icon_eu"]}
    )
    assert f"astroseeing {astroseeing.__version__}" in report
    assert f"forecast settings hash `{settings.config_hash}`" in report
    assert "Commit `" in report and "Commit `unknown`" not in report
