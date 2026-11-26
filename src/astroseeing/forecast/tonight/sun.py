"""The Sun over Tonight: ``sun_track`` builds a ``SunTrack`` from the Skyfield-based solar
module (spec Module 5).

- **Which Night:** Tonight is the Night (local mean solar noon to the next one, named by
  its evening date) that has not yet reached its sunrise; from sunrise on, it is the Night
  that begins at the coming noon (``CONTEXT.md``).
- **Rows:** the 24 hh:00 UTC times from the Night's start, with the Sun's geometric
  altitude at each (the solar module's convention: no refraction; D48 item 1 classes an
  hour by the altitude at hh:00).
- **Sunset and sunrise:** a 1-minute scan of the altitude against -0.833° (the Sun's
  centre when its upper limb meets the horizon, with standard refraction), each crossing
  placed by linear interpolation between the bracketing minutes.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np

from astroseeing.forecast.tonight.shapes import HOURS_PER_NIGHT, SunTrack
from astroseeing.solar.sun import UNIX_EPOCH, solar_altitude_deg, sun_gha_dec, to_unix

#: The Sun's centre at sunrise and sunset, degrees (34′ refraction + 16′ radius).
SUNRISE_ALTITUDE_DEG = -0.833
_DAY = dt.timedelta(days=1)


def night_start(evening: dt.date, lon_deg: float) -> dt.datetime:
    """Local mean solar noon on ``evening``: 12:00 UTC - λ/15 h (λ east-positive)."""
    noon = dt.datetime(evening.year, evening.month, evening.day, 12, tzinfo=dt.UTC)
    return noon - dt.timedelta(hours=lon_deg / 15.0)


def sun_track(lat_deg: float, lon_deg: float, now: dt.datetime, eph, ts) -> SunTrack:
    """The Sun over Tonight at a place, as seen at ``now`` (UTC)."""
    if now.tzinfo is None or now.utcoffset() != dt.timedelta(0):
        raise ValueError(f"now must be a timezone-aware UTC datetime, got {now!r}")
    days = (now - night_start(dt.date(1970, 1, 1), lon_deg)).total_seconds() / 86400.0
    evening = dt.date(1970, 1, 1) + dt.timedelta(days=math.floor(days))
    track = _night(lat_deg, lon_deg, evening, eph, ts)
    if now >= track.sunrise:
        track = _night(lat_deg, lon_deg, evening + dt.timedelta(days=1), eph, ts)
    return track


def crossings(times_unix: np.ndarray, values: np.ndarray, level: float) -> list[tuple[float, bool]]:
    """Every time ``values`` crosses ``level`` between samples: (unix time, rising),
    each placed by linear interpolation within its bracket."""
    above = values >= level
    out = []
    for i in np.flatnonzero(above[1:] != above[:-1]):
        v0, v1 = values[i], values[i + 1]
        f = (level - v0) / (v1 - v0)
        out.append(
            (float(times_unix[i] + f * (times_unix[i + 1] - times_unix[i])), bool(above[i + 1]))
        )
    return out


def from_unix(u: float) -> dt.datetime:
    return UNIX_EPOCH + dt.timedelta(seconds=u)


def _night(lat_deg: float, lon_deg: float, evening: dt.date, eph, ts) -> SunTrack:
    start = night_start(evening, lon_deg)
    end = start + _DAY
    first = start.replace(minute=0, second=0, microsecond=0)
    if first < start:
        first += dt.timedelta(hours=1)
    hours = tuple(first + dt.timedelta(hours=i) for i in range(HOURS_PER_NIGHT))

    def altitude(u: np.ndarray) -> np.ndarray:
        gha, dec = sun_gha_dec(u, eph, ts)
        return solar_altitude_deg(lat_deg, lon_deg, gha, dec)

    row_alts = altitude(np.array([float(to_unix(t)) for t in hours]))
    minutes = float(to_unix(start)) + 60.0 * np.arange(24 * 60 + 1)
    events = crossings(minutes, altitude(minutes), SUNRISE_ALTITUDE_DEG)
    sets = [u for u, rising in events if not rising]
    if not sets:
        raise ValueError(f"no sunset in the Night of {evening} at {lat_deg}, {lon_deg}: "
                         "places without one are outside F1 (spec, Out of Scope)")  # fmt: skip
    rises = [u for u, rising in events if rising and u > sets[0]]
    if not rises:
        raise ValueError(f"no sunrise after sunset in the Night of {evening} at "
                         f"{lat_deg}, {lon_deg}")  # fmt: skip
    return SunTrack(
        night=evening,
        start=start,
        end=end,
        hours=hours,
        altitude_deg=tuple(float(a) for a in row_alts),
        sunset=from_unix(sets[0]),
        sunrise=from_unix(rises[0]),
    )
