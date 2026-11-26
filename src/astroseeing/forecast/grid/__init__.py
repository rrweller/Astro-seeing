"""The map grid (F1 spec Module 4, D60 item 2): each map cell takes its family's nearest
grid point (fixed south-west tie rule); nothing is averaged or interpolated, and seeing is
always computed from J after assignment.

Ticket #51 adds the two pieces the first slice needs: :func:`map_grid` (the grid
``latest.json`` describes) and :func:`nearest_point` (the grid point a saved place
takes). Assigning whole fields to the map grid is ticket #65 (F1-16).
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


def map_grid(area: Area, model: Model) -> MapGrid:
    """The grid points of ``model`` (the area's map-grid model) inside the area's box.

    Assumes the model's points lie on whole multiples of its spacing, which holds for
    GFS and IFS (0.25°) and ICON-EU (0.0625°; 29.5° N and 23.5° W are multiples of it).
    Ticket #65 checks this against ICON-EU's own files.
    """
    if model.grid.kind != "regular_latlon":
        raise ValueError(f"{model.id}: a map grid needs a regular lat-lon model")
    d, box = model.grid.spacing, area.box
    north = math.floor(box.north / d + 1e-9) * d
    south = math.ceil(box.south / d - 1e-9) * d
    west = math.ceil(box.west / d - 1e-9) * d
    east = math.floor(box.east / d + 1e-9) * d
    return MapGrid(north, west, d, d, round((north - south) / d) + 1, round((east - west) / d) + 1)


def nearest_point(
    lat: np.ndarray, lon: np.ndarray, at_lat: float, at_lon: float
) -> tuple[int, int]:
    """Index (row, column) of the grid point nearest to (``at_lat``, ``at_lon``) on a
    regular grid (2-D ``lat``, ``lon``). Exactly halfway between points, the point to the
    south-west wins (spec Module 4's tie rule)."""
    lats, lons = np.asarray(lat)[:, 0], np.asarray(lon)[0, :]
    dlat = np.abs(lats - at_lat)
    dlon = np.abs((lons - at_lon + 180.0) % 360.0 - 180.0)
    # among equally near points take the southernmost row and the westernmost column
    i = min(np.flatnonzero(np.isclose(dlat, dlat.min(), rtol=0, atol=1e-9)), key=lambda k: lats[k])
    j = min(
        np.flatnonzero(np.isclose(dlon, dlon.min(), rtol=0, atol=1e-9)),
        key=lambda k: (lons[k] - at_lon + 180.0) % 360.0 - 180.0,
    )
    return int(i), int(j)
