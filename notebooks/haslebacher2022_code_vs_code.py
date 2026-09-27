# %% [markdown]
# # Haslebacher et al. 2022: their code vs ours on the same ERA5 input
#
# Phase 1 task 9, tolerance D19: "our code vs theirs, same inputs: seeing within 0.1%".
#
# * **Theirs:** `climxa.ERA5_seeing_calc` from `external/haslebacher` (GPL-3.0, commit in
#   `external/haslebacher.COMMIT`), imported and called **unmodified**; nothing is copied.
#   `climxa.py` imports plotting and I/O packages at module level that are not in our
#   environment (cartopy, seaborn, SkillMetrics, netCDF4, webcolors, labellines); those
#   are replaced by empty stand-in modules. The seeing functions don't use them.
# * **Ours:** `compute_profile(..., model=HASLEBACHER2022_MODEL)` and
#   `seeing_with_convention(J, HASLEBACHER2022)` (0.976 λ/r₀, 500 nm).
# * **Input:** any ingested or verified ERA5 pressure-level GRIB with u, v, t, z. Their
#   level list has no 70 hPa, so 70 hPa is dropped on both sides; integration starts at
#   the site's Table 4 level (Paranal: 900 hPa).
#
# Run: `pixi run python notebooks/haslebacher2022_code_vs_code.py [GRIB] [start_hPa]`
#
# **Result 2026-09-27** (smoke-test hour, 2023-06-21 00 UTC, 25 Paranal columns, 900 → 50 hPa;
# `reports/haslebacher2022_code_vs_code.json`): median uncalibrated seeing 0.2044″ both ways,
# max relative difference 9.39e-7. That is exactly their rad→arcsec constant 206265 vs the
# exact 206264.806 (ratio − 1 = 9.39e-7), so the methods agree to rounding.

# %%
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import numpy as np
import xarray as xr

from astroseeing.constants import G0, HASLEBACHER2022
from astroseeing.ingest.decode import decode_grib
from astroseeing.manifest import Manifest
from astroseeing.paths import Paths
from astroseeing.physics.optics import seeing_with_convention
from astroseeing.physics.profile import HASLEBACHER2022_MODEL, compute_profile

REPO = Path(__file__).resolve().parents[1]
THEIR_LEVELS = [50, 100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500, 550, 600,
                650, 700, 750, 775, 800, 825, 850, 875, 900, 925, 950, 975, 1000]  # fmt: skip


def import_climxa():
    """Import their climxa.py unmodified, with plotting-only imports stubbed."""

    def stub(name: str, **attrs) -> types.ModuleType:
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        parent, _, child = name.rpartition(".")
        if parent:
            setattr(sys.modules[parent], child, m)
        return m

    for name in ("netCDF4", "seaborn", "skill_metrics", "webcolors", "labellines", "cartopy"):
        stub(name)
    stub("cartopy.crs")
    stub("cartopy.mpl")
    stub("cartopy.mpl.ticker", LongitudeFormatter=object, LatitudeFormatter=object)
    sys.path.insert(0, str(REPO / "external" / "haslebacher"))
    import climxa  # noqa: PLC0415

    return climxa


# %%
def load(grib: Path | None):
    """(DecodedGrib) for the given GRIB, or the newest verified pl file in the manifest."""
    m = Manifest(Paths.from_env().manifest)
    rows = [r for r in m.by_state("verified", "ingested") if r.key.startswith("pl/")]
    for r in reversed(rows):
        f = m.current_file(r.id)
        if f is not None and (grib is None or Path(f["path"]) == grib):
            return r.key, decode_grib(Path(f["path"]), r.expected)
    raise SystemExit(f"no verified pressure-level file found{f' for {grib}' if grib else ''}")


def compare(dec, start_hpa: float) -> dict:
    climxa = import_climxa()
    levels = [lv for lv in THEIR_LEVELS if lv <= start_hpa and lv in set(dec.levels)]
    levels_desc = sorted(levels, reverse=True)  # bottom → top, as their code wants
    idx = [list(dec.levels).index(lv) for lv in levels_desc]

    # Theirs: dims (level, time, latitude, longitude); every operation is elementwise.
    def da(name):
        return xr.DataArray(
            dec.data[name][:, idx].astype(np.float64).transpose(1, 0, 2, 3),
            dims=("level", "time", "latitude", "longitude"),
            coords={"level": levels_desc},
        )

    ds_full = xr.Dataset({v: da(v) for v in ("t", "u", "v", "z")})
    seeing_theirs, _, calib = climxa.ERA5_seeing_calc(ds_full, 1.0, levels_desc)
    eps_theirs = np.asarray(seeing_theirs["seeing"]) / float(calib)  # undo their calibration

    # Ours: level axis last, bottom → top.
    def arr(name):
        return np.moveaxis(dec.data[name][:, idx].astype(np.float64), 1, -1)

    z = arr("z") / G0
    res = compute_profile(
        z, arr("t"), arr("u"), arr("v"), np.array(levels_desc, float), HASLEBACHER2022_MODEL
    )
    eps_ours = seeing_with_convention(res.J, HASLEBACHER2022)
    rel = np.abs(eps_ours / eps_theirs - 1)
    return {
        "levels_hpa": levels_desc,
        "n_columns": int(eps_ours.size),
        "seeing_theirs_median_arcsec": float(np.median(eps_theirs)),
        "seeing_ours_median_arcsec": float(np.median(eps_ours)),
        "max_relative_difference": float(rel.max()),
        "tolerance": 1e-3,
        "pass": bool(rel.max() <= 1e-3),
        "qc": res.qc.as_dict(),
    }


# %%
if __name__ == "__main__":
    grib = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    start = float(sys.argv[2]) if len(sys.argv) > 2 else 900.0
    key, dec = load(grib)
    out = {"request": key, "start_level_hpa": start, **compare(dec, start)}
    print(json.dumps(out, indent=2))
