"""The whole tick, end to end (F1 spec Testing seam 1; ticket #51).

A fake NOMADS serves the saved GFS samples (the 2026-11-26 06z run, published from
09:40 UTC in the fake), a fake clock steps through the day, and the manifest is a
temporary SQLite file. Everything the tick touches lives under ``tmp_path``.
"""

from __future__ import annotations

import datetime as dt
import json
import stat

import pytest

from astroseeing.forecast.schemas import validate
from astroseeing.forecast.tick import tick_lock

from forecast_samples import copy_samples, drop_messages, edit_values, small_box_settings
from forecast_world import DAY, PUBLISHED, World
from icon_eu_samples import IconWorld


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


@pytest.mark.slow  # ~40 s: 5244 files from the fake DWD
def test_icon_eu_hours_show_in_the_kongsberg_place_file(tmp_path, ephemeris):
    """Ticket #55: a second forecast model behind the same interface, from a fake DWD."""
    w = IconWorld(tmp_path, ephemeris)
    try:
        for hour in (9, 10, 11):
            assert w.at(DAY + dt.timedelta(hours=hour)).skipped is None
        latest, place = w.latest(), w.place_file()
        validate(latest, "f1-latest/1")
        validate(place, "f1-place/1")

        runs = {r["model"]: r for r in w.runs()}
        icon = runs["icon_eu"]
        assert icon["state"] == "processed" and icon["attempts"] == 1
        assert json.loads(icon["steps_verified"]) == {str(s): "ok" for s in range(49)}
        # the download size per run is recorded (the 7-day size report reads it):
        # every file served, the model ground once and 107 files a step
        files = w.manifest.conn.execute(
            "SELECT * FROM forecast_files WHERE run_id = ?", (icon["id"],)
        ).fetchall()
        served = [r for r in w.dwd.requests if r.method == "GET" and r.path.endswith(".bz2")]
        assert len(files) == len(served) == 1 + 49 * 107
        assert icon["bytes"] == sum(f["bytes"] for f in files) > 0
        assert all(f["host"] == "dwd-opendata" for f in files)
        assert all(f["verified"] == 1 and f["raw_deleted_at"] for f in files)
        assert not any(w.paths.root.rglob("*.bz2"))

        assert latest["runs"]["icon_eu"]["run_time"] == "2026-11-26T06:00:00Z"
        assert not latest["runs"]["icon_eu"]["stale"]
        assert place["provenance"]["run_ids"] == {"gfs": runs["gfs"]["id"], "icon_eu": icon["id"]}
        for h in place["hours"]:  # Tonight is 12 UTC on the 26th to 11 UTC on the 27th
            i = h["models"]["icon_eu"]
            assert i["run_id"] == icon["id"]
            assert 0 <= i["cloud"]["total_pct"] <= 100
            assert i["seeing"]["osborn_sarazin"]["free_atmosphere_arcsec"] > 0
            assert i["fog"]["visibility_m"] != "absent" and i["fog"]["weather_code"] != "absent"
            assert i["fog"]["fog_fraction_pct"] == "absent"
        model = place["models"]["icon_eu"]
        assert model["family"] == "icon" and not model["regional"]
        assert model["level_count"] == 20 and "Deutscher Wetterdienst" in model["credit"]
        # Kongsberg takes ICON-EU's point 59.6875° N 9.625° E, whose ground is 347 m
        # (D47's evidence): raised by about 185 m above the town's 162 m
        assert model["model_ground_m"] == pytest.approx(347, abs=1)
        assert model["observer_height_m"] == model["model_ground_m"]
        assert model["terrain_caveat_m"] == model["raise_m"] == pytest.approx(185, abs=1)
        # the map grid is ICON-EU's, the finest global family (D60 item 2)
        assert (latest["grid"]["dlat"], latest["grid"]["nlat"]) == (0.0625, 17)
    finally:
        w.close()


def test_cloud_a_hair_over_100_is_published_as_100_and_counted(world):
    """Ticket #80: GRIB packing decodes a full layer as 100.00000610351563 %. At 10:00 UTC
    on 27 November, Tonight (27th-28th) holds four such hours at Kongsberg's GFS point
    (steps 37 and 39 high cloud, 43 and 48 mid cloud, read straight from the samples)."""
    world.at(DAY + dt.timedelta(hours=10))  # the 06z run is fetched and stored
    report = world.at(DAY + dt.timedelta(days=1, hours=10))
    assert report.skipped is None

    place = world.place_file()
    validate(place, "f1-place/1")
    gfs = {h["time"]: h["models"]["gfs"] for h in place["hours"]}
    cloud = {t: g["cloud"] for t, g in gfs.items() if "cloud" in g}
    assert len(cloud) == 19  # the run ends at 06 UTC on the 28th (step 48)
    assert cloud["2026-11-27T19:00:00Z"]["high_pct"] == 100.0  # step 37
    assert cloud["2026-11-27T21:00:00Z"]["high_pct"] == 100.0  # step 39
    assert cloud["2026-11-28T01:00:00Z"]["mid_pct"] == 100.0  # step 43
    assert cloud["2026-11-28T06:00:00Z"]["mid_pct"] == 100.0  # step 48
    assert all(0 <= v <= 100 for c in cloud.values() for v in c.values())

    # the run's QC counts: values set to 100, per field, over the 5 × 5 points × 49 steps
    # the run read, as counted straight from the samples with eccodes; none set to 0
    (run,) = world.runs()
    assert run["state"] == "processed"
    stored = json.loads(
        (world.paths.places / "kongsberg" / "2026-11-26" / "gfs-20261126T06Z.json").read_text()
    )
    qc = stored["qc"]["cloud_range"]
    n = 49 * 5 * 5
    assert qc["high_cloud_pct_set_to_100"] == {"count": 38, "total": n}
    assert qc["mid_cloud_pct_set_to_100"] == {"count": 39, "total": n}
    assert qc["low_cloud_pct_set_to_100"] == {"count": 28, "total": n}
    assert qc["total_cloud_pct_set_to_100"] == {"count": 0, "total": n}
    assert qc["level_cloud_pct_set_to_100"] == {"count": 219, "total": n * 39}
    for name in ("total", "low", "mid", "high", "level"):
        assert qc[f"{name}_cloud_pct_set_to_0"] == {
            "count": 0,
            "total": n * (39 if name == "level" else 1),
        }


def test_cloud_far_over_100_fails_the_run_naming_field_step_and_value(tmp_path, ephemeris):
    """Ticket #80: a cloud value further above 100 % than the tolerance is a data error,
    failed loudly like a format mismatch, never set to 100."""
    folder = copy_samples(tmp_path / "broken")

    def raise_one(values):
        values[7] = 101.0
        return values

    def instant_mid(keys):
        return keys["shortName"] == "mcc" and keys["stepType"] == "instant"

    assert edit_values(folder / "gfs.t06z.pgrb2.0p25.f020.grb2", instant_mid, raise_one) == 1
    w = World(tmp_path / "w", ephemeris, sample_folder=folder)
    try:
        report = w.at(DAY + dt.timedelta(hours=10))
        (run,) = w.runs()
        assert run["state"] == "failed"
        assert "format mismatch" in run["last_error"]
        assert "mid_cloud_pct at step 20 is 101.0" in run["last_error"]
        assert report.runs[0]["state"] == "failed"
        place = w.place_file()  # the page still gets its files, with GFS missing
        validate(place, "f1-place/1")
        assert all(h["models"]["gfs"] == {"missing": "no_run"} for h in place["hours"])
    finally:
        w.close()


#: GFS's runs of 26 November are all final by 27 November 00:00 with a 10 h online window
#: (abandoned or gone 6 h after their run time): 00z never seen (06z is newer), 06z
#: processed, 12z and 18z never published by the fake NOMADS.
SHORT_WINDOW = {"models.gfs.online_window_h": 10}


def files_under(path) -> dict:
    return {str(p.relative_to(path)): (p.stat().st_mtime_ns, p.read_bytes())
            for p in sorted(path.rglob("*")) if p.is_file()}  # fmt: skip


def test_a_place_day_store_appears_once_its_runs_are_final_and_is_never_touched_again(
    tmp_path, ephemeris
):
    w = World(tmp_path, ephemeris, settings_edits=SHORT_WINDOW)
    try:
        store = w.paths.place_days / "kongsberg" / "2026-11-26.zarr"
        appeared = None
        for hour in (0, 9, 10, 17, 18, 23, 24, 25, 30):
            report = w.at(DAY + dt.timedelta(hours=hour))
            if store.exists() and appeared is None:
                appeared, written = hour, files_under(store)
                assert [(d["day"], d["outcome"]) for d in report.days] == [
                    ("2026-11-26", "written")
                ]
            elif appeared is not None:
                assert report.days == [] and files_under(store) == written
        assert appeared == 24  # 27 November 00:00, when the 18z run is gone for good
        assert str(w.paths.place_days).startswith(str(tmp_path / "data"))
        (row,) = w.manifest.conn.execute("SELECT * FROM forecast_place_days").fetchall()
        assert (row["place"], row["day"], row["outcome"]) == ("kongsberg", "2026-11-26", "written")
        assert row["bytes"] == sum(len(b) for _, b in written.values())
    finally:
        w.close()


def test_a_hanging_nas_times_out_without_holding_back_publish(tmp_path, ephemeris):
    import threading
    import time

    from astroseeing.forecast.store.days import DayStores
    from astroseeing.forecast.tick import tick

    from forecast_world import BUILD

    class HangingNas(DayStores):
        release = threading.Event()

        def put(self, content):
            self.release.wait(30)
            return super().put(content)

    edits = {**SHORT_WINDOW, "place_stores.nas_timeout_s": 0.3}
    w = World(tmp_path, ephemeris, settings_edits=edits)
    nas = HangingNas(w.paths.place_days)
    try:
        for hour in (9, 10):  # the 06z run is in; no tick runs from 11:00 on
            w.at(DAY + dt.timedelta(hours=hour))
        before = w.latest()["set_id"]
        t0 = time.monotonic()
        report = tick(DAY + dt.timedelta(hours=32), w.settings, w.adapters(), w.manifest,
                      w.paths, ephemeris=ephemeris, build=BUILD, day_stores=nas)  # fmt: skip
        assert time.monotonic() - t0 < 10
        assert report.published and w.latest()["set_id"] == report.set_id != before
        (day,) = report.days
        assert day["outcome"] == "timed_out" and "no answer from the NAS" in day["error"]
        assert w.manifest.conn.execute("SELECT * FROM forecast_place_days").fetchall() == []
    finally:
        nas.release.set()
        w.close()
