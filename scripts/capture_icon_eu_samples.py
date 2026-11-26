"""Capture the ICON-EU test samples from DWD opendata (ticket #55; run once, by hand).

Downloads every file the adapter's plan names for one run, steps 0-48 (whole-domain
bz2 GRIB2, one field per file, ~4.4 GB in all), a few at a time (``--workers``)
with the generic User-Agent, and keeps only small cuts of them, so the samples stay
under about 5 MB:

- ``box1deg``: every field cut to the GFS samples' 1.1° box round Kongsberg
  (59.2-60.3° N × 9.2-10.3° E, 17 × 17 ICON-EU points), every step 0-48. Each step's
  107 cut messages are saved together as ``step_<SSS>.grib2.bz2``, the model ground as
  ``hsurf.grib2.bz2``; ``SOURCES.json`` names the DWD file each message came from (in
  order), with that file's size and SHA-256 as downloaded.
- ``whole-domain``: one file exactly as DWD served it (the step-0 ``WW``, the smallest),
  so the adapter's own cut is tested on DWD's bytes.

A cut keeps the box's grid points as they are, with the grid description changed to
the box. eccodes re-packs the values (CCSDS, DWD's 16 bits per value), so a cut value
can differ from DWD's by up to one packing step of the box's range; integer codes such
as ``WW`` come out exactly.

    pixi run python scripts/capture_icon_eu_samples.py 2026-11-26T06

Writes ``tests/fixtures/forecast/icon_eu/<run>/`` and prints the run's total size.
"""

from __future__ import annotations

import argparse
import bz2
import datetime as dt
import json
import math
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.settings import Box, load_settings
from astroseeing.forecast.sources import RunRef
from astroseeing.forecast.sources.icon_eu import IconEuAdapter

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "forecast" / "icon_eu"

#: The GFS samples' box (``scripts/capture_gfs_samples.py``).
BOX_1DEG = Box(west=9.2, east=10.3, south=59.2, north=60.3)
SPACING = 0.0625


def cut_message(message: bytes, box: Box) -> tuple[bytes, dict]:
    """The message cut to the grid points inside ``box``, and its keys for the record."""
    import eccodes as ec

    h = ec.codes_new_from_message(message)
    try:
        keys = {
            k: ec.codes_get(h, k)
            for k in (
                "discipline", "parameterCategory", "parameterNumber", "typeOfFirstFixedSurface",
                "level", "stepType", "dataDate", "dataTime", "packingType", "bitsPerValue",
            )
        }  # fmt: skip
        assert ec.codes_get(h, "gridType") == "regular_ll"
        assert int(ec.codes_get(h, "jScansPositively")) == 1
        assert not int(ec.codes_get(h, "iScansNegatively"))
        ni, nj = int(ec.codes_get(h, "Ni")), int(ec.codes_get(h, "Nj"))
        lat0 = float(ec.codes_get(h, "latitudeOfFirstGridPointInDegrees"))
        lon0 = (float(ec.codes_get(h, "longitudeOfFirstGridPointInDegrees")) + 180) % 360 - 180
        d = float(ec.codes_get(h, "iDirectionIncrementInDegrees"))
        assert d == SPACING == float(ec.codes_get(h, "jDirectionIncrementInDegrees"))
        k_south, k_north = math.ceil(box.south / d), math.floor(box.north / d)
        k_west, k_east = math.ceil(box.west / d), math.floor(box.east / d)
        j0, j1 = round(k_south - lat0 / d), round(k_north - lat0 / d)
        i0, i1 = round(k_west - lon0 / d), round(k_east - lon0 / d)
        assert 0 <= j0 <= j1 < nj and 0 <= i0 <= i1 < ni
        ec.codes_set(h, "missingValue", 1e20)
        values = ec.codes_get_values(h).reshape(nj, ni)[j0 : j1 + 1, i0 : i1 + 1]
        assert not np.any(values == 1e20), "a missing value inside the box"
        out = ec.codes_clone(h)
        try:
            ec.codes_set(out, "Ni", i1 - i0 + 1)
            ec.codes_set(out, "Nj", j1 - j0 + 1)
            ec.codes_set(out, "latitudeOfFirstGridPointInDegrees", k_south * d)
            ec.codes_set(out, "longitudeOfFirstGridPointInDegrees", (k_west * d) % 360)
            ec.codes_set(out, "latitudeOfLastGridPointInDegrees", k_north * d)
            ec.codes_set(out, "longitudeOfLastGridPointInDegrees", (k_east * d) % 360)
            ec.codes_set_values(out, values.ravel())
            return ec.codes_get_message(out), keys
        finally:
            ec.codes_release(out)
    finally:
        ec.codes_release(h)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", help="run time, e.g. 2026-11-26T06")
    ap.add_argument("--workers", type=int, default=6, help="parallel downloads (default 6)")
    args = ap.parse_args(argv)
    settings = load_settings()
    model = settings.models["icon_eu"]
    run = RunRef("icon_eu", dt.datetime.strptime(args.run, "%Y-%m-%dT%H").replace(tzinfo=dt.UTC))
    http = HttpClient(timeout_s=300)
    adapter = IconEuAdapter(model, http, settings.areas)
    plan = adapter.file_plan(run, model.steps_h)
    dest = ROOT / run.label
    (dest / "box1deg").mkdir(parents=True, exist_ok=True)
    (dest / "whole-domain").mkdir(parents=True, exist_ok=True)
    bundles: dict[str, list[bytes]] = {}
    sources: dict[str, list[dict]] = {}
    total, seen_keys = 0, {}

    def one(f, tmp: str):
        """Download one file and cut it; only the cut is kept (the file is deleted)."""
        d = http.download(adapter.base_url + f.path, Path(tmp) / f.filename)
        try:
            raw = d.path.read_bytes()
            cut, keys = cut_message(bz2.decompress(raw), BOX_1DEG)
            return d, cut, keys, raw if f.step == 0 and f.field.name == "WW" else None
        finally:
            d.path.unlink()

    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor(args.workers) as pool:
        # map() yields in plan order, so each bundle keeps the plan's field order
        results = pool.map(lambda f: one(f, tmp), plan)
        for n, (f, (d, cut, keys, whole)) in enumerate(zip(plan, results, strict=True)):
            total += d.bytes
            seen_keys.setdefault(f.field.name, keys)
            bundle = "hsurf.grib2.bz2" if f.step is None else f"step_{f.step:03d}.grib2.bz2"
            bundles.setdefault(bundle, []).append(cut)
            sources.setdefault(bundle, []).append(
                {"file": f.filename, "url": d.url, "bytes": d.bytes, "sha256": d.sha256}
            )
            if whole is not None:
                (dest / "whole-domain" / f.filename).write_bytes(whole)
            if n % 107 == 0:
                print(f"{n + 1}/{len(plan)} files, {total / 1e9:.2f} GB", file=sys.stderr)
    for name, messages in bundles.items():
        (dest / "box1deg" / name).write_bytes(bz2.compress(b"".join(messages), 9))
    doc = {
        "provider": "Deutscher Wetterdienst (DWD), ICON-EU, opendata.dwd.de (CC BY 4.0)",
        "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "run": run.run_time.isoformat(),
        "box": vars(BOX_1DEG),
        "steps_h": list(model.steps_h),
        "run_bytes_downloaded": total,
        "grib_keys_by_field": seen_keys,
        "bundles": sources,
    }
    (dest / "box1deg" / "SOURCES.json").write_text(json.dumps(doc, indent=1) + "\n")
    print(f"{len(plan)} files, {total / 1e9:.3f} GB downloaded → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
