"""End-to-end run of the ``astro`` CLI against the fake CDS backend."""

from __future__ import annotations

import json

import pytest

from astroseeing import cli
from astroseeing.manifest import Manifest

from fakes import FakeCdsBackend


@pytest.fixture
def ct(tmp_path, monkeypatch):
    for name in ("data", "staging", "state"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("ASTRO_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ASTRO_STAGING", str(tmp_path / "staging"))
    monkeypatch.setenv("ASTRO_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def _fake_from_manifest(path) -> FakeCdsBackend:
    m = Manifest(path)
    rows = m.conn.execute("SELECT request_json, expected_json FROM requests").fetchall()
    m.close()
    exp = {FakeCdsBackend.req_key(json.loads(r[0])): json.loads(r[1]) for r in rows}
    return FakeCdsBackend(exp, polls_to_finish=1)


def test_cli_end_to_end(ct, monkeypatch, capsys):
    args = [
        "plan-box",
        "--region",
        "paranal",
        "--lat",
        "-24.63",
        "--lon",
        "-70.40",
        "--half-width",
        "1",
        "--start",
        "2023-06-21",
        "--end",
        "2023-06-21",
        "--kinds",
        "pl,sl,static",
        "--hours",
        "0,12",
    ]
    assert cli.main(args) == 0
    assert cli.main(args) == 0  # idempotent
    fake = _fake_from_manifest(ct / "state" / "manifest.sqlite")
    monkeypatch.setattr(cli, "_backend", lambda: fake)
    assert cli.main(["download", "--poll", "0"]) == 0
    assert cli.main(["verify"]) == 0
    assert cli.main(["ingest"]) == 0
    assert cli.main(["cleanup-raw"]) == 0
    assert cli.main(["export-manifest"]) == 0
    capsys.readouterr()
    assert cli.main(["status"]) == 0
    out = json.loads(capsys.readouterr().out.split("\n}\n")[0] + "\n}")
    assert out["counts"] == {"raw_deleted": 3}
    assert len(list((ct / "data" / "era5").rglob("zarr.json"))) > 0
    assert len(list((ct / "data" / "manifest-exports").glob("manifest-*.sqlite"))) == 1
    assert fake.submits == 3


def test_smoke_test_reports_auth_failure(ct, monkeypatch):
    class NoAuth:
        def check_authentication(self):
            raise RuntimeError("401 Unauthorized (fake)")

    monkeypatch.setattr(cli, "_backend", lambda: NoAuth())
    out = ct / "smoke.json"
    assert cli.main(["cds-smoke-test", "--out", str(out)]) == 2
    rep = json.loads(out.read_text())
    assert rep["authentication"]["ok"] is False and "401" in rep["authentication"]["error"]


def test_cli_exit_codes_report_failures(ct, monkeypatch):
    args = [
        "plan-box",
        "--region",
        "x",
        "--lat",
        "-24.63",
        "--lon",
        "-70.40",
        "--half-width",
        "1",
        "--start",
        "2023-06-21",
        "--end",
        "2023-06-22",
        "--kinds",
        "sl",
        "--hours",
        "0",
    ]
    assert cli.main(args) == 0
    fake = _fake_from_manifest(ct / "state" / "manifest.sqlite")
    first, second = list(fake.expected)
    fake.behaviour[first] = "reject"
    fake.behaviour[second] = "drop"
    monkeypatch.setattr(cli, "_backend", lambda: fake)
    assert cli.main(["download", "--poll", "0"]) == 1  # one CDS rejection
    assert cli.main(["verify"]) == 1  # one file missing a message
