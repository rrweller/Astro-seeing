"""The map grid and a place's nearest grid point (F1 spec Module 4; ticket #51)."""

from __future__ import annotations

import numpy as np

from astroseeing.forecast.grid import map_grid, nearest_point
from astroseeing.forecast.settings import load_settings


def test_the_kongsberg_map_grid_is_icon_eus_160_by_160_cells():
    s = load_settings()
    g = map_grid(s.areas["kongsberg"], s.models["icon_eu"])
    # the spec's example latest.json: 64.625° N, 4.6875° E, 0.0625°, 160 × 160
    assert (g.lat_north, g.lon_west, g.dlat, g.nlat, g.nlon) == (64.625, 4.6875, 0.0625, 160, 160)


def test_a_place_takes_its_nearest_point_and_ties_go_south_west():
    lat, lon = np.meshgrid([60.0, 59.75, 59.5], [9.5, 9.75, 10.0], indexing="ij")
    assert nearest_point(lat, lon, 59.669, 9.652) == (1, 1)  # Kongsberg → 59.75° N 9.75° E
    assert nearest_point(lat, lon, 59.625, 9.875) == (2, 1)  # halfway both ways: SW point
    assert nearest_point(lat, lon, 59.7, 9.875) == (1, 1)


def test_on_a_turned_grid_a_place_takes_the_point_nearest_on_the_sphere():
    # a projected grid (MEPS's Lambert) has neither rows of one latitude nor columns of
    # one longitude: rows here run 0.01° north per 0.05° east
    rows, cols = np.meshgrid(np.arange(3), np.arange(3), indexing="ij")
    lat = 59.6 + 0.03 * rows + 0.01 * cols
    lon = 9.6 + 0.05 * cols - 0.01 * rows
    assert nearest_point(lat, lon, 59.669, 9.652) == (2, 1)  # 59.67° N 9.63° E
    assert nearest_point(lat, lon, lat[0, 2], lon[0, 2]) == (0, 2)
    # 59.655° N 9.668° E: the first row's and column's values alone point to (2, 1),
    # but (1, 2) at 59.65° N 9.69° E is nearer than (2, 1) at 59.67° N 9.63° E
    assert nearest_point(lat, lon, 59.655, 9.668) == (1, 2)
