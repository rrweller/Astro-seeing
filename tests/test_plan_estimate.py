"""CDS time per plan: queue wait plus run time per request (D63; report §5, §7)."""

from __future__ import annotations

import datetime as dt

import pytest

from astroseeing.download.estimate import KindRates, estimate_plan, load_rates
from astroseeing.download.requests import plan_requests

D = dt.date


def test_one_request_is_its_wait_plus_its_run_plus_the_idle_gap():
    """Report §5's model, W + F / R: one global hour of pressure levels per day (145
    fields x 24 = 3,480) at 29 fields/s runs 120 s; with a 4 h wait and 18 s idle that is
    14,538 s."""
    (spec,) = plan_requests("pl", "x", D(2023, 6, 1), D(2023, 6, 1), None)
    rates = {"pl": KindRates(queue_wait_h=(3.0, 4.0, 5.0), run_fields_per_s=29.0,
                             run_overhead_s=0.0)}  # fmt: skip
    est = estimate_plan([spec], rates=rates, idle_s=18.0)
    assert est.total.requests == 1
    assert est.total.fields == 3480
    assert est.total.hours == pytest.approx((10_938 / 3600, 14_538 / 3600, 18_138 / 3600))


def test_single_levels_carry_a_fixed_run_cost_per_request():
    """Report §2: single-level run time is 22.5 s + fields / 17."""
    (spec,) = plan_requests("sl", "x", D(2023, 6, 1), D(2023, 6, 1), None)  # 408 fields
    rates = {"sl": KindRates(queue_wait_h=(0.0, 0.0, 0.0), run_fields_per_s=17.0,
                             run_overhead_s=22.5)}  # fmt: skip
    assert estimate_plan([spec], rates=rates, idle_s=0.0).total.hours[1] * 3600 == (
        pytest.approx(46.5)
    )


def test_five_years_global_matches_the_throughput_report():
    """Report §7.2, row "pressure levels half-monthly, single levels monthly": 120 + 60
    requests, 23 + 9 CDS days, 32 in all (27-36 with every wait at p10 or p90)."""
    start, end = D(2021, 1, 1), D(2025, 12, 31)
    pl = plan_requests("pl", "global", start, end, None, granularity="month")
    sl = plan_requests("sl", "global", start, end, None, granularity="month")
    assert (len(pl), len(sl)) == (120, 60)
    est = estimate_plan(pl + sl)
    assert round(est.by_kind["pl"].days[1]) == 23
    assert round(est.by_kind["sl"].days[1]) == 9
    assert [round(x) for x in est.total.days] == [27, 32, 36]


def test_three_month_single_levels_cut_their_days_to_about_three():
    """D55 item 9: single levels at 3 months per request take ~3-4 CDS days of 5 years."""
    sl = plan_requests("sl", "global", D(2021, 1, 1), D(2025, 12, 31), None,
                       granularity="month", months_per_request=3)  # fmt: skip
    assert len(sl) == 20
    days = estimate_plan(sl).by_kind["sl"].days[1]
    assert 3.0 <= days <= 4.0


def test_rates_come_from_the_config_per_kind():
    rates = load_rates()
    assert rates["pl"].queue_wait_h == (3.38, 4.04, 4.28)
    assert rates["sl"].queue_wait_h == (2.76, 3.25, 4.63)
    assert (rates["pl"].run_fields_per_s, rates["sl"].run_fields_per_s) == (28.0, 17.0)
    assert (rates["pl"].run_overhead_s, rates["sl"].run_overhead_s) == (0.0, 22.5)
    assert rates["static"] == rates["sl"]  # requested from the single-levels dataset


def test_an_empty_plan_takes_no_time():
    est = estimate_plan([])
    assert est.total.requests == 0
    assert est.total.days == (0.0, 0.0, 0.0)
