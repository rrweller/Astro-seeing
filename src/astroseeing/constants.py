"""Physical constants and paper-specific constant sets.

Everything is SI unless the name says otherwise. Formulas that expect other units
(Tatarskii and Osborn–Sarazin take pressure in hPa) say so in their docstrings.

Sources are cited per constant. Items marked [check] are not yet confirmed
against a primary source and are tracked in ``docs/decisions.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --- Basic physics -------------------------------------------------------------

#: Standard gravity, m s^-2 (used to turn ERA5 geopotential into geopotential height).
G0 = 9.80665

#: Gas constant of dry air, J kg^-1 K^-1 (value used in ECMWF's model-level recipe,
#: docs/RESEARCH.md §4.3).
R_DRY = 287.06

#: Specific heat of dry air at constant pressure, J kg^-1 K^-1, taken as 3.5 R_d
#: (the IFS convention) [check]. Only enters through g/c_p ≈ 9.76e-3 K m^-1.
CP_DRY = 3.5 * R_DRY

#: Dry adiabatic lapse rate g/c_p, K m^-1 (≈ 9.76e-3).
GAMMA_DRY = G0 / CP_DRY

#: R/c_p used for potential temperature by Osborn & Sarazin 2018 (eq. 3),
#: Haslebacher et al. 2022 (eq. 16) and Priyatikanto et al. 2026 (eq. 7).
KAPPA = 0.286

#: Reference pressure for potential temperature, hPa.
P0_HPA = 1000.0

#: von Kármán constant (W71 ground-layer option, docs/RESEARCH.md §4.7).
VON_KARMAN = 0.4

#: Radians to arcseconds.
ARCSEC_PER_RAD = 180.0 * 3600.0 / math.pi

#: Our product's reference wavelength, m (AGENTS.md "Seeing convention").
LAMBDA_REF = 500e-9

#: FWHM coefficient in ε = c λ / r0. 0.98 is the value used for our product
#: (docs/RESEARCH.md §4.5, "exact (5.307) form").
SEEING_COEFF = 0.98

#: Coefficient of the ε = C λ^(-1/5) J^(3/5) form exactly equivalent to
#: ε = 0.98 λ / r0 with r0 = (0.423 k² J)^(-3/5): C = 0.98 · 0.423^(3/5) · (2π)^(6/5).
SEEING_J_COEFF_EXACT = SEEING_COEFF * 0.423**0.6 * (2.0 * math.pi) ** 1.2

# --- Tatarskii + HMNSP99 (Bi et al. 2023; Priyatikanto et al. 2026) ------------


@dataclass(frozen=True)
class Hmnsp99Coefficients:
    """log10 outer-scale model: L0^(4/3) = 0.1^(4/3) · 10^(a1 + a2·S + a3·dT/dz).

    Written with ``+ a3·dT/dz`` so that a paper's printed sign convention can be
    reproduced by flipping the sign of ``a3``. With the usual HMNSP99 form
    (docs/RESEARCH.md §4.4) a3 is negative: a3 = −192.347 (troposphere) and
    −57.784 (stratosphere).
    """

    a1: float
    a2: float
    a3: float


#: HMNSP99 troposphere, as in docs/RESEARCH.md §4.4 (Bi et al. 2023).
HMNSP99_TROPOSPHERE = Hmnsp99Coefficients(0.362, 16.728, -192.347)
#: HMNSP99 stratosphere, as in docs/RESEARCH.md §4.4 (Bi et al. 2023).
HMNSP99_STRATOSPHERE = Hmnsp99Coefficients(0.757, 13.819, -57.784)

#: Tatarskii constant for the refractive-index gradient, K hPa^-1 (Bi et al.).
TATARSKII_A = 79e-6
#: Lapse-rate constant printed (after the 9.8×10³ typo fix) by Bi et al., K m^-1.
BI_GAMMA = 9.8e-3

# --- Osborn & Sarazin 2018 ------------------------------------------------------

#: Gladstone constant in O&S eq. 7, K hPa^-1.
OS_A = 80e-6
#: Global calibration constant fitted at Paranal (O&S §4).
OS_K = 6.0
#: Height above ground separating ground layer and free atmosphere in O&S (§5.7,
#: Fig. 9: "free atmosphere seeing (h>1 km)", "ground layer seeing (h<1 km)"), m.
OS_SPLIT_HEIGHT = 1000.0


# --- Paper presets for reproductions --------------------------------------------


@dataclass(frozen=True)
class SeeingConvention:
    """How a paper turns J into seeing."""

    name: str
    wavelength: float  # m
    form: str  # "fwhm" (ε = coeff·λ/r0) or "bi" (ε = coeff·λ^(-1/5)·J^(3/5))
    coeff: float
    note: str = ""


#: Our product: 500 nm, zenith, ε = 0.98 λ/r0.
OURS = SeeingConvention("ours", 500e-9, "fwhm", 0.98)
#: Bi et al. 2023: ε = 5.25 λ^(-1/5) J^(3/5) with λ = 550 nm (docs/RESEARCH.md §3.1).
BI2023 = SeeingConvention(
    "bi2023", 550e-9, "bi", 5.25, note="PDF not yet checked from this container [check]"
)
#: Haslebacher et al. 2022 eq. 6: ε = 0.976 λ/r0, λ = 500 nm (checked in arXiv:2208.04918).
HASLEBACHER2022 = SeeingConvention("haslebacher2022", 500e-9, "fwhm", 0.976)
#: Priyatikanto et al. 2026 eq. 1: ε = 0.98 λ/r0; λ given only as "e.g. 500 nm" [check].
PRIYATIKANTO2026 = SeeingConvention(
    "priyatikanto2026", 500e-9, "fwhm", 0.98, note="wavelength not stated exactly [check]"
)
#: Osborn & Sarazin 2018 do not print their r0→ε conversion; 0.98 λ/r0 at 500 nm is
#: our assumption [check].
OSBORN_SARAZIN2018 = SeeingConvention(
    "osborn_sarazin2018", 500e-9, "fwhm", 0.98, note="conversion not printed in paper [check]"
)

SEEING_CONVENTIONS = {
    c.name: c for c in (OURS, BI2023, HASLEBACHER2022, PRIYATIKANTO2026, OSBORN_SARAZIN2018)
}
