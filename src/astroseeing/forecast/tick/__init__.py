"""The tick (F1 spec Module 8): ``astro forecast tick``, every 15 min from
``astro-forecast.timer``; idempotent, manifest-driven, every dependency injected (D51).

Ticket #51 builds steps 1-5 of the spec's order:

1. ask each adapter for its newest published run;
2. fetch, verify and compute what's new (one run at a time, in this process: within
   D51 item 4's limit of 2 worker processes, D72);
3. store each saved place's values (SSD part of Module 6);
4. build each saved place's file (the verdict comes with ticket #63);
5. publish a product set, if anything changed.

A run is fetched once. Its manifest row moves ``seen`` → ``fetching`` → ``fetched`` →
``verified`` → ``processed`` (or ``partial`` when some steps are missing, ``failed`` on
a format mismatch or failed verification). Raw files are deleted only after the run's
stored values have been read back and checked; a failed run keeps them (D51 item 5).
Retries, late and abandoned runs and the fallback host are ticket #58 (F1-9); a failed
run is not fetched again here. An area with no saved place is not fetched yet: nothing
would use it until the map layers (ticket #65).
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
from astroseeing.forecast.column import column_products
from astroseeing.forecast.grid import map_grid, nearest_point
from astroseeing.forecast.http import HttpClient, HttpError
from astroseeing.forecast.places import PlaceHeightMissing, require_looked_up_heights
from astroseeing.forecast.publish.place_file import build_place_file
from astroseeing.forecast.publish.sets import publish
from astroseeing.forecast.schemas import validate
from astroseeing.forecast.settings import Area, ForecastSettings, Place
from astroseeing.forecast.sources.gfs import GfsAdapter
from astroseeing.forecast.sources.icon_eu import IconEuAdapter
from astroseeing.forecast.sources.interface import (
    FormatMismatch,
    RunFields,
    RunRef,
    SourceAdapter,
)
from astroseeing.forecast.store import PlaceStore, run_document, utc_text
from astroseeing.forecast.tonight.sun import sun_track
from astroseeing.forecast.verify import ForecastRecords, verify_run
from astroseeing.manifest import Manifest
from astroseeing.paths import Paths
from astroseeing.provenance import git_state

log = logging.getLogger(__name__)

GB = 1e9  # bytes in the settings' gigabytes (alerts.staging_min_free_gb)


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
    runs: list[dict] = field(default_factory=list)  # each new run: model, area, state, error
    set_id: str | None = None
    published: bool = False

    def as_dict(self) -> dict:
        return {
            "now": utc_text(self.now),
            "skipped": self.skipped,
            "runs": self.runs,
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
    """The adapters that exist so far (ticket #51: GFS; ticket #55: ICON-EU)."""
    return {
        "gfs": GfsAdapter(settings.models["gfs"], http, settings.areas),
        "icon_eu": IconEuAdapter(settings.models["icon_eu"], http, settings.areas),
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

    # 1-3: newest runs, fetched, verified, computed and stored
    newest: dict[str, RunRef | None] = {}
    for area in settings.areas.values():
        area_places = [p for p in places.values() if p.area == area.id]
        if not area_places:
            continue
        for model_id in area.models:
            adapter = adapters.get(model_id)
            if adapter is None:
                continue  # no adapter yet (MEPS, IFS: tickets #56-#57)
            if model_id not in newest:
                try:
                    newest[model_id] = adapter.latest_published(now)
                except HttpError as e:  # host down: nothing new this tick (ticket #58)
                    log.warning("%s: no answer on the newest run: %s", model_id, e)
                    newest[model_id] = None
            run = newest[model_id]
            if run is None or not _is_new(records, run, area.id):
                continue
            free = free_bytes(paths.root)
            min_free = settings.alerts.staging_min_free_gb * GB
            if free < min_free:
                log.error(
                    "skipping %s %s: /staging has %.1f GB free, needs %.0f GB",
                    model_id,
                    run.label,
                    free / GB,
                    min_free / GB,
                )
                continue
            report.runs.append(
                _process_run(
                    now, settings, adapter, run, area, area_places, records, store, paths, build
                )
            )

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


def _is_new(records: ForecastRecords, run: RunRef, area: str) -> bool:
    if records.find(run.model, area, run.run_time) is not None:
        return False  # already handled, in any state (retries: ticket #58)
    have = records.latest(run.model, area)
    return have is None or have.run_time < run.run_time


def _process_run(
    now,
    settings,
    adapter,
    run,
    area: Area,
    places: list[Place],
    records: ForecastRecords,
    store: PlaceStore,
    paths: ForecastPaths,
    build: BuildInfo,
) -> dict:
    model = settings.models[run.model]
    steps = model.steps_h
    run_id = records.seen(run.model, area.id, run.run_time, steps, at=now)
    out = {"model": run.model, "area": area.id, "run_time": utc_text(run.run_time)}

    def fail(state_from: tuple[str, ...], error: str) -> dict:
        records.transition(run_id, state_from, "failed", at=now, last_error=error)
        log.error("%s %s %s failed: %s", run.model, area.id, run.label, error)
        return {**out, "state": "failed", "error": error}

    records.transition(run_id, ("seen",), "fetching", at=now, increment_attempts=True)
    dest = paths.raw_dir(run, area.id)
    t0 = time.monotonic()
    try:
        fetched = adapter.fetch(run, area, steps, dest)
    except Exception as e:  # recorded and logged, never left in "fetching"
        return fail(("fetching",), f"fetch error: {e!r}")
    for f in fetched.files:
        records.add_file(run_id, f, at=now)
    records.transition(
        run_id,
        ("fetching",),
        "fetched",
        at=now,
        bytes=fetched.bytes,
        download_seconds=time.monotonic() - t0,
    )
    t1 = time.monotonic()
    try:
        fields = adapter.read(fetched)
    except FormatMismatch as e:
        return fail(("fetched",), str(e))
    except Exception as e:  # an unreadable file (eccodes error) fails the run loudly too
        return fail(("fetched",), f"read error: {e!r}")
    report = verify_run(fields, model, steps, fetched.missing_steps)
    if not report.ok or not report.verified_steps:
        why = "; ".join(report.problems) or "no step verified"
        return fail(("fetched",), f"verify failed: {why}")
    records.transition(run_id, ("fetched",), "verified", at=now, steps_verified=report.steps)
    records.mark_files_verified(run_id)

    derived = 0
    for place in places:
        stored = _store_place(
            place, fields, report, fetched.missing_steps, run_id, adapter, settings, store, build
        )
        if stored is None:
            return fail(("verified",), f"stored values for {place.id} did not read back")
        derived += stored
    state = "processed" if len(report.verified_steps) == len(steps) else "partial"
    records.transition(
        run_id,
        ("verified",),
        state,
        at=now,
        derived_bytes=derived,
        processing_seconds=time.monotonic() - t1,
    )
    _delete_raw(fetched.files, dest)
    records.mark_raw_deleted(run_id, at=now)
    log.info(
        "%s %s %s %s: %d of %d steps",
        run.model,
        area.id,
        run.label,
        state,
        len(report.verified_steps),
        len(steps),
    )
    return {**out, "state": state, "error": None}


def _store_place(
    place, fields: RunFields, report, missing, run_id, adapter, settings, store, build
) -> int | None:
    """Compute and store one place's values; return the bytes written, or None if the
    file does not read back as written."""
    i, j = nearest_point(fields.lat, fields.lon, place.lat, place.lon)
    at = _at_point(fields, i, j)
    products = column_products(at, observer_height_m=place.height.metres)
    provenance = {
        "commit": build.commit,
        "config_hash": settings.config_hash,
        "manifest_run_id": run_id,
        "software": dict(build.software),
    }
    doc = run_document(
        place,
        at,
        (0, 0),
        products,
        report.verified_steps,
        missing,
        run_id,
        adapter.credit,
        settings.cloud_classes,
        provenance,
    )
    stored = store.put_run(doc)
    if store.read_run(stored.path) != json.loads(json.dumps(doc)):
        return None
    return stored.bytes


def _at_point(f: RunFields, i: int, j: int) -> RunFields:
    """The run's fields at one grid point, as a 1 × 1 grid."""

    def cut(a):
        return None if a is None else a[:, i : i + 1, j : j + 1]

    return RunFields(
        run=f.run,
        model=f.model,
        lat=f.lat[i : i + 1, j : j + 1],
        lon=f.lon[i : i + 1, j : j + 1],
        valid_times=f.valid_times,
        pressure_hpa=f.pressure_hpa,
        geopotential_height_m=cut(f.geopotential_height_m),
        temperature_k=cut(f.temperature_k),
        u_ms=cut(f.u_ms),
        v_ms=cut(f.v_ms),
        level_cloud_pct=cut(f.level_cloud_pct),
        total_cloud_pct=cut(f.total_cloud_pct),
        low_cloud_pct=cut(f.low_cloud_pct),
        mid_cloud_pct=cut(f.mid_cloud_pct),
        high_cloud_pct=cut(f.high_cloud_pct),
        surface_pressure_hpa=cut(f.surface_pressure_hpa),
        model_ground_m=f.model_ground_m[i : i + 1, j : j + 1],
        fog={k: cut(v) for k, v in f.fog.items()},
        run_id=f.run_id,
    )


def _delete_raw(files, dest: Path) -> None:
    for f in files:
        Path(f.path).unlink(missing_ok=True)
    for d in (dest, dest.parent, dest.parent.parent):
        try:
            d.rmdir()  # only if empty
        except OSError:
            break


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
