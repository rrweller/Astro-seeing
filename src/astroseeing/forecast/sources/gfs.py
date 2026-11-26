"""GFS 0.25° from NOMADS's grib filter (F1 spec Module 1; ticket #51).

NOMADS cuts each file to the area on the server (D51 item 14), so a step is two small
requests: ``pgrb2`` (the "most commonly used" file) and ``pgrb2b`` (the in-between
25 hPa levels). Together they hold the 39 pressure levels from 1000 to 50 hPa
(``docs/research/forecast-sources.md``). Requests are paced to the host's limit in the
settings (NOMADS: at most 1 a second). The AWS fallback and the retry rules are
ticket #58 (F1-9); here every file is tried once, and a failed file leaves its step
missing, with the reason.

``read`` decodes the GRIB2 messages by their WMO code numbers (discipline, category,
parameter, surface type), not by eccodes' short names, and refuses anything other than
the expected content with :class:`FormatMismatch`: a missing or duplicated field, an
unknown one, another grid, run or step. The filter's cross product of variables and
levels also returns two kinds of message we never read, and these are the only ones
skipped, each counted in the log: the 6-hour (and shorter) average cloud covers (D48
item 1: the instantaneous values are used) and the skin temperature ``TMP:surface``.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import numpy as np

from astroseeing.forecast.http import HttpClient, HttpError, HttpUnavailable
from astroseeing.forecast.settings import Area, Model
from astroseeing.forecast.sources.interface import (
    FetchedFile,
    FetchResult,
    FormatMismatch,
    RunFields,
    RunRef,
)

log = logging.getLogger(__name__)

#: Credit beside GFS's rows (D44 item 8). The AWS registry: "NOAA requests attribution
#: for the use or dissemination of unaltered NOAA data" and "it is not permissible to
#: state or imply endorsement by or affiliation with NOAA" (forecast-sources.md).
CREDIT = "GFS: NOAA/NCEP (US government open data); not endorsed by NOAA"

DATA_DIR = "/pub/data/nccf/com/gfs/prod"
FILTERS = {"pgrb2": "/cgi-bin/filter_gfs_0p25_1hr.pl", "pgrb2b": "/cgi-bin/filter_gfs_0p25b.pl"}

#: The levels only ``pgrb2b`` has: 125 to 875 hPa every 50 hPa (``.idx`` files of the
#: 2026-11-26 06z run). Cloud cover at 70 hPa is also only in ``pgrb2b``.
PGRB2B_LEVELS = frozenset(float(p) for p in range(125, 900, 50))
PGRB2B_CLOUD_LEVEL = 70.0

#: GRIB2 (discipline, category, number) → the NOMADS name used in requests and messages.
PARAMETERS = {
    (0, 0, 0): "TMP",
    (0, 3, 5): "HGT",
    (0, 2, 2): "UGRD",
    (0, 2, 3): "VGRD",
    (0, 6, 1): "TCDC",
    (0, 6, 3): "LCDC",
    (0, 6, 4): "MCDC",
    (0, 6, 5): "HCDC",
    (0, 19, 0): "VIS",
    (0, 3, 0): "PRES",
}
#: GRIB2 type of first fixed surface → the filter's level name.
SURFACES = {
    100: "mb",
    1: "surface",
    214: "low cloud layer",
    224: "middle cloud layer",
    234: "high cloud layer",
    10: "entire atmosphere",
}
PROFILE_VARS = ("HGT", "TMP", "UGRD", "VGRD")
LAYER_CLOUD = {
    "total_cloud_pct": ("TCDC", "entire atmosphere"),
    "low_cloud_pct": ("LCDC", "low cloud layer"),
    "mid_cloud_pct": ("MCDC", "middle cloud layer"),
    "high_cloud_pct": ("HCDC", "high cloud layer"),
}
#: Fog signals GFS has (D49 item 3), in RunFields' vocabulary.
FOG_FIELDS = {"visibility_m": ("VIS", "surface")}
#: Messages the filter returns that are never read (counted in the log).
IGNORED_INSTANT = frozenset({("TMP", "surface", None)})
IGNORED_AVERAGES = frozenset({(v, s, None) for v, s in LAYER_CLOUD.values()})

_FILE_RE = re.compile(r"gfs\.t(\d\d)z\.(pgrb2b?)\.0p25\.f(\d{3})\.grb2$")
_GRID_TOL = 1e-6


class RatePacer:
    """Spaces request starts at least ``1 / max_per_s`` seconds apart (D51 item 14)."""

    def __init__(self, max_per_s: float | None, monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):  # fmt: skip
        self.interval = 0.0 if not max_per_s else 1.0 / max_per_s
        self.monotonic, self.sleep = monotonic, sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            gap = self._last + self.interval - self.monotonic()
            if gap > 0:
                self.sleep(gap)
        self._last = self.monotonic()


@dataclass(frozen=True)
class FilterRequest:
    """One NOMADS grib-filter request: one file (``pgrb2`` or ``pgrb2b``) of one step."""

    step: int
    part: str
    path: str
    params: tuple[tuple[str, str], ...]
    filename: str

    @property
    def target(self) -> str:
        """Path and query string, exactly as sent."""
        return f"{self.path}?{urlencode(self.params)}"


class GfsAdapter:
    """The GFS source (``SourceAdapter``). ``areas`` are the settings' areas (``read``
    checks the grid against the fetched area's box); ``base_url`` replaces the configured
    main host (tests point it at a fake server); ``pacer`` paces every request to it."""

    def __init__(self, model: Model, http: HttpClient | None, areas: Mapping[str, Area],
                 base_url: str | None = None, pacer: RatePacer | None = None):  # fmt: skip
        if model.grid.kind != "regular_latlon":
            raise ValueError(f"GFS needs a regular lat-lon grid, settings say {model.grid.kind}")
        unknown = sorted(set(model.fog_signals) - set(FOG_FIELDS))
        if unknown:
            raise ValueError(f"GFS has no fog signal {unknown}; it has {sorted(FOG_FIELDS)}")
        self.model = model
        self.http = http
        self.areas = areas
        self.host = model.hosts.main
        self.base_url = (base_url or self.host.url).rstrip("/")
        self.pacer = pacer or RatePacer(self.host.max_requests_per_s)
        levels = set(model.pressure_levels_hpa)
        self._levels = {
            "pgrb2": sorted(levels - PGRB2B_LEVELS, reverse=True),
            "pgrb2b": sorted(levels & PGRB2B_LEVELS, reverse=True),
        }
        self._cloud_levels = {
            "pgrb2": [p for p in self._levels["pgrb2"] if p != PGRB2B_CLOUD_LEVEL],
            "pgrb2b": sorted({*self._levels["pgrb2b"], PGRB2B_CLOUD_LEVEL} & levels, reverse=True),
        }

    # -- the request plan ---------------------------------------------------------------
    def request_plan(
        self, run: RunRef, area: Area, steps_h: tuple[int, ...]
    ) -> list[FilterRequest]:
        """Every request a fetch of these steps makes, in order (two per step)."""
        day, hh = run.run_time.strftime("%Y%m%d"), run.run_time.strftime("%H")
        box = area.box
        region = (("subregion", ""), ("leftlon", _deg(box.west % 360)),
                  ("rightlon", _deg(box.east % 360 or 360)), ("toplat", _deg(box.north)),
                  ("bottomlat", _deg(box.south)))  # fmt: skip
        plan = []
        for step in steps_h:
            for part in ("pgrb2", "pgrb2b"):
                name = f"gfs.t{hh}z.{part}.0p25.f{step:03d}"
                variables = [*PROFILE_VARS, "TCDC"]
                levels = sorted(set(self._levels[part]) | set(self._cloud_levels[part]),
                                reverse=True)  # fmt: skip
                extra_levels: list[str] = []
                if part == "pgrb2":
                    variables += ["LCDC", "MCDC", "HCDC", "VIS", "PRES"]
                    extra_levels = ["surface", "low_cloud_layer", "middle_cloud_layer",
                                    "high_cloud_layer", "entire_atmosphere"]  # fmt: skip
                params = (("dir", f"/gfs.{day}/{hh}/atmos"), ("file", name),
                          *((f"var_{v}", "on") for v in variables),
                          *((f"lev_{p:g}_mb", "on") for p in levels),
                          *((f"lev_{s}", "on") for s in extra_levels), *region)  # fmt: skip
                plan.append(FilterRequest(step, part, FILTERS[part], params, f"{name}.grb2"))
        return plan

    # -- SourceAdapter --------------------------------------------------------------------
    def latest_published(self, now: dt.datetime) -> RunRef | None:
        """The newest run of the last day whose last step is listed in both files' index
        (two HEAD requests per run tried; a 403 or 404 means not there yet)."""
        last = self.model.steps_h[-1]
        start = now.replace(minute=0, second=0, microsecond=0)
        for back in range(25):
            t = start - dt.timedelta(hours=back)
            if t.hour not in self.model.runs_utc:
                continue
            run = RunRef(self.model.id, t)
            if all(self._listed(run, part, last) for part in ("pgrb2", "pgrb2b")):
                return run
        return None

    def _listed(self, run: RunRef, part: str, step: int) -> bool:
        day, hh = run.run_time.strftime("%Y%m%d"), run.run_time.strftime("%H")
        url = (f"{self.base_url}{DATA_DIR}/gfs.{day}/{hh}/atmos/"
               f"gfs.t{hh}z.{part}.0p25.f{step:03d}.idx")  # fmt: skip
        self.pacer.wait()
        try:
            self.http.head(url)
        except HttpUnavailable:
            raise
        except HttpError as e:
            if e.status in (403, 404):
                return False
            raise
        return True

    def fetch(self, run: RunRef, area: Area, steps_h: tuple[int, ...],
              dest_dir: Path) -> FetchResult:  # fmt: skip
        files, missing = [], {}
        for req in self.request_plan(run, area, steps_h):
            if req.step in missing:
                continue  # the step's other file failed: the step is missing anyway
            self.pacer.wait()
            try:
                d = self.http.download(self.base_url + req.target, Path(dest_dir) / req.filename)
            except HttpError as e:
                missing[req.step] = f"{req.part}: {e}"
                log.warning("GFS %s step %d %s: %s", run.label, req.step, req.part, e)
                continue
            files.append(FetchedFile(d.url, self.host.name, d.path, d.bytes, d.seconds, d.sha256))
        return FetchResult(run, area.id, Path(dest_dir), tuple(files), tuple(steps_h), missing)

    def read(self, fetched: FetchResult) -> RunFields:
        run, area = fetched.run, fetched.area
        steps = fetched.fetched_steps
        if not steps:
            raise FormatMismatch(self.model.id, f"{run.label}: no step was fetched")
        by_step: dict[int, dict[str, Path]] = {}
        for f in fetched.files:
            m = _FILE_RE.search(Path(f.path).name)
            if not m or int(m.group(1)) != run.run_time.hour:
                raise FormatMismatch(self.model.id, f"unexpected file {Path(f.path).name}")
            by_step.setdefault(int(m.group(3)), {})[m.group(2)] = Path(f.path)
        grid = None
        decoded: list[dict] = []
        ignored: Counter[str] = Counter()
        for step in steps:
            parts = by_step.get(step, {})
            fields: dict[tuple, np.ndarray] = {}
            for part in ("pgrb2", "pgrb2b"):
                if part not in parts:
                    raise FormatMismatch(self.model.id, f"step {step}: no {part} file")
                got: dict[tuple, np.ndarray] = {}
                grid = self._decode(parts[part], area, run, step, got, ignored, grid)
                missing = sorted(self._expected(part) - got.keys(), key=str)
                if missing:
                    raise FormatMismatch(self.model.id, f"step {step} ({parts[part].name}): "
                                         f"missing {_names(missing)}")  # fmt: skip
                fields.update(got)
            decoded.append(fields)
        if ignored:
            log.info("GFS %s: skipped, as expected: %s", run.label,
                     ", ".join(f"{k} ×{n}" for k, n in sorted(ignored.items())))  # fmt: skip
        return self._assemble(run, area, steps, decoded, grid)

    # -- decoding ---------------------------------------------------------------------
    def _expected(self, part: str) -> set[tuple]:
        want = {(v, "mb", p) for v in PROFILE_VARS for p in self._levels[part]}
        if self.model.level_cloud:
            want |= {("TCDC", "mb", p) for p in self._cloud_levels[part]}
        if part == "pgrb2":
            want |= {(v, s, None) for v, s in LAYER_CLOUD.values()}
            want |= {("PRES", "surface", None), ("HGT", "surface", None)}
            want |= {(*FOG_FIELDS[name], None) for name in self.model.fog_signals}
        return want

    def _decode(self, path: Path, area: str, run: RunRef, step: int, fields: dict,
                ignored: Counter, grid: tuple | None) -> tuple:  # fmt: skip
        import eccodes as ec

        model = self.model.id
        part = "pgrb2b" if ".pgrb2b." in path.name else "pgrb2"
        want = self._expected(part)
        n = 0
        with open(path, "rb") as f:
            while (h := ec.codes_grib_new_from_file(f)) is not None:
                n += 1
                try:
                    key, step_type = _message_key(h)
                    where = f"step {step} ({path.name}) message {n}"
                    if key is None:
                        raise FormatMismatch(model, f"{where}: unknown field {step_type}")
                    if step_type != "instant":
                        if key in IGNORED_AVERAGES and step > 0:
                            ignored[f"{_names([key])} ({step_type})"] += 1
                            continue
                        raise FormatMismatch(model, f"{where}: {_names([key])} is {step_type}")
                    if key in IGNORED_INSTANT:
                        ignored[_names([key])] += 1
                        continue
                    if key not in want:
                        raise FormatMismatch(model, f"{where}: unexpected {_names([key])}")
                    if key in fields:
                        raise FormatMismatch(model, f"{where}: {_names([key])} twice")
                    _check_time(h, run, step, model, where)
                    this_grid = _grid(h)
                    if grid is None:
                        self._check_area_grid(this_grid, area)
                        grid = this_grid
                    elif not _same_grid(this_grid, grid):
                        raise FormatMismatch(model, f"{where}: grid {this_grid} differs from "
                                             f"{grid}")  # fmt: skip
                    fields[key] = _values(h, this_grid)
                finally:
                    ec.codes_release(h)
        if n == 0:
            raise FormatMismatch(model, f"step {step}: {path.name} holds no GRIB message")
        return grid

    def _check_area_grid(self, grid: tuple, area_id: str) -> None:
        if area_id not in self.areas:
            raise ValueError(f"unknown area {area_id!r}; known: {sorted(self.areas)}")
        want = expected_grid(self.model.grid.spacing, self.areas[area_id])
        if not _same_grid(grid, want):
            raise FormatMismatch(self.model.id, f"grid {grid} is not the "
                                 f"{self.model.grid.spacing:g}° grid of area {area_id}, {want} "
                                 "(Nj, Ni, north, west, Δlat, Δlon)")  # fmt: skip

    def _assemble(self, run: RunRef, area: str, steps: tuple[int, ...], decoded: list[dict],
                  grid: tuple) -> RunFields:  # fmt: skip
        levels = list(self.model.pressure_levels_hpa)  # bottom → top
        nj, ni, lat0, lon0, dlat, dlon = grid
        lats = lat0 - dlat * np.arange(nj)
        lons = (lon0 + dlon * np.arange(ni) + 180.0) % 360.0 - 180.0
        lat2, lon2 = np.meshgrid(lats, lons, indexing="ij")

        def level_field(var: str) -> np.ndarray:
            return np.stack([np.stack([d[(var, "mb", p)] for p in levels], axis=-1)
                             for d in decoded])  # fmt: skip

        def single(var: str, surface: str) -> np.ndarray:
            return np.stack([d[(var, surface, None)] for d in decoded])

        ground = single("HGT", "surface")
        if not np.array_equal(ground, np.broadcast_to(ground[0], ground.shape), equal_nan=True):
            raise FormatMismatch(self.model.id, "HGT:surface (model ground) changes between steps")
        t0 = np.datetime64(run.run_time.replace(tzinfo=None), "s")
        return RunFields(
            run=run,
            model=self.model,
            lat=lat2,
            lon=lon2,
            valid_times=t0 + np.array(steps, dtype="timedelta64[h]").astype("timedelta64[s]"),
            pressure_hpa=np.array(levels),
            geopotential_height_m=level_field("HGT"),
            temperature_k=level_field("TMP"),
            u_ms=level_field("UGRD"),
            v_ms=level_field("VGRD"),
            level_cloud_pct=level_field("TCDC") if self.model.level_cloud else None,
            **{name: single(*key) for name, key in LAYER_CLOUD.items()},
            surface_pressure_hpa=single("PRES", "surface") / 100.0,
            model_ground_m=ground[0],
            fog={name: single(*FOG_FIELDS[name]) for name in self.model.fog_signals},
        )


def _deg(x: float) -> str:
    return repr(round(float(x), 6))


def _names(keys) -> str:
    out = []
    for var, surface, level in keys:
        out.append(f"{var}:{level:g} mb" if surface == "mb" else f"{var}:{surface}")
    return ", ".join(out)


def _message_key(h) -> tuple[tuple | None, str]:
    import eccodes as ec

    code = tuple(ec.codes_get(h, k, int) for k in ("discipline", "parameterCategory",
                                                     "parameterNumber"))  # fmt: skip
    surface_code = ec.codes_get(h, "typeOfFirstFixedSurface", int)
    step_type = str(ec.codes_get(h, "stepType"))
    var, surface = PARAMETERS.get(code), SURFACES.get(surface_code)
    if var is None or surface is None:
        return None, f"(GRIB2 parameter {code}, surface type {surface_code})"
    level = None
    if surface == "mb":
        scale = ec.codes_get(h, "scaleFactorOfFirstFixedSurface", int)
        value = ec.codes_get(h, "scaledValueOfFirstFixedSurface", int)
        level = round(value * 10.0 ** (-scale) / 100.0, 6)  # Pa → hPa
    return (var, surface, level), step_type


def _check_time(h, run: RunRef, step: int, model: str, where: str) -> None:
    import eccodes as ec

    date, hhmm = ec.codes_get(h, "dataDate", int), ec.codes_get(h, "dataTime", int)
    t = dt.datetime.strptime(f"{date:08d}{hhmm:04d}", "%Y%m%d%H%M").replace(tzinfo=dt.UTC)
    if t != run.run_time:
        raise FormatMismatch(model, f"{where}: run time {t:%Y-%m-%dT%H}Z, expected {run.label}")
    ec.codes_set(h, "stepUnits", 1)
    if int(ec.codes_get(h, "endStep")) != step:
        raise FormatMismatch(model, f"{where}: step {ec.codes_get(h, 'endStep')} h, expected "
                             f"{step} h")  # fmt: skip


def _grid(h) -> tuple:
    """(Nj, Ni, north latitude, west longitude, Δlat, Δlon), whichever way rows run."""
    import eccodes as ec

    if ec.codes_get(h, "gridType") != "regular_ll":
        return ("not regular_ll", ec.codes_get(h, "gridType"))
    if int(ec.codes_get(h, "iScansNegatively")) or int(ec.codes_get(h, "jPointsAreConsecutive")):
        return ("scan order", "not west→east in consecutive rows")
    north_key = "latitudeOf{}GridPointInDegrees".format(
        "Last" if int(ec.codes_get(h, "jScansPositively")) else "First"
    )
    return (
        int(ec.codes_get(h, "Nj")),
        int(ec.codes_get(h, "Ni")),
        float(ec.codes_get(h, north_key)),
        float(ec.codes_get(h, "longitudeOfFirstGridPointInDegrees")),
        float(ec.codes_get(h, "jDirectionIncrementInDegrees")),
        float(ec.codes_get(h, "iDirectionIncrementInDegrees")),
    )


def _same_grid(a: tuple, b: tuple) -> bool:
    return len(a) == len(b) == 6 and a[:2] == b[:2] and all(
        abs(x - y) < _GRID_TOL for x, y in zip(a[2:], b[2:], strict=True))  # fmt: skip


def expected_grid(spacing: float, area: Area) -> tuple:
    """The grid NOMADS's filter returns for the area: every grid point inside the box
    (Nj, Ni, north latitude, west longitude 0-360, Δlat, Δlon)."""
    box = area.box
    north = math.floor(box.north / spacing + 1e-9) * spacing
    south = math.ceil(box.south / spacing - 1e-9) * spacing
    west = math.ceil((box.west % 360) / spacing - 1e-9) * spacing
    east = math.floor(((box.east % 360) or 360) / spacing + 1e-9) * spacing
    nj = round((north - south) / spacing) + 1
    ni = round((east - west) / spacing) + 1
    return (nj, ni, north, west, spacing, spacing)


def _values(h, grid: tuple) -> np.ndarray:
    import eccodes as ec

    ec.codes_set(h, "missingValue", 1e20)
    vals = ec.codes_get_values(h).astype(np.float64)
    vals[vals == 1e20] = np.nan  # bitmap-missing points stay NaN, counted by verify_run
    rows = vals.reshape(grid[0], grid[1])
    return rows[::-1] if int(ec.codes_get(h, "jScansPositively")) else rows  # north → south
