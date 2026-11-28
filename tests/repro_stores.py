"""Synthetic ERA5 Zarr stores for the reproduction reader's tests (roadmap C9, D66).

Stores are written through the real ingest path (``prepare`` → ``write_store_atomic``),
in either layout, so the reader is tested against exactly what the CT has on the NAS:
geopotential (m² s⁻²) not height, float32, levels bottom → top, latitudes north →
south, and for the ``cells`` layout only the cells a mask keeps.

The default fields are the 1976 standard atmosphere and the idealised jet of
``astroseeing.synthetic``; tests replace any variable with an analytic function of
(time, pressure, latitude, longitude) to get known answers.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from astroseeing.constants import G0
from astroseeing.ingest.decode import DecodedGrib
from astroseeing.ingest.store import prepare, write_store_atomic
from astroseeing.synthetic import (
    ERA5_LEVELS_HPA,
    jet_wind,
    std_atmosphere_height,
    std_atmosphere_temperature,
)

#: f(t_unix, p_hpa, lat, lon) → values; arguments broadcast as (time, level, lat, lon).
Field = Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray], np.ndarray]


def hourly(start: str, n: int, step_h: int = 1) -> np.ndarray:
    """``n`` UTC times from ``start`` (ISO), ``step_h`` hours apart, as datetime64[s]."""
    t0 = np.datetime64(start, "s")
    return t0 + np.arange(n) * np.timedelta64(step_h * 3600, "s")


def _std_z(t, p, la, lo):
    return std_atmosphere_height(
        np.broadcast_to(p, np.broadcast_shapes(t.shape, p.shape, la.shape, lo.shape))
    )


def _std_t(t, p, la, lo):
    return std_atmosphere_temperature(_std_z(t, p, la, lo)) + 0.01 * la


def _std_u(t, p, la, lo):
    return jet_wind(_std_z(t, p, la, lo))[0] + 0.01 * lo


def _std_v(t, p, la, lo):
    return jet_wind(_std_z(t, p, la, lo))[1] + 0.01 * la


DEFAULT_FIELDS: dict[str, Field] = {"z": _std_z, "t": _std_t, "u": _std_u, "v": _std_v}


def _grid(times, levels, lat, lon):
    t = (np.asarray(times, "datetime64[s]").astype(np.int64)).astype(np.float64)
    return (
        t[:, None, None, None],
        np.asarray(levels, float)[None, :, None, None],
        np.asarray(lat, float)[None, None, :, None],
        np.asarray(lon, float)[None, None, None, :],
    )


def write_pl_store(
    path: Path,
    *,
    times: np.ndarray,
    lat: Sequence[float],
    lon: Sequence[float],
    levels: Sequence[float] = ERA5_LEVELS_HPA,
    fields: dict[str, Field] | None = None,
    cc: Field | None = None,
    cells: np.ndarray | None = None,
) -> Path:
    """A pressure-level store. ``fields["z"]`` gives geopotential *height* in metres
    (stored as geopotential, ×g₀, as ERA5 does). ``cells`` (bool, lat × lon) selects
    the ``cells`` layout."""
    f = {**DEFAULT_FIELDS, **(fields or {})}
    if cc is not None:
        f["cc"] = cc
    tt, pp, la, lo = _grid(times, levels, lat, lon)
    shape = (tt.shape[0], pp.shape[1], la.shape[2], lo.shape[3])
    data = {}
    for name, fn in f.items():
        vals = np.broadcast_to(np.asarray(fn(tt, pp, la, lo), dtype=np.float64), shape)
        if name == "z":
            vals = vals * G0
        data[name] = np.ascontiguousarray(vals, dtype=np.float32)
    dec = DecodedGrib(
        times=np.asarray(times, "datetime64[s]"),
        levels=np.asarray(levels, dtype=np.float64),
        lat=np.asarray(lat, dtype=np.float64),
        lon=np.asarray(lon, dtype=np.float64),
        data=data,
    )
    attrs = {"layout": "cells" if cells is not None else "grid"}
    return write_store_atomic(Path(path), prepare(dec, cells), attrs).path


def write_static_store(
    path: Path,
    *,
    lat: Sequence[float],
    lon: Sequence[float],
    orography_m: float | Callable[[np.ndarray, np.ndarray], np.ndarray] = 0.0,
    cells: np.ndarray | None = None,
) -> Path:
    """A static store (z as geopotential, lsm), one time, like ``static_request``'s."""
    la = np.asarray(lat, float)[:, None]
    lo = np.asarray(lon, float)[None, :]
    oro = orography_m(la, lo) if callable(orography_m) else np.full((la.size, lo.size), orography_m)
    oro = np.broadcast_to(np.asarray(oro, float), (la.size, lo.size))
    dec = DecodedGrib(
        times=np.array(["2023-01-01T00:00"], "datetime64[s]"),
        levels=None,
        lat=np.asarray(lat, dtype=np.float64),
        lon=np.asarray(lon, dtype=np.float64),
        data={
            "z": (oro * G0)[None].astype(np.float32),
            "lsm": np.ones((1, la.size, lo.size), np.float32),
        },
    )
    attrs = {"layout": "cells" if cells is not None else "grid"}
    return write_store_atomic(Path(path), prepare(dec, cells), attrs).path


def axis(first: float, n: int, step: float = 0.25) -> np.ndarray:
    """``n`` grid values from ``first`` in ``step`` (negative for north → south)."""
    return first + step * np.arange(n)
