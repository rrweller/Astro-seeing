"""The per-place file ``place-<id>.json`` (schema ``f1-place/1``): a direct
serialisation of ``Tonight`` plus the hourly rows, the models and the Moon.

Ticket #51 fills the place, the 24 hourly rows (time, the Sun's altitude and class, and
every model's values or the reason it has none), the models and provenance. Ticket #63
adds the verdict: :func:`hour_table` turns the store's hours into ``tonight()``'s
``HourTable``, and the file's ``tonight``, ``moon`` and each hour's agreement, past and
counted flags and Moon altitude are ``tonight()``'s and ``moon_track``'s results as
they are (D84): nothing here re-derives a verdict rule.

Tonight's 24 hours and the Sun's altitude at each come from ``forecast.tonight``'s
``sun_track`` (ticket #53), which also decides which Night is Tonight.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from astroseeing.forecast.settings import ForecastSettings, Model, Place
from astroseeing.forecast.store import PlaceHours, utc_text
from astroseeing.forecast.tonight import (
    HourTable,
    HourValue,
    Missing,
    ModelHours,
    RunInfo,
    SunTrack,
    moon_track,
    tonight,
)
from astroseeing.forecast.tonight.sun import SUNRISE_ALTITUDE_DEG

SCHEMA = "f1-place/1"
#: Sun classes by altitude at hh:00 (D48 item 1), lower bounds in degrees.
SUN_CLASSES = (
    (SUNRISE_ALTITUDE_DEG, "day"),
    (-6.0, "civil_twilight"),
    (-12.0, "nautical_twilight"),
    (-18.0, "astronomical_twilight"),
)


def sun_class(altitude_deg: float) -> str:
    for lower, name in SUN_CLASSES:
        if altitude_deg >= lower:
            return name
    return "dark"


#: The Cₙ² model whose free-atmosphere J the verdict uses (D47's headline, D48 item 7).
VERDICT_CN2 = "osborn_sarazin"


def hour_table(night: dt.date, hours: PlaceHours, models: Sequence[Model]) -> HourTable:
    """``tonight()``'s input from the store's hours: each model's unrounded total cloud and
    O&S free-atmosphere J per hour, or the stored reason it has none, and its run."""
    table = []
    for m in models:
        run = hours.runs[m.id]
        info = None
        if run is not None:
            run_time = dt.datetime.fromisoformat(run["run_time"].replace("Z", "+00:00"))
            info = RunInfo(run["run_id"], run_time)
        values = tuple(_hour_value(v) for v in hours.values[m.id])
        table.append(ModelHours(m.id, m.family, m.regional, info, values))
    return HourTable(night, tuple(hours.hours), tuple(table))


def _hour_value(value: Mapping) -> HourValue | Missing:
    if "missing" in value:
        return Missing(value["missing"])
    return HourValue(value["cloud"]["total_pct"], value["cn2"][VERDICT_CN2]["j_free"])


def build_place_file(
    place: Place,
    models: Sequence[Model],
    hours: PlaceHours,
    sun: SunTrack,
    now: dt.datetime,
    settings: ForecastSettings,
    ephemeris,
    commit: str,
) -> dict[str, Any]:
    """The place file at ``now`` for ``hours`` (Tonight's 24 hours, from
    ``PlaceStore.hours_for`` on ``sun.hours``), with ``tonight()``'s verdict and the
    Moon. ``ephemeris`` is ``solar.sun.load_ephemeris()``'s (eph, ts)."""
    if place.height is None:
        raise ValueError(f"{place.id} has no ground height")
    if tuple(hours.hours) != sun.hours:
        raise ValueError("the stored hours and the Sun are for different rows")
    verdict = tonight(
        hour_table(sun.night, hours, models),
        sun,
        now,
        cloud_classes=settings.cloud_classes,
        stale_after_h=settings.run_rules.stale_after_h,
    )
    moon = moon_track(place.lat, place.lon, sun, *ephemeris)
    rows = []
    for k, t in enumerate(hours.hours):
        alt = float(sun.altitude_deg[k])
        row = verdict.hours[k]
        rows.append(
            {
                "time": utc_text(t),
                "sun_altitude_deg": alt,
                "sun_class": sun_class(alt),
                "moon_altitude_deg": moon.altitude_deg[k],
                "past": row.past,
                "counted": row.counted,
                "agreement": row.agreement._asdict(),
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
        "tonight": verdict.to_json(),
        "hours": rows,
        "models": model_info,
        "moon": moon.to_json(),
        "provenance": {
            "commit": commit,
            "config_hash": settings.config_hash,
            "run_ids": run_ids,
        },
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
