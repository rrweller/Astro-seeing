"""Synthetic days of stored runs for the per-place daily stores (ticket #59).

Each run's document is made the way the tick makes it: a synthetic column at the
place (the model's own pressure levels on the 1976 standard atmosphere, a jet, random
cloud and fog where the model has the signal) goes through ``column_products`` and
``run_document``. The manifest rows are made through ``ForecastRecords``, so a test
can put each run in the state it needs.
"""

from __future__ import annotations

import datetime as dt
import zlib

import numpy as np

from astroseeing.forecast.column import column_products
from astroseeing.forecast.settings import FOG_SIGNALS, ForecastSettings
from astroseeing.forecast.sources import RunFields, RunRef
from astroseeing.forecast.store import PlaceStore, run_document
from astroseeing.forecast.verify import ForecastRecords
from astroseeing.synthetic import jet_wind, std_atmosphere_height, std_atmosphere_temperature

COMMIT = "b" * 40
SOFTWARE = {"astroseeing": "0.1.0"}


def run_doc(
    settings: ForecastSettings,
    place_id: str,
    model_id: str,
    run_time: dt.datetime,
    run_id: int,
    missing: dict[int, str] | None = None,
    ground_m: float | None = None,
) -> dict:
    """One run's stored values at a saved place, as the tick would store them. The
    model's ground is ``ground_m``, or 60 m below the place by default."""
    missing = missing or {}
    model, place = settings.models[model_id], settings.places[place_id]
    steps = model.steps_h
    levels = np.array(model.pressure_levels_hpa)
    rng = np.random.default_rng(zlib.crc32(f"{place_id}{model_id}{run_time}".encode()))
    ns, nl = len(steps), len(levels)
    z = std_atmosphere_height(levels) + rng.normal(0, 20, (ns, 1, 1, nl))
    u, v = jet_wind(z)
    ground = place.height.metres - 60.0 if ground_m is None else ground_m
    sp = 1013.25 * (1 - 2.25577e-5 * ground) ** 5.25588
    sfc = (ns, 1, 1)
    run = RunRef(model_id, run_time)
    fields = RunFields(
        run=run,
        model=model,
        lat=np.array([[place.lat]]),
        lon=np.array([[place.lon]]),
        valid_times=np.array(
            [run_time.replace(tzinfo=None) + dt.timedelta(hours=s) for s in steps],
            dtype="datetime64[s]",
        ),
        pressure_hpa=levels,
        geopotential_height_m=z,
        temperature_k=std_atmosphere_temperature(z) + rng.normal(0, 1, z.shape),
        u_ms=u + rng.normal(0, 3, z.shape),
        v_ms=v + rng.normal(0, 3, z.shape),
        level_cloud_pct=rng.uniform(0, 100, z.shape) if model.level_cloud else None,
        total_cloud_pct=rng.uniform(0, 100, sfc),
        low_cloud_pct=rng.uniform(0, 100, sfc),
        mid_cloud_pct=rng.uniform(0, 100, sfc),
        high_cloud_pct=rng.uniform(0, 100, sfc),
        surface_pressure_hpa=np.full(sfc, sp),
        model_ground_m=np.array([[ground]]),
        fog={
            name: rng.uniform(0, 30000, sfc) if name in model.fog_signals else None
            for name in FOG_SIGNALS
        },
    )
    products = column_products(fields, observer_height_m=place.height.metres)
    provenance = {
        "commit": COMMIT,
        "config_hash": settings.config_hash,
        "manifest_run_id": run_id,
        "software": SOFTWARE,
    }
    return run_document(
        place,
        fields,
        (0, 0),
        products,
        [s for s in steps if s not in missing],
        missing,
        run_id,
        f"{model.name}: credit line",
        settings.cloud_classes,
        provenance,
    )


def day_runs(settings: ForecastSettings, place_id: str, day: dt.date):
    """Every (model, run time) a saved place's area expects on a UTC day."""
    area = settings.areas[settings.places[place_id].area]
    start = dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC)
    for model_id in area.models:
        for hour in settings.models[model_id].runs_utc:
            yield model_id, start + dt.timedelta(hours=hour)


def store_day(
    settings: ForecastSettings,
    records: ForecastRecords,
    store: PlaceStore,
    place_id: str,
    day: dt.date,
    state: str = "processed",
    except_runs: tuple[tuple[str, int], ...] = (),
    at: dt.datetime | None = None,
) -> dict[tuple[str, dt.datetime], dict]:
    """Record every run of the day in ``state`` and store its values on the SSD, but for
    ``except_runs`` ((model, hour) pairs: recorded ``seen``, nothing stored)."""
    area = settings.places[place_id].area
    at = at or dt.datetime.combine(day, dt.time(23), tzinfo=dt.UTC)
    docs = {}
    for model_id, run_time in day_runs(settings, place_id, day):
        steps = settings.models[model_id].steps_h
        run_id = records.seen(model_id, area, run_time, steps, at=at)
        if (model_id, run_time.hour) in except_runs:
            continue
        doc = run_doc(settings, place_id, model_id, run_time, run_id)
        stored = store.put_run(doc)
        finish(records, run_id, state, at, stored.bytes)
        docs[(model_id, run_time)] = store.read_run(stored.path)
    return docs


def finish(records: ForecastRecords, run_id: int, state: str, at: dt.datetime, nbytes=1) -> None:
    """Move a recorded run to a final ``state`` (``processed``, ``abandoned``, ...)."""
    run = records.get(run_id)
    steps = {s: "ok" for s in run.steps_expected}
    records.transition(run_id, (run.state,), state, at=at, steps_verified=steps,
                       derived_bytes=nbytes)  # fmt: skip
