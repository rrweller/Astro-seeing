"""CDS access behind a small interface, so the downloader can be tested offline.

The real backend wraps ``ecmwf.datastores.Client`` (the library behind
``cdsapi>=0.7.7`` for the current CDS). It is used asynchronously — submit, then
poll by request id — so a restart can re-attach to a request that is still queued
at the CDS instead of submitting it again.

Credentials come from ``~/.cdsapirc`` (``url:`` and ``key:`` lines, AGENTS.md).
The key is never logged or stored in the manifest.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

#: Remote job states reported by the CDS retrieve API.
DONE = "successful"
PENDING = ("accepted", "running")
FAILED = ("failed", "rejected")
GONE = ("dismissed", "deleted")

#: The CDS rejects a job outright when a user has too many queued for one dataset
#: (seen on the CT, 2026-09-27: 24 of 29 simultaneous submissions rejected with
#: "Number queued requests for this dataset is temporarily limited. Please configure
#: your scripts accordingly"). That is transient: the request is planned again.
QUEUE_LIMIT_MESSAGE = "queued requests for this dataset is temporarily limited"


def is_queue_limit_rejection(error: str | None) -> bool:
    return bool(error) and QUEUE_LIMIT_MESSAGE in error.lower()


@dataclass
class RemoteInfo:
    status: str
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    content_length: int | None = None


class CdsBackend(Protocol):
    def submit(self, dataset: str, request: dict[str, Any]) -> str: ...
    def info(self, request_id: str) -> RemoteInfo: ...
    def download(self, request_id: str, target: Path) -> int: ...
    def delete(self, request_id: str) -> None: ...


def read_cdsapirc(path: Path | None = None) -> tuple[str, str]:
    """(url, key) from ``~/.cdsapirc`` (or $CDSAPI_RC). Refuses group/world-readable files."""
    path = Path(path or os.environ.get("CDSAPI_RC", Path.home() / ".cdsapirc"))
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise PermissionError(f"{path} has mode {oct(mode)}; run `chmod 600 {path}`")
    cfg: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            cfg[k.strip()] = v.strip()
    if "url" not in cfg or "key" not in cfg:
        raise ValueError(f"{path} needs 'url:' and 'key:' lines")
    return cfg["url"], cfg["key"]


class DatastoresBackend:
    """Real CDS backend (``ecmwf-datastores-client``)."""

    def __init__(self, url: str | None = None, key: str | None = None, timeout: float = 120.0):
        from ecmwf.datastores import Client

        if url is None or key is None:
            url, key = read_cdsapirc()
        # progress=False: logs, not progress bars; maximum_tries bounds HTTP retries.
        self.client = Client(url=url, key=key, timeout=timeout, progress=False, maximum_tries=10)

    def check_authentication(self) -> dict[str, Any]:
        return self.client.check_authentication()

    def submit(self, dataset: str, request: dict[str, Any]) -> str:
        return self.client.submit(dataset, request).request_id

    def info(self, request_id: str) -> RemoteInfo:
        from ecmwf.datastores.processing import ProcessingFailedError

        remote = self.client.get_remote(request_id)
        status = remote.status
        info = RemoteInfo(status=status)
        for attr in ("created_at", "started_at", "finished_at"):
            try:
                v = getattr(remote, attr)
                setattr(info, attr, v.isoformat() if v else None)
            except Exception:  # timestamps are informational only
                pass
        if status in FAILED:
            try:
                remote.results_ready  # noqa: B018 - raises with the server's message
            except ProcessingFailedError as e:
                info.error = str(e)
            except Exception as e:  # rejected jobs raise HTTPError (400) instead
                info.error = f"{type(e).__name__}: {e}"
            if info.error is None:
                info.error = f"cds status {status} (no message)"
        if status == DONE:
            info.content_length = self.client.get_results(request_id).content_length
        return info

    def download(self, request_id: str, target: Path) -> int:
        results = self.client.get_results(request_id)
        results.download(str(target))  # checks the size against the server's value
        return int(Path(target).stat().st_size)

    def delete(self, request_id: str) -> None:
        self.client.delete(request_id)
