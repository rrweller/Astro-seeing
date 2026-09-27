"""Known-answer tests: docs/RESEARCH.md §4.9 (λ = 500 nm, zenith unless noted).

Each expected value is checked to half a unit in the last digit printed in §4.9,
i.e. the test fails if our value would not round to the printed number.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from astroseeing import constants as K
from astroseeing.physics import cn2 as C
from astroseeing.physics import column, optics


def printed(expected: str) -> tuple[float, float]:
    """Value and half-unit tolerance of a number as printed ("0.3158" → 5e-5)."""
    mant = expected.lower().split("e")[0]
    decimals = len(mant.split(".")[1]) if "." in mant else 0
    exp = int(expected.lower().split("e")[1]) if "e" in expected.lower() else 0
    return float(expected), 0.5 * 10.0 ** (exp - decimals) * (1 + 1e-9)


def assert_printed(value: float, expected: str) -> None:
    exp_val, tol = printed(expected)
    assert abs(float(value) - exp_val) <= tol, f"{value!r} does not round to {expected}"


@pytest.mark.parametrize(
    ("J", "exact", "bi"),
    [
        (1e-13, "0.3158", "0.3125"),
        (3e-13, "0.6106", "0.6040"),
        (1e-12, "1.2574", "1.2439"),
    ],
)
def test_seeing_from_J(J, exact, bi):
    assert_printed(optics.seeing_arcsec(J, 500e-9), exact)
    assert_printed(optics.seeing_arcsec_bi(J, 500e-9, 5.25), bi)


def test_J_giving_one_arcsec():
    assert_printed(optics.j_from_seeing(1.0, 500e-9), "6.83e-13")
    assert_printed(optics.j_from_seeing_bi(1.0, 500e-9), "6.95e-13")


def test_r0_for_one_arcsec():
    r0 = optics.fried_r0(optics.j_from_seeing(1.0))
    assert_printed(r0, "0.1011")
    # and directly from ε = 0.98 λ / r0
    assert_printed(0.98 * 500e-9 / (1.0 / K.ARCSEC_PER_RAD), "0.1011")


def test_exact_coefficient_is_5307():
    assert_printed(K.SEEING_J_COEFF_EXACT, "5.307")
    # the 5.25 form is 1.1% lower
    assert_printed(1 - 5.25 / K.SEEING_J_COEFF_EXACT, "0.011")


def test_wavelength_ratio():
    assert_printed(optics.scale_seeing_wavelength(1.0, 500e-9, 550e-9), "0.9811")


def test_isoplanatic_angle_single_layer():
    moment = 1e-13 * (10_000.0) ** (5.0 / 3.0)
    assert_printed(optics.isoplanatic_angle_arcsec(moment), "2.07")


def test_coherence_time():
    r0 = optics.fried_r0(3e-13)
    assert_printed(r0, "0.1655")
    assert_printed(optics.coherence_time_s(r0, 20.0) * 1e3, "2.60")


def test_hmnsp99_troposphere():
    e = C.hmnsp99_exponent(0.005, -0.0065, K.HMNSP99_TROPOSPHERE)
    assert_printed(e, "1.6959")
    l43 = float(C.hmnsp99_l0_43(0.005, -0.0065, stratosphere=False))
    assert_printed(l43, "2.3044")
    assert_printed(l43**0.75, "1.870")


def test_hmnsp99_stratosphere():
    l43 = float(C.hmnsp99_l0_43(0.005, 0.002, stratosphere=True))
    assert_printed(l43, "0.2383")
    assert_printed(l43**0.75, "0.341")


def test_tatarskii_cn2():
    m = C.tatarskii_m(500.0, 250.0, -0.0065, gamma=9.8e-3, a=79e-6)
    assert_printed(C.tatarskii_cn2(m, 2.3044), "2.807e-17")


def test_osborn_sarazin_chain():
    t, p, dtdz, s = 250.0, 500.0, -0.0065, 0.005
    theta = column.potential_temperature(t, p)
    dth = column.dtheta_dz_from_dtdz(t, p, dtdz, gamma=K.GAMMA_DRY)
    n2 = K.G0 / theta * dth
    assert_printed(n2, "1.279e-4")
    assert_printed(n2 / s**2, "5.12")
    assert_printed(C.osborn_sarazin_outer_scale(s**2, theta, dth), "0.625")
    assert_printed(C.osborn_sarazin_cn2(p, t, theta, dth, s**2, k=6.0), "1.397e-17")


def test_os_stable_form_equals_literal_eq7():
    rng = np.random.default_rng(1)
    for _ in range(200):
        p = rng.uniform(50, 1000)
        t = rng.uniform(190, 310)
        theta = float(column.potential_temperature(t, p))
        dth = rng.uniform(1e-5, 3e-2)
        s2 = rng.uniform(0, 1e-3)
        lit = C.osborn_sarazin_cn2_literal(p, t, theta, dth, s2)
        stable = float(C.osborn_sarazin_cn2(p, t, theta, dth, s2))
        assert stable == pytest.approx(lit, rel=1e-12, abs=1e-40)


def test_theta_form_equivalence_note():
    """RESEARCH §4.4: 79e-6 (P/T²)(∂T/∂z + g/c_p) = 79e-6 P/(Tθ) ∂θ/∂z exactly."""
    t, p, dtdz = 250.0, 500.0, -0.0065
    theta = column.potential_temperature(t, p)
    dth = column.dtheta_dz_from_dtdz(t, p, dtdz, gamma=K.GAMMA_DRY)
    lhs = 79e-6 * p / t**2 * (dtdz + K.GAMMA_DRY)
    rhs = 79e-6 * p / (t * theta) * dth
    assert lhs == pytest.approx(rhs, rel=1e-12)
    # ...whereas Priyatikanto's printed M = 79e-6 P/T² ∂θ/∂z differs by θ/T.
    m_prt = abs(float(C.tatarskii_m_theta(p, t, dth)))
    assert m_prt / lhs == pytest.approx(theta / t, rel=1e-12)


def test_dry_adiabatic_lapse_rate_value():
    # RESEARCH §4.4: γ = g/c_p ≈ 9.76e-3 K/m; Bi et al. use 9.8e-3.
    assert_printed(K.GAMMA_DRY, "9.76e-3")


def test_seeing_conventions_of_papers():
    # Haslebacher et al. 2022 eq. 6 uses 0.976 λ/r0 at 500 nm: 0.4% below 0.98.
    J = 3e-13
    ours = optics.seeing_with_convention(J, K.OURS)
    has = optics.seeing_with_convention(J, K.HASLEBACHER2022)
    assert has / ours == pytest.approx(0.976 / 0.98, rel=1e-12)
    bi = optics.seeing_with_convention(J, K.BI2023)
    assert bi == pytest.approx(5.25 * (550e-9) ** -0.2 * J**0.6 * K.ARCSEC_PER_RAD, rel=1e-12)
    assert math.isclose(float(optics.seeing_arcsec(J)), float(ours), rel_tol=1e-15)
