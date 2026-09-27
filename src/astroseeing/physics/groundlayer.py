"""Ground-layer options (docs/RESEARCH.md §5 step 3, §4.7). All experimental until phase 1.

Osborn–Sarazin relocation
    O&S 2018 §5.4 take the model's turbulence from the grid altitude z_g to
    z_g + 1 km and add it into the levels at the observatory altitude. We
    generalise that to any observer height h as

        J(h) = I(max(h, z_g + D)) + [I(z_g) − I(z_g + D)],   I(x) = ∫_x^top Cₙ² dz

    with D = 1000 m. For h ≥ z_g + D this is exactly O&S (model profile above the
    site plus the relocated lowest km). For h ≤ z_g + D it is the full model column,
    so nothing is double-counted for valley pixels. J(h) is continuous and
    non-increasing in h. This generalisation is our choice (docs/decisions.md).

W71 / Monin–Obukhov similarity (as written in OTCliM; RESEARCH §4.7)
    C_T² = θ*² z^(−2/3) g(ζ),  θ* = −w′θ′/u*,  ζ = z/L,  L = −u*³ T / (κ g w′θ′)
    g(ζ) = 4.9 (1 − 6.1ζ)^(−2/3) for ζ < 0;  4.9 (1 + 2.2 ζ^(2/3)) for ζ ≥ 0
    Cₙ² = (A P/T²)² (1 + 0.03/β)² C_T²
    w′θ′ = −H/(ρ c_p) for H positive downward (ECMWF convention [check on data]).
"""

from __future__ import annotations

import numpy as np

from astroseeing.constants import CP_DRY, G0, OS_SPLIT_HEIGHT, R_DRY, TATARSKII_A, VON_KARMAN
from astroseeing.physics.integrate import integral_above


def relocated_integral_above(
    h: np.ndarray,
    cn2: np.ndarray,
    z_bot: np.ndarray,
    z_top: np.ndarray,
    z_ground_model: np.ndarray,
    depth: float = OS_SPLIT_HEIGHT,
    valid: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """O&S relocation generalised to heights ``h``.

    Returns
    -------
    (J_free, J_gl)
        J_free(h) = I(max(h, z_g + D)), shape (..., nh); J_gl = I(z_g) − I(z_g + D),
        shape (...). Total J(h) = J_free + J_gl[..., None].
    """
    zg = np.asarray(z_ground_model, dtype=np.float64)
    hh = np.asarray(h, dtype=np.float64)
    h_eff = np.maximum(hh, (zg + depth)[..., None])
    j_free = integral_above(h_eff, cn2, z_bot, z_top, valid)
    ends = np.stack([zg, zg + depth], axis=-1)
    i_ends = integral_above(ends, cn2, z_bot, z_top, valid)
    j_gl = i_ends[..., 0] - i_ends[..., 1]
    return j_free, j_gl


def w71_g(zeta: np.ndarray) -> np.ndarray:
    """Similarity function g(ζ) for C_T² (Wyngaard, Izumi & Collins 1971 form)."""
    zeta = np.asarray(zeta, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        unstable = 4.9 * (1.0 - 6.1 * np.minimum(zeta, 0.0)) ** (-2.0 / 3.0)
        stable = 4.9 * (1.0 + 2.2 * np.maximum(zeta, 0.0) ** (2.0 / 3.0))
    return np.where(zeta < 0, unstable, stable)


def kinematic_heat_flux(
    sensible_heat_flux: np.ndarray,
    p_hpa: np.ndarray,
    t_k: np.ndarray,
    positive_downward: bool = True,
) -> np.ndarray:
    """w′θ′ (K m s⁻¹, positive upward) from a sensible heat flux H (W m⁻²).

    ECMWF fluxes are positive downward, so an upward (daytime) flux is negative H
    and w′θ′ = −H/(ρ c_p). The sign must be checked on real data (RESEARCH §4.7).
    """
    rho = np.asarray(p_hpa, dtype=np.float64) * 100.0 / (R_DRY * np.asarray(t_k, dtype=np.float64))
    sign = -1.0 if positive_downward else 1.0
    return sign * np.asarray(sensible_heat_flux, dtype=np.float64) / (rho * CP_DRY)


def w71_cn2(
    z: np.ndarray,
    p_hpa: np.ndarray,
    t_k: np.ndarray,
    wtheta: np.ndarray,
    ustar: np.ndarray,
    bowen: np.ndarray | None = None,
    a: float = TATARSKII_A,
    kappa: float = VON_KARMAN,
    g: float = G0,
) -> np.ndarray:
    """Cₙ² (m^(−2/3)) at height ``z`` above ground (m) from surface-layer similarity.

    ``bowen=None`` omits the humidity correction (1 + 0.03/β)², i.e. β → ∞.
    """
    z = np.asarray(z, dtype=np.float64)
    t = np.asarray(t_k, dtype=np.float64)
    wt = np.asarray(wtheta, dtype=np.float64)
    us = np.asarray(ustar, dtype=np.float64)
    theta_star = -wt / us
    with np.errstate(divide="ignore", invalid="ignore"):
        obukhov = -(us**3) * t / (kappa * g * wt)
        zeta = np.where(wt == 0, 0.0, z / obukhov)
    ct2 = theta_star**2 * z ** (-2.0 / 3.0) * w71_g(zeta)
    humid = 1.0 if bowen is None else (1.0 + 0.03 / np.asarray(bowen, dtype=np.float64)) ** 2
    return (a * np.asarray(p_hpa, dtype=np.float64) / t**2) ** 2 * humid * ct2
