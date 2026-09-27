"""Manifest-driven stages: verify → ingest → delete raw (AGENTS.md "Data safety").

* :func:`verify_pending`: ``downloaded`` → ``verified`` (or ``failed``); checks the
  file's SHA-256 still matches the manifest, then runs ``verify_grib``.
* :func:`ingest_pending`: ``verified`` → ``ingested``; decodes, writes the Zarr store
  atomically and verifies it bit-for-bit (read-back before and after rename).
* :func:`cleanup_raw`: ``ingested`` → ``raw_deleted``; deletes the raw GRIB only if
  the ingest was verified, the Zarr store still passes a content check, and the
  file lies under the staging directory. Never deletes anything under /data.
  Crash-safe: if a previous run deleted the file but died before the manifest
  update, the next run checks the store against its recorded content hash and
  completes the transition.

Without a land/night mask function, only validation boxes (at most
:data:`MAX_UNMASKED_POINTS` grid points) are ingested; AGENTS.md: "only land cells
(with the 1 km buffer) and night hours … Validation boxes keep all hours".
Larger requests, and any request a ``mask_fn`` refuses by raising
:class:`RefusedUnmasked`, move to the ``refused`` state and are counted as
``refused_unmasked``. That is neither a failure (nothing is retried or re-downloaded)
nor pending work (unattended loops don't wait on it); ``Manifest.requeue_refused``
puts such requests back to ``verified`` once a suitable mask exists.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np

from astroseeing.download.downloader import sha256_file
from astroseeing.ingest.decode import decode_grib
from astroseeing.ingest.store import compare_store, prepare, self_check_store, write_store_atomic
from astroseeing.manifest import Manifest, Request
from astroseeing.paths import probe_responsive
from astroseeing.provenance import era5_attribution, provenance
from astroseeing.verify.grib import verify_grib

log = logging.getLogger(__name__)

#: Largest request grid (points) that may be stored without a land/night mask:
#: validation boxes only (11×11 points covers a ±1.25° box).
MAX_UNMASKED_POINTS = 121

#: Optional hook returning (cell_mask, keep_hours) for a request; None → grid layout.
MaskFn = Callable[[Request, "object"], tuple[np.ndarray | None, np.ndarray | None]]


class RefusedUnmasked(ValueError):
    """A mask function declines to store a request (D18): not a failure, not retried."""


def store_path(data_root: Path, req: Request) -> Path:
    return Path(data_root) / "era5" / req.kind / req.region / f"{req.period}.zarr"


def verify_pending(m: Manifest) -> dict[str, int]:
    out = {"verified": 0, "failed": 0}
    for req in m.by_state("downloaded"):
        f = m.current_file(req.id)
        path = Path(f["path"])
        try:
            digest = sha256_file(path)
            if digest != f["sha256"]:
                raise OSError(f"sha256 changed since download: {digest} != {f['sha256']}")
            rep = verify_grib(path, req.expected)
        except Exception as e:
            m.add_verification(f["id"], False, {"error": str(e)})
            m.fail(req.id, ["downloaded"], f"verify: {e}")
            out["failed"] += 1
            continue
        m.add_verification(f["id"], rep.ok, rep.as_dict())
        if rep.ok:
            m.transition(req.id, ["downloaded"], "verified", detail=f"{rep.n_messages} messages")
            out["verified"] += 1
            for w in rep.warnings:
                log.warning("%s: %s", req.key, w)
        else:
            m.fail(req.id, ["downloaded"], "verify: " + "; ".join(rep.problems[:5]))
            out["failed"] += 1
    return out


def ingest_pending(
    m: Manifest,
    data_root: Path,
    config: dict,
    mask_fn: MaskFn | None = None,
    probe_timeout_s: float = 60.0,
    max_unmasked_points: int = MAX_UNMASKED_POINTS,
) -> dict[str, int]:
    out = {"ingested": 0, "already_present": 0, "failed": 0, "refused_unmasked": 0}
    todo = m.by_state("verified")
    if todo:
        probe_responsive(Path(data_root), probe_timeout_s)

    def refuse(req: Request, why: str) -> None:
        log.error("%s: %s; refused (state 'refused', D18)", req.key, why)
        m.transition(req.id, ["verified"], "refused", detail=why)
        out["refused_unmasked"] += 1

    for req in todo:
        if mask_fn is None:
            g = req.expected["grid"]
            npts = g["nlat"] * g["nlon"]
            if npts > max_unmasked_points:
                refuse(req, f"{npts} grid points > {max_unmasked_points} and no land/night mask")
                continue
        # A mask function may refuse from the request alone (``mask_fn.preflight``), so
        # an unmasked large request (e.g. a global day) is never decoded into memory.
        preflight = getattr(mask_fn, "preflight", None)
        if preflight is not None:
            try:
                preflight(req)
            except RefusedUnmasked as e:
                refuse(req, str(e))
                continue
        f = m.current_file(req.id)
        try:
            dec = decode_grib(Path(f["path"]), req.expected)
            try:
                cell_mask, keep = mask_fn(req, dec) if mask_fn else (None, None)
            except RefusedUnmasked as e:
                refuse(req, str(e))
                continue
            prep = prepare(dec, cell_mask, keep)
            prov = provenance(
                config,
                manifest_ids={
                    "request_id": req.id,
                    "request_key": req.key,
                    "request_hash": req.request_hash,
                    "cds_request_id": req.cds_request_id,
                    "file_id": f["id"],
                    "file_sha256": f["sha256"],
                },
            )
            attrs = {
                "provenance": prov,
                **era5_attribution(req.dataset, dt.datetime.now(dt.UTC).year),
                "source_dataset": req.dataset,
                "layout": "cells" if cell_mask is not None else "grid",
            }
            res = write_store_atomic(store_path(data_root, req), prep, attrs)
        except Exception as e:
            log.exception("ingest %s failed", req.key)
            m.fail(req.id, ["verified"], f"ingest: {e}")
            out["failed"] += 1
            continue
        res.qc.log(log, context=f"{req.key} ")
        report = {
            "already_present": res.already_present,
            "layout": attrs["layout"],
            "qc": res.qc.as_dict(),
        }
        if res.already_present:
            # The manifest records the provenance the store carries (the run that
            # wrote it); this run's identity is noted alongside.
            report["this_run"] = {"git": prov["git"], "config_hash": prov["config_hash"]}
            log.info("%s: identical store already present; keeping its provenance", req.key)
        m.add_ingest(f["id"], res.path, True, report, res.provenance or prov, res.content_sha256)
        m.transition(req.id, ["verified"], "ingested", detail=str(res.path))
        out["already_present" if res.already_present else "ingested"] += 1
    return out


def cleanup_raw(m: Manifest, staging_root: Path, mask_fn: MaskFn | None = None) -> dict[str, int]:
    """Delete raw GRIBs whose ingest is verified. Only files under ``staging_root``.

    Before deleting, the store is compared bit-for-bit once more with the arrays
    rebuilt from the GRIB (using the same ``mask_fn`` as the ingest). The file row
    and the state change are then recorded in one transaction. A failure on one
    request is logged and counted; it does not stop the others.
    """
    staging_root = Path(staging_root).resolve()
    out = {"deleted": 0, "recovered": 0, "skipped": 0, "failed": 0}
    for req in m.by_state("ingested"):
        try:
            out[_cleanup_one(m, req, staging_root, mask_fn)] += 1
        except Exception:
            log.exception("cleanup of %s failed", req.key)
            out["failed"] += 1
    return out


def _cleanup_one(m: Manifest, req: Request, staging_root: Path, mask_fn: MaskFn | None) -> str:
    f = m.current_file(req.id)
    if f is None:
        last = m.latest_file(req.id)
        if last is not None and last["deleted_at"]:
            # Deletion was recorded but the state change was not (older runs only).
            m.transition(req.id, ["ingested"], "raw_deleted", detail="recovered: deletion recorded")
            return "recovered"
        raise RuntimeError(f"{req.key}: no file row")
    ing = m.conn.execute(
        "SELECT * FROM ingests WHERE file_id=? AND ok=1 ORDER BY id DESC LIMIT 1", (f["id"],)
    ).fetchone()
    path = Path(f["path"]).resolve()
    if ing is None or not path.is_relative_to(staging_root):
        log.warning("not deleting %s (no verified ingest, or outside staging)", path)
        return "skipped"
    layout = json.loads(ing["report_json"]).get("layout", "grid")
    if layout != "grid" and mask_fn is None:
        log.warning("not deleting %s: %s-layout store needs the ingest's mask_fn", path, layout)
        return "skipped"
    store = Path(ing["store_path"])
    if not path.exists():
        # A previous run deleted the file and died before the manifest update. The
        # GRIB is gone, so check the store against its recorded content hash.
        problems = self_check_store(store, ing["content_sha256"])
        if problems:
            log.error(
                "%s: raw file gone and store %s fails its self-check: %s", req.key, store, problems
            )
            return "skipped"
        m.mark_raw_deleted(req.id, f["id"], detail=f"recovered: {path} already gone")
        return "recovered"
    dec = decode_grib(path, req.expected)
    cell_mask, keep = mask_fn(req, dec) if mask_fn else (None, None)
    problems = compare_store(store, prepare(dec, cell_mask, keep))
    if problems:
        log.error("store %s does not match %s: %s", store, path, problems)
        return "skipped"
    path.unlink()
    m.mark_raw_deleted(req.id, f["id"], detail=str(path))
    return "deleted"
