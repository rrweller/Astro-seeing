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


# --- Synthetic GRIB files (tests and dry runs) ---------------------------------------

_SL_TYPICAL = {
    "tcc": 0.3,
    "lcc": 0.1,
    "mcc": 0.1,
    "hcc": 0.2,
    "cbh": 1500.0,
    "sp": 85000.0,
    "2t": 285.0,
    "2d": 275.0,
    "skt": 283.0,
    "10u": 3.0,
    "10v": -1.0,
    "100u": 5.0,
    "100v": -2.0,
    "blh": 400.0,
    "zust": 0.3,
    "ishf": 20.0,
    "tcwv": 12.0,
    "z": 15000.0,
    "lsm": 1.0,
    "sdor": 120.0,
}


def write_synthetic_grib(
    path,
    expected: dict,
    param_ids: dict[str, int],
    seed: int = 0,
    drop: int = 0,
    duplicate: int = 0,
    shift_grid_deg: float = 0.0,
) -> int:
    """Write an ERA5-like GRIB1 file matching ``expected`` (from ``RequestSpec.expected``).

    ``param_ids`` maps short names to ERA5 paramIds. ``drop``/``duplicate`` remove or
    repeat that many messages and ``shift_grid_deg`` offsets the grid, to test that
    verification catches them. Returns the number of messages written.
    """
    import datetime as dt

    import eccodes as ec

    rng = np.random.default_rng(seed)
    g = expected["grid"]
    nlat, nlon = g["nlat"], g["nlon"]
    levels = expected.get("levels")
    sample = "regular_ll_pl_grib1" if levels else "regular_ll_sfc_grib1"
    lat = np.linspace(g["lat_first"], g["lat_last"], nlat)
    fields = []
    for t in expected["times"]:
        when = dt.datetime.strptime(t, "%Y-%m-%dT%H:%M")
        for sn in expected["short_names"]:
            for lv in levels or [None]:
                fields.append((when, sn, lv))
    if drop:
        fields = fields[:-drop]
    if duplicate:
        fields = fields + fields[:duplicate]
    n = 0
    with open(path, "wb") as f:
        for when, sn, lv in fields:
            h = ec.codes_grib_new_from_samples(sample)
            try:
                ec.codes_set(h, "centre", "ecmf")
                ec.codes_set(h, "paramId", param_ids[sn])
                if lv is not None:
                    ec.codes_set(h, "typeOfLevel", "isobaricInhPa")
                    ec.codes_set(h, "level", int(lv))
                ec.codes_set(h, "dataDate", int(when.strftime("%Y%m%d")))
                ec.codes_set(h, "dataTime", int(when.strftime("%H%M")))
                ec.codes_set(h, "Ni", nlon)
                ec.codes_set(h, "Nj", nlat)
                ec.codes_set(
                    h, "latitudeOfFirstGridPointInDegrees", g["lat_first"] + shift_grid_deg
                )
                ec.codes_set(h, "latitudeOfLastGridPointInDegrees", g["lat_last"] + shift_grid_deg)
                ec.codes_set(h, "longitudeOfFirstGridPointInDegrees", g["lon_first"])
                ec.codes_set(h, "longitudeOfLastGridPointInDegrees", g["lon_last"])
                ec.codes_set(h, "iDirectionIncrementInDegrees", g["step"])
                ec.codes_set(h, "jDirectionIncrementInDegrees", g["step"])
                ec.codes_set(h, "bitsPerValue", 16)
                if lv is not None:
                    zc = float(std_atmosphere_height(np.array([float(lv)]))[0])
                    base = {
                        "z": zc * G0,
                        "t": float(std_atmosphere_temperature(np.array([zc]))[0]),
                        "u": float(jet_wind(np.array([zc]))[0][0]),
                        "v": float(jet_wind(np.array([zc]))[1][0]),
                        "cc": 0.2,
                        "q": 1e-3,
                    }[sn]
                else:
                    base = _SL_TYPICAL.get(sn, 1.0)
                vals = (
                    base
                    + 0.01 * abs(base) * rng.standard_normal((nlat, nlon))
                    + 0.001 * lat[:, None]
                )
                if sn in ("cc", "tcc", "lcc", "mcc", "hcc", "lsm"):
                    vals = np.clip(vals, 0.0, 1.0)
                ec.codes_set_values(h, vals.ravel())
                ec.codes_write(h, f)
                n += 1
            finally:
                ec.codes_release(h)
    return n
