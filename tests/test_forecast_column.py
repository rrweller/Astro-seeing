"""Column products (F1 spec Module 3; ticket #51): known answers for H̄, the observer's
raise to the model ground, the gap to the first usable level and the cut slab."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from astroseeing.forecast.column import CN2_MODELS, column_products
from astroseeing.forecast.settings import Grid, Host, Hosts, Model
from astroseeing.forecast.sources import RunFields, RunRef

LEVELS = np.array([1000.0, 975, 950, 900, 800, 700, 600, 500, 400, 300, 200, 100])
RUN = RunRef("test", dt.datetime(2026, 11, 26, 12, tzinfo=dt.UTC))
MODEL = Model(
    id="test",
    name="Test",
    family="test",
    regional=False,
    runs_utc=(12,),
    steps_h=(0,),
    publish_delay_h=1.0,
    online_window_h=24.0,
    hosts=Hosts(Host("fake", "https://example.invalid", None), None),
    grid=Grid("regular_latlon", 0.25, "deg"),
    pressure_levels_hpa=tuple(LEVELS),
    level_cloud=False,
    fog_signals=(),
)
GAMMA = 9.8e-3  # Tatarskii's lapse-rate constant (Bi et al.): M = 0 at dT/dz = -γ


def column(z, turbulent_slab, ground=-50.0, sp=1013.0):
    """One column on one step: dry-adiabatic and windless shear everywhere (no
    turbulence in either Cₙ² model) except the slab ``turbulent_slab`` (an index into
    the slabs), which is isothermal and sheared."""
    z = np.asarray(z, dtype=float)
    t = 290.0 - GAMMA * (z - z[0])
    u = np.full_like(z, 10.0)
    k = turbulent_slab
    t[k + 1 :] += GAMMA * (z[k + 1] - z[k])  # isothermal across the slab, adiabatic above
    u[k + 1 :] += 0.01 * (z[k + 1] - z[k])  # shear only across the slab
    one = (1, 1, 1, len(z))  # (steps, lat, lon, levels)
    return RunFields(
        run=RUN,
        model=MODEL,
        lat=np.array([[60.0]]),
        lon=np.array([[10.0]]),
        valid_times=np.array(["2026-11-26T12:00"], dtype="datetime64[s]"),
        pressure_hpa=LEVELS,
        geopotential_height_m=z.reshape(one),
        temperature_k=t.reshape(one),
        u_ms=u.reshape(one),
        v_ms=np.zeros(one),
        level_cloud_pct=None,
        total_cloud_pct=np.zeros((1, 1, 1)),
        low_cloud_pct=np.zeros((1, 1, 1)),
        mid_cloud_pct=np.zeros((1, 1, 1)),
        high_cloud_pct=np.zeros((1, 1, 1)),
        surface_pressure_hpa=np.full((1, 1, 1), sp),
        model_ground_m=np.full((1, 1), ground),
        fog={},
    )


# heights of the 12 levels; slab 6 is a thin layer from 4990 to 5010 m
Z_THIN = [0, 200, 400, 1000, 2000, 3000, 4990, 5010, 7000, 9000, 12000, 16000]


@pytest.mark.parametrize("cn2", list(CN2_MODELS))
def test_hbar_of_a_single_thin_layer_at_height_h_is_h(cn2):
    f = column(Z_THIN, turbulent_slab=6)
    c = column_products(f, observer_height_m=0.0)[cn2]
    assert c.j_total[0, 0, 0] > 0
    assert c.hbar_m[0, 0, 0] == pytest.approx(5000.0, rel=1e-5)
    # the whole column's turbulence is in the free atmosphere (above observer + 1 km)
    assert c.j_free[0, 0, 0] == pytest.approx(c.j_total[0, 0, 0], rel=1e-12)
    # H̄ is measured above the observer: from 1000 m up, the layer is 4000 m above
    c2 = column_products(f, observer_height_m=1000.0)[cn2]
    assert c2.hbar_m[0, 0, 0] == pytest.approx(4000.0, rel=1e-5)


def test_seeing_is_the_exact_5307_form_at_500_nm_zenith():
    f = column(Z_THIN, turbulent_slab=6)
    c = column_products(f, observer_height_m=0.0)["osborn_sarazin"]
    j = c.j_total[0, 0, 0]
    # RESEARCH §4.5: ε = 5.307 λ^(-1/5) J^(3/5) (radians), λ = 500 nm
    want = 5.307 * (500e-9) ** -0.2 * j**0.6 * 206264.806
    assert c.seeing_total_arcsec[0, 0, 0] == pytest.approx(want, rel=1e-3)


def test_a_place_below_the_model_ground_is_raised_to_it_and_the_gap_is_counted():
    # Kongsberg-like: the place at 162 m, the model ground at 327 m, surface pressure
    # 992 hPa so 1000 hPa (z = 80 m) is below ground; 975 hPa (z = 480 m) is first.
    z = [80, 480, 700, 1100, 2000, 3000, 4200, 5600, 7200, 9200, 11800, 16200]
    f = column(z, turbulent_slab=5, ground=327.0, sp=992.0)
    p = column_products(f, observer_height_m=162.0)
    assert p.observer_height_m[0, 0] == 327.0
    assert p.raise_m[0, 0] == pytest.approx(165.0)
    assert p.gap_to_first_level_m[0, 0, 0] == pytest.approx(480 - 327)
    assert p.valid_levels[0, 0, 0] == 11 and p.level_count == 12
    assert p.qc["level_below_surface_pressure"] == 1
    assert p.qc["observer_raised"] == 1


def test_a_place_above_the_model_ground_cuts_the_straddling_slab_in_j():
    # observer at 2500 m inside slab 4 (2000-3000 m), the only turbulent slab
    f = column(Z_THIN, turbulent_slab=4, ground=-10.0)
    at_bottom = column_products(f, observer_height_m=2000.0)
    inside = column_products(f, observer_height_m=2500.0)
    assert inside.raise_m[0, 0] == 0.0 and inside.observer_height_m[0, 0] == 2500.0
    for cn2 in CN2_MODELS:
        j_full = at_bottom[cn2].j_total[0, 0, 0]
        assert inside[cn2].j_total[0, 0, 0] == pytest.approx(0.5 * j_full, rel=1e-12)
    # the levels at 0-2000 m are wholly below the observer (index 0..4 at 2500 m)
    assert inside.qc["level_below_observer"] == 5


def test_the_200_hpa_wind_is_the_speed_at_200_hpa():
    f = column(Z_THIN, turbulent_slab=6)
    p = column_products(f, observer_height_m=0.0)
    u200 = f.u_ms[0, 0, 0, list(LEVELS).index(200.0)]
    assert p.wind_200hpa_ms[0, 0, 0] == pytest.approx(abs(u200))


def test_a_column_with_no_turbulence_has_no_hbar_and_says_so():
    f = column(Z_THIN, turbulent_slab=6)
    f = RunFields(**{**f.__dict__, "u_ms": np.full_like(f.u_ms, 10.0)})  # no shear anywhere
    c = column_products(f, observer_height_m=0.0)["osborn_sarazin"]
    assert c.j_total[0, 0, 0] == 0.0 and np.isnan(c.hbar_m[0, 0, 0])
    assert c.qc["hbar_undefined_no_turbulence"] == 1
