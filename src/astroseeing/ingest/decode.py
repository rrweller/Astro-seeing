"""Decode a verified ERA5 GRIB file into dense arrays."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class DecodedGrib:
    """Arrays on the request grid.

    ``data[short_name]`` has shape (time, level, lat, lon) for pressure-level data
    and (time, lat, lon) otherwise; float32 exactly as decoded (GRIB packing is
    coarser than float32 rounding). Levels are ordered bottom → top (1000 → 50 hPa),
    latitudes north → south, longitudes west → east (as in the GRIB file).
    """

    times: np.ndarray  # datetime64[s]
    levels: np.ndarray | None  # hPa
    lat: np.ndarray
    lon: np.ndarray
    data: dict[str, np.ndarray]

    @property
    def dims(self) -> tuple[str, ...]:
        return (
            ("time", "level", "latitude", "longitude")
            if self.levels is not None
            else ("time", "latitude", "longitude")
        )


def _axis(first: float, last: float, n: int) -> np.ndarray:
    return np.linspace(first, last, n) if n > 1 else np.array([first])


def decode_grib(path: Path, expected: dict[str, Any]) -> DecodedGrib:
    """Decode every message into its slot. Assumes ``verify_grib`` already passed."""
    import eccodes as ec

    short = list(expected["short_names"])
    levels = expected.get("levels")
    times = [dt.datetime.strptime(t, "%Y-%m-%dT%H:%M") for t in expected["times"]]
    t_index = {t.strftime("%Y-%m-%dT%H:%M"): i for i, t in enumerate(times)}
    lv_index = {int(lv): i for i, lv in enumerate(levels)} if levels else None
    g = expected["grid"]
    nlat, nlon = g["nlat"], g["nlon"]
    shape = (len(times), len(levels), nlat, nlon) if levels else (len(times), nlat, nlon)
    data = {s: np.full(shape, np.nan, dtype=np.float32) for s in short}
    filled = {s: np.zeros(shape[:-2], dtype=bool) for s in short}
    lat = lon = None

    with open(path, "rb") as f:
        while True:
            h = ec.codes_grib_new_from_file(f)
            if h is None:
                break
            try:
                if (
                    ec.codes_get(h, "iScansNegatively") != 0
                    or ec.codes_get(h, "jScansPositively") != 0
                ):
                    raise ValueError("unexpected GRIB scanning mode (expect N→S, W→E)")
                if ec.codes_get(h, "jPointsAreConsecutive") != 0:
                    raise ValueError("unexpected GRIB point order")
                sn = ec.codes_get(h, "shortName")
                d = ec.codes_get(h, "validityDate")
                tt = ec.codes_get(h, "validityTime")
                key = dt.datetime.strptime(f"{d:08d}{tt:04d}", "%Y%m%d%H%M").strftime(
                    "%Y-%m-%dT%H:%M"
                )
                ti = t_index[key]
                vals = ec.codes_get_values(h).reshape(nlat, nlon).astype(np.float32)
                if levels:
                    li = lv_index[int(ec.codes_get(h, "level"))]
                    data[sn][ti, li] = vals
                    filled[sn][ti, li] = True
                else:
                    data[sn][ti] = vals
                    filled[sn][ti] = True
                if lat is None:
                    lat = _axis(
                        ec.codes_get(h, "latitudeOfFirstGridPointInDegrees"),
                        ec.codes_get(h, "latitudeOfLastGridPointInDegrees"),
                        nlat,
                    )
                    lon = _axis(
                        ec.codes_get(h, "longitudeOfFirstGridPointInDegrees"),
                        ec.codes_get(h, "longitudeOfLastGridPointInDegrees"),
                        nlon,
                    )
            finally:
                ec.codes_release(h)

    for s in short:
        if not filled[s].all():
            raise ValueError(f"{path}: {int((~filled[s]).sum())} fields of {s} not filled")
    return DecodedGrib(
        times=np.array(times, dtype="datetime64[s]"),
        levels=np.asarray(levels, dtype=np.float64) if levels else None,
        lat=np.asarray(lat, dtype=np.float64),
        lon=np.asarray(lon, dtype=np.float64),
        data=data,
    )
