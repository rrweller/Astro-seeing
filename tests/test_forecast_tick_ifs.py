"""The whole tick with IFS beside GFS (F1 spec Testing seam 1; ticket #56).

A fake NOMADS serves the GFS samples (the 2026-11-26 06z run, out from 09:40 UTC) and
a fake ECMWF portal the IFS samples (the same run, out from 12:27 UTC, as the
dissemination schedule has it), both for the small box round Kongsberg.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from forecast_ifs_samples import SAMPLE_RUN, serve_samples

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.schemas import validate
from astroseeing.forecast.settings import load_settings
from astroseeing.forecast.sources.ifs import IfsAdapter
from astroseeing.forecast.tick import default_adapters, tick

from fake_http import FakeHttpServer
from forecast_samples import small_box_settings
from forecast_world import BUILD, DAY, World

IFS_PUBLISHED = DAY + dt.timedelta(hours=12, minutes=27)


class IfsWorld(World):
    """``World`` with IFS in the Kongsberg area beside GFS, from its own fake portal."""

    def __init__(self, tmp_path, ephemeris):
        super().__init__(tmp_path, ephemeris)
        self.settings = small_box_settings(
            tmp_path / "config-ifs", **{"areas.kongsberg.models": ["gfs", "ifs"]}
        )
        self.portal = FakeHttpServer()
        self.portal.__enter__()
        self.ifs = IfsAdapter(
            self.settings.models["ifs"],
            HttpClient(timeout_s=5),
            self.settings.areas,
            base_url=self.portal.url,
        )
        self.ifs_published = False

    def at(self, now: dt.datetime):
        from forecast_samples import serve_samples as serve_gfs
        from forecast_world import PUBLISHED

        if now >= PUBLISHED and not self.published:
            serve_gfs(self.server, self.gfs, self.area, self.gfs.model.steps_h, folder=self.folder)
            self.published = True
        if now >= IFS_PUBLISHED and not self.ifs_published:
            serve_samples(self.portal, self.ifs.model.steps_h)
            self.ifs_published = True
        return tick(
            now,
            self.settings,
            {"gfs": self.gfs, "ifs": self.ifs},
            self.manifest,
            self.paths,
            ephemeris=self.ephemeris,
            build=BUILD,
        )

    def close(self):
        super().close()
        self.portal.__exit__(None, None, None)


@pytest.fixture
def world(tmp_path, ephemeris):
    w = IfsWorld(tmp_path, ephemeris)
    yield w
    w.close()


def test_ifs_hours_reach_the_kongsberg_place_file_with_the_hours_between_absent(world):
    for hour in range(24):
        assert world.at(DAY + dt.timedelta(hours=hour)).skipped is None
    latest, place = world.latest(), world.place_file()
    validate(latest, "f1-latest/1")
    validate(place, "f1-place/1")

    runs = {r["model"]: r for r in world.runs()}
    ifs = runs["ifs"]
    assert ifs["state"] == "processed" and ifs["attempts"] == 1
    assert json.loads(ifs["steps_verified"]) == {str(s): "ok" for s in range(0, 49, 3)}
    assert latest["runs"]["ifs"] == {
        "run_id": ifs["id"],
        "run_time": "2026-11-26T06:00:00Z",
        "state": "processed",
        "stale": False,
    }
    # only the needed bytes were asked for, one index and a few ranges per step
    gets = [r for r in world.portal.requests if r.method == "GET"]
    assert sum(r.path.endswith(".index") for r in gets) == 17
    assert all("Range" in r.headers for r in gets if r.path.endswith(".grib2"))
    assert not any(world.paths.root.rglob("*.grib2"))  # raw files gone once verified

    # Tonight is 12 UTC on the 26th to 11 UTC on the 27th: IFS has every third hour
    # (12, 15, 18, … from its 06z run) and the hours between stay absent, never filled
    by_time = {h["time"]: h["models"]["ifs"] for h in place["hours"]}
    assert len(by_time) == 24
    for time, value in by_time.items():
        hour = int(time[11:13])
        if hour % 3 == 0:
            assert value["run_id"] == ifs["id"]
            assert 0 <= value["cloud"]["total_pct"] <= 100
            assert value["seeing"]["osborn_sarazin"]["free_atmosphere_arcsec"] > 0
            assert value["fog"]["dewpoint_depression_2m_k"] != "absent"
            assert value["fog"]["visibility_m"] == "absent"
        else:
            assert value == {"missing": "off_step"}
    # GFS is still there for every hour
    assert all("run_id" in h["models"]["gfs"] for h in place["hours"])

    m = place["models"]["ifs"]
    height = world.settings.places["kongsberg"].height.metres
    assert m["level_count"] == 13 and not m["regional"] and "ECMWF" in m["credit"]
    # D47's evidence: IFS's ground at 59.75° N 9.75° E is 261 m, so Kongsberg (162 m)
    # is raised by about 99 m
    assert m["model_ground_m"] == pytest.approx(261, abs=1)
    assert m["raise_m"] == pytest.approx(m["model_ground_m"] - height)


def test_the_tick_has_an_ifs_adapter_for_both_areas():
    settings = load_settings()
    adapters = default_adapters(settings, HttpClient())
    assert isinstance(adapters["ifs"], IfsAdapter)
    assert "ifs" in settings.areas["kongsberg"].models
    assert "ifs" in settings.areas["paranal"].models
    assert {p.area for p in settings.places.values()} == {"kongsberg", "paranal"}
    assert SAMPLE_RUN.model == "ifs"
