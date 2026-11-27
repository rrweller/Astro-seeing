"""Hand-made nights at Kongsberg as the tick would publish them (ticket #63).

``place_file`` builds a per-place file with the real settings (all four forecast
models of the Kongsberg box) through the tick's own ``build_place_file``, from stored
values written here by hand instead of fetched: each model's run time and, per hour,
its total cloud or the reason it has none. So the page's tests can show nights the
saved samples don't have (four models, June, the end of dark time) with the verdict
``tonight()`` really gives for them.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping

from astroseeing.forecast.publish.place_file import build_place_file
from astroseeing.forecast.settings import default_settings_path, load_settings
from astroseeing.forecast.store import PlaceHours, utc_text
from astroseeing.forecast.tonight import sun_track
from astroseeing.physics.optics import j_from_seeing

SETTINGS = load_settings(default_settings_path())
PLACE = SETTINGS.places["kongsberg"]
MODELS = [SETTINGS.models[m] for m in SETTINGS.areas[PLACE.area].models]
COMMIT = "a" * 40
RUN_IDS = {"gfs": 11, "icon_eu": 12, "meps": 13, "ifs": 14}
GROUND_M = {"gfs": 327.4, "icon_eu": 346.9, "meps": 255.0, "ifs": 301.2}
#: Each model's gap from its ground to its first usable pressure level, m.
GAP_M = {"gfs": 137.0, "icon_eu": 352.0, "meps": 548.0, "ifs": 561.0}
CREDITS = {
    "gfs": "GFS: NOAA/NCEP (US government open data); not endorsed by NOAA",
    "icon_eu": "ICON-EU: Deutscher Wetterdienst (CC BY 4.0), seeing added by us",
    "meps": "MEPS: based on data from MET Norway (NLOD, CC BY 4.0)",
    "ifs": "IFS: ECMWF open data (CC BY 4.0), seeing added by us",
}

#: Each model's free-atmosphere seeing (O&S) on every hour it has a value, arcsec.
SEEING = {"gfs": 0.62, "icon_eu": 0.81, "meps": 0.70, "ifs": 0.55}

#: Fog signals on every hour a model has values, but at ``FOGGY_HOUR`` UTC; a signal
#: the model doesn't have (D49 item 3, ``fog_signals`` in the settings) is "absent".
FOG = {
    "fog_fraction_pct": 0.0,
    "visibility_m": 24000.0,
    "weather_code": 0.0,
    "dewpoint_depression_2m_k": 3.1,
}
FOGGY_HOUR = 6  # an hour every model has a step for, IFS included
FOGGY = {
    "fog_fraction_pct": 82.5,
    "visibility_m": 350.0,
    "weather_code": 45.0,
    "dewpoint_depression_2m_k": 0.2,
}

#: A model's total cloud (%) at an hour, or why it has none ("partial", ...).
Cloud = Callable[[str, dt.datetime], float | str]


def _fog(model, t: dt.datetime) -> dict:
    values = FOGGY if t.hour == FOGGY_HOUR else FOG
    return {name: values[name] if name in model.fog_signals else "absent" for name in FOG}


def _step(model, t: dt.datetime, total: float) -> dict:
    fa = SEEING[model.id]
    seeing = {
        "j_total": float(j_from_seeing(fa * 1.4)),
        "j_free": float(j_from_seeing(fa)),
        "hbar_m": 5200.0,
        "seeing_total_arcsec": fa * 1.4,
        "seeing_free_arcsec": fa,
    }
    return {
        "cloud": {"total_pct": total, "low_pct": total, "mid_pct": 0.0, "high_pct": 0.0},
        "cloud_class": "clear" if total <= 10 else "some_cloud" if total <= 50 else "cloudy",
        "cn2": {"osborn_sarazin": seeing, "tatarskii": {**seeing, "hbar_m": 6100.0}},
        "wind_200hpa_ms": 31.5,
        "fog": _fog(model, t),
        "gap_to_first_level_m": GAP_M[model.id],
        "valid_levels": 30,
    }


def _run(model, ground: float) -> dict:
    raise_m = max(ground - PLACE.height.metres, 0.0)
    return {
        "name": model.name,
        "family": model.family,
        "regional": model.regional,
        "level_count": model.level_count,
        "credit": CREDITS[model.id],
        "model_ground_m": ground,
        "observer_height_m": PLACE.height.metres + raise_m,
        "raise_m": raise_m,
    }


def place_file(
    now: dt.datetime,
    ephemeris,
    runs: Mapping[str, dt.datetime | None],
    cloud: Cloud,
    ground_m: Mapping[str, float] | None = None,
) -> dict:
    """The Kongsberg place file at ``now``: ``runs`` gives each model's run time (None or
    absent: no run), ``cloud`` its value at each hour its run has a step for, and
    ``ground_m`` model grounds that differ from ``GROUND_M``."""
    grounds = {**GROUND_M, **(ground_m or {})}
    sun = sun_track(PLACE.lat, PLACE.lon, now, *ephemeris)
    stored_runs, values = {}, {}
    for m in MODELS:
        run_time = runs.get(m.id)
        if run_time is None:
            stored_runs[m.id] = None
            values[m.id] = ({"missing": "no_run"},) * len(sun.hours)
            continue
        stored_runs[m.id] = {
            "run_id": RUN_IDS[m.id],
            "run_time": utc_text(run_time),
            "meta": _run(m, grounds[m.id]),
        }
        row = []
        for t in sun.hours:
            step = (t - run_time) / dt.timedelta(hours=1)
            if not m.steps_h[0] <= step <= m.steps_h[-1]:
                row.append({"missing": "no_run"})
            elif int(step) not in m.steps_h:
                row.append({"missing": "off_step"})
            else:
                v = cloud(m.id, t)
                row.append({"missing": v} if isinstance(v, str) else _step(m, t, v))
        values[m.id] = tuple(row)
    hours = PlaceHours(sun.hours, stored_runs, values)
    return build_place_file(
        PLACE, MODELS, hours, sun, now, settings=SETTINGS, ephemeris=ephemeris, commit=COMMIT
    )
