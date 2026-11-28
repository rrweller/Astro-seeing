"""Read a site's hourly pressure-level columns from ERA5 Zarr stores (roadmap C9, D66).

One call, :func:`read_site`, does everything a paper reproduction needs before the
physics: it reads z, T, u, v (and cc when every store has it) from one or many
stores in either layout (``grid`` or ``cells``, D10), keeps a time range, puts the
hours in time order, checks them against the expected hour grid (no duplicate,
missing or unexpected hours), makes the site value by the paper's rule (D57 item 2),
and masks levels at or below the site's static ERA5 orography (D57 item 1), returning
the masked counts.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from astroseeing.constants import G0
from astroseeing.qc import QCCounts
from astroseeing.repro.rules import COORD_DECIMALS, SiteRule, Stencil
from astroseeing.solar.sun import to_unix

log = logging.getLogger(__name__)

REQUIRED_VARIABLES = ("z", "t", "u", "v")


class SiteReadError(ValueError):
    """The stores can't give a complete, unambiguous site series as asked."""


@dataclass(frozen=True)
class StoreRef:
    """A store that went into a result: its id and its recorded content hash (D10)."""

    store: str
    content_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {"store": self.store, "content_sha256": self.content_sha256}


@dataclass(frozen=True)
class HourGrid:
    """The hours a read must find: these UTC hours on the days kept.

    ``day_step`` > 1 keeps days 1, 1 + step, 1 + 2·step, … of each month, the rule the
    download planner uses (``download.requests.plan_requests``): Timau's every-4th-day
    stores hold days 1, 5, 9, … 29 of every month (D31).
    """

    utc_hours: tuple[int, ...] = tuple(range(24))
    day_step: int = 1

    def __post_init__(self) -> None:
        if self.day_step < 1:
            raise ValueError("day_step must be >= 1")
        if any(not 0 <= h <= 23 for h in self.utc_hours):
            raise ValueError(f"UTC hours must be 0–23, got {self.utc_hours}")

    def times(self, start_s: int, end_s: int) -> np.ndarray:
        days = np.arange(start_s // 86400, (end_s - 1) // 86400 + 1, dtype=np.int64)
        d = days.astype("datetime64[D]")
        day_of_month = (d - d.astype("datetime64[M]")).astype(np.int64) + 1
        days = days[(day_of_month - 1) % self.day_step == 0]
        hours = np.asarray(sorted(self.utc_hours), dtype=np.int64)
        t = (days[:, None] * 86400 + hours[None, :] * 3600).ravel()
        return t[(t >= start_s) & (t < end_s)]

    def settings(self) -> dict[str, Any]:
        return {"utc_hours": sorted(self.utc_hours), "day_step": self.day_step}


@dataclass
class SiteColumns:
    """A site's hourly columns, levels bottom → top on the last axis.

    ``z_m`` is geopotential height (Φ/g₀, metres above mean sea level). Values are as
    read and combined by the rule; masked levels are *not* blanked. ``level_valid``
    says which levels are finite and, when masking, above the orography. Pass
    ``surface_height_m`` to ``physics.compute_profile``, which applies the same test
    (Z ≤ orography); it is ``None`` for the unmasked variant.
    """

    times: np.ndarray  # datetime64[s], (ntime,)
    p_hpa: np.ndarray  # (nlev,)
    z_m: np.ndarray  # (ntime, nlev)
    t_k: np.ndarray
    u: np.ndarray
    v: np.ndarray
    cc: np.ndarray | None
    orography_m: float
    mask_underground: bool
    points: tuple[tuple[float, float], ...]  # grid points used, (lat, lon)
    inputs: tuple[StoreRef, ...]
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def surface_height_m(self) -> float | None:
        return self.orography_m if self.mask_underground else None

    def _finite(self) -> np.ndarray:
        ok = np.ones(self.z_m.shape, bool)
        for a in (self.z_m, self.t_k, self.u, self.v):
            ok &= np.isfinite(a)
        return ok

    def _underground(self) -> np.ndarray:
        if not self.mask_underground:
            return np.zeros(self.z_m.shape, bool)
        return self._finite() & (self.z_m <= self.orography_m)

    @property
    def level_valid(self) -> np.ndarray:
        """bool (ntime, nlev): finite z, T, u, v and, when masking, Z above the orography."""
        return self._finite() & ~self._underground()

    @property
    def masked_levels(self) -> int:
        """Level values at or below the orography (0 for the unmasked variant)."""
        return int(self._underground().sum())

    @property
    def qc(self) -> QCCounts:
        q = QCCounts()
        n = self.z_m.size
        q.add("level_nonfinite", int((~self._finite()).sum()), n)
        q.add("level_below_orography", self.masked_levels, n)
        if self.cc is not None:
            q.add("cc_nonfinite", int((~np.isfinite(self.cc)).sum()), self.cc.size)
        return q

    def select(self, hours: np.ndarray) -> SiteColumns:
        """The same columns at the hours where ``hours`` (bool, one per time) is True."""
        m = np.asarray(hours, dtype=bool)
        if m.shape != self.times.shape:
            raise ValueError(f"hour mask shape {m.shape} != times {self.times.shape}")
        return replace(
            self,
            times=self.times[m],
            z_m=self.z_m[m],
            t_k=self.t_k[m],
            u=self.u[m],
            v=self.v[m],
            cc=None if self.cc is None else self.cc[m],
        )


# --- time ------------------------------------------------------------------------------


def _unix_s(x: dt.datetime | np.datetime64 | str) -> int:
    if isinstance(x, dt.datetime) and x.tzinfo is None:
        raise ValueError("naive datetime; pass UTC-aware times")
    if isinstance(x, dt.datetime):
        return int(to_unix(x))
    return int(np.datetime64(x, "s").astype(np.int64))


def _iso(s: int) -> str:
    return str(np.datetime64(s, "s")) + "Z"


# --- stores ----------------------------------------------------------------------------


def _wrap(dlon: np.ndarray) -> np.ndarray:
    return (np.asarray(dlon, float) + 180.0) % 360.0 - 180.0


@dataclass
class _Store:
    path: Path
    group: Any
    layout: str
    lats: np.ndarray  # per stored point (grid: axis values; cells: per cell)
    dlons: np.ndarray
    names: frozenset[str]

    @classmethod
    def open(cls, path: Path, site_lon: float) -> _Store:
        import zarr

        g = zarr.open_group(str(path), mode="r", zarr_format=3)
        names = {n for n, _ in g.arrays()}
        if "cell_lat" in names:
            lats = np.asarray(g["cell_lat"][...], float)
            lons = np.asarray(g["cell_lon"][...], float)
            layout = "cells"
        elif "latitude" in names:
            lats = np.asarray(g["latitude"][...], float)
            lons = np.asarray(g["longitude"][...], float)
            layout = "grid"
        else:
            raise SiteReadError(f"{path}: neither a grid nor a cells store")
        return cls(
            path=Path(path),
            group=g,
            layout=layout,
            lats=np.round(lats, COORD_DECIMALS),
            dlons=np.round(_wrap(lons - site_lon), COORD_DECIMALS),
            names=frozenset(names),
        )

    @property
    def content_sha256(self) -> str:
        h = self.group.attrs.get("content_sha256")
        if not h:
            raise SiteReadError(f"{self.path}: no content_sha256 attribute")
        return str(h)

    def axes(self) -> tuple[np.ndarray, np.ndarray]:
        """Distinct latitudes and longitude offsets present."""
        return np.unique(self.lats), np.unique(self.dlons)

    def _index(self, stencil: Stencil):
        lat_axis, dlon_axis = stencil.lat, stencil.dlon
        if self.layout == "grid":
            iy = [np.flatnonzero(self.lats == la) for la in lat_axis]
            ix = [np.flatnonzero(self.dlons == d) for d in dlon_axis]
            if any(i.size != 1 for i in iy) or any(i.size != 1 for i in ix):
                raise SiteReadError(f"{self.path}: grid points needed by the rule are missing")
            return np.array([i[0] for i in iy]), np.array([i[0] for i in ix])
        idx = np.empty((lat_axis.size, dlon_axis.size), dtype=np.int64)
        for a, la in enumerate(lat_axis):
            for b, d in enumerate(dlon_axis):
                hit = np.flatnonzero((self.lats == la) & (self.dlons == d))
                if hit.size != 1:
                    raise SiteReadError(
                        f"{self.path}: grid point ({la}, {d:+} east of the site) needed by the "
                        "rule is not among the stored cells"
                    )
                idx[a, b] = hit[0]
        return idx

    def read_block(self, name: str, tsel: np.ndarray, stencil: Stencil) -> np.ndarray:
        """(ntime, [nlev,] ny, nx) float64 on the stencil, latitudes ascending."""
        a = self.group[name]
        # Every non-time axis but the spatial ones is read whole (the level axis, if any).
        whole = (slice(None),) * (a.ndim - (3 if self.layout == "grid" else 2))
        if self.layout == "grid":
            iy, ix = self._index(stencil)
            return np.asarray(a.oindex[(tsel, *whole, iy, ix)], dtype=np.float64)
        idx = self._index(stencil)
        flat = idx.ravel()
        order = np.argsort(flat)
        raw = np.asarray(a.oindex[(tsel, *whole, flat[order])], dtype=np.float64)
        out = np.empty_like(raw)
        out[..., order] = raw
        return out.reshape(*out.shape[:-1], *idx.shape)


def store_id(path: Path, data_root: Path | None = None) -> str:
    """The store's path relative to the data root (``era5/pl/chile/2021-01.zarr``),
    or its absolute path when it lies elsewhere."""
    from astroseeing.paths import Paths

    root = Path(data_root) if data_root is not None else Paths.from_env().data_root
    p = Path(path).resolve()
    try:
        return p.relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


# --- the reader ------------------------------------------------------------------------


def read_site(
    stores: Sequence[Path],
    *,
    lat: float,
    lon: float,
    rule: SiteRule,
    start: dt.datetime | np.datetime64 | str,
    end: dt.datetime | np.datetime64 | str,
    static_store: Path | None,
    expected: HourGrid | None = None,
    levels: Sequence[float] | None = None,
    mask_underground: bool = True,
    data_root: Path | None = None,
) -> SiteColumns:
    """The site's columns over [start, end), in time order, by ``rule``.

    ``stores``: pressure-level stores of one level set, in either layout, in any order.
    ``static_store``: the area's static store (orography = z/g₀ at the site by the same
    rule); needed when ``mask_underground``. ``expected``: the hours that must be
    present (default every UTC hour of every day); a duplicate, missing or unexpected
    hour raises :class:`SiteReadError`. ``levels``: keep only these stored levels (hPa,
    e.g. Haslebacher's 28 without 70 hPa); every one must be stored. ``data_root`` only
    shapes the store ids.
    """
    start_s, end_s = _unix_s(start), _unix_s(end)
    if end_s <= start_s:
        raise ValueError("end must be after start")
    expected = expected or HourGrid()
    if mask_underground and static_store is None:
        raise ValueError("masking underground levels needs the static store (orography)")

    stencil: Stencil | None = None
    stored_levels: np.ndarray | None = None
    parts: list[tuple[np.ndarray, dict[str, np.ndarray]]] = []
    refs: list[StoreRef] = []
    for path in stores:
        store = _Store.open(path, lon)
        t_all = np.asarray(store.group["time"][...], dtype=np.int64)
        tsel = np.flatnonzero((t_all >= start_s) & (t_all < end_s))
        if tsel.size == 0:
            continue
        missing = [v for v in REQUIRED_VARIABLES if v not in store.names]
        if missing:
            raise SiteReadError(f"{path}: variables {missing} missing")
        lv = np.asarray(store.group["level"][...], dtype=np.float64)
        if stored_levels is None:
            stored_levels = lv
        elif not np.array_equal(lv, stored_levels):
            raise SiteReadError(
                f"{path}: levels {lv.tolist()} differ from {stored_levels.tolist()}"
            )
        this = rule.stencil(*store.axes(), lat)
        if stencil is None:
            stencil = this
        elif this != stencil:
            raise SiteReadError(f"{path}: the rule picks different grid points than other stores")
        names = [*REQUIRED_VARIABLES, *(["cc"] if "cc" in store.names else [])]
        data = {n: rule.combine(store.read_block(n, tsel, stencil), stencil, lat) for n in names}
        parts.append((t_all[tsel], data))
        refs.append(StoreRef(store_id(path, data_root), store.content_sha256))

    if not parts:
        raise SiteReadError(f"no store holds any hour in [{_iso(start_s)}, {_iso(end_s)})")
    assert stencil is not None and stored_levels is not None

    times = np.concatenate([t for t, _ in parts])
    order = np.argsort(times, kind="stable")
    times = times[order]
    has_cc = all("cc" in d for _, d in parts)
    if not has_cc and any("cc" in d for _, d in parts):
        log.info("cc is in some stores only; not returned")
    names = [*REQUIRED_VARIABLES, *(["cc"] if has_cc else [])]
    cat = {n: np.concatenate([d[n] for _, d in parts])[order] for n in names}
    _check_hours(times, expected.times(start_s, end_s))

    keep = _level_selection(stored_levels, levels)
    out_levels = stored_levels[keep]
    for n in names:
        out_levels, cat[n] = rule.vertical(stored_levels[keep], cat[n][:, keep])

    orography = np.nan
    if static_store is not None:
        static = _Store.open(static_store, lon)
        block = static.read_block("z", np.array([0]), stencil)
        orography = float(rule.combine(block, stencil, lat)[0]) / G0
        if not np.isfinite(orography):
            raise SiteReadError(f"{static_store}: the orography at the site is not finite")
        refs.append(StoreRef(store_id(static_store, data_root), static.content_sha256))

    points = tuple(
        (float(la), float(np.round(_wrap(lon + d), COORD_DECIMALS)))
        for la in stencil.lat[::-1]
        for d in stencil.dlon
    )
    cols = SiteColumns(
        times=times.astype("datetime64[s]"),
        p_hpa=out_levels,
        z_m=cat["z"] / G0,
        t_k=cat["t"],
        u=cat["u"],
        v=cat["v"],
        cc=cat.get("cc"),
        orography_m=orography,
        mask_underground=mask_underground,
        points=points,
        inputs=tuple(refs),
        settings={
            "site": {"lat": lat, "lon": lon},
            "rule": rule.settings(),
            "start": _iso(start_s),
            "end": _iso(end_s),
            "expected_hours": expected.settings(),
            "mask_underground": mask_underground,
            "stored_levels_hpa": stored_levels.tolist(),
            "levels_hpa": None if levels is None else stored_levels[keep].tolist(),
        },
    )
    cols.qc.log(log, context=f"site ({lat}, {lon}) ")
    return cols


def _level_selection(stored: np.ndarray, wanted: Sequence[float] | None) -> np.ndarray:
    if wanted is None:
        return np.ones(stored.size, bool)
    w = np.asarray(wanted, dtype=np.float64)
    absent = np.setdiff1d(w, stored)
    if absent.size:
        raise SiteReadError(f"levels {absent.tolist()} hPa are not stored")
    return np.isin(stored, w)


def _check_hours(times: np.ndarray, want: np.ndarray) -> None:
    dup = times[1:][np.diff(times) == 0]
    if dup.size:
        raise SiteReadError(
            f"{dup.size} duplicate hours across the stores, first {_iso(int(dup[0]))}"
        )
    missing = np.setdiff1d(want, times)
    extra = np.setdiff1d(times, want)
    if missing.size:
        raise SiteReadError(f"{missing.size} expected hours missing, first {_iso(int(missing[0]))}")
    if extra.size:
        raise SiteReadError(
            f"{extra.size} hours not in the expected hour grid, first {_iso(int(extra[0]))}"
        )
