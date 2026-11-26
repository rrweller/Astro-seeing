"""Shared helpers for tests that use the saved MEPS samples (ticket #57).

The samples are real OPeNDAP responses from MET Norway's THREDDS server for the
2026-11-26 06 UTC MEPS deterministic run (CC BY 4.0 / NLOD; based on data from MET
Norway; ``tests/fixtures/forecast/meps/README.md``):

- ``kongsberg``: 59.6-59.72° N × 9.55-9.75° E (5 × 5 points), every step 0-48;
- ``box1deg``: the GFS samples' 1.1° box (51 × 29 points), steps 16-19;
- ``catalogue``: the ``mepslatest`` catalogue and the 06z run's time axis (``.dds?time``).
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import numpy as np

from astroseeing.forecast.settings import Area, Box
from astroseeing.forecast.sources import RunRef
from astroseeing.forecast.sources.dap2 import DapArray, DapVariable, parse_dods
from astroseeing.forecast.sources.meps import CATALOGUE, DAP_DIR

MEPS_SAMPLES = Path(__file__).resolve().parent / "fixtures" / "forecast" / "meps"
SAMPLE_RUN = RunRef("meps", dt.datetime(2026, 11, 26, 6, tzinfo=dt.UTC))
BOX_KONGSBERG = Box(west=9.55, east=9.75, south=59.6, north=59.72)
BOX_1DEG = Box(west=9.2, east=10.3, south=59.2, north=60.3)
SETS = {"kongsberg": BOX_KONGSBERG, "box1deg": BOX_1DEG}


def sample_folder(sample_set: str) -> Path:
    return MEPS_SAMPLES / SAMPLE_RUN.label / sample_set


def sample_area(sample_set: str) -> Area:
    """The Kongsberg area cut to a sample set's box."""
    return Area("kongsberg", SETS[sample_set], ("meps",), "icon_eu")


def sample_steps(sample_set: str) -> tuple[int, ...]:
    return tuple(json.loads((sample_folder(sample_set) / "SOURCES.json").read_text())["steps_h"])


def serve_meps(server, sample_set: str = "kongsberg", folder: Path | None = None,
               catalogue: bool = True) -> None:  # fmt: skip
    """Route every request the samples answered to its saved file, and (``catalogue``)
    the ``mepslatest`` catalogue and the 06z run's time axis."""
    folder = folder or sample_folder(sample_set)
    sources = json.loads((sample_folder(sample_set) / "SOURCES.json").read_text())
    for name, f in sources["files"].items():
        server.route(f["target"], folder / name)
    if catalogue:
        cat = MEPS_SAMPLES / "catalogue"
        server.route(CATALOGUE, cat / "catalog.xml")
        name = f"meps_det_2_5km_{SAMPLE_RUN.label}.ncml"
        server.route(f"{DAP_DIR}{name}.dds?time", cat / f"{name}.dds")


def copy_samples(dest: Path, sample_set: str = "kongsberg") -> Path:
    shutil.copytree(sample_folder(sample_set), dest)
    return dest


def edit_dods(path: Path, edit: Callable[[dict[str, DapVariable]], dict[str, DapVariable]]) -> None:
    """Rewrite a saved ``.dods`` response after ``edit`` changed its variables."""
    path.write_bytes(encode_dods(edit(parse_dods(path.read_bytes()))))


def without_level(var: DapVariable, level_hpa: float) -> DapVariable:
    """A pressure-level Grid with one level taken out (values and pressure map)."""
    p = var.maps["pressure"].values
    keep = np.flatnonzero(p != level_hpa)
    assert len(keep) == len(p) - 1, f"no level {level_hpa} in {p}"
    dims = tuple((d, len(keep)) if d == "pressure" else (d, n) for d, n in var.array.dims)
    array = DapArray(var.array.name, var.array.dap_type, dims, var.array.values[:, keep])
    maps = dict(var.maps)
    pm = maps["pressure"]
    maps["pressure"] = DapArray(pm.name, pm.dap_type, (("pressure", len(keep)),), pm.values[keep])
    return DapVariable(array, maps)


def encode_dods(variables: dict[str, DapVariable]) -> bytes:
    """A DAP 2.0 ``.dods`` body for ``variables`` (atomic arrays and Grids only), written
    from the format's description, independently of the reader."""
    lines, data = ["Dataset {"], b""
    for name, v in variables.items():
        if v.maps:
            lines += ["    Grid {", "     ARRAY:", f"        {_decl(v.array)}", "     MAPS:"]
            lines += [f"        {_decl(m)}" for m in v.maps.values()]
            lines.append(f"    }} {name};")
        else:
            lines.append(f"    {_decl(v.array)}")
        for a in (v.array, *v.maps.values()):
            data += _xdr(a)
    lines.append("} sample;")
    return ("\n".join(lines) + "\n\nData:\n").encode() + data


def _decl(a: DapArray) -> str:
    return f"{a.dap_type} {a.name}" + "".join(f"[{d} = {n}]" for d, n in a.dims) + ";"


_WIRE = {"Float32": ">f4", "Float64": ">f8", "Int32": ">i4", "Int16": ">i4"}


def _xdr(a: DapArray) -> bytes:
    values = np.asarray(a.values).astype(_WIRE[a.dap_type]).tobytes()
    if not a.dims:
        return values
    n = int(np.prod([s for _, s in a.dims]))
    return np.array([n, n], ">u4").tobytes() + values
