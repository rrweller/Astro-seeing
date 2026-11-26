"""Saved places' ground heights from Copernicus DEM GLO-30 (F1 spec #47 Module 6;
ticket #54; D47 item 1, D54 item 3, D60 item 1; choices in D75).

- :func:`look_up_height` fetches the one GLO-30 tile holding a place from the public
  AWS bucket and reads the height at the posting nearest the place.
- :func:`set_place_height` (``astro forecast place-height <id>``) looks a saved place
  up and rewrites only that place's ``height`` entry in the settings file, with the
  tile, its SHA-256, the posting and the Copernicus DEM credit line. It logs the
  difference from the place's published height, flagged above the configured limit.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import logging
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
import yaml

from astroseeing.forecast.http import HttpClient, HttpError
from astroseeing.forecast.places.glo30 import Tile, TileFormatError, TileId
from astroseeing.forecast.settings import (
    ForecastSettings,
    Posting,
    SettingsError,
    load_settings,
)
from astroseeing.provenance import DEM_ATTRIBUTION

log = logging.getLogger(__name__)


class PlaceHeightError(RuntimeError):
    """A place's height could not be looked up and confirmed; nothing was written."""


class PlaceHeightMissing(RuntimeError):
    """Saved places whose ground height hasn't been looked up (``places`` names them)."""

    def __init__(self, places: tuple[str, ...]):
        self.places = places
        fixes = "; ".join(f"astro forecast place-height {p}" for p in places)
        super().__init__(
            f"saved place(s) {', '.join(places)} have no looked-up GLO-30 ground height, so "
            f"their seeing can't be computed at their real height (D47 item 1). Run: {fixes}"
        )


def require_looked_up_heights(settings: ForecastSettings) -> None:
    """Refuse to go on unless every saved place has a GLO-30 height (the tick's check).

    A hand-entered height or none at all counts as missing. Raises
    :class:`PlaceHeightMissing` naming every such place and the command that fixes it.
    """
    missing = tuple(pid for pid, place in settings.places.items()
                    if place.height is None or place.height.source != "glo30")  # fmt: skip
    if missing:
        raise PlaceHeightMissing(missing)


@dataclass(frozen=True)
class HeightLookup:
    """One place's GLO-30 height and exactly where it was read."""

    metres: float  # above the EGM2008 geoid; GLO-30 is a surface model
    tile: str  # the tile's name, e.g. Copernicus_DSM_COG_10_N59_00_E009_00_DEM
    sha256: str  # of the whole tile file as downloaded
    posting: Posting  # the posting read: row and column in the tile, and its position


def look_up_height(lat: float, lon: float, *, http: HttpClient, dem_url: str,
                   work_dir: Path) -> HeightLookup:  # fmt: skip
    """Fetch the GLO-30 tile holding (lat, lon) from ``dem_url`` and read the height at
    the nearest posting. The tile goes to a temporary folder under ``work_dir`` and is
    deleted afterwards."""
    plat, plon = _decimal(lat), _decimal(lon)
    tile = TileId.containing(plat, plon)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_dir, prefix="glo30-") as tmp:
        # A tile's postings stop one spacing short of its south and east edges, so the
        # posting nearest a place can be the first row or column of the tile below or
        # to the east: then read that tile instead (at most one step each way).
        for _ in range(3):
            path, sha256 = _fetch_verified(http, dem_url, tile, Path(tmp))
            try:
                t = Tile(path, tile)
                row, col = t.grid.nearest(plat, plon)
                if row == t.grid.rows:
                    tile = tile.south_neighbour()
                elif col == t.grid.cols:
                    tile = tile.east_neighbour()
                else:
                    metres = t.height(row, col)
                    break
            except TileFormatError as e:
                raise PlaceHeightError(f"tile {tile.name}: {e}") from e
            path.unlink()
        else:  # unreachable: after one step south and one east the posting is inside
            raise PlaceHeightError(f"no tile holds the posting nearest ({lat}, {lon})")
        posting = Posting(row, col, *t.grid.centre(row, col))
    return HeightLookup(metres, tile.name, sha256, posting)


def _fetch_verified(http: HttpClient, dem_url: str, tile: TileId, folder: Path):
    """Download one tile and check it against the bucket's checksum; return its path and
    SHA-256.

    The bucket publishes no checksum file, but S3 gives an object uploaded in one part
    an ETag that is the MD5 of its bytes (checked on the two real tiles, 2026-11-26).
    A tile whose ETag isn't such an MD5 (a multipart upload) can't be checked, so it is
    refused rather than trusted. ``If-Match`` makes S3 refuse the download if the object
    changed after the HEAD.
    """
    url = f"{dem_url}/{tile.key}"
    try:
        etag = http.head(url).headers.get("ETag")
        if not etag or not re.fullmatch(r'"[0-9a-f]{32}"', etag):
            raise PlaceHeightError(f"tile {tile.name}: the bucket's ETag {etag!r} is not a "
                                   f"plain MD5, so the download can't be checked")  # fmt: skip
        dl = http.download(url, folder / f"{tile.name}.tif", headers={"If-Match": etag})
    except HttpError as e:
        raise PlaceHeightError(f"tile {tile.name} could not be fetched from {url}: {e}") from e
    md5 = hashlib.md5()
    with open(dl.path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            md5.update(chunk)
    if f'"{md5.hexdigest()}"' != etag:
        dl.path.unlink()
        raise PlaceHeightError(f"tile {tile.name}: MD5 {md5.hexdigest()} of the download "
                               f"doesn't match the bucket's ETag {etag}")  # fmt: skip
    return dl.path, dl.sha256


def _decimal(x: float) -> Fraction:
    """A coordinate as the decimal written in the settings file, exactly (59.669 is
    59669/1000, not the nearest binary float), so halfway cases are decided exactly."""
    return Fraction(repr(float(x)))


@dataclass(frozen=True)
class PlaceHeightResult:
    """What ``set_place_height`` wrote, and how it compares with a published height."""

    place: str
    lookup: HeightLookup
    published_height_m: float | None
    published_difference_m: float | None  # looked-up minus published
    flagged: bool  # the difference is above the settings' limit


def set_place_height(settings_path: Path, place_id: str, *, http: HttpClient, work_dir: Path,
                     dem_url: str | None = None) -> PlaceHeightResult:  # fmt: skip
    """Look up a saved place's GLO-30 height and write it into the settings file.

    ``dem_url`` overrides the settings' bucket (tests point it at a fake server). The
    file is changed only if the lookup succeeds, and then only in that place's
    ``height`` entry: the new text is re-read and compared with the old data before it
    replaces the file atomically, so comments and every other value stay as they were.
    """
    settings_path = Path(settings_path)
    settings = load_settings(settings_path)
    if place_id not in settings.places:
        raise PlaceHeightError(f"no saved place {place_id!r} in {settings_path} "
                               f"(saved places: {', '.join(settings.places)})")  # fmt: skip
    place = settings.places[place_id]
    found = look_up_height(place.lat, place.lon, http=http, work_dir=work_dir,
                           dem_url=dem_url or settings.place_heights.dem.url)  # fmt: skip
    _write_height(settings_path, place_id, found)
    p = found.posting
    log.info("%s: GLO-30 height %.2f m at posting (%d, %d) of %s, %.5f, %.5f (sha256 %s)",
             place_id, found.metres, p.row, p.col, found.tile, p.lat, p.lon,
             found.sha256)  # fmt: skip
    diff, flagged = None, False
    if place.published_height_m is not None:
        diff = found.metres - place.published_height_m
        flagged = abs(diff) > settings.place_heights.flag_published_difference_m
        log.log(logging.WARNING if flagged else logging.INFO,
                "%s: GLO-30 height minus the published %g m is %+.1f m%s", place_id,
                place.published_height_m, diff,
                f" (FLAG: more than {settings.place_heights.flag_published_difference_m:g} m;"
                " GLO-30 is a surface model)" if flagged else "")  # fmt: skip
    return PlaceHeightResult(place_id, found, place.published_height_m, diff, flagged)


def _height_entry(found: HeightLookup) -> dict:
    return {
        "metres": float(_float32_text(found.metres)),
        "source": "glo30",
        "tile": found.tile,
        "sha256": found.sha256,
        "posting": dataclasses.asdict(found.posting),
        "attribution": DEM_ATTRIBUTION,
    }


def _float32_text(x: float) -> str:
    """The shortest decimal that reads back as the same float32 (GLO-30's type)."""
    return np.format_float_positional(np.float32(x), unique=True, trim="0")


def _write_height(path: Path, place_id: str, found: HeightLookup) -> None:
    text = path.read_text()
    old = yaml.safe_load(text)
    entry = _height_entry(found)
    p = entry["posting"]
    block = [
        f"    height:  # looked up by `astro forecast place-height {place_id}` (D75)",
        f"      metres: {_float32_text(found.metres)}",
        "      source: glo30",
        f"      tile: {found.tile}",
        f"      sha256: {found.sha256}",
        f"      posting: {{row: {p['row']}, col: {p['col']}, lat: {p['lat']!r}, "
        f"lon: {p['lon']!r}}}",
        f"      attribution: {json.dumps(DEM_ATTRIBUTION, ensure_ascii=False)}",
    ]
    new_text = _replace_height_lines(text, place_id, block)

    expected = copy.deepcopy(old)
    expected["places"][place_id]["height"] = entry
    if yaml.safe_load(new_text) != expected:
        raise PlaceHeightError(f"{path}: rewriting {place_id}'s height would change other "
                               "values; nothing written")  # fmt: skip
    _atomic_write(path, new_text)


def _check_settings(path: Path) -> None:
    try:
        load_settings(path)
    except SettingsError as e:
        raise PlaceHeightError(f"the new height entry doesn't validate: {e}") from e


def _replace_height_lines(text: str, place_id: str, block: list[str]) -> str:
    """Swap the ``height:`` entry of ``places.<place_id>`` (one line, or a line and its
    more-indented continuation) for ``block``. The settings file writes places as
    ``places:`` at the top level, ids indented 2 and their keys 4."""
    lines = text.splitlines()

    def indent(line: str) -> int | None:  # None: blank or comment-only
        stripped = line.lstrip(" ")
        return None if not stripped or stripped.startswith("#") else len(line) - len(stripped)

    def find(start: int, end: int, pattern: str, level: int) -> int:
        for i in range(start, end):
            if indent(lines[i]) == level and re.match(pattern, lines[i]):
                return i
        raise PlaceHeightError(f"settings file: can't find {pattern!r} at indent {level}")

    def block_end(start: int, level: int) -> int:
        for i in range(start + 1, len(lines)):
            if (ind := indent(lines[i])) is not None and ind <= level:
                return i
        return len(lines)

    places = find(0, len(lines), r"places:\s*(#.*)?$", 0)
    pl = find(places + 1, block_end(places, 0), rf"  {re.escape(place_id)}:\s*(#.*)?$", 2)
    h = find(pl + 1, block_end(pl, 2), r"    height:", 4)
    end = h + 1
    while (
        end < len(lines)
        and lines[end].strip()
        and len(lines[end]) - len(lines[end].lstrip(" ")) > 4
    ):
        end += 1
    out = lines[:h] + block + lines[end:]
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def _atomic_write(path: Path, text: str) -> None:
    """Temp file beside ``path``, fsync, validate it as settings, keep the mode, rename;
    nothing is left behind on failure."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        _check_settings(Path(tmp))
        os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
