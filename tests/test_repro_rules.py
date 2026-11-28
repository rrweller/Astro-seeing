"""Site-value rules (D57 item 2): known answers and properties, through ``read_site``."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from astroseeing.repro import Bilinear, Nearest, PriyatikantoCubic, read_site

from repro_stores import axis, hourly, write_pl_store, write_static_store

LAT = axis(-24.0, 5, -0.25)  # -24.00 … -25.00
LON = axis(-71.0, 5, 0.25)  # -71.00 … -70.00
TIMES = hourly("2023-06-01T00:00", 2)


def _bilinear_t(t, p, la, lo):
    return 100.0 + 2.0 * la + 3.0 * lo + 0.5 * la * lo + 0.0 * p + 0.0 * t


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    d = tmp_path_factory.mktemp("box")
    pl = write_pl_store(d / "pl.zarr", times=TIMES, lat=LAT, lon=LON, fields={"t": _bilinear_t})
    oro = write_static_store(
        d / "st.zarr", lat=LAT, lon=LON, orography_m=lambda la, lo: 100.0 * la + 10.0 * lo + 5000.0
    )
    return pl, oro


def _site(box, lat, lon, rule, **kw):
    pl, oro = box
    return read_site(
        [pl],
        lat=lat,
        lon=lon,
        rule=rule,
        start="2023-06-01",
        end="2023-06-01T02:00",
        static_store=oro,
        **kw,
    )


def test_bilinear_reproduces_a_bilinear_field_exactly_at_paranal(box):
    cols = _site(box, -24.63, -70.40, Bilinear())
    # 100 + 2(-24.63) + 3(-70.40) + 0.5(-24.63)(-70.40) = 706.516, worked by hand.
    np.testing.assert_allclose(cols.t_k, 706.516, rtol=0, atol=2e-3)
    assert set(cols.points) == {(-24.5, -70.5), (-24.5, -70.25), (-24.75, -70.5), (-24.75, -70.25)}
    # The orography goes through the same rule: 100(-24.63) + 10(-70.40) + 5000 = 1833.0.
    assert cols.orography_m == pytest.approx(1833.0, abs=0.01)
    assert cols.settings["rule"] == {"rule": "bilinear"}


def test_bilinear_on_a_grid_point_is_that_point(box):
    near = _site(box, -24.75, -70.50, Nearest())
    bil = _site(box, -24.75, -70.50, Bilinear())
    np.testing.assert_allclose(bil.t_k, near.t_k, rtol=1e-7)


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(fy=st.floats(0.0, 1.0), fx=st.floats(0.0, 1.0))
def test_bilinear_stays_within_the_four_corner_values(box, fy, fx):
    lat = -24.75 + 0.25 * fy * 0.999
    lon = -70.50 + 0.25 * fx * 0.999
    bil = _site(box, lat, lon, Bilinear())
    corners = np.array([_site(box, la, lo, Nearest()).u for la, lo in bil.points])
    assert (bil.u >= corners.min(axis=0) - 1e-4).all()
    assert (bil.u <= corners.max(axis=0) + 1e-4).all()


# --- Priyatikanto et al. 2026: cubic in lon, lat, p; then linear to 5 hPa steps -------

#: ERA5's 37 pressure levels, bottom → top (the Timau stores have all of them).
# fmt: off
LEVELS_37 = np.array([1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 650, 600,
                      550, 500, 450, 400, 350, 300, 250, 225, 200, 175, 150, 125, 100, 70, 50,
                      30, 20, 10, 7, 5, 3, 2, 1], dtype=float)
# fmt: on
LAT7 = axis(-24.0, 7, -0.25)  # -24.00 … -25.50: holds the 5 × 5 box round (-24.75, -70.50)
LON7 = axis(-71.5, 7, 0.25)  # -71.50 … -70.00


def _cubic_t(t, p, la, lo):
    x, y = la + 24.5, lo + 70.5
    return 250.0 + 40 * x**3 + 30 * y**3 + 20 * x**2 * y + 5 * x + 0.0 * p + 0.0 * t


def _quadratic_in_p(t, p, la, lo):
    return 200.0 + 1e-4 * (p - 500.0) ** 2 + 0.0 * la + 0.0 * lo + 0.0 * t


@pytest.fixture(scope="module")
def box37(tmp_path_factory):
    d = tmp_path_factory.mktemp("box37")
    pl = write_pl_store(
        d / "pl.zarr",
        times=TIMES,
        lat=LAT7,
        lon=LON7,
        levels=LEVELS_37,
        fields={"t": _cubic_t, "u": _quadratic_in_p},
    )
    oro = write_static_store(d / "st.zarr", lat=LAT7, lon=LON7, orography_m=1300.0)
    return pl, oro


def test_priyatikanto_cubic_reproduces_a_cubic_field_exactly(box37):
    cols = _site(box37, -24.63, -70.40, PriyatikantoCubic())
    # x = -0.13, y = 0.10: 250 - 0.08788 + 0.03 + 0.0338 - 0.65 = 249.32592, by hand.
    np.testing.assert_allclose(cols.t_k, 249.32592, rtol=0, atol=2e-4)
    # The stencil is the 5 × 5 box round the nearest point.
    assert len(cols.points) == 25
    assert {la for la, _ in cols.points} == {-24.25, -24.5, -24.75, -25.0, -25.25}
    # Bilinear on the same field misses it, so the test tells the rules apart.
    assert abs(_site(box37, -24.63, -70.40, Bilinear()).t_k[0, 0] - 249.32592) > 1e-3


def test_priyatikanto_puts_the_column_on_5_hpa_steps_from_1000_to_10_hpa(box37):
    cols = _site(box37, -24.63, -70.40, PriyatikantoCubic())
    np.testing.assert_array_equal(cols.p_hpa, np.arange(1000.0, 9.0, -5.0))
    assert cols.u.shape == (2, 199)
    # Linear between the 1000 and 975 hPa values (225 and 222.5625) at 995 hPa.
    assert cols.u[0, 1] == pytest.approx(224.5125, abs=2e-4)
    assert cols.settings["rule"] == {
        "rule": "priyatikanto_cubic",
        "half_width": 2,
        "cubic_to": "native",
        "bottom_hpa": 1000.0,
        "top_hpa": 10.0,
        "step_hpa": 5.0,
    }


def test_priyatikanto_cubic_in_pressure_onto_the_5_hpa_steps_variant(box37):
    cols = _site(box37, -24.63, -70.40, PriyatikantoCubic(cubic_to="target"))
    # A cubic spline is exact for a quadratic: 200 + 1e-4 · 495² = 224.5025.
    assert cols.u[0, 1] == pytest.approx(224.5025, abs=2e-4)


def test_priyatikanto_masks_after_interpolation_with_the_interpolated_orography(box37):
    cols = _site(box37, -24.63, -70.40, PriyatikantoCubic())
    # 1300 m lies between 875 hPa (1220.2 m) and 850 hPa (1457.3 m): on the 5 hPa steps
    # 870 hPa is at 1267.6 m (masked) and 865 hPa at 1315.0 m (kept): 27 levels masked.
    assert cols.orography_m == pytest.approx(1300.0, abs=0.01)
    assert cols.masked_levels == 27 * 2
    assert not cols.level_valid[:, :27].any() and cols.level_valid[:, 27:].all()


def test_priyatikanto_refuses_a_top_the_stores_do_not_reach(tmp_path):
    pl = write_pl_store(tmp_path / "pl.zarr", times=TIMES, lat=LAT7, lon=LON7)  # 29 levels
    oro = write_static_store(tmp_path / "st.zarr", lat=LAT7, lon=LON7)
    with pytest.raises(ValueError, match=r"10\.0 hPa"):
        _site((pl, oro), -24.63, -70.40, PriyatikantoCubic())  # they stop at 50 hPa
    cols = _site((pl, oro), -24.63, -70.40, PriyatikantoCubic(top_hpa=50.0))
    assert cols.p_hpa[-1] == 50.0 and cols.p_hpa.size == 191


def test_priyatikanto_needs_the_whole_box(box):
    # The 5 × 5 store holds no full box round (-24.75, -70.50).
    with pytest.raises(ValueError, match="grid point"):
        _site(box, -24.63, -70.40, PriyatikantoCubic(top_hpa=50.0))
