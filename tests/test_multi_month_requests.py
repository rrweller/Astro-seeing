"""Single-level requests spanning several months (D55 item 5, D63)."""

from __future__ import annotations

import datetime as dt
import shutil

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from astroseeing import config
from astroseeing.download.requests import Area, plan_requests
from astroseeing.manifest import Manifest

AREA = Area(-24.0, -71.0, -25.0, -70.0)
D = dt.date


def _times(spec) -> set[str]:
    return set(spec.expected()["times"])


def test_three_whole_months_are_one_request_with_only_real_dates():
    (spec,) = plan_requests("sl", "x", D(2023, 1, 1), D(2023, 3, 31), AREA,
                            granularity="month", months_per_request=3)  # fmt: skip
    assert spec.key == "sl/x/2023-01_2023-03"
    req = spec.cds_request()
    assert req["year"] == ["2023"]
    assert req["month"] == ["01", "02", "03"]
    assert req["day"] == [f"{d:02d}" for d in range(1, 32)]
    times = _times(spec)
    assert len(times) == 90 * 24  # 31 + 28 + 31 days, no 29-31 February
    assert "2023-02-28T23:00" in times
    assert not any(t.startswith(("2023-02-29", "2023-02-30", "2023-02-31")) for t in times)
    assert spec.n_fields == 90 * 24 * 17


def _plan(start, end, n=3, **kw):
    return plan_requests("sl", "x", start, end, AREA, granularity="month",
                         months_per_request=n, **kw)  # fmt: skip


def test_leap_year_block_has_29_february_and_nothing_after():
    (spec,) = _plan(D(2024, 1, 1), D(2024, 3, 31))
    times = _times(spec)
    assert len(times) == 91 * 24
    assert "2024-02-29T00:00" in times
    assert not any(t.startswith(("2024-02-30", "2024-02-31")) for t in times)


def test_april_to_june_has_no_31_april_or_31_june():
    (spec,) = _plan(D(2023, 4, 1), D(2023, 6, 30))
    assert spec.cds_request()["day"][-1] == "31"  # May has a 31st
    times = _times(spec)
    assert len(times) == (30 + 31 + 30) * 24
    assert not any(t.startswith(("2023-04-31", "2023-06-31")) for t in times)
    assert spec.cds_cost == 3 * 31 * 24 * 17  # the whole product, the upper bound
    assert spec.n_fields == 91 * 24 * 17


def test_blocks_follow_the_calendar_and_never_cross_a_year():
    specs = _plan(D(2023, 11, 1), D(2024, 7, 31))
    assert [s.period_label for s in specs] == [
        "2023-11",  # October is not in the plan: a broken block stays monthly
        "2023-12",
        "2024-01_2024-03",
        "2024-04_2024-06",
        "2024-07",
    ]
    for s in specs:
        assert len(s.cds_request()["year"]) == 1


def test_partial_first_and_last_months_stay_on_their_own():
    specs = _plan(D(2023, 2, 10), D(2023, 8, 15))
    assert [s.period_label for s in specs] == [
        "2023-02-10_2023-02-28",
        "2023-03",
        "2023-04_2023-06",
        "2023-07",
        "2023-08-01_2023-08-15",
    ]


def test_a_block_merges_the_same_whatever_day_the_plan_starts():
    """Review finding: a plan starting in February merged February and March, which a
    January-March plan then overlapped. Only whole calendar blocks merge."""
    from_jan = {s.key for s in _plan(D(2023, 1, 10), D(2023, 6, 30))}
    from_feb = {s.key for s in _plan(D(2023, 2, 1), D(2023, 6, 30))}
    assert from_feb <= from_jan
    assert {"sl/x/2023-02", "sl/x/2023-03", "sl/x/2023-04_2023-06"} == from_feb
    ends_feb = {s.key for s in _plan(D(2023, 1, 1), D(2023, 2, 28))}
    assert ends_feb == {"sl/x/2023-01", "sl/x/2023-02"}


def test_every_day_is_requested_exactly_once():
    start, end = D(2023, 2, 10), D(2024, 12, 31)
    specs = _plan(start, end)
    days = [d for s in specs for d in s.dates]
    assert days == [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    keys = [s.key for s in specs]
    assert len(set(keys)) == len(keys)


@pytest.fixture
def era5_request(tmp_path, monkeypatch):
    """Edit ``request:`` in a copy of configs/era5.yaml for one test."""
    cfg_dir = tmp_path / "configs"
    shutil.copytree(config.REPO_CONFIG_DIR, cfg_dir)
    monkeypatch.setenv("ASTRO_CONFIG_DIR", str(cfg_dir))

    def edit(**changes):
        path = cfg_dir / "era5.yaml"
        cfg = yaml.safe_load(path.read_text())
        cfg["request"].update(changes)
        path.write_text(yaml.safe_dump(cfg))
        config.load_config.cache_clear()

    config.load_config.cache_clear()
    yield edit
    config.load_config.cache_clear()


def test_pressure_levels_stay_one_month_at_most():
    with pytest.raises(ValueError, match="at most 1 month"):
        plan_requests("pl", "x", D(2023, 1, 1), D(2023, 3, 31), AREA,
                      granularity="month", months_per_request=2)  # fmt: skip


def test_more_months_than_configured_are_refused():
    with pytest.raises(ValueError, match="at most 3 month"):
        _plan(D(2023, 1, 1), D(2023, 12, 31), n=4)


def test_months_need_month_granularity():
    with pytest.raises(ValueError, match="granularity"):
        plan_requests("sl", "x", D(2023, 1, 1), D(2023, 3, 31), AREA, months_per_request=3)


def test_a_merged_request_over_the_cost_limit_is_refused_not_split(era5_request):
    # 3 months of 17 variables x 24 h on the product's 3 x 31 days: 37,944 fields
    era5_request(max_fields={"pl": 60000, "sl": 37943, "static": 121000})
    with pytest.raises(ValueError, match="37944 fields, over the CDS limit of 37943"):
        _plan(D(2023, 4, 1), D(2023, 6, 30))
    era5_request(max_fields={"pl": 60000, "sl": 37944, "static": 121000})
    (spec,) = _plan(D(2023, 4, 1), D(2023, 6, 30))  # exactly at the limit is fine
    assert spec.cds_cost == 37944


def test_the_manifest_refuses_a_request_over_the_cost_limit(tmp_path):
    (whole,) = plan_requests("pl", "x", D(2023, 1, 1), D(2023, 1, 31), AREA,
                             granularity="month", split=False)  # fmt: skip
    assert whole.cds_cost == 107_880  # over 60,000: only an estimate may build this
    m = Manifest(tmp_path / "m.sqlite")
    with pytest.raises(ValueError, match="over the CDS limit"):
        m.add_request(whole)
    assert m.conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("kind", "start", "end", "kw", "expected"),
    [
        # Hashes from the code before multi-month requests (origin/dev, 2026-11-27): the
        # manifest's existing rows must keep their identity.
        ("sl", D(2023, 1, 1), D(2023, 1, 31), {}, [
            ("sl/x/2023-01", "c576e4f424cf2b6811374c81b3856d4cd3796f37acf0bdd05d33f77b51817968"),
        ]),
        ("pl", D(2023, 1, 1), D(2023, 1, 31), {}, [
            ("pl/x/2023-01-01_2023-01-16",
             "9832b8c13f3e7f59d5f9db0373b10c7090778b88a9401c437c14c629b4b27656"),
            ("pl/x/2023-01-17_2023-01-31",
             "d4ab13cd58c260b059cc5abd12139306c7f8fc0e8407438f86711d5ce8a60557"),
        ]),
        ("sl", D(2023, 1, 1), D(2023, 2, 28), {"day_step": 4}, [
            ("sl/x/2023-01-01_2023-01-29",
             "c2d4652acff336d7033d49c20bf8ce64660fe389e6a31e043ea60bac816ef090"),
            ("sl/x/2023-02-01_2023-02-25",
             "fa94275e31265b27e674635cb26369b0b14839b23f8ce092d00f9fa6c278cca8"),
        ]),
    ],
)  # fmt: skip
def test_one_month_plans_keep_their_keys_and_hashes(kind, start, end, kw, expected):
    specs = plan_requests(kind, "x", start, end, AREA, granularity="month", **kw)
    assert [(s.key, s.request_hash()) for s in specs] == expected
    assert all(s.cds_cost == s.n_fields for s in specs)


def test_every_4th_day_merges_across_months_with_only_real_dates():
    (spec,) = _plan(D(2023, 1, 1), D(2023, 3, 31), day_step=4)
    # days 1, 5, ..., 29: February 2023 has no 29th, so it has 7 of them
    assert len(spec.dates) == 8 + 7 + 8
    assert spec.key == "sl/x/2023-01-01_2023-03-29"
    assert spec.cds_request()["day"] == [f"{d:02d}" for d in range(1, 30, 4)]


@settings(max_examples=200, deadline=None)
@given(
    start=st.dates(D(2019, 1, 1), D(2026, 12, 31)),
    length=st.integers(0, 800),
    n=st.integers(1, 3),
    day_step=st.sampled_from([1, 1, 2, 4]),
)
def test_any_plan_covers_each_day_once_with_valid_unique_requests(start, length, n, day_step):
    end = start + dt.timedelta(days=length)
    specs = _plan(start, end, n=n, day_step=day_step)
    want = [start + dt.timedelta(days=i) for i in range(length + 1)]
    want = [d for d in want if (d.day - 1) % day_step == 0]
    assert [d for s in specs for d in s.dates] == want
    assert len({s.key for s in specs}) == len(specs)
    for s in specs:
        req = s.cds_request()  # a valid year x month x day product, or it raises
        assert len(req["year"]) == 1
        assert len(req["month"]) <= n
        assert s.n_fields <= s.cds_cost <= 121_000
        assert len(s.expected()["times"]) == len(s.dates) * 24
