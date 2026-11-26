"""A fake HTTP host for forecast tests: serves files from a fixtures folder on
127.0.0.1, and can fail, slow down, cut or drop requests on demand (ticket #50).

    with FakeHttpServer(tests_dir / "fixtures/forecast/gfs") as nomads:
        client.get(nomads.url + "/gfs.20261126/12/atmos/....idx")
        nomads.fail("/gfs.20261126/", status=503, times=2)  # next two requests under it
        nomads.delay("/", seconds=5)                        # a slow host / timeouts
        nomads.outage(); nomads.restore()                    # connections dropped unanswered
        nomads.requests                                      # every request, in order

A URL path maps to the file at the same relative path under the root. A request with
a query string (a NOMADS grib-filter call, say) is served from an explicit
``route(target, file_or_bytes)``. GET, HEAD and single byte ranges are supported.
Like S3, every answer with content carries ``ETag: "<MD5 of the whole file>"``;
``header(path, name, value)`` overrides a header for one path (``None`` leaves it out).
Run two servers for a main host and its fallback.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    at: float  # time.monotonic() when the request arrived
    status: int | None  # None: dropped without an answer


@dataclass
class _Behaviour:
    kind: str  # "fail", "delay", "truncate", "drop"
    prefix: str
    times: int | None  # None: until cleared
    status: int = 503
    seconds: float = 0.0
    used: int = field(default=0)


class FakeHttpServer:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else None
        self.routes: dict[str, bytes | Path] = {}
        self.header_overrides: dict[str, dict[str, str | None]] = {}
        self.requests: list[RecordedRequest] = []
        self._behaviours: list[_Behaviour] = []
        self._lock = threading.Lock()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )

    # -- lifecycle -------------------------------------------------------------------
    def __enter__(self) -> FakeHttpServer:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    # -- content and behaviours ------------------------------------------------------
    def route(self, target: str, content: bytes | Path) -> None:
        """Serve ``content`` for the exact request target (path plus query string)."""
        self.routes[target] = content

    def header(self, path: str, name: str, value: str | None) -> None:
        """Send ``name: value`` for requests to ``path`` instead of the default (``None``:
        leave the header out), e.g. a wrong ``ETag`` to test checksum checks."""
        self.header_overrides.setdefault(path, {})[name] = value

    def fail(self, prefix: str = "/", status: int = 503, times: int | None = None) -> None:
        """Answer requests under ``prefix`` with ``status`` (the next ``times`` of them)."""
        self._add(_Behaviour("fail", prefix, times, status=status))

    def delay(self, prefix: str = "/", seconds: float = 1.0, times: int | None = None) -> None:
        """Wait ``seconds`` before answering (a slow host; a timeout if long enough)."""
        self._add(_Behaviour("delay", prefix, times, seconds=seconds))

    def truncate(self, prefix: str = "/", times: int | None = None) -> None:
        """Announce the full length but send only half the body, then close."""
        self._add(_Behaviour("truncate", prefix, times))

    def outage(self, prefix: str = "/") -> None:
        """Drop every connection under ``prefix`` without an answer, until restored."""
        self._add(_Behaviour("drop", prefix, None))

    def restore(self) -> None:
        """Clear every behaviour: the host answers normally again."""
        with self._lock:
            self._behaviours.clear()

    def _add(self, b: _Behaviour) -> None:
        with self._lock:
            self._behaviours.append(b)

    def _take(self, path: str) -> list[_Behaviour]:
        """The behaviours that apply to this request, using up counted ones."""
        out = []
        with self._lock:
            for b in self._behaviours:
                if path.startswith(b.prefix) and (b.times is None or b.used < b.times):
                    b.used += 1
                    out.append(b)
        return out

    def _record(self, r: RecordedRequest) -> None:
        with self._lock:
            self.requests.append(r)

    def _content(self, target: str, path: str) -> bytes | None:
        if target in self.routes:
            c = self.routes[target]
            return c.read_bytes() if isinstance(c, Path) else c
        if self.root is None:
            return None
        f = (self.root / path.lstrip("/")).resolve()
        if self.root.resolve() not in f.parents or not f.is_file():
            return None
        return f.read_bytes()


def _handler_for(server: FakeHttpServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._serve(body=True)

        def do_HEAD(self) -> None:
            self._serve(body=False)

        def log_message(self, *args) -> None:  # keep test output quiet
            pass

        def _serve(self, body: bool) -> None:
            arrived = time.monotonic()
            parts = urlsplit(self.path)
            behaviours = {b.kind: b for b in server._take(parts.path)}
            extra: tuple = ()
            if "drop" in behaviours:
                status, content = None, b""
            elif "fail" in behaviours:
                status, content = behaviours["fail"].status, b"fake failure\n"
            elif (found := server._content(self.path, parts.path)) is None:
                status, content = 404, b"not found\n"
            else:
                status, content, extra = _apply_range(self.headers.get("Range"), found)
                extra = _with_headers(extra, found, server.header_overrides.get(parts.path, {}))
            # Recorded before answering, so a client that has its answer sees the record.
            server._record(RecordedRequest(
                self.command, parts.path, parse_qs(parts.query), dict(self.headers.items()),
                arrived, status,
            ))  # fmt: skip
            try:
                if status is None:
                    self.close_connection = True
                    return
                if "delay" in behaviours:
                    time.sleep(behaviours["delay"].seconds)
                if "truncate" in behaviours and status < 400:
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content[: len(content) // 2])
                    self.close_connection = True
                    return
                self._reply(status, content, body, extra)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the client gave up (a timeout test)

        def _reply(self, status: int, content: bytes, body: bool, extra=()) -> None:
            self.send_response(status)
            self.send_header("Content-Length", str(len(content)))
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            if body:
                self.wfile.write(content)

    return Handler


def _with_headers(extra: tuple, whole: bytes, overrides: dict[str, str | None]) -> tuple:
    """Add the S3-style ETag (MD5 of the whole file), then apply per-path overrides."""
    headers = {"ETag": f'"{hashlib.md5(whole).hexdigest()}"', **dict(extra), **overrides}
    return tuple((k, v) for k, v in headers.items() if v is not None)


def _apply_range(header: str | None, content: bytes):
    """A single ``bytes=a-b`` range → 206 with that slice; otherwise the whole file."""
    if not header:
        return 200, content, ()
    m = re.fullmatch(r"bytes=(\d+)-(\d*)", header.strip())
    if not m:
        return 416, b"", ()
    start = int(m.group(1))
    end = min(int(m.group(2)) if m.group(2) else len(content) - 1, len(content) - 1)
    if start > end:
        return 416, b"", ()
    return (
        206,
        content[start : end + 1],
        (("Content-Range", f"bytes {start}-{end}/{len(content)}"),),
    )
