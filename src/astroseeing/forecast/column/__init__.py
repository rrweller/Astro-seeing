"""Column products (F1 spec Module 3): J above the observer and above observer + 1 km,
H̄ and seeing (500 nm, zenith) for both Cₙ² models, from the shared ``physics`` engine,
which this package never changes (D47, D54 item 3).

Rules (D47 items 1, 2, 4 and 6):

- **Observer height:** the given height (a saved place's GLO-30 height, or the model
  ground for a map cell), raised to the model ground where it lies below it. Each
  raised column is counted (``observer_raised``) and its raise returned.
- **Levels:** a level with p > surface pressure, or at or below the model ground, is
  masked and counted (``physics.column.level_validity``). The gap between the model
  ground and the first valid level is not filled; its depth is returned per column.
- **Above the observer:** levels wholly below the observer contribute nothing to J and
  are counted (``level_below_observer``); the slab straddling the observer is cut at the
  observer in J (``integral_above``), never in seeing.
- **H̄** = [∫Cₙ² h^(5/3) dh / ∫Cₙ² dh]^(3/5), h above the observer, over the column from
  the observer up (D47 item 4). Undefined where the column has no turbulence: NaN,
  counted (``hbar_undefined_no_turbulence``).
- **Seeing:** ``physics.optics.seeing_arcsec`` (exact 5.307 form, 500 nm, zenith) of J.
- Unstable layers are zeroed and the WMO lapse-rate tropopause is used, as in the
  historical track (D5, D47 item 6): both come with the engine's Cₙ² models.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from astroseeing.constants import OS_SPLIT_HEIGHT
from astroseeing.forecast.sources.interface import RunFields
from astroseeing.physics.integrate import weighted_moment_above
from astroseeing.physics.optics import seeing_arcsec
from astroseeing.physics.profile import BI2023_MODEL, OS2018_MODEL, Cn2Model, compute_profile
from astroseeing.qc import QCCounts

#: The two Cₙ² models of D47 item 4, under the names the page files use (D71 item 9):
#: Osborn & Sarazin 2018 with K = 6, and Tatarskii + HMNSP99 with the constants of
#: RESEARCH §4.4 (79×10⁻⁶ K hPa⁻¹, γ = 9.8×10⁻³ K m⁻¹; Bi et al.'s preset). D72.
CN2_MODELS: Mapping[str, Cn2Model] = MappingProxyType(
    {"osborn_sarazin": OS2018_MODEL, "tatarskii": BI2023_MODEL}
)


@dataclass(frozen=True)
class Cn2Column:
    """One Cₙ² model's products, each ``(steps, *grid)``."""

    j_total: np.ndarray  # m^(1/3), above the observer
    j_free: np.ndarray  # m^(1/3), above the observer + 1 km
    hbar_m: np.ndarray  # effective turbulence altitude above the observer, m (NaN: none)
    seeing_total_arcsec: np.ndarray
    seeing_free_arcsec: np.ndarray
    qc: QCCounts


@dataclass(frozen=True)
class ColumnProducts:
    """Column products of one run (spec Module 3); index by Cₙ² model name."""

    models: Mapping[str, Cn2Column]
    observer_height_m: np.ndarray  # (*grid): the height used, after any raise
    raise_m: np.ndarray  # (*grid): metres the observer was raised to the model ground
    model_ground_m: np.ndarray  # (*grid)
    gap_to_first_level_m: np.ndarray  # (steps, *grid): NaN where no level is valid
    valid_levels: np.ndarray  # (steps, *grid): levels above ground
    level_count: int  # the forecast model's pressure levels (D47 item 5's label)
    wind_200hpa_ms: np.ndarray  # (steps, *grid)
    qc: QCCounts  # level, slab and observer counts (each Cn2Column has its model's own)

    def __getitem__(self, cn2_model: str) -> Cn2Column:
        return self.models[cn2_model]


def column_products(
    fields: RunFields,
    observer_height_m: float | np.ndarray,
    cn2_models: Mapping[str, Cn2Model] = CN2_MODELS,
) -> ColumnProducts:
    """Column products for every step and grid point of ``fields``.

    ``observer_height_m`` is a scalar (a saved place's height) or an array of the grid's
    shape (e.g. the model ground, for map cells).
    """
    ground = np.asarray(fields.model_ground_m, dtype=np.float64)
    wanted = np.broadcast_to(np.asarray(observer_height_m, dtype=np.float64), ground.shape)
    observer = np.maximum(wanted, ground)
    raised = wanted < ground
    qc = QCCounts()
    qc.add_mask("observer_raised", raised)

    shape = (fields.n_steps, *fields.grid_shape)
    obs = np.broadcast_to(observer, shape)
    heights = np.stack([obs, obs + OS_SPLIT_HEIGHT], axis=-1)
    z = np.asarray(fields.geopotential_height_m, dtype=np.float64)
    sp = np.asarray(fields.surface_pressure_hpa, dtype=np.float64)
    ground_s = np.broadcast_to(ground, shape)

    models, level_valid = {}, None
    for name, model in cn2_models.items():
        prof = compute_profile(
            z,
            fields.temperature_k,
            fields.u_ms,
            fields.v_ms,
            fields.pressure_hpa,
            model=model,
            surface_pressure_hpa=sp,
            surface_height_m=ground_s,
        )
        if level_valid is None:  # the level masks are the same for every Cₙ² model
            level_valid = prof.slabs.level_valid
            qc.merge(prof.slabs.qc)
        j = prof.j_above(heights)
        j_total, j_free = j[..., 0], j[..., 1]
        none = ~prof.slabs.valid.any(axis=-1)  # no valid slab: no column at all
        prof.qc.add_mask("column_without_valid_slab", none)
        j_total = np.where(none, np.nan, j_total)
        j_free = np.where(none, np.nan, j_free)
        s = prof.slabs
        moment = weighted_moment_above(obs, prof.cn2, s.z_bot, s.z_top, valid=s.valid)
        calm = j_total == 0
        prof.qc.add_mask("hbar_undefined_no_turbulence", calm)
        with np.errstate(divide="ignore", invalid="ignore"):
            hbar = np.where(calm | none, np.nan, (moment / j_total) ** 0.6)
        models[name] = Cn2Column(
            j_total, j_free, hbar, seeing_arcsec(j_total), seeing_arcsec(j_free), prof.qc
        )

    below_obs = level_valid & (z <= obs[..., None])
    qc.add("level_below_observer", int(below_obs.sum()), below_obs.size)
    first = np.argmax(level_valid, axis=-1)
    z_first = np.take_along_axis(z, first[..., None], axis=-1)[..., 0]
    any_valid = level_valid.any(axis=-1)
    qc.add_mask("column_without_valid_level", ~any_valid)
    gap = np.where(any_valid, z_first - ground_s, np.nan)
    u200, v200 = fields.wind_200hpa_ms
    return ColumnProducts(
        models=MappingProxyType(models),
        observer_height_m=observer,
        raise_m=np.maximum(ground - wanted, 0.0),
        model_ground_m=ground,
        gap_to_first_level_m=gap,
        valid_levels=level_valid.sum(axis=-1),
        level_count=fields.level_count,
        wind_200hpa_ms=np.hypot(u200, v200),
        qc=qc,
    )
