"""Headless Chromium for the forecast page's tests (F1 spec Testing seam 5; ticket #52).

- ``PageSite`` is a real HTTP server on 127.0.0.1 that serves the page from ``web/`` and
  the tick's products under ``/data/``, the way the CT will (latest.json with an ETag
  and ``Cache-Control: no-cache``; ``If-None-Match`` answered with 304). It records
  every request.
- ``Browser`` drives Playwright for Node through ``tests/browser/driver.cjs``, one JSON
  command per line. Every request the page makes is recorded there too, and any
  request to another origin is aborted and recorded as blocked.

``require_browser()`` skips a test, with the reason, when Node or Playwright is
missing on a developer's machine, and fails it instead under CI (``CI`` set), so the
GitHub ``tests`` check can never pass without having run the page.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

REPO = Path(__file__).resolve().parent.parent
WEB = REPO / "web"
DRIVER = REPO / "tests" / "browser" / "driver.cjs"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
}


@functools.cache
def _browser_problem() -> str | None:
    node = shutil.which("node")
    if node is None:
        return "Node.js is not installed"
    probe = (
        "for (const n of ['playwright-core', 'playwright']) "
        "{ try { require(n); process.exit(0); } catch (e) {} } process.exit(1);"
    )
    done = subprocess.run([node, "-e", probe], cwd=DRIVER.parent, capture_output=True)
    if done.returncode != 0:
        return "Playwright for Node is not installed (npm ci --prefix tests/browser)"
    return None


def require_browser() -> None:
    problem = _browser_problem()
    if problem is None:
        return
    if os.environ.get("CI"):
        pytest.fail(f"the page's browser tests must run in CI, but {problem}")
    pytest.skip(f"browser tests skipped: {problem}")


@dataclass(frozen=True)
class SiteRequest:
    path: str
    headers: dict[str, str]
    status: int


class PageSite:
    """Serves ``/<page>`` from ``web/``, ``/data/`` from ``data_dir`` and
    ``/version.json`` from ``site_files`` (what ``astro web deploy`` would add)."""

    def __init__(self, data_dir: Path, site_files: Path):
        self.data_dir = data_dir
        self.site_files = site_files
        self.requests: list[SiteRequest] = []
        self._lock = threading.Lock()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def __enter__(self) -> PageSite:
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    @property
    def origin(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def resolve(self, url_path: str) -> Path | None:
        path = unquote(url_path)
        if path.startswith("/data/"):
            base, rel = self.data_dir, path[len("/data/") :]
        elif path == "/version.json":
            base, rel = self.site_files, "version.json"
        else:
            base, rel = WEB, path.lstrip("/")
            if rel.endswith("/") or rel == "":
                rel += "index.html"
        target = (base / rel).resolve()
        if not target.is_relative_to(base.resolve()) or not target.is_file():
            return None
        return target

    def record(self, req: SiteRequest) -> None:
        with self._lock:
            self.requests.append(req)


def _handler_for(site: PageSite):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            target = site.resolve(path)
            headers = {k.lower(): v for k, v in self.headers.items()}
            if target is None:
                site.record(SiteRequest(path, headers, 404))
                self.send_error(404)
                return
            body = target.read_bytes()
            etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
            if headers.get("if-none-match") == etag:
                site.record(SiteRequest(path, headers, 304))
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                return
            site.record(SiteRequest(path, headers, 200))
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "text/plain"))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

    return Handler


class DriverError(RuntimeError):
    pass


class Browser:
    """One headless Chromium page, driven through ``driver.cjs``."""

    def __init__(self, origin: str, *, width: int = 1280, height: int = 900, scale: float = 1):
        self.origin = origin
        self._proc = subprocess.Popen(
            ["node", str(DRIVER)],
            cwd=DRIVER.parent,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            self.call(
                "launch",
                origin=origin,
                viewport={"width": width, "height": height},
                deviceScaleFactor=scale,
            )
        except BaseException:
            self._proc.kill()
            self._proc.wait(timeout=30)
            raise

    def call(self, op: str, **args):
        assert self._proc.stdin and self._proc.stdout
        self._proc.stdin.write(json.dumps({"op": op, **args}) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            raise DriverError(f"the browser driver exited during {op}")
        answer = json.loads(line)
        if not answer["ok"]:
            raise DriverError(answer["error"])
        return answer["value"]

    # conveniences -------------------------------------------------------------------
    def open(self, path: str, *, clock: str | None = None) -> None:
        """Open ``path`` with the page's clock faked from ``clock`` (ISO 8601 UTC), and
        wait until the page says it has rendered a product set."""
        if clock is not None:
            self.call("clockInstall", time=clock)
        self.call("goto", url=self.origin + path)
        self.wait_for("document.body.dataset.state === 'ready'")

    def wait_for(self, expr: str, timeout_ms: int = 10000) -> None:
        self.call("waitForFunction", expr=expr, timeout=timeout_ms)

    def eval(self, expr: str):
        return self.call("eval", expr=expr)

    def run_clock(self, ms: int) -> None:
        self.call("clockRunFor", ms=ms)

    def close(self) -> None:
        try:
            self.call("close")
        finally:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.wait(timeout=30)
