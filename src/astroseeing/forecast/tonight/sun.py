"""The Sun over Tonight: ``sun_track`` builds a ``SunTrack`` from the Skyfield-based solar
module (spec Module 5).

- **Which Night:** Tonight is the Night (local mean solar noon to the next one, named by
  its evening date) that has not yet reached its sunrise; from sunrise on, it is the Night
  that begins at the coming noon (``CONTEXT.md``).
- **Rows:** the 24 hh:00 UTC times from the Night's start, with the Sun's geometric
  altitude at each (the solar module's convention: no refraction; D48 item 1 classes an
  hour by the altitude at hh:00).
- **Map cells** (ticket #65): ``cell_suns`` gives every cell of a grid its
  ``sun_track``, asking Skyfield once for all the grid's distinct times, and the minutes
  of dark time left.
- **Sunset and sunrise:** a 1-minute scan of the altitude against -0.833° (the Sun's
  centre when its upper limb meets the horizon, with standard refraction), each crossing
  placed by linear interpolation between the bracketing minutes.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from astroseeing.forecast.tonight.shapes import HOURS_PER_NIGHT, SunTrack, check_utc
from astroseeing.solar.sun import UNIX_EPOCH, solar_altitude_deg, sun_gha_dec, to_unix

#: The Sun's centre at sunrise and sunset, degrees (34′ refraction + 16′ radius).
SUNRISE_ALTITUDE_DEG = -0.833
#: The Sun's altitude below which it is dark time (astronomical darkness), degrees.
DARK_ALTITUDE_DEG = -18.0
_DAY = dt.timedelta(days=1)


def night_start(evening: dt.date, lon_deg: float) -> dt.datetime:
    """Local mean solar noon on ``evening``: 12:00 UTC - λ/15 h (λ east-positive)."""
    noon = dt.datetime(evening.year, evening.month, evening.day, 12, tzinfo=dt.UTC)
    return noon - dt.timedelta(hours=lon_deg / 15.0)


def sun_track(lat_deg: float, lon_deg: float, now: dt.datetime, eph, ts) -> SunTrack:
    """The Sun over Tonight at a place, as seen at ``now`` (UTC)."""
    return cell_suns((lat_deg,), (lon_deg,), now, eph, ts)[0][0].track


@dataclass(frozen=True)
class CellSun:
    """The Sun over Tonight at one map cell: its ``SunTrack`` and the minutes of dark
    time (Sun below -18°) left in Tonight from ``now`` on (ticket #65)."""

    track: SunTrack
    dark_left_min: int


def cell_suns(
    lats_deg: Sequence[float], lons_deg: Sequence[float], now: dt.datetime, eph, ts
) -> list[list[CellSun]]:
    """The Sun over Tonight at every cell of a lat-lon grid (``[row][column]``), as seen
    at ``now`` (UTC); each cell's track is ``sun_track(lat, lon, now)``'s.

    The Sun's position over a Night depends only on time, and every cell of a Night at
    one longitude samples the same times, so it is asked of Skyfield once for all the
    distinct times of all the grid's Nights (the Kongsberg map's 160 meridians share
    ~6000 times, against ~234 000 one meridian at a time); each cell then takes its own
    altitudes, events and Tonight from it.

    **Dark time left** counts the scan's minutes of Tonight (from its start, the last
    minute before its end) at or after ``now`` with the Sun below -18°.
    """
    check_utc("now", now)
    lats, lons = [float(x) for x in lats_deg], [float(x) for x in lons_deg]
    evening = {lon: _evening(now, lon) for lon in lons}
    nights = _night_suns({(lon, evening[lon]) for lon in lons}, eph, ts)
    out: list[list[CellSun | None]] = []
    later = []  # cells at or after their Night's sunrise: Tonight is the coming Night
    for i, lat in enumerate(lats):
        row = []
        for j, lon in enumerate(lons):
            sun = nights[lon, evening[lon]]
            track, minute_alts = _track(lat, lon, sun)
            if now >= track.sunrise:
                later.append((i, j))
                row.append(None)
            else:
                row.append(CellSun(track, _dark_left_min(sun.minutes, minute_alts, now)))
        out.append(row)
    if later:
        nights.update(_night_suns({(lons[j], evening[lons[j]] + _DAY) for _, j in later}, eph, ts))
        for i, j in later:
            sun = nights[lons[j], evening[lons[j]] + _DAY]
            track, minute_alts = _track(lats[i], lons[j], sun)
            out[i][j] = CellSun(track, _dark_left_min(sun.minutes, minute_alts, now))
    return out


def _evening(now: dt.datetime, lon_deg: float) -> dt.date:
    """The evening date of the Night (local mean noon to noon) that holds ``now``."""
    days = (now - night_start(dt.date(1970, 1, 1), lon_deg)).total_seconds() / 86400.0
    return dt.date(1970, 1, 1) + dt.timedelta(days=math.floor(days))


def _dark_left_min(minutes: np.ndarray, altitudes: np.ndarray, now: dt.datetime) -> int:
    left = (minutes[:-1] >= float(to_unix(now))) & (altitudes[:-1] < DARK_ALTITUDE_DEG)
    return int(left.sum())


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


def night_minutes(start: dt.datetime) -> np.ndarray:
    """Unix times of every minute of the Night from ``start``, both ends included."""
    return float(to_unix(start)) + 60.0 * np.arange(24 * 60 + 1)


def from_unix(u: float) -> dt.datetime:
    return UNIX_EPOCH + dt.timedelta(seconds=u)


@dataclass(frozen=True, eq=False)
class _NightSun:
    """Where the Sun is over one Night for one longitude: its Greenwich hour angle and
    declination at the Night's 24 rows and at each minute of its 1-minute scan."""

    evening: dt.date
    start: dt.datetime
    end: dt.datetime
    hours: tuple[dt.datetime, ...]
    rows: tuple[np.ndarray, np.ndarray]
    minutes: np.ndarray
    at_minutes: tuple[np.ndarray, np.ndarray]


def _night_suns(
    nights: set[tuple[float, dt.date]], eph, ts
) -> dict[tuple[float, dt.date], _NightSun]:
    """The Sun over each (longitude, evening) Night, from one Skyfield call over all
    their distinct times (rows and scan minutes)."""
    parts = {}
    for lon, evening in nights:
        start = night_start(evening, lon)
        first = start.replace(minute=0, second=0, microsecond=0)
        if first < start:
            first += dt.timedelta(hours=1)
        hours = tuple(first + dt.timedelta(hours=i) for i in range(HOURS_PER_NIGHT))
        rows = np.array([float(to_unix(t)) for t in hours])
        parts[lon, evening] = (start, hours, rows, night_minutes(start))
    times = np.unique(np.concatenate([u for p in parts.values() for u in p[2:]]))
    gha, dec = sun_gha_dec(times, eph, ts)

    def at(u: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        k = np.searchsorted(times, u)
        return gha[k], dec[k]

    return {
        key: _NightSun(key[1], start, start + _DAY, hours, at(rows), minutes, at(minutes))
        for key, (start, hours, rows, minutes) in parts.items()
    }


def _track(lat_deg: float, lon_deg: float, sun: _NightSun) -> tuple[SunTrack, np.ndarray]:
    """The SunTrack at one latitude of the Night ``sun``, and the Sun's altitude at each
    minute of the scan."""
    row_alts = solar_altitude_deg(lat_deg, lon_deg, *sun.rows)
    minute_alts = solar_altitude_deg(lat_deg, lon_deg, *sun.at_minutes)
    events = crossings(sun.minutes, minute_alts, SUNRISE_ALTITUDE_DEG)
    evening = sun.evening
    sets = [u for u, rising in events if not rising]
    if not sets:
        raise ValueError(f"no sunset in the Night of {evening} at {lat_deg}, {lon_deg}: "
                         "places without one are outside F1 (spec, Out of Scope)")  # fmt: skip
    rises = [u for u, rising in events if rising and u > sets[0]]
    if not rises:
        raise ValueError(f"no sunrise after sunset in the Night of {evening} at "
                         f"{lat_deg}, {lon_deg}")  # fmt: skip
    track = SunTrack(
        night=evening,
        start=sun.start,
        end=sun.end,
        hours=sun.hours,
        altitude_deg=tuple(float(a) for a in row_alts),
        sunset=from_unix(sets[0]),
        sunrise=from_unix(rises[0]),
    )
    return track, minute_alts
