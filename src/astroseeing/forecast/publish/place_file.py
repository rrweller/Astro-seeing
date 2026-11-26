"""The per-place file ``place-<id>.json`` (schema ``f1-place/1``): a direct
serialisation of ``Tonight`` plus the hourly rows, the models and the Moon.

Ticket #51 fills the place, the 24 hourly rows (time, the Sun's altitude and class, and
every model's values or the reason it has none), the models and provenance. The verdict
(``tonight``), the Moon and each hour's agreement, past and counted flags and Moon
altitude come from ``forecast.tonight`` and are null until ticket #63 (F1-14) wires it
in (D72): nothing here re-derives a verdict rule.

Which Night is Tonight, and its hours: the Night (local mean solar noon to the next) is
Tonight until its sunrise; from sunrise on, Tonight is the next Night (``CONTEXT.md``).
Sunrise is the Sun's upward crossing of -0.833° (D48 item 2), found on a 1-minute scan.
The 24 rows are the hh:00 UTC times inside Tonight.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from astroseeing.forecast.settings import Model, Place
from astroseeing.forecast.store import PlaceHours, utc_text
from astroseeing.solar.sun import solar_altitude_deg, sun_gha_dec, to_unix

SCHEMA = "f1-place/1"
HORIZON_DEG = -0.833  # the Sun "below the horizon", D48 item 2
#: Sun classes by altitude at hh:00 (D48 item 1), lower bounds in degrees.
SUN_CLASSES = (
    (HORIZON_DEG, "day"),
    (-6.0, "civil_twilight"),
    (-12.0, "nautical_twilight"),
    (-18.0, "astronomical_twilight"),
)


def night_start(evening: dt.date, lon: float) -> dt.datetime:
    """Local mean solar noon on the evening's date: 12:00 UTC − λ/15 h (λ east-positive)."""
    noon = dt.datetime(evening.year, evening.month, evening.day, 12, tzinfo=dt.UTC)
    return noon - dt.timedelta(hours=lon / 15.0)


def sun_altitudes(lat: float, lon: float, times: Sequence[dt.datetime], ephemeris) -> np.ndarray:
    """The Sun's geometric altitude (degrees) at each time, straight from Skyfield."""
    eph, ts = ephemeris
    gha, dec = sun_gha_dec(np.array([to_unix(t) for t in times]), eph, ts)
    return solar_altitude_deg(lat, lon, gha, dec)


def tonight(place: Place, now: dt.datetime, ephemeris) -> dt.date:
    """The evening date of Tonight at ``place`` (see the module docstring)."""
    evening = (now + dt.timedelta(hours=place.lon / 15.0) - dt.timedelta(hours=12)).date()
    start = night_start(evening, place.lon)
    minutes = [start + dt.timedelta(minutes=m) for m in range(24 * 60 + 1)]
    alt = sun_altitudes(place.lat, place.lon, minutes, ephemeris)
    up = np.flatnonzero((alt[:-1] < HORIZON_DEG) & (alt[1:] >= HORIZON_DEG))
    if up.size == 0:
        raise ValueError(
            f"{place.id}: no sunrise in the night of {evening}; places without "
            "sunrise or sunset are out of F1's scope"
        )
    sunrise = minutes[int(up[0]) + 1]
    return evening + dt.timedelta(days=1) if now >= sunrise else evening


def night_hours(evening: dt.date, lon: float) -> tuple[dt.datetime, ...]:
    """The 24 hh:00 UTC times inside the Night of ``evening``."""
    start = night_start(evening, lon)
    first = start.replace(minute=0, second=0, microsecond=0)
    if first < start:
        first += dt.timedelta(hours=1)
    return tuple(first + dt.timedelta(hours=k) for k in range(24))


def sun_class(altitude_deg: float) -> str:
    for lower, name in SUN_CLASSES:
        if altitude_deg >= lower:
            return name
    return "dark"


def build_place_file(
    place: Place,
    models: Sequence[Model],
    hours: PlaceHours,
    sun_altitude_deg: Sequence[float],
    config_hash: str,
    commit: str,
) -> dict[str, Any]:
    """The place file for ``hours`` (Tonight's 24 hours, from ``PlaceStore.hours_for``)."""
    if place.height is None:
        raise ValueError(f"{place.id} has no ground height")
    rows = []
    for k, t in enumerate(hours.hours):
        alt = float(sun_altitude_deg[k])
        rows.append(
            {
                "time": utc_text(t),
                "sun_altitude_deg": alt,
                "sun_class": sun_class(alt),
                "moon_altitude_deg": None,
                "past": None,
                "counted": None,
                "agreement": None,
                "models": {
                    m.id: _model_hour(hours.runs[m.id], hours.values[m.id][k]) for m in models
                },
            }
        )
    model_info, run_ids = {}, {}
    for m in models:
        run = hours.runs[m.id]
        if run is None:
            continue
        run_ids[m.id] = run["run_id"]
        model_info[m.id] = _model_info(run, hours.values[m.id])
    return {
        "schema": SCHEMA,
        "place": {
            "id": place.id,
            "name": place.name,
            "lat": place.lat,
            "lon": place.lon,
            "time_zone": place.time_zone,
            "height_m": place.height.metres,
            "height_source": place.height.source,
        },
        "tonight": None,
        "hours": rows,
        "models": model_info,
        "moon": None,
        "provenance": {"commit": commit, "config_hash": config_hash, "run_ids": run_ids},
    }


def _model_hour(run: Mapping | None, value: Mapping) -> dict:
    if "missing" in value:
        return {"missing": value["missing"]}

    def seeing(c: Mapping) -> dict:
        h = c["hbar_m"]
        return {
            "free_atmosphere_arcsec": c["seeing_free_arcsec"],
            "total_arcsec": c["seeing_total_arcsec"],
            "hbar_km": None if h is None else h / 1000.0,
        }

    return {
        "run_id": run["run_id"],
        "cloud": dict(value["cloud"]),
        "cloud_class": value["cloud_class"],
        "seeing": {name: seeing(c) for name, c in value["cn2"].items()},
        "wind_200hpa_ms": value["wind_200hpa_ms"],
        "fog": dict(value["fog"]),
    }


def _model_info(run: Mapping, values: Sequence[Mapping]) -> dict:
    meta = run["meta"]
    gaps = [
        v["gap_to_first_level_m"]
        for v in values
        if "missing" not in v and v["gap_to_first_level_m"] is not None
    ]
    raise_m = meta["raise_m"]
    return {
        "name": meta["name"],
        "family": meta["family"],
        "level_count": meta["level_count"],
        "regional": meta["regional"],
        "observer_height_m": meta["observer_height_m"],
        "raise_m": raise_m,
        # the deepest gap over Tonight's hours: the column starts at most this far up
        "gap_to_first_level_m": max(gaps) if gaps else None,
        "model_ground_m": meta["model_ground_m"],
        "terrain_caveat_m": raise_m if raise_m > 0 else None,
        "credit": meta["credit"],
    }
