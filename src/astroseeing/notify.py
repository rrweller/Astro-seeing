"""Phone notifications about long downloads, sent from the CT itself (ntfy).

Riley chose ntfy (2026-09-27): the CT posts one-line status messages to a private,
hard-to-guess topic on ntfy.sh, and he subscribes in the ntfy app. The topic URL
lives outside git in ``~/.config/astro/notify.env`` (``NTFY_URL=...``, mode 600) or
``$ASTRO_NTFY_URL``. Messages never contain keys or data.

``astro notify-watch`` checks the manifest every few minutes and sends:

* **finished**: nothing left to download, verify or ingest (held requests are
  paused on purpose and don't count);
* **problems**: requests that failed ``max_attempts`` times (earlier failures are
  retried by ``scripts/run_boxes.sh``) or were refused by ingest (D18); no progress
  for ``stall_hours``; a request sitting at the CDS for ``stuck_hours``; the download
  loop not running while work remains; the NAS not answering;
* **daily progress**: once a day after ``daily_hour_utc``: done / left / failed,
  and an estimated finish from the fields the CDS processed in the last 24 h.

Its state (what was already reported) is kept in the local state directory so a
restart doesn't repeat messages.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from astroseeing.manifest import Manifest
from astroseeing.paths import Paths, StorageUnresponsive, probe_responsive

log = logging.getLogger(__name__)

PENDING = ("planned", "submitted", "downloaded", "verified")
#: States a request reaches only by making real progress (a finished download or later).
PROGRESS = ("downloaded", "verified", "ingested", "raw_deleted")
DEFAULT_ENV = Path.home() / ".config" / "astro" / "notify.env"


def ntfy_url(env_file: Path = DEFAULT_ENV) -> str:
    """The ntfy topic URL from $ASTRO_NTFY_URL or ``env_file`` (never logged)."""
    url = os.environ.get("ASTRO_NTFY_URL")
    if not url and env_file.is_file():
        mode = env_file.stat().st_mode & 0o777
        if mode & 0o077:  # the topic URL is the only thing keeping the topic private
            raise PermissionError(f"{env_file} has mode {oct(mode)}; run `chmod 600 {env_file}`")
        for line in env_file.read_text().splitlines():
            if line.startswith("NTFY_URL="):
                url = line.split("=", 1)[1].strip()
    if not url:
        raise RuntimeError(f"no ntfy URL: set ASTRO_NTFY_URL or NTFY_URL= in {env_file}")
    return url


def send_ntfy(url: str, message: str, title: str = "astro-seeing", priority: str = "default",
              tags: str = "telescope", timeout: float = 30.0) -> None:  # fmt: skip
    import requests

    r = requests.post(
        url,
        data=message.encode(),
        headers={"Title": title, "Priority": priority, "Tags": tags},
        timeout=timeout,
    )
    r.raise_for_status()


def request_fields(request: dict[str, Any]) -> int:
    """CDS cost of a stored request: variables × levels × times × days × months × years."""
    n = 1
    for key in ("variable", "time", "day", "month", "year"):
        n *= max(1, len(request.get(key) or []))
    return n * max(1, len(request.get("pressure_level") or []))


@dataclass
class Snapshot:
    counts: dict[str, int]
    pending: int  # in flight, plus failed requests that will be retried
    failed: int  # failed for good: max_attempts used up
    last_change: dt.datetime | None  # last real progress (see snapshot)
    fields_left: int
    fields_done_24h: int
    failed_examples: list[str] = field(default_factory=list)
    #: Wall-clock seconds from the first start to the last finish of the requests
    #: finished in the last 24 h (the span that work actually took).
    span_24h_s: float = 0.0
    refused: int = 0  # verified but not stored (D18): needs a person
    #: Keys of requests submitted to the CDS more than ``stuck_hours`` ago.
    stuck: list[str] = field(default_factory=list)
    #: One entry per problem event, "state key @ time": a request failed for good or
    #: refused at that time. A requeued request that fails again is a new event.
    problem_events: list[str] = field(default_factory=list)

    @property
    def done(self) -> int:
        return sum(self.counts.get(s, 0) for s in ("ingested", "raw_deleted"))

    def eta(self, now: dt.datetime) -> dt.datetime | None:
        """Finish estimate from the recent throughput (fields per wall-clock second)."""
        if not self.fields_left or not self.fields_done_24h or self.span_24h_s <= 0:
            return None
        rate = self.fields_done_24h / self.span_24h_s
        return now + dt.timedelta(seconds=self.fields_left / rate)


def snapshot(
    m: Manifest, now: dt.datetime, max_attempts: int = 5, stuck_hours: float = 12.0
) -> Snapshot:
    counts = m.counts()
    rows = m.conn.execute(
        "SELECT key, state, attempts, request_json, created_at, updated_at, submitted_at,"
        " cds_started_at, cds_finished_at, last_error FROM requests"
    ).fetchall()
    # Progress = a request finishing a download (or later), or pending work being
    # planned. Retries of failing requests also touch updated_at, and so do holds and
    # cancellations; none of them is progress (during a CDS outage the loop keeps
    # retrying without progressing).
    stamps = [r["updated_at"] for r in rows if r["state"] in PROGRESS]
    stamps += [r["created_at"] for r in rows if r["state"] in PENDING]
    last = max((dt.datetime.fromisoformat(t) for t in stamps), default=None)
    stuck = [
        r["key"]
        for r in rows
        if r["state"] == "submitted"
        and r["submitted_at"]
        and (now - dt.datetime.fromisoformat(r["submitted_at"])).total_seconds()
        > stuck_hours * 3600
    ]
    left = done24 = 0
    since = now - dt.timedelta(hours=24)
    starts, ends = [], []
    failed_examples = []
    retryable = permanent = 0
    problem_events: list[str] = []
    for r in rows:
        # Everything unfinished counts, including requests the CDS has done but that
        # still await local verify/ingest (a slight overestimate of CDS time, never zero
        # while work is pending).
        retry = r["state"] == "failed" and r["attempts"] < max_attempts
        if r["state"] in PENDING or retry:
            left += request_fields(json.loads(r["request_json"]))
        fin = r["cds_finished_at"]
        if fin and dt.datetime.fromisoformat(fin).astimezone(dt.UTC) >= since:
            done24 += request_fields(json.loads(r["request_json"]))
            ends.append(dt.datetime.fromisoformat(fin).astimezone(dt.UTC))
            if r["cds_started_at"]:
                starts.append(dt.datetime.fromisoformat(r["cds_started_at"]).astimezone(dt.UTC))
        if r["state"] == "failed":
            if r["attempts"] < max_attempts:
                retryable += 1
            else:
                permanent += 1
                failed_examples.append(f"{r['key']}: {(r['last_error'] or '')[:100]}")
                problem_events.append(f"failed {r['key']} @ {r['updated_at']}")
        elif r["state"] == "refused":
            problem_events.append(f"refused {r['key']} @ {r['updated_at']}")
    return Snapshot(
        counts=counts,
        pending=sum(counts.get(s, 0) for s in PENDING) + retryable,
        failed=permanent,
        last_change=last,
        fields_left=left,
        fields_done_24h=done24,
        failed_examples=failed_examples,
        span_24h_s=(max(ends) - min(starts)).total_seconds() if starts and ends else 0.0,
        refused=counts.get("refused", 0),
        stuck=stuck,
        problem_events=problem_events,
    )


@dataclass
class WatchState:
    last_daily: str = ""
    reported_events: list[str] = field(default_factory=list)  # problem events already sent
    stall_alerted_at: str = ""
    stuck_alerted_at: str = ""
    loop_alerted_at: str = ""
    nas_alerted_at: str = ""
    finished_reported: bool = False

    @classmethod
    def load(cls, path: Path) -> WatchState:
        """The saved state; fields from older versions are ignored, not fatal."""
        try:
            d = json.loads(path.read_text())
            return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self)))
        os.replace(tmp, path)


def _hours_since(stamp: str, now: dt.datetime) -> float:
    if not stamp:
        return float("inf")
    return (now - dt.datetime.fromisoformat(stamp)).total_seconds() / 3600


def download_loop_running() -> bool:
    """True if scripts/run_boxes.sh is running (checked with pgrep).

    The pattern is anchored to the end of the command line, so e.g. `tail -f
    logs/run_boxes.log` or a shell mentioning the script don't count.
    """
    r = subprocess.run(["pgrep", "-f", r"run_boxes\.sh$"], capture_output=True, text=True)
    return r.returncode == 0


def check_once(
    m: Manifest,
    state: WatchState,
    send: Callable[[str, str, str], None],
    now: dt.datetime,
    data_root: Path | None = None,
    stall_hours: float = 3.0,
    realert_hours: float = 12.0,
    daily_hour_utc: int = 6,
    max_attempts: int = 5,
    stuck_hours: float = 12.0,
    loop_running: Callable[[], bool] = download_loop_running,
) -> list[str]:
    """One round of checks; returns the messages sent (for tests and logs)."""
    sent: list[str] = []

    def emit(msg: str, title: str = "astro-seeing", priority: str = "default") -> None:
        send(msg, title, priority)
        sent.append(msg)

    s = snapshot(m, now, max_attempts, stuck_hours)

    if data_root is not None:
        try:
            probe_responsive(data_root, timeout_s=60)
        except (StorageUnresponsive, FileNotFoundError) as e:
            if _hours_since(state.nas_alerted_at, now) >= realert_hours:
                emit(f"Problem: the NAS ({data_root}) did not respond: {e}", "astro-seeing: NAS",
                     "high")  # fmt: skip
                state.nas_alerted_at = now.isoformat()

    # Problems are reported per event (request + time), not by comparing counts: a
    # count sampled every few minutes misses a requeue followed by a new refusal.
    new_events = [e for e in s.problem_events if e not in set(state.reported_events)]
    new_failed = [e for e in new_events if e.startswith("failed ")]
    new_refused = [e for e in new_events if e.startswith("refused ")]
    if new_failed:
        example = s.failed_examples[-1] if s.failed_examples else ""
        msg = (f"Problem: {len(new_failed)} download request(s) failed {max_attempts} times "
               f"and need a look ({s.failed} in total). {example}")  # fmt: skip
        emit(msg, "astro-seeing: failures", "high")
    if new_refused:
        emit(f"Problem: {len(new_refused)} downloaded request(s) were refused by ingest (not a "
             "declared validation area, D18) and need a look.", "astro-seeing: refused",
             "high")  # fmt: skip
    state.reported_events = list(s.problem_events)  # keeps the state as small as the problems

    if s.stuck:
        if _hours_since(state.stuck_alerted_at, now) >= realert_hours:
            emit(f"Problem: {len(s.stuck)} request(s) submitted to the CDS more than "
                 f"{stuck_hours:.0f} h ago are not done, e.g. {s.stuck[0]}.",
                 "astro-seeing: stuck at the CDS", "high")  # fmt: skip
            state.stuck_alerted_at = now.isoformat()
    else:
        state.stuck_alerted_at = ""

    if s.pending:
        state.finished_reported = False
        idle = (now - s.last_change).total_seconds() / 3600 if s.last_change else 0.0
        if idle >= stall_hours:
            if _hours_since(state.stall_alerted_at, now) >= realert_hours:
                emit(f"Problem: no download progress for {idle:.1f} h; {s.pending} requests "
                     "still pending.", "astro-seeing: stalled", "high")  # fmt: skip
                state.stall_alerted_at = now.isoformat()
        else:
            state.stall_alerted_at = ""
        if not loop_running():
            if _hours_since(state.loop_alerted_at, now) >= realert_hours:
                emit(f"Problem: the download loop is not running but {s.pending} requests are "
                     "pending.", "astro-seeing: loop stopped", "high")  # fmt: skip
                state.loop_alerted_at = now.isoformat()
        else:
            state.loop_alerted_at = ""
    elif not state.finished_reported and (s.done or s.failed or s.refused):
        held = s.counts.get("held", 0)
        if s.failed or s.refused:
            msg = (f"Queue finished WITH PROBLEMS: {s.done} requests stored and verified, "
                   f"but {s.failed} failed for good and {s.refused} were refused; they need a "
                   f"look ({held} on hold).")  # fmt: skip
            emit(msg, "astro-seeing: finished with problems", "high")
        else:
            msg = (f"Finished: all queued downloads are stored and verified ({s.done} requests; "
                   f"{held} on hold).")  # fmt: skip
            emit(msg, "astro-seeing: downloads finished", "high")
        state.finished_reported = True

    today = now.date().isoformat()
    if now.hour >= daily_hour_utc and state.last_daily != today:
        eta = s.eta(now)
        eta_txt = f"; at the last day's pace, done around {eta:%a %d %b %H:%M} UTC" if eta else ""
        emit(f"Daily: {s.done} requests done, {s.pending} pending, {s.failed} failed"
             f"{eta_txt}.", "astro-seeing: daily progress", "low")  # fmt: skip
        state.last_daily = today
    return sent


def watch(
    paths: Paths,
    interval_s: float = 600.0,
    send: Callable[[str, str, str], None] | None = None,
    **kw: Any,
) -> None:
    """Run :func:`check_once` forever (Ctrl-C to stop)."""
    url = ntfy_url()
    send = send or (lambda msg, title, prio: send_ntfy(url, msg, title=title, priority=prio))
    state_path = paths.state_dir / "notify_state.json"
    while True:
        state = WatchState.load(state_path)
        m = Manifest(paths.manifest)
        try:
            for msg in check_once(m, state, send, dt.datetime.now(dt.UTC), paths.data_root, **kw):
                log.info("notified: %s", msg)
        except Exception:  # a failed send must not stop the watcher
            log.exception("notify check failed")
        finally:
            m.close()
        state.save(state_path)
        time.sleep(interval_s)
