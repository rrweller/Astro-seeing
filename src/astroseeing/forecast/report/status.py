"""``astro forecast status`` (ticket #60; spec #47's CLI): for each model and area, its
latest runs with state, age and steps verified, whether its newest usable run is stale,
and when the tick last ran. Read only.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass

from astroseeing.forecast.report.readonly import ReadOnlyManifest, RunRecord
from astroseeing.forecast.settings import ForecastSettings
from astroseeing.forecast.store import utc_text
from astroseeing.forecast.verify.records import USABLE_STATES

MISSING = "missing"


@dataclass(frozen=True)
class ModelStatus:
    model: str
    area: str
    runs: Sequence[RunRecord]  # newest first, at most the asked-for number
    newest_usable: RunRecord | None


@dataclass(frozen=True)
class Status:
    now: dt.datetime
    last_tick: dt.datetime | None
    stale_after_h: float
    models: Sequence[ModelStatus]


def _usable(r: RunRecord) -> bool:
    """As ``ForecastRecords.latest`` (keep the two alike): an abandoned run counts only
    if it stored values."""
    return r.state in USABLE_STATES and (r.state != "abandoned" or r.derived_bytes is not None)


def forecast_status(
    manifest: ReadOnlyManifest, settings: ForecastSettings, now: dt.datetime, runs: int = 4
) -> Status:
    """Each configured model and area (and any other the manifest holds), in the
    settings' order: its ``runs`` newest runs and its newest usable run."""
    by_pair: dict[tuple[str, str], list[RunRecord]] = {}
    for area in settings.areas.values():
        for model in area.models:
            by_pair[(model, area.id)] = []
    for r in manifest.runs():
        by_pair.setdefault((r.model, r.area), []).append(r)
    models = []
    for (model, area), records in by_pair.items():
        newest_first = sorted(records, key=lambda r: r.run_time, reverse=True)
        usable = [r for r in newest_first if _usable(r)]
        models.append(
            ModelStatus(model, area, tuple(newest_first[:runs]), usable[0] if usable else None)
        )
    return Status(now, manifest.last_tick(), settings.run_rules.stale_after_h, tuple(models))


def _age_h(now: dt.datetime, t: dt.datetime) -> float:
    return (now - t) / dt.timedelta(hours=1)


def format_status(status: Status) -> str:
    now = status.now
    tick = status.last_tick
    lines = [
        f"forecast status at {utc_text(now)}",
        "last tick: not recorded (no tick heartbeat in this manifest)"
        if tick is None
        else f"last tick: {utc_text(tick)}, {_age_h(now, tick) * 60:.0f} min ago",
    ]
    for m in status.models:
        lines.append("")
        head = f"{m.model} {m.area}: "
        u = m.newest_usable
        if u is None:
            head += "no usable run"
        else:
            age = _age_h(now, u.run_time)
            stale = (
                f"stale (over {status.stale_after_h:g} h)"
                if age > status.stale_after_h
                else "not stale"
            )
            head += f"newest usable run {utc_text(u.run_time)}, {age:.1f} h old, {stale}"
        lines.append(head)
        if not m.runs:
            lines.append("  no runs recorded")
            continue
        lines.append(f"  {'run time':<21} {'state':<10} {'age h':>6}  steps verified")
        for r in m.runs:
            ok = r.steps_ok
            steps = MISSING if ok is None else f"{ok}/{len(r.steps_expected)}"
            age = _age_h(now, r.run_time)
            lines.append(f"  {utc_text(r.run_time):<21} {r.state:<10} {age:>6.1f}  {steps}")
    return "\n".join(lines) + "\n"
