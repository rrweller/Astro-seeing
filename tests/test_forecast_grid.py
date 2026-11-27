"""The map grid and a place's nearest grid point (F1 spec Module 4; ticket #51)."""

from __future__ import annotations

import numpy as np
import pytest

from astroseeing.forecast.grid import MapGrid, SourceGrid, map_grid, nearest_point, to_map_grid
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


# -- whole fields onto the map grid (ticket #65) ------------------------------------------


def _coarse(lats, lons):
    """A regular source grid as an adapter gives it (2-D lat and lon)."""
    return np.meshgrid(np.asarray(lats, float), np.asarray(lons, float), indexing="ij")


def test_map_cells_exactly_between_coarse_points_take_the_south_west_point():
    # map cells every 0.0625° on 59.6875-59.9375 N × 9.6875-9.9375 E; a 0.25° source
    # at 59.75/60.0 N × 9.75/10.0 E: 59.875 and 9.875 lie exactly halfway between points
    grid = MapGrid(59.9375, 9.6875, 0.0625, 0.0625, 5, 5)
    lat, lon = _coarse([60.0, 59.75], [9.75, 10.0])  # rows north to south, as GFS cuts
    values = np.array([[1, 2], [3, 4]])  # 1: 60.0 N 9.75 E … 4: 59.75 N 10.0 E
    got = to_map_grid(values, SourceGrid.from_fields(lat, lon), grid)
    # map rows (north → south) 59.9375, 59.875, 59.8125, 59.75, 59.6875 take source rows
    # 60.0, 59.75 (tie: south), 59.75, 59.75, 59.75; map columns 9.6875, 9.75, 9.8125,
    # 9.875 (tie: west) take 9.75 and 9.9375 takes 10.0
    expected = np.array(
        [
            [1, 1, 1, 1, 2],
            [3, 3, 3, 3, 4],
            [3, 3, 3, 3, 4],
            [3, 3, 3, 3, 4],
            [3, 3, 3, 3, 4],
        ]
    )
    np.testing.assert_array_equal(got, expected)


def test_the_tie_rule_holds_whichever_way_the_source_rows_run():
    grid = MapGrid(59.9375, 9.6875, 0.0625, 0.0625, 5, 5)
    north_first = _coarse([60.0, 59.75], [9.75, 10.0])
    south_first = _coarse([59.75, 60.0], [9.75, 10.0])
    a = to_map_grid(np.array([[1, 2], [3, 4]]), SourceGrid.from_fields(*north_first), grid)
    b = to_map_grid(np.array([[3, 4], [1, 2]]), SourceGrid.from_fields(*south_first), grid)
    np.testing.assert_array_equal(a, b)


def test_leading_axes_are_kept_and_values_are_assigned_never_averaged():
    grid = MapGrid(59.9375, 9.6875, 0.0625, 0.0625, 5, 5)
    lat, lon = _coarse([60.0, 59.75], [9.75, 10.0])
    steps = np.array([[[0.5, 7.25], [33.0, np.nan]], [[1.0, 2.0], [3.0, 4.0]]])
    got = to_map_grid(steps, SourceGrid.from_fields(lat, lon), grid)
    assert got.shape == (2, 5, 5)
    # every map value is one of the source's own values (NaN stays NaN: never filled)
    assert set(np.unique(got[0][~np.isnan(got[0])])) <= {0.5, 7.25, 33.0}
    assert np.isnan(got[0, 1:, 4]).all() and not np.isnan(got[0, :, :4]).any()


def test_a_source_on_the_map_grid_itself_maps_one_to_one():
    s = load_settings()
    grid = map_grid(s.areas["kongsberg"], s.models["icon_eu"])
    lats = grid.lat_north - grid.dlat * np.arange(grid.nlat)
    lons = grid.lon_west + grid.dlon * np.arange(grid.nlon)
    lat, lon = _coarse(lats[::-1], lons)  # ICON-EU's rows run south to north
    values = np.arange(grid.nlat * grid.nlon, dtype=float).reshape(grid.nlat, grid.nlon)
    got = to_map_grid(values, SourceGrid.from_fields(lat, lon), grid)
    np.testing.assert_array_equal(got, values[::-1])


def test_gfs_shows_as_blocks_of_four_by_four_map_cells_on_the_kongsberg_box():
    s = load_settings()
    area = s.areas["kongsberg"]
    grid = map_grid(area, s.models["icon_eu"])
    gfs = map_grid(area, s.models["gfs"])  # the GFS points inside the box
    lat, lon = _coarse(gfs.lat_north - 0.25 * np.arange(gfs.nlat),
                       gfs.lon_west + 0.25 * np.arange(gfs.nlon))  # fmt: skip
    ids = np.arange(gfs.nlat * gfs.nlon).reshape(gfs.nlat, gfs.nlon)
    got = to_map_grid(ids, SourceGrid.from_fields(lat, lon), grid)
    # interior blocks are 4 × 4 cells (the box edges hold the remainder)
    _, counts = np.unique(got, return_counts=True)
    assert (counts == 16).sum() >= (gfs.nlat - 2) * (gfs.nlon - 2)
    assert got.shape == (160, 160) and set(np.unique(got)) == set(ids.ravel())


def test_a_map_cell_the_source_does_not_cover_is_refused_not_filled():
    grid = MapGrid(60.25, 9.6875, 0.0625, 0.0625, 6, 5)  # reaches 0.25° north of the source
    lat, lon = _coarse([60.0, 59.75], [9.75, 10.0])
    with pytest.raises(ValueError, match="does not cover"):
        to_map_grid(np.zeros((2, 2)), SourceGrid.from_fields(lat, lon), grid)


def test_a_turned_source_grid_is_refused():
    rows, cols = np.meshgrid(np.arange(3), np.arange(3), indexing="ij")
    lat = 59.6 + 0.03 * rows + 0.01 * cols
    lon = 9.6 + 0.05 * cols - 0.01 * rows
    with pytest.raises(ValueError, match="regular"):
        SourceGrid.from_fields(lat, lon)
