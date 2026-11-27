"""Golden results for the reproductions (D57 item 5; map #6 "Golden tests").

One JSON file per paper in ``tests/golden/`` holds numbers only, never data: per
site and variant, the full settings, the input store ids and content hashes, our
statistics, the paper's printed target and the D19 tolerance, and whether the
variant is ``gating`` (the one a tolerance is judged on) or ``informational``.
Tests recompute the results from the NAS stores (``@pytest.mark.data``) and compare
them with :func:`check_golden`.

Moving a gating number needs Riley's approval (``allow_gating_change=True``);
moving an informational one needs a note on the result (D57 item 5).
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

SCHEMA = "astro-golden/1"
STATUSES = ("gating", "informational")


@dataclass(frozen=True)
class GoldenResult:
    """One site and variant of one paper's reproduction."""

    site: str
    variant: str
    status: str
    settings: dict[str, Any]
    inputs: list[dict[str, str]]
    statistics: dict[str, float | int]
    target: dict[str, float] | None = None
    #: ``{"abs": x, "on": [...]}`` (same units as the statistics) or ``{"rel": x, "on": [...]}``.
    tolerance: dict[str, Any] | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {self.status!r}")
        tol = self.tolerance
        if tol is None:
            return
        kinds = [k for k in ("abs", "rel") if k in tol]
        if len(kinds) != 1 or set(tol) != {kinds[0], "on"} or not tol["on"]:
            raise ValueError(f"{self.key}: tolerance must be one of abs or rel, with 'on': {tol}")
        if self.target is None or not set(tol["on"]) <= set(self.target):
            raise ValueError(f"{self.key}: the tolerance names statistics the target lacks")

    @property
    def key(self) -> str:
        return f"{self.site}/{self.variant}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def summary_statistics(
    values: np.ndarray, masked_levels: int | None = None
) -> dict[str, float | int]:
    """Median, quartiles (NumPy's default linear quantiles), the number of values and,
    if given, the masked-level count (``SiteColumns.masked_levels``; D57 item 5).

    NaN is refused rather than dropped: choose the hours before, and count what you drop.
    """
    v = np.asarray(values, dtype=np.float64).ravel()
    if v.size == 0:
        raise ValueError("no values")
    n_nan = int(np.isnan(v).sum())
    if n_nan:
        raise ValueError(f"{n_nan} NaN among {v.size} values; select the hours first")
    q1, med, q3 = np.percentile(v, [25.0, 50.0, 75.0])
    out: dict[str, float | int] = {
        "median": float(med),
        "q1": float(q1),
        "q3": float(q3),
        "hours": int(v.size),
    }
    if masked_levels is not None:
        out["masked_levels"] = int(masked_levels)
    return out


def meets_target(result: GoldenResult) -> bool | None:
    """Whether every statistic the tolerance names is within it of the paper's target;
    ``None`` when the result has no target."""
    if result.target is None or result.tolerance is None:
        return None
    tol = result.tolerance
    ok = True
    for name in tol["on"]:
        ours, theirs = float(result.statistics[name]), float(result.target[name])
        if "abs" in tol:
            ok &= abs(ours - theirs) <= float(tol["abs"]) + 1e-12
        else:
            ok &= abs(ours - theirs) <= float(tol["rel"]) * abs(theirs) + 1e-12
    return bool(ok)


def _check_finite(obj: Any, where: str) -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ValueError(f"{where}: NaN or infinity cannot go into a golden file")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _check_finite(v, f"{where}.{k}")
    elif isinstance(obj, list | tuple):
        for i, v in enumerate(obj):
            _check_finite(v, f"{where}[{i}]")


def load_golden(path: Path) -> tuple[str, list[GoldenResult]]:
    """(paper, results) from a golden file."""
    raw = json.loads(Path(path).read_text())
    if raw.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema {raw.get('schema')!r}, expected {SCHEMA!r}")
    return raw["paper"], [GoldenResult(**r) for r in raw["results"]]


def write_golden(
    path: Path,
    paper: str,
    results: Sequence[GoldenResult],
    *,
    allow_gating_change: bool = False,
) -> Path:
    """Write (or replace) a paper's golden file atomically.

    Results already in the file and not passed are kept. Any change to a gating
    result other than its note (statistics, status, settings, inputs, target,
    tolerance) raises unless ``allow_gating_change`` (Riley approved it); a changed
    informational statistic needs a new ``note``. The file is written to a temporary
    name, read back and compared, then renamed into place.
    """
    path = Path(path)
    keys = [r.key for r in results]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        raise ValueError(f"results {sorted(dup)} given twice")
    for r in results:
        _check_finite(r.as_dict(), r.key)

    merged: dict[str, GoldenResult] = {}
    if path.exists():
        old_paper, old = load_golden(path)
        if old_paper != paper:
            raise ValueError(f"{path} holds paper {old_paper!r}, not {paper!r}")
        merged = {r.key: r for r in old}
    for r in results:
        prev = merged.get(r.key)
        if prev is not None and prev.status == "gating":
            changed = [
                f
                for f in ("status", "settings", "inputs", "statistics", "target", "tolerance")
                if getattr(prev, f) != getattr(r, f)
            ]
            if changed and not allow_gating_change:
                raise ValueError(
                    f"{r.key}: changing a gating result ({', '.join(changed)}) needs Riley's "
                    "approval (allow_gating_change=True)"
                )
        if (
            prev is not None
            and prev.status == "informational"
            and prev.statistics != r.statistics
            and (not r.note or r.note == prev.note)
        ):
            raise ValueError(f"{r.key}: informational statistics changed; add a note why")
        merged[r.key] = r

    doc = {
        "schema": SCHEMA,
        "paper": paper,
        "results": [merged[k].as_dict() for k in sorted(merged)],
    }
    text = json.dumps(doc, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if tmp.read_text() != text or load_golden(tmp)[1] != [merged[k] for k in sorted(merged)]:
            raise OSError(f"read-back of {tmp} failed")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def check_golden(path: Path, recomputed: Sequence[GoldenResult], rtol: float = 1e-9) -> list[str]:
    """Differences between recomputed results and the golden file (empty if none).

    Every recorded result must be recomputed. Settings, inputs, status, target and
    tolerance must match exactly; statistics within ``rtol`` (relative), which allows
    only floating-point noise.
    """
    _, recorded = load_golden(path)
    by_key = {r.key: r for r in recorded}
    problems: list[str] = []
    for key in sorted(set(by_key) - {r.key for r in recomputed}):
        problems.append(f"{key}: in the golden file, not recomputed")
    for r in recomputed:
        rec = by_key.get(r.key)
        if rec is None:
            problems.append(f"{r.key}: not in the golden file")
            continue
        for name in ("status", "settings", "inputs", "target", "tolerance"):
            if getattr(r, name) != getattr(rec, name):
                problems.append(f"{r.key}: {name} differ")
        if set(r.statistics) != set(rec.statistics):
            problems.append(
                f"{r.key}: statistics {sorted(r.statistics)} != recorded {sorted(rec.statistics)}"
            )
        for name in sorted(set(r.statistics) & set(rec.statistics)):
            a, b = float(r.statistics[name]), float(rec.statistics[name])
            if not abs(a - b) <= rtol * abs(b) + 1e-12:
                problems.append(f"{r.key}: {name} {a} != recorded {b}")
    return problems
