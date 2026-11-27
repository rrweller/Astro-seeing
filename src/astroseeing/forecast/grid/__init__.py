"""The map grid (F1 spec Module 4, D60 item 2): each map cell takes its family's nearest
grid point (fixed south-west tie rule); nothing is averaged or interpolated, and seeing is
always computed from J after assignment.

Ticket #51 adds the two pieces the first slice needs: :func:`map_grid` (the grid
``latest.json`` describes) and :func:`nearest_point` (the grid point a saved place
takes). Ticket #65 (F1-16) adds :func:`to_map_grid`, which assigns whole fields of a
regular source grid (GFS, IFS, ICON-EU) to the map grid by the same rule, each axis on
its own: a map cell centre exactly halfway between two source points takes the
southern row and the western column (D86).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from astroseeing.forecast.settings import Area, Model


@dataclass(frozen=True)
class MapGrid:
    """A regular lat-lon grid, row-major, north to south, west to east."""

    lat_north: float
    lon_west: float
    dlat: float
    dlon: float
    nlat: int
    nlon: int

    @property
    def lats(self) -> np.ndarray:
        """The cell-centre latitudes, north to south."""
        return self.lat_north - self.dlat * np.arange(self.nlat)

    @property
    def lons(self) -> np.ndarray:
        """The cell-centre longitudes, west to east."""
        return self.lon_west + self.dlon * np.arange(self.nlon)


@dataclass(frozen=True, eq=False)
class SourceGrid:
    """A regular source grid: its rows' latitudes and its columns' longitudes, in the
    source's own order (rows may run either way)."""

    lats: np.ndarray
    lons: np.ndarray

    @classmethod
    def from_fields(cls, lat: np.ndarray, lon: np.ndarray) -> SourceGrid:
        """From an adapter's 2-D ``lat`` and ``lon``; refuses a turned (projected) grid,
        which has no rows of one latitude (MEPS is not on the map, D60 item 2)."""
        lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
        if lat.ndim != 2 or lat.shape != lon.shape:
            raise ValueError(f"need 2-D lat and lon of one shape, got {lat.shape}, {lon.shape}")
        if not (np.all(lat == lat[:, :1]) and np.all(lon == lon[:1, :])):
            raise ValueError("the map grid takes values from a regular lat-lon grid only")
        return cls(lat[:, 0].copy(), lon[0, :].copy())


def map_grid(area: Area, model: Model) -> MapGrid:
    """The grid points of ``model`` (the area's map-grid model) inside the area's box.

    Assumes the model's points lie on whole multiples of its spacing, which holds for
    GFS and IFS (0.25°) and ICON-EU (0.0625°; 29.5° N and 23.5° W are multiples of it).
    The ICON-EU adapter checks it on every file it reads (D76 item 4).
    """
    if model.grid.kind != "regular_latlon":
        raise ValueError(f"{model.id}: a map grid needs a regular lat-lon model")
    d, box = model.grid.spacing, area.box
    north = math.floor(box.north / d + 1e-9) * d
    south = math.ceil(box.south / d - 1e-9) * d
    west = math.ceil(box.west / d - 1e-9) * d
    east = math.floor(box.east / d + 1e-9) * d
    return MapGrid(north, west, d, d, round((north - south) / d) + 1, round((east - west) / d) + 1)


def to_map_grid(values: np.ndarray, source: SourceGrid, grid: MapGrid) -> np.ndarray:
    """``values`` (``(..., rows, columns)`` on ``source``) assigned to the map grid:
    ``(..., grid.nlat, grid.nlon)``, north to south, west to east.

    Each map cell takes the value of its nearest source point, each axis on its own;
    exactly halfway between two points, the southern row and the western column win
    (spec Module 4's tie rule, the same as :func:`nearest_point`). Nothing is averaged,
    interpolated or filled: every value is one of the source's own, NaN included. A map
    cell farther than half a source spacing from the source's outermost point is not
    covered by it, and is refused rather than given the edge value.
    """
    values = np.asarray(values)
    if values.shape[-2:] != (source.lats.size, source.lons.size):
        raise ValueError(f"values of shape {values.shape} don't fit the source grid "
                         f"{source.lats.size} × {source.lons.size}")  # fmt: skip
    rows = _nearest_on_axis(source.lats, grid.lats, "latitude", wrap=False)
    cols = _nearest_on_axis(source.lons, grid.lons, "longitude", wrap=True)
    return values[..., rows[:, None], cols[None, :]]


def _nearest_on_axis(src: np.ndarray, want: np.ndarray, name: str, wrap: bool) -> np.ndarray:
    """For each ``want`` coordinate, the index of the nearest ``src`` coordinate; among
    equally near ones the southern (western) one. Longitudes are compared on the circle."""
    if src.size < 2:
        raise ValueError(f"a source grid needs at least two points along {name}")
    diff = want[:, None] - src[None, :]
    if wrap:
        diff = (diff + 180.0) % 360.0 - 180.0
    dist = np.abs(diff)
    spacing = np.min(np.abs(np.diff(np.sort(src))))
    best = dist.min(axis=1)
    far = best > spacing / 2 + _TIE_DEG
    if far.any():
        raise ValueError(f"the source grid does not cover map {name}s {want[far].tolist()}: "
                         f"its nearest point is more than half a spacing away")  # fmt: skip
    out = np.empty(want.size, dtype=np.intp)
    for k in range(want.size):
        ties = np.flatnonzero(np.abs(dist[k] - best[k]) <= _TIE_DEG)
        # the southern (western) point lies below ``want``: the most negative offset
        out[k] = min(ties, key=lambda i: -diff[k, i])
    return out


#: Coordinates this close (degrees) count as equal, as in :func:`nearest_point`.
_TIE_DEG = 1e-9


def nearest_point(
    lat: np.ndarray, lon: np.ndarray, at_lat: float, at_lon: float
) -> tuple[int, int]:
    """Index (row, column) of the grid point nearest to (``at_lat``, ``at_lon``) (2-D
    ``lat``, ``lon``). Exactly halfway between points, the point to the south-west wins
    (spec Module 4's tie rule).

    On a regular grid (rows of one latitude, columns of one longitude) each axis is
    taken on its own. On a projected grid (MEPS's Lambert) it is the point nearest on
    the sphere (smallest chord), ties going to the southernmost, then westernmost point.
    """
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    regular = np.all(lat == lat[:, :1]) and np.all(lon == lon[:1, :])
    if not regular:
        return _nearest_on_sphere(lat, lon, at_lat, at_lon)
    lats, lons = lat[:, 0], lon[0, :]
    dlat = np.abs(lats - at_lat)
    dlon = np.abs((lons - at_lon + 180.0) % 360.0 - 180.0)
    # among equally near points take the southernmost row and the westernmost column
    i = min(np.flatnonzero(np.isclose(dlat, dlat.min(), rtol=0, atol=1e-9)), key=lambda k: lats[k])
    j = min(
        np.flatnonzero(np.isclose(dlon, dlon.min(), rtol=0, atol=1e-9)),
        key=lambda k: (lons[k] - at_lon + 180.0) % 360.0 - 180.0,
    )
    return int(i), int(j)


def _nearest_on_sphere(lat, lon, at_lat: float, at_lon: float) -> tuple[int, int]:
    def unit(la, lo):
        la, lo = np.radians(la), np.radians(lo)
        return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], -1)

    chord = np.linalg.norm(unit(lat, lon) - unit(at_lat, at_lon), axis=-1)
    ties = np.argwhere(np.isclose(chord, chord.min(), rtol=0, atol=1e-12))
    i, j = min(ties, key=lambda ij: (lat[tuple(ij)], (lon[tuple(ij)] - at_lon + 180.0) % 360.0))
    return int(i), int(j)
