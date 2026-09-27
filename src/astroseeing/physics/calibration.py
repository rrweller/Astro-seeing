"""Calibration helpers (docs/RESEARCH.md §4.8) and the jet-stream shortcut (§4.6).

J ∝ K  ⇒  ε ∝ K^(3/5)  ⇒  K_new = K_old · (ε_obs / ε_model)^(5/3)

Fitting is done on nightly medians with held-out years or sites; this module only
holds the algebra and the skill statistics.
"""

from __future__ import annotations

import numpy as np


def j_scale_for_seeing_ratio(ratio: float | np.ndarray) -> float | np.ndarray:
    """Factor on J (or K) that multiplies seeing by ``ratio``: ratio^(5/3)."""
    return np.asarray(ratio, dtype=np.float64) ** (5.0 / 3.0)


def recalibrate_k(k_old: float, eps_observed: float, eps_model: float) -> float:
    """K_new = K_old · (ε_obs/ε_model)^(5/3)."""
    return float(k_old * (eps_observed / eps_model) ** (5.0 / 3.0))


def skill_stats(model: np.ndarray, observed: np.ndarray) -> dict[str, float]:
    """Bias (model − obs), RMSE and Pearson r over pairs where both are finite."""
    m = np.asarray(model, dtype=np.float64)
    o = np.asarray(observed, dtype=np.float64)
    ok = np.isfinite(m) & np.isfinite(o)
    m, o = m[ok], o[ok]
    n = int(m.size)
    if n == 0:
        return {"n": 0, "bias": np.nan, "rmse": np.nan, "r": np.nan}
    d = m - o
    r = float(np.corrcoef(m, o)[0, 1]) if n > 1 and m.std() > 0 and o.std() > 0 else np.nan
    return {"n": n, "bias": float(d.mean()), "rmse": float(np.sqrt((d**2).mean())), "r": r}


def wind_speed_200(u200: np.ndarray, v200: np.ndarray) -> np.ndarray:
    """V₂₀₀ = √(u² + v²) at 200 hPa, m s⁻¹."""
    return np.hypot(np.asarray(u200, dtype=np.float64), np.asarray(v200, dtype=np.float64))


def fit_jetstream_a(j_fa: np.ndarray, u200: np.ndarray, v200: np.ndarray) -> float:
    """Least-squares A in J_FA ≈ A (u₂₀₀² + v₂₀₀²) (through the origin; Vernin 1986 form)."""
    x = wind_speed_200(u200, v200) ** 2
    y = np.asarray(j_fa, dtype=np.float64)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    return float(np.dot(x, y) / np.dot(x, x))
