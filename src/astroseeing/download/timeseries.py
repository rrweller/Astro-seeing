"""Point time series from the CDS product ``reanalysis-era5-single-levels-timeseries``.

Built for one job (D57 item 4): ERA5 surface pressure (``sp``) at the 8 Haslebacher et
al. sites' nearest grid points, 1979–2020, so their lowest integration level (the
pressure level closest to the site's time-mean ERA5 surface pressure) can be checked
against their Table 4. Decisions: D62.

* **Own slot (D29).** The time-series products run in their own CDS slot, so these
  jobs live in their own manifest tables (``ts_requests``, ``ts_events``,
  ``ts_stores``): the pressure-level downloader, its gate (D39), ``astro status`` and
  the notify watcher never read them, and :meth:`DatastoresBackend.active_jobs` leaves
  time-series jobs out of the gate's count. This fetcher keeps to one time-series job
  at a time, submits nothing while the account's CDS pause is on, and stops
  submitting for the rest of the run after any rejection.
* **Client pattern (D2).** Submit, store the CDS request id at once, poll by id,
  download; a restart re-attaches to a job still at the CDS.
* **Chunks.** Each site's period is split into runs of ``chunk_years`` calendar years
  (the first and last may be partial years). Whether one 42-year request works is
  untested, so the size is a setting; ``--replan`` changes it for sites not yet stored.
* **Verify, then store.** Every returned file is checked (variable, point, every hour
  present once, no NaN; counts logged). When all of a site's chunks pass, they are
  joined, checked again as a whole, and written atomically as one small Zarr store per
  site and variable. An existing store is never overwritten.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import json
import logging
import math
import os
import tempfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from astroseeing.config import load_config
from astroseeing.download.cds import DONE, FAILED, GONE, PENDING, RemoteInfo
from astroseeing.download.downloader import (
    MAX_LOST_RESUBMITS,
    REJECTION_WINDOW,
    REJECTIONS_TO_PAUSE,
    safe_name,
    sha256_file,
)
from astroseeing.manifest import LOST_PREFIX, Manifest, StateError, utcnow
from astroseeing.provenance import canonical_json, era5_attribution, provenance

log = logging.getLogger(__name__)


def nearest_grid_point(lon: float, lat: float, grid_deg: float = 0.25) -> tuple[float, float]:
    """The nearest point of the ERA5 grid; refuses an exact tie rather than pick one."""

    def snap(x: float) -> float:
        n = x / grid_deg
        if abs(abs(n - math.floor(n)) - 0.5) < 1e-9:
            raise ValueError(f"{x} is a tie between two grid points; choose one explicitly")
        return round(n) * grid_deg + 0.0  # + 0.0 turns -0.0 into 0.0

    return snap(lon), snap(lat)


@dataclass(frozen=True)
class PointSite:
    group: str
    site: str
    lon: float  # the ERA5 grid point requested
    lat: float
    site_lon: float  # the site's own coordinates (configs/sites.yaml)
    site_lat: float


def site_points(group: str) -> list[PointSite]:
    """Sites of one ``configs/sites.yaml`` group, at their ``era5_point`` (else the nearest)."""
    out = []
    for name, s in load_config("sites")[group].items():
        lon, lat = s.get("era5_point") or nearest_grid_point(s["lon"], s["lat"])
        out.append(PointSite(group, name, float(lon), float(lat), s["lon"], s["lat"]))
    return out


# --- verification --------------------------------------------------------------------

#: How far the returned point may be from the requested grid point, in degrees.
POINT_TOLERANCE_DEG = 1e-3
TIME_NAMES = ("valid_time", "time")
LAT_NAMES = ("latitude", "lat")
LON_NAMES = ("longitude", "lon")


@dataclass(frozen=True)
class PointExpectation:
    """What one returned file must hold: one variable at one point, every hour once."""

    short_name: str
    units: str
    lon: float
    lat: float
    start: dt.date  # first day, from 00 UTC
    end: dt.date  # last day, through 23 UTC

    def hours(self) -> np.ndarray:
        """Every expected hour, as int64 seconds since 1970-01-01 UTC."""
        t0 = np.datetime64(self.start.isoformat(), "s")
        t1 = np.datetime64((self.end + dt.timedelta(days=1)).isoformat(), "s")
        return np.arange(t0, t1, np.timedelta64(3600, "s")).astype(np.int64)


@dataclass
class PointCheck:
    ok: bool
    problems: list[str]
    counts: dict[str, int] = field(default_factory=dict)
    times: np.ndarray = field(default_factory=lambda: np.empty(0, np.int64))  # s since 1970
    values: np.ndarray = field(default_factory=lambda: np.empty(0, np.float32))

    def report(self) -> dict:
        return {"ok": self.ok, "problems": self.problems, "counts": self.counts,
                "hours": int(self.times.size)}  # fmt: skip


def _open_point_dataset(path: Path):
    """The NetCDF dataset in ``path``: a zip holding exactly one NetCDF file, or a bare one."""
    import xarray as xr

    path = Path(path)
    if not zipfile.is_zipfile(path):
        with xr.open_dataset(path, engine="netcdf4") as ds:
            return ds.load()
    with zipfile.ZipFile(path) as z:
        members = [n for n in z.namelist() if not n.endswith("/")]
        if len(members) != 1:
            raise ValueError(f"zip holds {len(members)} files, expected one NetCDF: {members}")
        fd, tmp = tempfile.mkstemp(suffix=".nc", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as out, z.open(members[0]) as src:
                while chunk := src.read(8 << 20):
                    out.write(chunk)
            with xr.open_dataset(tmp, engine="netcdf4") as ds:
                return ds.load()
        finally:
            os.unlink(tmp)


def _coord(ds, names: tuple[str, ...]):
    for n in names:
        if n in ds.variables:
            return ds[n]
    return None


def verify_point_file(path: Path, want: PointExpectation) -> PointCheck:
    """Check a returned file: variable, units, point, every hour exactly once, no NaN.

    Nothing is fixed or dropped: problems are listed and counted (AGENTS.md "No silent
    fixes"), and a file with any problem fails.
    """
    try:
        ds = _open_point_dataset(path)
    except Exception as e:
        return PointCheck(False, [f"cannot read {Path(path).name} as NetCDF: {e}"])
    problems: list[str] = []
    if want.short_name not in ds.data_vars:
        problems.append(f"no variable {want.short_name!r} (found {sorted(ds.data_vars)})")
        return PointCheck(False, problems)
    var = ds[want.short_name]
    units = var.attrs.get("units")
    if units is None:
        log.warning("%s: %s has no units attribute; values not checked for units",
                    Path(path).name, want.short_name)  # fmt: skip
    elif units != want.units:
        problems.append(f"{want.short_name} units {units!r}, expected {want.units!r}")

    lat, lon = _coord(ds, LAT_NAMES), _coord(ds, LON_NAMES)
    if lat is None or lon is None or lat.size != 1 or lon.size != 1:
        problems.append("expected one point (scalar latitude and longitude)")
    else:
        got_lat, got_lon = float(lat.values.ravel()[0]), float(lon.values.ravel()[0])
        dlon = (got_lon - want.lon + 180.0) % 360.0 - 180.0  # 0..360 or -180..180
        if abs(got_lat - want.lat) > POINT_TOLERANCE_DEG or abs(dlon) > POINT_TOLERANCE_DEG:
            problems.append(f"point ({got_lon}, {got_lat}) is not the requested grid point "
                            f"({want.lon}, {want.lat})")  # fmt: skip

    tcoord = _coord(ds, TIME_NAMES)
    if tcoord is None or var.squeeze().ndim != 1 or tcoord.name not in var.dims:
        problems.append(f"expected {want.short_name} along one time axis, got dims {var.dims}")
        return PointCheck(False, problems)
    times = tcoord.values.astype("datetime64[s]").astype(np.int64)
    values = var.squeeze().values.astype(np.float32)
    out_of_order = int((np.diff(times) < 0).sum())
    order = np.argsort(times, kind="stable")
    times, values = times[order], values[order]

    expected = want.hours()
    unique = np.unique(times)
    counts = {
        "missing_hours": int(np.setdiff1d(expected, unique).size),
        "extra_hours": int(np.setdiff1d(unique, expected).size),
        "duplicate_hours": int(times.size - unique.size),
        "nan": int(np.isnan(values).sum()),
        "out_of_order": out_of_order,
    }
    if counts["missing_hours"]:
        problems.append(f"{counts['missing_hours']} of {expected.size} hours missing")
    if counts["extra_hours"]:
        problems.append(f"{counts['extra_hours']} hours outside {want.start}..{want.end}")
    if counts["duplicate_hours"]:
        problems.append(f"{counts['duplicate_hours']} duplicate hours")
    if counts["nan"]:
        problems.append(f"{counts['nan']} NaN values in {want.short_name}")
    if counts["out_of_order"]:
        problems.append(f"time axis out of order at {counts['out_of_order']} places")
    return PointCheck(not problems, problems, counts, times, values)


# --- settings and chunks ---------------------------------------------------------------


@dataclass(frozen=True)
class PointFetchConfig:
    """One product, variable and period to fetch at a group's points (configs/timeseries.yaml)."""

    dataset: str
    variable: str  # CDS name
    short_name: str  # name in the returned NetCDF
    units: str
    data_format: str
    sites: str  # group in configs/sites.yaml
    start: dt.date
    end: dt.date
    chunk_years: int
    store_dir: str  # under ASTRO_DATA_ROOT

    @classmethod
    def from_config(cls, name: str = "surface_pressure_points") -> PointFetchConfig:
        c = dict(load_config("timeseries")[name])
        for k in ("start", "end"):
            if isinstance(c[k], str):
                c[k] = dt.date.fromisoformat(c[k])
        return cls(**c)


def plan_chunks(start: dt.date, end: dt.date, years: int) -> list[tuple[dt.date, dt.date]]:
    """Split ``start..end`` into runs of ``years`` calendar years (the ends may be partial)."""
    if years < 1:
        raise ValueError(f"chunk_years must be at least 1, got {years}")
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    out = []
    s = start
    while s <= end:
        e = min(dt.date(s.year + years - 1, 12, 31), end)
        out.append((s, e))
        s = e + dt.timedelta(days=1)
    return out


def cds_request(cfg: PointFetchConfig, point: PointSite, start: dt.date, end: dt.date) -> dict:
    """The CDS request for one chunk (keys as in ECMWF's earthkit tutorial; D62)."""
    return {
        "variable": [cfg.variable],
        "location": {"longitude": point.lon, "latitude": point.lat},
        "date": [f"{start.isoformat()}/{end.isoformat()}"],
        "data_format": cfg.data_format,
    }


def chunk_key(point: PointSite, short_name: str, start: dt.date, end: dt.date) -> str:
    return f"{point.group}/{point.site}/{short_name}/{start:%Y%m%d}-{end:%Y%m%d}"


# --- the manifest records (tables ts_requests, ts_events, ts_stores) --------------------

#: planned → submitted → verified → stored; any → failed (retry → planned); planned,
#: verified or failed → cancelled (``--replan``).
TS_STATES = ("planned", "submitted", "verified", "stored", "failed", "cancelled")
#: States of the chunks that make up a site's next store.
ACTIVE = ("planned", "submitted", "verified", "failed")


@dataclass
class TsRequest:
    id: int
    key: str
    dataset: str
    site_group: str
    site: str
    variable: str
    short_name: str
    units: str
    lon: float
    lat: float
    start: dt.date
    end: dt.date
    request: dict[str, Any]
    request_hash: str
    state: str
    cds_request_id: str | None
    attempts: int
    last_error: str | None
    file_path: str | None
    file_sha256: str | None

    @classmethod
    def from_row(cls, r) -> TsRequest:
        return cls(
            id=r["id"], key=r["key"], dataset=r["dataset"], site_group=r["site_group"],
            site=r["site"], variable=r["variable"], short_name=r["short_name"],
            units=r["units"], lon=r["lon"], lat=r["lat"],
            start=dt.date.fromisoformat(r["start_date"]),
            end=dt.date.fromisoformat(r["end_date"]), request=json.loads(r["request_json"]),
            request_hash=r["request_hash"], state=r["state"],
            cds_request_id=r["cds_request_id"], attempts=r["attempts"],
            last_error=r["last_error"], file_path=r["file_path"],
            file_sha256=r["file_sha256"],
        )  # fmt: skip

    def expectation(self) -> PointExpectation:
        return PointExpectation(self.short_name, self.units, self.lon, self.lat, self.start,
                                self.end)  # fmt: skip


class TimeseriesRecords:
    """The time-series tables of the manifest: requests, their events, written stores."""

    def __init__(self, manifest: Manifest):
        self.m = manifest

    def add(
        self, key: str, dataset: str, point: PointSite, cfg: PointFetchConfig,
        start: dt.date, end: dt.date, request: dict,
    ) -> tuple[int, bool]:  # fmt: skip
        """Insert a chunk; idempotent. Returns (id, newly planned).

        The same key for a different request raises. A cancelled chunk planned again
        with the same request goes back to planned.
        """
        h = hashlib.sha256(canonical_json({"dataset": dataset, "request": request}).encode())
        h = h.hexdigest()
        now = utcnow()
        with self.m.tx() as c:
            row = c.execute(
                "SELECT id, request_hash, state FROM ts_requests WHERE key=?", (key,)
            ).fetchone()
            if row is not None:
                if row["request_hash"] != h:
                    raise ValueError(f"key {key} already used by a different request")
                if row["state"] != "cancelled":
                    return int(row["id"]), False
                self._transition(c, row["id"], ["cancelled"], "planned", "planned again", {})
                return int(row["id"]), True
            cur = c.execute(
                "INSERT INTO ts_requests (key, dataset, site_group, site, variable, short_name,"
                " units, lon, lat, start_date, end_date, request_json, request_hash, state,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (key, dataset, point.group, point.site, cfg.variable, cfg.short_name,
                 cfg.units, point.lon, point.lat, start.isoformat(), end.isoformat(),
                 canonical_json(request), h, "planned", now, now),
            )  # fmt: skip
            rid = int(cur.lastrowid)
            c.execute("INSERT INTO ts_events (ts_request_id, at, event) VALUES (?,?,?)",
                      (rid, now, "planned"))  # fmt: skip
            return rid, True

    def get(self, rid: int) -> TsRequest:
        r = self.m.conn.execute("SELECT * FROM ts_requests WHERE id=?", (rid,)).fetchone()
        if r is None:
            raise KeyError(rid)
        return TsRequest.from_row(r)

    def by_state(self, *states: str) -> list[TsRequest]:
        q = (f"SELECT * FROM ts_requests WHERE state IN ({','.join('?' * len(states))})"
             " ORDER BY id")  # fmt: skip
        return [TsRequest.from_row(r) for r in self.m.conn.execute(q, states)]

    def for_site(self, group: str, site: str, short_name: str, states=ACTIVE) -> list[TsRequest]:
        return [r for r in self.by_state(*states)
                if (r.site_group, r.site, r.short_name) == (group, site, short_name)]  # fmt: skip

    def counts(self) -> dict[str, int]:
        rows = self.m.conn.execute("SELECT state, COUNT(*) n FROM ts_requests GROUP BY state")
        return {r["state"]: r["n"] for r in rows}

    def transition(
        self, rid: int, from_states, to_state: str, detail: str | None = None,
        increment_attempts: bool = False, **fields: Any,
    ) -> None:  # fmt: skip
        with self.m.tx() as c:
            if increment_attempts:
                fields["attempts"] = (
                    c.execute("SELECT attempts FROM ts_requests WHERE id=?", (rid,)).fetchone()[0]
                    + 1
                )
            self._transition(c, rid, from_states, to_state, detail, fields)

    def fail(self, rid: int, from_states, error: str, **fields: Any) -> None:
        self.transition(rid, from_states, "failed", detail=error, increment_attempts=True,
                        last_error=error, **fields)  # fmt: skip

    @staticmethod
    def _transition(c, rid: int, from_states, to_state: str, detail, fields: dict) -> None:
        """Compare-and-set state change plus an event row; the caller holds the transaction."""
        if to_state not in TS_STATES:
            raise ValueError(to_state)
        from_states = tuple(from_states)
        now = utcnow()
        sets = "".join(f", {k}=?" for k in fields)
        cur = c.execute(
            f"UPDATE ts_requests SET state=?, updated_at=?{sets}"
            f" WHERE id=? AND state IN ({','.join('?' * len(from_states))})",
            (to_state, now, *fields.values(), rid, *from_states),
        )
        if cur.rowcount != 1:
            raise StateError(f"ts request {rid}: expected {from_states}")
        c.execute("INSERT INTO ts_events (ts_request_id, at, event, detail) VALUES (?,?,?,?)",
                  (rid, now, to_state, detail))  # fmt: skip

    def lost_count(self, rid: int) -> int:
        """How many times the CDS lost this chunk's job (D34; bounded as in D39)."""
        row = self.m.conn.execute(
            "SELECT COUNT(*) FROM ts_events WHERE ts_request_id=? AND detail LIKE ?",
            (rid, f"{LOST_PREFIX}%"),
        ).fetchone()
        return int(row[0])

    def record_rejection(self, rid: int, error: str, at: str) -> None:
        """A time-series rejection or submit error: an event here, never in ``cds_rejections``."""
        with self.m.tx() as c:
            c.execute("INSERT INTO ts_events (ts_request_id, at, event, detail) VALUES (?,?,?,?)",
                      (rid, at, "cds_rejection", error[:500]))  # fmt: skip

    def rejections_since(self, since: str) -> list[str]:
        """Times (ISO, oldest first) of time-series rejections after ``since``."""
        rows = self.m.conn.execute(
            "SELECT at FROM ts_events WHERE event='cds_rejection' AND at > ? ORDER BY at",
            (since,),
        )
        return [r["at"] for r in rows]

    def add_store(self, rows: list[TsRequest], path: Path, content_sha256: str) -> None:
        """Record a written store and move its chunks verified → stored, in one transaction."""
        first = rows[0]
        now = utcnow()
        with self.m.tx() as c:
            c.execute(
                "INSERT INTO ts_stores (site_group, site, short_name, start_date, end_date,"
                " path, content_sha256, request_ids, written_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (first.site_group, first.site, first.short_name, rows[0].start.isoformat(),
                 rows[-1].end.isoformat(), str(path), content_sha256,
                 json.dumps([r.id for r in rows]), now),
            )  # fmt: skip
            for r in rows:
                self._transition(c, r.id, ["verified"], "stored", str(path), {})

    def stores(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.m.conn.execute("SELECT * FROM ts_stores ORDER BY id")]

    def store_for(self, group: str, site: str, short: str, start: dt.date, end: dt.date):
        return self.m.conn.execute(
            "SELECT * FROM ts_stores WHERE site_group=? AND site=? AND short_name=? AND"
            " start_date=? AND end_date=?",
            (group, site, short, start.isoformat(), end.isoformat()),
        ).fetchone()


# --- the fetcher -----------------------------------------------------------------------


class TimeseriesBackend(Protocol):
    """What the fetcher needs from the CDS (``DatastoresBackend`` provides it)."""

    def submit(self, dataset: str, request: dict[str, Any]) -> str: ...
    def info(self, request_id: str) -> RemoteInfo: ...
    def download(self, request_id: str, target: Path) -> int: ...
    def delete(self, request_id: str) -> None: ...
    def active_timeseries_jobs(self) -> list[str]: ...


class PlanConflict(ValueError):
    """A site already has chunks planned another way; ``--replan`` replaces them."""


@dataclass
class PlanResult:
    planned: int = 0  # chunks newly planned
    kept: int = 0  # chunks already there
    cancelled: int = 0  # chunks replaced by --replan
    already_stored: list[str] = field(default_factory=list)


@dataclass
class FetchSummary:
    submitted: int = 0
    verified: int = 0
    failed: int = 0
    verification_failed: int = 0
    rejected: int = 0
    resubmitted: int = 0
    stored: int = 0
    store_errors: list[str] = field(default_factory=list)
    stopped: str | None = None  # why submissions stopped for this run
    paused: bool = False  # the account's CDS pause is on (D39)
    left: dict[str, int] = field(default_factory=dict)  # chunk counts by state at the end

    def add(self, o: FetchSummary) -> None:
        for f in ("submitted", "verified", "failed", "verification_failed", "rejected",
                  "resubmitted", "stored"):  # fmt: skip
            setattr(self, f, getattr(self, f) + getattr(o, f))
        self.store_errors += o.store_errors
        self.stopped, self.paused = o.stopped, o.paused


class PointFetcher:
    """Plans, fetches, verifies and stores point time series; resumable from the manifest."""

    def __init__(
        self,
        manifest: Manifest,
        backend: TimeseriesBackend,
        staging_dir: Path,
        store_root: Path,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
        delete_remote: bool = True,
    ):
        self.m = manifest
        self.rec = TimeseriesRecords(manifest)
        self.backend = backend
        self.download_dir = Path(staging_dir) / "timeseries"
        self.store_root = Path(store_root)
        self.now = now
        self.delete_remote = delete_remote
        self.stopped: str | None = None

    # --- planning ---------------------------------------------------------------------
    def plan(
        self, cfg: PointFetchConfig, points: list[PointSite], chunk_years: int | None = None,
        replan: bool = False,
    ) -> PlanResult:  # fmt: skip
        years = chunk_years or cfg.chunk_years
        chunks = plan_chunks(cfg.start, cfg.end, years)
        out = PlanResult()
        todo: list[tuple[PointSite, list[TsRequest]]] = []
        for p in points:  # check every site first, so a conflict changes nothing
            if self.rec.store_for(p.group, p.site, cfg.short_name, cfg.start, cfg.end):
                out.already_stored.append(p.site)
                continue
            keys = {chunk_key(p, cfg.short_name, s, e) for s, e in chunks}
            stale = [r for r in self.rec.for_site(p.group, p.site, cfg.short_name)
                     if r.key not in keys]  # fmt: skip
            if stale and not replan:
                raise PlanConflict(
                    f"{p.site} already has chunks planned another way "
                    f"({', '.join(r.key.rsplit('/', 1)[1] for r in stale[:3])}…); "
                    "use --replan to replace the unfinished ones"
                )
            if any(r.state == "submitted" for r in stale):
                raise PlanConflict(f"{p.site} has a chunk at the CDS; replan once it is back")
            todo.append((p, stale))
        for p, stale in todo:
            for r in stale:
                self.rec.transition(r.id, ["planned", "verified", "failed"], "cancelled",
                                    detail=f"replanned with {years}-year chunks")  # fmt: skip
                out.cancelled += 1
            for s, e in chunks:
                key = chunk_key(p, cfg.short_name, s, e)
                _, new = self.rec.add(key, cfg.dataset, p, cfg, s, e, cds_request(cfg, p, s, e))
                out.planned += new
                out.kept += not new
        log.info("time series: %d chunks planned, %d already there, %d replaced; stored "
                 "already: %s", out.planned, out.kept, out.cancelled,
                 ", ".join(out.already_stored) or "none")  # fmt: skip
        return out

    def retry_failed(self, max_attempts: int = 5) -> int:
        """Failed chunks with fewer than ``max_attempts`` attempts go back to planned."""
        n = 0
        for r in self.rec.by_state("failed"):
            if r.attempts < max_attempts:
                self.rec.transition(r.id, ["failed"], "planned", detail="retry",
                                    cds_request_id=None)  # fmt: skip
                n += 1
        return n

    # --- one pass ---------------------------------------------------------------------
    def step(self) -> FetchSummary:
        s = FetchSummary()
        in_flight, finished = 0, []
        for r in self.rec.by_state("submitted"):
            outcome, info = self._poll(r, s)
            if outcome == "in_flight":
                in_flight += 1
            elif outcome == "finished":
                finished.append((r, info))
        nxt = self.rec.by_state("planned")
        if nxt and not in_flight and self._gate_open(s):
            self._submit(nxt[0], s)
        for r, info in finished:
            self._fetch(r, info, s)
        self._write_ready_stores(s)
        s.stopped = self.stopped
        s.left = self.rec.counts()
        return s

    def run(self, poll_seconds: float = 10.0, max_seconds: float | None = None) -> FetchSummary:
        """Step until nothing is planned or at the CDS, submissions stop, or time runs out."""
        t_end = None if max_seconds is None else time.monotonic() + max_seconds
        total = FetchSummary()
        while True:
            s = self.step()
            total.add(s)
            total.left = s.left
            if not self.rec.by_state("planned", "submitted"):
                return total
            if (s.stopped or s.paused) and not self.rec.by_state("submitted"):
                return total
            if t_end is not None and time.monotonic() > t_end:
                return total
            time.sleep(poll_seconds)

    # --- the time-series slot's own gate ----------------------------------------------
    def _gate_open(self, s: FetchSummary) -> bool:
        if self.stopped:
            return False
        since = (self.now() - REJECTION_WINDOW).isoformat(timespec="seconds")
        recent = self.rec.rejections_since(since)
        if len(recent) >= REJECTIONS_TO_PAUSE:
            # Repeated invalid requests are what gets accounts disabled (D39), so the
            # time-series slot has the same ceiling, on its own count: it waits until the
            # oldest of them is 24 h old. No resume command; time lifts it.
            self._stop(f"{len(recent)} time-series rejections within 24 h (last {recent[-1]}); "
                       "no time-series request until the oldest is 24 h old")  # fmt: skip
            return False
        if self.m.cds_control().get("paused_at"):
            # The account's pause (D39) holds this slot too: a paused account is one to
            # leave alone. The reverse never happens: these jobs don't touch that gate.
            s.paused = True
            log.warning("CDS submissions are paused (D39); no time-series request submitted")
            return False
        try:
            active = self.backend.active_timeseries_jobs()
        except Exception as e:
            log.warning("could not list time-series jobs at the CDS, not submitting: %s", e)
            return False
        if active:
            log.info("%d time-series job(s) at the CDS (%s); waiting", len(active),
                     ", ".join(active[:3]))  # fmt: skip
            return False
        return True

    def _now_iso(self) -> str:
        return self.now().astimezone(dt.UTC).isoformat(timespec="seconds")

    def _stop(self, why: str) -> None:
        self.stopped = why
        log.error("time-series submissions stopped for this run: %s", why)

    # --- internals --------------------------------------------------------------------
    def _submit(self, r: TsRequest, s: FetchSummary) -> None:
        try:
            rid = self.backend.submit(r.dataset, r.request)
        except Exception as e:
            s.rejected += 1
            s.failed += 1
            self.rec.record_rejection(r.id, f"submit: {e}", self._now_iso())
            self.rec.fail(r.id, ["planned"], f"submit: {e}")
            self._stop(f"submit of {r.key} failed: {e}")
            return
        self.rec.transition(r.id, ["planned"], "submitted", detail=rid, cds_request_id=rid,
                            submitted_at=self._now_iso())  # fmt: skip
        s.submitted += 1
        log.info("submitted %s as %s", r.key, rid)

    def _poll(self, r: TsRequest, s: FetchSummary) -> tuple[str, RemoteInfo | None]:
        try:
            info = self.backend.info(r.cds_request_id)
        except Exception as e:
            log.warning("poll %s (%s) failed, will retry: %s", r.key, r.cds_request_id, e)
            return "in_flight", None
        if info.status in PENDING:
            return "in_flight", info
        if info.status in FAILED:
            error = f"cds {info.status}: {info.error}"
            s.rejected += 1
            s.failed += 1
            self.rec.record_rejection(r.id, error, self._now_iso())
            self.rec.fail(r.id, ["submitted"], error)
            self._stop(f"{r.key} {error}")
            return "done_with", info
        if info.status in GONE:
            why = f"cds {info.status}" + (f": {info.error}" if info.error else "")
            lost = self.rec.lost_count(r.id)
            if lost >= MAX_LOST_RESUBMITS:
                s.failed += 1
                self.rec.fail(r.id, ["submitted"], f"{LOST_PREFIX} {lost + 1} times ({why})")
                return "done_with", info
            s.resubmitted += 1
            self.rec.transition(r.id, ["submitted"], "planned", detail=f"{LOST_PREFIX} ({why})",
                                cds_request_id=None)  # fmt: skip
            log.warning("%s: %s; planned again (%d of %d)", r.key, why, lost + 1,
                        MAX_LOST_RESUBMITS)  # fmt: skip
            return "done_with", info
        if info.status != DONE:
            s.failed += 1
            self.rec.fail(r.id, ["submitted"], f"unknown cds status {info.status!r}")
            return "done_with", info
        return "finished", info

    def _fetch(self, r: TsRequest, info: RemoteInfo, s: FetchSummary) -> None:
        """Download (temp name → fsync → rename), then verify; the file stays on staging."""
        self.download_dir.mkdir(parents=True, exist_ok=True)
        final = self.download_dir / f"{safe_name(r.key)}.download"
        part = final.with_name(final.name + ".part")
        try:
            size = self.backend.download(r.cds_request_id, part)
            if info.content_length is not None and size != info.content_length:
                raise OSError(f"size {size} != server content length {info.content_length}")
            digest = sha256_file(part)
            with open(part, "rb") as fh:
                os.fsync(fh.fileno())
            os.replace(part, final)
        except Exception as e:
            log.error("download %s failed: %s", r.key, e)
            part.unlink(missing_ok=True)
            s.failed += 1
            self.rec.fail(r.id, ["submitted"], f"download: {e}")
            return
        check = verify_point_file(final, r.expectation())
        files = dict(file_path=str(final), file_size=size, file_sha256=digest,
                     check_json=json.dumps(check.report(), sort_keys=True))  # fmt: skip
        if check.ok:
            detail = f"{check.times.size} hours, {size} bytes"
            self.rec.transition(r.id, ["submitted"], "verified", detail=detail, **files)
            s.verified += 1
            log.info("verified %s: %d hours, sha256 %s", r.key, check.times.size, digest[:12])
        else:
            # Kept under its own name, so a retry's download never replaces the evidence.
            kept = final.with_name(f"{final.stem}.failed-{r.attempts + 1}{final.suffix}")
            os.replace(final, kept)
            final = kept
            files["file_path"] = str(kept)
            s.failed += 1
            s.verification_failed += 1
            self.rec.fail(r.id, ["submitted"], "verification: " + "; ".join(check.problems),
                          **files)  # fmt: skip
            log.error("verification of %s failed (file kept at %s): %s; counts %s", r.key,
                      final, "; ".join(check.problems), check.counts)  # fmt: skip
        if self.delete_remote:
            try:
                self.backend.delete(r.cds_request_id)
            except Exception as e:  # cleanup at the CDS is a courtesy, not required
                log.warning("could not delete remote %s: %s", r.cds_request_id, e)

    # --- per-site stores ----------------------------------------------------------------
    def store_path(self, rows: list[TsRequest]) -> Path:
        r = rows[0]
        name = f"{r.short_name}_{rows[0].start:%Y%m%d}-{rows[-1].end:%Y%m%d}.zarr"
        return self.store_root / r.site_group / r.site / name

    def _write_ready_stores(self, s: FetchSummary) -> None:
        groups: dict[tuple[str, str, str], list[TsRequest]] = {}
        for r in self.rec.by_state(*ACTIVE):
            groups.setdefault((r.site_group, r.site, r.short_name), []).append(r)
        for rows in groups.values():
            if all(r.state == "verified" for r in rows):
                rows.sort(key=lambda r: r.start)
                try:
                    self._write_store(rows)
                    s.stored += 1
                except Exception as e:
                    msg = f"{rows[0].site_group}/{rows[0].site}: {e}"
                    s.store_errors.append(msg)
                    log.error("store not written for %s", msg)

    def _write_store(self, rows: list[TsRequest]) -> None:
        from astroseeing.ingest.store import Prepared, write_store_atomic
        from astroseeing.qc import QCCounts

        for a, b in itertools.pairwise(rows):
            if b.start != a.end + dt.timedelta(days=1):
                raise ValueError(f"chunks {a.key} and {b.key} are not contiguous")
        times, values = [], []
        qc = QCCounts()
        for r in rows:  # read again: the staging file must still be the verified one
            if sha256_file(Path(r.file_path)) != r.file_sha256:
                raise OSError(f"{r.file_path} changed since it was verified")
            check = verify_point_file(Path(r.file_path), r.expectation())
            if not check.ok:
                raise ValueError(f"{r.key} no longer verifies: {check.problems}")
            times.append(check.times)
            values.append(check.values)
            for name, n in check.counts.items():
                qc.add(name, n, check.times.size)
        t, v = np.concatenate(times), np.concatenate(values)
        whole = PointExpectation(rows[0].short_name, rows[0].units, rows[0].lon, rows[0].lat,
                                 rows[0].start, rows[-1].end)  # fmt: skip
        if not np.array_equal(t, whole.hours()) or np.isnan(v).any():
            raise ValueError("the joined series is not every hour once without NaN")
        first = rows[0]
        site_cfg = load_config("sites")[first.site_group][first.site]
        settings = {"dataset": first.dataset, "requests": [r.request for r in rows]}
        attrs = {
            "site_group": first.site_group,
            "site": first.site,
            "site_coords": {"lon": site_cfg["lon"], "lat": site_cfg["lat"]},
            "point": {"lon": first.lon, "lat": first.lat},
            "source_dataset": first.dataset,
            "variable": first.variable,
            "short_name": first.short_name,
            "units": first.units,
            "period": [first.start.isoformat(), rows[-1].end.isoformat()],
            "time_axis": "every hour, seconds since 1970-01-01 UTC",
            "chunk_files_sha256": {r.key: r.file_sha256 for r in rows},
            **era5_attribution(first.dataset),
            "provenance": provenance(settings, {"ts_request_ids": [r.id for r in rows]}),
        }
        prep = Prepared(dims=("time",), coords={"time": (("time",), t)},
                        data={first.short_name: v}, qc=qc)  # fmt: skip
        path = self.store_path(rows)
        _probe_nas(self.store_root)  # a hung NAS must not hang the write (AGENTS.md)
        result = write_store_atomic(path, prep, attrs)
        self.rec.add_store(rows, path, result.content_sha256)
        log.info("stored %s: %d hours (%s)", path, t.size,
                 "already present" if result.already_present else "written")  # fmt: skip


def read_point_store(path: Path) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """(times as int64 s since 1970, values, attributes) of a per-site store."""
    from astroseeing.ingest.store import read_store

    arrays, attrs = read_store(Path(path))
    times = arrays.pop("time")
    (values,) = arrays.values()
    return times, values, attrs


def _probe_nas(root: Path, timeout_s: float = 30.0) -> None:
    """``stat`` the nearest existing parent of ``root`` in a child process, with a timeout."""
    from astroseeing.paths import probe_responsive

    p = Path(root)
    while not p.exists() and p != p.parent:
        p = p.parent
    probe_responsive(p, timeout_s)
