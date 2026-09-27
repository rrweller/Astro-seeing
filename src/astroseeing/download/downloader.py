"""Resumable, idempotent downloader driven by the manifest.

One :meth:`Downloader.step` does a single pass:

1. poll every ``submitted`` request; download finished ones; record failures;
2. submit ``planned`` requests until ``max_active`` are in flight at the CDS.

Everything needed to resume lives in the manifest (the CDS request id is stored
as soon as the CDS accepts the request), so the process can be killed at any
point and restarted. Downloads go to ``<staging>/grib/<name>.grib.part``, are
hashed while being read back, fsynced, and renamed; only then is the file row
written. A crash before the row exists just repeats the download.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from astroseeing.download.cds import DONE, FAILED, GONE, PENDING, CdsBackend
from astroseeing.manifest import Manifest, Request, utcnow

log = logging.getLogger(__name__)


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


class Downloader:
    def __init__(
        self,
        manifest: Manifest,
        backend: CdsBackend,
        grib_dir: Path,
        max_active: int = 4,
        delete_remote_after_download: bool = True,
    ):
        self.m = manifest
        self.backend = backend
        self.grib_dir = Path(grib_dir)
        self.grib_dir.mkdir(parents=True, exist_ok=True)
        self.max_active = max_active
        self.delete_remote = delete_remote_after_download

    def target_path(self, req: Request) -> Path:
        return self.grib_dir / f"{safe_name(req.key)}.grib"

    # --- one pass ------------------------------------------------------------------
    def step(self) -> StepSummary:
        s = StepSummary()
        for req in self.m.by_state("submitted"):
            self._poll(req, s)
        active = len(self.m.by_state("submitted"))
        for req in self.m.by_state("planned", limit=max(0, self.max_active - active)):
            self._submit(req)
            s.submitted += 1
        s.pending = len(self.m.by_state("submitted"))
        return s

    def run(self, poll_seconds: float = 60.0, max_seconds: float | None = None) -> StepSummary:
        """Loop until nothing is planned or submitted (or ``max_seconds`` elapse)."""
        t_end = None if max_seconds is None else time.monotonic() + max_seconds
        total = StepSummary()
        while True:
            s = self.step()
            for f in ("submitted", "downloaded", "failed", "resubmit"):
                setattr(total, f, getattr(total, f) + getattr(s, f))
            if not self.m.by_state("planned", "submitted"):
                return total
            if t_end is not None and time.monotonic() > t_end:
                return total
            time.sleep(poll_seconds)

    # --- internals ------------------------------------------------------------------
    def _submit(self, req: Request) -> None:
        try:
            rid = self.backend.submit(req.dataset, req.request)
        except Exception as e:  # network, auth, licence, request-size errors
            log.error("submit %s failed: %s", req.key, e)
            self.m.fail(req.id, ["planned"], f"submit: {e}")
            return
        self.m.transition(
            req.id, ["planned"], "submitted", detail=rid, cds_request_id=rid, submitted_at=utcnow()
        )
        log.info("submitted %s as %s", req.key, rid)

    def _poll(self, req: Request, s: StepSummary) -> None:
        try:
            info = self.backend.info(req.cds_request_id)
        except Exception as e:
            log.warning("poll %s (%s) failed, will retry: %s", req.key, req.cds_request_id, e)
            return
        if info.status in PENDING:
            return
        if info.status in FAILED:
            s.failed += 1
            self.m.fail(req.id, ["submitted"], f"cds {info.status}: {info.error}")
            return
        if info.status in GONE:
            # Result expired or was removed at the CDS: submit again.
            s.resubmit += 1
            self.m.transition(
                req.id, ["submitted"], "planned", detail=f"cds {info.status}", cds_request_id=None
            )
            return
        if info.status != DONE:
            s.failed += 1
            self.m.fail(req.id, ["submitted"], f"unknown cds status {info.status!r}")
            return
        self._download(req, info, s)

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
            try:
                self.backend.delete(req.cds_request_id)
            except Exception as e:  # cleanup at the CDS is a courtesy, not required
                log.warning("could not delete remote %s: %s", req.cds_request_id, e)
