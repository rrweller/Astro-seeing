"""Manifest-driven stages: verify → ingest → delete raw (AGENTS.md "Data safety").

* :func:`verify_pending`: ``downloaded`` → ``verified`` (or ``failed``); checks the
  file's SHA-256 still matches the manifest, then runs ``verify_grib``.
* :func:`ingest_pending`: ``verified`` → ``ingested``; decodes, writes the Zarr store
  atomically and verifies it bit-for-bit (read-back before and after rename).
* :func:`cleanup_raw`: ``ingested`` → ``raw_deleted``; deletes the raw GRIB only if
  the ingest was verified, the Zarr store still passes a content check, and the
  file lies under the staging directory. Never deletes anything under /data.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np

from astroseeing.download.downloader import sha256_file
from astroseeing.ingest.decode import decode_grib
from astroseeing.ingest.store import compare_store, prepare, write_store_atomic
from astroseeing.manifest import Manifest, Request
from astroseeing.paths import probe_responsive
from astroseeing.provenance import era5_attribution, provenance
from astroseeing.verify.grib import verify_grib

log = logging.getLogger(__name__)

#: Optional hook returning (cell_mask, keep_hours) for a request; None → grid layout.
MaskFn = Callable[[Request, "object"], tuple[np.ndarray | None, np.ndarray | None]]


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
) -> dict[str, int]:
    out = {"ingested": 0, "already_present": 0, "failed": 0}
    todo = m.by_state("verified")
    if todo:
        probe_responsive(Path(data_root), probe_timeout_s)
    for req in todo:
        f = m.current_file(req.id)
        try:
            dec = decode_grib(Path(f["path"]), req.expected)
            cell_mask, keep = mask_fn(req, dec) if mask_fn else (None, None)
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
        m.add_ingest(f["id"], res.path, True, report, prov, res.content_sha256)
        m.transition(req.id, ["verified"], "ingested", detail=str(res.path))
        out["already_present" if res.already_present else "ingested"] += 1
    return out


def cleanup_raw(m: Manifest, staging_root: Path, mask_fn: MaskFn | None = None) -> dict[str, int]:
    """Delete raw GRIBs whose ingest is verified. Only files under ``staging_root``.

    Before deleting, the store is compared bit-for-bit once more with the arrays
    rebuilt from the GRIB (using the same ``mask_fn`` as the ingest).
    """
    staging_root = Path(staging_root).resolve()
    out = {"deleted": 0, "skipped": 0}
    for req in m.by_state("ingested"):
        f = m.current_file(req.id)
        ing = m.conn.execute(
            "SELECT * FROM ingests WHERE file_id=? AND ok=1 ORDER BY id DESC LIMIT 1", (f["id"],)
        ).fetchone()
        path = Path(f["path"]).resolve()
        if ing is None or not path.is_relative_to(staging_root):
            log.warning("not deleting %s (no verified ingest, or outside staging)", path)
            out["skipped"] += 1
            continue
        dec = decode_grib(path, req.expected)
        cell_mask, keep = mask_fn(req, dec) if mask_fn else (None, None)
        problems = compare_store(Path(ing["store_path"]), prepare(dec, cell_mask, keep))
        if problems:
            log.error("store %s does not match %s: %s", ing["store_path"], path, problems)
            out["skipped"] += 1
            continue
        path.unlink()
        m.mark_file_deleted(f["id"])
        m.transition(req.id, ["ingested"], "raw_deleted", detail=str(path))
        out["deleted"] += 1
    return out
