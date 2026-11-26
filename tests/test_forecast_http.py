"""The forecast HTTP client (one injected seam, generic User-Agent, D51 item 15) and the
reusable fake HTTP server tests use instead of live hosts (ticket #50)."""

from __future__ import annotations

import hashlib
import time

import pytest

import astroseeing
from astroseeing.forecast.http import (
    HttpClient,
    HttpError,
    HttpTimeout,
    HttpUnavailable,
    user_agent,
)

from fake_http import FakeHttpServer


@pytest.fixture
def root(tmp_path):
    """A fixtures folder with one small 'GRIB' file and its index."""
    d = tmp_path / "fixtures"
    (d / "gfs.20261126/12/atmos").mkdir(parents=True)
    (d / "gfs.20261126/12/atmos/gfs.t12z.pgrb2.0p25.f000").write_bytes(bytes(range(256)) * 4)
    (d / "gfs.20261126/12/atmos/gfs.t12z.pgrb2.0p25.f000.idx").write_text("1:0:d=2026112612\n")
    return d


@pytest.fixture
def server(root):
    with FakeHttpServer(root) as s:
        yield s


@pytest.fixture
def client():
    return HttpClient(timeout_s=2.0)


GRIB = "/gfs.20261126/12/atmos/gfs.t12z.pgrb2.0p25.f000"


def test_user_agent_is_generic_with_the_version():
    assert user_agent() == f"astro-seeing/{astroseeing.__version__}"
    assert "@" not in user_agent()  # no contact details (D51 item 15)


def test_serves_fixture_files_and_records_each_request(server, client, root):
    r = client.get(server.url + GRIB + ".idx")
    assert r.status == 200 and r.body == b"1:0:d=2026112612\n"
    h = client.head(server.url + GRIB)
    assert h.status == 200 and h.headers["Content-Length"] == "1024" and h.body == b""

    assert [(q.method, q.path, q.status) for q in server.requests] == [
        ("GET", GRIB + ".idx", 200),
        ("HEAD", GRIB, 200),
    ]
    assert all(q.headers["User-Agent"] == user_agent() for q in server.requests)
    assert server.requests[0].at <= server.requests[1].at  # monotonic times, for rate tests


def test_byte_ranges_and_query_routes(server, client, root):
    r = client.get(server.url + GRIB, headers={"Range": "bytes=10-19"})
    assert r.status == 206 and r.body == bytes(range(10, 20))
    assert server.requests[-1].headers["Range"] == "bytes=10-19"

    # A NOMADS-style filter request is served from an explicit route, query and all.
    server.route("/cgi-bin/filter_gfs_0p25_1hr.pl?file=f000&var_TMP=on", b"filtered")
    r = client.get(server.url + "/cgi-bin/filter_gfs_0p25_1hr.pl",
                   params={"file": "f000", "var_TMP": "on"})  # fmt: skip
    assert r.body == b"filtered"
    assert server.requests[-1].query == {"file": ["f000"], "var_TMP": ["on"]}


def test_missing_file_is_an_http_error(server, client):
    with pytest.raises(HttpError) as e:
        client.get(server.url + "/nope.grib2")
    assert e.value.status == 404 and e.value.url.endswith("/nope.grib2")


def test_errors_on_request_then_recovery(server, client):
    server.fail(GRIB, status=503, times=2)
    for _ in range(2):
        with pytest.raises(HttpError, match="503"):
            client.get(server.url + GRIB)
    assert client.get(server.url + GRIB).status == 200
    assert [q.status for q in server.requests] == [503, 503, 200]


def test_slow_host_and_timeout(server):
    server.delay(GRIB, seconds=0.3)
    t0 = time.monotonic()
    assert HttpClient(timeout_s=2.0).get(server.url + GRIB).status == 200  # slow but fine
    assert time.monotonic() - t0 >= 0.3
    server.delay(GRIB, seconds=1.5)
    with pytest.raises(HttpTimeout):
        HttpClient(timeout_s=0.3).get(server.url + GRIB)


def test_host_outage_drops_connections_until_restored(server, client):
    server.outage()
    with pytest.raises(HttpUnavailable) as e:
        client.get(server.url + GRIB)
    assert e.value.status is None
    assert server.requests[-1].status is None  # recorded, but never answered
    server.restore()
    assert client.get(server.url + GRIB).status == 200


def test_download_is_atomic_with_size_time_and_checksum(server, client, root, tmp_path):
    dest = tmp_path / "staging" / "gfs" / "f000.grib2"
    d = client.download(server.url + GRIB, dest)
    data = (root / GRIB.lstrip("/")).read_bytes()
    assert dest.read_bytes() == data
    assert (d.path, d.bytes, d.sha256) == (dest, 1024, hashlib.sha256(data).hexdigest())
    assert d.seconds >= 0 and d.url == server.url + GRIB
    assert list(dest.parent.iterdir()) == [dest]  # no temporary file left behind


def test_a_cut_download_leaves_no_file(server, client, tmp_path):
    server.truncate(GRIB)
    dest = tmp_path / "staging" / "f000.grib2"
    with pytest.raises(HttpUnavailable):
        client.download(server.url + GRIB, dest)
    assert list(dest.parent.iterdir()) == []


def test_a_failed_download_leaves_no_file(server, client, tmp_path):
    server.fail(GRIB, status=500)
    with pytest.raises(HttpError, match="500"):
        client.download(server.url + GRIB, tmp_path / "staging" / "f000.grib2")
    assert list((tmp_path / "staging").iterdir()) == []
