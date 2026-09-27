"""Cₙ² models (docs/RESEARCH.md §4.4).

Two recipes, the same physics with different constants:

* Tatarskii + HMNSP99 outer scale (Bi et al. 2023; Priyatikanto et al. 2026)::

      Cₙ² = 2.8 · M² · L0^(4/3)
      M   = A · (P/T²) · (∂T/∂z + γ)                   (Bi et al. form)
      L0^(4/3) = 0.1^(4/3) · 10^(a1 + a2·S + a3·∂T/∂z)

  Priyatikanto et al. print M = −7.9×10⁻⁵ (P/T²) ∂θ/∂h instead (their eq. 6);
  :func:`tatarskii_m_theta` reproduces that form.

* Osborn & Sarazin 2018 (their eq. 7)::

      Cₙ² = k · [A · P/(T·θ)]² · L^(4/3) · (∂θ/∂z)²,   L = √(2E / ((g/θ) ∂θ/∂z)),  E = S²

Pressure is in hPa, temperature in K, heights in m, S in s⁻¹.
"""

from __future__ import annotations

import numpy as np

from astroseeing.constants import (
    BI_GAMMA,
    G0,
    HMNSP99_STRATOSPHERE,
    HMNSP99_TROPOSPHERE,
    OS_A,
    OS_K,
    TATARSKII_A,
    Hmnsp99Coefficients,
)
from astroseeing.qc import QCCounts

_L0_PREFACTOR = 0.1 ** (4.0 / 3.0)


def hmnsp99_l0_43(
    shear: np.ndarray,
    dtdz: np.ndarray,
    stratosphere: np.ndarray | bool = False,
    troposphere_coeffs: Hmnsp99Coefficients = HMNSP99_TROPOSPHERE,
    stratosphere_coeffs: Hmnsp99Coefficients = HMNSP99_STRATOSPHERE,
) -> np.ndarray:
    """HMNSP99 outer scale L0^(4/3) (m^(4/3)).

    Parameters
    ----------
    shear
        Vertical wind shear S, s⁻¹.
    dtdz
        ∂T/∂z, K m⁻¹.
    stratosphere
        Boolean (broadcastable): True where the stratosphere coefficients apply.
    """
    shear = np.asarray(shear, dtype=np.float64)
    dtdz = np.asarray(dtdz, dtype=np.float64)
    tr, st = troposphere_coeffs, stratosphere_coeffs
    exp_tr = tr.a1 + tr.a2 * shear + tr.a3 * dtdz
    exp_st = st.a1 + st.a2 * shear + st.a3 * dtdz
    exponent = np.where(stratosphere, exp_st, exp_tr)
    return _L0_PREFACTOR * 10.0**exponent


def hmnsp99_exponent(shear: float, dtdz: float, coeffs: Hmnsp99Coefficients) -> float:
    """The log10 exponent a1 + a2·S + a3·∂T/∂z (for tests and diagnostics)."""
    return coeffs.a1 + coeffs.a2 * shear + coeffs.a3 * dtdz


def tatarskii_m(
    p_hpa: np.ndarray,
    t_k: np.ndarray,
    dtdz: np.ndarray,
    gamma: float = BI_GAMMA,
    a: float = TATARSKII_A,
) -> np.ndarray:
    """Refractive-index gradient M = A (P/T²)(∂T/∂z + γ) (Bi et al. form), m⁻¹."""
    p = np.asarray(p_hpa, dtype=np.float64)
    t = np.asarray(t_k, dtype=np.float64)
    return a * p / t**2 * (np.asarray(dtdz, dtype=np.float64) + gamma)


def tatarskii_m_theta(
    p_hpa: np.ndarray, t_k: np.ndarray, dthetadz: np.ndarray, a: float = TATARSKII_A
) -> np.ndarray:
    """M = −A (P/T²) ∂θ/∂z (the form printed by Priyatikanto et al., eq. 6), m⁻¹.

    Note this differs from :func:`tatarskii_m` by a factor θ/T, because
    ∂θ/∂z = (θ/T)(∂T/∂z + g/c_p).
    """
    p = np.asarray(p_hpa, dtype=np.float64)
    t = np.asarray(t_k, dtype=np.float64)
    return -a * p / t**2 * np.asarray(dthetadz, dtype=np.float64)


def tatarskii_cn2(m: np.ndarray, l0_43: np.ndarray) -> np.ndarray:
    """Cₙ² = 2.8 · M² · L0^(4/3), m^(−2/3)."""
    return 2.8 * np.asarray(m, dtype=np.float64) ** 2 * np.asarray(l0_43, dtype=np.float64)


def osborn_sarazin_outer_scale(
    shear2: np.ndarray, theta_k: np.ndarray, dthetadz: np.ndarray, g: float = G0
) -> np.ndarray:
    """L = √(2 S² / N²) with N² = (g/θ) ∂θ/∂z (O&S eq. 5 with E = S²).

    Returns NaN where N² ≤ 0 (L is undefined for neutral or unstable layers).
    """
    n2 = g / np.asarray(theta_k, dtype=np.float64) * np.asarray(dthetadz, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(n2 > 0, np.sqrt(2.0 * np.asarray(shear2) / n2), np.nan)


#: Rules for layers where N² ≤ 0 and the O&S outer scale L is undefined.
#: "zero": Cₙ² = 0 (continuous with the N² → 0⁺ limit, where Cₙ² → 0).
#: "abs":  use |∂θ/∂z| (also continuous; treats unstable layers as turbulent).
#: "nan":  propagate NaN (for inspection only).
UNSTABLE_RULES = ("zero", "abs", "nan")


def osborn_sarazin_cn2(
    p_hpa: np.ndarray,
    t_k: np.ndarray,
    theta_k: np.ndarray,
    dthetadz: np.ndarray,
    shear2: np.ndarray,
    k: float = OS_K,
    a: float = OS_A,
    g: float = G0,
    unstable: str = "zero",
    qc: QCCounts | None = None,
) -> np.ndarray:
    """Osborn & Sarazin 2018 eq. 7, m^(−2/3).

    Evaluated in the algebraically equivalent, numerically stable form
    Cₙ² = k [A P/(Tθ)]² (2θ/g)^(2/3) S^(4/3) |∂θ/∂z|^(4/3), which equals eq. 7 for
    N² > 0. ``unstable`` chooses the rule for N² ≤ 0 (see :data:`UNSTABLE_RULES`);
    the number of such layers is recorded in ``qc`` as ``os_unstable_layers``.
    """
    if unstable not in UNSTABLE_RULES:
        raise ValueError(f"unstable must be one of {UNSTABLE_RULES}, got {unstable!r}")
    p = np.asarray(p_hpa, dtype=np.float64)
    t = np.asarray(t_k, dtype=np.float64)
    theta = np.asarray(theta_k, dtype=np.float64)
    dth = np.asarray(dthetadz, dtype=np.float64)
    s2 = np.asarray(shear2, dtype=np.float64)

    finite = np.isfinite(dth) & np.isfinite(theta)
    unstable_mask = finite & (dth <= 0)
    if qc is not None:
        qc.add("os_unstable_layers", int(unstable_mask.sum()), int(finite.sum()))

    base = k * (a * p / (t * theta)) ** 2 * (2.0 * theta / g) ** (2.0 / 3.0)
    cn2 = base * s2 ** (2.0 / 3.0) * np.abs(dth) ** (4.0 / 3.0)
    if unstable == "zero":
        cn2 = np.where(unstable_mask, 0.0, cn2)
    elif unstable == "nan":
        cn2 = np.where(unstable_mask, np.nan, cn2)
    return cn2


def osborn_sarazin_cn2_literal(
    p_hpa: float,
    t_k: float,
    theta_k: float,
    dthetadz: float,
    shear2: float,
    k: float = OS_K,
    a: float = OS_A,
    g: float = G0,
) -> float:
    """O&S eq. 7 written literally (scalar, N² > 0 only). Used to test the stable form."""
    big_l = float(osborn_sarazin_outer_scale(shear2, theta_k, dthetadz, g))
    return k * (a * p_hpa / (t_k * theta_k)) ** 2 * big_l ** (4.0 / 3.0) * dthetadz**2
