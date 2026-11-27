"""Site-value rules: how a site's column is made from the grid points around it (D57 item 2).

A rule picks a *stencil* (a rectangle of grid points around the site) and combines
the values on it into one column. Longitudes are handled as offsets east of the
site (wrapped to ±180°), so 0..360 and −180..180 stores behave the same.

Only z, T, u, v (and cc) are interpolated here, inside reproductions, because the
papers did; seeing and J are never interpolated (AGENTS.md, D57 item 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

#: Coordinates are compared after rounding to this many decimals (1e-6°, ~0.1 m).
COORD_DECIMALS = 6


def _nearest(axis: np.ndarray, x: float, what: str) -> float:
    d = np.abs(axis - x)
    best = d.min()
    ties = axis[np.isclose(d, best, rtol=0.0, atol=1e-9)]
    if ties.size > 1:
        raise ValueError(
            f"site {what} {x} is exactly halfway between grid {what}s {sorted(ties.tolist())}; "
            "the nearest point is ambiguous"
        )
    return float(axis[np.argmin(d)])


@dataclass(frozen=True)
class Nearest:
    """The nearest grid point (Bi: its listed point; Haslebacher: their code's choice).

    Nearest in latitude and in longitude separately, which on a regular grid is the
    nearest point in degrees. A site exactly halfway between two grid lines is an
    error rather than a silent pick.
    """

    def settings(self) -> dict[str, Any]:
        return {"rule": "nearest"}

    def stencil(
        self, lats: np.ndarray, dlons: np.ndarray, site_lat: float
    ) -> tuple[np.ndarray, np.ndarray]:
        return (
            np.array([_nearest(lats, site_lat, "latitude")]),
            np.array([_nearest(dlons, 0.0, "longitude")]),
        )

    def combine(
        self, values: np.ndarray, lat_axis: np.ndarray, dlon_axis: np.ndarray, site_lat: float
    ) -> np.ndarray:
        return values[..., 0, 0]

    def vertical(self, p_hpa: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The stored levels, unchanged."""
        return p_hpa, values


def _bracket(axis: np.ndarray, x: float, what: str) -> np.ndarray:
    """The two axis values either side of ``x``, or ``x`` alone when it is on the axis."""
    on = axis[np.isclose(axis, x, rtol=0.0, atol=10.0**-COORD_DECIMALS)]
    if on.size:
        return on[:1]
    below, above = axis[axis < x], axis[axis > x]
    if not below.size or not above.size:
        raise ValueError(f"site {what} {x} is outside the stored grid points")
    return np.array([below.max(), above.min()])


def _linear_weights(axis: np.ndarray, x: float) -> np.ndarray:
    if axis.size == 1:
        return np.ones(1)
    f = (x - axis[0]) / (axis[1] - axis[0])
    return np.array([1.0 - f, f])


@dataclass(frozen=True)
class Bilinear:
    """Four-point bilinear interpolation in latitude and longitude (degrees; O&S 2018).

    A site exactly on a grid line uses that line alone (two points, or one on a
    grid point), so the weights never reach outside the grid points they name.
    """

    def settings(self) -> dict[str, Any]:
        return {"rule": "bilinear"}

    def stencil(
        self, lats: np.ndarray, dlons: np.ndarray, site_lat: float
    ) -> tuple[np.ndarray, np.ndarray]:
        return _bracket(lats, site_lat, "latitude"), _bracket(dlons, 0.0, "longitude")

    def combine(
        self, values: np.ndarray, lat_axis: np.ndarray, dlon_axis: np.ndarray, site_lat: float
    ) -> np.ndarray:
        wy = _linear_weights(lat_axis, site_lat)
        wx = _linear_weights(dlon_axis, 0.0)
        return np.einsum("...yx,y,x->...", values, wy, wx)

    def vertical(self, p_hpa: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The stored levels, unchanged."""
        return p_hpa, values


def _spline_eval(x: np.ndarray, y: np.ndarray, xq: np.ndarray | float, axis: int) -> np.ndarray:
    """Not-a-knot cubic spline through (x, y) along ``axis``, evaluated at ``xq``.

    This is what SciPy's ``RegularGridInterpolator(method="cubic")`` does along each
    axis in turn (``make_interp_spline``, k = 3, not-a-knot ends).
    """
    from scipy.interpolate import make_interp_spline

    order = np.argsort(x)
    spl = make_interp_spline(x[order], np.take(y, order, axis=axis), k=3, axis=axis)
    return spl(xq)


@dataclass(frozen=True)
class PriyatikantoCubic:
    """Priyatikanto et al. 2026's site column: cubic interpolation in longitude,
    latitude and pressure, then linear interpolation onto ``step_hpa`` steps from
    ``bottom_hpa`` to ``top_hpa`` (their §II.1–II.2; D57 items 2 and 10).

    * Horizontal: not-a-knot cubic splines, one axis after the other (longitude, then
      latitude), over the ``(2·half_width+1)²`` box round the nearest grid point; every
      point of the box must be stored. Their own cube was larger (its extent is not
      stated), which changes the spline's ends slightly.
    * ``cubic_to="native"`` (default): the cubic step in pressure is evaluated at the
      stored levels, where it returns them unchanged; the linear step (linear in p)
      then makes the 5 hPa column. This reads their text literally: cubic to the site,
      then linear onto 5 hPa steps "on the ERA5 and radiosonde datasets".
    * ``cubic_to="target"``: the cubic spline in pressure is evaluated on the 5 hPa
      steps directly, so the linear step changes nothing (a variant).

    The target levels must lie within the stored levels: nothing is extrapolated.
    """

    half_width: int = 2
    cubic_to: str = "native"
    bottom_hpa: float = 1000.0
    top_hpa: float = 10.0
    step_hpa: float = 5.0

    def __post_init__(self) -> None:
        if self.cubic_to not in ("native", "target"):
            raise ValueError(f"cubic_to must be 'native' or 'target', got {self.cubic_to!r}")
        if self.half_width < 2:
            raise ValueError("a cubic spline needs at least 4 points per axis (half_width ≥ 2)")

    def settings(self) -> dict[str, Any]:
        return {
            "rule": "priyatikanto_cubic",
            "half_width": self.half_width,
            "cubic_to": self.cubic_to,
            "bottom_hpa": float(self.bottom_hpa),
            "top_hpa": float(self.top_hpa),
            "step_hpa": float(self.step_hpa),
        }

    def stencil(
        self, lats: np.ndarray, dlons: np.ndarray, site_lat: float
    ) -> tuple[np.ndarray, np.ndarray]:
        lat0 = _nearest(lats, site_lat, "latitude")
        dlon0 = _nearest(dlons, 0.0, "longitude")
        step_y = np.min(np.diff(lats)) if lats.size > 1 else 0.25
        step_x = np.min(np.diff(dlons)) if dlons.size > 1 else 0.25
        k = np.arange(-self.half_width, self.half_width + 1)
        return (
            np.round(lat0 + k * step_y, COORD_DECIMALS),
            np.round(dlon0 + k * step_x, COORD_DECIMALS),
        )

    def combine(
        self, values: np.ndarray, lat_axis: np.ndarray, dlon_axis: np.ndarray, site_lat: float
    ) -> np.ndarray:
        along_lon = _spline_eval(dlon_axis, values, 0.0, axis=values.ndim - 1)
        return _spline_eval(lat_axis, along_lon, site_lat, axis=along_lon.ndim - 1)

    def target_levels(self) -> np.ndarray:
        n = round((self.bottom_hpa - self.top_hpa) / self.step_hpa)
        return self.bottom_hpa - self.step_hpa * np.arange(n + 1)

    def vertical(self, p_hpa: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        target = self.target_levels()
        if target.max() > p_hpa.max() or target.min() < p_hpa.min():
            raise ValueError(
                f"target levels {target.max()}–{target.min()} hPa reach outside the stored "
                f"levels {p_hpa.max()}–{p_hpa.min()} hPa; nothing is extrapolated"
            )
        if self.cubic_to == "target":
            return target, _spline_eval(p_hpa, values, target, axis=values.ndim - 1)
        # Linear in p between the stored levels either side of each target level.
        order = np.argsort(p_hpa)
        xp, fp = p_hpa[order], values[..., order]
        hi = np.clip(np.searchsorted(xp, target, side="right"), 1, xp.size - 1)
        lo = hi - 1
        w = (target - xp[lo]) / (xp[hi] - xp[lo])
        return target, fp[..., lo] * (1.0 - w) + fp[..., hi] * w


SiteRule = Nearest | Bilinear | PriyatikantoCubic
