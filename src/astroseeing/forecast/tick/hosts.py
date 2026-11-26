"""Which host a model is fetched from this tick (D51 item 14; ticket #58, D79).

Every tick first asks the **main** host for the model's newest run (the adapter's cheap
``latest_published`` check). An answer, even "nothing new", means the main host works:
the model uses it, and a model that was on its fallback comes back to it (logged).
No answer (``HttpError``) starts or continues the main host's failure; once it has
lasted ``fallback_after_main_failed_h`` (1 h) and the model has a fallback host, the
model switches to it (logged once) and asks it instead. Before that, or with no
fallback, nothing is fetched for the model this tick, so a host that is down costs no
tries of any step.

An adapter whose model has a fallback host provides ``on_fallback()``: the same
source, with every request going to the fallback host.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from astroseeing.forecast.http import HttpError
from astroseeing.forecast.settings import Model, RunRules
from astroseeing.forecast.sources.interface import RunRef, SourceAdapter
from astroseeing.forecast.verify.records import ForecastRecords, HostState
from astroseeing.forecast.verify.rules import main_failed_long_enough

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HostPick:
    """The adapter to fetch with this tick (None: no host answered), the host's name
    from the settings, and the newest run that host has published."""

    adapter: SourceAdapter | None
    host: str | None
    newest: RunRef | None


NO_HOST = HostPick(None, None, None)


def pick_host(
    model: Model,
    adapter: SourceAdapter,
    records: ForecastRecords,
    rules: RunRules,
    now: dt.datetime,
) -> HostPick:
    state = records.host_state(model.id)
    main, fallback = model.hosts.main, model.hosts.fallback
    try:
        newest = adapter.latest_published(now)
    except HttpError as e:
        since = state.main_failing_since or now
        failing = HostState(state.current, since, state.switched_at)
        if fallback is None or not main_failed_long_enough(failing, rules, now):
            log.warning(
                "%s: main host %s has not answered since %s (%s); no fetch this tick",
                model.id,
                main.name,
                f"{since:%Y-%m-%dT%H:%MZ}",
                e,
            )
            records.set_host_state(model.id, failing, at=now)
            return NO_HOST
        if state.current != "fallback":
            log.warning(
                "%s: main host %s has failed since %s (%s); switching to the fallback host %s",
                model.id,
                main.name,
                f"{since:%Y-%m-%dT%H:%MZ}",
                e,
                fallback.name,
            )
            failing = HostState("fallback", since, now)
        records.set_host_state(model.id, failing, at=now)
        on_fallback = getattr(adapter, "on_fallback", None)
        if on_fallback is None:
            raise TypeError(
                f"the settings give {model.id} the fallback host {fallback.name}, "
                "but its adapter has no on_fallback()"
            ) from None
        other = on_fallback()
        try:
            return HostPick(other, fallback.name, other.latest_published(now))
        except HttpError as e2:
            log.warning(
                "%s: the fallback host %s does not answer either: %s", model.id, fallback.name, e2
            )
            return NO_HOST
    if state.current == "fallback":
        log.warning(
            "%s: main host %s answers again; back to it from %s",
            model.id,
            main.name,
            fallback.name if fallback else "?",
        )
        records.set_host_state(model.id, HostState("main", None, now), at=now)
    elif state.main_failing_since is not None:
        log.info("%s: main host %s answers again", model.id, main.name)
        records.set_host_state(model.id, HostState("main", None, state.switched_at), at=now)
    return HostPick(adapter, main.name, newest)
