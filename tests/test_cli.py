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
        "--granularity",
        "day",  # two one-day requests, so one can fail and one can succeed
    ]
    assert cli.main(args) == 0
    fake = _fake_from_manifest(ct / "state" / "manifest.sqlite")
    first, second = list(fake.expected)
    fake.behaviour[first] = "reject"
    fake.behaviour[second] = "drop"
    monkeypatch.setattr(cli, "_backend", lambda: fake)
    assert cli.main(["download", "--poll", "0"]) == 1  # one CDS rejection
    assert cli.main(["verify"]) == 1  # one file missing a message


def _smoke_fake(reject_kind: str | None = None) -> FakeCdsBackend:
    import datetime as dt

    from astroseeing.download.requests import Area, plan_requests

    area, day = Area.around(-24.63, -70.40, 2), dt.date(2023, 6, 21)
    specs = [plan_requests(k, "s", day, day, area, hours=(0,))[0] for k in ("pl", "sl")]
    fake = FakeCdsBackend({FakeCdsBackend.req_key(s.cds_request()): s.expected() for s in specs})
    fake.check_authentication = lambda: {"id": "fake"}

    class _Client:
        @staticmethod
        def estimate_costs(dataset, request):
            return {"cost": 1, "limit": 10}

        @staticmethod
        def get_accepted_licences():
            return [{"id": "licence-to-use-copernicus-products", "revision": 12}]

    fake.client = _Client()
    if reject_kind:
        spec = specs[0] if reject_kind == "pl" else specs[1]
        fake.behaviour[FakeCdsBackend.req_key(spec.cds_request())] = "reject"
    return fake


def test_smoke_test_passes_when_everything_verifies(ct, monkeypatch):
    fake = _smoke_fake()
    monkeypatch.setattr(cli, "_backend", lambda: fake)
    out = ct / "smoke.json"
    assert cli.main(["cds-smoke-test", "--out", str(out), "--poll", "0"]) == 0
    rep = json.loads(out.read_text())
    assert rep["ok"] is True and rep["download"]["downloaded"] == 2
    assert all(r["state"] == "verified" for r in rep["requests"])
    assert set(rep["cost_estimates"]) == {
        "pl_global_day",
        "sl_global_day",
        "pl_box_month",
        "sl_box_month",
    }
    assert rep["accepted_licences"] == ["licence-to-use-copernicus-products (revision 12)"]


def test_smoke_test_fails_when_a_request_is_rejected(ct, monkeypatch):
    fake = _smoke_fake(reject_kind="pl")
    monkeypatch.setattr(cli, "_backend", lambda: fake)
    out = ct / "smoke.json"
    assert cli.main(["cds-smoke-test", "--out", str(out), "--poll", "0"]) == 1
    rep = json.loads(out.read_text())
    assert rep["ok"] is False and rep["download"]["failed"] == 1
    states = {r["key"].split("/")[0]: r["state"] for r in rep["requests"]}
    assert states == {"pl": "failed", "sl": "verified"}


def test_config_lookup_order(tmp_path, monkeypatch):
    from astroseeing import config

    assert config.config_dir() == config.REPO_CONFIG_DIR  # source checkout
    (tmp_path / "era5.yaml").write_text("grid_deg: 0.5\n")
    monkeypatch.setenv("ASTRO_CONFIG_DIR", str(tmp_path))
    config.load_config.cache_clear()
    try:
        assert config.load_config("era5") == {"grid_deg": 0.5}
    finally:
        config.load_config.cache_clear()


def test_plan_box_defaults_to_month_sized_requests(ct):
    """D16: validation boxes use one request per month."""
    args = ["plan-box", "--region", "m", "--lat", "-24.63", "--lon", "-70.40",
            "--start", "2023-01-30", "--end", "2023-02-02", "--kinds", "pl"]  # fmt: skip
    assert cli.main(args) == 0
    m = Manifest(ct / "state" / "manifest.sqlite")
    keys = [r[0] for r in m.conn.execute("SELECT key FROM requests ORDER BY id")]
    m.close()
    assert keys == ["pl/m/2023-01", "pl/m/2023-02"]
