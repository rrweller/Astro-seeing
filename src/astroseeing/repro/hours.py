"""Hour sets for the reproductions (D57 item 3; CONTEXT.md "Night mask", "Dark time").

Each selector takes the hourly sample times (``datetime64``, UTC) and returns a bool
array, one per time, for ``SiteColumns.select``:

* :func:`all_hours`: every hour (Haslebacher, Priyatikanto, Bi);
* :func:`night_mask`: the ingest rule (D8): the Sun below −12° at any minute of the
  hour centred on the sample (Bi);
* :func:`dark_time`: the Sun below −18° at the sample time, on listed nights only
  (O&S: the 79 Appendix B nights; −12° as a sensitivity);
* :func:`solar_time_window`: local mean solar time within a window (Bi's balloon
  launch windows, 04–07 h and 19–23 h).

Solar positions come from :mod:`astroseeing.solar` (DE440s, geometric altitude).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import numpy as np

from astroseeing.solar.darkness import ASTRONOMICAL, night_hours_to_keep, night_start_unix
from astroseeing.solar.sun import SunTable, solar_altitude_deg, to_unix


def _unix(times: np.ndarray) -> np.ndarray:
    t = np.asarray(times)
    if not np.issubdtype(t.dtype, np.datetime64):
        raise TypeError(f"times must be datetime64 (UTC), got {t.dtype}")
    return to_unix(t.astype("datetime64[s]"))


def _sun_for(unix_s: np.ndarray, sun: SunTable | None) -> SunTable:
    if sun is not None:
        return sun
    from astroseeing.solar.sun import load_ephemeris

    eph, ts = load_ephemeris()
    start = dt.datetime.fromtimestamp(float(unix_s.min()), dt.UTC) - dt.timedelta(hours=2)
    end = dt.datetime.fromtimestamp(float(unix_s.max()), dt.UTC) + dt.timedelta(hours=2)
    return SunTable.build(start, end, eph, ts)


def all_hours(times: np.ndarray) -> np.ndarray:
    """Every hour."""
    return np.ones(_unix(times).shape, dtype=bool)


def night_mask(
    times: np.ndarray, lat: float, lon: float, sun: SunTable | None = None
) -> np.ndarray:
    """The night mask (D8): the Sun below −12° at any minute in [t − 30 min, t + 30 min)."""
    t = _unix(times)
    if t.size == 0:
        return np.zeros(0, dtype=bool)
    return night_hours_to_keep(np.array([lat]), np.array([lon]), t, _sun_for(t, sun))[0]


def dark_time(
    times: np.ndarray,
    lat: float,
    lon: float,
    nights: Sequence[dt.date | str | np.datetime64],
    sun: SunTable | None = None,
    threshold_deg: float = ASTRONOMICAL,
) -> np.ndarray:
    """Hours of the listed nights whose sample has the Sun below ``threshold_deg``.

    ``nights`` are evening dates; a night runs from local mean noon to the next local
    mean noon at ``lon`` (CONTEXT.md "Night"). The altitude is the Sun's at the sample
    time itself, since a reanalysis hour is compared with measurements at that time.
    Only the default −18° is Dark time as CONTEXT.md defines it; −12° is O&S's
    sensitivity variant (D57 item 3) and should be named as such in results.
    """
    t = _unix(times)
    if t.size == 0:
        return np.zeros(0, dtype=bool)
    dates = np.array([np.datetime64(str(d), "D") for d in nights], dtype="datetime64[D]")
    starts = night_start_unix(dates, np.array([lon]))[0]
    in_listed = np.zeros(t.shape, dtype=bool)
    for s in starts:
        in_listed |= (t >= s) & (t < s + 86400.0)
    gha, dec = _sun_for(t, sun).at(t)
    return in_listed & (solar_altitude_deg(lat, lon, gha, dec) < threshold_deg)


def solar_time_window(times: np.ndarray, lon: float, start_h: float, end_h: float) -> np.ndarray:
    """Hours whose local mean solar time (UTC + lon/15 h) is in [start_h, end_h].

    Both ends are included. A window with ``start_h > end_h`` wraps midnight.
    """
    t = _unix(times)
    lmst = ((t + lon / 15.0 * 3600.0) % 86400.0) / 3600.0
    if start_h <= end_h:
        return (lmst >= start_h) & (lmst <= end_h)
    return (lmst >= start_h) | (lmst <= end_h)
