"""Land mask: GLOBE 30″ land plus a 1 km buffer, and the ERA5 0.25° cells it touches.

AGENTS.md "Coverage: land plus a 1 km buffer"; source chosen in decision D20.

**Source.** ``global-land-mask`` 1.0.0 (MIT) packs NOAA GLOBE v1.0 as a boolean
ocean mask: the unrestricted "G.O.O.D." tiles (``*10g``) with GLOBE's ocean flag
(−500) as ocean and everything else, lakes included, as land. GLOBE is
cell-registered at 30″: 21 600 × 43 200 cells, row ``i`` spanning latitudes
[90 − (i+1)/120, 90 − i/120] and column ``j`` longitudes [−180 + j/120,
−180 + (j+1)/120]. GLOBE's own tile header (``a10g.hdr``: ULXMAP −179.995833,
ULYMAP 89.995833) puts the upper-left cell centre half a cell in from the corner.
The package stores the cells' north and west edges as its ``lat``/``lon`` axes, so
its truncating lookup returns the cell that contains a point;
:func:`load_globe_land` checks those axes before trusting the array.

**Buffer.** A 30″ cell is in the buffer if the great-circle distance between its
centre and the centre of some land cell is at most ``buffer_m``, on a sphere with
the WGS84 mean radius (2a + b)/3. Rows two or more apart are at least 2 × 926.6 m
apart, so a 1 km buffer only reaches the rows directly above and below; along a
row it spans 1 cell at the equator, 2 at 60°, 6 at 80°, and whole rows near the
poles (where the distance through the pole is short).

**ERA5 cells.** The 0.25° grid of 721 × 1440 points (latitudes 90 … −90,
longitudes 0 … 359.75). Each point's cell is the 0.25° box centred on it, clipped
at the poles (0.125° tall there). Box edges fall on GLOBE cell edges (0.125° = 15
cells), so an ERA5 cell holds exactly 30 × 30 GLOBE cells (15 × 30 at the poles).
A cell is kept if it holds at least one land-or-buffer GLOBE cell.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from astroseeing.qc import QCCounts

GLOBE_CELLS_PER_DEG = 120
GLOBE_SHAPE = (180 * GLOBE_CELLS_PER_DEG, 360 * GLOBE_CELLS_PER_DEG)

#: WGS84 defining parameters (semi-major axis a, flattening f) and the mean radius
#: R1 = (2a + b)/3 used for buffer distances.
WGS84_A = 6_378_137.0
WGS84_F = 1 / 298.257223563
MEAN_EARTH_RADIUS_M = (2 * WGS84_A + WGS84_A * (1 - WGS84_F)) / 3

#: GLOBE documentation manual, Section 3.A (papers/globe_documentation.pdf, NOAA NGDC).
GLOBE_CITATION = (
    "GLOBE Task Team and others (Hastings, David A., Paula K. Dunbar, Gerald M. Elphingstone, "
    "Mark Bootz, Hiroshi Murakami, Hiroshi Maruyama, Hiroshi Masaharu, Peter Holland, John "
    "Payne, Nevin A. Bryant, Thomas L. Logan, J.-P. Muller, Gunter Schreier, and John S. "
    "MacDonald), eds., 1999. The Global Land One-kilometer Base Elevation (GLOBE) Digital "
    "Elevation Model, Version 1.0. National Oceanic and Atmospheric Administration, National "
    "Geophysical Data Center. doi:10.7289/V52R3PMS"
)
LAND_MASK_SOURCE_NOTE = (
    "Land = GLOBE v1.0 unrestricted (G.O.O.D.) tiles, ocean flag -500 as sea, via the "
    "global-land-mask Python package (MIT licence, https://github.com/toddkarin/"
    "global-land-mask). Lakes count as land; floating ice shelves count as sea."
)


def globe_centres(cells_per_deg: int = GLOBE_CELLS_PER_DEG) -> tuple[np.ndarray, np.ndarray]:
    """Cell-centre latitudes (north → south) and longitudes (west → east), degrees."""
    nrows, ncols = 180 * cells_per_deg, 360 * cells_per_deg
    lat = 90.0 - (np.arange(nrows) + 0.5) / cells_per_deg
    lon = -180.0 + (np.arange(ncols) + 0.5) / cells_per_deg
    return lat, lon


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_globe_land() -> tuple[np.ndarray, dict[str, Any]]:
    """GLOBE land (True) at 30″ from ``global-land-mask``, plus source details.

    Raises if the package's array or axes are not the cell-registered GLOBE grid
    described in the module docstring.
    """
    from importlib import metadata

    import global_land_mask

    npz = Path(global_land_mask.__file__).parent / "globe_combined_mask_compressed.npz"
    with np.load(npz) as z:
        ocean, lat_edges, lon_edges = z["mask"], z["lat"], z["lon"]
    if ocean.shape != GLOBE_SHAPE or ocean.dtype != np.bool_:
        raise ValueError(f"unexpected mask {ocean.shape} {ocean.dtype}; expected {GLOBE_SHAPE}")
    nrows, ncols = GLOBE_SHAPE
    want_lat = 90.0 - np.arange(nrows) / GLOBE_CELLS_PER_DEG
    want_lon = -180.0 + np.arange(ncols) / GLOBE_CELLS_PER_DEG
    if not (
        np.allclose(lat_edges, want_lat, rtol=0, atol=1e-9)
        and np.allclose(lon_edges, want_lon, rtol=0, atol=1e-9)
    ):
        raise ValueError("global-land-mask axes are not the GLOBE north/west cell edges")
    info = {
        "package": "global-land-mask",
        "version": metadata.version("global-land-mask"),
        "file": npz.name,
        "sha256": sha256_file(npz),
    }
    return np.logical_not(ocean), info


# --- Buffer ------------------------------------------------------------------------


MEASURES = ("centre", "edge")


def row_reach(
    lat_centres_deg: np.ndarray,
    dlon_deg: float,
    buffer_m: float,
    radius_m: float,
    measure: str = "centre",
) -> dict[int, np.ndarray]:
    """For each row offset ``di``, the largest column offset within ``buffer_m``, per row.

    ``reach[di][i]`` is the largest ``dj ≥ 0`` such that cell (i + di, j ± dj) is
    within ``buffer_m`` of the centre of cell (i, j); −1 if no cell of row ``i + di``
    is (or that row does not exist); ``ncols // 2`` or more means the whole row.
    Longitudes are uniformly spaced by ``dlon_deg`` and wrap around; rows are
    uniformly spaced in latitude.

    ``measure``: ``"centre"`` measures to the other cell's centre; ``"edge"`` to its
    nearest point (the cell as an area: its latitude and longitude clamped to the
    cell's edges), i.e. "within ``buffer_m`` of land" taken literally.
    """
    if measure not in MEASURES:
        raise ValueError(f"measure must be one of {MEASURES}")
    lat = np.radians(np.asarray(lat_centres_deg, float))
    nrows = lat.size
    ncols = round(360 / dlon_deg)
    theta = buffer_m / radius_m
    h_max = np.sin(theta / 2) ** 2
    dlon = np.radians(dlon_deg)
    edge = measure == "edge"
    half_row = abs(lat[1] - lat[0]) / 2 if (edge and nrows > 1) else 0.0

    def lat_gap(phi1: np.ndarray, phi2: np.ndarray) -> np.ndarray:
        """Latitude difference from phi1 to the nearest latitude of the row at phi2."""
        return np.maximum(np.abs(phi1 - phi2) - half_row, 0.0)

    # Rows are monotone in latitude, so the meridional gap grows with |di|: stop at
    # the first offset where no pair of rows is within reach.
    kmax = 0
    while kmax + 1 < nrows and (lat_gap(lat[kmax + 1 :], lat[: -(kmax + 1)]) <= theta).any():
        kmax += 1
    out: dict[int, np.ndarray] = {}
    for di in range(-kmax, kmax + 1):
        i = np.arange(max(0, -di), min(nrows, nrows - di))
        phi1, phi2 = lat[i], lat[i + di]
        gap = lat_gap(phi1, phi2)
        # Latitude of the nearest point of the other row (phi1 itself when di == 0).
        phi_near = phi1 - np.sign(phi1 - phi2) * gap
        rem = h_max - np.sin(gap / 2) ** 2
        x = rem / (np.cos(phi1) * np.cos(phi_near))
        reach = np.full(nrows, -1, dtype=np.int64)
        r = np.full(i.size, -1, dtype=np.int64)
        whole = x >= 1
        part = (rem >= 0) & ~whole
        r[whole] = ncols
        # Largest longitude difference to the nearest point that stays within reach;
        # for "edge" the nearest point of column dj is (dj - 1/2) columns away.
        cols = 2 * np.arcsin(np.sqrt(x[part])) / dlon + (0.5 if edge else 0.0)
        r[part] = np.floor(cols * (1 + 1e-12)).astype(np.int64)
        reach[i] = np.minimum(r, ncols)
        out[di] = reach
    return out


def _runs(values: np.ndarray) -> list[tuple[int, int, int]]:
    """(start, stop, value) for each run of equal values."""
    edges = np.flatnonzero(np.diff(values)) + 1
    starts = np.concatenate(([0], edges))
    stops = np.concatenate((edges, [values.size]))
    return [(int(a), int(b), int(values[a])) for a, b in zip(starts, stops, strict=True)]


def buffer_mask(
    land: np.ndarray,
    lat_centres_deg: np.ndarray,
    buffer_m: float,
    radius_m: float = MEAN_EARTH_RADIUS_M,
    measure: str = "centre",
    qc: QCCounts | None = None,
    block_rows: int = 2048,
) -> np.ndarray:
    """Land plus every cell whose centre is within ``buffer_m`` of a land cell.

    ``land`` is (nrows, ncols) on a grid with the given row-centre latitudes and
    ``ncols`` uniformly spaced longitudes covering 360° (columns wrap around).
    ``measure`` is as in :func:`row_reach`.
    """
    from scipy.ndimage import maximum_filter1d

    land = np.ascontiguousarray(land, dtype=bool)
    nrows, ncols = land.shape
    if len(lat_centres_deg) != nrows:
        raise ValueError("one latitude per row expected")
    src = land.view(np.uint8)
    out = land.copy()
    reaches = row_reach(lat_centres_deg, 360 / ncols, buffer_m, radius_m, measure)
    for di, reach in reaches.items():
        for a, b, r in _runs(reach):
            if r < 0:
                continue
            for s in range(a, b, block_rows):
                e = min(b, s + block_rows)
                rows = src[s + di : e + di]
                if 2 * r + 1 >= ncols:
                    out[s:e] |= rows.any(axis=1)[:, None]
                elif r == 0:
                    out[s:e] |= rows.view(bool)
                else:
                    dil = maximum_filter1d(rows, size=2 * r + 1, axis=1, mode="wrap")
                    out[s:e] |= dil.view(bool)
    if qc is not None:
        qc.add("landmask_buffer_cells_added", int(out.sum() - land.sum()), out.size)
    return out


# --- Aggregation to a coarser grid ---------------------------------------------------


def grid_shape(grid_deg: float) -> tuple[int, int]:
    """(nlat, nlon) of a regular grid with points on multiples of ``grid_deg``, poles included."""
    return round(180 / grid_deg) + 1, round(360 / grid_deg)


def grid_axes(grid_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """ERA5-style axes: latitudes 90 → −90 and longitudes 0 → 360 − ``grid_deg``."""
    nlat, nlon = grid_shape(grid_deg)
    return 90.0 - grid_deg * np.arange(nlat), grid_deg * np.arange(nlon)


def cell_counts(
    mask: np.ndarray, grid_deg: float, cells_per_deg: int = GLOBE_CELLS_PER_DEG
) -> np.ndarray:
    """Number of True fine cells inside each coarse cell (box centred on each grid point).

    ``mask`` is the full global fine grid (north → south rows from 90°, columns from
    −180°). Returns (nlat, nlon) counts on the :func:`grid_axes` layout.
    """
    nrows, ncols = mask.shape
    if (nrows, ncols) != (180 * cells_per_deg, 360 * cells_per_deg):
        raise ValueError(f"mask {mask.shape} is not a global {cells_per_deg}-per-degree grid")
    f = grid_deg * cells_per_deg
    if abs(f - round(f)) > 1e-9 or round(f) % 2:
        raise ValueError("coarse cell edges must fall on fine cell edges (even ratio)")
    f = round(f)
    half = f // 2
    nlat, nlon = grid_shape(grid_deg)
    # Rolled column c is original column (c + shift) % ncols; coarse cell m (longitude
    # m·grid_deg) then covers rolled columns [m·f, (m+1)·f).
    shift = ncols // 2 - half
    out = np.zeros((nlat, nlon), dtype=np.int64)
    for k in range(nlat):
        r0, r1 = max(0, k * f - half), min(nrows, k * f + half)
        band = np.roll(mask[r0:r1], -shift, axis=1)
        out[k] = band.reshape(r1 - r0, nlon, f).sum(axis=(0, 2), dtype=np.int64)
    return out


def cell_index(lat: np.ndarray, lon: np.ndarray, grid_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Row/column of the grid cell containing each point (east-positive longitudes)."""
    nlat, nlon = grid_shape(grid_deg)
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    if np.any(np.abs(lat) > 90):
        raise ValueError("latitude outside [-90, 90]")
    iy = np.floor((90.0 - lat) / grid_deg + 0.5).astype(np.int64)
    ix = np.floor(np.mod(lon, 360.0) / grid_deg + 0.5).astype(np.int64) % nlon
    return np.clip(iy, 0, nlat - 1), ix


def grid_point_index(
    lat: np.ndarray, lon: np.ndarray, grid_deg: float, tol: float = 1e-6
) -> tuple[np.ndarray, np.ndarray]:
    """Like :func:`cell_index`, but every point must lie on the grid (e.g. GRIB axes)."""
    iy, ix = cell_index(lat, lon, grid_deg)
    glat, glon = grid_axes(grid_deg)
    off_lat = np.abs(glat[iy] - np.asarray(lat, float))
    off_lon = np.abs((glon[ix] - np.mod(np.asarray(lon, float), 360.0) + 180.0) % 360.0 - 180.0)
    if np.any(off_lat > tol) or np.any(off_lon > tol):
        raise ValueError(f"points are not on the {grid_deg}° grid")
    return iy, ix


def cells_per_coarse_cell(grid_deg: float, cells_per_deg: int = GLOBE_CELLS_PER_DEG) -> np.ndarray:
    """Fine cells inside each coarse cell: f × f, or f/2 × f in the polar rows."""
    f = round(grid_deg * cells_per_deg)
    out = np.full(grid_shape(grid_deg), f * f, dtype=np.int64)
    out[0] = out[-1] = f * (f // 2)
    return out


def fine_cell_area_fraction(cells_per_deg: int = GLOBE_CELLS_PER_DEG) -> np.ndarray:
    """Area of one fine cell in each row, as a fraction of the sphere (rows north → south)."""
    nrows = 180 * cells_per_deg
    top = np.radians(90.0 - np.arange(nrows) / cells_per_deg)
    bottom = np.radians(90.0 - (np.arange(nrows) + 1) / cells_per_deg)
    dlon = np.radians(1.0 / cells_per_deg)
    return dlon * (np.sin(top) - np.sin(bottom)) / (4 * np.pi)


# --- Build ---------------------------------------------------------------------------


@dataclass
class LandMask:
    """Everything :func:`build` computes; arrays on the GLOBE and ERA5 grids."""

    land: np.ndarray  # (21600, 43200) bool, GLOBE land
    land_or_buffer: np.ndarray  # (21600, 43200) bool
    land_cells: np.ndarray  # (721, 1440) count of GLOBE land cells per ERA5 cell
    buffer_cells: np.ndarray  # (721, 1440) count of land-or-buffer GLOBE cells
    total_cells: np.ndarray  # (721, 1440) GLOBE cells per ERA5 cell (900; 450 at the poles)
    keep: np.ndarray  # (721, 1440) bool, ERA5 cells kept
    config: dict[str, Any]
    source: dict[str, Any]
    qc: QCCounts

    def summary(self, sites: dict[str, tuple[float, float]] | None = None) -> dict[str, Any]:
        rows_area = fine_cell_area_fraction()
        land_area = float((self.land.sum(axis=1) * rows_area).sum())
        buf_area = float((self.land_or_buffer.sum(axis=1) * rows_area).sum())
        glat, _ = grid_axes(self.config["grid_deg"])
        kept = int(self.keep.sum())
        out: dict[str, Any] = {
            "globe_land_area_fraction": land_area,
            "globe_land_or_buffer_area_fraction": buf_area,
            "globe_cells_land": int(self.land.sum()),
            "globe_cells_added_by_buffer": int(self.land_or_buffer.sum() - self.land.sum()),
            "era5_cells_total": int(self.keep.size),
            "era5_cells_with_land": int((self.land_cells > 0).sum()),
            "era5_cells_kept": kept,
            "era5_cells_kept_fraction": kept / self.keep.size,
            "era5_cells_kept_south_of_60S": int(self.keep[glat < -60].sum()),
        }
        for g in (0.5, 1.0):
            c = cell_counts(self.land_or_buffer, g)
            out[f"cells_kept_at_{g}deg"] = int((c > 0).sum())
        if sites:
            out["sites"] = {}
            for name, (la, lo) in sites.items():
                i = min(int((90.0 - la) * GLOBE_CELLS_PER_DEG), GLOBE_SHAPE[0] - 1)
                j = min(int((lo + 180.0) * GLOBE_CELLS_PER_DEG), GLOBE_SHAPE[1] - 1)
                iy, ix = cell_index(np.array([la]), np.array([lo]), self.config["grid_deg"])
                out["sites"][name] = {
                    "globe_land": bool(self.land[i, j]),
                    "globe_land_or_buffer": bool(self.land_or_buffer[i, j]),
                    "era5_cell_kept": bool(self.keep[iy[0], ix[0]]),
                    "era5_cell_land_cells": int(self.land_cells[iy[0], ix[0]]),
                }
        return out


def build(buffer_m: float = 1000.0, grid_deg: float = 0.25, measure: str = "centre") -> LandMask:
    """GLOBE land, its buffer, and the per-ERA5-cell counts (~10 s, ~3 GB RAM)."""
    qc = QCCounts()
    land, source = load_globe_land()
    lat_c, _ = globe_centres()
    radius = MEAN_EARTH_RADIUS_M
    lob = buffer_mask(land, lat_c, buffer_m, radius, measure=measure, qc=qc)
    land_cells = cell_counts(land, grid_deg)
    buffer_cells = cell_counts(lob, grid_deg)
    total = cells_per_coarse_cell(grid_deg)
    keep = buffer_cells > 0
    qc.add("landmask_era5_cells_kept", int(keep.sum()), keep.size)
    qc.add("landmask_era5_cells_kept_only_by_buffer", int((keep & (land_cells == 0)).sum()))
    config = {
        "buffer_m": buffer_m,
        "earth_radius_m": radius,
        "measure": measure,
        "distance": {
            "centre": "great-circle distance between 30 arc-second cell centres",
            "edge": "great-circle distance from a cell centre to the nearest point of a land cell",
        }[measure],
        "grid_deg": grid_deg,
        "era5_cell": "box of +-grid_deg/2 around each grid point, clipped at the poles",
        "keep_rule": "at least one land-or-buffer GLOBE cell inside the ERA5 cell",
    }
    return LandMask(
        land=land,
        land_or_buffer=lob,
        land_cells=land_cells.astype(np.uint16),
        buffer_cells=buffer_cells.astype(np.uint16),
        total_cells=total.astype(np.uint16),
        keep=keep,
        config=config,
        source=source,
        qc=qc,
    )


# --- Stores --------------------------------------------------------------------------

STORE_DESCRIPTIONS = {
    "era5_cells": (
        "ERA5 0.25 degree cells (721 x 1440, latitudes 90..-90, longitudes 0..359.75): "
        "counts of GLOBE 30 arc-second cells that are land (land_cells), land or within the "
        "buffer (buffer_cells) and in total (total_cells) inside the box of +-0.125 degree "
        "around each grid point (clipped at the poles); keep = buffer_cells > 0."
    ),
    "globe": (
        "GLOBE 30 arc-second grid (21600 x 43200, cell centres; row 0 is 90..89.99167 N, "
        "column 0 is 180..179.99167 W): land, and land or within the buffer."
    ),
}


def write_stores(
    mask: LandMask, out_dir: Path, names: dict[str, str], summary: dict[str, Any]
) -> dict[str, Any]:
    """Write both stores atomically (never overwriting different content)."""
    from astroseeing.ingest.store import Prepared, write_store_atomic
    from astroseeing.provenance import provenance

    glat, glon = grid_axes(mask.config["grid_deg"])
    lat_c, lon_c = globe_centres()
    prepared = {
        "era5_cells": Prepared(
            dims=("latitude", "longitude"),
            coords={"latitude": (("latitude",), glat), "longitude": (("longitude",), glon)},
            data={
                "land_cells": mask.land_cells,
                "buffer_cells": mask.buffer_cells,
                "total_cells": mask.total_cells,
                "keep": mask.keep,
            },
            qc=mask.qc,
        ),
        "globe": Prepared(
            dims=("latitude", "longitude"),
            coords={"latitude": (("latitude",), lat_c), "longitude": (("longitude",), lon_c)},
            data={"land": mask.land, "land_or_buffer": mask.land_or_buffer},
            qc=mask.qc,
        ),
    }
    prov = provenance(mask.config, extra={"source": mask.source})
    out = {}
    for key, prep in prepared.items():
        attrs = {
            "provenance": prov,
            "description": STORE_DESCRIPTIONS[key],
            "source_note": LAND_MASK_SOURCE_NOTE,
            "citation": GLOBE_CITATION,
            "summary": summary,
        }
        out[key] = write_store_atomic(Path(out_dir) / names[key], prep, attrs)
    return out


def load_keep(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(latitude, longitude, keep) from an ``era5_cells`` store."""
    import zarr

    g = zarr.open_group(str(path), mode="r", zarr_format=3)
    return (np.asarray(g["latitude"][...]), np.asarray(g["longitude"][...]), g["keep"][...])


def era5_cell_mask(
    lat: np.ndarray, lon: np.ndarray, keep: np.ndarray, grid_deg: float = 0.25
) -> np.ndarray:
    """Kept-cell mask (len(lat), len(lon)) for a request's axes, which must be on the grid.

    Longitudes may be given in either −180..180 or 0..360 form.
    """
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    iy, _ = grid_point_index(lat, np.zeros_like(lat), grid_deg)
    _, ix = grid_point_index(np.zeros_like(lon), lon, grid_deg)
    return np.asarray(keep)[np.ix_(iy, ix)]
