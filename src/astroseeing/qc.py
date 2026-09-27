"""Quality-control counters.

AGENTS.md: "never clip, fill or smooth silently. Count and log every masked or
clipped value." Every function that masks, clips or falls back records the count
in a :class:`QCCounts` object, which callers merge, log and store with products.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping

import numpy as np

log = logging.getLogger(__name__)


class QCCounts:
    """Named integer counters, plus the number of items each was counted against."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.totals: Counter[str] = Counter()

    def add(
        self, name: str, count: int | np.integer, total: int | np.integer | None = None
    ) -> None:
        """Add ``count`` events of ``name`` (out of ``total`` items, if known)."""
        self.counts[name] += int(count)
        if total is not None:
            self.totals[name] += int(total)

    def add_mask(self, name: str, mask: np.ndarray) -> None:
        """Count the True entries of a boolean mask (total = mask size)."""
        mask = np.asarray(mask, dtype=bool)
        self.add(name, int(mask.sum()), mask.size)

    def merge(self, other: QCCounts) -> QCCounts:
        self.counts.update(other.counts)
        self.totals.update(other.totals)
        return self

    def __getitem__(self, name: str) -> int:
        return self.counts[name]

    def as_dict(self) -> dict[str, dict[str, int]]:
        names = sorted(set(self.counts) | set(self.totals))
        return {n: {"count": self.counts[n], "total": self.totals.get(n, 0)} for n in names}

    def log(self, logger: logging.Logger = log, context: str = "") -> None:
        for name, d in self.as_dict().items():
            if d["count"]:
                frac = f" ({d['count'] / d['total']:.3%})" if d["total"] else ""
                logger.info("QC %s%s: %d of %d%s", context, name, d["count"], d["total"], frac)

    @classmethod
    def from_dict(cls, d: Mapping[str, Mapping[str, int]]) -> QCCounts:
        q = cls()
        for name, v in d.items():
            q.add(name, v["count"], v.get("total") or None)
        return q

    def __repr__(self) -> str:
        return f"QCCounts({dict(self.counts)})"
