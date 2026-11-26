"""The run rules (F1 spec Module 2; D51 items 5, 7 and 14; ticket #58, D79), as pure
functions of the clock, the settings and a run's records. The tick applies them.

- **Retries:** each step's files are tried at most ``file_retries`` (5) times in all,
  on any host and over any number of ticks, never sooner than ``retry_spacing_min``
  (1 min) after the step's last try. A step out of tries stays missing, with its
  reason; the run is then final for it.
- **Late:** the newest run that should be out by now is late from its publish delay
  + ``late_after_delay_h`` (3 h) until it is seen. Logged only.
- **Abandoned:** a run still fetching is given up when a newer run of the same model
  and area is complete (``processed``), or ``abandon_before_window_end_h`` (4 h)
  before the end of the source's online window (ICON-EU: 24 - 4 = 20 h after the run).
- **Fallback host:** a model uses its fallback host only once its main host has
  failed for ``fallback_after_main_failed_h`` (1 h), and returns to the main host as
  soon as the main host answers again (the tick checks it first on every tick).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from astroseeing.forecast.settings import Model, RunRules
from astroseeing.forecast.sources.interface import RunRef
from astroseeing.forecast.verify.records import HostState, StepTry

HOUR = dt.timedelta(hours=1)


@dataclass(frozen=True)
class StepStatus:
    """Where each step of a run stands, from its tries."""

    fetched: tuple[int, ...]  # a try succeeded
    pending: tuple[int, ...]  # not fetched, tries left
    reasons: Mapping[int, str]  # why each step not fetched is missing (out of tries too)

    @property
    def final(self) -> bool:
        """No step is left to try: the run's raw files can go once it is processed."""
        return not self.pending


def step_status(
    steps: Sequence[int], tries: Mapping[int, Sequence[StepTry]], rules: RunRules
) -> StepStatus:
    fetched, pending, reasons = [], [], {}
    for s in steps:
        ts = tries.get(s, ())
        if any(t.error is None for t in ts):
            fetched.append(s)
        elif not ts:
            pending.append(s)
            reasons[s] = "not tried yet"
        elif len(ts) >= rules.file_retries:
            reasons[s] = f"{len(ts)} tries failed; last: {ts[-1].error}"
        else:
            pending.append(s)
            reasons[s] = f"try {len(ts)} of {rules.file_retries} failed: {ts[-1].error}"
    return StepStatus(tuple(fetched), tuple(pending), reasons)


def ready_steps(
    steps: Sequence[int],
    tries: Mapping[int, Sequence[StepTry]],
    rules: RunRules,
    now: dt.datetime,
) -> list[int]:
    """The steps to try now, in order: tries left, and the last try at least the
    spacing ago."""
    spacing = dt.timedelta(minutes=rules.retry_spacing_min)
    return [
        s
        for s in sorted(step_status(steps, tries, rules).pending)
        if not tries.get(s) or now - tries[s][-1].at >= spacing
    ]


def window_end_abandon_at(run_time: dt.datetime, model: Model, rules: RunRules) -> dt.datetime:
    """When a run still fetching is given up because its source is about to drop it."""
    return run_time + (model.online_window_h - rules.abandon_before_window_end_h) * HOUR


def abandon_reason(
    run_time: dt.datetime,
    model: Model,
    rules: RunRules,
    now: dt.datetime,
    newer_complete: dt.datetime | None,
) -> str | None:
    """Why a run still fetching is given up now, or None. ``newer_complete`` is the run
    time of the newest complete run of the same model and area, if any."""
    if newer_complete is not None and newer_complete > run_time:
        return f"the newer run {newer_complete:%Y-%m-%dT%HZ} is complete"
    at = window_end_abandon_at(run_time, model, rules)
    if now >= at:
        return (
            f"{rules.abandon_before_window_end_h:g} h before the end of the source's "
            f"{model.online_window_h:g} h online window ({at:%Y-%m-%dT%H:%MZ})"
        )
    return None


def expected_run(model: Model, rules: RunRules, now: dt.datetime) -> RunRef | None:
    """The newest run that should be out by ``now`` (run time + publish delay)."""
    start = now.replace(minute=0, second=0, microsecond=0)
    for back in range(48):
        t = start - back * HOUR
        if t.hour in model.runs_utc and t + model.publish_delay_h * HOUR <= now:
            return RunRef(model.id, t)
    return None


def late_since(model: Model, rules: RunRules, run: RunRef) -> dt.datetime:
    return run.run_time + (model.publish_delay_h + rules.late_after_delay_h) * HOUR


def late_run(model: Model, rules: RunRules, now: dt.datetime) -> RunRef | None:
    """The newest expected run if it is late by now (the caller checks it was not seen)."""
    run = expected_run(model, rules, now)
    if run is None or now < late_since(model, rules, run):
        return None
    return run


def main_failed_long_enough(state: HostState, rules: RunRules, now: dt.datetime) -> bool:
    since = state.main_failing_since
    return since is not None and now - since >= rules.fallback_after_main_failed_h * HOUR
