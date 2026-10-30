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
    # the rejection comes second: after it the CDS gate backs off (D39)
    fake.behaviour[first] = "drop"
    fake.behaviour[second] = "reject"
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
        "pl_box_month_split",
        "sl_box_month_split",
    }
    assert len(rep["cost_estimates"]["pl_box_month_split"]) == 2  # 16 + 15 days
    assert rep["accepted_licences"] == ["licence-to-use-copernicus-products (revision 12)"]


def test_smoke_test_fails_when_a_request_is_rejected(ct, monkeypatch):
    fake = _smoke_fake(reject_kind="sl")  # submitted last, so the backoff stops nothing
    monkeypatch.setattr(cli, "_backend", lambda: fake)
    out = ct / "smoke.json"
    assert cli.main(["cds-smoke-test", "--out", str(out), "--poll", "0"]) == 1
    rep = json.loads(out.read_text())
    assert rep["ok"] is False and rep["download"]["failed"] == 1
    states = {r["key"].split("/")[0]: r["state"] for r in rep["requests"]}
    assert states == {"pl": "verified", "sl": "failed"}


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
    """D16: validation boxes use one request per month; D23: pressure levels are split
    in two per month to stay under the CDS limit of 60,000 fields per request."""
    args = ["plan-box", "--region", "m", "--lat", "-24.63", "--lon", "-70.40",
            "--start", "2023-01-01", "--end", "2023-02-28", "--kinds", "pl,sl"]  # fmt: skip
    assert cli.main(args) == 0
    m = Manifest(ct / "state" / "manifest.sqlite")
    keys = [r[0] for r in m.conn.execute("SELECT key FROM requests ORDER BY id")]
    m.close()
    assert keys == [
        "pl/m/2023-01-01_2023-01-16",
        "pl/m/2023-01-17_2023-01-31",
        "pl/m/2023-02-01_2023-02-14",
        "pl/m/2023-02-15_2023-02-28",
        "sl/m/2023-01",
        "sl/m/2023-02",
    ]


class _StubMask:
    """Stands in for terrain.landmask.LandMask (the real build needs ~3 GB and 10 s)."""

    def __init__(self, sites):
        from astroseeing.qc import QCCounts

        self._sites = sites
        self.qc = QCCounts()

    def summary(self, sites=None):
        return {"era5_cells_kept": 1, "sites": self._sites}


@pytest.mark.parametrize(
    ("sites", "code"),
    [
        # a site whose listed coordinates are at sea: warn, still succeed
        ({"a": (True, True), "b": (False, False)}, 0),
        # a site on land outside the kept cells: the aggregation is wrong, fail
        ({"a": (True, False)}, 1),
    ],
)
def test_build_landmask_site_checks(ct, monkeypatch, sites, code):
    from astroseeing.terrain import landmask

    stub = _StubMask(
        {n: {"globe_land": land, "era5_cell_kept": kept} for n, (land, kept) in sites.items()}
    )
    monkeypatch.setattr(landmask, "build", lambda **kw: stub)
    out = ct / "summary.json"
    assert cli.main(["build-landmask", "--dry-run", "--summary-out", str(out)]) == code
    assert json.loads(out.read_text())["sites"].keys() == sites.keys()


def test_build_landmask_dry_run_writes_nothing_by_default(ct, monkeypatch):
    """Copilot review of PR #2: --dry-run must not rewrite reports/landmask_summary.json."""
    from astroseeing.terrain import landmask

    stub = _StubMask({"a": {"globe_land": True, "era5_cell_kept": True}})
    monkeypatch.setattr(landmask, "build", lambda **kw: stub)
    written = []
    monkeypatch.setattr(cli.Path, "write_text", lambda self, *a, **k: written.append(self))
    assert cli.main(["build-landmask", "--dry-run"]) == 0
    assert written == []


def _planned(ct) -> list[dict]:
    m = Manifest(ct / "state" / "manifest.sqlite")
    rows = m.conn.execute("SELECT kind, request_json, region FROM requests").fetchall()
    m.close()
    return [{"kind": r[0], "region": r[2], **json.loads(r[1])} for r in rows]


def test_plan_area_passes_variables_for_single_levels(ct):
    """Regression (D36): --variables was ignored for sl, which got all 17 variables."""
    args = ["plan-area", "chile", "--start", "2021-01-01", "--end", "2021-02-28",
            "--kinds", "sl", "--variables", "lcc,mcc,hcc,zust,ishf,tcwv",
            "--hours", "night"]  # fmt: skip
    assert cli.main(args) == 0
    reqs = _planned(ct)
    assert len(reqs) == 2 and {r["kind"] for r in reqs} == {"sl"}
    # its own region, so keys and stores never mix with full single-level requests
    assert {r["region"] for r in reqs} == {"chile@vars-lcc-mcc-hcc-zust-ishf-tcwv"}
    want = {
        "low_cloud_cover",
        "medium_cloud_cover",
        "high_cloud_cover",
        "friction_velocity",
        "instantaneous_surface_sensible_heat_flux",
        "total_column_water_vapour",
    }
    assert all(set(r["variable"]) == want for r in reqs)


def test_plan_area_pl_variables_still_work_and_unknown_names_fail(ct):
    args = ["plan-area", "chile", "--start", "2021-01-01", "--end", "2021-01-31",
            "--kinds", "pl", "--variables", "z,t,u,v", "--hours", "night"]  # fmt: skip
    assert cli.main(args) == 0
    assert all(len(r["variable"]) == 4 for r in _planned(ct))
    # one list for both kinds can't be right for both: refused, not silently ignored
    bad = ["plan-area", "chile", "--start", "2021-03-01", "--end", "2021-03-31",
           "--kinds", "pl,sl", "--variables", "z,t", "--hours", "night"]  # fmt: skip
    before = len(_planned(ct))
    with pytest.raises(SystemExit, match="unknown sl variable"):
        cli.main(bad)
    assert len(_planned(ct)) == before  # nothing half-planned


def test_plan_area_full_and_subset_plans_do_not_collide(ct):
    common = ["plan-area", "chile", "--start", "2006-06-01", "--end", "2006-06-30",
              "--kinds", "sl", "--hours", "night"]  # fmt: skip
    assert cli.main(common) == 0  # all 17 variables, region chile
    assert cli.main([*common, "--variables", "lcc,zust"]) == 0
    assert sorted(r["region"] for r in _planned(ct)) == ["chile", "chile@vars-lcc-zust"]
    # naming every default variable is the full set, not a subset
    sl = load_config_sl_short_names()
    assert cli.main([*common, "--variables", ",".join(sl)]) == 0
    assert len(_planned(ct)) == 2


def load_config_sl_short_names() -> list[str]:
    from astroseeing.config import load_config

    return [v["short_name"] for v in load_config("era5")["datasets"]["sl"]["variables"].values()]


def test_plan_area_estimate_uses_the_configured_rate(ct, caplog):
    import logging

    from astroseeing.config import load_config

    rate = load_config("era5")["request"]["fields_per_s"]
    assert rate == 5.6  # measured with one job at a time (D40)
    args = ["plan-area", "chile", "--start", "2021-01-01", "--end", "2021-01-31",
            "--kinds", "sl", "--variables", "lcc", "--hours", "night"]  # fmt: skip
    with caplog.at_level(logging.INFO):
        assert cli.main(args) == 0
    assert f"at {rate:.1f} fields/s" in caplog.text
