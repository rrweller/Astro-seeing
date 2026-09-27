"""Astronomical darkness per cell and night (docs/RESEARCH.md §4.1).

Night definition: from local mean solar noon to the next local mean solar noon,
keyed by the date of the evening. Local mean noon at longitude λ (east-positive) is
12:00 UTC − λ/15 h. Everything is stored in UTC.

Durations are counted at 1-minute resolution (minute midpoints), as §4.1 asks;
hourly samples are too coarse (§9 pitfall 20). :func:`dark_intervals` refines
crossing times further (bisection to 1 s) for comparisons with Skyfield.
"""

from __future__ import annotations

import numpy as np

from astroseeing.solar.sun import SunTable, solar_altitude_deg

ASTRONOMICAL = -18.0
NAUTICAL = -12.0
MINUTES_PER_NIGHT = 1440


def night_start_unix(evening_dates: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    """Unix seconds of local mean noon on each evening date, shape (ncells, nnights).

    ``evening_dates`` are ``datetime64[D]`` (or castable), ``lon_deg`` east-positive.
    """
    d = np.asarray(evening_dates, dtype="datetime64[D]").astype(np.int64) * 86400.0
    lon = np.asarray(lon_deg, dtype=np.float64)
    return d[None, :] + 12 * 3600.0 - lon[:, None] / 15.0 * 3600.0


def _minute_midpoints() -> np.ndarray:
    return (np.arange(MINUTES_PER_NIGHT) + 0.5) * 60.0


def dark_minutes(
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    evening_dates: np.ndarray,
    sun: SunTable,
    threshold_deg: float = ASTRONOMICAL,
    chunk_cells: int = 2048,
) -> np.ndarray:
    """Minutes with the Sun below ``threshold_deg`` per cell and night, int16 (ncells, nnights)."""
    lat = np.atleast_1d(np.asarray(lat_deg, dtype=np.float64))
    lon = np.atleast_1d(np.asarray(lon_deg, dtype=np.float64))
    dates = np.atleast_1d(np.asarray(evening_dates, dtype="datetime64[D]"))
    out = np.empty((lat.size, dates.size), dtype=np.int16)
    mids = _minute_midpoints()
    for c0 in range(0, lat.size, chunk_cells):
        sl = slice(c0, c0 + chunk_cells)
        starts = night_start_unix(dates, lon[sl])  # (nc, nn)
        for n in range(dates.size):
            t = starts[:, n, None] + mids[None, :]  # (nc, 1440)
            gha, dec = sun.at(t)
            alt = solar_altitude_deg(lat[sl, None], lon[sl, None], gha, dec)
            out[sl, n] = np.sum(alt < threshold_deg, axis=1)
    return out


def minute_fraction_below(
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    hour_times_unix: np.ndarray,
    sun: SunTable,
    threshold_deg: float = ASTRONOMICAL,
) -> np.ndarray:
    """Fraction of the minutes in [t − 30 min, t + 30 min) with the Sun below the threshold.

    Returns (ncells, ntimes) float32. This is how an hourly ERA5 sample is related
    to darkness: the sample represents the hour centred on it.
    """
    lat = np.atleast_1d(np.asarray(lat_deg, dtype=np.float64))
    lon = np.atleast_1d(np.asarray(lon_deg, dtype=np.float64))
    t = np.atleast_1d(np.asarray(hour_times_unix, dtype=np.float64))
    offsets = (np.arange(60) - 30 + 0.5) * 60.0
    out = np.empty((lat.size, t.size), dtype=np.float32)
    for j, tj in enumerate(t):
        gha, dec = sun.at(tj + offsets)
        alt = solar_altitude_deg(lat[:, None], lon[:, None], gha[None, :], dec[None, :])
        out[:, j] = np.mean(alt < threshold_deg, axis=1)
    return out


def night_hours_to_keep(
    lat_deg: np.ndarray,
    lon_deg: np.ndarray,
    hour_times_unix: np.ndarray,
    sun: SunTable,
    threshold_deg: float = NAUTICAL,
) -> np.ndarray:
    """Ingest night mask: keep hour t if the Sun is below −12° at any minute in [t−30, t+30).

    Stricter-than-needed on purpose: any hour whose window touches astronomical
    darkness (−18°) is always kept, with margin (docs/decisions.md).
    """
    return minute_fraction_below(lat_deg, lon_deg, hour_times_unix, sun, threshold_deg) > 0


def dark_intervals(
    lat_deg: float,
    lon_deg: float,
    start_unix: float,
    end_unix: float,
    sun: SunTable,
    threshold_deg: float = ASTRONOMICAL,
    tol_s: float = 1.0,
) -> list[tuple[float, float]]:
    """Intervals within [start, end) with the Sun below the threshold, crossings to ``tol_s``.

    Sampled every minute, then each sign change is refined by bisection. Dips shorter
    than a minute between samples can be missed; that is below the 1-minute target.
    """
    t = np.arange(start_unix, end_unix, 60.0)
    t = np.append(t, end_unix)

    def below(x: np.ndarray) -> np.ndarray:
        gha, dec = sun.at(x)
        return solar_altitude_deg(lat_deg, lon_deg, gha, dec) < threshold_deg

    b = below(t)

    def refine(lo: float, hi: float, lo_state: bool) -> float:
        while hi - lo > tol_s:
            mid = 0.5 * (lo + hi)
            if bool(below(np.array([mid]))[0]) == lo_state:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    intervals: list[tuple[float, float]] = []
    cur_start = start_unix if b[0] else None
    for i in np.flatnonzero(b[1:] != b[:-1]):
        x = refine(t[i], t[i + 1], bool(b[i]))
        if b[i + 1]:
            cur_start = x
        else:
            intervals.append((cur_start, x))
            cur_start = None
    if cur_start is not None:
        intervals.append((cur_start, end_unix))
    return intervals


def dark_hours_declination(lat_deg: np.ndarray, dec_deg: np.ndarray, threshold_deg: float = -18.0):
    """Simple declination formula (§4.1): 2(180° − H₁₈)/15°, hours; δ held fixed over the night."""
    phi = np.radians(lat_deg)
    dec = np.radians(dec_deg)
    with np.errstate(divide="ignore", invalid="ignore"):
        cos_h = (np.sin(np.radians(threshold_deg)) - np.sin(phi) * np.sin(dec)) / (
            np.cos(phi) * np.cos(dec)
        )
    h = np.degrees(np.arccos(np.clip(cos_h, -1.0, 1.0)))
    return np.where(cos_h <= -1, 0.0, np.where(cos_h >= 1, 24.0, 2 * (180.0 - h) / 15.0))
