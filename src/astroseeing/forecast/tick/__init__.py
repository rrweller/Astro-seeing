"""The tick (F1 spec Module 8): ``astro forecast tick``, every 15 min from
``astro-forecast.timer``; idempotent, manifest-driven, every dependency injected (D51).

Ticket #51 builds steps 1-5 of the spec's order, ticket #59 step 6:

1. ask each adapter for its newest published run;
2. fetch, verify and compute what's new (one run at a time, in this process: within
   D51 item 4's limit of 2 worker processes, D72);
3. store each saved place's values (SSD part of Module 6);
4. build each saved place's file, with ``tonight()``'s verdict and the Moon (ticket #63),
   and the map layers of the default saved place's area: ``tonight()`` for every map
   cell (ticket #65, ``publish.layers``), timed in the report and the log;
5. publish a product set, if anything changed;
6. finalise days: each saved place's UTC days whose runs are all final go from the SSD
   to one Zarr store each on ``/data``, written once (``store.days``). Every call to
   ``/data`` has a timeout, so a hung NAS is logged and tried again next tick; and it
   comes after publishing, so it never holds the page back.

A run's manifest row moves ``seen`` → ``fetching`` → ``fetched`` → ``verified`` →
``processed`` (or ``partial`` when some steps are missing, ``failed`` on a format
mismatch or failed verification, ``abandoned`` when given up). The run rules of ticket
#58 (D51 items 5, 7 and 14; D79) live beside the tick: ``tick.hosts`` picks each
model's host (the fallback after the main host has failed for 1 h), ``tick.runs`` works
each open run over as many ticks as it needs (each step tried at most 5 times, at least
1 min apart; abandoned runs; raw files deleted once final), and ``verify.rules`` holds
the rules themselves. A late run is logged (and listed in the report), never alerted.
A failed run is not fetched again. An area with no saved place is not fetched: the map
covers the default saved place's area only (``latest.json`` has one grid). A processed
run of a global model in that area also stores its latest area grid
(``store.areas``) for the map.

Alerts (ticket #61, D82; ``forecast.alerts``): the tick checks ``/staging``'s free space
before any fetch, and after publishing fetches the served ``latest.json`` (spec step 9)
and checks each worked model for a stale or failed run; each condition alerts once when
it starts and once when it clears. A tick that gets this far writes its heartbeat
last, which the download watcher checks for "no tick for 1 h".
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import logging
import shutil
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import astroseeing
from astroseeing.forecast.alerts import Notifier, TickAlerts
from astroseeing.forecast.grid import MapGrid, map_grid
from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.places import PlaceHeightMissing, require_looked_up_heights
from astroseeing.forecast.publish.layers import MapLayers, build_layers
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
from astroseeing.forecast.store.areas import AreaStore
from astroseeing.forecast.store.days import DayStores, NasGuard, finalise_days
from astroseeing.forecast.tick.hosts import pick_host
from astroseeing.forecast.tick.runs import RunWork
from astroseeing.forecast.tonight.sun import cell_suns, sun_track
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
    data: Path  # /data/astro/forecast: only ever grows (D51 item 10)

    @classmethod
    def from_paths(cls, paths: Paths) -> ForecastPaths:
        return cls(
            root=paths.staging / "forecast",
            lock=paths.state_dir / "forecast-tick.lock",
            data=paths.data_root / "forecast",
        )

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
    def areas(self) -> Path:
        """``products/areas``: the latest area grids the map layers read (ticket #65)."""
        return self.products / "areas"

    @property
    def site(self) -> Path:
        """``/staging/forecast/site``: the deployed page (``astro web deploy``, D52 item 5)."""
        return self.root / "site"

    @property
    def place_days(self) -> Path:
        """``/data/astro/forecast/places``: the per-place daily stores (D51 item 12)."""
        return self.data / "places"

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
    days: list[dict] = field(default_factory=list)  # per-place days finalised or tried
    map_seconds: float | None = None  # time to build the map layers (ticket #65)
    map_bytes: int | None = None  # the map layers' size, all files

    def as_dict(self) -> dict:
        return {
            "now": utc_text(self.now),
            "skipped": self.skipped,
            "runs": self.runs,
            "late": self.late,
            "set_id": self.set_id,
            "published": self.published,
            "days": self.days,
            "map_seconds": self.map_seconds,
            "map_bytes": self.map_bytes,
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
    http: HttpClient | None = None,
    notify: Notifier | None = None,
    day_stores: DayStores | None = None,
) -> TickReport:
    """One tick at ``now`` (UTC). ``ephemeris`` is ``solar.sun.load_ephemeris()``'s
    (eph, ts); ``free_bytes`` measures free space on /staging (default: the real disk);
    ``http`` fetches the served ``latest.json`` (``None``: the served-page check is
    skipped); ``notify`` sends the alerts (``None``: they are logged only);
    ``day_stores`` are the per-place daily stores (default: under ``paths.place_days``)."""
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
                http,
                TickAlerts(manifest, settings, notify, now),
                day_stores or DayStores(paths.place_days),
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


def _tick(
    now,
    settings,
    adapters,
    manifest,
    paths,
    ephemeris,
    build,
    free_bytes,
    http,
    alerts,
    day_stores,
    report,
) -> None:
    records = ForecastRecords(manifest)
    guard = NasGuard(settings.place_stores.nas_timeout_s)
    store = PlaceStore(paths.places, days=day_stores, guard=guard)
    areas = AreaStore(paths.areas)
    places = settings.places
    map_area = settings.areas[places[settings.default_place].area]
    alerts.disk(free_bytes(paths.root))  # the runs below skip fetching while it is low

    # 1-3: each model's host and newest run; open runs fetched, verified and stored
    work = RunWork(
        now, settings, adapters, records, store, paths.raw_dir, paths.root, build, free_bytes,
        areas, map_area.id,
    )  # fmt: skip
    picks, worked = {}, []
    for area in settings.areas.values():
        area_places = [p for p in places.values() if p.area == area.id]
        if not area_places:
            continue
        for model_id in area.models:
            adapter = adapters.get(model_id)
            if adapter is None:
                continue  # no adapter for this model in this tick
            model = settings.models[model_id]
            worked.append((model, area.id))
            if model_id not in picks:  # one host check per model and tick
                picks[model_id] = pick_host(model, adapter, records, settings.run_rules, now)
            report.runs += work.work_model(model, area, area_places, picks[model_id])
            report.late += _late(model, area.id, records, settings, now)

    # 4-5: the place files, the map layers and latest.json, published when anything changed
    files, suns = {}, {}
    for place in places.values():
        area = settings.areas[place.area]
        models = [settings.models[m] for m in area.models]
        sun = suns[place.id] = sun_track(place.lat, place.lon, now, *ephemeris)
        hours = store.hours_for(place.id, models, sun.hours)
        doc = build_place_file(
            place, models, hours, sun, now,
            settings=settings, ephemeris=ephemeris, commit=build.commit,
        )  # fmt: skip
        validate(doc, "f1-place/1")
        files[f"place-{place.id}.json"] = _json_bytes(doc)
    t0 = time.monotonic()
    grid = map_grid(map_area, settings.models[map_area.map_grid_model])
    layers = _map_layers(grid, map_area, areas, suns[settings.default_place].hours, now,
                         settings, ephemeris)  # fmt: skip
    report.map_seconds = time.monotonic() - t0
    report.map_bytes = sum(len(b) for b in layers.files.values())
    log.info("map layers: %d × %d cells, %d files, %.0f kB, built in %.1f s", grid.nlat,
             grid.nlon, len(layers.files), report.map_bytes / 1e3, report.map_seconds)  # fmt: skip
    files.update(layers.files)
    latest = _latest_doc(now, settings, places, records, build, grid, layers)
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

    # 6: final days to /data (after publishing: a hung NAS never holds the page back)
    try:
        report.days = finalise_days(now, settings, records, store, build)
    except Exception as e:  # logged and reported; the next tick tries again
        log.exception("finalising days failed")
        report.days = [{"outcome": "error", "error": repr(e)}]

    if http is not None:  # 9: is the page served what was just written? (D52 item 10)
        alerts.page(http, paths.latest)
    alerts.models(worked)
    alerts.beat(worked)  # last: only a finished tick counts for the watcher


def _map_layers(
    grid: MapGrid, area, areas: AreaStore, slider_hours, now, settings, ephemeris
) -> MapLayers:
    """The map layers of ``area``: every cell's Sun and each model's newest stored area
    grid, through ``tonight()`` per cell."""
    suns = cell_suns(grid.lats, grid.lons, now, *ephemeris)
    models = [settings.models[m] for m in area.models]
    runs = {m.id: areas.newest(area.id, m.id) for m in models if not m.regional}
    return build_layers(
        grid,
        models,
        {k: v for k, v in runs.items() if v is not None},
        suns,
        slider_hours,
        now,
        cloud_classes=settings.cloud_classes,
        stale_after_h=settings.run_rules.stale_after_h,
    )


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
    grid: MapGrid,
    layers: MapLayers,
) -> dict:
    default = settings.places[settings.default_place]
    area = settings.areas[default.area]
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
        "layers": dict(layers.entries),
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
