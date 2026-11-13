#!/usr/bin/env python3
"""Phase 2 and 3 download time at one CDS job at a time (D39), from measured queue waits.

At one job at a time each request holds the account's only place at the CDS from submit to
finish, so a campaign takes

    sum over requests of (queue wait + run time + idle before the next submit)

- queue wait: the 10th percentile, median and 90th percentile per kind, measured from a
  manifest copy over requests submitted since ``--since``;
- run time: pressure levels ``fields / 28`` s, single levels ``22.5 + fields / 17`` s
  (``reports/cds_throughput_one_job.md`` §2 and §5);
- idle: 18 s, the measured median.

The request plans cover 2021-2025 and keep each request inside one month, as
``RequestSpec.cds_request`` requires. Field counts are the CDS cost: variables x levels x
hours x days (29 levels x 5 variables on pressure levels, 17 single-level variables).
Gigabytes use the measured 1.87 MB per global pressure-level field (the global hour,
2026-11-13). Regional requests are much smaller, so their size isn't shown.

Read-only. Point it at a copy of the manifest, never the live file:
    pixi run python scripts/download_estimates.py COPY.sqlite [--since 2026-11-07]
"""

from __future__ import annotations

import argparse
import calendar
import sqlite3
import sys
from collections.abc import Callable

import pandas as pd

PL_PER_HOUR = 29 * 5  # levels x variables
SL_PER_HOUR = 17
MB_PER_GLOBAL_PL_FIELD = 270_996_300 / 145 / 1e6  # the global hour, 2026-11-13
IDLE_S = 18.0
RUN_S: dict[str, Callable[[int], float]] = {
    "pl": lambda f: f / 28.0,
    "sl": lambda f: 22.5 + f / 17.0,
}
MONTHS = [(y, m, calendar.monthrange(y, m)[1]) for y in range(2021, 2026) for m in range(1, 13)]


def waits(path: str, since: str) -> dict[str, tuple[float, float, float]]:
    """Queue wait in hours per kind: (p10, median, p90)."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    df = pd.read_sql_query(
        "SELECT kind, submitted_at, cds_started_at FROM requests"
        " WHERE cds_started_at IS NOT NULL AND submitted_at >= ?",
        db,
        params=(since,),
    )
    db.close()
    q = (
        pd.to_datetime(df.cds_started_at, utc=True, format="ISO8601")
        - pd.to_datetime(df.submitted_at, utc=True, format="ISO8601")
    ).dt.total_seconds() / 3600
    out = {}
    for kind in ("pl", "sl"):
        k = q[df.kind == kind]
        lo, mid, hi = out[kind] = (k.quantile(0.1), k.median(), k.quantile(0.9))
        print(f"- queue wait, {kind}, {len(k)} requests submitted since {since}:"
              f" median {mid:.2f} h, p10 {lo:.2f}, p90 {hi:.2f}")  # fmt: skip
    return out


def parts(k: int) -> Callable[[int], list[int]]:
    """Split a month of d days into k nearly equal requests."""
    return lambda d: [d // k + (1 if i < d % k else 0) for i in range(k)]


def weekly(d: int) -> list[int]:
    return parts(-(-d // 7))(d)


def daily(d: int) -> list[int]:
    return [1] * d


def plan(per_day: int, split: Callable[[int], list[int]], copies: int = 1) -> list[int]:
    return [per_day * n for *_, d in MONTHS for n in split(d)] * copies


def days(reqs: list[int], kind: str, w: tuple[float, float, float]) -> list[float]:
    return [sum(x + (RUN_S[kind](f) + IDLE_S) / 3600 for f in reqs) / 24 for x in w]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifest", help="a COPY of manifest.sqlite (opened read-only)")
    ap.add_argument("--since", default="2026-11-07", help="queue waits of requests submitted since")
    a = ap.parse_args()
    w = waits(a.manifest, a.since)
    pl_day, sl_day = 24 * PL_PER_HOUR, 24 * SL_PER_HOUR
    n_days = sum(d for *_, d in MONTHS)
    cases = {
        "Phase 3, hourly: one day per request": (plan(pl_day, daily), plan(sl_day, daily), True),
        "Phase 3, hourly: pl about weekly, sl monthly": (
            plan(pl_day, weekly), plan(sl_day, parts(1)), True),
        "Phase 3, hourly: pl half-monthly, sl monthly": (
            plan(pl_day, parts(2)), plan(sl_day, parts(1)), True),
        "Phase 3, 3-hourly: pl half-monthly, sl monthly": (
            plan(pl_day // 3, parts(2)), plan(sl_day // 3, parts(1)), True),
        "Phase 3, 3-hourly: pl monthly, sl monthly": (
            plan(pl_day // 3, parts(1)), plan(sl_day // 3, parts(1)), True),
        "Phase 2, 8 regions, all hours: pl half-monthly, sl monthly": (
            plan(pl_day, parts(2), 8), plan(sl_day, parts(1), 8), False),
        "Phase 2, 8 regions, ~13 night hours: pl monthly, sl monthly": (
            plan(13 * PL_PER_HOUR, parts(1), 8), plan(13 * SL_PER_HOUR, parts(1), 8), False),
    }  # fmt: skip
    print(f"\n2021-2025: {n_days} days, {len(MONTHS)} months.\n")
    print("| Plan | pl requests | largest pl request | sl requests | pl days | sl days"
          " | total days (p10-p90 waits) |")  # fmt: skip
    print("|---|---|---|---|---|---|---|")
    for name, (pl, sl, glob) in cases.items():
        p, s = days(pl, "pl", w["pl"]), days(sl, "sl", w["sl"])
        size = f", {max(pl) * MB_PER_GLOBAL_PL_FIELD / 1e3:.1f} GB" if glob else ""
        lo, mid, hi = (x + y for x, y in zip(p, s, strict=True))
        print(f"| {name} | {len(pl):,} | {max(pl):,} fields{size} | {len(sl):,} | {p[1]:.0f}"
              f" | {s[1]:.0f} | **{mid:.0f}** ({lo:.0f}-{hi:.0f}) |")  # fmt: skip
    pl_f, sl_f = pl_day * n_days, sl_day * n_days
    print(f"\nHourly, 5 years: {pl_f:,} pl + {sl_f:,} sl = {pl_f + sl_f:,} fields."
          f" CDS run time alone: pl {RUN_S['pl'](pl_f) / 86400:.1f} days,"
          f" sl {RUN_S['sl'](sl_f) / 86400:.1f} days."
          f" Global pl volume: {pl_f * MB_PER_GLOBAL_PL_FIELD / 1e6:.1f} TB"
          f" ({pl_day * MB_PER_GLOBAL_PL_FIELD / 1e3:.2f} GB per day).")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
