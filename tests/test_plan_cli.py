"""``astro plan-area --months``, its estimate, and ``astro cost-check`` (D63)."""

from __future__ import annotations

import pytest

from astroseeing import cli
from astroseeing.manifest import Manifest


@pytest.fixture
def ct(tmp_path, monkeypatch):
    for name in ("data", "staging", "state"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("ASTRO_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ASTRO_STAGING", str(tmp_path / "staging"))
    monkeypatch.setenv("ASTRO_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def _keys(ct) -> list[str]:
    m = Manifest(ct / "state" / "manifest.sqlite")
    keys = [r[0] for r in m.conn.execute("SELECT key FROM requests ORDER BY id")]
    m.close()
    return keys


SL_2023 = ["plan-area", "chile", "--kinds", "sl", "--start", "2023-01-01", "--end", "2023-12-31"]


def test_plan_area_merges_single_levels_into_three_month_requests(ct):
    assert cli.main([*SL_2023, "--months", "3"]) == 0
    assert _keys(ct) == [
        "sl/chile/2023-01_2023-03",
        "sl/chile/2023-04_2023-06",
        "sl/chile/2023-07_2023-09",
        "sl/chile/2023-10_2023-12",
    ]


def test_plan_area_stays_monthly_unless_asked(ct):
    assert cli.main(SL_2023) == 0
    assert len(_keys(ct)) == 12


def test_plan_area_refuses_months_for_pressure_levels(ct):
    with pytest.raises(SystemExit, match="at most 1 month"):
        cli.main(["plan-area", "chile", "--kinds", "pl", "--start", "2023-01-01",
                  "--end", "2023-03-31", "--months", "3"])  # fmt: skip
    assert _keys(ct) == []


def test_plan_area_refuses_dates_another_request_of_the_region_already_covers(ct):
    """A monthly and a three-month plan of one region would put a day in two stores."""
    assert cli.main([*SL_2023[:-1], "2023-02-28"]) == 0  # January and February, monthly
    with pytest.raises(SystemExit, match=r"sl/chile/2023-01.*already cover"):
        cli.main([*SL_2023, "--months", "3"])
    assert _keys(ct) == ["sl/chile/2023-01", "sl/chile/2023-02"]
    assert cli.main([*SL_2023[:-1], "2023-02-28"]) == 0  # re-planning the same is a no-op
    assert cli.main(SL_2023) == 0  # monthly, adding March onward, is fine
    assert len(_keys(ct)) == 12


def test_plan_area_prints_the_wait_plus_run_estimate(ct, caplog):
    import logging

    with caplog.at_level(logging.INFO):
        assert cli.main([*SL_2023, "--months", "3"]) == 0
    # 4 single-level requests of a ~3.25 h median wait each: about half a day
    assert "planned 4 requests" in caplog.text
    assert "~0.6 days of CDS time at one job at a time" in caplog.text
    assert "sl 4 requests" in caplog.text
    assert "fields/s (measured on pressure levels" not in caplog.text  # D40's single rate


class _CostingCds:
    """A fake CDS that prices requests and refuses to run them."""

    def __init__(self, counts: str, limit: int = 121_000):
        self.counts, self.limit, self.priced = counts, limit, []
        self.client = self

    def estimate_costs(self, dataset, request):
        import calendar
        import itertools

        self.priced.append((dataset, request))
        if self.counts == "error":
            raise RuntimeError("HTTP 503 (fake)")
        combos = list(itertools.product(request["year"], request["month"], request["day"]))
        if self.counts == "real":
            combos = [(y, m, d) for y, m, d in combos
                      if int(d) <= calendar.monthrange(int(y), int(m))[1]]  # fmt: skip
        n = len(combos) * len(request["variable"]) * len(request["time"])
        n *= len(request.get("pressure_level") or [1])
        return {"id": "size", "cost": float(n), "limit": float(self.limit)}

    def submit(self, *a, **k):
        raise AssertionError("cost-check must never submit")


GLOBAL_SL = ["cost-check", "global", "--kinds", "sl", "--start", "2023-01-01",
             "--end", "2024-06-30", "--months", "3"]  # fmt: skip


@pytest.mark.parametrize(
    ("counts", "verdict"),
    [
        ("product", "the CDS counts the non-existent dates"),
        ("real", "the CDS counts only the real dates"),
    ],
)
def test_cost_check_prices_a_plan_without_submitting_or_planning(ct, monkeypatch, capsys,
                                                                 counts, verdict):  # fmt: skip
    fake = _CostingCds(counts)
    monkeypatch.setattr(cli, "_backend", lambda: fake)
    assert cli.main(GLOBAL_SL) == 0
    out = capsys.readouterr().out
    assert len(fake.priced) == 6  # 2023 Q1-Q4, 2024 Q1-Q2
    assert all(ds == "reanalysis-era5-single-levels" for ds, _ in fake.priced)
    # Q1 2023: 90 real days of 93 named (17 variables x 24 h)
    q1 = next(line for line in out.splitlines() if "sl/global/2023-01_2023-03" in line)
    assert "36720" in q1 and "37944" in q1
    q1_2024 = next(line for line in out.splitlines() if "sl/global/2024-01_2024-03" in line)
    assert "37128" in q1_2024  # 91 real days: 29 February 2024 is real
    assert verdict in out
    assert not (ct / "state" / "manifest.sqlite").exists()  # nothing planned


def test_cost_check_fails_when_the_cds_puts_a_request_over_its_limit(ct, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_backend", lambda: _CostingCds("product", limit=37_000))
    assert cli.main(GLOBAL_SL) == 1
    assert "OVER" in capsys.readouterr().out


def test_cost_check_reports_an_estimate_it_could_not_get(ct, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_backend", lambda: _CostingCds("error"))
    assert cli.main(GLOBAL_SL) == 1
    out = capsys.readouterr().out
    assert "HTTP 503 (fake)" in out
    assert "no verdict" in out


def test_cost_check_writes_its_findings_as_json(ct, monkeypatch):
    import json

    monkeypatch.setattr(cli, "_backend", lambda: _CostingCds("real"))
    out = ct / "cost.json"
    assert cli.main([*GLOBAL_SL, "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["verdict"] == "real"
    first = report["requests"][0]
    assert first["key"] == "sl/global/2023-01_2023-03"
    assert (first["real_fields"], first["named_fields"], first["cds_cost"]) == (36720, 37944, 36720)
    assert first["cds_limit"] == 121000


def test_a_three_month_request_downloads_verifies_and_ingests_to_its_own_store(ct, monkeypatch):
    import json

    from fakes import FakeCdsBackend

    args = ["plan-area", "chile", "--kinds", "sl", "--variables", "lcc", "--hours", "0",
            "--start", "2024-01-01", "--end", "2024-03-31", "--months", "3"]  # fmt: skip
    assert cli.main(args) == 0
    m = Manifest(ct / "state" / "manifest.sqlite")
    (row,) = m.conn.execute("SELECT key, request_json, expected_json FROM requests").fetchall()
    m.close()
    assert row["key"] == "sl/chile@vars-lcc/2024-01_2024-03"
    times = json.loads(row["expected_json"])["times"]
    assert len(times) == 91 and "2024-02-29T00:00" in times  # leap day in, 30-31 Feb out
    fake = FakeCdsBackend({FakeCdsBackend.req_key(json.loads(row["request_json"])): json.loads(
        row["expected_json"])}, polls_to_finish=1)  # fmt: skip
    monkeypatch.setattr(cli, "_backend", lambda: fake)
    assert cli.main(["download", "--poll", "0"]) == 0
    assert cli.main(["verify"]) == 0
    assert cli.main(["ingest"]) == 0
    store = ct / "data" / "era5" / "sl" / "chile@vars-lcc" / "2024-01_2024-03.zarr"
    assert (store / "zarr.json").is_file()
