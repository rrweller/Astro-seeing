"""Shared helpers for tests that use the saved GFS samples (ticket #51).

The samples are real NOMADS grib-filter responses for the 2026-11-26 06 UTC GFS run
(NOAA/NCEP, US-government open data; ``tests/fixtures/forecast/gfs/README.md``):

- ``box1deg``: 59.25-60.25° N × 9.25-10.25° E (5 × 5 points), every step 0-48;
- ``kongsberg``: the whole Kongsberg box (40 × 40 points), steps 0 and 1.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from pathlib import Path

import yaml

from astroseeing.forecast.settings import (
    Box,
    ForecastSettings,
    default_settings_path,
    load_settings,
)
from astroseeing.forecast.sources import RunRef
from astroseeing.forecast.sources.gfs import DATA_DIR, GfsAdapter

SAMPLES = Path(__file__).resolve().parent / "fixtures" / "forecast" / "gfs" / "20261126T06Z"
SAMPLE_RUN = RunRef("gfs", dt.datetime(2026, 11, 26, 6, tzinfo=dt.UTC))
BOX_1DEG = Box(west=9.2, east=10.3, south=59.2, north=60.3)


def small_box_settings(tmp_path: Path, **edits) -> ForecastSettings:
    """The real forecast settings with the Kongsberg area cut to the sample box, only
    GFS in it and no Paranal (the other models and Paranal have no samples yet);
    ``edits`` replace values by dotted path, e.g. ``{"places.kongsberg.height": None}``."""
    raw = yaml.safe_load(default_settings_path().read_text())
    raw["areas"]["kongsberg"]["box"] = dict(vars(BOX_1DEG))
    raw["areas"]["kongsberg"]["models"] = ["gfs"]
    raw["areas"]["kongsberg"]["map_grid_model"] = "gfs"
    del raw["areas"]["paranal"], raw["places"]["paranal"]  # no Paranal samples yet
    for path, value in edits.items():
        node = raw
        *head, last = path.split(".")
        for key in head:
            node = node[key]
        node[last] = value
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "forecast.yaml"
    p.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_settings(p)


def serve_samples(
    server,
    adapter: GfsAdapter,
    area,
    steps,
    sample_set: str = "box1deg",
    folder: Path | None = None,
    run: RunRef = SAMPLE_RUN,
) -> None:
    """Route every request of the adapter's plan to its saved sample, and the last
    step's two index files (what ``latest_published`` checks) to empty answers."""
    folder = folder or SAMPLES / sample_set
    for req in adapter.request_plan(run, area, tuple(steps)):
        server.route(req.target, folder / req.filename)
    day, hh = run.run_time.strftime("%Y%m%d"), run.run_time.strftime("%H")
    last = adapter.model.steps_h[-1]
    for part in ("pgrb2", "pgrb2b"):
        server.route(f"{DATA_DIR}/gfs.{day}/{hh}/atmos/gfs.t{hh}z.{part}.0p25.f{last:03d}.idx", b"")


def copy_samples(dest: Path, sample_set: str = "box1deg") -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for f in (SAMPLES / sample_set).glob("*.grb2"):
        (dest / f.name).write_bytes(f.read_bytes())
    return dest


def drop_messages(path: Path, drop: Callable[[dict], bool]) -> int:
    """Rewrite a GRIB file without the messages ``drop`` selects; returns how many went.

    ``drop`` gets the eccodes keys shortName, typeOfLevel, level and stepType.
    """
    import eccodes as ec

    kept, dropped = [], 0
    with open(path, "rb") as f:
        while (h := ec.codes_grib_new_from_file(f)) is not None:
            try:
                keys = {
                    k: ec.codes_get(h, k) for k in ("shortName", "typeOfLevel", "level", "stepType")
                }
                if drop(keys):
                    dropped += 1
                else:
                    kept.append(ec.codes_get_message(h))
            finally:
                ec.codes_release(h)
    path.write_bytes(b"".join(kept))
    return dropped


def edit_values(path: Path, select: Callable[[dict], bool], edit: Callable) -> int:
    """Rewrite a GRIB file with ``edit(values)`` applied to the messages ``select`` picks
    (``select`` gets the keys ``drop_messages`` gives); returns how many were edited."""
    import eccodes as ec

    out, edited = [], 0
    with open(path, "rb") as f:
        while (h := ec.codes_grib_new_from_file(f)) is not None:
            try:
                keys = {
                    k: ec.codes_get(h, k) for k in ("shortName", "typeOfLevel", "level", "stepType")
                }
                if select(keys):
                    ec.codes_set_values(h, edit(ec.codes_get_values(h)))
                    edited += 1
                out.append(ec.codes_get_message(h))
            finally:
                ec.codes_release(h)
    path.write_bytes(b"".join(out))
    return edited
