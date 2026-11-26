"""One CT in miniature for tests that run the forecast tick on the saved GFS samples.

Settings cut to the sample box, a fake NOMADS that publishes the 2026-11-26 06z run
from 09:40 UTC, a temporary manifest and temporary folders (ticket #51). Shared by the
tick's own tests and the page's browser tests (ticket #52), so the page is tested
against what the back end really writes.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.sources.gfs import GfsAdapter, RatePacer
from astroseeing.forecast.sources.icon_eu import IconEuAdapter
from astroseeing.forecast.tick import BuildInfo, ForecastPaths, tick
from astroseeing.manifest import Manifest
from astroseeing.paths import Paths

from fake_http import FakeHttpServer
from forecast_samples import SAMPLES, serve_samples, small_box_settings
from icon_eu_samples import sample_messages, serve_icon_samples

DAY = dt.datetime(2026, 11, 26, tzinfo=dt.UTC)
PUBLISHED = DAY + dt.timedelta(hours=9, minutes=40)  # the 06z run appears on NOMADS
BUILD = BuildInfo(commit="a" * 40, software={"astroseeing": "0.1.0"})


class World:
    """Settings, a fake NOMADS, a temp manifest and temp folders: one CT in miniature."""

    def __init__(self, tmp_path, ephemeris, sample_folder=None, icon_eu=False):
        """``icon_eu``: also ICON-EU in the area, from a fake DWD opendata publishing the
        saved samples of the same run at the same time (ticket #55)."""
        edits = {}
        if icon_eu:
            edits = {
                "areas.kongsberg.models": ["gfs", "icon_eu"],
                "areas.kongsberg.map_grid_model": "icon_eu",  # the finest global family
            }
        self.settings = small_box_settings(tmp_path / "config", **edits)
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
        self.adapters = {"gfs": self.gfs}
        self.dwd = None
        if icon_eu:
            self.dwd = FakeHttpServer()
            self.dwd.__enter__()
            self.icon_eu = IconEuAdapter(
                self.settings.models["icon_eu"],
                HttpClient(timeout_s=5),
                self.settings.areas,
                base_url=self.dwd.url,
                pacer=RatePacer(None),
            )
            self.adapters["icon_eu"] = self.icon_eu
        self.area = self.settings.areas["kongsberg"]
        self.folder = sample_folder or SAMPLES / "box1deg"
        self.published = False

    def at(self, now: dt.datetime):
        if now >= PUBLISHED and not self.published:
            serve_samples(
                self.server, self.gfs, self.area, self.gfs.model.steps_h, folder=self.folder
            )
            if self.dwd is not None:
                serve_icon_samples(self.dwd, sample_messages())
            self.published = True
        return tick(
            now,
            self.settings,
            self.adapters,
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
        if self.dwd is not None:
            self.dwd.__exit__(None, None, None)
