"""The forecast page's nginx config (F1 spec #47 Module 11, ticket #62, D52 items 7-9).

Runs conda-forge's nginx (``$ASTRO_TEST_NGINX``, else ``nginx`` on the PATH) on the
real config, with only its CT paths and port pointed at temp folders: ``nginx -t``,
then real requests for the headers the page relies on. Without nginx these tests skip;
under CI they fail instead.
"""

from __future__ import annotations

import datetime as dt
import gzip
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from git_repo import commit_files, new_repo

from astroseeing.forecast.deploy import deploy, rollback
from astroseeing.forecast.settings import load_settings
from astroseeing.provenance import REPO_ROOT

CONF = REPO_ROOT / "scripts" / "nginx" / "astro-web.conf"
CT_PATHS = {  # what the config says on the CT → where the test puts it
    "/staging/forecast/site/current": "site/current",
    "/staging/forecast/products/": "products/",
    "/run/astro-web/": "run/",
    "/var/log/astro-web/": "log/",
}
LONG_CACHE = "public, max-age=31536000, immutable"
SET = "sets/20261127T120000Z-3fa9c2d1"
NOW = dt.datetime(2026, 11, 27, 12, 0, tzinfo=dt.UTC)


def nginx_binary() -> str:
    found = os.environ.get("ASTRO_TEST_NGINX") or shutil.which("nginx")
    if found is None:
        if os.environ.get("CI"):
            pytest.fail("nginx is needed under CI (pixi global install nginx)")
        pytest.skip("nginx not installed (pixi global install nginx); config not run")
    return found


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def local_conf(tmp_path: Path, port: int) -> Path:
    text = CONF.read_text()
    for ct, local in {**CT_PATHS, "listen 8350;": f"listen 127.0.0.1:{port};"}.items():
        assert ct in text, ct  # the substitution can't silently miss
        text = text.replace(ct, local if ct.startswith("listen") else f"{tmp_path}/{local}")
    for d in ("run", "log", "products", "site"):
        (tmp_path / d).mkdir(exist_ok=True)
    conf = tmp_path / "nginx.conf"
    conf.write_text(text)
    return conf


def nginx_args(binary: str, tmp_path: Path, conf: Path) -> list[str]:
    args = [binary, "-p", f"{tmp_path}/run/", "-c", str(conf), "-e", "stderr"]
    if os.geteuid() == 0:  # the CT runs it as a dynamic user; root here would switch
        args += ["-g", "user root root;"]  # workers to `nobody`, who can't enter tmp_path
    return args


def test_nginx_accepts_the_config(tmp_path):
    binary = nginx_binary()
    conf = local_conf(tmp_path, free_port())

    out = subprocess.run([*nginx_args(binary, tmp_path, conf), "-t"], capture_output=True,
                         text=True, timeout=30)  # fmt: skip

    assert out.returncode == 0, out.stderr
    assert "syntax is ok" in out.stderr and "test is successful" in out.stderr


@pytest.fixture
def served(tmp_path):
    """nginx on the config, serving a deployed site and a product set; yields a getter."""
    binary = nginx_binary()
    port = free_port()
    conf = local_conf(tmp_path, port)
    repo = new_repo(tmp_path / "repo")
    for html in ("<p>one</p>", "<p>two</p>"):
        js = "export const x = 1;\n" * 50  # big enough to be sent compressed
        commit_files(repo, {"web/forecast/index.html": html, "web/forecast/main.js": js})
        deploy(repo, tmp_path / "site", now=NOW)
    products = tmp_path / "products"
    (products / SET).mkdir(parents=True)
    (products / "latest.json").write_text('{"set_id": "x", "pad": "' + "y" * 400 + '"}\n')
    (products / SET / "place-kongsberg.json").write_text('{"tonight": null}\n')
    (products / SET / "clear_left.u8").write_bytes(bytes(160 * 160))
    (products / "places" / "kongsberg").mkdir(parents=True)
    (products / "places" / "kongsberg" / "gfs-run.json").write_text("{}\n")

    proc = subprocess.Popen(nginx_args(binary, tmp_path, conf), stderr=subprocess.PIPE)
    deadline = time.monotonic() + 10
    while True:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.kill()
                pytest.fail(f"nginx didn't start: {proc.stderr.read().decode()}")
            time.sleep(0.05)

    def get(path: str, **headers: str):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(req, timeout=5) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    try:
        get.products = products
        yield get
    finally:
        proc.terminate()
        proc.wait(timeout=10)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def test_latest_json_is_never_cached_and_answers_304_to_its_etag(served):
    status, headers, body = served("/data/latest.json")

    assert status == 200
    assert body.startswith(b'{"set_id": "x"')
    assert headers["Cache-Control"] == "no-cache"
    assert headers["Content-Type"].startswith("application/json")
    etag = headers["ETag"]

    assert served("/data/latest.json", **{"If-None-Match": etag})[0] == 304
    # The page asks with gzip, which makes nginx weaken the ETag: it must still match.
    status, headers, body = served("/data/latest.json", **{"Accept-Encoding": "gzip"})
    assert headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(body).startswith(b'{"set_id": "x"')
    assert served("/data/latest.json", **{"If-None-Match": headers["ETag"],
                                          "Accept-Encoding": "gzip"})[0] == 304  # fmt: skip


def test_latest_json_is_where_the_page_not_served_alert_looks_for_it(served):
    # F1-12's alert fetches this URL after each tick (alerts.served_latest_url, D52 item 10).
    url = urlsplit(load_settings().alerts.served_latest_url)
    assert (url.hostname, url.port) == ("127.0.0.1", 8350)
    assert "listen 8350;" in CONF.read_text()  # all addresses, so 127.0.0.1 too

    status, _, body = served(url.path)

    assert (status, body) == (200, (served.products / "latest.json").read_bytes())


def test_set_files_are_cached_long_and_layers_are_sent_gzip_compressed(served):
    status, headers, body = served(f"/data/{SET}/clear_left.u8", **{"Accept-Encoding": "gzip"})

    assert status == 200
    assert headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(body) == bytes(160 * 160)
    assert headers["Cache-Control"] == LONG_CACHE
    assert headers["Vary"] == "Accept-Encoding"

    status, headers, _ = served(f"/data/{SET}/place-kongsberg.json")
    assert (status, headers["Cache-Control"]) == (200, LONG_CACHE)


def test_the_page_comes_from_the_deployed_commit_and_follows_a_rollback(served, tmp_path):
    status, headers, _ = served("/")
    assert (status, headers["Location"].endswith("/forecast/")) == (302, True)
    status, headers, body = served("/forecast/")
    assert (status, body) == (200, b"<p>two</p>")
    assert headers["Cache-Control"] == "no-cache"  # a new deploy shows at the next load
    status, headers, body = served("/forecast/main.js", **{"Accept-Encoding": "gzip"})
    assert headers["Content-Type"].startswith("text/javascript")  # required for modules
    assert headers["Content-Encoding"] == "gzip"
    status, headers, body = served("/version.json")
    assert (status, headers["Cache-Control"]) == (200, "no-cache")
    assert body.decode() == f'{{"commit": "{os.readlink(tmp_path / "site" / "current")}"}}\n'

    rollback(tmp_path / "site", now=NOW)  # no reload: nginx follows `current` per request

    assert served("/forecast/")[2] == b"<p>one</p>"


def test_only_the_page_and_the_published_products_are_served(served):
    assert served("/data/places/kongsberg/gfs-run.json")[0] == 404  # the tick's own store
    assert served("/data/sets/")[0] in (403, 404)  # no listings
    assert served("/forecast/../../products/latest.json")[0] in (400, 404)
    assert served("/.deploy.lock")[0] == 404
    headers = served("/data/latest.json")[1]
    assert "Server" not in headers or headers["Server"] == "nginx"  # no version shown
