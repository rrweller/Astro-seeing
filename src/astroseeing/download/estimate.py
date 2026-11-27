"""How long a plan holds the account's one CDS place (D39), request by request (D63).

At one job at a time, a request takes about ``W + overhead + F / R`` from submit to finish
(``reports/cds_throughput_one_job.md`` §5, §7.1): ``W`` the queue wait, ``F`` its fields,
``R`` the CDS's processing rate for the kind and ``overhead`` a fixed run cost per request
(single levels: 22.5 s). Then ``idle_s`` passes before the next submission. A plan's time
is the sum over its requests, so the request count matters far more than the field count.

The queue wait is given as its 10th percentile, median and 90th percentile. The range
assumes every wait at p10, or every wait at p90: the CDS's load moves all waits together,
so it is a range of scenarios, not a confidence interval. The rates live in
``configs/era5.yaml`` (``request.planning``) and should be re-measured before any large
campaign (``scripts/download_estimates.py``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from astroseeing.config import load_config


@dataclass(frozen=True)
class KindRates:
    """Planning rates for one request kind."""

    queue_wait_h: tuple[float, float, float]  # p10, median, p90
    run_fields_per_s: float
    run_overhead_s: float = 0.0

    def request_seconds(self, fields: int, idle_s: float) -> tuple[float, float, float]:
        after_wait = self.run_overhead_s + fields / self.run_fields_per_s + idle_s
        lo, mid, hi = self.queue_wait_h
        return (lo * 3600 + after_wait, mid * 3600 + after_wait, hi * 3600 + after_wait)


@dataclass
class Tally:
    """Requests, fields and CDS time (p10, median, p90 waits) for part of a plan."""

    requests: int = 0
    fields: int = 0
    seconds: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def add(self, fields: int, seconds: tuple[float, float, float]) -> None:
        self.requests += 1
        self.fields += fields
        self.seconds = tuple(a + b for a, b in zip(self.seconds, seconds, strict=True))

    @property
    def hours(self) -> tuple[float, float, float]:
        return tuple(s / 3600 for s in self.seconds)

    @property
    def days(self) -> tuple[float, float, float]:
        return tuple(s / 86400 for s in self.seconds)


@dataclass
class PlanEstimate:
    by_kind: dict[str, Tally] = field(default_factory=dict)
    total: Tally = field(default_factory=Tally)

    def summary(self) -> str:
        """One line for the planning log, e.g. ``~32.0 days (27.0-36.2 ...)``."""
        lo, mid, hi = self.total.days
        parts = ", ".join(
            f"{k} {t.requests} requests ~{t.days[1]:.1f} d" for k, t in sorted(self.by_kind.items())
        )
        return (
            f"~{mid:.1f} days of CDS time at one job at a time ({lo:.1f}-{hi:.1f} with every "
            f"queue wait at its p10 or p90; {parts}; wait + run per request, "
            "configs/era5.yaml request.planning)"
        )


def load_rates() -> dict[str, KindRates]:
    """Per-kind planning rates from ``configs/era5.yaml`` ``request.planning.kinds``."""
    kinds = load_config("era5")["request"]["planning"]["kinds"]
    return {
        k: KindRates(
            queue_wait_h=tuple(float(x) for x in v["queue_wait_h"]),
            run_fields_per_s=float(v["run_fields_per_s"]),
            run_overhead_s=float(v["run_overhead_s"]),
        )
        for k, v in kinds.items()
    }


def estimate_plan(
    specs: Iterable,
    rates: Mapping[str, KindRates] | None = None,
    idle_s: float | None = None,
) -> PlanEstimate:
    """CDS time for ``specs`` (``RequestSpec``s), run one after another.

    Run time uses each request's real fields (``n_fields``): a request over several months
    names non-existent dates, but nothing is produced for them.
    """
    rates = load_rates() if rates is None else rates
    if idle_s is None:
        idle_s = float(load_config("era5")["request"]["planning"]["idle_s"])
    est = PlanEstimate()
    for spec in specs:
        sec = rates[spec.kind].request_seconds(spec.n_fields, idle_s)
        est.by_kind.setdefault(spec.kind, Tally()).add(spec.n_fields, sec)
        est.total.add(spec.n_fields, sec)
    return est
