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
