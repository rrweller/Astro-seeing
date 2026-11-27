"""Price a plan with the CDS cost estimator, without submitting anything (D55 item 5, D63).

A request over several months names days that don't exist (30 February, 31 April): the
CDS form takes a year × month × day product. Our ``cds_cost`` counts the whole product,
our ``n_fields`` only the real dates. The CDS's own estimate shows which one it charges,
which sets how close to its limit a multi-month request may go.

The estimator (``Client.estimate_costs``, the CDS ``costing`` endpoint) prices a request
without creating a job, so it doesn't use the account's one CDS place (D39).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

#: ``estimate(dataset, request) -> the CDS's answer``; ``Client.estimate_costs`` in use.
Estimator = Callable[[str, dict[str, Any]], Any]


def read_estimate(answer: Any) -> tuple[float, float]:
    """``(cost, limit)`` from the estimator's answer: ``{"id": "size", "cost", "limit"}``
    as seen on 2026-09-27 and 2026-11-13 (``reports/cds_smoke_test.json``, throughput
    report §6.4). Any other shape raises, so a changed API is reported, never guessed."""
    if isinstance(answer, dict) and "cost" in answer and "limit" in answer:
        return float(answer["cost"]), float(answer["limit"])
    raise ValueError(f"unrecognised cost estimate: {answer!r}")


@dataclass
class CostRow:
    key: str
    dataset: str
    real_fields: int  # fields on the real dates: what verification expects
    named_fields: int  # the whole year x month x day product (RequestSpec.cds_cost)
    cds_cost: float | None = None
    cds_limit: float | None = None
    error: str | None = None
    answer: Any = None

    @property
    def counts(self) -> str | None:
        """Which count the CDS charged: ``product``, ``real``, ``other``; ``None`` when no
        estimate or the request names no non-existent date (both counts are equal)."""
        if self.cds_cost is None or self.real_fields == self.named_fields:
            return None
        if self.cds_cost == self.named_fields:
            return "product"
        if self.cds_cost == self.real_fields:
            return "real"
        return "other"

    @property
    def over_limit(self) -> bool:
        return (
            self.cds_cost is not None
            and self.cds_limit is not None
            and (self.cds_cost > self.cds_limit)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "dataset": self.dataset,
            "real_fields": self.real_fields,
            "named_fields": self.named_fields,
            "cds_cost": None if self.cds_cost is None else round(self.cds_cost),
            "cds_limit": None if self.cds_limit is None else round(self.cds_limit),
            "counts": self.counts,
            "over_limit": self.over_limit,
            "error": self.error,
            "answer": self.answer,
        }


def price_plan(specs: Iterable, estimate: Estimator) -> list[CostRow]:
    """Ask the CDS to price each request; an estimate that fails is recorded, not raised."""
    rows = []
    for spec in specs:
        row = CostRow(spec.key, spec.dataset, spec.n_fields, spec.cds_cost)
        try:
            row.answer = estimate(spec.dataset, spec.cds_request())
            row.cds_cost, row.cds_limit = read_estimate(row.answer)
        except Exception as e:  # reported per request; the command then fails
            row.error = f"{type(e).__name__}: {e}"
        rows.append(row)
    return rows


def verdict(rows: list[CostRow]) -> str | None:
    """``product`` or ``real`` when every request naming a non-existent date agrees and no
    estimate failed; ``mixed`` when they disagree; ``None`` when there is no verdict."""
    if any(r.error for r in rows):
        return None
    seen = {r.counts for r in rows if r.counts is not None}
    if not seen:
        return None
    return seen.pop() if len(seen) == 1 else "mixed"


VERDICT_TEXT = {
    "product": "the CDS counts the non-existent dates (it charges the whole year x month x "
    "day product); planning's cost limit already uses that count",
    "real": "the CDS counts only the real dates; planning's limit (the whole product) is "
    "conservative by up to 3 days of fields per request",
    "mixed": "the CDS's counts disagree between requests; read the rows",
    "other": "the CDS's cost matches neither count; read the rows",
    None: "no verdict: an estimate failed, or no request names a non-existent date "
    "(plan several months with --months)",
}
