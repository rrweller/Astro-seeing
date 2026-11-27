"""Product sets (F1 spec Module 7): ``sets/<set_id>/`` and ``latest.json``
(schema ``f1-latest/1``), written last and atomically; the last 3 sets are kept.

A set is written only when its content differs from the current set's: the content hash
covers every file's bytes and ``latest.json`` without its three write-time keys
(``set_id``, ``set_path``, ``written_at``), and is kept beside the files as
``content.sha256``, with a copy of the set's own ``latest.json`` (the sunset maps copy
the ``latest.json`` of the set current at sunset, ticket #67). ``set_id`` is the write
time ``YYYYMMDDTHHMMSSZ`` plus the hash's first 8 hex digits.

Order on disk: the set's files go into a temp folder (each written, fsynced and made
world-readable), the folder is renamed into place, then ``latest.json`` is written to a
temp name, fsynced and renamed (D52 items 2 and 9). A page mid-load never loses a file:
only sets older than the newest 3 are pruned, never the current one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astroseeing.forecast.store import fsync_dir, utc_text, write_atomic
from astroseeing.provenance import canonical_json

KEEP_SETS = 3
CONTENT_FILE = "content.sha256"
SET_LATEST = "latest.json"  # the set's own copy of its latest.json (for the sunset maps)
_WRITE_TIME_KEYS = ("set_id", "set_path", "written_at")


@dataclass(frozen=True)
class Published:
    set_id: str
    new: bool  # False: the content was unchanged, nothing was written


def content_hash(files: Mapping[str, bytes], latest: Mapping[str, Any]) -> str:
    body = {k: v for k, v in latest.items() if k not in _WRITE_TIME_KEYS}
    digests = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    return hashlib.sha256(canonical_json({"files": digests, "latest": body}).encode()).hexdigest()


def current_set(products: Path) -> str | None:
    latest = Path(products) / "latest.json"
    return json.loads(latest.read_text())["set_id"] if latest.exists() else None


def publish(
    products: Path, files: Mapping[str, bytes], latest: Mapping[str, Any], now: dt.datetime
) -> Published:
    """Write a new set and point ``latest.json`` at it, unless the content is unchanged.

    ``latest`` is the ``latest.json`` document without ``set_id``, ``set_path`` and
    ``written_at``, which are filled here.
    """
    products = Path(products)
    sets = products / "sets"
    digest = content_hash(files, latest)
    current = current_set(products)
    if current is not None:
        mark = sets / current / CONTENT_FILE
        if mark.exists() and mark.read_text().strip() == digest:
            return Published(current, new=False)

    set_id = f"{now.astimezone(dt.UTC):%Y%m%dT%H%M%SZ}-{digest[:8]}"
    doc = {**latest, "set_id": set_id, "set_path": f"sets/{set_id}/", "written_at": utc_text(now)}
    ordered = {k: doc[k] for k in ("schema", "set_id", "set_path", "written_at")} | doc
    latest_bytes = (json.dumps(ordered, indent=1, allow_nan=False) + "\n").encode()
    final = sets / set_id
    tmp = sets / f".tmp-{set_id}-{os.getpid()}"
    sets.mkdir(parents=True, exist_ok=True)
    os.chmod(products, 0o755)
    os.chmod(sets, 0o755)
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        own = {CONTENT_FILE: (digest + "\n").encode(), SET_LATEST: latest_bytes}
        for name, data in {**files, **own}.items():
            write_atomic(tmp / name, data)
        os.chmod(tmp, 0o755)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    fsync_dir(sets)
    write_atomic(products / "latest.json", latest_bytes)
    prune(products)
    return Published(set_id, new=True)


def prune(products: Path, keep: int = KEEP_SETS) -> list[str]:
    """Delete all but the newest ``keep`` sets (never the current one), and leftover
    temp folders; returns the deleted set ids."""
    sets = Path(products) / "sets"
    if not sets.is_dir():
        return []
    current = current_set(products)
    for leftover in sets.glob(".tmp-*"):
        shutil.rmtree(leftover, ignore_errors=True)
    ids = sorted(p.name for p in sets.iterdir() if p.is_dir() and not p.name.startswith("."))
    gone = [s for s in ids[:-keep] if s != current]
    for s in gone:
        shutil.rmtree(sets / s)
    return gone
