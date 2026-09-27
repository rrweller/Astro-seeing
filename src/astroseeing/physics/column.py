"""Prepare atmospheric columns for the Cₙ² models (docs/RESEARCH.md §4.3).

Conventions
-----------
* The level axis is the **last** axis of every array.
* Levels are ordered **bottom → top** (height increasing, pressure decreasing).
  For ERA5 pressure levels that is 1000 → 50 hPa.
* Heights are geopotential heights in metres above mean sea level: Z = Φ / g₀.
* Pressure is in hPa (the unit the Tatarskii and Osborn–Sarazin formulas expect).

Work is done on *slabs* between neighbouring valid levels. Within a slab, Cₙ² is
constant; temperature is taken at the slab midpoint as the mean of the two levels,
pressure as the log-pressure midpoint √(p₁p₂), and gradients by finite difference.
The slab's potential temperature is θ_mid = T_mid (P₀/P_mid)^κ.

``state_at="lower"`` instead takes T, P and θ at the slab's lower level, as
Haslebacher et al. 2022 do ("Euler forward"; their code evaluates the formula at
level i and differences to level i+1). The fields keep their ``*_mid`` names;
``Slabs.state_at`` records which was used.

Levels that are below ground (p > surface pressure, or Z ≤ surface height) hold
extrapolated values in ERA5 and are masked; the count is recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from astroseeing.constants import G0, KAPPA, P0_HPA
from astroseeing.qc import QCCounts


def geopotential_to_height(phi: np.ndarray) -> np.ndarray:
    """Geopotential (m² s⁻²) → geopotential height (m): Z = Φ / g₀."""
    return np.asarray(phi, dtype=np.float64) / G0


def potential_temperature(
    t_k: np.ndarray, p_hpa: np.ndarray, kappa: float = KAPPA, p0_hpa: float = P0_HPA
) -> np.ndarray:
    """θ = T (P₀/P)^κ with P in hPa."""
    return (
        np.asarray(t_k, dtype=np.float64) * (p0_hpa / np.asarray(p_hpa, dtype=np.float64)) ** kappa
    )


def dtheta_dz_from_dtdz(
    t_k: np.ndarray,
    p_hpa: np.ndarray,
    dtdz: np.ndarray,
    gamma: float,
    kappa: float = KAPPA,
    p0_hpa: float = P0_HPA,
) -> np.ndarray:
    """∂θ/∂z = (θ/T)(∂T/∂z + g/c_p) for a hydrostatic atmosphere (point form)."""
    theta = potential_temperature(t_k, p_hpa, kappa, p0_hpa)
    return theta / np.asarray(t_k, dtype=np.float64) * (np.asarray(dtdz) + gamma)


@dataclass
class Slabs:
    """Slab (layer) quantities between neighbouring levels. Shape (..., nlev-1)."""

    z_bot: np.ndarray  # m
    z_top: np.ndarray  # m
    p_mid: np.ndarray  # hPa
    t_mid: np.ndarray  # K
    theta_mid: np.ndarray  # K
    dtdz: np.ndarray  # K m^-1
    dthetadz: np.ndarray  # K m^-1
    dudz: np.ndarray  # s^-1
    dvdz: np.ndarray  # s^-1
    u_mid: np.ndarray  # m s^-1
    v_mid: np.ndarray  # m s^-1
    valid: np.ndarray  # bool: both bounding levels valid
    level_valid: np.ndarray  # bool, shape (..., nlev)
    qc: QCCounts = field(default_factory=QCCounts)
    state_at: str = "mid"  # where p_mid, t_mid, theta_mid were taken: "mid" or "lower"

    @property
    def dz(self) -> np.ndarray:
        return self.z_top - self.z_bot

    @property
    def shear2(self) -> np.ndarray:
        """S² = (∂u/∂z)² + (∂v/∂z)², s⁻²."""
        return self.dudz**2 + self.dvdz**2

    @property
    def shear(self) -> np.ndarray:
        """S, s⁻¹."""
        return np.sqrt(self.shear2)

    @property
    def n2(self) -> np.ndarray:
        """N² = (g/θ) ∂θ/∂z, s⁻²."""
        return G0 / self.theta_mid * self.dthetadz

    @property
    def wind_speed_mid(self) -> np.ndarray:
        return np.hypot(self.u_mid, self.v_mid)


def level_validity(
    z_m: np.ndarray,
    p_hpa: np.ndarray,
    *,
    data: tuple[np.ndarray, ...] = (),
    surface_pressure_hpa: np.ndarray | None = None,
    surface_height_m: np.ndarray | None = None,
    qc: QCCounts | None = None,
) -> np.ndarray:
    """Boolean mask of levels that are above ground and have finite data.

    ``surface_pressure_hpa`` and ``surface_height_m`` have the column shape
    (no level axis). Counts go into ``qc`` under ``level_below_surface_pressure``,
    ``level_below_orography`` and ``level_nonfinite``.
    """
    qc = qc if qc is not None else QCCounts()
    z_m = np.asarray(z_m, dtype=np.float64)
    p = np.broadcast_to(np.asarray(p_hpa, dtype=np.float64), z_m.shape)
    valid = np.isfinite(z_m) & np.isfinite(p)
    for a in data:
        valid &= np.isfinite(np.broadcast_to(a, z_m.shape))
    qc.add("level_nonfinite", int((~valid).sum()), valid.size)
    if surface_pressure_hpa is not None:
        below = p > np.asarray(surface_pressure_hpa, dtype=np.float64)[..., None]
        qc.add("level_below_surface_pressure", int((below & valid).sum()), valid.size)
        valid &= ~below
    if surface_height_m is not None:
        below = z_m <= np.asarray(surface_height_m, dtype=np.float64)[..., None]
        qc.add("level_below_orography", int((below & valid).sum()), valid.size)
        valid &= ~below
    return valid


def prepare_slabs(
    z_m: np.ndarray,
    t_k: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    p_hpa: np.ndarray,
    surface_pressure_hpa: np.ndarray | None = None,
    surface_height_m: np.ndarray | None = None,
    kappa: float = KAPPA,
    p0_hpa: float = P0_HPA,
    state_at: str = "mid",
) -> Slabs:
    """Build slabs between neighbouring levels of each column.

    Parameters
    ----------
    z_m, t_k, u, v
        Geopotential height (m), temperature (K) and wind components (m/s), shape
        (..., nlev), levels bottom → top.
    p_hpa
        Pressure of each level in hPa: shape (nlev,) for pressure levels or
        (..., nlev) for model levels.
    surface_pressure_hpa, surface_height_m
        Optional, shape (...): used to mask underground levels.
    state_at
        ``"mid"`` (default): T, P, θ at the slab midpoint (decision D3).
        ``"lower"``: at the slab's lower level (Haslebacher et al. 2022).

    Returns
    -------
    Slabs
        A slab is valid only if both of its bounding levels are valid. Heights must
        strictly increase across each valid slab; otherwise ``ValueError`` is raised
        (bad input is never silently repaired).
    """
    z = np.asarray(z_m, dtype=np.float64)
    t = np.asarray(t_k, dtype=np.float64)
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    p = np.broadcast_to(np.asarray(p_hpa, dtype=np.float64), z.shape)
    if not (z.shape == t.shape == u.shape == v.shape):
        raise ValueError(f"shape mismatch: z{z.shape} t{t.shape} u{u.shape} v{v.shape}")
    if z.shape[-1] < 2:
        raise ValueError("need at least two levels")

    qc = QCCounts()
    lv = level_validity(
        z,
        p,
        data=(t, u, v),
        surface_pressure_hpa=surface_pressure_hpa,
        surface_height_m=surface_height_m,
        qc=qc,
    )
    valid = lv[..., :-1] & lv[..., 1:]

    z_bot, z_top = z[..., :-1], z[..., 1:]
    dz = z_top - z_bot
    bad = valid & ~(dz > 0)
    if bad.any():
        raise ValueError(f"{int(bad.sum())} valid slabs do not increase in height (dz <= 0)")
    # Use a safe dz for invalid slabs so no warnings or infinities are produced there.
    dz_safe = np.where(valid, dz, 1.0)

    theta = potential_temperature(t, p, kappa, p0_hpa)
    if state_at == "mid":
        t_mid = 0.5 * (t[..., :-1] + t[..., 1:])
        p_mid = np.sqrt(p[..., :-1] * p[..., 1:])
        theta_mid = potential_temperature(t_mid, p_mid, kappa, p0_hpa)
    elif state_at == "lower":
        t_mid, p_mid, theta_mid = t[..., :-1], p[..., :-1], theta[..., :-1]
    else:
        raise ValueError(f"state_at must be 'mid' or 'lower', got {state_at!r}")

    def grad(x: np.ndarray) -> np.ndarray:
        return np.where(valid, (x[..., 1:] - x[..., :-1]) / dz_safe, np.nan)

    qc.add("slab_invalid", int((~valid).sum()), valid.size)
    return Slabs(
        z_bot=z_bot,
        z_top=z_top,
        p_mid=np.where(valid, p_mid, np.nan),
        t_mid=np.where(valid, t_mid, np.nan),
        theta_mid=np.where(valid, theta_mid, np.nan),
        dtdz=grad(t),
        dthetadz=grad(theta),
        dudz=grad(u),
        dvdz=grad(v),
        u_mid=np.where(valid, 0.5 * (u[..., :-1] + u[..., 1:]), np.nan),
        v_mid=np.where(valid, 0.5 * (v[..., :-1] + v[..., 1:]), np.nan),
        valid=valid,
        level_valid=lv,
        qc=qc,
        state_at=state_at,
    )


def richardson_number(n2: np.ndarray, shear2: np.ndarray) -> np.ndarray:
    """Gradient Richardson number Ri = N² / S² (inf where S² = 0 and N² > 0)."""
    n2 = np.asarray(n2, dtype=np.float64)
    shear2 = np.asarray(shear2, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return n2 / shear2
