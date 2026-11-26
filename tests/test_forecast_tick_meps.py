"""The whole tick with MEPS beside GFS (F1 spec Testing seam 1; ticket #57).

A fake NOMADS serves the GFS samples and a fake THREDDS the MEPS samples for the same
1.1° box round Kongsberg (the 2026-11-26 06z runs). The MEPS samples hold steps 16-19
only (22-01 UTC, the middle of Tonight), so the MEPS run is partial: those four hours
have MEPS values, the others say why not.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.schemas import validate
from astroseeing.forecast.sources.meps import MepsAdapter
from astroseeing.forecast.tick import default_adapters

from fake_http import FakeHttpServer
from forecast_samples import small_box_settings
from forecast_world import DAY, World
from meps_samples import serve_meps


class WithMeps(World):
    """The tick test's CT in miniature, with MEPS added to the Kongsberg area."""

    def __init__(self, tmp_path, ephemeris):
        super().__init__(tmp_path, ephemeris)
        self.settings = small_box_settings(
            tmp_path / "config-meps", **{"areas.kongsberg.models": ["gfs", "meps"]}
        )
        self.thredds = FakeHttpServer()
        self.thredds.__enter__()
        self.meps = MepsAdapter(
            self.settings.models["meps"],
            HttpClient(timeout_s=5),
            self.settings.areas,
            base_url=self.thredds.url,
        )
        serve_meps(self.thredds, "box1deg")

    def adapters(self) -> dict:
        return {**super().adapters(), "meps": self.meps}

    def close(self):
        super().close()
        self.thredds.__exit__(None, None, None)


@pytest.fixture
def world(tmp_path, ephemeris):
    w = WithMeps(tmp_path, ephemeris)
    yield w
    w.close()


def test_the_tick_shows_meps_hours_in_the_kongsberg_place_file_flagged_regional(world):
    # steps 0-15 and 20-48 answer 404 (not in the samples): tried 5 times, from 10:00
    # every 15 min (ticket #58), then the run is final
    for t in (8, 10, 10.25, 10.5, 10.75, 11, 23):
        report = world.at(DAY + dt.timedelta(hours=t))
        assert report.skipped is None
    latest, place = world.latest(), world.place_file()
    validate(latest, "f1-latest/1")
    validate(place, "f1-place/1")

    runs = {r["model"]: r for r in world.runs()}
    assert runs["gfs"]["state"] == "processed"
    # MEPS's 06z run: listed and complete at THREDDS; only steps 16-19 are in the samples
    meps_run = runs["meps"]
    assert meps_run["state"] == "partial" and meps_run["attempts"] == 5
    verified = json.loads(meps_run["steps_verified"])
    assert [s for s, why in verified.items() if why == "ok"] == ["16", "17", "18", "19"]
    assert verified["0"].startswith("not fetched: 5 tries failed") and "404" in verified["0"]
    assert latest["runs"]["meps"]["run_time"] == "2026-11-26T06:00:00Z"
    assert not any(world.paths.root.rglob("*.dods"))  # raw files gone once stored

    # the place file: MEPS is listed, regional-only, with MET Norway's credit
    meps = place["models"]["meps"]
    assert meps["regional"] is True and meps["family"] == "meps" and meps["level_count"] == 13
    assert "MET Norway" in meps["credit"]
    assert not place["models"]["gfs"]["regional"]
    # Kongsberg (162 m) takes MEPS's point 59.660° N 9.662° E, ground 231 m (D47)
    assert meps["model_ground_m"] == pytest.approx(231, abs=1)
    assert meps["observer_height_m"] == meps["model_ground_m"]
    assert place["provenance"]["run_ids"]["meps"] == meps_run["id"]

    hours = {h["time"]: h["models"]["meps"] for h in place["hours"]}
    for t in ("2026-11-26T22:00:00Z", "2026-11-26T23:00:00Z", "2026-11-27T01:00:00Z"):
        h = hours[t]
        assert h["run_id"] == meps_run["id"]
        assert 0 <= h["cloud"]["total_pct"] <= 100
        assert h["seeing"]["osborn_sarazin"]["free_atmosphere_arcsec"] > 0
        assert h["fog"]["fog_fraction_pct"] != "absent" and h["fog"]["visibility_m"] != "absent"
        assert h["fog"]["weather_code"] == "absent"
    assert hours["2026-11-26T21:00:00Z"] == {"missing": "partial"}
    assert hours["2026-11-27T02:00:00Z"] == {"missing": "partial"}


def test_the_default_adapters_include_meps(tmp_path):
    settings = small_box_settings(tmp_path)
    adapters = default_adapters(settings, HttpClient(timeout_s=5))
    assert isinstance(adapters["meps"], MepsAdapter)
    assert adapters["meps"].model.regional and adapters["meps"].model.hosts.fallback is None
