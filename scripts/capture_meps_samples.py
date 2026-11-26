"""Capture the MEPS test samples from MET Norway's THREDDS server (ticket #57; run once,
by hand).

Uses the adapter's own requests, so the samples are exactly what ``fetch`` asks for,
cut to each box on the server, with the generic User-Agent. Two sets, under about
5 MB together:

- ``kongsberg``: a 0.12° × 0.2° box round Kongsberg, every step 0-48;
- ``box1deg``: the 1.1° box of the GFS samples (``tests/forecast_samples.py``), steps
  16-19 (22-01 UTC for the 06z run, the middle of Tonight), so the tick test can run
  MEPS beside GFS on one area.

    pixi run python scripts/capture_meps_samples.py 2026-11-26T06

Writes ``tests/fixtures/forecast/meps/<run>/<set>/`` and a ``SOURCES.json`` per set
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
from astroseeing.forecast.sources.meps import MepsAdapter

ROOT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "forecast" / "meps"

#: Kongsberg (59.669° N, 9.652° E) with a few MEPS points round it.
BOX_KONGSBERG = Box(west=9.55, east=9.75, south=59.6, north=59.72)
#: The GFS samples' box (``scripts/capture_gfs_samples.py``).
BOX_1DEG = Box(west=9.2, east=10.3, south=59.2, north=60.3)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", help="run time, e.g. 2026-11-26T06")
    args = ap.parse_args(argv)
    settings = load_settings()
    model = settings.models["meps"]
    run = RunRef("meps", dt.datetime.strptime(args.run, "%Y-%m-%dT%H").replace(tzinfo=dt.UTC))
    sets = {
        "kongsberg": (Area("kongsberg", BOX_KONGSBERG, ("meps",), "icon_eu"), model.steps_h),
        "box1deg": (Area("kongsberg", BOX_1DEG, ("meps",), "icon_eu"), (16, 17, 18, 19)),
    }
    http = HttpClient(timeout_s=300)
    for name, (area, steps) in sets.items():
        adapter = MepsAdapter(model, http, {area.id: area})
        dest = ROOT / run.label / name
        result = adapter.fetch(run, area, steps, dest)
        if result.missing_steps:
            print(f"{name}: missing steps {dict(result.missing_steps)}", file=sys.stderr)
            return 1
        base = adapter.base_url
        sources = {
            "provider": "MET Norway, MEPS deterministic 2.5 km (MetCoOp), via THREDDS OPeNDAP; "
            "CC BY 4.0 and NLOD; based on data from MET Norway",
            "fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "run": run.run_time.isoformat(),
            "box": vars(area.box),
            "steps_h": list(steps),
            "files": {
                f.path.name: {
                    "target": f.url.removeprefix(base),
                    "bytes": f.bytes,
                    "sha256": f.sha256,
                }
                for f in result.files
            },
        }
        (dest / "SOURCES.json").write_text(json.dumps(sources, indent=1) + "\n")
        print(f"{name}: {len(result.files)} files, {result.bytes / 1e6:.2f} MB → {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
