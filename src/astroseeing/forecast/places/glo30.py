"""Copernicus DEM GLO-30 tiles: names, their grid, and one height from one tile.

GLO-30's Cloud-Optimised GeoTIFFs on AWS (``copernicus-dem-30m``) are 1° × 1° tiles
named after their south-west corner. Checked on two real tiles (N59 E009 and
S25 W071, 2026-11-26) and against the tiles' own metadata XML (cell geometry
"point"):

- classic little-endian TIFF, one float32 band, internal 1024 × 1024 blocks, DEFLATE
  with the floating-point predictor (3);
- ``GTRasterTypeGeoKey`` = 2, *pixel is point*: each value is the height at a grid
  posting, and the tiepoint puts the posting of pixel (0, 0) exactly on the tile's
  north-west corner (e.g. 60° N, 9° E for N59 E009);
- 3600 rows, 1″ apart, so row 3599 sits 1″ north of the tile's south edge (the south
  edge's postings are row 0 of the tile below); columns are 1″ × a factor that grows
  with latitude (2400 columns of 1.5″ at N59), and likewise stop one spacing short of
  the east edge.

This module reads exactly that and refuses anything else (another registration,
compression, data type, a grid that doesn't span its 1°, no-data), so a format change
fails loudly rather than shifting a height by a pixel. Nothing here downloads.
"""

from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

#: GLO-30's no-data value (``valueInvalidPixels`` in the tiles' metadata XML).
NODATA = -32767.0

_TYPES = {1: "B", 2: "s", 3: "H", 4: "I", 11: "f", 12: "d", 16: "Q"}  # TIFF field types
_SIZES = {"B": 1, "s": 1, "H": 2, "I": 4, "f": 4, "d": 8, "Q": 8}
_PIXEL_IS_POINT = 2


class TileFormatError(ValueError):
    """The file is not laid out as a GLO-30 tile is expected to be."""


@dataclass(frozen=True)
class TileId:
    """A GLO-30 tile, named by its south-west corner in whole degrees."""

    south: int
    west: int

    @classmethod
    def containing(cls, lat: Fraction, lon: Fraction) -> TileId:
        return cls(math.floor(lat), math.floor(lon))

    @property
    def name(self) -> str:
        ns = f"{'N' if self.south >= 0 else 'S'}{abs(self.south):02d}"
        ew = f"{'E' if self.west >= 0 else 'W'}{abs(self.west):03d}"
        return f"Copernicus_DSM_COG_10_{ns}_00_{ew}_00_DEM"

    @property
    def key(self) -> str:
        """The tile's object key in the bucket."""
        return f"{self.name}/{self.name}.tif"

    def south_neighbour(self) -> TileId:
        return TileId(self.south - 1, self.west)

    def east_neighbour(self) -> TileId:
        west = self.west + 1
        return TileId(self.south, -180 if west == 180 else west)


@dataclass(frozen=True)
class Grid:
    """A tile's postings: row 0 at latitude ``north``, column 0 at ``west``."""

    rows: int
    cols: int
    north: Fraction
    west: Fraction
    dlat: Fraction
    dlon: Fraction

    def nearest(self, lat: Fraction, lon: Fraction) -> tuple[int, int]:
        """The posting nearest (lat, lon), as (row, col), in exact arithmetic.

        A place exactly halfway between postings takes the one to its south-west (the
        F1 spec's tie rule for the map grid). The result can be ``rows`` or ``cols``: the
        nearest posting is then on the south or east edge, which belongs to the next
        tile.
        """
        r = (self.north - lat) / self.dlat
        c = (lon - self.west) / self.dlon
        return math.floor(r + Fraction(1, 2)), math.ceil(c - Fraction(1, 2))

    def centre(self, row: int, col: int) -> tuple[float, float]:
        return float(self.north - row * self.dlat), float(self.west + col * self.dlon)


class Tile:
    """One GLO-30 tile file, read lazily: the header now, one block per ``height``."""

    def __init__(self, path: Path, tile: TileId):
        self.path = Path(path)
        with open(self.path, "rb") as f:
            self._head = f.read(1 << 16)
        self._tags = self._read_ifd()
        self.grid = self._read_grid(tile)

    def height(self, row: int, col: int) -> float:
        """The height (m above the EGM2008 geoid) at posting (row, col)."""
        g = self.grid
        if not (0 <= row < g.rows and 0 <= col < g.cols):
            raise IndexError(f"posting ({row}, {col}) is outside the {g.rows} × {g.cols} tile")
        tw, tl = self._one(322), self._one(323)
        across = -(-g.cols // tw)
        index = (row // tl) * across + col // tw
        offset, size = self._tags[324][index], self._tags[325][index]
        with open(self.path, "rb") as f:
            f.seek(offset)
            raw = f.read(size)
        if len(raw) != size:
            raise TileFormatError(f"{self.path.name}: block {index} is cut short")
        try:
            data = zlib.decompress(raw)
        except zlib.error as e:
            raise TileFormatError(f"{self.path.name}: block {index} won't inflate: {e}") from e
        if len(data) != tw * tl * 4:
            raise TileFormatError(f"{self.path.name}: block {index} has {len(data)} bytes, "
                                  f"expected {tw * tl * 4}")  # fmt: skip
        value = float(_undo_float_predictor(data, tw, tl)[row % tl, col % tw])
        if not math.isfinite(value) or value == NODATA:
            raise TileFormatError(f"{self.path.name}: posting ({row}, {col}) holds no data "
                                  f"({value})")  # fmt: skip
        return value

    # -- header ----------------------------------------------------------------------
    def _read_ifd(self) -> dict[int, tuple]:
        head = self._head
        if head[:4] != b"II*\0":
            raise TileFormatError(f"{self.path.name}: not a classic little-endian TIFF")
        (ifd,) = struct.unpack_from("<I", head, 4)
        (count,) = self._unpack("<H", ifd)
        tags = {}
        for i in range(count):
            tag, typ, n, value_or_offset = self._unpack("<HHII", ifd + 2 + 12 * i)
            if typ not in _TYPES:
                continue  # a field type this reader never needs
            fmt = _TYPES[typ]
            size = _SIZES[fmt] * n
            at = ifd + 2 + 12 * i + 8 if size <= 4 else value_or_offset
            tags[tag] = self._unpack(f"<{n}{fmt}", at)
        return tags

    def _unpack(self, fmt: str, at: int) -> tuple:
        size = struct.calcsize(fmt)
        if at + size > len(self._head):
            with open(self.path, "rb") as f:
                f.seek(at)
                raw = f.read(size)
            if len(raw) != size:
                raise TileFormatError(f"{self.path.name}: header points past the end")
            return struct.unpack(fmt, raw)
        return struct.unpack_from(fmt, self._head, at)

    def _one(self, tag: int) -> int:
        if tag not in self._tags or len(self._tags[tag]) != 1:
            raise TileFormatError(f"{self.path.name}: TIFF tag {tag} missing or not single")
        return self._tags[tag][0]

    def _read_grid(self, tile: TileId) -> Grid:
        name = self.path.name
        expect = {258: 32, 259: 8, 277: 1, 284: 1, 317: 3, 339: 3}
        got = {tag: self._one(tag) for tag in expect}
        if got != expect:
            raise TileFormatError(f"{name}: expected float32, DEFLATE, floating-point "
                                  f"predictor, one band (tags {expect}), got {got}")  # fmt: skip
        if 322 not in self._tags or 324 not in self._tags or 325 not in self._tags:
            raise TileFormatError(f"{name}: not internally tiled")
        if self._geokey(1025) != _PIXEL_IS_POINT:
            raise TileFormatError(f"{name}: GTRasterTypeGeoKey is {self._geokey(1025)}, not 2 "
                                  f"(pixel is point) as GLO-30 is")  # fmt: skip
        if self._geokey(2048) != 4326:
            raise TileFormatError(f"{name}: not on WGS 84 latitude/longitude (EPSG:4326)")
        scale, tie = self._tags.get(33550), self._tags.get(33922)
        if not scale or not tie or len(tie) != 6 or tie[:3] != (0.0, 0.0, 0.0):
            raise TileFormatError(f"{name}: no single tiepoint at pixel (0, 0) and scale")
        rows, cols = self._one(257), self._one(256)
        dlon, dlat = _exact(scale[0], name), _exact(scale[1], name)
        west, north = _exact(tie[3], name), _exact(tie[4], name)
        if (north, west) != (tile.south + 1, tile.west):
            raise TileFormatError(f"{name}: pixel (0, 0) is at ({float(north)}, {float(west)}), "
                                  f"not the tile's north-west corner")  # fmt: skip
        if rows * dlat != 1 or cols * dlon != 1:
            raise TileFormatError(f"{name}: {rows} × {cols} postings don't span 1°")
        n_blocks = -(-rows // self._one(323)) * -(-cols // self._one(322))
        if len(self._tags[324]) != n_blocks or len(self._tags[325]) != n_blocks:
            raise TileFormatError(f"{name}: expected {n_blocks} blocks")
        return Grid(rows, cols, north, west, dlat, dlon)

    def _geokey(self, key: int) -> int | None:
        keys = self._tags.get(34735, ())
        for i in range(4, len(keys) - 3, 4):
            if keys[i] == key and keys[i + 1] == 0 and keys[i + 2] == 1:
                return keys[i + 3]
        return None


def _exact(value: float, name: str) -> Fraction:
    """A header number as the fraction it stands for (1/3600, 1/2400, 60, …).

    Real tiles don't always hold the nearest double: N59 E009's column spacing is
    0.00041666666666666664, one rounding step below 1/2400. So a value counts as the
    fraction within a relative 1e-12, far below any real spacing difference."""
    frac = Fraction(value).limit_denominator(1_000_000)
    if not math.isclose(float(frac), value, rel_tol=1e-12, abs_tol=0.0):
        raise TileFormatError(f"{name}: header value {value!r} is not a simple fraction")
    return frac


def _undo_float_predictor(data: bytes, width: int, length: int) -> np.ndarray:
    """Undo TIFF's floating-point predictor (Adobe TIFF Technical Note 3): bytes are
    differenced along each row, laid out as byte planes, most significant first."""
    planes = np.frombuffer(data, dtype=np.uint8).reshape(length, 4 * width)
    planes = np.cumsum(planes, axis=1, dtype=np.uint8)  # wraps mod 256, as encoded
    return planes.reshape(length, 4, width).transpose(0, 2, 1).copy().view(">f4")[..., 0]
