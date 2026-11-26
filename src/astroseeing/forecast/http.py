"""The one HTTP client all forecast code uses (F1 spec Module 1, D51 item 15).

Adapters, the ESO step and the served-page check take an :class:`HttpClient` as an
argument instead of making their own, so tests point them at a fake server. The
client makes **one attempt** per call: retry spacing (at least 1 min apart) and the
fallback-host switch are run rules (D51 items 7 and 14) that belong to the caller,
which knows the clock and the manifest.

Every request carries the generic ``astro-seeing/<version>`` User-Agent, with no
contact details. Failures raise :class:`HttpError` (an HTTP status) or
:class:`HttpUnavailable` (no answer: connection refused or dropped, a cut transfer,
or :class:`HttpTimeout`).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import requests

import astroseeing

_CHUNK = 1 << 20


def user_agent() -> str:
    return f"astro-seeing/{astroseeing.__version__}"


class HttpError(Exception):
    """The request failed; ``status`` is the HTTP status, or ``None`` if none came back."""

    def __init__(self, url: str, status: int | None, reason: str):
        super().__init__(f"{url}: {f'HTTP {status} ' if status else ''}{reason}")
        self.url = url
        self.status = status


class HttpUnavailable(HttpError):
    """No (complete) answer: connection refused or dropped, or the transfer was cut."""

    def __init__(self, url: str, reason: str):
        super().__init__(url, None, reason)


class HttpTimeout(HttpUnavailable):
    """The host did not answer within the timeout."""


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status: int
    headers: Mapping[str, str]  # case-insensitive
    body: bytes


@dataclass(frozen=True)
class Download:
    """A file written by :meth:`HttpClient.download`."""

    url: str
    path: Path
    bytes: int
    seconds: float
    sha256: str


class HttpClient:
    def __init__(self, timeout_s: float = 60.0, session: requests.Session | None = None):
        self.timeout_s = timeout_s
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent()

    def get(self, url: str, *, headers: Mapping[str, str] | None = None,
            params: Mapping[str, str] | None = None,
            timeout_s: float | None = None) -> HttpResponse:  # fmt: skip
        """GET ``url`` and return the whole body (for listings, indexes, byte ranges)."""
        with self._send("GET", url, headers, params, timeout_s, stream=False) as r:
            return HttpResponse(r.url, r.status_code, r.headers, r.content)

    def head(self, url: str, *, headers: Mapping[str, str] | None = None,
             timeout_s: float | None = None) -> HttpResponse:  # fmt: skip
        with self._send("HEAD", url, headers, None, timeout_s, stream=False) as r:
            return HttpResponse(r.url, r.status_code, r.headers, b"")

    def download(self, url: str, dest: Path, *, headers: Mapping[str, str] | None = None,
                 params: Mapping[str, str] | None = None,
                 timeout_s: float | None = None) -> Download:  # fmt: skip
        """Stream ``url`` to ``dest`` atomically (temp file in the same folder, fsync,
        rename). On any failure nothing is left at ``dest`` or beside it."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        digest, size = hashlib.sha256(), 0
        fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as f, self._send("GET", url, headers, params, timeout_s,
                                                      stream=True) as r:  # fmt: skip
                try:
                    for chunk in r.iter_content(_CHUNK):
                        f.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                except requests.RequestException as e:
                    raise _unavailable(url, e) from e
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return Download(url, dest, size, time.monotonic() - t0, digest.hexdigest())

    def _send(self, method: str, url: str, headers, params, timeout_s,
              stream: bool) -> requests.Response:  # fmt: skip
        try:
            r = self.session.request(
                method, url, headers=dict(headers or {}), params=params, stream=stream,
                timeout=self.timeout_s if timeout_s is None else timeout_s,
            )  # fmt: skip
        except requests.RequestException as e:
            raise _unavailable(url, e) from e
        if r.status_code >= 400:
            r.close()
            raise HttpError(url, r.status_code, r.reason or "error")
        return r


def _unavailable(url: str, e: requests.RequestException) -> HttpUnavailable:
    if isinstance(e, requests.Timeout):
        return HttpTimeout(url, f"timed out ({e.__class__.__name__})")
    return HttpUnavailable(url, f"no complete answer ({e.__class__.__name__}: {e})")
