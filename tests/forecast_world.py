"""One CT in miniature for tests that run the forecast tick on the saved GFS samples.

Settings cut to the sample box, a fake NOMADS that publishes the 2026-11-26 06z run
from 09:40 UTC, a temporary manifest and temporary folders (ticket #51). Shared by the
tick's own tests and the page's browser tests (ticket #52), so the page is tested
against what the back end really writes.

For the run rules (ticket #58) a world can also publish other runs at other times
(``publish``), mirror them on a fake AWS bucket in its own layout (``mirror=True``, the
GFS fallback host), and edit the settings. Both fake hosts stamp each request with the
world's fake clock, so request spacing is checked on the time the tick saw.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.sources import RunRef
from astroseeing.forecast.sources.gfs import GfsAdapter, RatePacer
from astroseeing.forecast.tick import BuildInfo, ForecastPaths, tick
from astroseeing.manifest import Manifest
from astroseeing.paths import Paths

from fake_http import FakeHttpServer
from forecast_samples import (
    SAMPLE_RUN,
    SAMPLES,
    serve_aws_samples,
    serve_samples,
    small_box_settings,
)

DAY = dt.datetime(2026, 11, 26, tzinfo=dt.UTC)
PUBLISHED = DAY + dt.timedelta(hours=9, minutes=40)  # the 06z run appears on NOMADS
BUILD = BuildInfo(commit="a" * 40, software={"astroseeing": "0.1.0"})


class World:
    """Settings, a fake NOMADS (and AWS mirror), a temp manifest and temp folders: one CT
    in miniature. ``publish`` lists ``(time, run, sample folder)``: each run appears on
    the fake hosts from that time (default: the 06z samples from 09:40)."""

    def __init__(
        self,
        tmp_path,
        ephemeris,
        sample_folder=None,
        publish: list[tuple[dt.datetime, RunRef, Path]] | None = None,
        settings_edits: dict | None = None,
        mirror: bool = False,
    ):
        self.settings = small_box_settings(tmp_path / "config", **(settings_edits or {}))
        self.paths = ForecastPaths.from_paths(
            Paths(
                data_root=tmp_path / "data",
                staging=tmp_path / "staging",
                state_dir=tmp_path / "state",
            )
        )
        self.manifest = Manifest(tmp_path / "state" / "manifest.sqlite")
        self.ephemeris = ephemeris
        self.now = DAY
        self.server = FakeHttpServer(clock=self.clock)
        self.server.__enter__()
        self.aws = FakeHttpServer(clock=self.clock)
        self.aws.__enter__()
        model = self.settings.models["gfs"]
        self.gfs = GfsAdapter(
            model,
            HttpClient(timeout_s=5),
            self.settings.areas,
            base_url=self.server.url,
            pacer=RatePacer(None),
            fallback_url=self.aws.url,
        )
        self.area = self.settings.areas["kongsberg"]
        self.folder = sample_folder or SAMPLES / "box1deg"
        self.schedule = publish or [(PUBLISHED, SAMPLE_RUN, self.folder)]
        self.mirror = mirror
        self.done: set[int] = set()
        self.published = False  # any run published yet
        # the tick's other seams (ticket #61): None keeps the tick's defaults
        self.free_bytes = None  # /staging's free space, e.g. lambda path: 30e9
        self.page_http = None  # the client the served-page check uses
        self.notify = None  # the alert notifier, (message, title, priority)

    def clock(self) -> float:
        return self.now.timestamp()

    def at(self, now: dt.datetime):
        self.now = now
        for k, (when, run, folder) in enumerate(self.schedule):
            if now >= when and k not in self.done:
                steps = self.gfs.model.steps_h
                serve_samples(self.server, self.gfs, self.area, steps, folder=folder, run=run)
                if self.mirror:
                    serve_aws_samples(self.aws, steps, folder=folder, run=run)
                self.done.add(k)
                self.published = True
        return tick(
            now,
            self.settings,
            self.adapters(),
            self.manifest,
            self.paths,
            ephemeris=self.ephemeris,
            build=BUILD,
            free_bytes=self.free_bytes,
            http=self.page_http,
            notify=self.notify,
        )

    def adapters(self) -> dict:
        """The adapters each tick gets (a test world with more models adds to them)."""
        return {"gfs": self.gfs}

    def latest(self) -> dict:
        return json.loads(self.paths.latest.read_text())

    def place_file(self) -> dict:
        latest = self.latest()
        return json.loads(
            (self.paths.products / latest["set_path"] / "place-kongsberg.json").read_text()
        )

    def runs(self) -> list[sqlite3.Row]:
        return self.manifest.conn.execute("SELECT * FROM forecast_runs ORDER BY id").fetchall()

    def run(self, hour: int) -> sqlite3.Row:
        """The manifest row of the run of ``hour`` UTC on 26 November."""
        (row,) = [r for r in self.runs() if r["run_time"] == f"2026-11-26T{hour:02d}:00:00+00:00"]
        return row

    def close(self):
        self.manifest.close()
        self.server.__exit__(None, None, None)
        self.aws.__exit__(None, None, None)
