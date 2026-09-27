"""From Cₙ² integrals to optical parameters (docs/RESEARCH.md §4.5).

    r₀   = [0.423 k² sec ζ · J]^(−3/5),     k = 2π/λ
    ε    = c · λ / r₀                        (c = 0.98 for our product)
         = C · λ^(−1/5) (sec ζ)^(3/5) J^(3/5),  C = c · 0.423^(3/5) (2π)^(6/5) ≈ 5.307
    ε_B  = 5.25 · λ^(−1/5) · J^(3/5)          (as printed by Bi et al.; zenith)
    θ₀   = [2.914 k² (sec ζ)^(8/3) ∫Cₙ² h^(5/3) dh]^(−3/5)
    τ₀   = 0.314 · r₀ / V₀                   (zenith; r₀ along the line of sight)
    V₀   = [∫Cₙ² |V|^(5/3) dh / ∫Cₙ² dh]^(3/5)

Angles returned in arcseconds unless the name says radians. J in m^(1/3).
"""

from __future__ import annotations

import math

import numpy as np

from astroseeing.constants import (
    ARCSEC_PER_RAD,
    LAMBDA_REF,
    SEEING_COEFF,
    SeeingConvention,
)


def _k(wavelength: float) -> float:
    return 2.0 * math.pi / wavelength


def _sec(zenith_deg: float) -> float:
    return 1.0 / math.cos(math.radians(zenith_deg))


def fried_r0(J: np.ndarray, wavelength: float = LAMBDA_REF, zenith_deg: float = 0.0) -> np.ndarray:
    """Fried parameter r₀ (m) for integrated turbulence J (m^(1/3))."""
    J = np.asarray(J, dtype=np.float64)
    with np.errstate(divide="ignore"):
        return (0.423 * _k(wavelength) ** 2 * _sec(zenith_deg) * J) ** (-0.6)


def seeing_from_r0_rad(r0: np.ndarray, wavelength: float = LAMBDA_REF, coeff: float = SEEING_COEFF):
    """ε = coeff · λ / r₀, radians."""
    return coeff * wavelength / np.asarray(r0, dtype=np.float64)


def seeing_arcsec(
    J: np.ndarray,
    wavelength: float = LAMBDA_REF,
    zenith_deg: float = 0.0,
    coeff: float = SEEING_COEFF,
) -> np.ndarray:
    """Seeing FWHM (arcsec) from J, using ε = coeff·λ/r₀ (our product: coeff 0.98, 500 nm)."""
    J = np.asarray(J, dtype=np.float64)
    c_j = coeff * 0.423**0.6 * (2.0 * math.pi) ** 1.2
    return c_j * wavelength ** (-0.2) * _sec(zenith_deg) ** 0.6 * J**0.6 * ARCSEC_PER_RAD


def seeing_arcsec_bi(J: np.ndarray, wavelength: float = 550e-9, coeff: float = 5.25) -> np.ndarray:
    """Bi et al. 2023 form: ε = 5.25 λ^(−1/5) J^(3/5) (zenith), arcsec."""
    J = np.asarray(J, dtype=np.float64)
    return coeff * wavelength ** (-0.2) * J**0.6 * ARCSEC_PER_RAD


def seeing_with_convention(J: np.ndarray, conv: SeeingConvention) -> np.ndarray:
    """Seeing (arcsec, zenith) using a paper's own convention (see constants.SEEING_CONVENTIONS)."""
    if conv.form == "fwhm":
        return seeing_arcsec(J, conv.wavelength, 0.0, conv.coeff)
    if conv.form == "bi":
        return seeing_arcsec_bi(J, conv.wavelength, conv.coeff)
    raise ValueError(f"unknown seeing form {conv.form!r}")


def j_from_seeing(
    eps_arcsec: np.ndarray,
    wavelength: float = LAMBDA_REF,
    zenith_deg: float = 0.0,
    coeff: float = SEEING_COEFF,
) -> np.ndarray:
    """Inverse of :func:`seeing_arcsec`: J (m^(1/3)) giving seeing ``eps_arcsec``."""
    eps = np.asarray(eps_arcsec, dtype=np.float64) / ARCSEC_PER_RAD
    c_j = coeff * 0.423**0.6 * (2.0 * math.pi) ** 1.2
    return (eps / (c_j * wavelength ** (-0.2) * _sec(zenith_deg) ** 0.6)) ** (5.0 / 3.0)


def j_from_seeing_bi(eps_arcsec: np.ndarray, wavelength: float = 550e-9, coeff: float = 5.25):
    """Inverse of :func:`seeing_arcsec_bi`."""
    eps = np.asarray(eps_arcsec, dtype=np.float64) / ARCSEC_PER_RAD
    return (eps / (coeff * wavelength ** (-0.2))) ** (5.0 / 3.0)


def scale_seeing_wavelength(eps: np.ndarray, from_wavelength: float, to_wavelength: float):
    """ε ∝ λ^(−1/5): convert seeing between wavelengths (same J)."""
    return np.asarray(eps, dtype=np.float64) * (to_wavelength / from_wavelength) ** (-0.2)


def combine_seeing(*eps: np.ndarray) -> np.ndarray:
    """ε_tot = (Σ εᵢ^(5/3))^(3/5); equivalent to adding the J's (Hickson et al. 2013 eq. 6)."""
    total = sum(np.asarray(e, dtype=np.float64) ** (5.0 / 3.0) for e in eps)
    return np.asarray(total) ** 0.6


def isoplanatic_angle_arcsec(
    moment_53: np.ndarray, wavelength: float = LAMBDA_REF, zenith_deg: float = 0.0
) -> np.ndarray:
    """θ₀ (arcsec) from ∫Cₙ² h^(5/3) dh (h = height above the observer)."""
    m = np.asarray(moment_53, dtype=np.float64)
    with np.errstate(divide="ignore"):
        val = (2.914 * _k(wavelength) ** 2 * _sec(zenith_deg) ** (8.0 / 3.0) * m) ** (-0.6)
    return val * ARCSEC_PER_RAD


def v0_from_integrals(sum_cn2_v53: np.ndarray, J: np.ndarray) -> np.ndarray:
    """V₀ = [∫Cₙ²|V|^(5/3) dh / ∫Cₙ² dh]^(3/5), m s⁻¹ (NaN where J = 0)."""
    J = np.asarray(J, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (np.asarray(sum_cn2_v53, dtype=np.float64) / J) ** 0.6


def coherence_time_s(r0: np.ndarray, v0: np.ndarray) -> np.ndarray:
    """τ₀ = 0.314 r₀ / V₀ (s), with r₀ and V₀ for the same line of sight."""
    return 0.314 * np.asarray(r0, dtype=np.float64) / np.asarray(v0, dtype=np.float64)
