"""Alerts (F1 spec Module 8; D51 item 9, D52 item 10, D82): each condition alerts once
when it starts and once when it clears, through ``astro-notify``, never every tick.

The tick checks four conditions with :class:`TickAlerts`:

* **stale model**: a model has no complete (``processed``) run newer than 24 h in an
  area the tick works (counted from the forecast's first tick, so a new install is not
  stale before it could have fetched anything);
* **run failed**: a model's newest failed run is newer than its newest run with stored
  values (a format change, a failed verification, an unreadable file, or every step out
  of tries; failed runs are never retried, D79 item 6; the message names the model and
  the run's error, which holds the difference);
* **disk low**: ``/staging`` has less than 20 GB free (the tick then skips fetching);
* **page not served**: the served ``latest.json``, fetched over HTTP, fails or differs
  from the one the tick just wrote.

The fifth, **no tick for 1 h**, is the download watcher's (``notify.check_once``): every
finished tick writes a heartbeat (:func:`write_heartbeat`) with the threshold and the
health summary for the 06:00 daily line, and the watcher reads it
(:func:`read_heartbeat`, :func:`daily_line`), so it never reads the forecast's run
records itself (D51 item 6).

Which conditions are active is kept in the manifest (``forecast_alerts``), so a restart
repeats nothing. A start goes out at high priority, a clear at default priority. A send
that fails is logged and not recorded, so the next tick tries it again. Late runs,
retries and partial runs never alert (D51 item 7).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from astroseeing.forecast.http import HttpClient, HttpError
from astroseeing.forecast.settings import ForecastSettings, Model
from astroseeing.forecast.verify.records import ForecastRecords, ForecastRun
from astroseeing.manifest import Manifest

log = logging.getLogger(__name__)

#: ``notify(message, title, priority)``, the same shape as ``notify.check_once``'s send.
Notifier = Callable[[str, str, str], None]

GB = 1e9  # bytes in the settings' gigabytes
PAGE_CHECK_TIMEOUT_S = 10.0
_ERROR_CHARS = 300  # of a run's error, in the alert


@dataclass(frozen=True)
class Condition:
    """One alert condition as checked now: ``key`` names it in the manifest, ``title``
    goes after "astro-seeing: " (and gains " cleared" on the clear)."""

    key: str
    title: str
    active: bool
    start: str  # the message when it starts
    clear: str  # the message when it clears


def log_only(message: str, title: str, priority: str) -> None:
    """The notifier when none is configured: the alert goes to the log only."""
    log.warning("alert (no notifier configured) [%s] %s: %s", priority, title, message)


def phone_notifier() -> Notifier | None:
    """Alerts to Riley's phone through ``astro-notify``'s ntfy topic, or ``None`` (the
    log only, warned) when no topic is configured or its file is readable by others."""
    from astroseeing.notify import ntfy_url, send_ntfy

    try:
        url = ntfy_url()
    except (RuntimeError, PermissionError) as e:
        log.warning("forecast alerts go to the log only: %s", e)
        return None
    return lambda message, title, priority: send_ntfy(url, message, title, priority)


def raise_and_clear(
    manifest: Manifest, conditions: Iterable[Condition], notify: Notifier, now: dt.datetime
) -> list[str]:
    """Send each condition's start or clear if its state changed; return the titles
    sent. Conditions not passed in are left as they are."""
    sent = []
    for c in conditions:
        row = manifest.conn.execute(
            "SELECT key FROM forecast_alerts WHERE key=?", (c.key,)
        ).fetchone()
        if c.active == (row is not None):
            continue
        title = f"astro-seeing: {c.title}" + ("" if c.active else " cleared")
        message, priority = (c.start, "high") if c.active else (c.clear, "default")
        try:
            notify(message, title, priority)
        except Exception:  # a failed send must not stop the tick; tried again next tick
            log.exception("alert not sent (tried again next tick): %s", title)
            continue
        log.warning("alert sent: %s: %s", title, message)
        with manifest.tx() as conn:
            if c.active:
                conn.execute(
                    "INSERT INTO forecast_alerts (key, title, started_at, message)"
                    " VALUES (?,?,?,?)",
                    (c.key, c.title, _iso(now), c.start),
                )
            else:
                conn.execute("DELETE FROM forecast_alerts WHERE key=?", (c.key,))
        sent.append(title)
    return sent


def disk_condition(free_bytes: float, min_free_gb: float) -> Condition:
    free = f"{free_bytes / GB:.1f} GB free"
    return Condition(
        key="disk_low",
        title="forecast disk low",
        active=free_bytes < min_free_gb * GB,
        start=f"Problem: /staging has {free}, below {min_free_gb:.0f} GB: the forecast "
        "tick is not fetching new runs. Historical files are never deleted to make room; "
        "free some space on the CT.",
        clear=f"Cleared: /staging has {free} again; the forecast fetches new runs again.",
    )


def failed_condition(
    model: Model, area: str, failed: ForecastRun | None, good: ForecastRun | None
) -> Condition:
    """Active while the model's newest failed run (``failed``) is newer than its newest
    run with stored values (``good``)."""
    active = failed is not None and (good is None or failed.run_time > good.run_time)
    start = clear = ""
    if failed is not None:
        error = (failed.last_error or "no error recorded")[:_ERROR_CHARS]
        start = (f"Problem: the {model.name} run {_run_text(failed)} for {area} failed and "
                 f"shows as missing: {error}. Its raw files are kept for the fix.")  # fmt: skip
    if good is not None:
        clear = f"Cleared: the {model.name} run {_run_text(good)} for {area} passed its checks."
    return Condition(f"run_failed:{model.id}:{area}", "forecast run failed", active, start, clear)


def stale_condition(
    model: Model,
    area: str,
    complete: ForecastRun | None,
    first_tick: dt.datetime,
    now: dt.datetime,
    limit_h: float,
) -> Condition:
    """Active when the model's newest complete run (``complete``) is more than
    ``limit_h`` old; the clock starts no earlier than the forecast's first tick."""
    since = first_tick if complete is None else max(complete.run_time, first_tick)
    newest = "none yet" if complete is None else f"{_run_text(complete)}, {_age(complete, now)}"
    return Condition(
        key=f"stale:{model.id}:{area}",
        title="forecast model stale",
        active=_hours(now - since) > limit_h,
        start=f"Problem: {model.name} has no complete run newer than {limit_h:.0f} h for "
        f"{area} (newest complete: {newest}). The page shows it as stale, not counted. "
        "Next: `astro forecast status` and `journalctl -u astro-forecast` on the CT.",
        clear=f"Cleared: {model.name} has a complete run for {area} again ({newest}).",
    )


def page_condition(url: str, written: bytes, served: bytes | None, error: str | None) -> Condition:
    """Active when fetching the served ``latest.json`` failed (``error``) or its bytes
    differ from the file the tick just wrote."""
    if error is not None:
        why = f"fetching it failed: {error}"
    elif served != written:
        why = (f"it serves a different latest.json (set {_set_id(served)}) than the one just "
               f"written (set {_set_id(written)})")  # fmt: skip
    else:
        why = None
    return Condition(
        key="page_not_served",
        title="forecast page not served",
        active=why is not None,
        start=f"Problem: the forecast page is not being served at {url}: {why}. Next: "
        "`systemctl status astro-web` on the CT.",
        clear=f"Cleared: the forecast page is served again at {url}.",
    )


class TickAlerts:
    """The alerts one tick checks, sent through ``notify`` (``None``: log only)."""

    def __init__(
        self,
        manifest: Manifest,
        settings: ForecastSettings,
        notify: Notifier | None,
        now: dt.datetime,
    ):
        self.manifest, self.settings, self.now = manifest, settings, now
        self.notify = notify or log_only

    def _send(self, *conditions: Condition) -> list[str]:
        return raise_and_clear(self.manifest, conditions, self.notify, self.now)

    def disk(self, free_bytes: float) -> list[str]:
        return self._send(disk_condition(free_bytes, self.settings.alerts.staging_min_free_gb))

    def page(self, http: HttpClient, latest: Path) -> list[str]:
        """Fetch the served ``latest.json`` and compare it with the file ``latest``."""
        url = self.settings.alerts.served_latest_url
        served = error = None
        try:
            served = http.get(url, timeout_s=PAGE_CHECK_TIMEOUT_S).body
        except HttpError as e:
            error = str(e)
        return self._send(page_condition(url, latest.read_bytes(), served, error))

    def models(self, worked: Iterable[tuple[Model, str]]) -> list[str]:
        """The stale and failed-run alerts of each (model, area) the tick works."""
        records = ForecastRecords(self.manifest)
        beat = read_heartbeat(self.manifest)
        first_tick = self.now if beat is None else beat.first_at
        limit_h = self.settings.alerts.no_complete_run_h
        conditions = []
        for model, area in worked:
            complete = records.latest(model.id, area, states=("processed",))
            conditions.append(stale_condition(model, area, complete, first_tick, self.now, limit_h))
            failed = records.latest(model.id, area, states=("failed",))
            conditions.append(failed_condition(model, area, failed, records.latest(model.id, area)))
        return self._send(*conditions)

    def beat(self, worked: Iterable[tuple[Model, str]]) -> Heartbeat:
        """Write the heartbeat of a finished tick, with each (model, area)'s runs
        completed in the last 24 h and its newest complete run."""
        records = ForecastRecords(self.manifest)
        since = _iso(self.now - dt.timedelta(hours=24))
        health = []
        for model, area in worked:
            (n,) = self.manifest.conn.execute(
                "SELECT COUNT(*) FROM forecast_runs WHERE model=? AND area=?"
                " AND state='processed' AND updated_at >= ?",
                (model.id, area, since),
            ).fetchone()
            newest = records.latest(model.id, area, states=("processed",))
            health.append(
                {
                    "area": area,
                    "model": model.id,
                    "name": model.name,
                    "completed_24h": n,
                    "newest_run_time": None if newest is None else _iso(newest.run_time),
                }
            )
        return write_heartbeat(self.manifest, self.now, self.settings.alerts.no_tick_h, health)


@dataclass(frozen=True)
class Heartbeat:
    """The last finished tick, as the tick wrote it for the download watcher."""

    first_at: dt.datetime  # the forecast's first finished tick
    last_at: dt.datetime
    no_tick_h: float  # the watcher alerts once ``last_at`` is this old
    health: list[dict]  # per area and model: name, completed_24h, newest_run_time


def read_heartbeat(manifest: Manifest) -> Heartbeat | None:
    """The heartbeat, or None if no tick has finished yet."""
    r = manifest.conn.execute("SELECT * FROM forecast_heartbeat WHERE id=1").fetchone()
    if r is None:
        return None
    return Heartbeat(
        first_at=dt.datetime.fromisoformat(r["first_at"]),
        last_at=dt.datetime.fromisoformat(r["last_at"]),
        no_tick_h=r["no_tick_h"],
        health=json.loads(r["health"]),
    )


def write_heartbeat(
    manifest: Manifest, now: dt.datetime, no_tick_h: float, health: list[dict]
) -> Heartbeat:
    """Record a finished tick at ``now`` (the first one is kept as ``first_at``)."""
    with manifest.tx() as c:
        c.execute(
            "INSERT INTO forecast_heartbeat (id, first_at, last_at, no_tick_h, health)"
            " VALUES (1,?,?,?,?) ON CONFLICT (id) DO UPDATE SET last_at=excluded.last_at,"
            " no_tick_h=excluded.no_tick_h, health=excluded.health",
            (_iso(now), _iso(now), no_tick_h, json.dumps(health)),
        )
    beat = read_heartbeat(manifest)
    if beat is None:  # the row was just written in this transaction's connection
        raise RuntimeError("the forecast heartbeat did not read back")
    return beat


def daily_line(beat: Heartbeat, now: dt.datetime) -> str:
    """The forecast line of the 06:00 daily message: runs completed per model in the
    last 24 h before the last tick, and the newest complete run's age at ``now``."""
    parts = []
    for h in beat.health:
        newest = h["newest_run_time"]
        if newest is None:
            age = "no complete run yet"
        else:
            t = dt.datetime.fromisoformat(newest)
            age = f"newest {t:%Y-%m-%d %H}z ({_hours(now - t):.1f} h old)"
        parts.append(f"{h['area']} {h['name']} {h['completed_24h']}, {age}")
    models = "; ".join(parts) or "no model is worked yet"
    return (f"Forecast, runs completed in the last 24 h (as of the {beat.last_at:%H:%M} UTC "
            f"tick): {models}.")  # fmt: skip


def _set_id(latest: bytes | None) -> str:
    try:
        return str(json.loads(latest or b"")["set_id"])
    except (ValueError, KeyError, TypeError):
        return "unreadable"


def _run_text(run: ForecastRun) -> str:
    return f"{run.run_time.astimezone(dt.UTC):%Y-%m-%d %H}z"


def _age(run: ForecastRun, now: dt.datetime) -> str:
    return f"{_hours(now - run.run_time):.1f} h old"


def _hours(d: dt.timedelta) -> float:
    return d / dt.timedelta(hours=1)


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).isoformat(timespec="seconds")
