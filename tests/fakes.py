"""A fake CDS backend that serves synthetic GRIB files (no network)."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

from astroseeing.config import load_config
from astroseeing.download.cds import RemoteInfo
from astroseeing.provenance import canonical_json
from astroseeing.synthetic import write_synthetic_grib


def era5_param_ids() -> dict[str, int]:
    out: dict[str, int] = {}
    for d in load_config("era5")["datasets"].values():
        for v in {**d["variables"], **d.get("optional_variables", {})}.values():
            out[v["short_name"]] = v["param_id"]
    return out


class FakeCdsBackend:
    """Jobs go accepted → running → successful after ``polls_to_finish`` polls.

    ``behaviour`` maps a request key (canonical JSON of the request) to one of:
    "reject", "queue_limit" (rejected once like the real CDS when too many jobs are
    queued, then fine), "expire", "truncate", "drop", "duplicate", "shift".
    """

    def __init__(self, expected_by_request: dict[str, dict], polls_to_finish: int = 2):
        self.expected = expected_by_request
        self.polls_to_finish = polls_to_finish
        self.behaviour: dict[str, str] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.ids = (f"job-{i}" for i in itertools.count(1))
        self.submits = 0
        self.deleted: list[str] = []

    @staticmethod
    def req_key(request: dict) -> str:
        return canonical_json(request)

    def submit(self, dataset: str, request: dict[str, Any]) -> str:
        self.submits += 1
        rid = next(self.ids)
        key = self.req_key(request)
        self.jobs[rid] = {"key": key, "polls": 0, "behaviour": self.behaviour.get(key)}
        return rid

    def info(self, request_id: str) -> RemoteInfo:
        job = self.jobs[request_id]
        job["polls"] += 1
        if job["polls"] < self.polls_to_finish:
            return RemoteInfo(status="accepted" if job["polls"] == 1 else "running")
        if job["behaviour"] == "reject":
            return RemoteInfo(status="rejected", error="cost limits exceeded (fake)")
        if job["behaviour"] == "queue_limit":
            job["behaviour"] = None  # the resubmitted job will succeed
            self.behaviour.pop(job["key"], None)
            return RemoteInfo(
                status="rejected",
                error="HTTPError: 400 Client Error: Bad Request\nThe job has been rejected\n"
                "Number queued requests for this dataset is temporarily limited. Please "
                "configure your scripts accordingly",
            )
        if job["behaviour"] == "expire":
            job["behaviour"] = None  # the resubmitted job will succeed
            self.behaviour.pop(job["key"], None)
            return RemoteInfo(status="dismissed")
        return RemoteInfo(
            status="successful", started_at="2026-09-27T00:00:00", finished_at="2026-09-27T00:01:00"
        )

    def download(self, request_id: str, target: Path) -> int:
        job = self.jobs[request_id]
        b = job["behaviour"]
        kwargs = {"drop": 1} if b == "drop" else {"duplicate": 1} if b == "duplicate" else {}
        if b == "shift":
            kwargs = {"shift_grid_deg": 0.25}
        write_synthetic_grib(target, self.expected[job["key"]], era5_param_ids(), **kwargs)
        size = Path(target).stat().st_size
        if b == "truncate":
            with open(target, "r+b") as f:
                f.truncate(size // 2)
            raise OSError("Download failed: downloaded fewer bytes than the server's size (fake)")
        return size

    def delete(self, request_id: str) -> None:
        self.deleted.append(request_id)
