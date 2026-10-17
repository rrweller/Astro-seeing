#!/usr/bin/env python3
"""Integrity survey of every ERA5 store on the NAS (read-only).

For each region prints: stores, cells, levels, UTC hours, days covered, duplicate or
unsorted times, days requested in the manifest but missing, and NaN counts (with the
variables that hold them). Nothing is written; the manifest is opened read-only.

Run on the CT:  pixi run python scripts/survey_stores.py
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import sys
from collections import Counter, defaultdict

import numpy as np

from astroseeing.ingest.store import read_store
from astroseeing.paths import Paths

COORDS = {"time", "level", "cell_lat", "cell_lon", "cell_index", "latitude", "longitude"}


def main() -> int:
    paths = Paths.from_env()
    db = sqlite3.connect(f"file:{paths.manifest}?mode=ro", uri=True)
    wanted = defaultdict(set)  # (kind, region) -> days requested
    rows = db.execute("select kind, region, expected_json from requests where state = 'ingested'")
    for kind, region, ej in rows:
        for t in json.loads(ej)["times"]:
            wanted[(kind, region)].add(t[:10])

    problems = 0
    for kind in ("pl", "sl"):
        for d in sorted((paths.data_root / "era5" / kind).glob("*/")):
            region = d.name
            if region.startswith("smoke"):
                continue
            stores = sorted(d.glob("*.zarr"))
            times, cells, levels, unsorted = [], set(), set(), 0
            nan, total = Counter(), 0
            for p in stores:
                a, _ = read_store(p)
                t = np.asarray(a["time"]).astype("int64")
                unsorted += int(np.any(np.diff(t) <= 0))
                times.append(t)
                if "cell_lat" in a:
                    cells.add(a["cell_lat"].size)
                else:
                    cells.add(a["latitude"].size * a["longitude"].size)
                levels.add(a["level"].size if "level" in a else 0)
                for k, v in a.items():
                    v = np.asarray(v)
                    if k not in COORDS and v.dtype.kind == "f":
                        nan[k] += int(np.isnan(v).sum())
                        total += v.size
            t = np.concatenate(times)
            dup = t.size - np.unique(t).size
            days = {dt.datetime.fromtimestamp(int(x), dt.UTC).strftime("%Y-%m-%d") for x in t}
            hours = {int(x // 3600 % 24) for x in t}
            missing = sorted(wanted.get((kind, region), set()) - days)
            nan_txt = ", ".join(f"{k} {n}" for k, n in sorted(nan.items()) if n) or "none"
            print(
                f"{kind}/{region}: {len(stores)} stores, cells {sorted(cells)}, levels "
                f"{sorted(levels)}, {len(days)} days {min(days)}..{max(days)}, {len(hours)} UTC "
                f"hours; duplicate times {dup}, unsorted stores {unsorted}, requested days "
                f"missing {len(missing)}{' (e.g. ' + missing[0] + ')' if missing else ''}; "
                f"NaN of {total}: {nan_txt}"
            )
            problems += dup + unsorted + len(missing)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
