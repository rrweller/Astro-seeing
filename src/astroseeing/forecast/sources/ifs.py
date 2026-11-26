"""ECMWF IFS open data, 0.25° (F1 spec Module 1; ticket #56).

The portal has one GRIB2 file per run and step, holding every open field for the whole
globe, and beside it a JSON-lines ``.index`` giving each field's byte offset and length
(``docs/research/forecast-sources.md``). There is no area cut on the server, so a step
is: one GET of the index, then one ranged GET per run of adjacent needed fields, written
together as that step's file. Only the needed fields' bytes are asked for (about 28 MB
a step of the ~120 MB file); the area is cut by ``read``, after download.

The needed fields, in the index's own names: ``gh``, ``t``, ``u``, ``v`` on the 13
levels 1000-50 hPa (the open data's 14th level, 10 hPa, is above our column's 50 hPa
top and isn't fetched); ``tcc``, ``lcc``, ``mcc``, ``hcc`` and ``sp``; ``2t`` and ``2d``
for the dewpoint-depression fog signal (D49 item 3); and the surface geopotential ``z``,
which only step 0 carries, for the model ground (``z``/g₀).

Steps are 0-48 every 3 h, all four runs a day: ``RunFields`` simply has 3-hourly valid
times, and the hours between stay absent (D44, D48 item 4).

The portal and its AWS mirror (``ecmwf-forecasts``, the fallback in the settings) lay
the files out alike, the mirror without the ``/forecasts`` prefix (``file_path``). The
adapter fetches from the main host; switching to the mirror is ticket #58 (F1-9). Here
every file is tried once, and a failed file leaves its step missing, with the reason.

``read`` identifies messages by ECMWF parameter id, level type and level, checks each
one's units, run, step and grid, and refuses anything else with :class:`FormatMismatch`:
a missing, duplicated or unexpected field, other units, another run, step or grid.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import math
import os
import tempfile
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from astroseeing.constants import G0
from astroseeing.forecast.http import HttpClient, HttpError
from astroseeing.forecast.settings import Area, Box, Host, Model
from astroseeing.forecast.sources.interface import (
    FetchedFile,
    FetchResult,
    FormatMismatch,
    RunFields,
    RunRef,
)

log = logging.getLogger(__name__)

#: Credit beside IFS's rows (D44 item 8), after ECMWF's own wording for a service
#: ("This service is based on data and products of the European Centre for Medium-Range
#: Weather Forecasts (ECMWF)", CC BY 4.0; forecast-sources.md). The full wording is in
#: the page's Data sources panel (D73 item 7).
CREDIT = "IFS: based on data and products of ECMWF (open data, CC BY 4.0)"

#: Where each configured host keeps the files (both answered on 2026-11-26).
PATH_PREFIX = {"ecmwf-opendata": "/forecasts", "aws": ""}

#: The fields read, in the index's names: ``(param, level)``, level in hPa or None.
PROFILE_PARAMS = ("gh", "t", "u", "v")
SURFACE_PARAMS = ("tcc", "lcc", "mcc", "hcc", "sp")
DEWPOINT_PARAMS = ("2t", "2d")
GROUND = ("z", None)  # surface geopotential: step 0 only
GROUND_STEP = 0

#: ECMWF parameter id → (index name, GRIB level type, units as eccodes names them),
#: read from the 2026-11-26 06z run's messages. Anything else is a format change.
PARAMETERS = {
    156: ("gh", "isobaricInhPa", "gpm"),
    130: ("t", "isobaricInhPa", "K"),
    131: ("u", "isobaricInhPa", "m s**-1"),
    132: ("v", "isobaricInhPa", "m s**-1"),
    164: ("tcc", "entireAtmosphere", "(0 - 1)"),
    186: ("lcc", "surface", "(0 - 1)"),
    187: ("mcc", "surface", "(0 - 1)"),
    188: ("hcc", "surface", "(0 - 1)"),
    134: ("sp", "surface", "Pa"),
    167: ("2t", "heightAboveGround", "K"),
    168: ("2d", "heightAboveGround", "K"),
    129: ("z", "surface", "m**2 s**-2"),
}
#: RunFields' cloud layers ← IFS's fractions (0-1 in the file, percent in RunFields).
LAYER_CLOUD = {
    "total_cloud_pct": "tcc",
    "low_cloud_pct": "lcc",
    "mid_cloud_pct": "mcc",
    "high_cloud_pct": "hcc",
}
_GRID_TOL = 1e-6


def file_name(run: RunRef, step: int, ext: str) -> str:
    """``20261126060000-48h-oper-fc.index``: the portal's name for one run and step."""
    return f"{run.run_time:%Y%m%d%H}0000-{step}h-oper-fc.{ext}"


def file_path(run: RunRef, step: int, ext: str, host: Host) -> str:
    """The path of one run and step's file on ``host`` (portal or AWS mirror)."""
    prefix = PATH_PREFIX[host.name]
    return f"{prefix}/{run.run_time:%Y%m%d}/{run.run_time:%H}z/ifs/0p25/oper/" + file_name(
        run, step, ext
    )


class IfsAdapter:
    """The IFS source (``SourceAdapter``). ``areas`` are the settings' areas (``read``
    cuts each to its box); ``base_url`` replaces the configured main host's URL (tests
    point it at a fake server)."""

    credit = CREDIT

    def __init__(
        self,
        model: Model,
        http: HttpClient | None,
        areas: Mapping[str, Area],
        base_url: str | None = None,
    ):
        if model.grid.kind != "regular_latlon":
            raise ValueError(f"IFS needs a regular lat-lon grid, settings say {model.grid.kind}")
        if model.level_cloud:
            raise ValueError("IFS open data has no cloud fraction on levels (settings say it has)")
        unknown = sorted(set(model.fog_signals) - {"dewpoint_depression_2m_k"})
        if unknown:
            raise ValueError(f"IFS has no fog signal {unknown}; it has dewpoint_depression_2m_k")
        hosts = [h for h in (model.hosts.main, model.hosts.fallback) if h is not None]
        layout = sorted(h.name for h in hosts if h.name not in PATH_PREFIX)
        if layout:
            raise ValueError(f"no IFS file layout known for host(s) {layout}")
        self.model = model
        self.http = http
        self.areas = areas
        self.host = model.hosts.main
        self.base_url = (base_url or self.host.url).rstrip("/")

    # -- what is needed ------------------------------------------------------------------
    def wanted(self, step: int) -> set[tuple[str, float | None]]:
        """The fields read from one step's file, as ``(param, level)``."""
        out = {(p, lev) for p in PROFILE_PARAMS for lev in self.model.pressure_levels_hpa}
        out |= {(p, None) for p in SURFACE_PARAMS}
        if self.model.fog_signals:
            out |= {(p, None) for p in DEWPOINT_PARAMS}
        if step == GROUND_STEP:
            out.add(GROUND)
        return out

    def url(self, run: RunRef, step: int, ext: str) -> str:
        return self.base_url + file_path(run, step, ext, self.host)

    # -- SourceAdapter --------------------------------------------------------------------
    def latest_published(self, now: dt.datetime) -> RunRef | None:
        """The newest run of the last day whose last step's index is there (one HEAD per
        run tried; a 403 or 404 means not there yet). The portal releases a run's steps
        all at once (forecast-sources.md), so the last step stands for the run."""
        last = self.model.steps_h[-1]
        start = now.replace(minute=0, second=0, microsecond=0)
        for back in range(25):
            t = start - dt.timedelta(hours=back)
            if t.hour not in self.model.runs_utc:
                continue
            run = RunRef(self.model.id, t)
            try:
                self.http.head(self.url(run, last, "index"))
            except HttpError as e:  # no answer at all (HttpUnavailable) is raised
                if e.status in (403, 404):
                    continue
                raise
            return run
        return None

    def fetch(
        self, run: RunRef, area: Area, steps_h: tuple[int, ...], dest_dir: Path
    ) -> FetchResult:
        if GROUND_STEP not in steps_h:
            raise ValueError(f"IFS steps must include {GROUND_STEP}, which alone has the ground")
        files, missing = [], {}
        for step in steps_h:
            try:
                files.append(self._fetch_step(run, step, Path(dest_dir)))
            except HttpError as e:
                missing[step] = str(e)
                log.warning("IFS %s step %d: %s", run.label, step, e)
            except FormatMismatch:
                # The index changed: the run fails loudly. Nothing it wrote is left
                # behind unrecorded (the manifest records files only from a FetchResult).
                for f in files:
                    Path(f.path).unlink(missing_ok=True)
                raise
        return FetchResult(run, area.id, Path(dest_dir), tuple(files), tuple(steps_h), missing)

    def _fetch_step(self, run: RunRef, step: int, dest_dir: Path) -> FetchedFile:
        t0 = time.monotonic()
        index_url = self.url(run, step, "index")
        rows = parse_index(self.http.get(index_url).body, self.model.id, index_url)
        ranges = self.ranges_for(rows, run, step)
        url = self.url(run, step, "grib2")
        parts = []
        for a, b in ranges:
            r = self.http.get(url, headers={"Range": f"bytes={a}-{b}"})
            if r.status != 206 or len(r.body) != b - a + 1:
                raise HttpError(url, r.status, f"asked bytes {a}-{b}, got {len(r.body)} bytes "
                                f"with HTTP {r.status}")  # fmt: skip
            parts.append(r.body)
        data = b"".join(parts)
        path = dest_dir / file_name(run, step, "grib2")
        _write_atomic(path, data)
        return FetchedFile(url, self.host.name, path, len(data), time.monotonic() - t0,
                           hashlib.sha256(data).hexdigest())  # fmt: skip

    def ranges_for(self, rows: list[dict], run: RunRef, step: int) -> list[tuple[int, int]]:
        """The byte ranges (inclusive) of the needed fields in a step's index, adjacent
        fields merged. A needed field missing from the index, listed twice, or listed
        for another run or step raises ``FormatMismatch``."""
        want = self.wanted(step)
        found: dict[tuple, tuple[int, int]] = {}
        where = f"{file_name(run, step, 'index')}"
        for row in rows:
            key = _index_key(row)
            if key not in want:
                continue
            if (row.get("date"), row.get("time"), row.get("step")) != (
                f"{run.run_time:%Y%m%d}",
                f"{run.run_time:%H}00",
                str(step),
            ):
                raise FormatMismatch(self.model.id, f"{where}: {_names([key])} is listed for "
                                     f"{row.get('date')} {row.get('time')} step "
                                     f"{row.get('step')}")  # fmt: skip
            if key in found:
                raise FormatMismatch(self.model.id, f"{where}: {_names([key])} listed twice")
            found[key] = (int(row["_offset"]), int(row["_length"]))
        absent = sorted(want - found.keys(), key=_sort_key)
        if absent:
            raise FormatMismatch(self.model.id, f"{where}: missing {_names(absent)}")
        merged: list[tuple[int, int]] = []
        for offset, length in sorted(found.values()):
            if merged and merged[-1][1] + 1 == offset:
                merged[-1] = (merged[-1][0], offset + length - 1)
            else:
                merged.append((offset, offset + length - 1))
        return merged

    def read(self, fetched: FetchResult) -> RunFields:
        run, area = fetched.run, fetched.area
        if area not in self.areas:
            raise ValueError(f"unknown area {area!r}; known: {sorted(self.areas)}")
        box = self.areas[area].box
        steps = fetched.fetched_steps
        if not steps:
            raise FormatMismatch(self.model.id, f"{run.label}: no step was fetched")
        if GROUND_STEP not in steps:
            raise FormatMismatch(self.model.id, f"{run.label}: step {GROUND_STEP}, the only "
                                 "step with the model ground (z), was not fetched")  # fmt: skip
        by_name = {Path(f.path).name: Path(f.path) for f in fetched.files}
        decoded, cut = [], None
        for step in steps:
            name = file_name(run, step, "grib2")
            if name not in by_name:
                raise FormatMismatch(self.model.id, f"step {step}: no file {name}")
            fields, cut = self._decode(by_name[name], run, step, area, box, cut)
            absent = sorted(self.wanted(step) - fields.keys(), key=_sort_key)
            if absent:
                raise FormatMismatch(self.model.id, f"step {step} ({name}): missing "
                                     f"{_names(absent)}")  # fmt: skip
            decoded.append(fields)
        lats, lons = cut.lats, cut.lons
        levels = list(self.model.pressure_levels_hpa)  # bottom → top

        def level_field(param: str) -> np.ndarray:
            return np.stack([np.stack([d[(param, p)] for p in levels], axis=-1) for d in decoded])

        def single(param: str) -> np.ndarray:
            return np.stack([d[(param, None)] for d in decoded])

        lat2, lon2 = np.meshgrid(lats, lons, indexing="ij")
        t0 = np.datetime64(run.run_time.replace(tzinfo=None), "s")
        fog = {}
        if self.model.fog_signals:
            fog["dewpoint_depression_2m_k"] = single("2t") - single("2d")
        return RunFields(
            run=run,
            model=self.model,
            lat=lat2,
            lon=lon2,
            valid_times=t0 + np.array(steps, dtype="timedelta64[h]").astype("timedelta64[s]"),
            pressure_hpa=np.array(levels),
            geopotential_height_m=level_field("gh"),
            temperature_k=level_field("t"),
            u_ms=level_field("u"),
            v_ms=level_field("v"),
            level_cloud_pct=None,
            **{name: single(param) * 100.0 for name, param in LAYER_CLOUD.items()},
            surface_pressure_hpa=single("sp") / 100.0,
            model_ground_m=decoded[steps.index(GROUND_STEP)][GROUND] / G0,
            fog=fog,
        )

    # -- decoding ---------------------------------------------------------------------
    def _decode(self, path: Path, run: RunRef, step: int, area: str, box: Box,
                cut: _Cut | None) -> tuple[dict, _Cut]:  # fmt: skip
        """Every message of one step's file, cut to the area as it is decoded (a global
        field is ~1 M values): ``{(param, level): values}``. ``cut`` is the first
        message's grid and cut; every other message must share the grid."""
        import eccodes as ec

        model, want = self.model.id, self.wanted(step)
        fields: dict[tuple, np.ndarray] = {}
        n = 0
        with open(path, "rb") as f:
            while (h := ec.codes_grib_new_from_file(f)) is not None:
                n += 1
                try:
                    where = f"step {step} ({path.name}) message {n}"
                    key = _message_key(h, model, where)
                    if key not in want:
                        raise FormatMismatch(model, f"{where}: unexpected {_names([key])}")
                    if key in fields:
                        raise FormatMismatch(model, f"{where}: {_names([key])} twice")
                    _check_time(h, run, step, model, where)
                    grid = _grid(h)
                    if cut is None:
                        cut = self._cut(grid, area, box)
                    elif grid != cut.grid:
                        raise FormatMismatch(model, f"{where}: grid {grid} differs from "
                                             f"{cut.grid}")  # fmt: skip
                    fields[key] = _values(h, grid)[np.ix_(cut.rows, cut.cols)]
                finally:
                    ec.codes_release(h)
        if n == 0:
            raise FormatMismatch(model, f"step {step}: {path.name} holds no GRIB message")
        return fields, cut

    def _cut(self, grid: tuple, area: str, box: Box) -> _Cut:
        """Rows and columns of the grid points inside the area's box (rows north → south,
        columns west → east), and their latitudes and longitudes. The cut must hold every
        point of the model's spacing inside the box, or it's a format change."""
        model, spacing = self.model.id, self.model.grid.spacing
        if grid[0] != "regular_ll":
            raise FormatMismatch(model, f"grid type {grid[1]!r}, not regular_ll")
        _, nj, ni, lat0, lon0, dlat, dlon = grid
        if abs(dlat - spacing) > _GRID_TOL or abs(dlon - spacing) > _GRID_TOL:
            raise FormatMismatch(model, f"grid spacing {dlat}° × {dlon}°, not {spacing:g}°")
        lats = lat0 - dlat * np.arange(nj)
        lons = (lon0 + dlon * np.arange(ni) + 180.0) % 360.0 - 180.0
        rows = np.flatnonzero((lats >= box.south - 1e-9) & (lats <= box.north + 1e-9))
        cols = np.flatnonzero((lons >= box.west - 1e-9) & (lons <= box.east + 1e-9))
        cols = cols[np.argsort(lons[cols], kind="stable")]
        want_lats, want_lons = box_points(box, spacing)
        if not (
            len(rows) == len(want_lats)
            and len(cols) == len(want_lons)
            and np.allclose(lats[rows], want_lats, atol=_GRID_TOL)
            and np.allclose(lons[cols], want_lons, atol=_GRID_TOL)
        ):
            raise FormatMismatch(model, f"the grid ({nj} × {ni} points from {lat0}° N "
                                 f"{lon0}° E) does not hold every {spacing:g}° point of "
                                 f"area {area}")  # fmt: skip
        return _Cut(grid, rows, cols, want_lats, want_lons)


@dataclass(frozen=True, eq=False)
class _Cut:
    """A source grid and the rows and columns of it inside an area's box."""

    grid: tuple
    rows: np.ndarray
    cols: np.ndarray
    lats: np.ndarray  # north → south
    lons: np.ndarray  # west → east


def box_points(box: Box, spacing: float) -> tuple[np.ndarray, np.ndarray]:
    """The latitudes (north → south) and longitudes (west → east) of every point of a
    regular grid of ``spacing`` (aligned on multiples of it) inside ``box``."""
    north = math.floor(box.north / spacing + 1e-9) * spacing
    south = math.ceil(box.south / spacing - 1e-9) * spacing
    west = math.ceil(box.west / spacing - 1e-9) * spacing
    east = math.floor(box.east / spacing + 1e-9) * spacing
    lats = north - spacing * np.arange(round((north - south) / spacing) + 1)
    lons = west + spacing * np.arange(round((east - west) / spacing) + 1)
    return lats, lons


def _message_key(h, model: str, where: str) -> tuple[str, float | None]:
    """``(param, level)`` of a message, after checking its level type, units and that
    it is an instantaneous value."""
    import eccodes as ec

    pid = ec.codes_get(h, "paramId", int)
    if pid not in PARAMETERS:
        raise FormatMismatch(model, f"{where}: unknown field (ECMWF parameter {pid}, "
                             f"{ec.codes_get(h, 'shortName')})")  # fmt: skip
    param, level_type, units = PARAMETERS[pid]
    got_type, got_units = ec.codes_get(h, "typeOfLevel"), ec.codes_get(h, "units")
    if got_type != level_type:
        raise FormatMismatch(model, f"{where}: {param} on {got_type}, expected {level_type}")
    if got_units != units:
        raise FormatMismatch(model, f"{where}: {param} in {got_units!r}, expected {units!r}")
    step_type = ec.codes_get(h, "stepType")
    if step_type != "instant":
        raise FormatMismatch(model, f"{where}: {param} is {step_type}, expected instant")
    if level_type == "isobaricInhPa":
        return (param, float(ec.codes_get(h, "level", float)))
    return (param, None)


def _check_time(h, run: RunRef, step: int, model: str, where: str) -> None:
    import eccodes as ec

    date, hhmm = ec.codes_get(h, "dataDate", int), ec.codes_get(h, "dataTime", int)
    t = dt.datetime.strptime(f"{date:08d}{hhmm:04d}", "%Y%m%d%H%M").replace(tzinfo=dt.UTC)
    if t != run.run_time:
        raise FormatMismatch(model, f"{where}: run time {t:%Y-%m-%dT%H}Z, expected {run.label}")
    ec.codes_set(h, "stepUnits", 1)
    if int(ec.codes_get(h, "endStep")) != step:
        raise FormatMismatch(model, f"{where}: step {ec.codes_get(h, 'endStep')} h, "
                             f"expected {step} h")  # fmt: skip


def _grid(h) -> tuple:
    """("regular_ll", Nj, Ni, north latitude, first longitude, Δlat, Δlon), rows north →
    south and columns eastward, as the portal sends them; another layout is refused."""
    import eccodes as ec

    kind = ec.codes_get(h, "gridType")
    if kind != "regular_ll":
        return ("not regular_ll", kind)
    if (
        int(ec.codes_get(h, "iScansNegatively"))
        or int(ec.codes_get(h, "jScansPositively"))
        or int(ec.codes_get(h, "jPointsAreConsecutive"))
    ):
        return ("scan order", "not north → south in rows west → east")
    return (
        "regular_ll",
        int(ec.codes_get(h, "Nj")),
        int(ec.codes_get(h, "Ni")),
        float(ec.codes_get(h, "latitudeOfFirstGridPointInDegrees")),
        float(ec.codes_get(h, "longitudeOfFirstGridPointInDegrees")),
        float(ec.codes_get(h, "jDirectionIncrementInDegrees")),
        float(ec.codes_get(h, "iDirectionIncrementInDegrees")),
    )


def _values(h, grid: tuple) -> np.ndarray:
    import eccodes as ec

    ec.codes_set(h, "missingValue", 1e20)
    vals = ec.codes_get_values(h).astype(np.float64)
    vals[vals == 1e20] = np.nan  # bitmap-missing points stay NaN, counted by verify_run
    return vals.reshape(grid[1], grid[2])


def parse_index(body: bytes, model: str, url: str) -> list[dict]:
    """The JSON-lines ``.index``: one object per field, with ``_offset`` and ``_length``."""
    rows = []
    for n, line in enumerate(body.decode().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            int(row["_offset"]), int(row["_length"]), row["param"], row["levtype"]
            if row["levtype"] == "pl":
                float(row["levelist"])
        except (ValueError, KeyError, TypeError) as e:
            raise FormatMismatch(model, f"{url} line {n}: not an index entry ({e})") from e
        rows.append(row)
    return rows


def _index_key(row: Mapping) -> tuple[str, float | None] | None:
    if row["levtype"] == "pl":
        return (row["param"], float(row["levelist"]))
    if row["levtype"] == "sfc":
        return (row["param"], None)
    return None  # soil levels and the like: never read


def _sort_key(key: tuple) -> tuple:
    return (key[0], -1.0 if key[1] is None else -key[1])


def _names(keys: Iterable[tuple]) -> str:
    return ", ".join(p if lev is None else f"{p}:{lev:g} hPa" for p, lev in keys)


def _write_atomic(path: Path, data: bytes) -> None:
    """Temp file in the same folder, fsync, rename: nothing half-written at ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


__all__ = ["CREDIT", "IfsAdapter", "box_points", "file_name", "file_path", "parse_index"]
