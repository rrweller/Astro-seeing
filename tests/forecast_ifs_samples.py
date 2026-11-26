"""Shared helpers for tests that use the saved IFS samples (ticket #56).

The samples are real ECMWF open-data fields of the 2026-11-26 06 UTC IFS run, cut to
small boxes (``tests/fixtures/forecast/ifs/README.md``):

- ``box1deg``: 59.25-60.25° N × 9.25-10.25° E (5 × 5 points), every step 0-48 by 3 h;
- ``kongsberg``: the whole Kongsberg box (40 × 40 points), steps 0 and 3;
- ``paranal``: the Paranal box (4 × 4 points), steps 0 and 3.

Each step is a ``.grib2`` file and its ``.index``, laid out as the portal's (fields the
adapter never asks for are a short filler), so a fake server answers the adapter's
ranged requests as the portal would.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

from astroseeing.forecast.sources import RunRef
from astroseeing.forecast.sources.ifs import file_name

SAMPLES = Path(__file__).resolve().parent / "fixtures" / "forecast" / "ifs" / "20261126T06Z"
SAMPLE_RUN = RunRef("ifs", dt.datetime(2026, 11, 26, 6, tzinfo=dt.UTC))
PORTAL_DIR = "/forecasts/20261126/06z/ifs/0p25/oper"


def serve_samples(server, steps, sample_set: str = "box1deg", folder: Path | None = None) -> None:
    """Serve each step's sample ``.grib2`` and ``.index`` where the portal keeps them."""
    folder = folder or SAMPLES / sample_set
    for step in steps:
        for ext in ("grib2", "index"):
            name = file_name(SAMPLE_RUN, step, ext)
            server.route(f"{PORTAL_DIR}/{name}", folder / name)


def copy_samples(dest: Path, sample_set: str = "box1deg") -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for f in (SAMPLES / sample_set).glob("*-oper-fc.*"):
        (dest / f.name).write_bytes(f.read_bytes())
    return dest


def read_index(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def rewrite_step(
    folder: Path, step: int, edit: Callable[[dict, bytes], tuple[dict, bytes] | None]
) -> int:
    """Rewrite one step's sample: ``edit(index row, field bytes)`` returns the row and
    bytes to keep, or None to drop the field from both the file and the index. Offsets
    are recomputed. Returns how many fields were dropped."""
    grib = folder / file_name(SAMPLE_RUN, step, "grib2")
    index = folder / file_name(SAMPLE_RUN, step, "index")
    data = grib.read_bytes()
    body, out, dropped = b"", [], 0
    for row in read_index(index):
        chunk = data[row["_offset"] : row["_offset"] + row["_length"]]
        kept = edit(row, chunk)
        if kept is None:
            dropped += 1
            continue
        row, chunk = kept
        out.append({**row, "_offset": len(body), "_length": len(chunk)})
        body += chunk
    grib.write_bytes(body)
    index.write_text("\n".join(json.dumps(r) for r in out) + "\n")
    return dropped
