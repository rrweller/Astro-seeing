"""Solar position for darkness and night masks (docs/RESEARCH.md §4.1).

The Sun's apparent geocentric position is computed with Skyfield once per time
step, as Greenwich hour angle (GHA) and declination δ. The altitude at any cell is
then plain vectorised trigonometry:

    sin a = sin φ sin δ + cos φ cos δ cos(GHA + λ)      (λ east-positive)

No refraction is applied (twilight limits are geometric, and Skyfield's
``almanac.dark_twilight_day`` applies none at −18°/−12°/−6°). Using the geocentric
rather than topocentric position ignores the Sun's parallax (≤ 8.8″), which shifts
twilight times by about a second.

:class:`SunTable` samples GHA and δ at a fixed step (default 10 min) and
interpolates linearly; tests bound the interpolation error.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

#: JPL DE440s (1849–2150), the ephemeris used for all solar computations.
EPHEMERIS_NAME = "de440s.bsp"
#: SHA-256 of the file as downloaded by Skyfield from ssd.jpl.nasa.gov on 2026-09-27.
EPHEMERIS_SHA256 = "c1c7feeab882263fc493a9d5a5b2ddd71b54826cdf65d8d17a76126b260a49f2"

UNIX_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def default_ephemeris_dir() -> Path:
    """``$ASTRO_EPHEMERIS_DIR`` or ``~/.local/share/astro/ephem``."""
    env = os.environ.get("ASTRO_EPHEMERIS_DIR")
    return Path(env) if env else Path.home() / ".local/share/astro/ephem"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_ephemeris(directory: Path | None = None, download: bool = True):
    """Load (ephemeris, timescale), downloading DE440s once if needed.

    The file's SHA-256 is checked against :data:`EPHEMERIS_SHA256`; a mismatch is
    an error (never silently accepted).
    """
    from skyfield.api import Loader

    directory = Path(directory) if directory else default_ephemeris_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / EPHEMERIS_NAME
    if not path.exists() and not download:
        raise FileNotFoundError(f"{path} missing; run `pixi run fetch-ephemeris`")
    loader = Loader(str(directory), verbose=False)
    eph = loader(EPHEMERIS_NAME)
    digest = _sha256(path)
    if digest != EPHEMERIS_SHA256:
        raise RuntimeError(f"{path} sha256 {digest} != expected {EPHEMERIS_SHA256}")
    ts = loader.timescale(builtin=True)
    return eph, ts


def to_unix(t: dt.datetime | np.datetime64 | np.ndarray) -> np.ndarray:
    """datetime / datetime64 → float seconds since 1970-01-01 UTC."""
    if isinstance(t, dt.datetime):
        if t.tzinfo is None:
            raise ValueError("naive datetime; everything must be UTC-aware")
        return np.float64((t - UNIX_EPOCH).total_seconds())
    arr = np.asarray(t)
    if np.issubdtype(arr.dtype, np.datetime64):
        return arr.astype("datetime64[ns]").astype(np.int64) / 1e9
    return arr.astype(np.float64)


def unix_to_time(ts, unix_seconds: np.ndarray):
    """Skyfield Time for Unix seconds.

    Unix time has exactly 86 400 s per day (no leap seconds), so pass Skyfield
    whole days plus seconds of day. ``ts.utc(1970, 1, 1, 0, 0, u)`` would instead
    count leap seconds and land 27 s early in 2023 (tested).
    """
    u = np.asarray(unix_seconds, dtype=np.float64)
    days = np.floor(u / 86400.0)
    return ts.utc(1970, 1, 1 + days, 0, 0, u - days * 86400.0)


def sun_gha_dec(unix_seconds: np.ndarray, eph, ts) -> tuple[np.ndarray, np.ndarray]:
    """Apparent geocentric GHA and declination of the Sun (degrees), directly from Skyfield."""
    t = unix_to_time(ts, np.atleast_1d(np.asarray(unix_seconds, dtype=np.float64)))
    ra, dec, _ = eph["earth"].at(t).observe(eph["sun"]).apparent().radec(epoch="date")
    gha = (t.gast - ra.hours) * 15.0
    return np.mod(gha, 360.0), dec.degrees


@dataclass
class SunTable:
    """GHA (unwrapped, degrees) and declination (degrees) on a regular UTC grid."""

    t0: float  # unix seconds of the first sample
    step: float  # seconds
    gha_unwrapped: np.ndarray
    dec: np.ndarray

    @classmethod
    def build(
        cls,
        start: dt.datetime,
        end: dt.datetime,
        eph,
        ts,
        step_minutes: float = 10.0,
    ) -> SunTable:
        """Tabulate from ``start`` to ``end`` (inclusive, padded by one step each side)."""
        step = step_minutes * 60.0
        t0 = float(to_unix(start)) - step
        n = int(np.ceil((float(to_unix(end)) + step - t0) / step)) + 1
        u = t0 + step * np.arange(n)
        t = unix_to_time(ts, u)
        ra, dec, _ = eph["earth"].at(t).observe(eph["sun"]).apparent().radec(epoch="date")
        gha = (t.gast - ra.hours) * 15.0
        return cls(t0=t0, step=step, gha_unwrapped=np.unwrap(gha, period=360.0), dec=dec.degrees)

    @property
    def t_end(self) -> float:
        return self.t0 + self.step * (self.dec.size - 1)

    def at(self, unix_seconds: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Linearly interpolated (GHA mod 360, δ) in degrees."""
        u = np.asarray(unix_seconds, dtype=np.float64)
        if u.size and (u.min() < self.t0 or u.max() > self.t_end):
            raise ValueError("time outside the SunTable range")
        x = (u - self.t0) / self.step
        i = np.clip(np.floor(x).astype(np.int64), 0, self.dec.size - 2)
        f = x - i
        gha = self.gha_unwrapped[i] * (1 - f) + self.gha_unwrapped[i + 1] * f
        dec = self.dec[i] * (1 - f) + self.dec[i + 1] * f
        return np.mod(gha, 360.0), dec


def solar_altitude_deg(
    lat_deg: np.ndarray, lon_deg: np.ndarray, gha_deg: np.ndarray, dec_deg: np.ndarray
) -> np.ndarray:
    """Geometric solar altitude (degrees); all inputs broadcast together."""
    phi = np.radians(lat_deg)
    dec = np.radians(dec_deg)
    h = np.radians(np.asarray(gha_deg) + np.asarray(lon_deg))
    s = np.sin(phi) * np.sin(dec) + np.cos(phi) * np.cos(dec) * np.cos(h)
    return np.degrees(np.arcsin(np.clip(s, -1.0, 1.0)))
