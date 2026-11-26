"""Small synthetic Copernicus DEM GLO-30 tiles for tests (ticket #54).

``write_tile`` writes a GeoTIFF laid out like the real GLO-30 Cloud-Optimised GeoTIFFs
on AWS (checked against two real tiles on 2026-11-26): classic little-endian TIFF,
float32, internal 16 × 16 tiles here (1024 there), DEFLATE with the floating-point
predictor (3), EPSG:4326, ``GTRasterTypeGeoKey`` = 2 (pixel is point), and a tiepoint
that puts the *centre* of pixel (0, 0) on the tile's north-west corner. A real tile has
3600 rows; these have far fewer, but each still spans exactly 1° so the edge rules are
the same.

The encoder here is written independently of the reader under test, following the
TIFF 6.0 layout and Adobe's TIFF Technical Note 3 (floating-point predictor).
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

import numpy as np

# TIFF field types
_SHORT, _LONG, _DOUBLE, _ASCII = 3, 4, 12, 2
_SIZES = {_SHORT: 2, _LONG: 4, _DOUBLE: 8, _ASCII: 1}
_FMT = {_SHORT: "H", _LONG: "I", _DOUBLE: "d"}


def tile_name(south: int, west: int) -> str:
    ns = f"{'N' if south >= 0 else 'S'}{abs(south):02d}"
    ew = f"{'E' if west >= 0 else 'W'}{abs(west):03d}"
    return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"


def tile_path(south: int, west: int) -> str:
    """The tile's path in the bucket, as served (``/<name>/<name>.tif``)."""
    name = tile_name(south, west)
    return f"/{name}/{name}.tif"


def write_tile(
    path: Path,
    heights: np.ndarray,
    *,
    north: float,
    west: float,
    raster_type: int = 2,
    predictor: int = 3,
    block: int = 16,
    scale: tuple[float, float] | None = None,
) -> bytes:
    """Write ``heights`` (rows north → south, columns west → east) as a GeoTIFF whose
    pixel (0, 0) is centred on (``north``, ``west``) and which spans exactly 1°; return
    the file's bytes. ``scale`` overrides the stored (dlon, dlat)."""
    heights = np.asarray(heights, dtype=np.float32)
    rows, cols = heights.shape
    dlon, dlat = scale if scale is not None else (1.0 / cols, 1.0 / rows)
    blocks = []
    for r0 in range(0, rows, block):
        for c0 in range(0, cols, block):
            b = np.zeros((block, block), dtype=np.float32)  # edge blocks padded, as in TIFF
            part = heights[r0 : r0 + block, c0 : c0 + block]
            b[: part.shape[0], : part.shape[1]] = part
            blocks.append(zlib.compress(_encode(b, predictor)))
    geokeys = [1, 1, 0, 4, 1024, 0, 1, 2, 1025, 0, 1, raster_type, 2048, 0, 1, 4326,
               2054, 0, 1, 9102]  # fmt: skip
    tags = [
        (256, _SHORT, [cols]),
        (257, _SHORT, [rows]),
        (258, _SHORT, [32]),
        (259, _SHORT, [8]),  # DEFLATE
        (262, _SHORT, [1]),
        (277, _SHORT, [1]),
        (284, _SHORT, [1]),
        (317, _SHORT, [predictor]),
        (322, _SHORT, [block]),
        (323, _SHORT, [block]),
        (324, _LONG, [0] * len(blocks)),  # offsets, filled in below
        (325, _LONG, [len(b) for b in blocks]),
        (339, _SHORT, [3]),  # IEEE float
        (33550, _DOUBLE, [dlon, dlat, 0.0]),
        (33922, _DOUBLE, [0.0, 0.0, 0.0, west, north, 0.0]),
        (34735, _SHORT, geokeys),
    ]
    data = _layout(tags, blocks)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)
    return data


def md5_etag(data: bytes) -> str:
    """The ETag S3 gives an object uploaded in one part: its MD5, in quotes."""
    return f'"{hashlib.md5(data).hexdigest()}"'


def _encode(block: np.ndarray, predictor: int) -> bytes:
    if predictor == 1:
        return block.astype("<f4").tobytes()
    assert predictor == 3
    out = []
    for row in block:
        planes = row.astype(">f4").view(np.uint8).reshape(-1, 4).T.reshape(-1)  # MSB plane first
        diff = np.empty_like(planes)
        diff[0] = planes[0]
        diff[1:] = planes[1:] - planes[:-1]  # uint8 arithmetic wraps mod 256
        out.append(diff.tobytes())
    return b"".join(out)


def _layout(tags, blocks: list[bytes]) -> bytes:
    """Header, then the one IFD, then out-of-line values, then the compressed blocks."""
    ifd_offset = 8
    ifd_size = 2 + 12 * len(tags) + 4
    extra_offset = ifd_offset + ifd_size
    extras: list[bytes] = []

    def extra_len() -> int:
        return sum(len(e) for e in extras)

    # First pass: size the out-of-line values so the block offsets are known.
    sizes = [_SIZES[t] * len(v) for _, t, v in tags]
    blocks_offset = extra_offset + sum(s for s in sizes if s > 4)
    offsets, pos = [], blocks_offset
    for b in blocks:
        offsets.append(pos)
        pos += len(b)
    entries = []
    for tag, typ, values in tags:
        if tag == 324:
            values = offsets
        raw = struct.pack(f"<{len(values)}{_FMT[typ]}", *values)
        if len(raw) <= 4:
            entries.append(struct.pack("<HHI", tag, typ, len(values)) + raw.ljust(4, b"\0"))
        else:
            entries.append(struct.pack("<HHII", tag, typ, len(values), extra_offset + extra_len()))
            extras.append(raw)
    head = b"II*\0" + struct.pack("<I", ifd_offset)
    ifd = struct.pack("<H", len(tags)) + b"".join(entries) + struct.pack("<I", 0)
    out = head + ifd + b"".join(extras)
    assert len(out) == blocks_offset
    return out + b"".join(blocks)
