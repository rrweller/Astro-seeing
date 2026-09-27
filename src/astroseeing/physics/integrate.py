"""Integrals of Cₙ² over slabs (docs/RESEARCH.md §4.3, §4.5, §5).

Cₙ² is constant within each slab [z_bot, z_top). Invalid slabs (NaN Cₙ² or
``valid`` False) contribute nothing. All results are exact for that
piecewise-constant profile, including partial slabs.
"""

from __future__ import annotations

import numpy as np


def _clean(cn2: np.ndarray, valid: np.ndarray | None) -> np.ndarray:
    cn2 = np.asarray(cn2, dtype=np.float64)
    ok = np.isfinite(cn2)
    if valid is not None:
        ok &= np.asarray(valid, bool)
    return np.where(ok, cn2, 0.0)


def column_integral(
    cn2: np.ndarray, z_bot: np.ndarray, z_top: np.ndarray, valid: np.ndarray | None = None
) -> np.ndarray:
    """J = Σ Cₙ² Δz over valid slabs, m^(1/3). Level axis last."""
    c = _clean(cn2, valid)
    dz = np.where(c != 0, np.asarray(z_top) - np.asarray(z_bot), 0.0)
    return np.sum(c * dz, axis=-1)


def integral_above(
    h: np.ndarray,
    cn2: np.ndarray,
    z_bot: np.ndarray,
    z_top: np.ndarray,
    valid: np.ndarray | None = None,
) -> np.ndarray:
    """J(h) = ∫_h^top Cₙ² dz for each height in ``h``.

    Parameters
    ----------
    h
        Heights (m). Shape (nh,) to use one height grid for all columns, or
        (..., nh) matching the column shape.
    cn2, z_bot, z_top, valid
        Slab arrays of shape (..., nslab).

    Returns
    -------
    ndarray of shape (..., nh). Non-increasing in h by construction.
    """
    c = _clean(cn2, valid)[..., None, :]  # (..., 1, nslab)
    zb = np.asarray(z_bot, dtype=np.float64)[..., None, :]
    zt = np.asarray(z_top, dtype=np.float64)[..., None, :]
    hh = np.asarray(h, dtype=np.float64)[..., :, None]  # (..., nh, 1)
    overlap = np.clip(zt - np.maximum(hh, zb), 0.0, None)
    overlap = np.where(c != 0, overlap, 0.0)
    return np.sum(c * overlap, axis=-1)


def weighted_moment_above(
    h_obs: np.ndarray,
    cn2: np.ndarray,
    z_bot: np.ndarray,
    z_top: np.ndarray,
    power: float = 5.0 / 3.0,
    valid: np.ndarray | None = None,
) -> np.ndarray:
    """∫_{h_obs}^top Cₙ² (z − h_obs)^power dz, exact for piecewise-constant Cₙ².

    Used for the isoplanatic angle θ₀ (power 5/3). ``h_obs`` has the column shape.
    """
    c = _clean(cn2, valid)
    ho = np.asarray(h_obs, dtype=np.float64)[..., None]
    lo = np.clip(np.asarray(z_bot) - ho, 0.0, None)
    hi = np.clip(np.asarray(z_top) - ho, 0.0, None)
    q = power + 1.0
    contrib = np.where(c != 0, c * (hi**q - lo**q) / q, 0.0)
    return np.sum(contrib, axis=-1)


def weighted_sum_above(
    h_obs: np.ndarray,
    cn2: np.ndarray,
    z_bot: np.ndarray,
    z_top: np.ndarray,
    weight: np.ndarray,
    valid: np.ndarray | None = None,
) -> np.ndarray:
    """∫_{h_obs}^top Cₙ² · w dz with w constant per slab (e.g. |V|^(5/3) for V₀)."""
    c = _clean(cn2, valid) * np.where(np.isfinite(weight), weight, 0.0)
    ho = np.asarray(h_obs, dtype=np.float64)[..., None]
    overlap = np.clip(np.asarray(z_top) - np.maximum(ho, np.asarray(z_bot)), 0.0, None)
    return np.sum(np.where(c != 0, c * overlap, 0.0), axis=-1)
