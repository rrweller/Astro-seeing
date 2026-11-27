"""Sunset maps (F1 spec Module 7, D60 item 3, D88): the Tonight map as it stood at
sunset at the default saved place, kept for looking back.

At the first tick after that place's sunset, the product set that was current at
sunset (the latest one written at or before it) has its map layers and its own copy of
``latest.json`` copied to ``products/sunset/<night>/``, ``<night>`` being the Night's
evening date. Seven are kept, the oldest deleted first. Everything lives on the SSD
under ``/staging/forecast/products/`` (D51 item 10); nothing goes to ``/data``.

The set current at sunset is found on disk, from each set's own ``latest.json`` and its
``written_at``, so a restart or a missed tick changes nothing: the next tick still takes
the right set while it is among the kept sets. If no kept set was written at or before
sunset (the service started after sunset, or the right set was already pruned), no map
is taken for that night, never a later set's; the tick logs it. Times are compared at
the whole second of ``written_at``.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from astroseeing.forecast.publish.sets import SET_LATEST, write_folder
from astroseeing.forecast.tonight.shapes import SunTrack

log = logging.getLogger(__name__)

KEEP_NIGHTS = 7
FOLDER = "sunset"


@dataclass(frozen=True)
class SunsetMap:
    night: dt.date
    set_id: str  # the set current at sunset, whose layers were copied
    deleted: tuple[str, ...] = ()  # nights deleted to keep seven

    def as_dict(self) -> dict:
        return {"night": self.night.isoformat(), "set_id": self.set_id,
                "deleted": list(self.deleted)}  # fmt: skip


def take_sunset_map(products: Path, sun: SunTrack, now: dt.datetime) -> SunsetMap | None:
    """Copy the set current at sunset to ``sunset/<night>/``, if ``now`` is after
    Tonight's sunset (``sun`` is Tonight's Sun at the default saved place) and that
    night's map isn't taken yet. Returns what was taken, or None."""
    products = Path(products)
    if now <= sun.sunset:
        return None
    night = sun.night.isoformat()
    root = products / FOLDER
    final = root / night
    if final.is_dir():
        return None
    found = _set_at(products / "sets", sun.sunset)
    if found is None:
        log.warning("no sunset map for the night of %s: no kept product set was written at "
                    "or before its sunset (%s)", night, sun.sunset)  # fmt: skip
        return None
    folder, latest_bytes = found
    latest = json.loads(latest_bytes)
    files = {e["file"]: (folder / e["file"]).read_bytes() for e in latest["layers"].values()}
    write_folder(final, {**files, SET_LATEST: latest_bytes})
    deleted = _prune(root)
    log.info("sunset map for the night of %s taken from set %s (sunset %s)%s", night,
             latest["set_id"], sun.sunset,
             f"; deleted {', '.join(deleted)}" if deleted else "")  # fmt: skip
    return SunsetMap(sun.night, latest["set_id"], deleted)


def sunset_maps(products: Path) -> list[dict]:
    """The kept sunset maps, newest first, as ``latest.json``'s ``sunset_maps`` lists them."""
    root = Path(products) / FOLDER
    if not root.is_dir():
        return []
    nights = sorted((n for n in _nights(root) if (root / n / SET_LATEST).is_file()), reverse=True)
    return [{"night": n, "path": f"{FOLDER}/{n}/"} for n in nights]


def _set_at(sets: Path, t: dt.datetime) -> tuple[Path, bytes] | None:
    """The newest kept set written at or before ``t``: its folder and ``latest.json``."""
    if not sets.is_dir():
        return None
    best = None
    for folder in sets.iterdir():
        own = folder / SET_LATEST
        if folder.name.startswith(".") or not own.is_file():
            continue
        data = own.read_bytes()
        written = dt.datetime.fromisoformat(json.loads(data)["written_at"].replace("Z", "+00:00"))
        if written <= t and (best is None or written > best[0]):
            best = (written, folder, data)
    return None if best is None else best[1:]


def _nights(root: Path) -> list[str]:
    out = []
    for p in root.iterdir():
        if p.is_dir() and not p.name.startswith("."):
            try:
                dt.date.fromisoformat(p.name)
            except ValueError:
                continue
            out.append(p.name)
    return out


def _prune(root: Path, keep: int = KEEP_NIGHTS) -> tuple[str, ...]:
    """Delete all but the newest ``keep`` nights, oldest first, and leftover temp folders."""
    for leftover in root.glob(".tmp-*"):
        shutil.rmtree(leftover, ignore_errors=True)
    nights = sorted(_nights(root))
    gone = tuple(nights[:-keep])
    for n in gone:
        shutil.rmtree(root / n)
    return gone
