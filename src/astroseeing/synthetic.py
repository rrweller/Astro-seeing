"""Synthetic atmospheres for tests and dry runs (never used for products).

The temperature/pressure structure is the U.S. Standard Atmosphere 1976 up to
32 km (geopotential height): 6.5 K/km lapse to 11 km, isothermal 216.65 K to
20 km, then +1 K/km. Winds are an idealised jet so shear is non-zero.
"""

from __future__ import annotations

import numpy as np

from astroseeing.constants import G0

# U.S. Standard Atmosphere 1976 base layers: (base height m, base T K, lapse K/m, base p hPa)
_R_STD = 287.053  # J/(kg K) implied by R*/M of the 1976 standard
_LAYERS = (
    (0.0, 288.15, -0.0065, 1013.25),
    (11000.0, 216.65, 0.0, 226.3206),
    (20000.0, 216.65, 0.001, 54.74889),
)

#: The 29 ERA5 pressure levels used by the project (docs/RESEARCH.md §7), hPa, bottom → top.
# fmt: off
ERA5_LEVELS_HPA = np.array(
    [1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 650, 600, 550,
     500, 450, 400, 350, 300, 250, 225, 200, 175, 150, 125, 100, 70, 50],
    dtype=np.float64,
)
# fmt: on


def std_atmosphere_height(p_hpa: np.ndarray) -> np.ndarray:
    """Geopotential height (m) of pressure ``p_hpa`` in the 1976 standard atmosphere."""
    p = np.asarray(p_hpa, dtype=np.float64)
    out = np.full(p.shape, np.nan)
    for i, (hb, tb, lapse, pb) in enumerate(_LAYERS):
        p_top = _LAYERS[i + 1][3] if i + 1 < len(_LAYERS) else 0.0
        sel = (p <= pb) & (p > p_top)
        if lapse == 0.0:
            out[sel] = hb - _R_STD * tb / G0 * np.log(p[sel] / pb)
        else:
            out[sel] = hb + tb / lapse * ((p[sel] / pb) ** (-_R_STD * lapse / G0) - 1.0)
    return out


def std_atmosphere_temperature(z_m: np.ndarray) -> np.ndarray:
    """Temperature (K) at geopotential height ``z_m`` (valid 0–32 km; extrapolated below 0)."""
    z = np.asarray(z_m, dtype=np.float64)
    out = np.empty(z.shape)
    for i, (hb, tb, lapse, _) in enumerate(_LAYERS):
        h_top = _LAYERS[i + 1][0] if i + 1 < len(_LAYERS) else np.inf
        sel = (z < h_top) if i == 0 else ((z >= hb) & (z < h_top))
        out[sel] = tb + lapse * (z[sel] - hb)
    return out


def jet_wind(z_m: np.ndarray, u_max: float = 30.0, z_jet: float = 11500.0, width: float = 4000.0):
    """Idealised (u, v) wind profile with a Gaussian jet at ``z_jet``, m/s."""
    z = np.asarray(z_m, dtype=np.float64)
    u = 3.0 + u_max * np.exp(-(((z - z_jet) / width) ** 2))
    v = 2.0 * np.sin(z / 3000.0)
    return u, v


def std_column(p_levels_hpa: np.ndarray = ERA5_LEVELS_HPA, u_max: float = 30.0):
    """(z, t, u, v) on the given pressure levels (bottom → top) for one column."""
    z = std_atmosphere_height(p_levels_hpa)
    t = std_atmosphere_temperature(z)
    u, v = jet_wind(z, u_max=u_max)
    return z, t, u, v
