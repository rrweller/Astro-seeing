"""``verify_run``: a run's fields against the model's expected content (spec Module 2).

Two kinds of finding:

- **content problems** (other levels, grid spacing, level cloud or fog signals than the
  settings expect): the run fails (``ok`` is false) and the model shows as missing
  (D51 item 8);
- **per-step findings**: a step not delivered, or a field with NaN (bitmap-missing)
  values at that step. The step is not verified, with its reason; the other steps
  still count (a partial run, D51 item 7).

Every NaN is counted per field (the counting style of ``verify.grib``); nothing is
dropped, filled or regridded here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from astroseeing.forecast.settings import Model
from astroseeing.forecast.sources.interface import RunFields

_GRID_TOL = 1e-6
_LEVEL_FIELDS = ("geopotential_height_m", "temperature_k", "u_ms", "v_ms", "level_cloud_pct")
_SURFACE_FIELDS = (
    "total_cloud_pct",
    "low_cloud_pct",
    "mid_cloud_pct",
    "high_cloud_pct",
    "surface_pressure_hpa",
)


@dataclass
class VerifyReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    nan_counts: dict[str, int] = field(default_factory=dict)
    steps: dict[int, str] = field(default_factory=dict)  # step → "ok" or why not

    @property
    def verified_steps(self) -> tuple[int, ...]:
        return tuple(s for s, why in sorted(self.steps.items()) if why == "ok")

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "problems": self.problems,
            "nan_counts": self.nan_counts,
            "steps": {str(k): v for k, v in sorted(self.steps.items())},
        }


def verify_run(
    fields: RunFields,
    expected: Model,
    steps_expected: tuple[int, ...],
    missing: Mapping[int, str] | None = None,
) -> VerifyReport:
    """Check ``fields`` against ``expected`` (the model's settings) and the steps asked for;
    ``missing`` gives the reason for each step the fetch could not get."""
    rep = VerifyReport(ok=True)
    if tuple(fields.pressure_hpa) != tuple(expected.pressure_levels_hpa):
        rep.problems.append(
            f"pressure levels {list(fields.pressure_hpa)} differ from the "
            f"expected {list(expected.pressure_levels_hpa)}"
        )
    if (fields.level_cloud_pct is not None) != expected.level_cloud:
        rep.problems.append(
            f"level cloud {
                'present' if fields.level_cloud_pct is not None else 'absent'
            }, expected {'present' if expected.level_cloud else 'absent'}"
        )
    have_fog = {k for k, v in fields.fog.items() if v is not None}
    for name in sorted(set(expected.fog_signals) - have_fog):
        rep.problems.append(f"fog signal {name} absent, expected")
    for name in sorted(have_fog - set(expected.fog_signals)):
        rep.problems.append(f"fog signal {name} present, not expected")
    rep.problems += _grid_problems(fields, expected)

    run_t0 = np.datetime64(fields.run.run_time.replace(tzinfo=None), "s")
    steps_h = ((fields.valid_times - run_t0) // np.timedelta64(1, "h")).astype(int).tolist()
    stray = sorted(set(steps_h) - set(steps_expected))
    if stray:
        rep.problems.append(f"steps {stray} were not asked for")
    missing = dict(missing or {})
    for s in steps_expected:
        if s not in steps_h:
            rep.steps[s] = f"not fetched: {missing.get(s, 'no reason given')}"

    arrays = {name: getattr(fields, name) for name in _LEVEL_FIELDS + _SURFACE_FIELDS}
    arrays["model_ground_m"] = np.broadcast_to(
        fields.model_ground_m, (fields.n_steps, *fields.grid_shape)
    )
    arrays |= {f"fog {k}": v for k, v in fields.fog.items() if v is not None}
    per_step: dict[int, list[str]] = {s: [] for s in steps_h}
    for name, values in arrays.items():
        if values is None:
            continue
        nan = np.isnan(np.asarray(values, dtype=np.float64))
        rep.nan_counts[name] = int(nan.sum())
        per = nan.reshape(fields.n_steps, -1).sum(axis=1)
        for s, n in zip(steps_h, per.tolist(), strict=True):
            if n:
                per_step[s].append(f"{name} ({n} value{'s' if n > 1 else ''})")
    for s in steps_h:
        if s in steps_expected:
            rep.steps[s] = "ok" if not per_step[s] else "NaN in " + ", ".join(per_step[s])
    rep.ok = not rep.problems
    return rep


def _grid_problems(fields: RunFields, expected: Model) -> list[str]:
    g = expected.grid
    if g.kind != "regular_latlon":
        return []  # a projected grid (MEPS) is checked by its own adapter
    lat, lon = np.asarray(fields.lat), np.asarray(fields.lon)
    out = []
    if (
        lat.ndim == 2
        and lat.shape[0] > 1
        and not np.allclose(-np.diff(lat[:, 0]), g.spacing, atol=_GRID_TOL)
    ):
        out.append(f"latitude spacing differs from {g.spacing}°")
    if (
        lat.ndim == 2
        and lat.shape[1] > 1
        and not np.allclose(np.diff(lon[0]) % 360, g.spacing, atol=_GRID_TOL)
    ):
        out.append(f"longitude spacing differs from {g.spacing}°")
    return out
