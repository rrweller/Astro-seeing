"""Validation areas: one CDS download for several nearby sites (decisions D29, D31).

The CDS charges per field whatever the area, so one request covering the rectangle
around several sites costs no more CDS time than a request for one site. Only the
5×5 boxes around the sites are stored (``cells`` layout; every downloaded hour).

``mask_fn`` is the ingest/cleanup hook: declared areas get their site-box mask;
small boxes (≤ :data:`MAX_UNMASKED_POINTS` points) keep the ``grid`` layout; any
other large request is refused (D18).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import cache

import numpy as np

from astroseeing.config import load_config
from astroseeing.download.requests import Area
from astroseeing.ingest.pipeline import MAX_UNMASKED_POINTS, RefusedUnmasked


@dataclass(frozen=True)
class ValidationArea:
    name: str
    sites: tuple[tuple[str, float, float], ...]  # (group/site, lat, lon)
    half_width: int = 2
    grid: float = 0.25

    def boxes(self) -> dict[str, Area]:
        return {n: Area.around(la, lo, self.half_width, self.grid) for n, la, lo in self.sites}

    @property
    def area(self) -> Area:
        """The smallest rectangle holding every site box."""
        b = list(self.boxes().values())
        return Area(
            north=max(x.north for x in b),
            west=min(x.west for x in b),
            south=min(x.south for x in b),
            east=max(x.east for x in b),
        )

    def cell_mask(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """True at grid points (lat × lon) inside any site box.

        Longitudes may come in either convention (−180..180 or 0..360: the CDS may
        return 289.0 for −71.0); they are compared modulo 360.
        """
        la = np.asarray(lat, float)[:, None]
        lo = np.asarray(lon, float)[None, :]
        eps = 1e-6
        out = np.zeros((la.size, lo.size), dtype=bool)
        for b in self.boxes().values():
            east_of_west = np.mod(lo - b.west + eps, 360.0) - eps  # 0 at the west edge
            out |= (
                (la <= b.north + eps) & (la >= b.south - eps)
                & (east_of_west <= (b.east - b.west) + eps)
            )  # fmt: skip
        return out

    def points(self) -> tuple[np.ndarray, np.ndarray]:
        """Latitudes and longitudes of every grid point in the site boxes."""
        a = self.area
        lat = np.arange(a.north, a.south - 1e-9, -self.grid)
        lon = np.arange(a.west, a.east + 1e-9, self.grid)
        m = self.cell_mask(lat, lon)
        iy, ix = np.nonzero(m)
        return lat[iy], lon[ix]

    def night_hours(self, year: int = 2023, threshold_deg: float = -12.0) -> tuple[int, ...]:
        """UTC hours that are night somewhere in the area on some day of ``year``.

        "Night" is the ingest rule (D8): the Sun below −12° at any minute within
        ±30 min of the hour, at any grid point of any site box.
        """
        from astroseeing.solar.darkness import night_hours_to_keep
        from astroseeing.solar.sun import SunTable, load_ephemeris, to_unix

        eph, ts = load_ephemeris()
        start = dt.datetime(year, 1, 1, tzinfo=dt.UTC)
        end = dt.datetime(year + 1, 1, 1, tzinfo=dt.UTC)
        sun = SunTable.build(start - dt.timedelta(hours=1), end + dt.timedelta(hours=1), eph, ts)
        hours = np.arange(float(to_unix(start)), float(to_unix(end)), 3600.0)
        lat, lon = self.points()
        keep = night_hours_to_keep(lat, lon, hours, sun, threshold_deg).any(axis=0)
        utc_hour = ((hours // 3600) % 24).astype(int)
        return tuple(sorted({int(h) for h in utc_hour[keep]}))


@cache
def load_areas() -> dict[str, ValidationArea]:
    sites = load_config("sites")
    out = {}
    for name, cfg in load_config("validation_areas").items():
        entries = []
        for ref in cfg["sites"]:
            group, site = ref.split("/")
            s = sites[group][site]
            entries.append((ref, float(s["lat"]), float(s["lon"])))
        out[name] = ValidationArea(name, tuple(entries), int(cfg.get("box_half_width", 2)))
    return out


def area_for_region(region: str) -> ValidationArea | None:
    """The area a request region belongs to (regions may carry a ``@tag``, e.g. ``timau@4d``)."""
    return load_areas().get(region.split("@", 1)[0])


def mask_fn(req, dec) -> tuple[np.ndarray | None, None]:
    """Ingest/cleanup hook: site-box mask for areas, grid layout for small boxes."""
    area = area_for_region(req.region)
    if area is not None:
        mask = area.cell_mask(dec.lat, dec.lon)
        want = area.points()[0].size
        if int(mask.sum()) != want:
            # Never store a partial or empty area silently (e.g. an unexpected grid).
            raise ValueError(
                f"{req.key}: site-box mask selects {int(mask.sum())} grid points, expected "
                f"{want} for area {area.name!r}; grid lat {dec.lat[0]}..{dec.lat[-1]}, "
                f"lon {dec.lon[0]}..{dec.lon[-1]}"
            )
        return mask, None
    npts = dec.lat.size * dec.lon.size
    if npts <= MAX_UNMASKED_POINTS:
        return None, None
    raise RefusedUnmasked(
        f"{npts} grid points and not a declared validation area; not stored unmasked"
    )
