"""The source-adapter interface (F1 spec Module 1).

Every forecast model gets one adapter with three methods (see :class:`SourceAdapter`):
a cheap check for the newest published run, a fetch of only the needed fields into
``/staging``, and a read that returns :class:`RunFields`, the one shape the rest of
the forecast code sees. ``read`` raises :class:`FormatMismatch` on any difference from
the model's expected content (``configs/forecast.yaml``); nothing is dropped, filled
or regridded silently (D51 item 8).

``RunFields`` checks only that its arrays fit together (shapes, level order, times).
Whether the content is what the model *should* deliver is verification's job
(``forecast.verify``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

import numpy as np

from astroseeing.forecast.settings import FOG_SIGNALS, Area, Model

#: The pressure level whose wind is the classic jet-stream indicator (RESEARCH §3.9).
JET_LEVEL_HPA = 200.0


class FormatMismatch(Exception):
    """A source delivered something other than its expected content (D51 item 8)."""

    def __init__(self, model: str, difference: str):
        super().__init__(f"{model}: format mismatch: {difference}")
        self.model = model
        self.difference = difference


@dataclass(frozen=True)
class RunRef:
    """One run of one forecast model: the model id and its UTC run time."""

    model: str
    run_time: dt.datetime

    def __post_init__(self) -> None:
        t = self.run_time
        if t.tzinfo is None or t.utcoffset() != dt.timedelta(0):
            raise ValueError(f"run_time must be timezone-aware UTC, got {t!r}")
        if (t.minute, t.second, t.microsecond) != (0, 0, 0):
            raise ValueError(f"run_time must be on the hour, got {t.isoformat()}")

    @property
    def label(self) -> str:
        """``20261126T12Z``: used in paths such as ``/staging/forecast/<model>/<run>/``."""
        return self.run_time.strftime("%Y%m%dT%HZ")


@dataclass(frozen=True)
class FetchedFile:
    """One downloaded file, as the manifest records it (spec Module 2, ``forecast_files``)."""

    url: str
    host: str
    path: Path
    bytes: int
    seconds: float
    sha256: str


@dataclass(frozen=True)
class FetchResult:
    """What ``fetch`` downloaded for a run: every file, and each step it could not get."""

    run: RunRef
    area: str
    dest_dir: Path
    files: tuple[FetchedFile, ...]
    steps_h: tuple[int, ...]  # the steps asked for
    missing_steps: Mapping[int, str] = field(default_factory=dict)  # step → reason

    def __post_init__(self) -> None:
        stray = sorted(set(self.missing_steps) - set(self.steps_h))
        if stray:
            raise ValueError(f"missing step {stray[0]} was not asked for (steps {self.steps_h})")

    @property
    def bytes(self) -> int:
        return sum(f.bytes for f in self.files)

    @property
    def fetched_steps(self) -> tuple[int, ...]:
        return tuple(s for s in self.steps_h if s not in self.missing_steps)


@dataclass(frozen=True, eq=False)
class RunFields:
    """One run's fields on the source's own grid, in one common shape (spec Module 1).

    Shapes, with ``G`` the grid shape (``lat.shape``; 2-D for a projected grid such as
    MEPS's, 1-D or 2-D for a regular one), ``S`` the number of steps and ``L`` the
    number of pressure levels:

    - level fields ``(S, *G, L)``, levels **bottom → top** (pressure strictly
      decreasing), the level axis last as ``physics.compute_profile`` expects:
      geopotential height (m), temperature (K), east/north wind (m s⁻¹; grid-relative
      winds are rotated by the adapter), and cloud fraction (%) where the model has it;
    - single-level fields ``(S, *G)``: total, low, mid and high cloud (0-100 %,
      instantaneous), surface pressure (hPa), and the fog signals;
    - ``model_ground_m`` ``(*G)``.

    ``fog`` holds every name in ``FOG_SIGNALS``: an array where the model has the
    signal, ``None`` (absent) where it doesn't, so missing never reads as "no fog".
    """

    run: RunRef
    model: Model
    lat: np.ndarray
    lon: np.ndarray
    valid_times: np.ndarray  # datetime64, UTC, one per step
    pressure_hpa: np.ndarray
    geopotential_height_m: np.ndarray
    temperature_k: np.ndarray
    u_ms: np.ndarray
    v_ms: np.ndarray
    level_cloud_pct: np.ndarray | None
    total_cloud_pct: np.ndarray
    low_cloud_pct: np.ndarray
    mid_cloud_pct: np.ndarray
    high_cloud_pct: np.ndarray
    surface_pressure_hpa: np.ndarray
    model_ground_m: np.ndarray
    fog: Mapping[str, np.ndarray | None]
    run_id: int | None = None  # the manifest's run id, once recorded

    def __post_init__(self) -> None:
        if self.run.model != self.model.id:
            raise ValueError(f"run is for {self.run.model!r} but the fields are {self.model.id!r}")
        lat, lon = np.asarray(self.lat), np.asarray(self.lon)
        if lat.shape != lon.shape or lat.ndim not in (1, 2) or lat.size == 0:
            raise ValueError(f"lat and lon must share a 1-D or 2-D shape, got {lat.shape}, "
                             f"{lon.shape}")  # fmt: skip
        p = np.asarray(self.pressure_hpa, dtype=float)
        if p.ndim != 1 or p.size < 2 or not np.all(np.diff(p) < 0):
            raise ValueError(f"pressure levels must run bottom → top (strictly decreasing "
                             f"pressure), got {p.tolist()}")  # fmt: skip
        if not np.any(p == JET_LEVEL_HPA):
            raise ValueError(f"the levels must include {JET_LEVEL_HPA:g} hPa (200 hPa wind)")
        t = np.asarray(self.valid_times)
        if t.ndim != 1 or t.size == 0 or not np.issubdtype(t.dtype, np.datetime64):
            raise ValueError("valid_times must be a 1-D datetime64 array, one per step")
        if not np.all(np.diff(t) > np.timedelta64(0, "s")):
            raise ValueError("valid_times must be strictly increasing")
        run64 = np.datetime64(self.run.run_time.replace(tzinfo=None), "s")
        if t[0] < run64:
            raise ValueError(f"valid time {t[0]} is before the run time {run64}")
        grid, steps, nlev = lat.shape, t.size, p.size
        level_shape, surface_shape = (steps, *grid, nlev), (steps, *grid)
        for name in ("geopotential_height_m", "temperature_k", "u_ms", "v_ms"):
            _check_shape(name, getattr(self, name), level_shape)
        if self.model.level_cloud and self.level_cloud_pct is None:
            raise ValueError(f"{self.model.id} has level cloud, but level_cloud_pct is None")
        if self.level_cloud_pct is not None:
            _check_shape("level_cloud_pct", self.level_cloud_pct, level_shape)
        for name in ("total_cloud_pct", "low_cloud_pct", "mid_cloud_pct", "high_cloud_pct",
                     "surface_pressure_hpa"):  # fmt: skip
            _check_shape(name, getattr(self, name), surface_shape)
        _check_shape("model_ground_m", self.model_ground_m, grid)
        unknown = sorted(set(self.fog) - set(FOG_SIGNALS))
        if unknown:
            raise ValueError(f"unknown fog signal(s) {unknown}; known: {list(FOG_SIGNALS)}")
        fog = {name: self.fog.get(name) for name in FOG_SIGNALS}
        for name, values in fog.items():
            if values is not None:
                _check_shape(f"fog signal {name}", values, surface_shape)
        object.__setattr__(self, "fog", MappingProxyType(fog))

    @property
    def grid_shape(self) -> tuple[int, ...]:
        return np.shape(self.lat)

    @property
    def n_steps(self) -> int:
        return len(self.valid_times)

    @property
    def level_count(self) -> int:
        return len(self.pressure_hpa)

    @property
    def family(self) -> str:
        return self.model.family

    @property
    def regional(self) -> bool:
        return self.model.regional

    @property
    def wind_200hpa_ms(self) -> tuple[np.ndarray, np.ndarray]:
        """East and north wind at 200 hPa, each ``(S, *G)``."""
        k = int(np.flatnonzero(np.asarray(self.pressure_hpa) == JET_LEVEL_HPA)[0])
        return self.u_ms[..., k], self.v_ms[..., k]


def _check_shape(name: str, values: np.ndarray, expected: tuple[int, ...]) -> None:
    shape = np.shape(values)
    if shape != expected:
        raise ValueError(f"{name} has shape {shape}, expected {expected} "
                         f"(steps, *grid{', levels' if len(expected) > 1 else ''})")  # fmt: skip


class SourceAdapter(Protocol):
    """One forecast model's source (spec Module 1). All HTTP goes through the
    injected ``forecast.http.HttpClient``, so tests swap in a fake server."""

    model: Model
    credit: str  # the short credit beside the model's rows (D44 item 8)

    def latest_published(self, now: dt.datetime) -> RunRef | None:
        """The newest run the source has published by ``now``: a cheap listing, index or
        HEAD check (D51 item 1); ``None`` if none is found."""
        ...

    def fetch(self, run: RunRef, area: Area, steps_h: tuple[int, ...],
              dest_dir: Path) -> FetchResult:  # fmt: skip
        """Download only the needed fields for the area and steps into ``dest_dir``,
        recording every file; retries and host fallback per D51 items 7 and 14."""
        ...

    def read(self, fetched: FetchResult) -> RunFields:
        """Decode a fetch into ``RunFields``; raise ``FormatMismatch`` on any difference
        from the model's expected content."""
        ...
