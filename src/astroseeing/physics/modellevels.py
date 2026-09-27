"""Heights of ERA5 model levels (docs/RESEARCH.md §4.3).

Model levels carry no heights; integrate the hypsometric equation upward from the
surface (Simmons & Burridge 1981 discretisation, as in ECMWF's
``compute_geopotential_on_ml`` recipe):

    p_{k+1/2} = a_{k+1/2} + b_{k+1/2} · sp                       half-level pressure
    Φ_{k−1/2} = Φ_{k+1/2} + R_d T_v,k ln(p_{k+1/2}/p_{k−1/2})       half levels, upward
    Φ_k       = Φ_{k+1/2} + α_k R_d T_v,k                          full levels
    α_k       = 1 − p_{k−1/2}/(p_{k+1/2} − p_{k−1/2}) · ln(p_{k+1/2}/p_{k−1/2})
    α_1       = ln 2                                               (top level)
    T_v       = T (1 + c_q q)

Arrays use ECMWF order (level 1 = top) along the last axis: ``t`` and ``q`` have
``nlev`` full levels; ``a_half`` and ``b_half`` have ``nlev + 1`` half levels
(top → surface). Integrating upward means only levels below a given level
matter, so a bottom subset (e.g. levels 49–137) gives identical heights.
"""

from __future__ import annotations

import numpy as np

from astroseeing.constants import G0, R_DRY

#: T_v = T (1 + c_q q). docs/RESEARCH.md §4.3 uses 0.608 [check against ECMWF's script].
TV_COEFF = 0.608


def half_level_pressure(a_half: np.ndarray, b_half: np.ndarray, sp_pa: np.ndarray) -> np.ndarray:
    """p_half = a + b · sp (Pa), shape (..., nlev+1)."""
    return (
        np.asarray(a_half, dtype=np.float64)
        + np.asarray(b_half, dtype=np.float64) * np.asarray(sp_pa, dtype=np.float64)[..., None]
    )


def model_level_heights(
    t_k: np.ndarray,
    q: np.ndarray,
    sp_pa: np.ndarray,
    z_surface_m: np.ndarray,
    a_half: np.ndarray,
    b_half: np.ndarray,
    tv_coeff: float = TV_COEFF,
    r_dry: float = R_DRY,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Geopotential heights of full and half model levels.

    Returns
    -------
    (z_full, z_half, p_half)
        z_full (..., nlev) m, z_half (..., nlev+1) m, p_half (..., nlev+1) Pa, all
        top → surface. The top half level has p = 0 when a=b=0 there; its height is
        then infinite, so it is returned as NaN.
    """
    t = np.asarray(t_k, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    nlev = t.shape[-1]
    if np.shape(a_half)[-1] != nlev + 1 or np.shape(b_half)[-1] != nlev + 1:
        raise ValueError("a_half and b_half need nlev + 1 entries")
    ph = half_level_pressure(a_half, b_half, sp_pa)
    tv_r = r_dry * t * (1.0 + tv_coeff * q)

    phi_half = np.full(ph.shape, np.nan)
    phi_full = np.full(t.shape, np.nan)
    phi_half[..., nlev] = np.asarray(z_surface_m, dtype=np.float64) * G0
    for k in range(nlev - 1, -1, -1):  # full level k lies between half levels k (above) and k+1
        p_lo = ph[..., k + 1]
        p_hi = ph[..., k]
        if k == 0 and np.all(p_hi <= 0):
            dlogp = np.full_like(p_lo, np.nan)
            alpha = np.full_like(p_lo, np.log(2.0))
        else:
            dlogp = np.log(p_lo / p_hi)
            alpha = 1.0 - p_hi / (p_lo - p_hi) * dlogp
        phi_full[..., k] = phi_half[..., k + 1] + alpha * tv_r[..., k]
        phi_half[..., k] = phi_half[..., k + 1] + tv_r[..., k] * dlogp
    return phi_full / G0, phi_half / G0, ph
