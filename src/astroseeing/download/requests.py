"""Build ERA5 CDS requests and the expectations used to verify their files.

A request covers one region for one period (a day by default, AGENTS.md
"day-sized requests"). Its canonical JSON is hashed for the manifest, so the same
request is never downloaded twice, and a changed request is never mistaken for an
old one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from typing import Any

from astroseeing.config import load_config
from astroseeing.provenance import canonical_json

ALL_HOURS = tuple(range(24))


@dataclass(frozen=True)
class Area:
    """Box [N, W, S, E] in degrees; edges must be multiples of the grid spacing."""

    north: float
    west: float
    south: float
    east: float

    def validate(self, grid: float) -> None:
        for name, v in (
            ("north", self.north),
            ("west", self.west),
            ("south", self.south),
            ("east", self.east),
        ):
            if abs(v / grid - round(v / grid)) > 1e-9:
                raise ValueError(
                    f"area {name}={v} is not a multiple of {grid}; refusing to snap silently"
                )
        if not (-90 <= self.south <= self.north <= 90):
            raise ValueError(f"bad latitudes {self.north}, {self.south}")
        if not (-180 <= self.west <= self.east <= 360):
            raise ValueError(
                f"bad longitudes {self.west}, {self.east} (dateline-crossing boxes unsupported)"
            )

    def as_cds(self) -> list[float]:
        return [self.north, self.west, self.south, self.east]

    def shape(self, grid: float) -> tuple[int, int]:
        return (
            round((self.north - self.south) / grid) + 1,
            round((self.east - self.west) / grid) + 1,
        )

    @classmethod
    def around(cls, lat: float, lon: float, half_width_cells: int = 2, grid: float = 0.25) -> Area:
        """Box of (2n+1)×(2n+1)+ grid points enclosing a site."""
        lat0 = grid * round(lat / grid)
        lon0 = grid * round(lon / grid)
        h = half_width_cells * grid
        return cls(lat0 + h, lon0 - h, lat0 - h, lon0 + h)


@dataclass(frozen=True)
class RequestSpec:
    kind: str  # "pl" | "sl" | "static"
    region: str
    dates: tuple[dt.date, ...]
    area: Area | None
    variables: tuple[str, ...]  # CDS variable names
    levels: tuple[int, ...] | None = None
    hours: tuple[int, ...] = ALL_HOURS
    grid: float = 0.25
    extra: dict[str, Any] = field(default_factory=dict)

    # --- identity -------------------------------------------------------------
    @property
    def period_label(self) -> str:
        """``YYYY-MM-DD`` (one day), ``YYYY-MM`` (a whole month), else ``first_last``."""
        d0, d1 = self.dates[0], self.dates[-1]
        if d0 == d1:
            return d0.isoformat()
        whole_month = (
            d0.day == 1
            and (d1 + dt.timedelta(days=1)).day == 1
            and (d0.year, d0.month) == (d1.year, d1.month)
            and len(self.dates) == d1.day
        )
        return f"{d0:%Y-%m}" if whole_month else f"{d0.isoformat()}_{d1.isoformat()}"

    @property
    def fields_per_day(self) -> int:
        """CDS cost of one day: variables × levels × hours (the CDS counts fields)."""
        return len(self.variables) * (len(self.levels) if self.levels else 1) * len(self.hours)

    @property
    def n_fields(self) -> int:
        return self.fields_per_day * len(self.dates)

    @property
    def key(self) -> str:
        return f"{self.kind}/{self.region}/{self.period_label}"

    @property
    def dataset(self) -> str:
        return load_config("era5")["datasets"][self.kind]["cds_name"]

    def cds_request(self) -> dict[str, Any]:
        cfg = load_config("era5")
        ds = cfg["datasets"][self.kind]
        years = sorted({f"{d.year:04d}" for d in self.dates})
        months = sorted({f"{d.month:02d}" for d in self.dates})
        days = sorted({f"{d.day:02d}" for d in self.dates})
        if len(years) * len(months) * len(days) != len(self.dates):
            raise ValueError("dates must form a full year×month×day product (one month at most)")
        req: dict[str, Any] = {
            "product_type": [ds["product_type"]],
            "variable": list(self.variables),
            "year": years,
            "month": months,
            "day": days,
            "time": [f"{h:02d}:00" for h in self.hours],
            "data_format": cfg["request"]["data_format"],
            "download_format": cfg["request"]["download_format"],
        }
        if self.levels is not None:
            req["pressure_level"] = [str(lv) for lv in sorted(self.levels)]
        if self.area is not None:
            self.area.validate(self.grid)
            req["area"] = self.area.as_cds()
        req.update(self.extra)
        return req

    def request_hash(self) -> str:
        return hashlib.sha256(
            canonical_json([self.dataset, self.cds_request()]).encode()
        ).hexdigest()

    # --- expectations ----------------------------------------------------------
    def expected(self) -> dict[str, Any]:
        """What a correct GRIB file for this request contains (used by verify)."""
        ds = load_config("era5")["datasets"][self.kind]
        allvars = {**ds["variables"], **ds.get("optional_variables", {})}
        short = [allvars[v]["short_name"] for v in self.variables]
        times = [
            dt.datetime(d.year, d.month, d.day, h, tzinfo=dt.UTC).strftime("%Y-%m-%dT%H:%M")
            for d in self.dates
            for h in self.hours
        ]
        if self.area is None:
            grid = {
                "lat_first": 90.0,
                "lat_last": -90.0,
                "lon_first": 0.0,
                "lon_last": 360.0 - self.grid,
                "nlat": round(180 / self.grid) + 1,
                "nlon": round(360 / self.grid),
            }
        else:
            nlat, nlon = self.area.shape(self.grid)
            grid = {
                "lat_first": self.area.north,
                "lat_last": self.area.south,
                "lon_first": self.area.west,
                "lon_last": self.area.east,
                "nlat": nlat,
                "nlon": nlon,
            }
        grid["step"] = self.grid
        return {
            "short_names": short,
            "levels": sorted(self.levels, reverse=True) if self.levels is not None else None,
            "times": times,
            "grid": grid,
        }


def max_fields(kind: str) -> int:
    """CDS per-request cost limit for a dataset kind (configs/era5.yaml, D23)."""
    return int(load_config("era5")["request"]["max_fields"][kind])


def _split_to_limit(days: list[dt.date], per_day: int, limit: int) -> list[list[dt.date]]:
    """The fewest near-equal contiguous chunks of ``days`` with at most ``limit`` fields each."""
    if len(days) * per_day <= limit:
        return [days]
    max_days = limit // per_day
    if max_days < 1:
        raise ValueError(f"one day is {per_day} fields, over the CDS limit of {limit}")
    n = -(-len(days) // max_days)
    size = -(-len(days) // n)
    return [days[i : i + size] for i in range(0, len(days), size)]


def plan_requests(
    kind: str,
    region: str,
    start: dt.date,
    end: dt.date,
    area: Area | None,
    granularity: str = "day",
    variables: tuple[str, ...] | None = None,
    levels: tuple[int, ...] | None = None,
    hours: tuple[int, ...] = ALL_HOURS,
    split: bool = True,
) -> list[RequestSpec]:
    """Split [start, end] (inclusive) into day- or month-sized requests.

    With ``split`` (the default), any request over the CDS cost limit for its dataset
    (:func:`max_fields`) is cut into the fewest near-equal runs of days under it; a
    whole month of 5×5-box pressure levels (107,880 fields) becomes two requests.
    """
    cfg = load_config("era5")["datasets"][kind]
    variables = tuple(variables or cfg["variables"].keys())
    if kind == "pl":
        levels = tuple(levels or cfg["levels_hpa"])
    if granularity not in ("day", "month"):
        raise ValueError("granularity must be 'day' or 'month'")
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    groups: list[list[dt.date]] = []
    for d in days:
        if (
            granularity == "day"
            or not groups
            or (groups[-1][0].year, groups[-1][0].month) != (d.year, d.month)
        ):
            groups.append([d])
        else:
            groups[-1].append(d)
    if split:
        per_day = len(variables) * (len(levels) if kind == "pl" else 1) * len(hours)
        groups = [c for g in groups for c in _split_to_limit(g, per_day, max_fields(kind))]
    return [
        RequestSpec(
            kind=kind,
            region=region,
            dates=tuple(g),
            area=area,
            variables=variables,
            levels=levels if kind == "pl" else None,
            hours=hours,
        )
        for g in groups
    ]


def static_request(
    region: str, area: Area | None, date: dt.date = dt.date(2023, 1, 1)
) -> RequestSpec:
    """Time-invariant fields (orography, land-sea mask, sdor) at one arbitrary time."""
    cfg = load_config("era5")["datasets"]["static"]
    return RequestSpec(
        kind="static",
        region=region,
        dates=(date,),
        area=area,
        variables=tuple(cfg["variables"].keys()),
        hours=(0,),
    )
