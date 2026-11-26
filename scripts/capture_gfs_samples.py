"""Capture the GFS test samples from NOMADS's grib filter (ticket #51; run once, by hand).

Uses the adapter's own request plan, so the samples are exactly what ``fetch`` asks for,
paced at the settings' limit (NOMADS: at most 1 request a second) with the generic
User-Agent. Two sets, under about 5 MB together:

- ``box1deg``: a 1.1° box round Kongsberg (5 × 5 GFS points), every step 0-48;
- ``kongsberg``: the whole Kongsberg box (40 × 40 points), steps 0 and 1.

    pixi run python scripts/capture_gfs_samples.py 2026-11-26T06

Writes ``tests/fixtures/forecast/gfs/<run>/<set>/`` and a ``SOURCES.json`` per set
(request targets, bytes, SHA-256, fetch time).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.settings import Area, Box, load_settings
from astroseeing.forecast.sources import RunRef
from astroseeing.forecast.sources.gfs import GfsAdapter

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "forecast" / "gfs"

#: The small sample box: GFS points 59.25-60.25° N × 9.25-10.25° E (5 × 5).
BOX_1DEG = Box(west=9.2, east=10.3, south=59.2, north=60.3)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", help="run time, e.g. 2026-11-26T06")
    args = ap.parse_args(argv)
    settings = load_settings()
    model = settings.models["gfs"]
    run = RunRef("gfs", dt.datetime.strptime(args.run, "%Y-%m-%dT%H").replace(tzinfo=dt.UTC))
    sets = {
        "box1deg": (Area("kongsberg", BOX_1DEG, ("gfs",), "gfs"), model.steps_h),
        "kongsberg": (settings.areas["kongsberg"], (0, 1)),
    }
    http = HttpClient(timeout_s=120)
    adapter = GfsAdapter(model, http, settings.areas)
    for name, (area, steps) in sets.items():
        dest = ROOT / run.label / name
        result = adapter.fetch(run, area, steps, dest)
        if result.missing_steps:
            print(f"{name}: missing steps {dict(result.missing_steps)}", file=sys.stderr)
            return 1
        plan = {r.filename: r.target for r in adapter.request_plan(run, area, steps)}
        sources = {
            "provider": "NOAA/NCEP GFS 0.25°, via the NOMADS grib filter (US-government open data)",
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "run": run.run_time.isoformat(),
            "box": vars(area.box),
            "steps_h": list(steps),
            "files": {
                f.path.name: {"target": plan[f.path.name], "bytes": f.bytes, "sha256": f.sha256}
                for f in result.files
            },
        }
        (dest / "SOURCES.json").write_text(json.dumps(sources, indent=1) + "\n")
        print(f"{name}: {len(result.files)} files, {result.bytes / 1e6:.2f} MB → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
