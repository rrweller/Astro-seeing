"""The latest area grids (F1 spec Module 6, expiring SSD products; ticket #65): what the
map layers need from each forecast model's run, over the whole area on the model's own
grid.

For each verified step, the unrounded total cloud and the Osborn–Sarazin
free-atmosphere J with the observer at the model ground (D60 item 1: a map cell is
seen from each model's own ground), and the model ground itself. J is kept, never
seeing: seeing is computed from J after the values are assigned to the map grid
(spec Module 4).

- :func:`area_run` computes them from a run's fields (a few steps at a time, so a
  whole ICON-EU box never needs more than a few hundred MB);
- :class:`AreaStore` keeps them on the SSD, one ``.npz`` file per area, model and run,
  under ``/staging/forecast/products/areas/<area>/<model>-<run>.npz``: written
  atomically and read back before the run's raw files may go, the newest
  :data:`KEEP_RUNS` per model kept, a failed run's file removed (D86).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from astroseeing.forecast.column import CN2_MODELS, column_products
from astroseeing.forecast.grid import SourceGrid
from astroseeing.forecast.sources.interface import RunFields
from astroseeing.forecast.store import StoredFile, utc_text, write_atomic

log = logging.getLogger(__name__)

AREA_SCHEMA = "forecast-area-run/1"
#: Runs kept per area and model: the newest, and the one before it for when the newest
#: fails after it was stored (its file is then removed and the one before shows).
KEEP_RUNS = 2
#: Steps computed at a time by :func:`area_run`.
STEP_CHUNK = 6


@dataclass(frozen=True, eq=False)
class AreaRun:
    """One run's map values over an area, on the model's own regular grid.

    ``steps`` are the run's verified steps (ascending), each with a row of
    ``total_cloud_pct`` and ``j_free`` (``(len(steps), rows, columns)``; ``j_free`` is
    NaN where the column gives no J). ``steps_expected`` are all the steps the run
    should have, so an hour between steps (``off_step``) is told from one the run
    lacks (``partial``), as the place store tells them."""

    area: str
    model: str
    run_id: int
    run_time: dt.datetime
    steps_expected: tuple[int, ...]
    steps: tuple[int, ...]
    lat: np.ndarray  # the rows' latitudes, in the source's order
    lon: np.ndarray  # the columns' longitudes
    total_cloud_pct: np.ndarray
    j_free: np.ndarray
    model_ground_m: np.ndarray  # (rows, columns)
    provenance: Mapping[str, Any]  # commit, config hash, manifest run id, software

    def __post_init__(self) -> None:
        if self.run_time.tzinfo is None:
            raise ValueError("run_time must be timezone-aware UTC")
        if list(self.steps) != sorted(set(self.steps)) or not set(self.steps) <= set(
            self.steps_expected
        ):
            raise ValueError(f"steps {self.steps} must be ascending and expected")
        shape = (len(self.steps), np.size(self.lat), np.size(self.lon))
        for name in ("total_cloud_pct", "j_free"):
            if np.shape(getattr(self, name)) != shape:
                raise ValueError(f"{name} has shape {np.shape(getattr(self, name))}, "
                                 f"expected {shape}")  # fmt: skip
        if np.shape(self.model_ground_m) != shape[1:]:
            raise ValueError(f"model_ground_m has shape {np.shape(self.model_ground_m)}")

    @property
    def grid(self) -> SourceGrid:
        return SourceGrid(np.asarray(self.lat, float), np.asarray(self.lon, float))

    def to_bytes(self) -> bytes:
        meta = {
            "schema": AREA_SCHEMA,
            "area": self.area,
            "model": self.model,
            "run_id": self.run_id,
            "run_time": utc_text(self.run_time),
            "steps_expected": list(self.steps_expected),
            "steps": list(self.steps),
            "provenance": dict(self.provenance),
        }
        buf = io.BytesIO()
        np.savez_compressed(
            buf,
            meta=np.array(json.dumps(meta)),
            lat=self.lat,
            lon=self.lon,
            total_cloud_pct=self.total_cloud_pct,
            j_free=self.j_free,
            model_ground_m=self.model_ground_m,
        )
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> AreaRun:
        with np.load(io.BytesIO(data), allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            if meta.get("schema") != AREA_SCHEMA:
                raise ValueError(f"not a {AREA_SCHEMA} file")
            arrays = {k: z[k] for k in ("lat", "lon", "total_cloud_pct", "j_free",
                                        "model_ground_m")}  # fmt: skip
        return cls(
            area=meta["area"],
            model=meta["model"],
            run_id=meta["run_id"],
            run_time=dt.datetime.fromisoformat(meta["run_time"].replace("Z", "+00:00")),
            steps_expected=tuple(meta["steps_expected"]),
            steps=tuple(meta["steps"]),
            provenance=meta["provenance"],
            **arrays,
        )

    def same_as(self, other: AreaRun) -> bool:
        """Equal in every value (NaN equal to NaN): the read-back check."""
        meta = ("area", "model", "run_id", "run_time", "steps_expected", "steps", "provenance")
        if any(getattr(self, k) != getattr(other, k) for k in meta):
            return False
        arrays = ("lat", "lon", "total_cloud_pct", "j_free", "model_ground_m")
        return all(
            np.array_equal(getattr(self, k), getattr(other, k), equal_nan=True) for k in arrays
        )


def area_run(
    fields: RunFields,
    area: str,
    verified_steps: Sequence[int],
    run_id: int,
    cn2_model: str,
    provenance: Mapping[str, Any],
) -> AreaRun:
    """The map values of a run's ``verified_steps`` over the whole area: total cloud as
    read, and ``cn2_model``'s free-atmosphere J at the model ground."""
    run_t0 = np.datetime64(fields.run.run_time.replace(tzinfo=None), "s")
    step_of = ((fields.valid_times - run_t0) // np.timedelta64(1, "h")).astype(int).tolist()
    keep = [k for k, s in enumerate(step_of) if s in verified_steps]
    grid = SourceGrid.from_fields(fields.lat, fields.lon)  # refuses a turned grid
    j = np.empty((len(keep), *fields.grid_shape))
    model = {cn2_model: CN2_MODELS[cn2_model]}
    for start in range(0, len(keep), STEP_CHUNK):
        chunk = keep[start : start + STEP_CHUNK]
        part = _steps(fields, chunk)
        products = column_products(part, observer_height_m=part.model_ground_m, cn2_models=model)
        j[start : start + len(chunk)] = products[cn2_model].j_free
    return AreaRun(
        area=area,
        model=fields.model.id,
        run_id=run_id,
        run_time=fields.run.run_time,
        steps_expected=tuple(fields.model.steps_h),
        steps=tuple(step_of[k] for k in keep),
        lat=grid.lats,
        lon=grid.lons,
        total_cloud_pct=np.asarray(fields.total_cloud_pct, dtype=np.float64)[keep],
        j_free=j,
        model_ground_m=np.asarray(fields.model_ground_m, dtype=np.float64).copy(),
        provenance=dict(provenance),
    )


def _steps(f: RunFields, keep: list[int]) -> RunFields:
    """The run's fields at the steps ``keep`` (indices)."""

    def cut(a):
        return None if a is None else np.asarray(a)[keep]

    return RunFields(
        run=f.run,
        model=f.model,
        lat=f.lat,
        lon=f.lon,
        valid_times=f.valid_times[keep],
        pressure_hpa=f.pressure_hpa,
        geopotential_height_m=cut(f.geopotential_height_m),
        temperature_k=cut(f.temperature_k),
        u_ms=cut(f.u_ms),
        v_ms=cut(f.v_ms),
        level_cloud_pct=cut(f.level_cloud_pct),
        total_cloud_pct=cut(f.total_cloud_pct),
        low_cloud_pct=cut(f.low_cloud_pct),
        mid_cloud_pct=cut(f.mid_cloud_pct),
        high_cloud_pct=cut(f.high_cloud_pct),
        surface_pressure_hpa=cut(f.surface_pressure_hpa),
        model_ground_m=f.model_ground_m,
        fog={k: cut(v) for k, v in f.fog.items()},
        run_id=f.run_id,
        qc=f.qc,  # the cloud range rule's counts over the whole run, as read
    )


class AreaStore:
    """The latest area grids on the SSD, under ``root`` (``products/areas``)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, area: str, model: str, run_time: dt.datetime) -> Path:
        return self.root / area / f"{model}-{run_time.strftime('%Y%m%dT%HZ')}.npz"

    def put_run(self, run: AreaRun) -> StoredFile | None:
        """Write a run atomically and read it back; None (and no file left) if it doesn't
        read back as written. Then the area's older runs of that model go (all but
        :data:`KEEP_RUNS`)."""
        path = self.path_for(run.area, run.model, run.run_time)
        data = run.to_bytes()
        write_atomic(path, data)
        if not AreaRun.from_bytes(path.read_bytes()).same_as(run):
            path.unlink()
            return None
        self.prune(run.area, run.model)
        return StoredFile(path, len(data), hashlib.sha256(data).hexdigest())

    def remove_run(self, area: str, model: str, run_time: dt.datetime) -> bool:
        path = self.path_for(area, model, run_time)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _paths(self, area: str, model: str) -> list[Path]:
        """The model's stored runs in the area, oldest first (the names sort by time)."""
        return sorted((self.root / area).glob(f"{model}-*.npz"))

    def newest(self, area: str, model: str) -> AreaRun | None:
        paths = self._paths(area, model)
        return AreaRun.from_bytes(paths[-1].read_bytes()) if paths else None

    def prune(self, area: str, model: str, keep: int = KEEP_RUNS) -> list[Path]:
        gone = self._paths(area, model)[:-keep]
        for p in gone:
            p.unlink()
        if gone:
            log.info("area grids: %d older %s run(s) of %s removed", len(gone), model, area)
        return gone


__all__ = ["AREA_SCHEMA", "AreaRun", "AreaStore", "area_run"]
