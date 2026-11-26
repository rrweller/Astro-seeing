"""The whole tick, end to end (F1 spec Testing seam 1; ticket #51).

A fake NOMADS serves the saved GFS samples (the 2026-11-26 06z run, published from
09:40 UTC in the fake), a fake clock steps through the day, and the manifest is a
temporary SQLite file. Everything the tick touches lives under ``tmp_path``.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import stat

import pytest

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.schemas import validate
from astroseeing.forecast.sources.gfs import GfsAdapter, RatePacer
from astroseeing.forecast.tick import BuildInfo, ForecastPaths, tick, tick_lock
from astroseeing.manifest import Manifest
from astroseeing.paths import Paths

from fake_http import FakeHttpServer
from forecast_samples import SAMPLES, copy_samples, drop_messages, serve_samples, small_box_settings

DAY = dt.datetime(2026, 11, 26, tzinfo=dt.UTC)
PUBLISHED = DAY + dt.timedelta(hours=9, minutes=40)  # the 06z run appears on NOMADS
BUILD = BuildInfo(commit="a" * 40, software={"astroseeing": "0.1.0"})


class World:
    """Settings, a fake NOMADS, a temp manifest and temp folders: one CT in miniature."""

    def __init__(self, tmp_path, ephemeris, sample_folder=None):
        self.settings = small_box_settings(tmp_path / "config")
        self.paths = ForecastPaths.from_paths(
            Paths(
                data_root=tmp_path / "data",
                staging=tmp_path / "staging",
                state_dir=tmp_path / "state",
            )
        )
        self.manifest = Manifest(tmp_path / "state" / "manifest.sqlite")
        self.ephemeris = ephemeris
        self.server = FakeHttpServer()
        self.server.__enter__()
        model = self.settings.models["gfs"]
        self.gfs = GfsAdapter(
            model,
            HttpClient(timeout_s=5),
            self.settings.areas,
            base_url=self.server.url,
            pacer=RatePacer(None),
        )
        self.area = self.settings.areas["kongsberg"]
        self.folder = sample_folder or SAMPLES / "box1deg"
        self.published = False

    def at(self, now: dt.datetime):
        if now >= PUBLISHED and not self.published:
            serve_samples(
                self.server, self.gfs, self.area, self.gfs.model.steps_h, folder=self.folder
            )
            self.published = True
        return tick(
            now,
            self.settings,
            {"gfs": self.gfs},
            self.manifest,
            self.paths,
            ephemeris=self.ephemeris,
            build=BUILD,
        )

    def latest(self) -> dict:
        return json.loads(self.paths.latest.read_text())

    def place_file(self) -> dict:
        latest = self.latest()
        return json.loads(
            (self.paths.products / latest["set_path"] / "place-kongsberg.json").read_text()
        )

    def runs(self) -> list[sqlite3.Row]:
        return self.manifest.conn.execute("SELECT * FROM forecast_runs").fetchall()

    def close(self):
        self.manifest.close()
        self.server.__exit__(None, None, None)


@pytest.fixture
def world(tmp_path, ephemeris):
    w = World(tmp_path, ephemeris)
    yield w
    w.close()


def snapshot(w: World) -> dict:
    """Every file under the products folder and every forecast manifest row."""
    files = {
        str(p.relative_to(w.paths.root)): p.read_bytes()
        for p in sorted(w.paths.root.rglob("*"))
        if p.is_file()
    }
    rows = {
        t: [tuple(r) for r in w.manifest.conn.execute(f"SELECT * FROM {t}")]
        for t in ("forecast_runs", "forecast_files")
    }
    return {"files": files, "rows": rows}


def test_a_day_of_ticks_publishes_kongsberg_from_the_gfs_run(world):
    set_ids = []
    for hour in range(24):
        report = world.at(DAY + dt.timedelta(hours=hour))
        assert report.skipped is None
        set_ids.append(world.latest()["set_id"])

    latest, place = world.latest(), world.place_file()
    validate(latest, "f1-latest/1")
    validate(place, "f1-place/1")

    # the run: fetched once, verified on all 49 steps, stored, raw files deleted
    (run,) = world.runs()
    assert run["state"] == "processed" and run["attempts"] == 1
    assert json.loads(run["steps_verified"]) == {str(s): "ok" for s in range(49)}
    files = world.manifest.conn.execute("SELECT * FROM forecast_files").fetchall()
    sample_bytes = sum(f.stat().st_size for f in world.folder.glob("*.grb2"))
    assert len(files) == 98 and run["bytes"] == sum(f["bytes"] for f in files) == sample_bytes
    assert all(f["verified"] == 1 and f["raw_deleted_at"] for f in files)
    assert not any(world.paths.root.rglob("*.grb2"))
    fetches = [r for r in world.server.requests if r.method == "GET"]
    assert len(fetches) == 98  # one fetch of the run in the whole day

    # latest.json names the run; the place file has the hours and the models filled
    assert latest["runs"]["gfs"] == {
        "run_id": run["id"],
        "run_time": "2026-11-26T06:00:00Z",
        "state": "processed",
        "stale": False,
    }
    assert latest["provenance"]["commit"] == "a" * 40
    assert latest["provenance"]["config_hash"] == world.settings.config_hash
    assert latest["places"] == [
        {"id": "kongsberg", "name": "Kongsberg", "file": "place-kongsberg.json"}
    ]
    assert place["tonight"] is None and place["moon"] is None  # F1-14 fills them
    assert place["provenance"]["run_ids"] == {"gfs": run["id"]}
    # Tonight at 23 UTC is the night of 26 November: 12 UTC on the 26th to 11 UTC on the 27th
    times = [h["time"] for h in place["hours"]]
    assert times[0] == "2026-11-26T12:00:00Z" and times[-1] == "2026-11-27T11:00:00Z"
    sun = {h["time"]: h["sun_class"] for h in place["hours"]}
    assert sun["2026-11-26T12:00:00Z"] == "day" and sun["2026-11-26T23:00:00Z"] == "dark"
    for h in place["hours"]:
        g = h["models"]["gfs"]
        assert g["run_id"] == run["id"]
        assert 0 <= g["cloud"]["total_pct"] <= 100
        assert g["seeing"]["osborn_sarazin"]["free_atmosphere_arcsec"] > 0
        assert g["fog"]["visibility_m"] != "absent" and g["fog"]["weather_code"] == "absent"
    gfs = place["models"]["gfs"]
    # Kongsberg (59.669° N 9.652° E, 162.28 m by GLO-30) takes GFS's point 59.75° N
    # 9.75° E, whose ground is 327 m (D47's evidence): raised by about 165 m, which is
    # also the terrain caveat
    height = world.settings.places["kongsberg"].height.metres
    assert place["place"]["height_m"] == height == pytest.approx(162.28, abs=0.01)
    assert gfs["model_ground_m"] == pytest.approx(327, abs=1)
    assert gfs["observer_height_m"] == gfs["model_ground_m"]
    assert gfs["raise_m"] == pytest.approx(gfs["model_ground_m"] - height)
    assert gfs["terrain_caveat_m"] == gfs["raise_m"]
    assert gfs["level_count"] == 39 and not gfs["regional"] and "NOAA" in gfs["credit"]
    assert 0 < gfs["gap_to_first_level_m"] < 1000

    # set_id changes only when content changes: once the run is in, it stays put
    first_with_run = set_ids.index(set_ids[-1])
    assert DAY + dt.timedelta(hours=first_with_run) >= PUBLISHED
    assert len(set(set_ids)) <= 3  # yesterday's night, today's night, today's with GFS
    assert sorted(p.name for p in world.paths.sets.iterdir()) == sorted(set(set_ids))[-3:]

    # every published file is world-readable (the web server runs as another user)
    for p in [world.paths.latest, *world.paths.sets.rglob("*")]:
        assert p.stat().st_mode & stat.S_IROTH


def test_rerunning_a_tick_at_the_same_time_changes_nothing(world):
    for hour in (9, 10, 11):
        world.at(DAY + dt.timedelta(hours=hour))
    before = snapshot(world)
    requests_before = len(world.server.requests)
    report = world.at(DAY + dt.timedelta(hours=11))
    assert snapshot(world) == before
    assert not report.published and report.runs == []
    new = world.server.requests[requests_before:]
    assert all(r.method == "HEAD" for r in new)  # only the cheap "is there a newer run?"


def test_a_sample_with_a_variable_removed_fails_the_run_and_keeps_its_raw_files(
    tmp_path, ephemeris
):
    folder = copy_samples(tmp_path / "broken")
    drop_messages(folder / "gfs.t06z.pgrb2.0p25.f012.grb2", lambda k: k["shortName"] == "vis")
    w = World(tmp_path / "w", ephemeris, sample_folder=folder)
    try:
        report = w.at(DAY + dt.timedelta(hours=10))
        (run,) = w.runs()
        assert run["state"] == "failed"
        assert "VIS:surface" in run["last_error"] and "step 12" in run["last_error"]
        assert report.runs == [
            {
                "model": "gfs",
                "area": "kongsberg",
                "run_time": "2026-11-26T06:00:00Z",
                "state": "failed",
                "error": run["last_error"],
            }
        ]
        # raw files stay until the run is retried or abandoned (D51 item 5)
        assert len(list(w.paths.root.rglob("*.grb2"))) == 98
        files = w.manifest.conn.execute("SELECT * FROM forecast_files").fetchall()
        assert all(f["raw_deleted_at"] is None and f["verified"] == 0 for f in files)
        # the page still gets its files: GFS shows as missing, never filled
        place = w.place_file()
        validate(place, "f1-place/1")
        assert all(h["models"]["gfs"] == {"missing": "no_run"} for h in place["hours"])
        assert "gfs" not in w.latest()["runs"] and place["models"] == {}
        # a failed run is not fetched again by the next tick (retries are ticket #58)
        n = len(w.server.requests)
        w.at(DAY + dt.timedelta(hours=11))
        assert all(r.method == "HEAD" for r in w.server.requests[n:])
    finally:
        w.close()


def test_a_second_tick_waits_for_the_lock(world):
    with tick_lock(world.paths.lock):
        report = world.at(DAY + dt.timedelta(hours=10))
    assert report.skipped == "another tick holds the lock"
    assert world.runs() == [] and not world.paths.latest.exists()


@pytest.mark.parametrize("height", [None, "hand-entered"])
def test_a_place_without_a_looked_up_height_refuses_the_tick(tmp_path, ephemeris, height):
    """Ticket #54: the tick never computes a place at a guessed or missing height."""
    w = World(tmp_path, ephemeris)
    edit = (
        None
        if height is None
        else {
            "metres": 162.0,
            "source": "hand-entered",
            "tile": None,
            "sha256": None,
            "posting": None,
            "attribution": None,
        }
    )
    w.settings = small_box_settings(tmp_path / "config2", **{"places.kongsberg.height": edit})
    try:
        report = w.at(DAY + dt.timedelta(hours=10))
        assert "astro forecast place-height kongsberg" in report.skipped
        assert w.runs() == [] and not w.paths.latest.exists()
        assert w.server.requests == []  # nothing fetched either
    finally:
        w.close()


def test_astro_forecast_tick_refuses_a_hand_entered_height_before_any_fetch(
    tmp_path, monkeypatch, capsys
):
    from astroseeing import cli

    for var, name in (
        ("ASTRO_DATA_ROOT", "data"),
        ("ASTRO_STAGING", "staging"),
        ("ASTRO_STATE_DIR", "state"),
    ):
        monkeypatch.setenv(var, str(tmp_path / name))
    hand = {
        "metres": 162.0,
        "source": "hand-entered",
        "tile": None,
        "sha256": None,
        "posting": None,
        "attribution": None,
    }
    small_box_settings(tmp_path / "config", **{"places.kongsberg.height": hand})
    code = cli.main(["forecast", "tick", "--settings", str(tmp_path / "config/forecast.yaml")])
    assert code == 1
    err = capsys.readouterr().err
    assert "refused" in err and "astro forecast place-height kongsberg" in err
    assert not (tmp_path / "state" / "manifest.sqlite").exists()
    assert not (tmp_path / "staging").exists()
