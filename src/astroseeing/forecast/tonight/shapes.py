"""The inputs of ``tonight()`` (F1 spec Module 5): ``HourTable`` and ``SunTrack``.

Both are plain, checked values, so a test can write a night by hand and the store and
the Sun scan can build the same shapes. They check only that they fit together (24
hourly rows, one value per row, reasons that agree with the run); the rules live in
``tonight.rules``.
"""

from __future__ import annotations

import datetime as dt
import itertools
import math
from dataclasses import dataclass
from typing import Literal

#: Why a model has no value for an hour (never filled, D48 item 4). ``off_step``: the
#: model has no step at this hour (IFS's in-between hours); ``no_run``: no usable run
#: for this hour (the model has none, or its run doesn't reach the hour: D84, as the
#: store writes it); ``partial``: its run lacks this step. A stale run is not a reason
#: here: its values stay in the table and ``tonight()`` leaves them out of the counts
#: (D48 item 5).
MissingReason = Literal["off_step", "no_run", "partial"]
MISSING_REASONS: tuple[str, ...] = ("off_step", "no_run", "partial")

HOURS_PER_NIGHT = 24
_HOUR = dt.timedelta(hours=1)


def check_utc(name: str, t: dt.datetime) -> None:
    """Refuse anything but a timezone-aware UTC datetime."""
    if not isinstance(t, dt.datetime) or t.tzinfo is None or t.utcoffset() != dt.timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime, got {t!r}")


def utc_text(t: dt.datetime | None) -> str | None:
    """A UTC time as the page files write it, ``YYYY-MM-DDTHH:MM:SSZ`` (None stays None)."""
    return None if t is None else t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_rows(name: str, hours: tuple[dt.datetime, ...]) -> None:
    if len(hours) != HOURS_PER_NIGHT:
        raise ValueError(f"{name} must hold {HOURS_PER_NIGHT} hourly rows, got {len(hours)}")
    for t in hours:
        check_utc(f"{name} row", t)
        if (t.minute, t.second, t.microsecond) != (0, 0, 0):
            raise ValueError(f"{name} rows must be at hh:00 UTC, got {t.isoformat()}")
    for a, b in itertools.pairwise(hours):
        if b - a != _HOUR:
            raise ValueError(f"{name} rows must be consecutive hours: {a} then {b}")


@dataclass(frozen=True)
class RunInfo:
    """The run that supplied a model's values: manifest run id and UTC run time."""

    run_id: int
    run_time: dt.datetime

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, int) or self.run_id < 1:
            raise ValueError(f"run_id must be a positive integer, got {self.run_id!r}")
        check_utc("run_time", self.run_time)


@dataclass(frozen=True)
class HourValue:
    """One model's value at one hour: unrounded total cloud (%) and its O&S
    free-atmosphere J (m^(1/3)), or ``None`` where the column gives no J."""

    total_cloud_pct: float
    j_free_atmosphere: float | None

    def __post_init__(self) -> None:
        c = self.total_cloud_pct
        if not (isinstance(c, (int, float)) and math.isfinite(c) and 0.0 <= c <= 100.0):
            raise ValueError(f"total cloud must be a finite percentage in [0, 100], got {c!r}")
        j = self.j_free_atmosphere
        if j is not None and not (isinstance(j, (int, float)) and math.isfinite(j) and j > 0):
            raise ValueError(f"J must be finite and positive, or None, got {j!r}")


@dataclass(frozen=True)
class Missing:
    """No value for this hour, and why (never filled, D48 item 4)."""

    reason: MissingReason

    def __post_init__(self) -> None:
        if self.reason not in MISSING_REASONS:
            raise ValueError(f"unknown missing reason {self.reason!r}; known: {MISSING_REASONS}")


@dataclass(frozen=True)
class ModelHours:
    """One forecast model's values for each row of Tonight, from one run (D48 item 5)."""

    model: str
    family: str
    regional: bool
    run: RunInfo | None
    values: tuple[HourValue | Missing, ...]

    def __post_init__(self) -> None:
        if len(self.values) != HOURS_PER_NIGHT:
            raise ValueError(f"{self.model}: {len(self.values)} values for "
                             f"{HOURS_PER_NIGHT} rows")  # fmt: skip
        for v in self.values:
            if not isinstance(v, (HourValue, Missing)):
                raise ValueError(f"{self.model}: a value must be HourValue or Missing, got {v!r}")
            if self.run is None and not (isinstance(v, Missing) and v.reason == "no_run"):
                raise ValueError(f"{self.model} has no run, so every hour must be "
                                 f"Missing('no_run')")  # fmt: skip


@dataclass(frozen=True)
class HourTable:
    """Every model's values for the 24 hourly rows of one Night (UTC hh:00 from local
    mean solar noon to the next one; spec Module 5)."""

    night: dt.date
    hours: tuple[dt.datetime, ...]
    models: tuple[ModelHours, ...]

    def __post_init__(self) -> None:
        _check_rows("HourTable", self.hours)
        ids = [m.model for m in self.models]
        if len(set(ids)) != len(ids):
            raise ValueError(f"a model appears twice: {ids}")
        families = [m.family for m in self.models]
        if len(set(families)) != len(families):
            # D45 item 2: a place uses one version of each family.
            raise ValueError(f"a family appears twice (one version per family): {families}")


@dataclass(frozen=True)
class SunTrack:
    """The Sun over one Night: its geometric altitude at each hh:00 row, and the Night's
    sunset and sunrise (Sun's centre at -0.833°). Built by ``sun_track`` from the
    Skyfield-based solar module, or by hand in tests."""

    night: dt.date
    start: dt.datetime  # local mean solar noon on the evening date
    end: dt.datetime  # the next local mean solar noon
    hours: tuple[dt.datetime, ...]
    altitude_deg: tuple[float, ...]
    sunset: dt.datetime
    sunrise: dt.datetime

    def __post_init__(self) -> None:
        for name in ("start", "end", "sunset", "sunrise"):
            check_utc(name, getattr(self, name))
        _check_rows("SunTrack", self.hours)
        if len(self.altitude_deg) != HOURS_PER_NIGHT:
            raise ValueError(f"SunTrack needs {HOURS_PER_NIGHT} altitudes, "
                             f"got {len(self.altitude_deg)}")  # fmt: skip
        if not all(math.isfinite(a) and -90.0 <= a <= 90.0 for a in self.altitude_deg):
            raise ValueError("Sun altitudes must be finite, in [-90, 90] degrees")
        if not (self.start <= self.hours[0] and self.hours[-1] < self.end):
            raise ValueError("the rows must lie within the Night")
        if not self.start < self.sunset < self.sunrise < self.end:
            raise ValueError(f"need start < sunset < sunrise < end, got {self.start}, "
                             f"{self.sunset}, {self.sunrise}, {self.end}")  # fmt: skip
