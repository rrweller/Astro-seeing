"""ICON-EU from DWD opendata (F1 spec Module 1; ticket #55).

DWD publishes ICON-EU as one bzip2-compressed GRIB2 file per field, level and step,
each covering the whole domain (29.5-70.5° N × 23.5° W-62.5° E at 0.0625°), with no
index and no server-side cut (``docs/research/forecast-sources.md``). So a run is
5 fields × 20 pressure levels + 7 single-level fields per step, plus the model ground
(``HSURF``) once, and we cut each field to the area's box after download: the grid
points inside the box are kept as they are, never averaged, interpolated or
regridded (D51 items 3 and 8). DWD's opendata has no fallback host (D51 item 14).

``read`` identifies every message by its GRIB2 code numbers (discipline, category,
parameter, type of surface, level), not by eccodes' short names, and refuses anything
other than the expected content with :class:`FormatMismatch`: a missing or unexpected
file, another field, level, run, step or grid, a non-instantaneous value, or a grid
that is off ICON-EU's 0.0625° lattice or doesn't cover the area's box.
"""

from __future__ import annotations

import bz2
import datetime as dt
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from astroseeing.constants import G0
from astroseeing.forecast.http import HttpClient, HttpError
from astroseeing.forecast.settings import Area, Box, Model
from astroseeing.forecast.sources.gfs import RatePacer
from astroseeing.forecast.sources.interface import (
    FetchedFile,
    FetchResult,
    FormatMismatch,
    RunFields,
    RunRef,
)

log = logging.getLogger(__name__)

#: Credit beside ICON-EU's rows (D44 item 8): DWD's source note for modified data,
#: "Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt"
#: (https://www.dwd.de/DE/service/rechtliche_hinweise/vorlagen_quellenangabe.html).
CREDIT = "ICON-EU: Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt (CC BY 4.0)"

DATA_DIR = "/weather/nwp/icon-eu/grib"
STEM = "icon-eu_europe_regular-lat-lon"

PRESSURE, SINGLE, INVARIANT = "pressure-level", "single-level", "time-invariant"


#: A GRIB2 fixed surface: its type and value (hPa on an isobaric surface, type 100;
#: as coded otherwise), ``None`` for a missing value. ``LEVEL`` stands for the level a
#: pressure-level file's name gives.
LEVEL = "level"
ISOBARIC, GROUND_SURFACE, MEAN_SEA_LEVEL, NO_SURFACE = 100, 1, 101, 255


@dataclass(frozen=True)
class Field:
    """One ICON-EU field as DWD publishes it, and how its GRIB2 message is coded: the
    parameter's code numbers and its first and second fixed surfaces (``read`` checks
    every one; DWD codes its low, mid and high cloud as cloud cover between isobaric
    surfaces, so the parameter alone doesn't tell them apart)."""

    name: str  # DWD's name, upper case in file names, lower case as the folder
    kind: str  # PRESSURE, SINGLE or INVARIANT
    code: tuple[int, int, int]  # GRIB2 discipline, parameter category, parameter number
    surfaces: tuple  # (first type, first value, second type, second value)

    @property
    def folder(self) -> str:
        return self.name.lower()


_ON_LEVEL = (ISOBARIC, LEVEL, NO_SURFACE, None)
_AT_GROUND = (GROUND_SURFACE, 0.0, NO_SURFACE, None)

#: The pressure-level fields: temperature, wind and geopotential.
PROFILE_FIELDS = {
    "temperature_k": Field("T", PRESSURE, (0, 0, 0), _ON_LEVEL),
    "u_ms": Field("U", PRESSURE, (0, 2, 2), _ON_LEVEL),
    "v_ms": Field("V", PRESSURE, (0, 2, 3), _ON_LEVEL),
    "geopotential_height_m": Field("FI", PRESSURE, (0, 3, 4), _ON_LEVEL),  # Φ; ÷ g₀ below
}
LEVEL_CLOUD = Field("CLC", PRESSURE, (0, 6, 22), _ON_LEVEL)
#: Instantaneous total, low, mid and high cloud (D48 item 1), and surface pressure. Low
#: cloud is cloud cover from the ground up to 800 hPa, mid 800-400 hPa, high above 400.
SINGLE_FIELDS = {
    "total_cloud_pct": Field("CLCT", SINGLE, (0, 6, 1), _AT_GROUND),
    "low_cloud_pct": Field("CLCL", SINGLE, (0, 6, 22), (ISOBARIC, 800.0, GROUND_SURFACE, 0.0)),
    "mid_cloud_pct": Field("CLCM", SINGLE, (0, 6, 22), (ISOBARIC, 400.0, ISOBARIC, 800.0)),
    "high_cloud_pct": Field("CLCH", SINGLE, (0, 6, 22), (ISOBARIC, 0.0, ISOBARIC, 400.0)),
    "surface_pressure_hpa": Field("PS", SINGLE, (0, 3, 0), _AT_GROUND),  # Pa; ÷ 100 below
}
#: Fog signals ICON-EU has (D49 item 3), in RunFields' vocabulary. ``WW`` is kept as
#: the code DWD gives (45 and 48 are fog); the low cloud is ``low_cloud_pct``.
FOG_FIELDS = {
    "visibility_m": Field("VIS", SINGLE, (0, 19, 0), _AT_GROUND),
    "weather_code": Field("WW", SINGLE, (0, 19, 25), _AT_GROUND),
}
#: The model ground: geometric height of the ground above mean sea level (m).
GROUND = Field("HSURF", INVARIANT, (0, 3, 6), (GROUND_SURFACE, 0.0, MEAN_SEA_LEVEL, 0.0))
#: DWD's field name → the RunFields name it fills.
_FIELD_NAMES = {
    f.name: name
    for name, f in {
        **PROFILE_FIELDS,
        "level_cloud_pct": LEVEL_CLOUD,
        **SINGLE_FIELDS,
        **FOG_FIELDS,
        "model_ground_m": GROUND,
    }.items()
}

_GRID_TOL = 1e-6


@dataclass(frozen=True)
class IconFile:
    """One file of a run: a field at one level (pressure-level fields) and one step
    (``None`` for the model ground, which DWD publishes once per run)."""

    field: Field
    step: int | None
    level_hpa: float | None
    path: str  # URL path on the host

    @property
    def filename(self) -> str:
        return self.path.rsplit("/", 1)[1]

    @property
    def label(self) -> str:
        return self.field.name + ("" if self.level_hpa is None else f":{self.level_hpa:g} hPa")


class IconEuAdapter:
    """The ICON-EU source (``SourceAdapter``). ``areas`` are the settings' areas (``read``
    cuts to the fetched area's box); ``base_url`` replaces the configured main host (tests
    point it at a fake server); ``pacer`` paces every request to it."""

    credit = CREDIT

    def __init__(
        self,
        model: Model,
        http: HttpClient | None,
        areas: Mapping[str, Area],
        base_url: str | None = None,
        pacer: RatePacer | None = None,
    ):
        if model.grid.kind != "regular_latlon":
            raise ValueError(
                f"ICON-EU needs a regular lat-lon grid, settings say {model.grid.kind}"
            )
        unknown = sorted(set(model.fog_signals) - set(FOG_FIELDS))
        if unknown:
            raise ValueError(f"ICON-EU has no fog signal {unknown}; it has {sorted(FOG_FIELDS)}")
        self.model = model
        self.http = http
        self.areas = areas
        self.host = model.hosts.main
        self.base_url = (base_url or self.host.url).rstrip("/")
        self.pacer = pacer or RatePacer(self.host.max_requests_per_s)

    # -- the file plan -------------------------------------------------------------------
    def step_fields(self) -> list[tuple[Field, float | None]]:
        """Every (field, level) a step needs, in the order they are fetched."""
        levels = list(self.model.pressure_levels_hpa)
        profile = [*PROFILE_FIELDS.values(), *([LEVEL_CLOUD] if self.model.level_cloud else [])]
        out: list[tuple[Field, float | None]] = [(f, p) for f in profile for p in levels]
        out += [(f, None) for f in SINGLE_FIELDS.values()]
        out += [(FOG_FIELDS[name], None) for name in self.model.fog_signals]
        return out

    def file_plan(self, run: RunRef, steps_h: tuple[int, ...]) -> list[IconFile]:
        """Every file a fetch of these steps downloads, in order: the model ground first,
        then each step's fields."""
        plan = [self._file(run, GROUND, None, None)]
        for step in steps_h:
            plan += [self._file(run, f, step, p) for f, p in self.step_fields()]
        return plan

    def _file(self, run: RunRef, f: Field, step: int | None, level: float | None) -> IconFile:
        stamp = run.run_time.strftime("%Y%m%d%H")
        parts = [STEM, f.kind, stamp]
        if step is not None:
            parts.append(f"{step:03d}")
        if level is not None:
            parts.append(f"{level:g}")
        parts.append(f.name)
        name = "_".join(parts) + ".grib2.bz2"
        path = f"{DATA_DIR}/{run.run_time:%H}/{f.folder}/{name}"
        return IconFile(f, step, level, path)

    # -- SourceAdapter --------------------------------------------------------------------
    def fetch(
        self, run: RunRef, area: Area, steps_h: tuple[int, ...], dest_dir: Path
    ) -> FetchResult:
        """Download the whole-domain files of these steps (the cut to ``area`` is
        ``read``'s). A failed file leaves its step missing with the reason, and the rest
        of that step isn't asked for; without the model ground no step is usable."""
        files: list[FetchedFile] = []
        missing: dict[int, str] = {}
        plan = self.file_plan(run, tuple(steps_h))
        ground, rest = plan[0], plan[1:]
        try:
            files.append(self._download(ground, dest_dir))
        except HttpError as e:
            log.warning("ICON-EU %s %s: %s", run.label, ground.label, e)
            missing = {s: f"{ground.label}: {e}" for s in steps_h}
            return FetchResult(run, area.id, Path(dest_dir), (), tuple(steps_h), missing)
        for f in rest:
            if f.step in missing:
                continue  # one of the step's files failed: the step is missing anyway
            try:
                files.append(self._download(f, dest_dir))
            except HttpError as e:
                missing[f.step] = f"{f.label}: {e}"
                log.warning("ICON-EU %s step %d %s: %s", run.label, f.step, f.label, e)
        return FetchResult(run, area.id, Path(dest_dir), tuple(files), tuple(steps_h), missing)

    def _download(self, f: IconFile, dest_dir: Path) -> FetchedFile:
        self.pacer.wait()
        d = self.http.download(self.base_url + f.path, Path(dest_dir) / f.filename)
        return FetchedFile(d.url, self.host.name, d.path, d.bytes, d.seconds, d.sha256)

    def latest_published(self, now: dt.datetime) -> RunRef | None:
        """The newest run of the last day whose last step is in DWD's listing (one GET of
        the cycle folder's ``ww/`` listing per run tried; 403 or 404 means not there).

        DWD writes the run step by step; within a step the single-level files come first
        and the pressure-level files follow within about 20 s (listing times, 2026-11-26
        12z, D76). ``fetch`` asks for the steps in order, so it reaches the last step
        minutes after its ``WW`` was listed; a file still missing then leaves its step
        missing, with the reason (D51 item 7).
        """
        last = self.model.steps_h[-1]
        start = now.replace(minute=0, second=0, microsecond=0)
        listings: dict[str, set[str]] = {}  # a cycle's folder may come up twice in 25 h
        for back in range(25):
            t = start - dt.timedelta(hours=back)
            if t.hour not in self.model.runs_utc:
                continue
            run = RunRef(self.model.id, t)
            listed = self._file(run, FOG_FIELDS["weather_code"], last, None)
            folder = listed.path.rsplit("/", 1)[0] + "/"
            if folder not in listings:
                listings[folder] = self._listing(folder)
            if listed.filename in listings[folder]:
                return run
        return None

    def _listing(self, folder: str) -> set[str]:
        self.pacer.wait()
        try:
            body = self.http.get(self.base_url + folder).body
        except HttpError as e:  # no answer at all (HttpUnavailable) is raised
            if e.status in (403, 404):
                return set()
            raise
        return set(re.findall(r'href="([^"/]+)"', body.decode("utf-8", "replace")))

    def read(self, fetched: FetchResult) -> RunFields:
        run, area_id = fetched.run, fetched.area
        if area_id not in self.areas:
            raise ValueError(f"unknown area {area_id!r}; known: {sorted(self.areas)}")
        area = self.areas[area_id]
        steps = fetched.fetched_steps
        if not steps:
            raise FormatMismatch(self.model.id, f"{run.label}: no step was fetched")
        have: dict[str, Path] = {}
        for f in fetched.files:
            name = Path(f.path).name
            if name in have:
                raise FormatMismatch(self.model.id, f"{name} twice in the fetch")
            have[name] = Path(f.path)
        plan = self.file_plan(run, steps)
        stray = sorted(set(have) - {f.filename for f in self.file_plan(run, fetched.steps_h)})
        if stray:
            raise FormatMismatch(self.model.id, f"unexpected file {stray[0]}")
        box = _box_points(self.model.grid.spacing, area.box)
        out = self._empty(len(steps), box)
        slot = {s: k for k, s in enumerate(steps)}
        levels = {p: k for k, p in enumerate(self.model.pressure_levels_hpa)}
        for f in plan:
            where = "model ground" if f.step is None else f"step {f.step}"
            if f.filename not in have:
                raise FormatMismatch(self.model.id, f"{where}: missing {f.label}")
            cut = self._decode(have[f.filename], f, run, area_id, box, where)
            target = out[_FIELD_NAMES[f.field.name]]
            if f.step is None:
                target[...] = cut
            elif f.level_hpa is None:
                target[slot[f.step]] = cut
            else:
                target[slot[f.step], ..., levels[f.level_hpa]] = cut
        out["geopotential_height_m"] /= G0  # Φ (m² s⁻²) → geopotential height (m)
        out["surface_pressure_hpa"] /= 100.0  # Pa → hPa
        t0 = np.datetime64(run.run_time.replace(tzinfo=None), "s")
        lat2, lon2 = np.meshgrid(box.lat, box.lon, indexing="ij")
        return RunFields(
            run=run,
            model=self.model,
            lat=lat2,
            lon=lon2,
            valid_times=t0 + np.array(steps, dtype="timedelta64[h]").astype("timedelta64[s]"),
            pressure_hpa=np.array(self.model.pressure_levels_hpa, dtype=float),
            level_cloud_pct=out.pop("level_cloud_pct", None),
            fog={name: out.pop(name) for name in self.model.fog_signals},
            **out,
        )

    def _empty(self, n_steps: int, box: _BoxPoints) -> dict[str, np.ndarray]:
        """NaN-filled arrays for every field, filled file by file (so a run's fields are
        held once, not stacked from copies: the whole Kongsberg box is ~1 GB)."""
        grid = (len(box.k_lat), len(box.k_lon))
        level_shape = (n_steps, *grid, len(self.model.pressure_levels_hpa))
        names = [*PROFILE_FIELDS, *(["level_cloud_pct"] if self.model.level_cloud else [])]
        out = {name: np.full(level_shape, np.nan) for name in names}
        for name in [*SINGLE_FIELDS, *self.model.fog_signals]:
            out[name] = np.full((n_steps, *grid), np.nan)
        out["model_ground_m"] = np.full(grid, np.nan)
        return out

    # -- decoding ---------------------------------------------------------------------
    def _decode(
        self, path: Path, f: IconFile, run: RunRef, area_id: str, box: _BoxPoints, where: str
    ) -> np.ndarray:
        """The one message of ``path``, checked against what ``f`` names, cut to the box."""
        import eccodes as ec

        model = self.model.id
        where = f"{where} ({f.label}, {path.name})"
        data = bz2.decompress(path.read_bytes())
        if not data:
            raise FormatMismatch(model, f"{where}: no GRIB message")
        h = ec.codes_new_from_message(data)
        try:
            if ec.codes_get_long(h, "totalLength") != len(data):
                raise FormatMismatch(model, f"{where}: more than one GRIB message")
            code = tuple(
                ec.codes_get_long(h, k)
                for k in ("discipline", "parameterCategory", "parameterNumber")
            )
            got = _surfaces(h)
            want = tuple(f.level_hpa if v == LEVEL else v for v in f.field.surfaces)
            if code != f.field.code or (got[0], got[2]) != (want[0], want[2]):
                raise FormatMismatch(
                    model,
                    f"{where}: holds {code} on surfaces {got}, expected "
                    f"{f.field.code} on surfaces {want}",
                )
            if got != want:
                what = f"{f.field.name}:{got[1]:g} hPa" if f.level_hpa is not None else got
                raise FormatMismatch(model, f"{where}: holds {what}, expected {want}")
            step_type = str(ec.codes_get(h, "stepType"))
            if step_type != "instant":
                raise FormatMismatch(model, f"{where}: {step_type}, not instantaneous")
            _check_time(h, run, 0 if f.step is None else f.step, model, where)
            return self._cut(h, area_id, box, where)
        finally:
            ec.codes_release(h)

    def _cut(self, h, area_id: str, box: _BoxPoints, where: str) -> np.ndarray:
        """The values at the box's grid points, rows north → south: kept as they are."""
        import eccodes as ec

        model, d = self.model.id, self.model.grid.spacing
        if ec.codes_get(h, "gridType") != "regular_ll":
            raise FormatMismatch(
                model, f"{where}: grid {ec.codes_get(h, 'gridType')}, not regular_ll"
            )
        if int(ec.codes_get(h, "iScansNegatively")) or int(
            ec.codes_get(h, "jPointsAreConsecutive")
        ):
            raise FormatMismatch(model, f"{where}: scan order not west → east in consecutive rows")
        ni, nj = int(ec.codes_get(h, "Ni")), int(ec.codes_get(h, "Nj"))
        dlon = float(ec.codes_get(h, "iDirectionIncrementInDegrees"))
        dlat = float(ec.codes_get(h, "jDirectionIncrementInDegrees"))
        if abs(dlon - d) > _GRID_TOL or abs(dlat - d) > _GRID_TOL:
            raise FormatMismatch(
                model, f"{where}: grid spacing {dlat:g}° × {dlon:g}°, expected {d:g}°"
            )
        north_up = int(ec.codes_get(h, "jScansPositively"))
        lat_first = float(ec.codes_get(h, "latitudeOfFirstGridPointInDegrees"))
        south = lat_first if north_up else lat_first - (nj - 1) * d
        west = (
            float(ec.codes_get(h, "longitudeOfFirstGridPointInDegrees")) + 180.0
        ) % 360.0 - 180.0
        k_south, k_west = south / d, west / d
        if abs(k_south - round(k_south)) > _GRID_TOL or abs(k_west - round(k_west)) > _GRID_TOL:
            raise FormatMismatch(
                model, f"{where}: grid starts at {south:g}° N {west:g}° E, off the {d:g}° lattice"
            )
        rows = box.k_lat - round(k_south)  # from the grid's south row
        cols = (box.k_lon - round(k_west)) % round(360.0 / d)
        if rows.min() < 0 or rows.max() >= nj or cols.max() >= ni:
            raise FormatMismatch(
                model,
                f"{where}: grid {south:g}-{south + (nj - 1) * d:g}° N × "
                f"{west:g}-{west + (ni - 1) * d:g}° E does not cover area {area_id}",
            )
        ec.codes_set(h, "missingValue", 1e20)
        vals = ec.codes_get_values(h).astype(np.float64).reshape(nj, ni)
        if not north_up:
            vals = vals[::-1]  # rows south → north, as ``rows`` counts them
        out = vals[np.ix_(rows, cols)]
        out[out == 1e20] = np.nan  # bitmap-missing points stay NaN, counted by verify_run
        return out


@dataclass(frozen=True)
class _BoxPoints:
    """The lattice points inside a box: latitudes north → south and longitudes west →
    east, and their whole multiples of the spacing (``k_lat``, ``k_lon``)."""

    k_lat: np.ndarray
    k_lon: np.ndarray
    spacing: float

    @property
    def lat(self) -> np.ndarray:
        return self.k_lat * self.spacing

    @property
    def lon(self) -> np.ndarray:
        return self.k_lon * self.spacing


def _box_points(spacing: float, box: Box) -> _BoxPoints:
    """Every lattice point inside ``box``, as ``forecast.grid.map_grid`` counts them."""
    k_north = np.floor(box.north / spacing + 1e-9)
    k_south = np.ceil(box.south / spacing - 1e-9)
    k_west = np.ceil(box.west / spacing - 1e-9)
    k_east = np.floor(box.east / spacing + 1e-9)
    return _BoxPoints(
        np.arange(k_north, k_south - 1, -1).astype(int),
        np.arange(k_west, k_east + 1).astype(int),
        spacing,
    )


def _surfaces(h) -> tuple:
    """(first type, first value, second type, second value) of a message, values in hPa
    on isobaric surfaces and ``None`` where missing (as ``Field.surfaces``)."""
    import eccodes as ec

    out: list = []
    for which in ("First", "Second"):
        kind = ec.codes_get_long(h, f"typeOf{which}FixedSurface")
        value = None
        if kind != NO_SURFACE:
            scale = ec.codes_get_long(h, f"scaleFactorOf{which}FixedSurface")
            scaled = ec.codes_get_long(h, f"scaledValueOf{which}FixedSurface")
            value = float(scaled) * 10.0 ** (-scale)
            if kind == ISOBARIC:
                value = round(value / 100.0, 6)  # Pa → hPa
        out += [kind, value]
    return tuple(out)


def _check_time(h, run: RunRef, step: int, model: str, where: str) -> None:
    import eccodes as ec

    date, hhmm = int(ec.codes_get(h, "dataDate")), int(ec.codes_get(h, "dataTime"))
    t = dt.datetime.strptime(f"{date:08d}{hhmm:04d}", "%Y%m%d%H%M").replace(tzinfo=dt.UTC)
    if t != run.run_time:
        raise FormatMismatch(model, f"{where}: run time {t:%Y-%m-%dT%H}Z, expected {run.label}")
    ec.codes_set(h, "stepUnits", 1)
    got = int(ec.codes_get(h, "endStep"))
    if got != step:
        raise FormatMismatch(model, f"{where}: step {got} h, expected {step} h")
