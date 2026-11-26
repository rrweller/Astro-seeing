"""Capture the IFS test samples from ECMWF's open-data portal (ticket #56; run once, by hand).

The portal has no area cut, so each field the adapter needs is global (about 28 MB a
step). The adapter's own ``fetch`` downloads them, byte ranges from the ``.index`` for
the needed fields only, into ``--raw`` (not kept in the repo). Each sample set is then
made by cutting every message to a small box with eccodes, and writing:

- ``<step file>.grib2``: the cut messages, in the portal's order, with a short filler
  ("not downloaded") standing in for every field the adapter never asks for;
- ``<step file>.index``: the portal's index for that step, its ``_offset`` and
  ``_length`` rewritten for this file, so a fake server answers the adapter's ranged
  requests as the portal would.

Cutting re-packs each message (same packing and bits per value); the largest change
of any value is recorded per field in ``SOURCES.json``, with the raw files' URLs,
ranges, sizes and SHA-256. Three sets, under about 5 MB together:

- ``box1deg``: a 1.1° box round Kongsberg (5 × 5 points), every step 0-48;
- ``kongsberg``: the whole Kongsberg box (40 × 40 points), steps 0 and 3;
- ``paranal``: the Paranal box (4 × 4 points), steps 0 and 3.

    pixi run python scripts/capture_ifs_samples.py 2026-11-26T06 --raw /staging/tmp/ifs
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.settings import Box, load_settings
from astroseeing.forecast.sources import RunRef
from astroseeing.forecast.sources.ifs import IfsAdapter, file_name, parse_index

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "forecast" / "ifs"

#: The small sample box (the GFS samples' box): IFS points 59.25-60.25° N × 9.25-10.25° E.
BOX_1DEG = Box(west=9.2, east=10.3, south=59.2, north=60.3)
FILLER = b"not downloaded: %s\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", help="run time, e.g. 2026-11-26T06")
    ap.add_argument("--raw", type=Path, required=True, help="folder for the global downloads")
    args = ap.parse_args(argv)
    settings = load_settings()
    model = settings.models["ifs"]
    run = RunRef("ifs", dt.datetime.strptime(args.run, "%Y-%m-%dT%H").replace(tzinfo=dt.UTC))
    http = HttpClient(timeout_s=300)
    adapter = IfsAdapter(model, http, settings.areas)

    raw = args.raw / run.label
    indexes, raw_sources = {}, {}
    for step in model.steps_h:
        url = adapter.url(run, step, "index")
        body = http.get(url).body
        (raw / file_name(run, step, "index")).parent.mkdir(parents=True, exist_ok=True)
        (raw / file_name(run, step, "index")).write_bytes(body)
        indexes[step] = parse_index(body, "ifs", url)
    fetched = adapter.fetch(run, settings.areas["kongsberg"], model.steps_h, raw)
    if fetched.missing_steps:
        print(f"missing steps {dict(fetched.missing_steps)}", file=sys.stderr)
        return 1
    fetched_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    for f in fetched.files:
        step = int(f.path.name.split("-")[1].rstrip("h"))
        raw_sources[f.path.name] = {
            "url": f.url,
            "index_sha256": hashlib.sha256(
                (raw / file_name(run, step, "index")).read_bytes()
            ).hexdigest(),
            "ranges": [f"{a}-{b}" for a, b in adapter.ranges_for(indexes[step], run, step)],
            "bytes": f.bytes,
            "sha256": f.sha256,
        }

    sets = {
        "box1deg": (BOX_1DEG, model.steps_h),
        "kongsberg": (settings.areas["kongsberg"].box, (0, 3)),
        "paranal": (settings.areas["paranal"].box, (0, 3)),
    }
    for name, (box, steps) in sets.items():
        dest = ROOT / run.label / name
        dest.mkdir(parents=True, exist_ok=True)
        files, max_change = {}, {}
        for step in steps:
            grib, index = cut_step(raw / file_name(run, step, "grib2"), indexes[step],
                                   adapter.wanted(step), box, max_change)  # fmt: skip
            for ext, data in (("grib2", grib), ("index", index)):
                (dest / file_name(run, step, ext)).write_bytes(data)
                files[file_name(run, step, ext)] = {
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
        sources = {
            "provider": "ECMWF IFS open data 0.25° (CC BY 4.0), from https://data.ecmwf.int",
            "credit": "Based on data and products of the European Centre for Medium-Range "
            "Weather Forecasts (ECMWF); cut to the box by this project",
            "fetched_at": fetched_at,
            "run": run.run_time.isoformat(),
            "box": vars(box),
            "steps_h": list(steps),
            "raw": {
                k: v for k, v in raw_sources.items() if int(k.split("-")[1].rstrip("h")) in steps
            },
            "max_change_from_cutting": {k: float(v) for k, v in sorted(max_change.items())},
            "files": files,
        }
        (dest / "SOURCES.json").write_text(json.dumps(sources, indent=1) + "\n")
        size = sum(v["bytes"] for v in files.values())
        print(f"{name}: {len(files)} files, {size / 1e6:.2f} MB → {dest}")
    return 0


def cut_step(
    raw_file: Path, rows: list[dict], wanted: set, box: Box, max_change: dict
) -> tuple[bytes, bytes]:
    """The step's fixture file and index: needed messages cut to ``box``, filler for
    the rest, offsets rewritten."""
    import eccodes as ec

    cut: list[bytes] = []
    with open(raw_file, "rb") as f:
        while (h := ec.codes_grib_new_from_file(f)) is not None:
            try:
                cut.append(cut_message(h, box, max_change))
            finally:
                ec.codes_release(h)
    body, out_rows, k = b"", [], 0
    for row in rows:
        key = (row["param"], float(row["levelist"]) if row["levtype"] == "pl" else None)
        if row["levtype"] in ("pl", "sfc") and key in wanted:
            chunk = cut[k]
            k += 1
        else:
            chunk = FILLER % row["param"].encode()
        out_rows.append({**row, "_offset": len(body), "_length": len(chunk)})
        body += chunk
    if k != len(cut):
        raise RuntimeError(f"{raw_file}: {len(cut)} messages but {k} needed index rows")
    return body, ("\n".join(json.dumps(r) for r in out_rows) + "\n").encode()


def cut_message(h, box: Box, max_change: dict) -> bytes:
    import eccodes as ec

    nj, ni = ec.codes_get(h, "Nj"), ec.codes_get(h, "Ni")
    lat0 = ec.codes_get(h, "latitudeOfFirstGridPointInDegrees")
    lon0 = ec.codes_get(h, "longitudeOfFirstGridPointInDegrees")
    dlat = ec.codes_get(h, "jDirectionIncrementInDegrees")
    dlon = ec.codes_get(h, "iDirectionIncrementInDegrees")
    assert not ec.codes_get(h, "jScansPositively") and not ec.codes_get(h, "iScansNegatively")
    lats = lat0 - dlat * np.arange(nj)
    lons = (lon0 + dlon * np.arange(ni) + 180.0) % 360.0 - 180.0
    rows = np.flatnonzero((lats >= box.south - 1e-9) & (lats <= box.north + 1e-9))
    cols = np.flatnonzero((lons >= box.west - 1e-9) & (lons <= box.east + 1e-9))
    assert np.all(np.diff(rows) == 1) and np.all(np.diff(cols) == 1)
    values = ec.codes_get_values(h).reshape(nj, ni)[np.ix_(rows, cols)]
    c = ec.codes_clone(h)
    try:
        ec.codes_set(c, "Ni", len(cols))
        ec.codes_set(c, "Nj", len(rows))
        ec.codes_set(c, "latitudeOfFirstGridPointInDegrees", float(lats[rows[0]]))
        ec.codes_set(c, "latitudeOfLastGridPointInDegrees", float(lats[rows[-1]]))
        ec.codes_set(c, "longitudeOfFirstGridPointInDegrees", float(lons[cols[0]] % 360))
        ec.codes_set(c, "longitudeOfLastGridPointInDegrees", float(lons[cols[-1]] % 360))
        ec.codes_set_values(c, values.ravel())
        back = ec.codes_get_values(c).reshape(len(rows), len(cols))
        name = ec.codes_get(h, "shortName")
        max_change[name] = max(max_change.get(name, 0.0), float(np.max(np.abs(back - values))))
        return ec.codes_get_message(c)
    finally:
        ec.codes_release(c)


if __name__ == "__main__":
    raise SystemExit(main())
