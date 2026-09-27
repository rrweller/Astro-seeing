"""Verify a downloaded GRIB file against its request (AGENTS.md "Verify before ingest").

Checks: message count; every expected (variable, level, time) present exactly once
and nothing unexpected; grid (size, first/last point, spacing); and missing/NaN
counts per variable. Values outside broad physical ranges are counted and
reported as warnings (they do not fail verification on their own).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

#: Broad sanity ranges for warnings only (units as stored in ERA5 GRIB).
SANITY_RANGES: dict[str, tuple[float, float]] = {
    "t": (150.0, 350.0),
    "u": (-150.0, 150.0),
    "v": (-150.0, 150.0),
    "cc": (-0.01, 1.01),
    "tcc": (-0.01, 1.01),
    "lcc": (-0.01, 1.01),
    "mcc": (-0.01, 1.01),
    "hcc": (-0.01, 1.01),
    "sp": (40000.0, 110000.0),
    "2t": (150.0, 350.0),
}

GRID_TOL = 1e-6

#: Variables where missing (bitmap) values are expected and do not fail
#: verification: ERA5 cloud base height has no value where there is no cloud.
#: Their counts are still recorded in the report.
MISSING_ALLOWED = frozenset({"cbh"})


@dataclass
class MessageInfo:
    short_name: str
    level: int | None
    time: str  # validity time, "%Y-%m-%dT%H:%M" UTC
    nlat: int
    nlon: int
    lat_first: float
    lat_last: float
    lon_first: float
    lon_last: float
    dlat: float
    dlon: float
    n_values: int
    n_missing: int
    n_nan: int
    vmin: float
    vmax: float


@dataclass
class VerifyReport:
    ok: bool
    path: str
    n_messages: int
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_values: dict[str, int] = field(default_factory=dict)
    nan_values: dict[str, int] = field(default_factory=dict)
    out_of_range: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _validity(h) -> str:
    import eccodes as ec

    d = ec.codes_get(h, "validityDate")
    t = ec.codes_get(h, "validityTime")
    return dt.datetime.strptime(f"{d:08d}{t:04d}", "%Y%m%d%H%M").strftime("%Y-%m-%dT%H:%M")


def scan_grib(path: Path, with_values: bool = True):
    """Yield (MessageInfo, values or None) for every message in the file."""
    import eccodes as ec

    with open(path, "rb") as f:
        while True:
            h = ec.codes_grib_new_from_file(f)
            if h is None:
                break
            try:
                level_type = ec.codes_get(h, "typeOfLevel")
                level = int(ec.codes_get(h, "level")) if level_type == "isobaricInhPa" else None
                vals = None
                n_missing = int(ec.codes_get(h, "numberOfMissing"))
                n_nan = 0
                vmin = vmax = float("nan")
                if with_values:
                    ec.codes_set(h, "missingValue", 1e20)
                    vals = ec.codes_get_values(h).astype(np.float64)
                    miss = vals == 1e20
                    vals[miss] = np.nan
                    n_nan = int(np.isnan(vals).sum()) - int(miss.sum())
                    if np.isfinite(vals).any():
                        vmin, vmax = float(np.nanmin(vals)), float(np.nanmax(vals))
                info = MessageInfo(
                    short_name=ec.codes_get(h, "shortName"),
                    level=level,
                    time=_validity(h),
                    nlat=int(ec.codes_get(h, "Nj")),
                    nlon=int(ec.codes_get(h, "Ni")),
                    lat_first=float(ec.codes_get(h, "latitudeOfFirstGridPointInDegrees")),
                    lat_last=float(ec.codes_get(h, "latitudeOfLastGridPointInDegrees")),
                    lon_first=float(ec.codes_get(h, "longitudeOfFirstGridPointInDegrees")),
                    lon_last=float(ec.codes_get(h, "longitudeOfLastGridPointInDegrees")),
                    dlat=float(ec.codes_get(h, "jDirectionIncrementInDegrees")),
                    dlon=float(ec.codes_get(h, "iDirectionIncrementInDegrees")),
                    # numberOfDataPoints = grid points; numberOfValues excludes bitmap-missing ones
                    n_values=int(ec.codes_get(h, "numberOfDataPoints")),
                    n_missing=n_missing,
                    n_nan=n_nan,
                    vmin=vmin,
                    vmax=vmax,
                )
                yield info, vals
            finally:
                ec.codes_release(h)


def _lon_eq(a: float, b: float) -> bool:
    return abs(((a - b) + 180.0) % 360.0 - 180.0) < GRID_TOL


def verify_grib(path: Path, expected: dict[str, Any], max_listed: int = 20) -> VerifyReport:
    """Check ``path`` against ``expected`` (from ``RequestSpec.expected()``)."""
    path = Path(path)
    short = list(expected["short_names"])
    levels = expected.get("levels")
    times = list(expected["times"])
    g = expected["grid"]
    want = {(v, lv, t) for v in short for lv in (levels or [None]) for t in times}

    seen: Counter[tuple] = Counter()
    grid_problems: list[str] = []
    missing = defaultdict(int)
    nans = defaultdict(int)
    oor = defaultdict(int)
    n = 0
    for info, vals in scan_grib(path):
        n += 1
        k = (info.short_name, info.level, info.time)
        seen[k] += 1
        if len(grid_problems) < max_listed:
            if (info.nlat, info.nlon) != (g["nlat"], g["nlon"]):
                grid_problems.append(
                    f"{k}: shape {(info.nlat, info.nlon)} != {(g['nlat'], g['nlon'])}"
                )
            elif not (
                abs(info.lat_first - g["lat_first"]) < GRID_TOL
                and abs(info.lat_last - g["lat_last"]) < GRID_TOL
                and _lon_eq(info.lon_first, g["lon_first"])
                and _lon_eq(info.lon_last, g["lon_last"])
                and abs(info.dlat - g["step"]) < GRID_TOL
                and abs(info.dlon - g["step"]) < GRID_TOL
            ):
                grid_problems.append(f"{k}: grid bounds/steps differ from request")
            if info.n_values != g["nlat"] * g["nlon"]:
                grid_problems.append(f"{k}: {info.n_values} values")
        missing[info.short_name] += info.n_missing
        nans[info.short_name] += info.n_nan
        if vals is not None and info.short_name in SANITY_RANGES:
            lo, hi = SANITY_RANGES[info.short_name]
            with np.errstate(invalid="ignore"):
                oor[info.short_name] += int(((vals < lo) | (vals > hi)).sum())

    rep = VerifyReport(ok=True, path=str(path), n_messages=n)
    absent = sorted(want - set(seen), key=str)
    extra = sorted(set(seen) - want, key=str)
    dupes = sorted((k for k, c in seen.items() if c > 1), key=str)
    if n != len(want):
        rep.problems.append(f"message count {n} != expected {len(want)}")
    if absent:
        rep.problems.append(f"{len(absent)} expected fields absent, e.g. {absent[:max_listed]}")
    if extra:
        rep.problems.append(f"{len(extra)} unexpected fields, e.g. {extra[:max_listed]}")
    if dupes:
        rep.problems.append(f"{len(dupes)} duplicated fields, e.g. {dupes[:max_listed]}")
    rep.problems.extend(grid_problems)
    rep.missing_values = dict(missing)
    rep.nan_values = dict(nans)
    rep.out_of_range = {k: v for k, v in oor.items() if v}
    for k, v in rep.missing_values.items():
        if v and k not in MISSING_ALLOWED:
            rep.problems.append(f"{k}: {v} missing (bitmap) values")
        elif v:
            rep.warnings.append(f"{k}: {v} missing values (expected for this variable)")
    for k, v in rep.nan_values.items():
        if v:
            rep.problems.append(f"{k}: {v} NaN values")
    for k, v in rep.out_of_range.items():
        rep.warnings.append(f"{k}: {v} values outside sanity range {SANITY_RANGES[k]}")
    rep.ok = not rep.problems
    return rep
