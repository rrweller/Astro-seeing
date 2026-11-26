"""Stores (F1 spec Module 6): per-place daily Zarr stores on ``/data`` (written once,
atomically, never touched again; D51 item 12) and the expiring products on the SSD
(D51 item 10).

This module holds the SSD part (ticket #51): each run's hourly values at each saved
place, one JSON file per place and run, under
``/staging/forecast/products/places/<place>/<run's UTC day>/<model>-<run>.json``. The
daily stores on ``/data`` (``finalise_days``) are ticket #59 (F1-10).

- :func:`run_document` turns one run's column products at a place into the stored
  values: every verified step, unrounded, with J, H̄ and seeing for both Cₙ² models,
  the cloud layers and class, the 200 hPa wind, the fog signals (or ``"absent"``), the
  observer height, raise, gap and level count, the QC counts and provenance.
- :meth:`PlaceStore.put_run` writes it atomically (temp file, fsync, rename) and
  world-readable; :meth:`PlaceStore.read_run` reads it back for the check that comes
  before any raw file is deleted.
- :meth:`PlaceStore.hours_for` gives each model's values for a list of UTC hours from
  its newest stored run, and the reason for every hour it has none (never filled).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from astroseeing.forecast.column import ColumnProducts, cloud_class
from astroseeing.forecast.settings import CloudClasses, Model, Place
from astroseeing.forecast.sources.interface import RunFields

STORE_SCHEMA = "forecast-place-run/1"
_CLOUD = {
    "total_pct": "total_cloud_pct",
    "low_pct": "low_cloud_pct",
    "mid_pct": "mid_cloud_pct",
    "high_pct": "high_cloud_pct",
}


def utc_text(t: dt.datetime | np.datetime64) -> str:
    """``2026-11-26T06:00:00Z``: the one time format of the stored and published files."""
    if isinstance(t, np.datetime64):
        t = t.astype("datetime64[s]").item().replace(tzinfo=dt.UTC)
    if t.tzinfo is None:
        raise ValueError(f"naive datetime {t!r}")
    return t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(x: Any) -> float | None:
    """A finite float, or None for NaN (JSON has no NaN; a NaN is never a value)."""
    x = float(x)
    return None if math.isnan(x) else x


@dataclass(frozen=True)
class StoredFile:
    path: Path
    bytes: int
    sha256: str


def run_document(
    place: Place,
    fields: RunFields,
    point: tuple[int, int],
    products: ColumnProducts,
    verified_steps: Sequence[int],
    missing_steps: Mapping[int, str],
    run_id: int,
    credit: str,
    cloud_classes: CloudClasses,
    provenance: Mapping[str, Any],
) -> dict:
    """The stored values of one run at one place (``fields`` and ``products`` on the
    place's grid point ``point``; only ``verified_steps`` are kept)."""
    i, j = point
    run_t0 = np.datetime64(fields.run.run_time.replace(tzinfo=None), "s")
    step_of = ((fields.valid_times - run_t0) // np.timedelta64(1, "h")).astype(int).tolist()
    steps = []
    for k, step in enumerate(step_of):
        if step not in verified_steps:
            continue
        total = float(fields.total_cloud_pct[k, i, j])
        steps.append(
            {
                "step": step,
                "valid_time": utc_text(fields.valid_times[k]),
                "cloud": {
                    key: float(getattr(fields, name)[k, i, j]) for key, name in _CLOUD.items()
                },
                "cloud_class": cloud_class(total, cloud_classes),
                "cn2": {
                    name: {
                        "j_total": _num(c.j_total[k, i, j]),
                        "j_free": _num(c.j_free[k, i, j]),
                        "hbar_m": _num(c.hbar_m[k, i, j]),
                        "seeing_total_arcsec": _num(c.seeing_total_arcsec[k, i, j]),
                        "seeing_free_arcsec": _num(c.seeing_free_arcsec[k, i, j]),
                    }
                    for name, c in products.models.items()
                },
                "wind_200hpa_ms": float(products.wind_200hpa_ms[k, i, j]),
                "fog": {
                    name: "absent" if v is None else float(v[k, i, j])
                    for name, v in fields.fog.items()
                },
                "gap_to_first_level_m": _num(products.gap_to_first_level_m[k, i, j]),
                "valid_levels": int(products.valid_levels[k, i, j]),
            }
        )
    model = fields.model
    return {
        "schema": STORE_SCHEMA,
        "place": place.id,
        "model": model.id,
        "run_id": run_id,
        "run_time": utc_text(fields.run.run_time),
        "meta": {
            "name": model.name,
            "family": model.family,
            "regional": model.regional,
            "level_count": products.level_count,
            "credit": credit,
            "grid_point": {"lat": float(fields.lat[i, j]), "lon": float(fields.lon[i, j])},
            "place_height_m": place.height.metres if place.height else None,
            "model_ground_m": float(products.model_ground_m[i, j]),
            "observer_height_m": float(products.observer_height_m[i, j]),
            "raise_m": float(products.raise_m[i, j]),
        },
        "steps_expected": list(model.steps_h),
        "missing_steps": {str(s): why for s, why in sorted(missing_steps.items())},
        "steps": steps,
        "qc": {
            "cloud_range": fields.qc.as_dict(),
            "column": products.qc.as_dict(),
            **{name: c.qc.as_dict() for name, c in products.models.items()},
        },
        "provenance": dict(provenance),
    }


@dataclass(frozen=True)
class PlaceHours:
    """Each model's values for a list of UTC hours (``values[model][k]`` is the stored step
    for ``hours[k]``, or ``{"missing": reason}``); ``runs[model]`` is the run's stored
    document without its steps, or None when the model has no stored run."""

    hours: tuple[dt.datetime, ...]
    runs: Mapping[str, dict | None]
    values: Mapping[str, tuple[dict, ...]]


class PlaceStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, place_id: str, model_id: str, run_time: dt.datetime) -> Path:
        return (
            self.root
            / place_id
            / run_time.strftime("%Y-%m-%d")
            / f"{model_id}-{run_time.strftime('%Y%m%dT%HZ')}.json"
        )

    def put_run(self, doc: dict) -> StoredFile:
        """Write one run's values for one place, atomically and world-readable."""
        run_time = dt.datetime.fromisoformat(doc["run_time"].replace("Z", "+00:00"))
        path = self.path_for(doc["place"], doc["model"], run_time)
        data = (json.dumps(doc, indent=1, allow_nan=False) + "\n").encode()
        write_atomic(path, data)
        return StoredFile(path, len(data), hashlib.sha256(data).hexdigest())

    def remove_run(self, place_id: str, model_id: str, run_time: dt.datetime) -> bool:
        """Remove one run's stored values (an SSD file, never ``/data``), when the run
        has failed after storing some steps; True if there was a file."""
        path = self.path_for(place_id, model_id, run_time)
        if not path.exists():
            return False
        path.unlink()
        return True

    @staticmethod
    def read_run(path: Path) -> dict:
        doc = json.loads(Path(path).read_text())
        if doc.get("schema") != STORE_SCHEMA:
            raise ValueError(f"{path}: not a {STORE_SCHEMA} file")
        return doc

    def latest_run(self, place_id: str, model_id: str) -> dict | None:
        """The stored run of this model at this place with the newest run time."""
        found = sorted((self.root / place_id).glob(f"*/{model_id}-*.json"), key=lambda p: p.name)
        return self.read_run(found[-1]) if found else None

    def hours_for(
        self, place_id: str, models: Sequence[Model], hours: Sequence[dt.datetime]
    ) -> PlaceHours:
        runs, values = {}, {}
        for model in models:
            doc = self.latest_run(place_id, model.id)
            runs[model.id] = None if doc is None else {k: v for k, v in doc.items() if k != "steps"}
            values[model.id] = tuple(_hour_value(doc, model, t) for t in hours)
        return PlaceHours(tuple(hours), runs, values)


def _hour_value(doc: dict | None, model: Model, t: dt.datetime) -> dict:
    """The stored step for hour ``t``, or why there is none (F1-1's three reasons)."""
    if doc is None:
        return {"missing": "no_run"}
    run_time = dt.datetime.fromisoformat(doc["run_time"].replace("Z", "+00:00"))
    step = (t - run_time) / dt.timedelta(hours=1)
    expected = doc["steps_expected"]
    if not step.is_integer() or not expected[0] <= step <= expected[-1]:
        return {"missing": "no_run"}  # the run doesn't reach this hour
    if int(step) not in expected:
        return {"missing": "off_step"}  # between a 3-hourly model's steps
    for s in doc["steps"]:
        if s["step"] == int(step):
            return s
    return {"missing": "partial"}  # the run lacks this step (not fetched or not verified)


def write_atomic(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Write ``data`` to ``path``: temp file in the same folder, fsync, chmod, rename,
    then fsync the folder. Nothing is left beside ``path`` on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    fsync_dir(path.parent)


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = ["PlaceHours", "PlaceStore", "StoredFile", "run_document", "utc_text", "write_atomic"]
