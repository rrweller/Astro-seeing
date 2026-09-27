"""Cloud cover above a height from pressure-level cloud fractions (docs/RESEARCH.md §5 step 5).

C(h) combines the cloud fractions ``cc`` of all valid levels with Z ≥ h under an
overlap rule:

* ``random``:      1 − C = Π (1 − cᵢ)
* ``maximum``:     C = max cᵢ
* ``max-random``:  Geleyn & Hollingsworth (1979): adjacent cloudy levels overlap
  maximally, cloud blocks separated by a clear level overlap randomly:
  1 − C = (1 − c_top) Π_{i below top} (1 − max(cᵢ, cᵢ₊₁)) / (1 − cᵢ₊₁)

All three are non-increasing as h rises (removing the lowest level never adds
cover). The rule is chosen in phase 1 by checking C(surface) against ERA5's own
total cloud cover.

Cloud fractions outside [0, 1] are clipped **and counted** (``cc_below_0``,
``cc_above_1``); non-finite and underground levels are treated as clear and
counted (``cc_level_masked``).
"""

from __future__ import annotations

import numpy as np

from astroseeing.qc import QCCounts

OVERLAP_RULES = ("random", "maximum", "max-random")


def clean_cloud_fraction(
    cc: np.ndarray, level_valid: np.ndarray | None = None, qc: QCCounts | None = None
) -> np.ndarray:
    """Clip to [0, 1] and zero out invalid levels, recording every change in ``qc``."""
    cc = np.asarray(cc, dtype=np.float64)
    finite = np.isfinite(cc)
    valid = finite if level_valid is None else finite & np.asarray(level_valid, bool)
    if qc is not None:
        qc.add("cc_level_masked", int((~valid).sum()), cc.size)
        qc.add("cc_below_0", int((valid & (cc < 0)).sum()), int(valid.sum()))
        qc.add("cc_above_1", int((valid & (cc > 1)).sum()), int(valid.sum()))
    return np.where(valid, np.clip(np.where(finite, cc, 0.0), 0.0, 1.0), 0.0)


def suffix_cover(cc: np.ndarray, rule: str = "max-random") -> np.ndarray:
    """Cover of levels k..top for every k, shape (..., nlev + 1); last entry is 0.

    ``cc`` must already be cleaned (in [0, 1], level axis last, bottom → top).
    """
    if rule not in OVERLAP_RULES:
        raise ValueError(f"rule must be one of {OVERLAP_RULES}, got {rule!r}")
    cc = np.asarray(cc, dtype=np.float64)
    nlev = cc.shape[-1]
    out = np.zeros((*cc.shape[:-1], nlev + 1))
    if rule == "maximum":
        acc = np.zeros(cc.shape[:-1])
        for k in range(nlev - 1, -1, -1):
            acc = np.maximum(acc, cc[..., k])
            out[..., k] = acc
        return out

    clear = np.ones(cc.shape[:-1])
    for k in range(nlev - 1, -1, -1):
        c = cc[..., k]
        if rule == "random" or k == nlev - 1:
            clear = clear * (1.0 - c)
        else:
            above = cc[..., k + 1]
            # When the level above is overcast the clear fraction is already 0,
            # so the ratio's value does not matter; use 1 to avoid 0/0.
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(above < 1.0, (1.0 - np.maximum(c, above)) / (1.0 - above), 1.0)
            clear = clear * ratio
        out[..., k] = 1.0 - clear
    return np.clip(out, 0.0, 1.0)  # removes only floating-point round-off (|excess| < 1e-15)


def cloud_cover_above(
    h: np.ndarray,
    cc: np.ndarray,
    z_m: np.ndarray,
    level_valid: np.ndarray | None = None,
    rule: str = "max-random",
    qc: QCCounts | None = None,
) -> np.ndarray:
    """C(h): cover of all valid levels with Z ≥ h, shape (..., nh).

    Parameters
    ----------
    h
        Heights (m), shape (nh,) or (..., nh).
    cc, z_m, level_valid
        Level arrays (..., nlev), bottom → top; ``z_m`` must increase.
    """
    ccc = clean_cloud_fraction(cc, level_valid, qc)
    cover = suffix_cover(ccc, rule)  # (..., nlev+1)
    z = np.asarray(z_m, dtype=np.float64)
    # Invalid levels already have zero cover. Give each one the height of the
    # nearest valid level below it (running maximum), so the level count below
    # stays correct even when an invalid level sits mid-column.
    ok = np.isfinite(z)
    if level_valid is not None:
        ok &= np.asarray(level_valid, bool)
    zz = np.maximum.accumulate(np.where(ok, z, -np.inf), axis=-1)
    hh = np.asarray(h, dtype=np.float64)
    # k*(h) = number of levels strictly below h (levels are sorted by height).
    kstar = np.sum(zz[..., None, :] < hh[..., :, None], axis=-1)  # (..., nh)
    return np.take_along_axis(cover, kstar, axis=-1)
