"""``tonight()``: the single implementation of the verdict rules (D48; spec Module 5).

A pure function with no I/O: given every model's hourly values for Tonight, the Sun
over Tonight, and ``now``, it returns the structured verdict. The per-place file, the
map layers and the cell cards all call it, so they can't disagree (D48 item 11).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple

from astroseeing.forecast.settings import CloudClasses
from astroseeing.forecast.tonight.shapes import (
    HourTable,
    HourValue,
    Missing,
    ModelHours,
    SunTrack,
    check_utc,
    utc_text,
)
from astroseeing.physics.optics import seeing_arcsec

CloudClass = Literal["clear", "some_cloud", "cloudy"]
Majority = Literal["clear", "some_cloud", "cloudy", "split"]
AgreementState = Literal["mostly_clear", "not_clear", "incomplete"]

Basis = Literal["dark", "sun_below_12", "sun_down"]

#: Sun-altitude limits of the counted-hours bases, in fallback order (D48 item 2).
BASIS_LIMITS_DEG: tuple[tuple[Basis, float], ...] = (
    ("dark", -18.0),
    ("sun_below_12", -12.0),
    ("sun_down", -0.833),
)


class Agreement(NamedTuple):
    """Model agreement in one hour over the counting families with a value (D48 item 4)."""

    state: AgreementState
    clear: int  # families putting the hour in the clear class
    of: int  # families with a value (the denominator)
    majority: Majority | None  # None only when no family has a value


class RunAge(NamedTuple):
    """A model's run with its age at ``now``; stale runs are shown, not counted (D48 item 5)."""

    run_id: int
    run_time: dt.datetime
    age_h: float
    stale: bool


ChipClass = Literal["clear", "some_cloud", "cloudy", "split", "incomplete"]


class Chip(NamedTuple):
    """Consecutive counted hours with one class (D48 item 8). ``start`` and ``end`` are
    the first and last hours' hh:00 times (inclusive), in UTC."""

    cls: ChipClass
    start: dt.datetime
    end: dt.datetime


@dataclass(frozen=True)
class SeeingRange:
    """D48 item 7: each counting family's median O&S free-atmosphere seeing (arcsec,
    500 nm, zenith; uncalibrated) over the counted hours, the median taken on J."""

    min_arcsec: float
    max_arcsec: float
    per_family: Mapping[str, float]


class MepsLine(NamedTuple):
    """D48 item 9: the regional-only model's own line, never counted: hours of the same
    counted hours that it alone puts in the clear class.

    Riley's choice (2026-11-26, D74 item 10): ``counted_hours`` stays Tonight's n,
    ``missing_hours`` reports the counted hours it has no value for, and a stale run's
    hours all count as missing, as for the global models, with ``stale`` set."""

    clear_hours: int
    counted_hours: int
    missing_hours: int
    stale: bool


FamilyState = Literal["ok", "stale", "missing", "partial", "off_step"]


class NothingToCount(NamedTuple):
    """D48 item 10: why there is no verdict.

    ``dark_time_ended``: no counted hour is left before sunrise; ``dark_time_ended_at``
    is when the last counted hour stopped counting (its hh:00 + 30 min, D48 item 3;
    Riley's choice, D74 item 10). ``not_enough_models``: every counted hour left is
    incomplete; ``families`` gives each global family's state."""

    reason: Literal["dark_time_ended", "not_enough_models"]
    dark_time_ended_at: dt.datetime | None
    families: Mapping[str, FamilyState]


@dataclass(frozen=True)
class HourVerdict:
    """One row of Tonight: whether it is past, whether it is counted, and its model
    agreement (computed for every row, counted or not, for the table)."""

    time: dt.datetime
    past: bool
    counted: bool
    agreement: Agreement


@dataclass(frozen=True)
class Tonight:
    """The verdict for Tonight at one place or map cell (D48), structured values only.

    ``counted_hours`` (n), ``clear_hours`` (x) and ``incomplete_hours`` (k) cover the
    counted hours from the current hour on; ``started`` says the Night has begun (local
    mean solar noon), so the headline says "left"; ``current_hour`` is ``None`` before
    then. ``hours`` has all 24 rows; ``runs`` every model that has a run."""

    night: dt.date
    basis: Basis
    started: bool
    current_hour: dt.datetime | None
    counted_hours: int
    clear_hours: int
    incomplete_hours: int
    chips: tuple[Chip, ...]
    seeing: SeeingRange | None  # None: no counting family has seeing tonight
    meps: MepsLine | None  # None: no regional-only model covers the place
    nothing_to_count: NothingToCount | None  # None: there are hours to count
    hours: tuple[HourVerdict, ...]
    runs: Mapping[str, RunAge]  # model id -> its run; models with no run are absent

    def to_json(self) -> dict[str, Any]:
        """The per-place file's ``tonight`` block (schema ``f1-place/1``): structured
        values only, times as UTC ``YYYY-MM-DDTHH:MM:SSZ``; the page writes the wording."""
        s, m, n = self.seeing, self.meps, self.nothing_to_count
        seeing = None
        if s is not None:
            seeing = {"min_arcsec": s.min_arcsec, "max_arcsec": s.max_arcsec,
                      "per_family": dict(sorted(s.per_family.items()))}  # fmt: skip
        nothing = None
        if n is not None:
            ended = utc_text(n.dark_time_ended_at)
            nothing = {"reason": n.reason, "dark_time_ended_at": ended,
                       "families": dict(sorted(n.families.items()))}  # fmt: skip
        runs = {
            model: {
                "run_id": r.run_id,
                "run_time": utc_text(r.run_time),
                "age_h": r.age_h,
                "stale": r.stale,
            }
            for model, r in sorted(self.runs.items())
        }
        chips = [
            {"class": c.cls, "start": utc_text(c.start), "end": utc_text(c.end)} for c in self.chips
        ]
        return {
            "night": self.night.isoformat(),
            "basis": self.basis,
            "started": self.started,
            "current_hour": utc_text(self.current_hour),
            "counted_hours": self.counted_hours,
            "clear_hours": self.clear_hours,
            "incomplete_hours": self.incomplete_hours,
            "chips": chips,
            "seeing": seeing,
            "meps": None if m is None else m._asdict(),
            "nothing_to_count": nothing,
            "runs": runs,
        }


def cloud_class(total_cloud_pct: float, classes: CloudClasses) -> CloudClass:
    """The cloud class of an unrounded total cloud value (D48 item 6)."""
    if total_cloud_pct <= classes.clear_max_pct:
        return "clear"
    if total_cloud_pct <= classes.some_cloud_max_pct:
        return "some_cloud"
    return "cloudy"


def agreement(classes: list[CloudClass]) -> Agreement:
    """Model agreement from the cloud classes of the counting families with a value."""
    n = len(classes)
    tally = Counter(classes)
    clear = tally["clear"]
    winners = [c for c, k in tally.items() if 2 * k > n]
    majority: Majority | None = winners[0] if winners else ("split" if n else None)
    if n < 2:
        state: AgreementState = "incomplete"
    elif 2 * clear > n:
        state = "mostly_clear"
    else:
        state = "not_clear"
    return Agreement(state, clear, n, majority)


def tonight(
    hours: HourTable,
    sun: SunTrack,
    now: dt.datetime,
    *,
    cloud_classes: CloudClasses,
    stale_after_h: float,
) -> Tonight:
    """The verdict rules of D48 applied to one place's (or map cell's) Tonight.

    ``cloud_classes`` and ``stale_after_h`` come from the forecast settings
    (``cloud_classes``, ``run_rules.stale_after_h``). Raises ``ValueError`` when
    ``now`` is not before the Night's sunrise (Tonight would be the next Night), when
    the table and the Sun are for different rows, or when a run time is after ``now``.
    """
    check_utc("now", now)
    if now >= sun.sunrise:
        # From sunrise on, Tonight is the next Night (CONTEXT.md, "Tonight").
        raise ValueError(f"now {now.isoformat()} is at or after this Night's sunrise "
                         f"{sun.sunrise.isoformat()}: Tonight is the next Night")  # fmt: skip
    if hours.night != sun.night or hours.hours != sun.hours:
        raise ValueError("the HourTable and the SunTrack are for different Nights or rows")
    basis, limit = _basis(sun)
    started = now >= sun.start
    current = _current_hour(now) if started else None
    runs = {
        m.model: _run_age(m.run.run_id, m.run.run_time, now, stale_after_h)
        for m in hours.models
        if m.run is not None
    }
    # Only global families count (D45 item 3), and never from a stale run (D48 item 5).
    counting = [m for m in hours.models if not m.regional and not _stale(runs, m)]
    rows = []
    for i, (t, alt) in enumerate(zip(sun.hours, sun.altitude_deg, strict=True)):
        past = current is not None and t < current
        values = [m.values[i] for m in counting]
        classes = [
            cloud_class(v.total_cloud_pct, cloud_classes)
            for v in values
            if isinstance(v, HourValue)
        ]
        rows.append(HourVerdict(t, past, alt < limit and not past, agreement(classes)))
    counted = [r for r in rows if r.counted]
    counted_rows = [i for i, r in enumerate(rows) if r.counted]
    return Tonight(
        night=hours.night,
        basis=basis,
        started=started,
        current_hour=current,
        counted_hours=len(counted),
        clear_hours=sum(r.agreement.state == "mostly_clear" for r in counted),
        incomplete_hours=sum(r.agreement.state == "incomplete" for r in counted),
        chips=_chips(counted),
        seeing=_seeing(counting, counted_rows),
        meps=_meps_line(hours, runs, counted_rows, cloud_classes),
        nothing_to_count=_nothing_to_count(hours, runs, rows, sun, limit, counted_rows),
        hours=tuple(rows),
        runs=runs,
    )


def _meps_line(
    hours: HourTable, runs: Mapping[str, RunAge], counted_rows: list[int], classes: CloudClasses
) -> MepsLine | None:
    regional = [m for m in hours.models if m.regional]
    if not regional:
        return None
    if len(regional) > 1:
        raise ValueError(
            f"F1 has one regional-only model (MEPS), got {[m.model for m in regional]}"
        )
    m = regional[0]
    stale = _stale(runs, m)
    values = [] if stale else [m.values[i] for i in counted_rows]
    present = [v for v in values if isinstance(v, HourValue)]
    clear = sum(cloud_class(v.total_cloud_pct, classes) == "clear" for v in present)
    n = len(counted_rows)
    return MepsLine(clear, n, n - len(present), stale)


def _nothing_to_count(
    hours: HourTable,
    runs: Mapping[str, RunAge],
    rows: list[HourVerdict],
    sun: SunTrack,
    limit: float,
    counted_rows: list[int],
) -> NothingToCount | None:
    if not counted_rows:
        last = max(i for i, a in enumerate(sun.altitude_deg) if a < limit)
        ended = sun.hours[last] + dt.timedelta(minutes=30)
        return NothingToCount("dark_time_ended", ended, {})
    if any(rows[i].agreement.state != "incomplete" for i in counted_rows):
        return None
    families: dict[str, FamilyState] = {}
    for m in hours.models:
        if m.regional:
            continue
        values = [m.values[i] for i in counted_rows]
        reasons = {v.reason for v in values if isinstance(v, Missing)}
        if m.run is None:
            families[m.family] = "missing"
        elif runs[m.model].stale:
            families[m.family] = "stale"
        elif any(isinstance(v, HourValue) for v in values):
            families[m.family] = "ok"
        elif "partial" in reasons:
            families[m.family] = "partial"
        elif "no_run" in reasons:  # its run ends before these hours (D84)
            families[m.family] = "missing"
        else:
            families[m.family] = "off_step"
    return NothingToCount("not_enough_models", None, families)


def _seeing(counting: list[ModelHours], counted_rows: list[int]) -> SeeingRange | None:
    per_family = {}
    for m in counting:
        js = sorted(
            v.j_free_atmosphere
            for i in counted_rows
            if isinstance(v := m.values[i], HourValue) and v.j_free_atmosphere is not None
        )
        if js:  # a family with no J for any counted hour drops out
            per_family[m.family] = float(seeing_arcsec(_median(js)))
    if not per_family:
        return None
    return SeeingRange(min(per_family.values()), max(per_family.values()), per_family)


def _median(sorted_values: list[float]) -> float:
    """The middle value, or the mean of the two middle values for an even count."""
    n = len(sorted_values)
    mid = n // 2
    if n % 2:
        return sorted_values[mid]
    return 0.5 * (sorted_values[mid - 1] + sorted_values[mid])


def _chips(counted: list[HourVerdict]) -> tuple[Chip, ...]:
    chips: list[Chip] = []
    for r in counted:
        a = r.agreement
        # A complete hour (two or more families) always has a majority class or split.
        cls: ChipClass = (
            "incomplete" if a.state == "incomplete" or a.majority is None else a.majority
        )
        last = chips[-1] if chips else None
        if last and last.cls == cls and r.time - last.end == dt.timedelta(hours=1):
            chips[-1] = last._replace(end=r.time)
        else:
            chips.append(Chip(cls, r.time, r.time))
    return tuple(chips)


def _stale(runs: Mapping[str, RunAge], m: ModelHours) -> bool:
    """Whether the model's run is stale (a model with no run has none to be stale)."""
    return m.model in runs and runs[m.model].stale


def _run_age(run_id: int, run_time: dt.datetime, now: dt.datetime, stale_after_h: float) -> RunAge:
    age_h = (now - run_time).total_seconds() / 3600.0
    if age_h < 0:
        raise ValueError(f"run time {run_time.isoformat()} is after now {now.isoformat()}")
    return RunAge(run_id, run_time, age_h, age_h > stale_after_h)


def _basis(sun: SunTrack) -> tuple[Basis, float]:
    for basis, limit in BASIS_LIMITS_DEG:
        if any(a < limit for a in sun.altitude_deg):
            return basis, limit
    raise ValueError("no hour of this Night has the Sun below the horizon")


def _current_hour(now: dt.datetime) -> dt.datetime:
    """The hour containing ``now``: a step at hh:00 counts until hh:30 (D48 item 3)."""
    shifted = now + dt.timedelta(minutes=30)
    return shifted.replace(minute=0, second=0, microsecond=0)
