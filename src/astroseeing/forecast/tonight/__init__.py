"""Tonight (F1 spec Module 5): the single, pure implementation of the verdict rules
(D48). The per-place file, the map layers and the cell cards all come from it, so the map
and the table can't disagree; the browser never re-derives a rule.

- ``tonight(hours, sun, now, cloud_classes=..., stale_after_h=...) -> Tonight``: the rules;
- ``HourTable`` and ``SunTrack``: its inputs (``shapes``); ``sun_track`` builds the
  SunTrack for Tonight at a place from the Skyfield-based solar module;
- ``moon_track``: the Moon's rise, set, phase and hourly altitude, same ephemeris.
"""

from astroseeing.forecast.tonight.moon import MoonTrack, moon_track
from astroseeing.forecast.tonight.rules import (
    Agreement,
    Chip,
    HourVerdict,
    MepsLine,
    NothingToCount,
    RunAge,
    SeeingRange,
    Tonight,
    cloud_class,
    tonight,
)
from astroseeing.forecast.tonight.shapes import (
    HourTable,
    HourValue,
    Missing,
    ModelHours,
    RunInfo,
    SunTrack,
)
from astroseeing.forecast.tonight.sun import sun_track

__all__ = [
    "Agreement",
    "Chip",
    "HourTable",
    "HourValue",
    "HourVerdict",
    "MepsLine",
    "Missing",
    "ModelHours",
    "MoonTrack",
    "NothingToCount",
    "RunAge",
    "RunInfo",
    "SeeingRange",
    "SunTrack",
    "Tonight",
    "cloud_class",
    "moon_track",
    "sun_track",
    "tonight",
]
