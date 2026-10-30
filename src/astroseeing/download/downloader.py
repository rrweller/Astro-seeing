"""Resumable, idempotent downloader driven by the manifest.

One :meth:`Downloader.step` does a single pass:

1. poll every ``submitted`` request; record failures and rejections;
2. submit the next ``planned`` request if the CDS gate allows it (below);
3. download the results of jobs that finished, while the new one runs.

The CDS gate (D39; the CDS wants sequential requests since 2026-10-22, D37):

* at most one job queued or running per account, in any dataset. Our own jobs are
  counted from their status, and :meth:`CdsBackend.active_jobs` must also list none
  (it catches jobs from a crash, a timed-out submission or another process). A job
  whose status can't be read counts as running;
* after a rejection (any rejected or failed job, or any submit error) nothing is
  submitted for 60 min, doubling with each further rejection up to 4 h;
* after 3 rejections within 24 h, submissions pause until a person runs
  ``astro cds-resume`` (the notify watcher sends the alert);
* a request whose job the CDS loses (D34) is submitted again at most twice, then
  fails like any other error.

The rejections and the pause live in the manifest, so restarts, ``run_boxes.sh`` and
``astro retry-failed`` can't get around them.

Everything needed to resume lives in the manifest (the CDS request id is stored
as soon as the CDS accepts the request), so the process can be killed at any
point and restarted. Downloads go to ``<staging>/grib/<name>.grib.part``, are
hashed while being read back, fsynced, and renamed; only then is the file row
written. A crash before the row exists just repeats the download.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from astroseeing.download.cds import (
    DONE,
    FAILED,
    GONE,
    PENDING,
    CdsBackend,
    is_queue_limit_rejection,
)
from astroseeing.manifest import LOST_PREFIX, Manifest, Request

log = logging.getLogger(__name__)

#: Hard limit on jobs queued or running at the CDS (D39). Raising it needs Riley's OK:
#: an account was disabled for two concurrent requests (forum.ecmwf.int/t/15481).
MAX_ACTIVE = 1
BACKOFF_FIRST = dt.timedelta(minutes=60)
BACKOFF_MAX = dt.timedelta(hours=4)
#: This many rejections within REJECTION_WINDOW pause all submissions.
REJECTIONS_TO_PAUSE = 3
REJECTION_WINDOW = dt.timedelta(hours=24)
#: A lost job (D34) is submitted again at most this many times, then fails.
MAX_LOST_RESUBMITS = 2


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).isoformat(timespec="seconds")


def safe_name(key: str) -> str:
    return key.replace("/", "__")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class StepSummary:
    submitted: int = 0
    downloaded: int = 0
    failed: int = 0
    resubmit: int = 0
    pending: int = 0
    rejected: int = 0
    paused: bool = False
    backoff_until: dt.datetime | None = None


class Downloader:
    def __init__(
        self,
        manifest: Manifest,
        backend: CdsBackend,
        grib_dir: Path,
        max_active: int = MAX_ACTIVE,
        delete_remote_after_download: bool = True,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ):
        if not 1 <= max_active <= MAX_ACTIVE:
            raise ValueError(
                f"max_active must be 1, got {max_active}: the CDS accepts one request at a "
                "time per account (D39); raising it needs Riley's OK"
            )
        self.m = manifest
        self.backend = backend
        self.grib_dir = Path(grib_dir)
        self.grib_dir.mkdir(parents=True, exist_ok=True)
        self.max_active = max_active
        self.delete_remote = delete_remote_after_download
        self.now = now

    def target_path(self, req: Request) -> Path:
        return self.grib_dir / f"{safe_name(req.key)}.grib"

    # --- one pass ------------------------------------------------------------------
    def step(self) -> StepSummary:
        s = StepSummary()
        in_flight, finished = 0, []
        for req in self.m.by_state("submitted"):
            outcome, info = self._poll(req, s)
            if outcome == "in_flight":
                in_flight += 1
            elif outcome == "finished":
                finished.append((req, info))
        nxt = self.m.by_state("planned", limit=1)
        if nxt and in_flight < self.max_active and self._gate_open():
            if self._submit(nxt[0]):
                s.submitted += 1
            else:
                s.rejected += 1
        # Download only now, so the CDS already works on the next request meanwhile.
        for req, info in finished:
            self._download(req, info, s)
        s.pending = len(self.m.by_state("submitted"))
        s.paused = bool(self.m.cds_control().get("paused_at"))
        s.backoff_until = self.backoff_until()
        return s

    def run(self, poll_seconds: float = 60.0, max_seconds: float | None = None) -> StepSummary:
        """Loop until nothing is planned or submitted (or ``max_seconds`` elapse).

        Returns early when nothing is left at the CDS and submissions are paused or
        backing off: there is nothing to do until then (``run_boxes.sh`` waits and
        calls again).
        """
        t_end = None if max_seconds is None else time.monotonic() + max_seconds
        total = StepSummary()
        while True:
            s = self.step()
            for f in ("submitted", "downloaded", "failed", "resubmit", "rejected"):
                setattr(total, f, getattr(total, f) + getattr(s, f))
            total.paused, total.backoff_until = s.paused, s.backoff_until
            if not self.m.by_state("planned", "submitted"):
                return total
            if (s.paused or s.backoff_until) and not self.m.by_state("submitted"):
                return total
            if t_end is not None and time.monotonic() > t_end:
                return total
            time.sleep(poll_seconds)

    # --- the CDS gate (D39) ---------------------------------------------------------
    def backoff_until(self) -> dt.datetime | None:
        """End of the current backoff, or None when none applies."""
        now = self.now()
        recent = self.m.rejections_since(_iso(now - REJECTION_WINDOW))
        if not recent:
            return None
        delay = min(BACKOFF_FIRST * 2 ** (len(recent) - 1), BACKOFF_MAX)
        until = dt.datetime.fromisoformat(recent[-1]) + delay
        return until if until > now else None

    def _gate_open(self) -> bool:
        if self.m.cds_control().get("paused_at"):
            return False
        if self.backoff_until() is not None:
            return False
        try:
            active = self.backend.active_jobs()
        except Exception as e:  # can't tell what is at the CDS: don't add to it
            log.warning("could not list jobs at the CDS, not submitting: %s", e)
            return False
        if active:
            log.info("%d job(s) queued or running at the CDS (%s); not submitting",
                     len(active), ", ".join(active[:3]))  # fmt: skip
            return False
        return True

    def _rejected(self, req: Request, error: str) -> None:
        """Record a rejection; pause everything after REJECTIONS_TO_PAUSE in the window."""
        now = self.now()
        self.m.record_rejection(req.id, error, at=_iso(now))
        n = len(self.m.rejections_since(_iso(now - REJECTION_WINDOW)))
        if n >= REJECTIONS_TO_PAUSE:
            reason = (f"{n} CDS rejections within {REJECTION_WINDOW.total_seconds() / 3600:.0f} h"
                      f", last {req.key}: {error[:200]}")  # fmt: skip
            self.m.pause_cds(reason, at=_iso(now))
            log.error("CDS submissions paused: %s", reason)
        else:
            log.warning("CDS rejection %d of %d allowed in 24 h; backing off until %s",
                        n, REJECTIONS_TO_PAUSE, self.backoff_until())  # fmt: skip

    # --- internals ------------------------------------------------------------------
    def _submit(self, req: Request) -> bool:
        try:
            rid = self.backend.submit(req.dataset, req.request)
        except Exception as e:  # unknown submit errors count as rejections (D39)
            log.error("submit %s failed (counted as a rejection): %s", req.key, e)
            self._rejected(req, f"submit: {e}")
            return False
        self.m.transition(
            req.id, ["planned"], "submitted", detail=rid, cds_request_id=rid,
            submitted_at=_iso(self.now()),
        )  # fmt: skip
        log.info("submitted %s as %s", req.key, rid)
        return True

    def _poll(self, req: Request, s: StepSummary) -> tuple[str, object]:
        """("in_flight" | "finished" | "done_with", info) for one submitted request."""
        try:
            info = self.backend.info(req.cds_request_id)
        except Exception as e:
            log.warning("poll %s (%s) failed, will retry: %s", req.key, req.cds_request_id, e)
            return "in_flight", None  # unknown, so it may still be running
        if info.status in PENDING:
            return "in_flight", info
        if info.status in FAILED:
            error = f"cds {info.status}: {info.error}"
            self._rejected(req, error)
            if is_queue_limit_rejection(info.error):
                # The request is fine, the CDS queue was full: plan it again (transient).
                s.resubmit += 1
                self.m.transition(
                    req.id,
                    ["submitted"],
                    "planned",
                    detail=f"cds {info.status}: queue limit",
                    cds_request_id=None,
                )
                log.warning("%s rejected by the CDS queue limit; planned again", req.key)
                self._delete_remote(req.cds_request_id)
                return "done_with", info
            s.failed += 1
            self.m.fail(req.id, ["submitted"], error)
            return "done_with", info
        if info.status in GONE:
            # Result expired, or the job was removed or lost at the CDS: submit again,
            # but only MAX_LOST_RESUBMITS times (D39), so it can never loop.
            why = f"cds {info.status}" + (f": {info.error}" if info.error else "")
            lost = self.m.lost_count(req.id)
            if lost >= MAX_LOST_RESUBMITS:
                s.failed += 1
                self.m.fail(req.id, ["submitted"], f"{LOST_PREFIX} {lost + 1} times ({why})")
                return "done_with", info
            s.resubmit += 1
            self.m.transition(
                req.id, ["submitted"], "planned", detail=f"{LOST_PREFIX} ({why})",
                cds_request_id=None,
            )  # fmt: skip
            log.warning("%s: %s; planned again (%d of %d)", req.key, why, lost + 1,
                        MAX_LOST_RESUBMITS)  # fmt: skip
            return "done_with", info
        if info.status != DONE:
            s.failed += 1
            self.m.fail(req.id, ["submitted"], f"unknown cds status {info.status!r}")
            return "done_with", info
        return "finished", info

    def _download(self, req: Request, info, s: StepSummary) -> None:
        final = self.target_path(req)
        part = final.with_suffix(".grib.part")
        t0 = time.monotonic()
        try:
            size = self.backend.download(req.cds_request_id, part)
            if info.content_length is not None and size != info.content_length:
                raise OSError(f"size {size} != server content length {info.content_length}")
            digest = sha256_file(part)
            with open(part, "rb") as f:
                os.fsync(f.fileno())
            os.replace(part, final)
        except Exception as e:
            log.error("download %s failed: %s", req.key, e)
            part.unlink(missing_ok=True)
            s.failed += 1
            self.m.fail(req.id, ["submitted"], f"download: {e}")
            return
        seconds = time.monotonic() - t0
        self.m.add_file(req.id, final, size, digest, seconds)
        self.m.transition(
            req.id,
            ["submitted"],
            "downloaded",
            detail=f"{size} bytes in {seconds:.1f} s",
            cds_started_at=info.started_at,
            cds_finished_at=info.finished_at,
        )
        s.downloaded += 1
        log.info("downloaded %s: %d bytes, %.1f s, sha256 %s", req.key, size, seconds, digest[:12])
        if self.delete_remote:
            self._delete_remote(req.cds_request_id)

    def _delete_remote(self, request_id: str) -> None:
        try:
            self.backend.delete(request_id)
        except Exception as e:  # cleanup at the CDS is a courtesy, not required
            log.warning("could not delete remote %s: %s", request_id, e)
