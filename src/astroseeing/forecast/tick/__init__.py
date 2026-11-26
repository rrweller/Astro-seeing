"""The tick (F1 spec Module 8): ``astro forecast tick``, every 15 min from
``astro-forecast.timer``; idempotent, manifest-driven, every dependency injected (D51).

Ticket #51 builds steps 1-5 of the spec's order:

1. ask each adapter for its newest published run;
2. fetch, verify and compute what's new (one run at a time, in this process: within
   D51 item 4's limit of 2 worker processes, D72);
3. store each saved place's values (SSD part of Module 6);
4. build each saved place's file (the verdict comes with ticket #63);
5. publish a product set, if anything changed.

A run's manifest row moves ``seen`` → ``fetching`` → ``fetched`` → ``verified`` →
``processed`` (or ``partial`` when some steps are missing, ``failed`` on a format
mismatch or failed verification, ``abandoned`` when given up). The run rules of ticket
#58 (D51 items 5, 7 and 14; D79) live beside the tick: ``tick.hosts`` picks each
model's host (the fallback after the main host has failed for 1 h), ``tick.runs`` works
each open run over as many ticks as it needs (each step tried at most 5 times, at least
1 min apart; abandoned runs; raw files deleted once final), and ``verify.rules`` holds
the rules themselves. A late run is logged (and listed in the report), never alerted.
A failed run is not fetched again. An area with no saved place is not fetched yet:
nothing would use it until the map layers (ticket #65).
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import logging
import shutil
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import astroseeing
from astroseeing.forecast.grid import map_grid
from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.places import PlaceHeightMissing, require_looked_up_heights
from astroseeing.forecast.publish.place_file import build_place_file
from astroseeing.forecast.publish.sets import publish
from astroseeing.forecast.schemas import validate
from astroseeing.forecast.settings import ForecastSettings, Place
from astroseeing.forecast.sources.gfs import GfsAdapter
from astroseeing.forecast.sources.icon_eu import IconEuAdapter
from astroseeing.forecast.sources.ifs import IfsAdapter
from astroseeing.forecast.sources.interface import RunRef, SourceAdapter
from astroseeing.forecast.sources.meps import MepsAdapter
from astroseeing.forecast.store import PlaceStore, utc_text
from astroseeing.forecast.tick.hosts import pick_host
from astroseeing.forecast.tick.runs import RunWork
from astroseeing.forecast.tonight.sun import sun_track
from astroseeing.forecast.verify import ForecastRecords
from astroseeing.forecast.verify.rules import late_run
from astroseeing.manifest import Manifest
from astroseeing.paths import Paths
from astroseeing.provenance import git_state

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForecastPaths:
    """Where the forecast keeps its files (D51 items 5 and 10, D52)."""

    root: Path  # /staging/forecast
    lock: Path  # on the root disk, beside the manifest

    @classmethod
    def from_paths(cls, paths: Paths) -> ForecastPaths:
        return cls(root=paths.staging / "forecast", lock=paths.state_dir / "forecast-tick.lock")

    def raw_dir(self, run: RunRef, area: str) -> Path:
        """``/staging/forecast/<model>/<run>/<area>/`` (D51 item 5's folder per run)."""
        return self.root / run.model / run.label / area

    @property
    def products(self) -> Path:
        return self.root / "products"

    @property
    def places(self) -> Path:
        return self.products / "places"

    @property
    def sets(self) -> Path:
        return self.products / "sets"

    @property
    def latest(self) -> Path:
        return self.products / "latest.json"


@dataclass(frozen=True)
class BuildInfo:
    """What built the products: the git commit and software versions (provenance)."""

    commit: str
    software: Mapping[str, str]

    @classmethod
    def current(cls) -> BuildInfo:
        state = git_state()
        if not state["commit"] or state["dirty"]:
            raise RuntimeError(
                f"the forecast publishes only from a clean git checkout, got {state}"
            )
        return cls(state["commit"], {"astroseeing": astroseeing.__version__})


@dataclass
class TickReport:
    now: dt.datetime
    skipped: str | None = None
    runs: list[dict] = field(default_factory=list)  # each run whose state changed
    late: list[dict] = field(default_factory=list)  # runs late (logged, never alerted)
    set_id: str | None = None
    published: bool = False

    def as_dict(self) -> dict:
        return {
            "now": utc_text(self.now),
            "skipped": self.skipped,
            "runs": self.runs,
            "late": self.late,
            "set_id": self.set_id,
            "published": self.published,
        }


class TickLocked(RuntimeError):
    pass


@contextmanager
def tick_lock(path: Path) -> Iterator[None]:
    """Hold the tick's lock (``flock`` on a file on the root disk) or raise TickLocked."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise TickLocked(str(path)) from e
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def default_adapters(settings: ForecastSettings, http: HttpClient) -> dict[str, SourceAdapter]:
    """The adapters that exist so far (ticket #51: GFS; ticket #55: ICON-EU; ticket #56:
    IFS; ticket #57: MEPS)."""
    return {
        "gfs": GfsAdapter(settings.models["gfs"], http, settings.areas),
        "icon_eu": IconEuAdapter(settings.models["icon_eu"], http, settings.areas),
        "ifs": IfsAdapter(settings.models["ifs"], http, settings.areas),
        "meps": MepsAdapter(settings.models["meps"], http, settings.areas),
    }


def tick(
    now: dt.datetime,
    settings: ForecastSettings,
    adapters: Mapping[str, SourceAdapter],
    manifest: Manifest,
    paths: ForecastPaths,
    ephemeris,
    build: BuildInfo,
    free_bytes: Callable[[Path], float] | None = None,
) -> TickReport:
    """One tick at ``now`` (UTC). ``ephemeris`` is ``solar.sun.load_ephemeris()``'s
    (eph, ts); ``free_bytes`` measures free space on /staging (default: the real disk)."""
    report = TickReport(now)
    try:
        require_looked_up_heights(settings)  # ticket #54: never at a guessed height
    except PlaceHeightMissing as e:
        log.error("tick refused: %s", e)
        report.skipped = str(e)
        return report
    try:
        with tick_lock(paths.lock):
            _tick(
                now,
                settings,
                adapters,
                manifest,
                paths,
                ephemeris,
                build,
                free_bytes or _free_bytes,
                report,
            )
    except TickLocked:
        report.skipped = "another tick holds the lock"
    return report


def _free_bytes(path: Path) -> float:
    p = Path(path)
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free


def _tick(now, settings, adapters, manifest, paths, ephemeris, build, free_bytes, report) -> None:
    records = ForecastRecords(manifest)
    store = PlaceStore(paths.places)
    places = settings.places

    # 1-3: each model's host and newest run; open runs fetched, verified and stored
    work = RunWork(
        now, settings, adapters, records, store, paths.raw_dir, paths.root, build, free_bytes
    )
    picks = {}
    for area in settings.areas.values():
        area_places = [p for p in places.values() if p.area == area.id]
        if not area_places:
            continue
        for model_id in area.models:
            adapter = adapters.get(model_id)
            if adapter is None:
                continue  # no adapter for this model in this tick
            model = settings.models[model_id]
            if model_id not in picks:  # one host check per model and tick
                picks[model_id] = pick_host(model, adapter, records, settings.run_rules, now)
            report.runs += work.work_model(model, area, area_places, picks[model_id])
            report.late += _late(model, area.id, records, settings, now)

    # 4-5: the place files and latest.json, published when anything changed
    files = {}
    for place in places.values():
        area = settings.areas[place.area]
        models = [settings.models[m] for m in area.models]
        sun = sun_track(place.lat, place.lon, now, *ephemeris)
        hours = sun.hours
        doc = build_place_file(
            place,
            models,
            store.hours_for(place.id, models, hours),
            sun.altitude_deg,
            settings.config_hash,
            build.commit,
        )
        validate(doc, "f1-place/1")
        files[f"place-{place.id}.json"] = _json_bytes(doc)
    latest = _latest_doc(now, settings, places, records, build)
    validate(
        {
            **latest,
            "set_id": "00000000T000000Z-00000000",
            "set_path": "sets/00000000T000000Z-00000000/",
            "written_at": utc_text(now),
        },
        "f1-latest/1",
    )
    result = publish(paths.products, files, latest, now)
    report.set_id, report.published = result.set_id, result.new


def _late(model, area_id: str, records: ForecastRecords, settings, now) -> list[dict]:
    """The model's newest expected run, if it is late and not yet seen (logged only)."""
    run = late_run(model, settings.run_rules, now)
    if run is None or records.find(model.id, area_id, run.run_time) is not None:
        return []
    late_h = (now - run.run_time) / dt.timedelta(hours=1)
    log.warning("%s %s %s is late: not out %.1f h after its run time (expected after "
                "%.1f h)", model.id, area_id, run.label, late_h, model.publish_delay_h)  # fmt: skip
    return [{"model": model.id, "area": area_id, "run_time": utc_text(run.run_time)}]


def _latest_doc(
    now,
    settings: ForecastSettings,
    places: Mapping[str, Place],
    records: ForecastRecords,
    build: BuildInfo,
) -> dict:
    default = settings.places[settings.default_place]
    area = settings.areas[default.area]
    grid = map_grid(area, settings.models[area.map_grid_model])
    runs = {}
    for model_id in area.models:
        r = records.latest(model_id, area.id)
        if r is not None:
            age_h = (now - r.run_time) / dt.timedelta(hours=1)
            runs[model_id] = {
                "run_id": r.id,
                "run_time": utc_text(r.run_time),
                "state": r.state,
                "stale": age_h > settings.run_rules.stale_after_h,
            }
    return {
        "schema": "f1-latest/1",
        "provenance": {
            "commit": build.commit,
            "config_hash": settings.config_hash,
            "software": dict(build.software),
        },
        "default_place": default.id,
        "places": [
            {"id": p.id, "name": p.name, "file": f"place-{p.id}.json"} for p in places.values()
        ],
        "grid": {
            "crs": "EPSG:4326",
            "lat_north": grid.lat_north,
            "lon_west": grid.lon_west,
            "dlat": grid.dlat,
            "dlon": grid.dlon,
            "nlat": grid.nlat,
            "nlon": grid.nlon,
            "order": "row-major, north to south, west to east",
        },
        "layers": {},
        "runs": runs,
        "sunset_maps": [],
    }


def _json_bytes(doc: dict) -> bytes:
    return (json.dumps(doc, indent=1, allow_nan=False) + "\n").encode()


__all__ = [
    "BuildInfo",
    "ForecastPaths",
    "TickLocked",
    "TickReport",
    "default_adapters",
    "tick",
    "tick_lock",
]
