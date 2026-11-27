"""Map layers (F1 spec Module 7): headerless little-endian arrays on the map grid,
each described entirely by its ``latest.json`` entry (dtype, shape, codes, scale,
units, sha256; ticket #65).

:func:`build_layers` calls ``tonight()`` once for every map cell, on that cell's own
``HourTable`` (each global model's values at the cell, from the latest area grids
assigned to the map grid) and its own ``SunTrack``, and writes what it returns: the map
and the verdict come from one function, so they can't disagree (D48 item 11). Nothing
here re-derives a verdict rule; a cell's values are those of a saved place at that
spot whose observer stands on each model's ground (D60 item 1).

Layers, row-major north to south, west to east:

- ``clear_left`` uint8: mostly clear counted hours left; 254 = every counted hour left
  is incomplete, 255 = no counted hours left;
- ``counted_left``, ``incomplete_left`` uint8: counted hours left, and how many are
  incomplete;
- ``dark_left_min`` uint16: minutes of dark time left in Tonight (the cell's Sun);
- ``seeing_fa_<family>`` uint16: the family's median O&S free-atmosphere seeing over
  the counted hours (``tonight()``'s seeing range), milli-arcsec; 65535 = none;
- ``total_cloud_<family>`` uint8 (hour, lat, lon): the family's total cloud at each
  of the default saved place's Tonight hours, whole percent for display only; 255 = no
  value (never filled);
- ``model_ground_<family>`` int16: the family's model ground, whole metres; -32768 =
  no run.

Only global families are on the map; MEPS, regional-only, is not (D45 item 3, D60
item 2).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from astroseeing.forecast.grid import MapGrid, to_map_grid
from astroseeing.forecast.settings import CloudClasses, Model
from astroseeing.forecast.store import reaches, run_step, utc_text
from astroseeing.forecast.store.areas import AreaRun
from astroseeing.forecast.tonight import (
    HourTable,
    HourValue,
    Missing,
    ModelHours,
    RunInfo,
    tonight,
)
from astroseeing.forecast.tonight.shapes import HOURS_PER_NIGHT
from astroseeing.forecast.tonight.sun import CellSun

ALL_INCOMPLETE = 254
NO_COUNTED_HOURS = 255
NO_SEEING = 65535
NO_CLOUD = 255
NO_GROUND = -32768
CLEAR_CODES = {str(ALL_INCOMPLETE): "all incomplete", str(NO_COUNTED_HOURS): "no counted hours"}

_EXT = {"uint8": "u8", "uint16": "u16", "int16": "i16"}


@dataclass(frozen=True)
class MapLayers:
    """The layer files (file name → bytes) and their ``latest.json`` entries (layer
    name → entry)."""

    files: Mapping[str, bytes]
    entries: Mapping[str, dict]


def build_layers(
    grid: MapGrid,
    models: Sequence[Model],
    runs: Mapping[str, AreaRun],
    suns: Sequence[Sequence[CellSun]],
    slider_hours: Sequence[dt.datetime],
    now: dt.datetime,
    *,
    cloud_classes: CloudClasses,
    stale_after_h: float,
) -> MapLayers:
    """The map layers at ``now``.

    ``models`` are the area's models; ``runs`` each model's newest stored area grid
    (a model without one is absent); ``suns[row][column]`` each map cell's Sun over its
    Tonight; ``slider_hours`` the hours of the total-cloud layers (the default saved
    place's Tonight).
    """
    shown = [m for m in models if not m.regional]
    shape = (grid.nlat, grid.nlon)
    if (len(suns), len({len(r) for r in suns}), len(suns[0])) != (grid.nlat, 1, grid.nlon):
        raise ValueError(f"suns must be {grid.nlat} rows of {grid.nlon} cells")
    on_map = {m.id: _OnMap(runs[m.id], grid) for m in shown if runs.get(m.id) is not None}

    clear = np.zeros(shape, np.uint8)
    counted = np.zeros(shape, np.uint8)
    incomplete = np.zeros(shape, np.uint8)
    dark = np.zeros(shape, np.uint16)
    seeing = {m.family: np.full(shape, NO_SEEING, np.uint16) for m in shown}
    lookups: dict[tuple[dt.datetime, ...], dict] = {}
    for i in range(grid.nlat):
        for j in range(grid.nlon):
            sun = suns[i][j]
            rows = sun.track.hours
            if rows not in lookups:
                lookups[rows] = {m.id: _hour_steps(on_map.get(m.id), rows) for m in shown}
            table = HourTable(
                sun.track.night,
                rows,
                tuple(_model_hours(m, on_map.get(m.id), lookups[rows][m.id], i, j) for m in shown),
            )
            t = tonight(
                table, sun.track, now, cloud_classes=cloud_classes, stale_after_h=stale_after_h
            )
            if t.counted_hours == 0:
                clear[i, j] = NO_COUNTED_HOURS
            elif t.nothing_to_count is not None:  # every counted hour left incomplete
                clear[i, j] = ALL_INCOMPLETE
            else:
                clear[i, j] = t.clear_hours
            counted[i, j], incomplete[i, j] = t.counted_hours, t.incomplete_hours
            dark[i, j] = sun.dark_left_min
            if t.seeing is not None:
                for family, arcsec in t.seeing.per_family.items():
                    seeing[family][i, j] = _whole(arcsec * 1000.0, NO_SEEING, "seeing (mas)")

    layers = _Layers()
    hours_unit = {"units": "hours"}
    layers.add("clear_left", clear, codes=CLEAR_CODES, **hours_unit)
    layers.add("counted_left", counted, **hours_unit)
    layers.add("incomplete_left", incomplete, **hours_unit)
    layers.add("dark_left_min", dark, units="minutes")
    slider = [utc_text(h) for h in slider_hours]
    for m in shown:
        layers.add(f"seeing_fa_{m.family}", seeing[m.family], codes={str(NO_SEEING): "none"},
                   units="arcsec", scale=0.001)  # fmt: skip
        layers.add(f"total_cloud_{m.family}", _slider_cloud(on_map.get(m.id), slider_hours, shape),
                   codes={str(NO_CLOUD): "no value"}, units="percent", hours=slider)  # fmt: skip
        layers.add(f"model_ground_{m.family}", _ground(on_map.get(m.id), shape),
                   codes={str(NO_GROUND): "no run"}, units="m")  # fmt: skip
    return MapLayers(layers.files, layers.entries)


class _OnMap:
    """A model's area grid with its values assigned to the map grid (nearest point,
    never averaged; spec Module 4)."""

    def __init__(self, run: AreaRun, grid: MapGrid):
        self.run = run
        self.info = RunInfo(run.run_id, run.run_time)
        src = run.grid
        self.cloud = to_map_grid(run.total_cloud_pct, src, grid)
        self.j = to_map_grid(run.j_free, src, grid)
        self.ground = to_map_grid(run.model_ground_m, src, grid)
        self.index = {s: k for k, s in enumerate(run.steps)}


def _hour_steps(on: _OnMap | None, hours: Sequence[dt.datetime]) -> list[int | str] | None:
    """For each hour, the index of the run's stored step, or why it has none, by the
    place store's rules (``store.run_step``), so a map cell and a saved place read a run
    alike. None when the run can't reach the hours (the model counts as having no run)."""
    if on is None:
        return None
    run = on.run
    if not reaches(run.run_time, run.steps_expected[-1], hours[0]):
        return None
    steps = (run_step(run.run_time, run.steps_expected, on.index, t) for t in hours)
    return [s if isinstance(s, str) else on.index[s] for s in steps]


def _model_hours(
    m: Model, on: _OnMap | None, steps: list[int | str] | None, i: int, j: int
) -> ModelHours:
    if steps is None:
        return ModelHours(m.id, m.family, m.regional, None, (Missing("no_run"),) * HOURS_PER_NIGHT)
    cloud, jfree = on.cloud[:, i, j].tolist(), on.j[:, i, j].tolist()
    values = tuple(
        Missing(k)
        if isinstance(k, str)
        else HourValue(cloud[k], None if jfree[k] != jfree[k] else jfree[k])  # NaN: no J
        for k in steps
    )
    return ModelHours(m.id, m.family, m.regional, on.info, values)


def _slider_cloud(
    on: _OnMap | None, hours: Sequence[dt.datetime], shape: tuple[int, int]
) -> np.ndarray:
    out = np.full((len(hours), *shape), NO_CLOUD, np.uint8)
    steps = _hour_steps(on, hours)
    for k, s in enumerate(steps or ()):
        if not isinstance(s, str):
            cloud = on.cloud[s]
            if not (np.isfinite(cloud).all() and (cloud >= 0).all() and (cloud <= 100).all()):
                raise ValueError(f"{on.run.model}: total cloud outside 0-100 % at step index {s}")
            out[k] = np.floor(cloud + 0.5)  # whole percent, for display only
    return out


def _ground(on: _OnMap | None, shape: tuple[int, int]) -> np.ndarray:
    if on is None:
        return np.full(shape, NO_GROUND, np.int16)
    metres = np.floor(on.ground + 0.5)
    if not (np.isfinite(metres).all() and (metres > NO_GROUND).all() and (metres < 2**15).all()):
        raise ValueError(f"{on.run.model}: a model ground doesn't fit the layer's int16")
    return metres.astype(np.int16)


def _whole(x: float, code: int, what: str) -> int:
    """``x`` rounded to a whole number (half up); a value the layer can't hold below its
    code is an error, never clipped."""
    n = int(np.floor(x + 0.5))
    if not 0 <= n < code:
        raise ValueError(f"{what} {x!r} doesn't fit below the layer's code {code}")
    return n


class _Layers:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.entries: dict[str, dict] = {}

    def add(self, name: str, values: np.ndarray, **extra) -> None:
        dtype = values.dtype.name
        data = values.astype(values.dtype.newbyteorder("<"), copy=False).tobytes(order="C")
        file = f"{name}.{_EXT[dtype]}"
        self.files[file] = data
        entry = {"file": file, "dtype": dtype, "shape": list(values.shape)}
        entry.update(extra)
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        self.entries[name] = entry


__all__ = ["CLEAR_CODES", "MapLayers", "build_layers"]
