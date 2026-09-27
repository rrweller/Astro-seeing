"""WMO lapse-rate tropopause (docs/RESEARCH.md §4.4).

WMO definition: "the lowest level at which the lapse rate decreases to 2 °C/km or
less, provided also the average lapse rate between this level and all higher
levels within 2 km does not exceed 2 °C/km".

Discrete implementation (our choice, logged in docs/decisions.md):

* Candidates are levels i (with p ≤ ``p_max_hpa``) whose slab lapse rate to the
  next valid level, −(T[i+1]−T[i])/(Z[i+1]−Z[i]), is ≤ 2 K/km. The ``p_max_hpa``
  bound (default 500 hPa) stops low-level inversions from being taken as the
  tropopause.
* Temperature is treated as piecewise linear in height between levels. The
  average lapse rate from level i to a height z is then extreme at level heights
  or at the 2 km endpoint, so we check every level within 2 km plus T interpolated
  at Z[i] + 2 km (when that lies below the top level).
* The tropopause height is Z[i] of the lowest passing level. NaN if none passes;
  the count is recorded under ``tropopause_not_found``.
"""

from __future__ import annotations

import numpy as np

from astroseeing.qc import QCCounts

WMO_LAPSE_LIMIT = 2.0e-3  # K m^-1
WMO_DEPTH = 2000.0  # m


def _wmo_tropopause_reference(
    z_m: np.ndarray,
    t_k: np.ndarray,
    p_hpa: np.ndarray,
    level_valid: np.ndarray | None = None,
    p_max_hpa: float = 500.0,
    lapse_limit: float = WMO_LAPSE_LIMIT,
    depth: float = WMO_DEPTH,
    qc: QCCounts | None = None,
) -> np.ndarray:
    """Straightforward per-column loop; the reference for testing the vectorised version."""
    z = np.asarray(z_m, dtype=np.float64)
    t = np.asarray(t_k, dtype=np.float64)
    p = np.broadcast_to(np.asarray(p_hpa, dtype=np.float64), z.shape)
    valid = np.ones(z.shape, bool) if level_valid is None else np.asarray(level_valid, bool)
    valid = valid & np.isfinite(z) & np.isfinite(t)

    col_shape = z.shape[:-1]
    nlev = z.shape[-1]
    z2 = z.reshape(-1, nlev)
    t2 = t.reshape(-1, nlev)
    p2 = p.reshape(-1, nlev)
    v2 = valid.reshape(-1, nlev)
    out = np.full(z2.shape[0], np.nan)

    # Columns are processed one by one: the search is sequential by nature and
    # this runs on at most tens of levels per column.
    for c in range(z2.shape[0]):
        idx = np.flatnonzero(v2[c])
        if idx.size < 2:
            continue
        zc, tc, pc = z2[c, idx], t2[c, idx], p2[c, idx]
        for j in range(idx.size - 1):
            if pc[j] > p_max_hpa:
                continue
            lapse = -(tc[j + 1] - tc[j]) / (zc[j + 1] - zc[j])
            if lapse > lapse_limit:
                continue
            ok = True
            within = np.flatnonzero((zc > zc[j]) & (zc - zc[j] <= depth))
            for k in within:
                if (tc[j] - tc[k]) / (zc[k] - zc[j]) > lapse_limit:
                    ok = False
                    break
            z_end = zc[j] + depth
            if ok and z_end < zc[-1]:
                t_end = np.interp(z_end, zc, tc)
                if (tc[j] - t_end) / depth > lapse_limit:
                    ok = False
            if ok:
                out[c] = zc[j]
                break

    out = out.reshape(col_shape)
    if qc is not None:
        qc.add("tropopause_not_found", int(np.isnan(out).sum()), out.size)
    return out


def wmo_tropopause_height(
    z_m: np.ndarray,
    t_k: np.ndarray,
    p_hpa: np.ndarray,
    level_valid: np.ndarray | None = None,
    p_max_hpa: float = 500.0,
    lapse_limit: float = WMO_LAPSE_LIMIT,
    depth: float = WMO_DEPTH,
    qc: QCCounts | None = None,
) -> np.ndarray:
    """Tropopause geopotential height (m) per column; level axis last, bottom → top.

    Vectorised over columns (O(nlev²) array operations); gives the same result as
    the per-column reference implementation.
    """
    z = np.asarray(z_m, dtype=np.float64)
    t = np.asarray(t_k, dtype=np.float64)
    p = np.broadcast_to(np.asarray(p_hpa, dtype=np.float64), z.shape)
    valid = np.ones(z.shape, bool) if level_valid is None else np.asarray(level_valid, bool)
    valid = valid & np.isfinite(z) & np.isfinite(t)

    col_shape = z.shape[:-1]
    nlev = z.shape[-1]
    z2 = np.where(valid, z, np.nan).reshape(-1, nlev)
    t2 = np.where(valid, t, np.nan).reshape(-1, nlev)
    p2 = p.reshape(-1, nlev)
    v2 = valid.reshape(-1, nlev)
    ncol = z2.shape[0]
    rows = np.arange(ncol)

    # Index of the next valid level above each level (nlev = none).
    nxt = np.full((ncol, nlev), nlev, dtype=np.intp)
    for j in range(nlev - 2, -1, -1):
        nxt[:, j] = np.where(v2[:, j + 1], j + 1, nxt[:, j + 1])
    z_top = np.nanmax(np.where(v2, z2, -np.inf), axis=1)

    out = np.full(ncol, np.nan)
    found = np.zeros(ncol, bool)
    with np.errstate(invalid="ignore", divide="ignore"):
        for j in range(nlev - 1):
            has_next = nxt[:, j] < nlev
            k1 = np.minimum(nxt[:, j], nlev - 1)
            lapse = -(t2[rows, k1] - t2[:, j]) / (z2[rows, k1] - z2[:, j])
            cand = ~found & v2[:, j] & has_next & (p2[:, j] <= p_max_hpa) & (lapse <= lapse_limit)
            if not cand.any():
                continue
            fail = np.zeros(ncol, bool)
            for k in range(j + 1, nlev):
                dzk = z2[:, k] - z2[:, j]
                within = v2[:, k] & (dzk > 0) & (dzk <= depth)
                fail |= within & ((t2[:, j] - t2[:, k]) / dzk > lapse_limit)
            # Interpolated temperature at Z[j] + depth (when below the top level).
            z_end = z2[:, j] + depth
            check_end = z_end < z_top
            below = v2 & (z2 <= z_end[:, None])
            below[:, :j] = False
            kb = nlev - 1 - np.argmax(below[:, ::-1], axis=1)  # last valid level <= z_end
            ka = np.minimum(nxt[rows, kb], nlev - 1)
            frac = (z_end - z2[rows, kb]) / (z2[rows, ka] - z2[rows, kb])
            t_end = t2[rows, kb] + frac * (t2[rows, ka] - t2[rows, kb])
            fail |= check_end & ((t2[:, j] - t_end) / depth > lapse_limit)
            hit = cand & ~fail
            out[hit] = z2[hit, j]
            found |= hit

    out = out.reshape(col_shape)
    if qc is not None:
        qc.add("tropopause_not_found", int(np.isnan(out).sum()), out.size)
    return out


def stratosphere_mask(z_bot: np.ndarray, tropopause_m: np.ndarray) -> np.ndarray:
    """True for slabs whose base is at or above the tropopause (NaN tropopause → all False)."""
    tp = np.asarray(tropopause_m, dtype=np.float64)[..., None]
    with np.errstate(invalid="ignore"):
        return np.asarray(z_bot) >= tp
