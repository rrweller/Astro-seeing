"""Land mask (terrain/landmask.py): buffer geometry, aggregation to ERA5 cells, and the
real GLOBE mask (decisions D20, D22)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from astroseeing.ingest.store import Prepared, read_store, write_store_atomic
from astroseeing.qc import QCCounts
from astroseeing.terrain import landmask as lm

R = lm.MEAN_EARTH_RADIUS_M


def haversine_m(lat1, lon1, lat2, lon2, r=R):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2, float) - np.asarray(lon1, float))
    h = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(np.clip(h, 0.0, 1.0)))


def nearest_point(lat, lon, clat, clon, dlat, dlon):
    """Nearest point of the cell centred at (clat, clon): latitude and longitude clamped."""
    plat = np.clip(lat, clat - dlat / 2, clat + dlat / 2)
    d = np.clip((np.asarray(lon) - clon + 180.0) % 360.0 - 180.0, -dlon / 2, dlon / 2)
    return plat, clon + d


def distance_to_cell(lat, lon, clat, clon, dlat, dlon, measure):
    if measure == "centre":
        return haversine_m(lat, lon, clat, clon)
    plat, plon = nearest_point(lat, lon, clat, clon, dlat, dlon)
    return haversine_m(lat, lon, plat, plon)


def brute_force_buffer(land, lat_c, lon_c, buffer_m, measure):
    dlat, dlon = abs(lat_c[1] - lat_c[0]), 360.0 / lon_c.size
    la, lo = np.meshgrid(lat_c, lon_c, indexing="ij")
    src_lat, src_lon = la[land], lo[land]
    out = land.copy()
    for i, j in zip(*np.nonzero(~land), strict=True):
        d = distance_to_cell(lat_c[i], lon_c[j], src_lat, src_lon, dlat, dlon, measure)
        out[i, j] = bool((d <= buffer_m).any())
    return out


def coarse_grid(deg):
    lat = 90.0 - (np.arange(round(180 / deg)) + 0.5) * deg
    lon = -180.0 + (np.arange(round(360 / deg)) + 0.5) * deg
    return lat, lon


# --- Buffer geometry -------------------------------------------------------------------


@settings(max_examples=40, deadline=None)
@given(
    seed=st.integers(0, 2**32 - 1),
    density=st.floats(0.005, 0.15),
    buffer_km=st.floats(0.0, 3500.0),
    measure=st.sampled_from(lm.MEASURES),
)
def test_buffer_matches_brute_force_on_coarse_globe(seed, density, buffer_km, measure):
    """10° cells: buffers of up to ~3 rows, wrap-around in longitude and across the poles."""
    lat, lon = coarse_grid(10.0)
    land = np.random.default_rng(seed).random((lat.size, lon.size)) < density
    got = lm.buffer_mask(land, lat, buffer_km * 1e3, R, measure=measure)
    want = brute_force_buffer(land, lat, lon, buffer_km * 1e3, measure)
    assert np.array_equal(got, want)


def test_buffer_zero_is_land_and_grows_with_distance():
    lat, lon = coarse_grid(5.0)
    land = np.random.default_rng(1).random((lat.size, lon.size)) < 0.05
    assert np.array_equal(lm.buffer_mask(land, lat, 0.0, R), land)
    small = lm.buffer_mask(land, lat, 400e3, R)
    large = lm.buffer_mask(land, lat, 900e3, R)
    assert (small >= land).all() and (large >= small).all() and large.sum() > small.sum()
    # The literal ("edge") buffer contains the centre-to-centre one.
    assert (lm.buffer_mask(land, lat, 900e3, R, measure="edge") >= large).all()


def test_buffer_counts_added_cells():
    lat, lon = coarse_grid(10.0)
    land = np.zeros((lat.size, lon.size), bool)
    land[9, 0] = True  # one cell just south of the equator
    qc = QCCounts()
    out = lm.buffer_mask(land, lat, 1200e3, R, qc=qc)  # 10° ≈ 1112 km: the 4 neighbours
    assert qc["landmask_buffer_cells_added"] == int(out.sum()) - 1 == 4


GLOBE_LAT, _ = lm.globe_centres()
GLOBE_DLAT = GLOBE_DLON = 1 / lm.GLOBE_CELLS_PER_DEG
REACH = {m: lm.row_reach(GLOBE_LAT, GLOBE_DLON, 1000.0, R, m) for m in lm.MEASURES}
NCOLS = lm.GLOBE_SHAPE[1]


def reach_distance(i, di, dj, measure):
    """Distance from the centre of GLOBE cell (i, 0) to cell (i + di, dj)."""
    return distance_to_cell(
        GLOBE_LAT[i],
        0.0,
        GLOBE_LAT[i + di],
        dj * GLOBE_DLON,
        GLOBE_DLAT,
        GLOBE_DLON,
        measure,
    )


@settings(max_examples=300, deadline=None)
@given(
    i=st.integers(0, lm.GLOBE_SHAPE[0] - 1),
    di=st.sampled_from([-1, 0, 1]),
    measure=st.sampled_from(lm.MEASURES),
)
def test_row_reach_is_tight_on_the_globe_grid(i, di, measure):
    """reach is the largest column offset within 1 km, for every row of the 30″ grid."""
    assert set(REACH[measure]) == {-1, 0, 1}  # 1 km never reaches two rows away
    r = int(REACH[measure][di][i])
    if not 0 <= i + di < lm.GLOBE_SHAPE[0]:
        assert r == -1
        return
    if r < 0:
        assert reach_distance(i, di, 0, measure) > 1000.0
    elif r >= NCOLS // 2:
        assert reach_distance(i, di, NCOLS // 2, measure) <= 1000.0
    else:
        assert reach_distance(i, di, r, measure) <= 1000.0 < reach_distance(i, di, r + 1, measure)


def test_row_reach_known_values():
    eq = 10799  # centre 0.00417° N
    assert [int(REACH["centre"][d][eq]) for d in (-1, 0, 1)] == [0, 1, 0]  # 4-neighbours
    assert [int(REACH["edge"][d][eq]) for d in (-1, 0, 1)] == [1, 1, 1]  # 8-neighbours
    lat60 = 30 * lm.GLOBE_CELLS_PER_DEG  # centre 59.996° N: cells 463 m wide
    assert int(REACH["centre"][0][lat60]) == 2
    assert int(REACH["centre"][0][0]) >= NCOLS // 2  # next to the pole: the whole row


# --- Aggregation to ERA5 cells ---------------------------------------------------------


def test_cell_counts_totals_and_poles():
    ones = np.ones((180 * 4, 360 * 4), bool)
    got = lm.cell_counts(ones, 0.5, cells_per_deg=4)
    assert np.array_equal(got, lm.cells_per_coarse_cell(0.5, cells_per_deg=4))
    assert got[0, 0] == got[-1, 0] == 2 and got[1, 0] == 4
    assert got.sum() == ones.size


@settings(max_examples=100, deadline=None)
@given(i=st.integers(0, 180 * 4 - 1), j=st.integers(0, 360 * 4 - 1))
def test_cell_counts_put_each_fine_cell_in_the_cell_around_its_centre(i, j):
    lat_c, lon_c = lm.globe_centres(cells_per_deg=4)
    fine = np.zeros((lat_c.size, lon_c.size), bool)
    fine[i, j] = True
    got = lm.cell_counts(fine, 0.5, cells_per_deg=4)
    iy, ix = lm.cell_index(lat_c[i], lon_c[j], 0.5)
    assert got.sum() == 1 and got[iy, ix] == 1


def test_era5_cell_edges_fall_on_globe_cell_edges():
    """ERA5 row 0 holds GLOBE rows 0–14; column 0 (0° E) holds columns 21585–21614."""
    fine = np.zeros(lm.GLOBE_SHAPE, bool)
    fine[14, 21585] = fine[15, 21585] = True  # 89.879° / 89.871° N at 0.1208° W
    fine[20000, 21584] = True  # 0.1292° W: belongs to 359.75° E
    fine[20000, 43199] = True  # 179.996° E: belongs to 180° E (column 720)
    got = lm.cell_counts(fine, 0.25)
    row_20000 = int(np.floor((90 - lm.globe_centres()[0][20000]) / 0.25 + 0.5))
    assert got[0, 0] == 1 and got[1, 0] == 1
    assert got[row_20000, 1439] == 1 and got[row_20000, 720] == 1
    assert got.sum() == 4


def test_grid_point_index_and_era5_cell_mask():
    keep = np.zeros(lm.grid_shape(0.25), bool)
    iy, ix = lm.cell_index(-24.63, -70.40, 0.25)  # Paranal: nearest point -24.75, -70.5
    keep[iy, ix] = True
    lat = np.array([-24.5, -24.75])
    west = np.array([-70.5, -70.25])
    east = np.mod(west, 360.0)
    a = lm.era5_cell_mask(lat, west, keep)
    b = lm.era5_cell_mask(lat, east, keep)
    assert np.array_equal(a, b) and a.sum() == 1
    with pytest.raises(ValueError, match=r"not on the 0\.25° grid"):
        lm.era5_cell_mask(np.array([-24.6]), west, keep)


def test_store_round_trip_with_integer_and_bool_arrays(tmp_path):
    """The Zarr writer stores counts and masks (fill value 0/False, not NaN)."""
    lat = np.array([1.0, 0.0])
    lon = np.array([0.0, 1.0, 2.0])
    prep = Prepared(
        dims=("latitude", "longitude"),
        coords={"latitude": (("latitude",), lat), "longitude": (("longitude",), lon)},
        data={
            "n": np.arange(6, dtype=np.uint16).reshape(2, 3),
            "keep": np.array([[True, False, True], [False, False, True]]),
        },
        qc=QCCounts(),
    )
    res = write_store_atomic(tmp_path / "m.zarr", prep, {"x": 1})
    arrays, attrs = read_store(res.path)
    assert arrays["n"].dtype == np.uint16 and arrays["keep"].dtype == np.bool_
    assert np.array_equal(arrays["keep"], prep.data["keep"])
    assert attrs["content_sha256"] == prep.content_sha256()


# --- The real GLOBE mask (slow: ~1 GB arrays) -------------------------------------------


@pytest.fixture(scope="module")
def built():
    return lm.build(buffer_m=1000.0, grid_deg=0.25, measure="edge")


@pytest.mark.slow
@settings(max_examples=200, deadline=None)
@given(lat=st.floats(-89.99, 89.99), lon=st.floats(-179.99, 179.99))
def test_our_land_array_agrees_with_the_package_lookup(lat, lon):
    from global_land_mask import globe

    land, _ = _land()
    i = int((90.0 - lat) * lm.GLOBE_CELLS_PER_DEG)
    j = int((lon + 180.0) * lm.GLOBE_CELLS_PER_DEG)
    assert bool(land[i, j]) == bool(globe.is_land(lat, lon))


_LAND_CACHE: dict = {}


def _land():
    if "land" not in _LAND_CACHE:
        _LAND_CACHE["land"] = lm.load_globe_land()
    return _LAND_CACHE["land"]


@pytest.mark.slow
def test_golden_counts(built):
    """Golden values (2026-09-27, global-land-mask 1.0.0, 1 km "edge" buffer; D20, D22)."""
    s = built.summary()
    assert s["globe_land_area_fraction"] == pytest.approx(0.2890527, abs=1e-7)
    assert s["globe_land_or_buffer_area_fraction"] == pytest.approx(0.2913121, abs=1e-7)
    assert s["era5_cells_with_land"] == 365_100
    assert s["era5_cells_kept"] == 366_604
    assert built.source["version"] == "1.0.0"
    assert built.source["sha256"] == (
        "ef089657594dcdd5bff443b96a24e6fa094fa65fd08c6cd1d7c8368ed6bcbeeb"
    )


@pytest.mark.slow
def test_sites_and_islands(built):
    sites = {
        "paranal": (-24.63, -70.40),
        "mauna_kea_13n": (19.8330, -155.4810),
        "la_palma": (28.7572, -17.8851),
        "timau": (-9.5971, 123.9472),
        "lenghu": (38.61, 93.89),
        "dome_c": (-75.10, 123.33),
        "south_pole": (-89.99, 0.0),
        "tristan_da_cunha": (-37.11, -12.28),
        "easter_island": (-27.12, -109.35),
        "lord_howe": (-31.55, 159.08),
    }
    s = built.summary(sites)["sites"]
    assert all(v["globe_land"] and v["era5_cell_kept"] for v in s.values()), s
    ocean = built.summary({"open_pacific": (0.0, -140.0), "ross_ice_shelf": (-81.5, -175.0)})
    assert not any(v["era5_cell_kept"] for v in ocean["sites"].values())


@pytest.mark.slow
def test_buffer_contains_land_and_only_adds_near_coast(built):
    assert (built.land_or_buffer >= built.land).all()
    assert (built.buffer_cells >= built.land_cells).all()
    assert (built.buffer_cells <= built.total_cells).all()
    # Every added cell touches land within one row and a few columns (1 km).
    added = built.land_or_buffer & ~built.land
    rows, cols = np.nonzero(added[5000:5010])  # a band at ~48° N
    for r, c in zip(rows[:500] + 5000, cols[:500], strict=True):
        win = built.land[r - 1 : r + 2, max(0, c - 3) : c + 4]
        assert win.any()
