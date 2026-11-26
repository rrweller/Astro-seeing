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


#: The NCEP names an AWS ``.idx`` line gives a message (as on ``noaa-gfs-bdp-pds``, seen
#: in the real index files under ``fixtures/forecast/gfs/aws-idx/``), by GRIB2 codes.
_IDX_VARS = {
    (0, 0, 0): "TMP", (0, 3, 5): "HGT", (0, 2, 2): "UGRD", (0, 2, 3): "VGRD",
    (0, 6, 1): "TCDC", (0, 6, 3): "LCDC", (0, 6, 4): "MCDC", (0, 6, 5): "HCDC",
    (0, 19, 0): "VIS", (0, 3, 0): "PRES",
}  # fmt: skip
_IDX_LEVELS = {
    1: "surface", 214: "low cloud layer", 224: "middle cloud layer",
    234: "high cloud layer", 10: "entire atmosphere",
}  # fmt: skip


def aws_file(nomads_file: Path, run: RunRef) -> tuple[bytes, str]:
    """The NOMADS sample's messages laid out as the AWS bucket's file of that step and
    part, and its ``.idx`` (``n:offset:d=YYYYMMDDHH:VAR:level:forecast:``)."""
    import eccodes as ec

    body, lines = b"", []
    with open(nomads_file, "rb") as f:
        while (h := ec.codes_grib_new_from_file(f)) is not None:
            try:
                code = tuple(
                    ec.codes_get(h, k, int)
                    for k in ("discipline", "parameterCategory", "parameterNumber")
                )
                surface = ec.codes_get(h, "typeOfFirstFixedSurface", int)
                if surface == 100:
                    level = f"{ec.codes_get(h, 'level', int):g} mb"
                else:
                    level = _IDX_LEVELS[surface]
                ec.codes_set(h, "stepUnits", 1)
                start, end = ec.codes_get(h, "startStep", int), ec.codes_get(h, "endStep", int)
                if ec.codes_get(h, "stepType") != "instant":
                    forecast = f"{start}-{end} hour ave fcst"
                else:
                    forecast = "anl" if end == 0 else f"{end} hour fcst"
                message = ec.codes_get_message(h)
            finally:
                ec.codes_release(h)
            lines.append(
                f"{len(lines) + 1}:{len(body)}:d={run.run_time:%Y%m%d%H}:"
                f"{_IDX_VARS[code]}:{level}:{forecast}:"
            )
            body += message
    return body, "\n".join(lines) + "\n"


def serve_aws_samples(
    server, steps, folder: Path | None = None, run: RunRef = SAMPLE_RUN
) -> None:
    """Serve the samples where the AWS bucket keeps each step's two files and their
    ``.idx`` (``/gfs.YYYYMMDD/HH/atmos/gfs.tHHz.pgrb2.0p25.fNNN``, no area cut)."""
    folder = folder or SAMPLES / "box1deg"
    day, hh = run.run_time.strftime("%Y%m%d"), run.run_time.strftime("%H")
    for step in steps:
        for part in ("pgrb2", "pgrb2b"):
            name = f"gfs.t{hh}z.{part}.0p25.f{step:03d}"
            body, idx = aws_file(folder / f"{name}.grb2", run)
            server.route(f"/gfs.{day}/{hh}/atmos/{name}", body)
            server.route(f"/gfs.{day}/{hh}/atmos/{name}.idx", idx.encode())


def retime_samples(dest: Path, hour: int, sample_set: str = "box1deg") -> Path:
    """A copy of the samples as if from the run of ``hour`` UTC on the same day: run
    time and file names changed, values and steps as they are (for a second run)."""
    import eccodes as ec

    copy_samples(dest, sample_set)
    for f in sorted(dest.glob("gfs.t06z.*.grb2")):

        def change(h, keys):
            ec.codes_set(h, "dataTime", hour * 100)
            return ec.codes_get_message(h), True

        _rewrite(f, change)
        f.rename(f.with_name(f.name.replace("t06z", f"t{hour:02d}z")))
    return dest


def copy_samples(dest: Path, sample_set: str = "box1deg") -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for f in (SAMPLES / sample_set).glob("*.grb2"):
        (dest / f.name).write_bytes(f.read_bytes())
    return dest


def _rewrite(path: Path, change: Callable) -> int:
    """Rewrite a GRIB file message by message. ``change(handle, keys)`` returns the
    message's new bytes (None drops it) and whether it changed the message; ``keys`` are
    the eccodes keys shortName, typeOfLevel, level and stepType. Returns how many changed."""
    import eccodes as ec

    out, changed = [], 0
    with open(path, "rb") as f:
        while (h := ec.codes_grib_new_from_file(f)) is not None:
            try:
                keys = {
                    k: ec.codes_get(h, k) for k in ("shortName", "typeOfLevel", "level", "stepType")
                }
                message, did = change(h, keys)
                changed += did
                if message is not None:
                    out.append(message)
            finally:
                ec.codes_release(h)
    path.write_bytes(b"".join(out))
    return changed


def drop_messages(path: Path, drop: Callable[[dict], bool]) -> int:
    """Rewrite a GRIB file without the messages ``drop`` selects; returns how many went.

    ``drop`` gets the eccodes keys shortName, typeOfLevel, level and stepType.
    """
    import eccodes as ec

    def change(h, keys):
        return (None, True) if drop(keys) else (ec.codes_get_message(h), False)

    return _rewrite(path, change)


def edit_values(path: Path, select: Callable[[dict], bool], edit: Callable) -> int:
    """Rewrite a GRIB file with ``edit(values)`` applied to the messages ``select`` picks
    (``select`` gets the keys ``drop_messages`` gives); returns how many were edited."""
    import eccodes as ec

    def change(h, keys):
        hit = select(keys)
        if hit:
            ec.codes_set_values(h, edit(ec.codes_get_values(h)))
        return ec.codes_get_message(h), hit

    return _rewrite(path, change)
