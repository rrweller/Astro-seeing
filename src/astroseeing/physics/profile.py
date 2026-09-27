"""High-level column → Cₙ² → J(h) pipeline (docs/RESEARCH.md §4, §5).

This ties the pieces together for one or many columns at a time:

    levels → slabs → (tropopause) → Cₙ² per slab → J_FA(h) on a height grid

The same function serves paper reproductions (pick ``model`` and constants) and our
product (defaults). Every mask and fallback is counted in the returned ``qc``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from astroseeing.constants import (
    BI_GAMMA,
    HMNSP99_STRATOSPHERE,
    HMNSP99_TROPOSPHERE,
    OS_A,
    OS_K,
    TATARSKII_A,
    Hmnsp99Coefficients,
)
from astroseeing.physics.cn2 import (
    hmnsp99_l0_43,
    osborn_sarazin_cn2,
    tatarskii_cn2,
    tatarskii_m,
    tatarskii_m_theta,
)
from astroseeing.physics.column import Slabs, prepare_slabs
from astroseeing.physics.integrate import column_integral, integral_above
from astroseeing.physics.tropopause import stratosphere_mask, wmo_tropopause_height
from astroseeing.qc import QCCounts


@dataclass(frozen=True)
class Cn2Model:
    """Choice of Cₙ² recipe and its constants.

    ``kind``:
      * ``"tatarskii"``: Cₙ² = 2.8 M² L0^(4/3) with HMNSP99 L0.
        ``m_form="dtdz"`` uses M = A(P/T²)(∂T/∂z + γ) (Bi et al.);
        ``m_form="dtheta"`` uses M = −A(P/T²)∂θ/∂z (Priyatikanto et al. as printed).
      * ``"osborn_sarazin"``: O&S eq. 7 with constant ``k``.

    ``state_at``: where each slab's T, P and θ are taken (``"mid"``, D3; or
    ``"lower"``, the lower level, as Haslebacher et al. 2022 do).
    """

    kind: str = "osborn_sarazin"
    a: float = OS_A
    k: float = OS_K
    unstable: str = "zero"
    gamma: float = BI_GAMMA
    m_form: str = "dtdz"
    troposphere: Hmnsp99Coefficients = HMNSP99_TROPOSPHERE
    stratosphere: Hmnsp99Coefficients = HMNSP99_STRATOSPHERE
    tropopause_p_max_hpa: float = 500.0
    theta_p0_hpa: float = 1000.0
    state_at: str = "mid"


#: Bi et al. 2023 as described in docs/RESEARCH.md §3.1/§4.4.
BI2023_MODEL = Cn2Model(kind="tatarskii", a=TATARSKII_A, gamma=BI_GAMMA, m_form="dtdz")
#: Osborn & Sarazin 2018 with their Paranal constant.
OS2018_MODEL = Cn2Model(kind="osborn_sarazin", a=OS_A, k=OS_K)
#: Haslebacher et al. 2022 "seeing model" before calibration, as their code computes
#: it (commit 1da3712): O&S eq. 13 with k = 1, T/P/θ at each slab's lower level, and
#: |∂θ/∂z| in N² (so unstable layers count, D5 "abs"). They calibrate seeing, not J,
#: afterwards (docs/RESEARCH.md §3.4, D27).
HASLEBACHER2022_MODEL = Cn2Model(
    kind="osborn_sarazin", a=OS_A, k=1.0, unstable="abs", state_at="lower"
)


@dataclass
class ProfileResult:
    slabs: Slabs
    cn2: np.ndarray  # (..., nslab)
    J: np.ndarray  # (...,) total over valid slabs
    tropopause_m: np.ndarray | None
    qc: QCCounts = field(default_factory=QCCounts)

    def j_above(self, heights_m: np.ndarray) -> np.ndarray:
        """J_FA(h) on a height grid, shape (..., nh)."""
        s = self.slabs
        return integral_above(heights_m, self.cn2, s.z_bot, s.z_top, s.valid)


def compute_profile(
    z_m: np.ndarray,
    t_k: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    p_hpa: np.ndarray,
    model: Cn2Model = OS2018_MODEL,
    surface_pressure_hpa: np.ndarray | None = None,
    surface_height_m: np.ndarray | None = None,
) -> ProfileResult:
    """Cₙ² per slab and total J for columns (level axis last, bottom → top)."""
    slabs = prepare_slabs(
        z_m,
        t_k,
        u,
        v,
        p_hpa,
        surface_pressure_hpa=surface_pressure_hpa,
        surface_height_m=surface_height_m,
        p0_hpa=model.theta_p0_hpa,
        state_at=model.state_at,
    )
    qc = QCCounts().merge(slabs.qc)
    tropo = None
    if model.kind == "tatarskii":
        tropo = wmo_tropopause_height(
            z_m,
            t_k,
            p_hpa,
            level_valid=slabs.level_valid,
            p_max_hpa=model.tropopause_p_max_hpa,
            qc=qc,
        )
        strat = stratosphere_mask(slabs.z_bot, tropo)
        l0_43 = hmnsp99_l0_43(slabs.shear, slabs.dtdz, strat, model.troposphere, model.stratosphere)
        if model.m_form == "dtdz":
            m = tatarskii_m(slabs.p_mid, slabs.t_mid, slabs.dtdz, model.gamma, model.a)
        elif model.m_form == "dtheta":
            m = tatarskii_m_theta(slabs.p_mid, slabs.t_mid, slabs.dthetadz, model.a)
        else:
            raise ValueError(f"unknown m_form {model.m_form!r}")
        cn2 = tatarskii_cn2(m, l0_43)
    elif model.kind == "osborn_sarazin":
        cn2 = osborn_sarazin_cn2(
            slabs.p_mid,
            slabs.t_mid,
            slabs.theta_mid,
            slabs.dthetadz,
            slabs.shear2,
            k=model.k,
            a=model.a,
            unstable=model.unstable,
            qc=qc,
        )
    else:
        raise ValueError(f"unknown Cn2 model kind {model.kind!r}")
    cn2 = np.where(slabs.valid, cn2, np.nan)
    J = column_integral(cn2, slabs.z_bot, slabs.z_top, slabs.valid)
    return ProfileResult(slabs=slabs, cn2=cn2, J=J, tropopause_m=tropo, qc=qc)
