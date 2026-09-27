"""Property and structural tests for the physics module (docs/RESEARCH.md §4.9 list)."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp

from astroseeing import constants as K
from astroseeing.physics import cloud, cn2, column, groundlayer, integrate, modellevels, optics
from astroseeing.physics.profile import BI2023_MODEL, OS2018_MODEL, Cn2Model, compute_profile
from astroseeing.physics.tropopause import _wmo_tropopause_reference, wmo_tropopause_height
from astroseeing.qc import QCCounts
from astroseeing.synthetic import ERA5_LEVELS_HPA, std_atmosphere_height, std_column

# --- strategies ------------------------------------------------------------------


@st.composite
def slab_profiles(draw, max_slabs: int = 12):
    n = draw(st.integers(1, max_slabs))
    dz = draw(hnp.arrays(np.float64, n, elements=st.floats(1.0, 3000.0)))
    z0 = draw(st.floats(-500.0, 5000.0))
    edges = z0 + np.concatenate([[0.0], np.cumsum(dz)])
    c = draw(hnp.arrays(np.float64, n, elements=st.floats(0.0, 1e-15)))
    return edges[:-1], edges[1:], c


heights = hnp.arrays(np.float64, st.integers(1, 20), elements=st.floats(-1000.0, 40000.0))


# --- integrals -------------------------------------------------------------------


@given(slab_profiles(), heights)
def test_J_of_h_never_increases(prof, h):
    zb, zt, c = prof
    h = np.sort(h)
    j = integrate.integral_above(h, c, zb, zt)
    assert np.all(np.diff(j) <= 1e-30 + 1e-12 * np.abs(j[:-1]))
    assert np.all(j >= 0)


@given(slab_profiles(), st.floats(0.0, 1e-15), st.integers(0, 11))
def test_adding_turbulence_never_lowers_J(prof, extra, idx):
    zb, zt, c = prof
    j0 = integrate.column_integral(c, zb, zt)
    c2 = c.copy()
    c2[idx % c.size] += extra
    assert integrate.column_integral(c2, zb, zt) >= j0


@given(slab_profiles())
def test_integral_above_limits(prof):
    zb, zt, c = prof
    total = integrate.column_integral(c, zb, zt)
    ends = np.array([zb[0] - 100.0, zb[0], zt[-1], zt[-1] + 100.0])
    j = integrate.integral_above(ends, c, zb, zt)
    assert j[0] == pytest.approx(total, rel=1e-12, abs=1e-40)
    assert j[1] == pytest.approx(total, rel=1e-12, abs=1e-40)
    assert j[2] == 0.0 and j[3] == 0.0


def test_partial_slab_is_exact():
    zb, zt, c = np.array([0.0, 1000.0]), np.array([1000.0, 3000.0]), np.array([2e-16, 1e-16])
    j = integrate.integral_above(np.array([250.0, 2000.0]), c, zb, zt)
    assert j[0] == pytest.approx(2e-16 * 750 + 1e-16 * 2000)
    assert j[1] == pytest.approx(1e-16 * 1000)


def test_invalid_and_nan_slabs_contribute_nothing():
    zb = np.array([0.0, np.nan, 2000.0])
    zt = np.array([1000.0, np.nan, 3000.0])
    c = np.array([1e-16, np.nan, 1e-16])
    assert integrate.column_integral(c, zb, zt) == pytest.approx(2e-13)
    valid = np.array([True, False, False])
    assert integrate.column_integral(c, zb, zt, valid) == pytest.approx(1e-13)
    m = integrate.weighted_moment_above(np.array(0.0), c, zb, zt)
    assert np.isfinite(m)


def test_weighted_moment_single_slab_analytic():
    # ∫_a^b c (z-h)^(5/3) dz = c [(b-h)^(8/3) - (a-h)^(8/3)] / (8/3)
    c, a, b, h = 3e-17, 1000.0, 1500.0, 200.0
    got = integrate.weighted_moment_above(np.array(h), np.array([c]), np.array([a]), np.array([b]))
    want = c * ((b - h) ** (8 / 3) - (a - h) ** (8 / 3)) / (8 / 3)
    assert float(got) == pytest.approx(want, rel=1e-12)


def test_v0_is_the_wind_for_a_single_layer():
    zb, zt, c = np.array([9000.0]), np.array([9500.0]), np.array([1e-16])
    J = integrate.column_integral(c, zb, zt)
    s = integrate.weighted_sum_above(np.array(0.0), c, zb, zt, np.array([25.0 ** (5 / 3)]))
    assert float(optics.v0_from_integrals(s, J)) == pytest.approx(25.0)


# --- optics ----------------------------------------------------------------------


@given(st.floats(1e-16, 1e-10))
def test_seeing_round_trips_through_J(J):
    eps = optics.seeing_arcsec(J)
    assert float(optics.j_from_seeing(eps)) == pytest.approx(J, rel=1e-10)
    eps_b = optics.seeing_arcsec_bi(J)
    assert float(optics.j_from_seeing_bi(eps_b)) == pytest.approx(J, rel=1e-10)


@given(st.floats(1e-16, 1e-10), st.floats(1e-16, 1e-10))
def test_combining_layers_equals_adding_J(j1, j2):
    e = optics.combine_seeing(optics.seeing_arcsec(j1), optics.seeing_arcsec(j2))
    assert float(e) == pytest.approx(float(optics.seeing_arcsec(j1 + j2)), rel=1e-10)


def test_seeing_via_r0_matches_closed_form():
    J = np.array([1e-14, 5e-13, 2e-12])
    for z in (0.0, 30.0, 60.0):
        r0 = optics.fried_r0(J, zenith_deg=z)
        via_r0 = optics.seeing_from_r0_rad(r0) * K.ARCSEC_PER_RAD
        np.testing.assert_allclose(via_r0, optics.seeing_arcsec(J, zenith_deg=z), rtol=1e-12)


def test_airmass_scaling():
    J = 3e-13
    assert float(optics.seeing_arcsec(J, zenith_deg=60.0)) == pytest.approx(
        float(optics.seeing_arcsec(J)) * 2.0**0.6, rel=1e-12
    )


# --- Cₙ² models ------------------------------------------------------------------


def test_os_unstable_rules_and_counts():
    p, t = np.full(3, 500.0), np.full(3, 250.0)
    theta = column.potential_temperature(t, p)
    dth = np.array([4e-3, 0.0, -4e-3])
    s2 = np.full(3, 2.5e-5)
    qc = QCCounts()
    zero = cn2.osborn_sarazin_cn2(p, t, theta, dth, s2, unstable="zero", qc=qc)
    assert qc["os_unstable_layers"] == 2
    assert zero[0] > 0 and zero[1] == 0 and zero[2] == 0
    ab = cn2.osborn_sarazin_cn2(p, t, theta, dth, s2, unstable="abs")
    assert ab[2] == pytest.approx(ab[0]) and ab[1] == 0
    nan = cn2.osborn_sarazin_cn2(p, t, theta, dth, s2, unstable="nan")
    assert np.isnan(nan[1]) and np.isnan(nan[2]) and nan[0] == zero[0]
    with pytest.raises(ValueError):
        cn2.osborn_sarazin_cn2(p, t, theta, dth, s2, unstable="clip")


@given(st.floats(1e-7, 1e-2))
def test_os_cn2_goes_to_zero_continuously_at_neutral(dth):
    small = float(cn2.osborn_sarazin_cn2(500.0, 250.0, 300.0, dth * 1e-9, 1e-4))
    big = float(cn2.osborn_sarazin_cn2(500.0, 250.0, 300.0, dth, 1e-4))
    assert 0 <= small <= big


@given(st.floats(0.0, 0.05), st.floats(-0.012, 0.012))
def test_hmnsp99_positive_and_sign_flip(s, dtdz):
    l_std = float(cn2.hmnsp99_l0_43(s, dtdz))
    assert l_std > 0
    flipped = K.Hmnsp99Coefficients(0.362, 16.728, +192.347)
    l_flip = float(cn2.hmnsp99_l0_43(s, dtdz, troposphere_coeffs=flipped))
    assert l_flip == pytest.approx(l_std * 10 ** (2 * 192.347 * dtdz), rel=1e-9)


# --- columns ---------------------------------------------------------------------


def test_prepare_slabs_masks_underground_levels_and_counts():
    z, t, u, v = std_column()
    zs = np.array(z[3] + 10.0)  # surface just above the 925 hPa level
    sp = np.array(930.0)
    s = column.prepare_slabs(z, t, u, v, ERA5_LEVELS_HPA, sp, zs)
    assert not s.level_valid[:4].any() and s.level_valid[4:].all()
    assert s.qc["level_below_surface_pressure"] == 3  # 1000, 975, 950 hPa
    assert s.qc["level_below_orography"] == 1  # 925 hPa passes the pressure test
    assert not s.valid[:4].any() and s.valid[4:].all()
    assert np.isnan(s.dtdz[:4]).all() and np.isfinite(s.dtdz[4:]).all()


def test_prepare_slabs_rejects_non_increasing_heights():
    z, t, u, v = std_column()
    z = z.copy()
    z[10] = z[9]
    with pytest.raises(ValueError, match="do not increase"):
        column.prepare_slabs(z, t, u, v, ERA5_LEVELS_HPA)


def test_prepare_slabs_gradients_linear_profile():
    z = np.array([0.0, 1000.0, 2000.0])
    t = 280.0 - 0.0065 * z
    u = 5.0 + 0.003 * z
    v = -0.004 * z
    s = column.prepare_slabs(z, t, u, v, np.array([1000.0, 900.0, 800.0]))
    np.testing.assert_allclose(s.dtdz, -0.0065)
    np.testing.assert_allclose(s.shear, 0.005)
    np.testing.assert_allclose(s.p_mid, [np.sqrt(900_000.0), np.sqrt(720_000.0)])


def test_std_atmosphere_heights_are_sane():
    z = std_atmosphere_height(np.array([1013.25, 500.0, 226.3206, 54.74889, 50.0]))
    np.testing.assert_allclose(z[[0, 2, 3]], [0.0, 11000.0, 20000.0], atol=0.5)
    assert 5500 < z[1] < 5600  # 500 hPa ≈ 5.57 km in the standard atmosphere
    assert 20000 < z[4] < 21000


# --- tropopause --------------------------------------------------------------------


def test_tropopause_of_standard_atmosphere():
    z, t, _, _ = std_column()
    tp = wmo_tropopause_height(z, t, ERA5_LEVELS_HPA)
    # The standard tropopause is at 11 km; the lowest level at or above it is 225 hPa
    # (≈11.0 km) — the 250 hPa level (≈10.4 km) still has a 6.5 K/km lapse rate above.
    assert tp == pytest.approx(z[list(ERA5_LEVELS_HPA).index(225.0)])
    assert 10_900 < tp < 11_200


def test_tropopause_ignores_low_inversion():
    z, t, _, _ = std_column()
    t = t.copy()
    # A shallow inversion topped by a normal lapse rate already fails the WMO 2-km
    # average test, so use a deep isothermal layer from 1000 to 750 hPa (~2.4 km).
    t[:11] = t[0]
    tp = wmo_tropopause_height(z, t, ERA5_LEVELS_HPA, p_max_hpa=500.0)
    assert tp > 10_000
    qc = QCCounts()
    tp_no_bound = wmo_tropopause_height(z, t, ERA5_LEVELS_HPA, p_max_hpa=2000.0, qc=qc)
    assert tp_no_bound < 1_000  # without the bound the low isothermal layer is picked
    assert qc["tropopause_not_found"] == 0


def test_tropopause_not_found_is_counted():
    z = np.linspace(0, 20000, 21)
    t = 290.0 - 0.0065 * z  # lapse everywhere
    qc = QCCounts()
    tp = wmo_tropopause_height(z, t, np.linspace(1000, 50, 21), qc=qc)
    assert np.isnan(tp) and qc["tropopause_not_found"] == 1


@settings(max_examples=150, deadline=None)
@given(
    hnp.arrays(np.float64, (6, 12), elements=st.floats(-0.012, 0.012)),
    hnp.arrays(np.float64, (6, 12), elements=st.floats(200.0, 2500.0)),
    hnp.arrays(np.bool_, (6, 13)),
)
def test_vectorised_tropopause_matches_reference(lapses, dzs, keep):
    z = np.concatenate([np.zeros((6, 1)), np.cumsum(dzs, axis=1)], axis=1)
    t = 290.0 + np.concatenate([np.zeros((6, 1)), np.cumsum(-lapses * dzs, axis=1)], axis=1)
    p = 1000.0 * np.exp(-z / 7500.0)
    ref = _wmo_tropopause_reference(z, t, p, level_valid=keep)
    vec = wmo_tropopause_height(z, t, p, level_valid=keep)
    np.testing.assert_array_equal(np.isnan(ref), np.isnan(vec))
    np.testing.assert_allclose(vec[~np.isnan(vec)], ref[~np.isnan(ref)])


# --- cloud -----------------------------------------------------------------------


cc_cols = hnp.arrays(np.float64, st.integers(1, 15), elements=st.floats(0.0, 1.0))


@given(cc_cols, heights)
def test_cloud_above_never_increases_with_height(cc, h):
    z = np.arange(cc.size) * 700.0 + 100.0
    h = np.sort(h)
    for rule in cloud.OVERLAP_RULES:
        c = cloud.cloud_cover_above(h, cc, z, rule=rule)
        assert np.all(np.diff(c) <= 1e-12)
        assert np.all((c >= 0) & (c <= 1))


@given(cc_cols)
def test_overlap_rules_are_ordered(cc):
    mx = cloud.suffix_cover(cc, "maximum")[0]
    mr = cloud.suffix_cover(cc, "max-random")[0]
    rn = cloud.suffix_cover(cc, "random")[0]
    assert mx <= mr + 1e-12 and mr <= rn + 1e-12


def test_overlap_known_values():
    cc = np.array([0.5, 0.5, 0.0, 0.5])  # bottom → top: a block of two, a gap, one more
    assert cloud.suffix_cover(cc, "random")[0] == pytest.approx(1 - 0.5**3)
    assert cloud.suffix_cover(cc, "maximum")[0] == pytest.approx(0.5)
    # max-random: the contiguous block counts as 0.5, then random with the top 0.5 → 0.75
    assert cloud.suffix_cover(cc, "max-random")[0] == pytest.approx(0.75)


def test_cloud_cleaning_is_counted_not_silent():
    qc = QCCounts()
    cc = np.array([-0.01, 0.3, 1.02, np.nan])
    valid = np.array([True, True, True, True])
    out = cloud.clean_cloud_fraction(cc, valid, qc)
    np.testing.assert_allclose(out, [0.0, 0.3, 1.0, 0.0])
    assert qc["cc_below_0"] == 1 and qc["cc_above_1"] == 1 and qc["cc_level_masked"] == 1


def test_cloud_mid_column_invalid_level_keeps_index():
    cc = np.array([0.8, 0.0, 0.9, 0.2])
    z = np.array([100.0, 800.0, 1500.0, 2500.0])
    valid = np.array([True, True, False, True])
    c = cloud.cloud_cover_above(np.array([50.0, 500.0, 2000.0]), cc, z, valid, rule="maximum")
    np.testing.assert_allclose(c, [0.8, 0.2, 0.2])


# --- ground layer ----------------------------------------------------------------


def test_relocation_matches_osborn_sarazin_at_the_site():
    zb = np.arange(0.0, 20000.0, 250.0) + 926.0
    zt = zb + 250.0
    c = 1e-17 * np.exp(-(zb - 926.0) / 3000.0)
    zg, site = 926.0, 2635.0
    j_free, j_gl = groundlayer.relocated_integral_above(np.array([site]), c, zb, zt, np.array(zg))
    full = integrate.integral_above
    want_free = full(np.array([site]), c, zb, zt)[0]
    want_gl = full(np.array([zg]), c, zb, zt)[0] - full(np.array([zg + 1000.0]), c, zb, zt)[0]
    assert j_free[0] == pytest.approx(want_free) and float(j_gl) == pytest.approx(want_gl)


@given(slab_profiles(), heights)
def test_relocated_J_is_monotone_and_never_double_counts(prof, h):
    zb, zt, c = prof
    zg = np.array(zb[0])
    h = np.sort(h)
    j_free, j_gl = groundlayer.relocated_integral_above(h, c, zb, zt, zg)
    total = j_free + j_gl
    assert np.all(np.diff(total) <= 1e-30 + 1e-12 * np.abs(total[:-1]))
    column_total = integrate.column_integral(c, zb, zt)
    assert np.all(total <= column_total * (1 + 1e-12) + 1e-40)
    below = h <= zg + 1000.0
    np.testing.assert_allclose(total[below], column_total, rtol=1e-12, atol=1e-40)


def test_w71_neutral_limit_and_stability_sign():
    z, p, t, us = 10.0, 1000.0, 290.0, 0.3
    tiny = 1e-9
    c = groundlayer.w71_cn2(z, p, t, tiny, us)
    theta_star = -tiny / us
    want = (K.TATARSKII_A * p / t**2) ** 2 * 4.9 * theta_star**2 * z ** (-2 / 3)
    assert float(c) == pytest.approx(want, rel=1e-6)
    # upward flux → unstable → g(ζ) < 4.9; downward flux → stable → g(ζ) > 4.9
    wt = 0.05
    obukhov = -(us**3) * t / (K.VON_KARMAN * K.G0 * wt)
    assert obukhov < 0
    assert float(groundlayer.w71_g(z / obukhov)) < 4.9
    assert float(groundlayer.w71_g(-z / obukhov)) > 4.9


def test_heat_flux_sign_convention():
    # ECMWF: positive downward. Daytime heating = upward flux = negative H → w′θ′ > 0.
    assert float(groundlayer.kinematic_heat_flux(-200.0, 1000.0, 300.0)) > 0
    assert (
        float(groundlayer.kinematic_heat_flux(-200.0, 1000.0, 300.0, positive_downward=False)) < 0
    )


# --- model levels ----------------------------------------------------------------


def _toy_hybrid(nlev: int):
    """Monotone a/b half-level coefficients: pure pressure aloft, pure sigma below."""
    eta = np.linspace(0.0, 1.0, nlev + 1)
    a = 20000.0 * eta * (1 - eta) ** 2 * 4
    b = eta**3
    a[0], b[0] = 0.0, 0.0
    return a, b


def test_model_level_heights_isothermal_dry_exact():
    nlev, T, sp, zs = 30, 250.0, 95000.0, 500.0
    a, b = _toy_hybrid(nlev)
    zf, zh, ph = modellevels.model_level_heights(
        np.full(nlev, T), np.zeros(nlev), np.array(sp), np.array(zs), a, b
    )
    want = zs + K.R_DRY * T / K.G0 * np.log(sp / ph[1:])
    np.testing.assert_allclose(zh[1:], want, rtol=1e-12)
    assert np.isnan(zh[0])
    # full levels sit strictly between their half levels
    assert np.all(zf[1:] > zh[2:]) and np.all(zf[1:] < zh[1:-1])


def test_model_level_bottom_subset_gives_same_heights():
    nlev = 40
    a, b = _toy_hybrid(nlev)
    rng = np.random.default_rng(3)
    t = 220 + 60 * np.linspace(0, 1, nlev) + rng.normal(0, 1, nlev)
    q = np.linspace(0, 0.01, nlev)
    full = modellevels.model_level_heights(t, q, np.array(90000.0), np.array(1200.0), a, b)
    k0 = 15
    sub = modellevels.model_level_heights(
        t[k0:], q[k0:], np.array(90000.0), np.array(1200.0), a[k0:], b[k0:]
    )
    np.testing.assert_allclose(sub[0], full[0][k0:], rtol=1e-12)
    np.testing.assert_allclose(sub[1], full[1][k0:], rtol=1e-12)


# --- end to end -------------------------------------------------------------------


@pytest.mark.parametrize("model", [OS2018_MODEL, BI2023_MODEL])
def test_compute_profile_on_standard_atmosphere(model):
    z, t, u, v = std_column()
    res = compute_profile(z, t, u, v, ERA5_LEVELS_HPA, model=model)
    assert res.J > 0 and np.isfinite(res.J)
    eps = float(optics.seeing_arcsec(res.J))
    assert 0.01 < eps < 5.0  # plausibility only; real validation is phase 1
    j_h = res.j_above(np.array([0.0, 2000.0, 10000.0, 30000.0]))
    assert j_h[0] == pytest.approx(res.J) and j_h[-1] == 0.0
    assert np.all(np.diff(j_h) <= 0)


def test_compute_profile_vectorised_equals_single_columns():
    cols = [std_column(u_max=u) for u in (10.0, 25.0, 45.0)]
    z, t, u, v = (np.stack(x) for x in zip(*cols, strict=True))
    batch = compute_profile(z, t, u, v, ERA5_LEVELS_HPA, model=BI2023_MODEL)
    for i, (zi, ti, ui, vi) in enumerate(cols):
        one = compute_profile(zi, ti, ui, vi, ERA5_LEVELS_HPA, model=BI2023_MODEL)
        assert batch.J[i] == pytest.approx(float(one.J), rel=1e-12)


def test_priyatikanto_variants_differ_as_expected():
    z, t, u, v = std_column()
    base = compute_profile(z, t, u, v, ERA5_LEVELS_HPA, model=BI2023_MODEL)
    theta_form = Cn2Model(kind="tatarskii", m_form="dtheta")
    alt = compute_profile(z, t, u, v, ERA5_LEVELS_HPA, model=theta_form)
    assert alt.J > base.J  # θ/T ≥ 1 above 1000 hPa inflates M
    p100 = Cn2Model(kind="tatarskii", m_form="dtheta", theta_p0_hpa=100.0)
    alt100 = compute_profile(z, t, u, v, ERA5_LEVELS_HPA, model=p100)
    assert float(alt100.J) == pytest.approx(float(alt.J) * 10 ** (-2 * K.KAPPA), rel=1e-9)


def test_seeing_is_zero_turbulence_safe():
    assert math.isinf(float(optics.fried_r0(0.0)))
    assert float(optics.seeing_arcsec(0.0)) == 0.0


# --- Haslebacher et al. 2022 discretisation (D27) ------------------------------------


def _haslebacher_loop(z, t, u, v, p):
    """Their eqs. 13–16 as described in the paper and code notes (docs/RESEARCH.md §3.4),
    written independently: for each slab i→i+1, P, T and θ at level i, differences to
    level i+1, Δz = z_{i+1} − z_i, N² with |Δθ|, k = 1; J = Σ Cₙ² Δz."""
    g, a = K.G0, 80e-6
    j = 0.0
    for i in range(len(p) - 1):
        th0 = t[i] * (1000.0 / p[i]) ** 0.286
        th1 = t[i + 1] * (1000.0 / p[i + 1]) ** 0.286
        dz = z[i + 1] - z[i]
        e = ((u[i + 1] - u[i]) / dz) ** 2 + ((v[i + 1] - v[i]) / dz) ** 2
        big_l = math.sqrt(2 * e / (g / th0 * abs(th1 - th0) / dz))
        cn2 = (a * p[i] / (t[i] * th0)) ** 2 * big_l ** (4 / 3) * ((th1 - th0) / dz) ** 2
        j += cn2 * dz
    return j


@settings(max_examples=60, deadline=None)
@given(
    dt=hnp.arrays(np.float64, 29, elements=st.floats(-3.0, 3.0)),
    du=hnp.arrays(np.float64, 29, elements=st.floats(-8.0, 8.0)),
    dv=hnp.arrays(np.float64, 29, elements=st.floats(-8.0, 8.0)),
)
def test_haslebacher_mode_matches_their_equations(dt, du, dv):
    """Includes unstable slabs (random T perturbations of ±3 K make some Δθ < 0)."""
    from astroseeing.physics.profile import HASLEBACHER2022_MODEL

    p = ERA5_LEVELS_HPA
    z, t, u, v = std_column(p)
    t, u, v = t + dt, u + du, v + dv
    want = _haslebacher_loop(z, t, u, v, p)
    got = compute_profile(z, t, u, v, p, model=HASLEBACHER2022_MODEL).J
    assert float(got) == pytest.approx(want, rel=1e-12)


def test_state_at_lower_takes_the_lower_level():
    z, t, u, v = std_column(ERA5_LEVELS_HPA)
    s = column.prepare_slabs(z, t, u, v, ERA5_LEVELS_HPA, state_at="lower")
    assert s.state_at == "lower"
    assert np.array_equal(s.t_mid, t[:-1]) and np.array_equal(s.p_mid, ERA5_LEVELS_HPA[:-1])
    m = column.prepare_slabs(z, t, u, v, ERA5_LEVELS_HPA)
    assert m.state_at == "mid" and np.array_equal(m.dthetadz, s.dthetadz)  # same gradients
    with pytest.raises(ValueError, match="state_at"):
        column.prepare_slabs(z, t, u, v, ERA5_LEVELS_HPA, state_at="upper")
