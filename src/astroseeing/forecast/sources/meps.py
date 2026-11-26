"""MEPS deterministic from MET Norway's THREDDS server (F1 spec Module 1; ticket #57).

MEPS (MetCoOp, 2.5 km Lambert grid, 13 pressure levels) is a regional-only model: it is
shown for the places it covers and never counted in model agreement (D45 item 3). There
is no fallback host.

**Requests** (THREDDS OPeNDAP, ``mepslatest/meps_det_2_5km_<run>.ncml``). MET Norway's
MEPS wiki says the ``latest`` files are ``ncml`` files that "can no longer be downloaded
directly, but must be accessed via OPeNDAP", an overlay "pointing to several nc files
in the background" (translated from the Norwegian of
https://github.com/metno/NWPdocs/wiki/MEPS-dataset, read 2026-11-26). So
``latest_published`` also checks that a listed run's time axis reaches the last step.
A run is fetched as:

- its attributes (``.das``): units, fill values and the Lambert projection;
- its x and y axes (``.dods?x,y``), from which the area's index window is worked out;
- the window's latitudes and longitudes;
- one request per step with every needed field in the window, cut on the server.

The window is every grid point whose projected position lies within the bounding
rectangle of the area's box in MEPS's own projection, so every point inside the box is
in it (and some just outside, near its corners).

**Reading** refuses anything other than the expected content with
:class:`FormatMismatch`: a missing or unexpected variable, another unit, fill value,
projection, grid spacing, window, pressure level, run or step. Values equal to the
fill value become NaN, which verification counts; nothing is clipped or filled here.
Grid-relative winds are turned to east and north with the projection's convergence
angle; fractions (units ``1``) become percent; geopotential becomes geopotential height
(÷ g₀); surface pressure becomes hPa.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from astroseeing.constants import G0
from astroseeing.forecast.http import HttpClient, HttpError
from astroseeing.forecast.settings import Area, Model
from astroseeing.forecast.sources.dap2 import (
    DapFormatError,
    DapVariable,
    dds_dims,
    parse_das,
    parse_dods,
)
from astroseeing.forecast.sources.interface import (
    FetchedFile,
    FetchResult,
    FormatMismatch,
    RunFields,
    RunRef,
)

log = logging.getLogger(__name__)

#: Credit beside MEPS's rows (D44 item 8), in MET Norway's own suggested wording
#: ("Credit should be given to The Norwegian Meteorological institute, shortened
#: “MET Norway” … «Based on data from MET Norway»"; data "licensed under Norwegian
#: license for public data (NLOD) and Creative Commons 4.0 BY Internasjonal",
#: https://www.met.no/en/free-meteorological-data/Licensing-and-crediting).
CREDIT = "MEPS: Based on data from MET Norway (CC BY 4.0, NLOD)"

CATALOGUE = "/thredds/catalog/mepslatest/catalog.xml"
DAP_DIR = "/thredds/dodsC/mepslatest/"

#: RunFields name → (THREDDS variable, its expected units).
LEVEL_VARS = {
    "geopotential_height_m": ("geopotential_pl", "m^2/s^2"),
    "temperature_k": ("air_temperature_pl", "K"),
    "x_wind": ("x_wind_pl", "m/s"),
    "y_wind": ("y_wind_pl", "m/s"),
}
LEVEL_CLOUD = ("cloud_area_fraction_pl", "1")
SURFACE_VARS = {
    "total_cloud_pct": ("cloud_area_fraction", "1"),
    "low_cloud_pct": ("low_type_cloud_area_fraction", "1"),
    "mid_cloud_pct": ("medium_type_cloud_area_fraction", "1"),
    "high_cloud_pct": ("high_type_cloud_area_fraction", "1"),
    "surface_pressure_hpa": ("surface_air_pressure", "Pa"),
    "model_ground_m": ("surface_geopotential", "m^2/s^2"),
}
#: Fog signals MEPS has (D49 item 3), in RunFields' vocabulary. Its low cloud
#: (``low_type_cloud_area_fraction``) is ``low_cloud_pct``.
FOG_FIELDS = {
    "fog_fraction_pct": ("fog_area_fraction", "1"),
    "visibility_m": ("visibility_in_air", "m"),
}
#: Each unit's factor to RunFields' units.
_SCALE = {"1": 100.0, "m^2/s^2": 1.0 / G0, "Pa": 0.01, "K": 1.0, "m/s": 1.0, "m": 1.0}

_RUN_RE = re.compile(r"meps_det_2_5km_(\d{8}T\d{2})Z\.ncml")
#: How far the model ground may differ between steps (float32 rounding only).
GROUND_TOLERANCE_M = 0.01
_PROJECTION_TOL_M = 1.0  # server latitude/longitude vs our projection of them
_SPACING_TOL_M = 0.5  # float32 axis values of about 1e6 m carry ~0.06 m of rounding


@dataclass(frozen=True)
class LambertConformal:
    """A spherical Lambert conformal conic projection, as CF's ``lambert_conformal_conic``
    grid mapping describes it (Snyder 1987, *Map Projections: A Working Manual*, ch. 15)."""

    standard_parallels_deg: tuple[float, float]
    central_meridian_deg: float
    origin_lat_deg: float
    earth_radius_m: float

    @property
    def cone(self) -> float:
        """The cone constant n (Snyder eq. 15-3; sin φ1 for a tangent cone)."""
        p1, p2 = (math.radians(p) for p in self.standard_parallels_deg)
        if math.isclose(p1, p2, rel_tol=0, abs_tol=1e-12):
            return math.sin(p1)
        return math.log(math.cos(p1) / math.cos(p2)) / math.log(
            math.tan(math.pi / 4 + p2 / 2) / math.tan(math.pi / 4 + p1 / 2)
        )

    def convergence_rad(self, lon_deg) -> np.ndarray:
        """The angle n(λ - λ0) by which the grid is turned against true north at each
        longitude (positive east of the central meridian)."""
        dlon = (np.asarray(lon_deg, dtype=float) - self.central_meridian_deg + 180.0) % 360.0
        return self.cone * np.radians(dlon - 180.0)

    def forward(self, lat_deg, lon_deg) -> tuple[np.ndarray, np.ndarray]:
        """Projected x and y (m) of latitudes and longitudes (Snyder eqs. 15-1 to 15-4,
        sphere; no false easting or northing)."""
        n = self.cone
        p1 = math.radians(self.standard_parallels_deg[0])
        f = math.cos(p1) * math.tan(math.pi / 4 + p1 / 2) ** n / n
        r = self.earth_radius_m

        def rho(lat_rad):
            return r * f / np.tan(np.pi / 4 + lat_rad / 2) ** n

        theta = self.convergence_rad(lon_deg)
        rho_p = rho(np.radians(np.asarray(lat_deg, dtype=float)))
        rho_0 = rho(math.radians(self.origin_lat_deg))
        return rho_p * np.sin(theta), rho_0 - rho_p * np.cos(theta)


def rotate_to_east_north(
    x_wind: np.ndarray, y_wind: np.ndarray, lon_deg: np.ndarray, projection: LambertConformal
) -> tuple[np.ndarray, np.ndarray]:
    """Turn grid-relative wind (along the projection's x and y axes) into east and north
    components. At a point turned by θ = n(λ - λ0), true east is (cos θ, sin θ) and true
    north (-sin θ, cos θ) in grid axes, so east = x cos θ + y sin θ and
    north = -x sin θ + y cos θ. ``lon_deg`` broadcasts against the winds."""
    theta = projection.convergence_rad(lon_deg)
    c, s = np.cos(theta), np.sin(theta)
    x, y = np.asarray(x_wind, dtype=float), np.asarray(y_wind, dtype=float)
    return x * c + y * s, -x * s + y * c


@dataclass(frozen=True)
class Window:
    """An index window of MEPS's grid, inclusive at both ends (rows are y, south → north)."""

    y0: int
    y1: int
    x0: int
    x1: int

    @property
    def shape(self) -> tuple[int, int]:
        return (self.y1 - self.y0 + 1, self.x1 - self.x0 + 1)

    @property
    def yx(self) -> str:
        """The constraint's last two hyperslabs, URL-encoded: ``[y0:1:y1][x0:1:x1]``."""
        return _slab(self.y0, self.y1) + _slab(self.x0, self.x1)


@dataclass(frozen=True)
class MepsRequest:
    """One OPeNDAP request: what it is for (``das``, ``axes``, ``grid`` or ``step``), the
    step (for ``step``), the path and constraint exactly as sent, and its file name."""

    kind: str
    step: int | None
    target: str
    filename: str


class MepsAdapter:
    """The MEPS source (``SourceAdapter``). ``areas`` are the settings' areas (``read``
    checks the window against the fetched area's box); ``base_url`` replaces the
    configured host (tests point it at a fake server)."""

    credit = CREDIT

    def __init__(
        self,
        model: Model,
        http: HttpClient | None,
        areas: Mapping[str, Area],
        base_url: str | None = None,
    ):
        if model.grid.kind != "lambert":
            raise ValueError(f"MEPS needs a Lambert grid, settings say {model.grid.kind}")
        unknown = sorted(set(model.fog_signals) - set(FOG_FIELDS))
        if unknown:
            raise ValueError(f"MEPS has no fog signal {unknown}; it has {sorted(FOG_FIELDS)}")
        self.model = model
        self.http = http
        self.areas = areas
        self.host = model.hosts.main
        self.base_url = (base_url or self.host.url).rstrip("/")
        self._spacing_m = model.grid.spacing * (1000.0 if model.grid.units == "km" else 1.0)
        self._variables: dict[str, tuple[str, str]] = {**LEVEL_VARS, **SURFACE_VARS}
        if model.level_cloud:
            self._variables["level_cloud_pct"] = LEVEL_CLOUD
        self._variables |= {name: FOG_FIELDS[name] for name in model.fog_signals}
        self._level_names = {v for k, (v, _) in self._variables.items()
                             if k in LEVEL_VARS or k == "level_cloud_pct"}  # fmt: skip

    # -- the request plan ---------------------------------------------------------------
    @staticmethod
    def dataset(run: RunRef) -> str:
        return f"meps_det_2_5km_{run.label}.ncml"

    def metadata_requests(self, run: RunRef) -> list[MepsRequest]:
        """The two requests every fetch makes first: attributes, then the x and y axes."""
        base, label = DAP_DIR + self.dataset(run), run.label
        return [
            MepsRequest("das", None, f"{base}.das", f"meps_{label}.das"),
            MepsRequest("axes", None, f"{base}.dods?x,y", f"meps_{label}_axes.dods"),
        ]

    def request_plan(
        self, run: RunRef, window: Window, steps_h: tuple[int, ...]
    ) -> list[MepsRequest]:
        """The window's latitudes and longitudes, then one request per step."""
        base, label = DAP_DIR + self.dataset(run), run.label
        plan = [
            MepsRequest(
                "grid",
                None,
                f"{base}.dods?latitude{window.yx},longitude{window.yx}",
                f"meps_{label}_grid.dods",
            )
        ]
        nlev = len(self.model.pressure_levels_hpa)
        for step in steps_h:
            fields = ["forecast_reference_time"]
            for var, _ in self._variables.values():
                vertical = _slab(0, nlev - 1) if var in self._level_names else _slab(0, 0)
                fields.append(f"{var}{_slab(step, step)}{vertical}{window.yx}")
            plan.append(
                MepsRequest(
                    "step",
                    step,
                    f"{base}.dods?{','.join(fields)}",
                    f"meps_{label}_f{step:03d}.dods",
                )
            )
        return plan

    def window(self, area: Area, das: Mapping[str, Any], axes: Mapping[str, DapVariable]) -> Window:
        """The index window holding every grid point inside the area's box: the points
        within the bounding rectangle of the box in MEPS's projection. The rectangle's
        corners are the box's corners, plus, where the box spans the central meridian,
        the points on its south and north edges there (where the projected parallels
        are lowest)."""
        proj = self.projection(das)
        x, y = (_axis(axes, name) for name in ("x", "y"))
        box = area.box
        lats = [box.south, box.south, box.north, box.north]
        lons = [box.west, box.east, box.west, box.east]
        if box.west <= proj.central_meridian_deg <= box.east:
            lats += [box.south, box.north]
            lons += [proj.central_meridian_deg] * 2
        px, py = proj.forward(np.array(lats), np.array(lons))
        x0, x1 = (
            int(np.searchsorted(x, px.min(), "left")),
            int(np.searchsorted(x, px.max(), "right")) - 1,
        )
        y0, y1 = (
            int(np.searchsorted(y, py.min(), "left")),
            int(np.searchsorted(y, py.max(), "right")) - 1,
        )
        if px.min() < x[0] or px.max() > x[-1] or py.min() < y[0] or py.max() > y[-1]:
            raise FormatMismatch(self.model.id, f"area {area.id}'s box reaches outside MEPS's grid")
        if x0 > x1 or y0 > y1:
            raise FormatMismatch(self.model.id, f"area {area.id}'s box holds no MEPS grid point")
        return Window(y0, y1, x0, x1)

    def projection(self, das: Mapping[str, Any]) -> LambertConformal:
        attrs = das.get("projection_lambert")
        if not isinstance(attrs, Mapping):
            raise FormatMismatch(self.model.id, "no projection_lambert attributes")
        if attrs.get("grid_mapping_name") != "lambert_conformal_conic":
            raise FormatMismatch(
                self.model.id, f"projection is {attrs.get('grid_mapping_name')!r}, "
                "expected lambert_conformal_conic"
            )  # fmt: skip
        try:
            parallels = attrs["standard_parallel"]
            parallels = tuple(parallels) if isinstance(parallels, tuple) else (parallels,) * 2
            return LambertConformal(
                (float(parallels[0]), float(parallels[1])),
                float(attrs["longitude_of_central_meridian"]),
                float(attrs["latitude_of_projection_origin"]),
                float(attrs["earth_radius"]),
            )
        except (KeyError, TypeError, ValueError, IndexError) as e:
            raise FormatMismatch(self.model.id, f"projection attributes incomplete: {e!r}") from e

    # -- SourceAdapter ------------------------------------------------------------------
    def latest_published(self, now: dt.datetime) -> RunRef | None:
        """The newest 00/06/12/18 UTC run listed in the ``mepslatest`` catalogue by
        ``now`` whose time axis already reaches the last step (a ``.dds?time`` check)."""
        body = self.http.get(self.base_url + CATALOGUE).body.decode("utf-8", errors="replace")
        runs = set()
        for label in _RUN_RE.findall(body):
            t = dt.datetime.strptime(label, "%Y%m%dT%H").replace(tzinfo=dt.UTC)
            if t.hour in self.model.runs_utc and t <= now:
                runs.add(t)
        need = self.model.steps_h[-1] + 1
        for t in sorted(runs, reverse=True):
            run = RunRef(self.model.id, t)
            try:
                dds = self.http.get(f"{self.base_url}{DAP_DIR}{self.dataset(run)}.dds?time")
            except HttpError as e:
                if e.status in (403, 404):
                    continue
                raise
            try:
                steps = dds_dims(dds.body.decode("utf-8", errors="replace")).get("time", 0)
            except DapFormatError as e:
                raise FormatMismatch(self.model.id, f"{run.label}: time axis: {e}") from e
            if steps >= need:
                return run
            log.info(
                "MEPS %s is listed with %d steps of %d: not complete yet", run.label, steps, need
            )
        return None

    def fetch(
        self, run: RunRef, area: Area, steps_h: tuple[int, ...], dest_dir: Path
    ) -> FetchResult:
        dest = Path(dest_dir)
        files: list[FetchedFile] = []

        def get(req: MepsRequest) -> Path:
            d = self.http.download(self.base_url + req.target, dest / req.filename)
            files.append(FetchedFile(d.url, self.host.name, d.path, d.bytes, d.seconds, d.sha256))
            return d.path

        try:
            das_path, axes_path = (get(r) for r in self.metadata_requests(run))
            window = self.window(area, self._das(das_path), self._dods(axes_path, "axes"))
            plan = self.request_plan(run, window, tuple(steps_h))
            get(plan[0])
        except HttpError as e:
            why = f"metadata: {e}"
            log.warning("MEPS %s: %s", run.label, why)
            return FetchResult(run, area.id, dest, tuple(files), tuple(steps_h),
                               dict.fromkeys(steps_h, why))  # fmt: skip
        missing = {}
        for req in plan[1:]:
            try:
                get(req)
            except HttpError as e:
                missing[req.step] = str(e)
                log.warning("MEPS %s step %d: %s", run.label, req.step, e)
        return FetchResult(run, area.id, dest, tuple(files), tuple(steps_h), missing)

    def read(self, fetched: FetchResult) -> RunFields:
        run, model = fetched.run, self.model.id
        steps = fetched.fetched_steps
        if not steps:
            raise FormatMismatch(model, f"{run.label}: no step was fetched")
        if fetched.area not in self.areas:
            raise ValueError(f"unknown area {fetched.area!r}; known: {sorted(self.areas)}")
        by_name = {Path(f.path).name: Path(f.path) for f in fetched.files}
        meta, axes_req = self.metadata_requests(run)
        for name in (meta.filename, axes_req.filename):
            if name not in by_name:
                raise FormatMismatch(model, f"{run.label}: no {name}")
        das = self._das(by_name[meta.filename])
        fills = self._check_attributes(das)
        proj = self.projection(das)
        axes = self._dods(by_name[axes_req.filename], "axes")
        self._check_spacing(axes)
        window = self.window(self.areas[fetched.area], das, axes)
        x = _axis(axes, "x")[window.x0 : window.x1 + 1]
        y = _axis(axes, "y")[window.y0 : window.y1 + 1]
        plan = self.request_plan(run, window, steps)
        if plan[0].filename not in by_name:
            raise FormatMismatch(model, f"{run.label}: no {plan[0].filename}")
        lat, lon = self._read_grid(by_name[plan[0].filename], proj, x, y, fetched.area)

        decoded = []
        for req in plan[1:]:
            if req.filename not in by_name:
                raise FormatMismatch(model, f"step {req.step}: no {req.filename}")
            decoded.append(self._read_step(by_name[req.filename], run, req.step, x, y, fills))
        return self._assemble(run, steps, decoded, lat, lon, proj)

    # -- reading ------------------------------------------------------------------------
    def _das(self, path: Path) -> dict[str, Any]:
        try:
            return parse_das(path.read_text(errors="replace"))
        except DapFormatError as e:
            raise FormatMismatch(self.model.id, f"{path.name}: {e}") from e

    def _dods(self, path: Path, what: str) -> dict[str, DapVariable]:
        try:
            return parse_dods(path.read_bytes())
        except DapFormatError as e:
            raise FormatMismatch(self.model.id, f"{what} ({path.name}): {e}") from e

    def _check_attributes(self, das: Mapping[str, Any]) -> dict[str, float]:
        """Every needed variable is there with its expected units; returns the fill values."""
        fills = {}
        for var, units in self._variables.values():
            attrs = das.get(var)
            if not isinstance(attrs, Mapping):
                raise FormatMismatch(self.model.id, f"attributes: missing {var}")
            if attrs.get("units") != units:
                raise FormatMismatch(
                    self.model.id, f"{var} has units {attrs.get('units')!r}, expected {units!r}"
                )
            if "_FillValue" not in attrs:
                raise FormatMismatch(self.model.id, f"{var} has no _FillValue")
            fills[var] = float(attrs["_FillValue"])
        return fills

    def _check_spacing(self, axes: Mapping[str, DapVariable]) -> None:
        for name in ("x", "y"):
            d = np.diff(_axis(axes, name))
            if d.size == 0 or not np.allclose(d, self._spacing_m, rtol=0, atol=_SPACING_TOL_M):
                raise FormatMismatch(
                    self.model.id, f"{name} axis spacing is not {self._spacing_m:g} m "
                    f"(from {d.min() if d.size else '-'} to {d.max() if d.size else '-'})"
                )  # fmt: skip

    def _read_grid(self, path, proj: LambertConformal, x, y, area: str):
        got = self._dods(path, "grid")
        out = []
        for name in ("latitude", "longitude"):
            v = got.get(name)
            if v is None:
                raise FormatMismatch(self.model.id, f"grid ({path.name}): missing {name}")
            self._check_maps(v, x, y, f"grid ({path.name}) {name}", area)
            out.append(np.asarray(v.array.values, dtype=np.float64))
        lat, lon = out
        px, py = proj.forward(lat, lon)
        off = max(np.abs(px - x[None, :]).max(), np.abs(py - y[:, None]).max())
        if not off <= _PROJECTION_TOL_M:
            raise FormatMismatch(
                self.model.id, f"the grid's latitudes and longitudes lie up to {off:.1f} m from "
                "their x and y in the stated projection"
            )  # fmt: skip
        return lat, (lon + 180.0) % 360.0 - 180.0

    def _check_maps(self, v: DapVariable, x, y, where: str, area: str) -> None:
        for name, want in (("x", x), ("y", y)):
            got = v.maps.get(name)
            if (
                got is None
                or got.values.shape != want.shape
                or not np.array_equal(got.values, want)
            ):
                raise FormatMismatch(
                    self.model.id, f"{where}: its {name} is not the window of area {area}"
                )

    def _read_step(self, path: Path, run: RunRef, step: int, x, y, fills) -> dict[str, np.ndarray]:
        model, where = self.model.id, f"step {step} ({path.name})"
        got = self._dods(path, f"step {step}")
        wanted = {var for var, _ in self._variables.values()} | {"forecast_reference_time"}
        missing = sorted(wanted - got.keys())
        if missing:
            raise FormatMismatch(model, f"{where}: missing {', '.join(missing)}")
        extra = sorted(got.keys() - wanted)
        if extra:
            raise FormatMismatch(model, f"{where}: unexpected {', '.join(extra)}")
        ref = got["forecast_reference_time"].array.values
        run_s = run.run_time.timestamp()
        if ref.shape != () or float(ref) != run_s:
            raise FormatMismatch(
                model, f"{where}: forecast_reference_time {ref}, expected {run.label}"
            )
        want_time = run_s + 3600.0 * step
        levels = np.asarray(self.model.pressure_levels_hpa, dtype=float)
        out: dict[str, np.ndarray] = {}
        for key, (var, _) in self._variables.items():
            v = got[var]
            dims = v.array.dims
            names = [d for d, _ in dims]
            self._check_maps(v, x, y, f"{where} {var}", "fetched")
            t = v.maps.get("time")
            if len(dims) != 4 or names[0] != "time" or names[2:] != ["y", "x"] or t is None:
                raise FormatMismatch(model, f"{where}: {var} has dimensions {names}")
            if t.values.shape != (1,) or float(t.values[0]) != want_time:
                raise FormatMismatch(model, f"{where}: {var} is for time {t.values.tolist()}, "
                                     f"expected step {step} h")  # fmt: skip
            vert = v.maps[names[1]].values.astype(float)
            values = np.asarray(v.array.values[0], dtype=np.float64)  # (vertical, y, x)
            values[np.asarray(v.array.values[0]) == np.float32(fills[var])] = np.nan
            if var in self._level_names:
                if names[1] != "pressure":
                    raise FormatMismatch(model, f"{where}: {var} is on {names[1]}, not pressure")
                lacking = sorted(set(levels) - set(vert), reverse=True)
                if lacking:
                    raise FormatMismatch(model, f"{where}: {var} missing level(s) "
                                         f"{', '.join(f'{p:g} hPa' for p in lacking)}")  # fmt: skip
                if len(vert) != len(levels):
                    raise FormatMismatch(model, f"{where}: {var} has levels {vert.tolist()}")
                order = [int(np.flatnonzero(vert == p)[0]) for p in levels]  # bottom → top
                values = np.moveaxis(values[order], 0, -1)  # (y, x, levels)
            else:
                if len(vert) != 1:
                    raise FormatMismatch(model, f"{where}: {var} has {len(vert)} {names[1]} values")
                values = values[0]
            out[key] = values * _SCALE[self._variables[key][1]]
        return out

    def _assemble(self, run, steps, decoded, lat, lon, proj) -> RunFields:
        def stack(key: str) -> np.ndarray:
            return np.stack([d[key] for d in decoded])

        ground = stack("model_ground_m")
        # Step 0's surface geopotential differs from the later steps' by a float32
        # rounding step (0.0015 m² s⁻², 0.15 mm, in the samples): the ground of the
        # first step read is used, and the largest difference is logged. A real change
        # of the ground between steps fails the run.
        change = np.abs(ground - ground[0])
        if np.isnan(change).any() and not np.array_equal(
            np.isnan(ground), np.broadcast_to(np.isnan(ground[0]), ground.shape)
        ):
            raise FormatMismatch(self.model.id, "surface_geopotential has NaN at some steps only")
        biggest = float(np.nanmax(change)) if np.isfinite(change).any() else 0.0
        if biggest > GROUND_TOLERANCE_M:
            raise FormatMismatch(
                self.model.id,
                f"surface_geopotential (model ground) changes between steps by up to "
                f"{biggest:.3f} m",
            )
        if biggest > 0:
            log.info("MEPS %s: model ground differs between steps by up to %.2g m (step %d's "
                     "is used)", run.label, biggest, steps[0])  # fmt: skip
        lon_levels = lon[None, :, :, None]
        u, v = rotate_to_east_north(stack("x_wind"), stack("y_wind"), lon_levels, proj)
        t0 = np.datetime64(run.run_time.replace(tzinfo=None), "s")
        return RunFields(
            run=run,
            model=self.model,
            lat=lat,
            lon=lon,
            valid_times=t0 + np.array(steps, dtype="timedelta64[h]").astype("timedelta64[s]"),
            pressure_hpa=np.array(self.model.pressure_levels_hpa, dtype=float),
            geopotential_height_m=stack("geopotential_height_m"),
            temperature_k=stack("temperature_k"),
            u_ms=u,
            v_ms=v,
            level_cloud_pct=stack("level_cloud_pct") if self.model.level_cloud else None,
            total_cloud_pct=stack("total_cloud_pct"),
            low_cloud_pct=stack("low_cloud_pct"),
            mid_cloud_pct=stack("mid_cloud_pct"),
            high_cloud_pct=stack("high_cloud_pct"),
            surface_pressure_hpa=stack("surface_pressure_hpa"),
            model_ground_m=ground[0],
            fog={name: stack(name) for name in self.model.fog_signals},
        )


def _slab(a: int, b: int) -> str:
    return f"%5B{a}:1:{b}%5D"


def _axis(axes: Mapping[str, DapVariable], name: str) -> np.ndarray:
    v = axes.get(name)
    if v is None or v.array.values.ndim != 1:
        raise FormatMismatch("meps", f"axes: missing {name}")
    return np.asarray(v.array.values, dtype=np.float64)
