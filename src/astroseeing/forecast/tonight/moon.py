"""The Moon over Tonight: rise, set, phase and hourly altitude (D43 item 7; spec Module 5).

Same ephemeris as the Sun (DE440s, through ``solar.sun.load_ephemeris``). No
sky-brightness model: "not now: moonlight" still applies to the historical layers.

- **Altitude** at each hh:00 row: topocentric, apparent, without refraction.
- **Rise and set:** the first of each within Tonight (local mean noon to noon), from a
  1-minute scan, each placed by linear interpolation between the bracketing minutes. The
  event is the Moon's upper limb at the horizon with 34′ of refraction (USNO's
  definition, as Skyfield's almanac uses): its centre at -34′ minus its apparent radius.
  ``None`` when the Moon does not rise (or set) during Tonight.
- **Phase** at the middle of the Night (local mean midnight): the geocentric apparent
  ecliptic longitude of the Moon minus that of the Sun, 0-360° (0 new, 180 full), and
  the illuminated fraction (1 + cos i)/2 from the phase angle i at the Moon (astrometric
  positions, Skyfield's definition).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import numpy as np

from astroseeing.forecast.tonight.shapes import SunTrack
from astroseeing.forecast.tonight.sun import crossings, from_unix
from astroseeing.solar.sun import to_unix, unix_to_time

MOON_RADIUS_M = 1.7374e6  # IAU mean radius, as Skyfield's almanac
REFRACTION_DEG = 34.0 / 60.0


@dataclass(frozen=True)
class MoonTrack:
    hours: tuple[dt.datetime, ...]  # Tonight's rows (the SunTrack's)
    altitude_deg: tuple[float, ...]
    rise: dt.datetime | None
    set: dt.datetime | None
    phase_deg: float
    illuminated_fraction: float

    def to_json(self) -> dict:
        """The per-place file's ``moon`` block (schema ``f1-place/1``)."""
        return {
            "rise": _utc(self.rise),
            "set": _utc(self.set),
            "phase_deg": self.phase_deg,
            "illuminated_fraction": self.illuminated_fraction,
        }


def moon_track(lat_deg: float, lon_deg: float, sun: SunTrack, eph, ts) -> MoonTrack:
    """The Moon over the Night that ``sun`` describes, at a place."""
    from skyfield.api import wgs84
    from skyfield.framelib import ecliptic_frame

    site = eph["earth"] + wgs84.latlon(lat_deg, lon_deg)
    moon = eph["moon"]

    def topocentric(u: np.ndarray):
        alt, _, dist = site.at(unix_to_time(ts, u)).observe(moon).apparent().altaz()
        return alt.degrees, dist.m

    rows = np.array([float(to_unix(t)) for t in sun.hours])
    row_alts, _ = topocentric(rows)

    minutes = float(to_unix(sun.start)) + 60.0 * np.arange(24 * 60 + 1)
    alt, dist = topocentric(minutes)
    # Centre altitude when the upper limb touches the horizon, per minute; scan the
    # altitude above that line for its zero crossings.
    horizon = -REFRACTION_DEG - np.degrees(np.arcsin(MOON_RADIUS_M / dist))
    events = crossings(minutes, alt - horizon, 0.0)
    rise = next((u for u, rising in events if rising), None)
    set_ = next((u for u, rising in events if not rising), None)

    t = unix_to_time(ts, np.array([float(to_unix(sun.start + dt.timedelta(hours=12)))]))
    earth = eph["earth"].at(t)
    m_astrometric = earth.observe(moon)
    _, mlon, _ = m_astrometric.apparent().frame_latlon(ecliptic_frame)
    _, slon, _ = earth.observe(eph["sun"]).apparent().frame_latlon(ecliptic_frame)
    phase = float((mlon.degrees[0] - slon.degrees[0]) % 360.0)
    if phase == 360.0:  # a difference of -1e-14° rounds to 360.0: the same angle as 0°
        phase = 0.0
    i = float(m_astrometric.phase_angle(eph["sun"]).radians[0])  # Skyfield's definition

    return MoonTrack(
        hours=sun.hours,
        altitude_deg=tuple(float(a) for a in row_alts),
        rise=None if rise is None else from_unix(rise),
        set=None if set_ is None else from_unix(set_),
        phase_deg=phase,
        illuminated_fraction=0.5 * (1.0 + math.cos(i)),
    )


def _utc(t: dt.datetime | None) -> str | None:
    return None if t is None else t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
