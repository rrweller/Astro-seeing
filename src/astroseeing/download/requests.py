"""Build ERA5 CDS requests and the expectations used to verify their files.

A request covers one region for one period: a day, part of a month, a month, or (single
levels only) up to ``request.max_months_per_request`` consecutive months of one calendar
year (D55 item 5, D63). Its canonical JSON is hashed for the manifest, so the same
request is never downloaded twice, and a changed request is never mistaken for an old
one.

The CDS form takes dates as a year × month × day product. A request over several months
therefore names days that don't exist in every month (30 February, 31 April). A request's
``dates`` are always the real dates only: they are what verification expects. Its
``cds_cost`` counts the whole product, the most the CDS could charge for it.
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
from dataclasses import dataclass, field
from typing import Any

from astroseeing.config import load_config
from astroseeing.provenance import canonical_json

ALL_HOURS = tuple(range(24))


def _cds_axes(dates) -> tuple[list[str], list[str], list[str]]:
    """The CDS form's year, month and day lists covering ``dates``."""
    return (
        sorted({f"{d.year:04d}" for d in dates}),
        sorted({f"{d.month:02d}" for d in dates}),
        sorted({f"{d.day:02d}" for d in dates}),
    )


def _real_dates(years, months, days) -> set[dt.date]:
    """The dates that exist in a year × month × day product (30 February drops out)."""
    out = set()
    for y in years:
        for m in months:
            n = calendar.monthrange(int(y), int(m))[1]
            out.update(dt.date(int(y), int(m), int(d)) for d in days if int(d) <= n)
    return out


def _is_product(dates) -> bool:
    """Whether ``dates`` are exactly the real dates of their own year × month × day product."""
    return _real_dates(*_cds_axes(dates)) == set(dates)


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
    #: "store" (the default: ingested into Zarr) or "measure" (downloaded and verified
    #: only, never ingested; one-off CDS test requests, ticket #10).
    purpose: str = "store"

    # --- identity -------------------------------------------------------------
    @property
    def period_label(self) -> str:
        """``YYYY-MM-DD`` (one day), ``YYYY-MM`` (a whole month), ``YYYY-MM_YYYY-MM``
        (several whole months, D63), else ``first_last`` (``YYYY-MM-DD_YYYY-MM-DD``)."""
        d0, d1 = self.dates[0], self.dates[-1]
        if d0 == d1:
            return d0.isoformat()
        whole_months = (
            d0.day == 1
            and (d1 + dt.timedelta(days=1)).day == 1
            and len(set(self.dates)) == (d1 - d0).days + 1
        )
        if whole_months and (d0.year, d0.month) == (d1.year, d1.month):
            return f"{d0:%Y-%m}"
        if whole_months:
            return f"{d0:%Y-%m}_{d1:%Y-%m}"
        return f"{d0.isoformat()}_{d1.isoformat()}"

    @property
    def fields_per_day(self) -> int:
        """CDS cost of one day: variables × levels × hours (the CDS counts fields)."""
        return len(self.variables) * (len(self.levels) if self.levels else 1) * len(self.hours)

    @property
    def n_fields(self) -> int:
        """Fields on the real dates: what verification expects in the file."""
        return self.fields_per_day * len(self.dates)

    @property
    def cds_cost(self) -> int:
        """The CDS cost of the request as the form names it: the whole year × month × day
        product, non-existent dates included (the same count as ``notify.request_fields``).

        Equal to ``n_fields`` for a request inside one month. Over several months it is
        the most the CDS could charge; whether it counts 30 February is the cost check's
        question (``astro cost-check``, D63), so planning limits use this upper bound.
        """
        return self.fields_per_day * _product_size(self.dates)

    def check_cost_limit(self) -> None:
        """Raise if ``cds_cost`` is over the CDS limit for the kind (:func:`max_fields`)."""
        limit = max_fields(self.kind)
        if self.cds_cost > limit:
            raise ValueError(
                f"{self.key} would cost {self.cds_cost} fields, over the CDS limit of {limit}"
            )

    @property
    def key(self) -> str:
        return f"{self.kind}/{self.region}/{self.period_label}"

    @property
    def dataset(self) -> str:
        return load_config("era5")["datasets"][self.kind]["cds_name"]

    def cds_request(self) -> dict[str, Any]:
        cfg = load_config("era5")
        ds = cfg["datasets"][self.kind]
        years, months, days = _cds_axes(self.dates)
        if len(set(self.dates)) != len(self.dates) or not _is_product(self.dates):
            raise ValueError("dates must be exactly the real dates of a year × month × day product")
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
        """Identity of the request in the manifest (unique there).

        A stored request hashes its dataset and CDS payload only, as it always has, so
        the manifest's existing rows keep their hashes. A measurement (#10) also hashes
        its purpose and key, so it never collides with a stored request or with another
        measurement of the same payload under a different label.
        """
        ident: list[Any] = [self.dataset, self.cds_request()]
        if self.purpose != "store":
            ident += [self.purpose, self.key]
        return hashlib.sha256(canonical_json(ident).encode()).hexdigest()

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


def max_months(kind: str) -> int:
    """Most consecutive months one request of a kind may span (configs/era5.yaml, D63)."""
    return int(load_config("era5")["request"]["max_months_per_request"][kind])


def default_months(kind: str) -> int:
    """Months per request ``plan-area`` uses unless ``--months`` is given (configs/era5.yaml
    ``request.default_months_per_request``; D63)."""
    return int(load_config("era5")["request"]["default_months_per_request"][kind])


def _merge_months(groups: list[list[dt.date]], n: int, day_step: int) -> list[list[dt.date]]:
    """Merge one-month groups into calendar blocks of ``n`` months (D63).

    A block merges only when every one of its months is in the plan whole (every day, or
    every ``day_step``-th day, as planning keeps them). Any other month stays a request of
    its own, as in a monthly plan, so a block's key never depends on where a plan starts.
    """

    def whole(year: int, month: int) -> list[dt.date]:
        days = range(1, calendar.monthrange(year, month)[1] + 1, day_step)
        return [dt.date(year, month, d) for d in days]

    by_month = {(g[0].year, g[0].month): g for g in groups}
    out: list[list[dt.date]] = []
    done: set[tuple[int, int]] = set()
    for g in groups:
        y, m = g[0].year, g[0].month
        if (y, m) in done:
            continue
        first = (m - 1) // n * n + 1
        block = [(y, mm) for mm in range(first, min(first + n, 13))]
        if len(block) > 1 and all(by_month.get(k) == whole(*k) for k in block):
            out.append([d for k in block for d in by_month[k]])
            done.update(block)
        else:
            out.append(list(g))
    return out


def _refuse_over_limit(days: list[dt.date], per_day: int, limit: int) -> list[list[dt.date]]:
    """A multi-month group is never split (its parts wouldn't be products); refuse it."""
    cost = per_day * _product_size(days)
    if cost > limit:
        raise ValueError(
            f"{days[0]:%Y-%m}_{days[-1]:%Y-%m} would cost {cost} fields, over the CDS limit "
            f"of {limit}; plan fewer months per request"
        )
    return [days]


def _product_size(dates) -> int:
    years, months, days = _cds_axes(dates)
    return len(years) * len(months) * len(days)


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
    day_step: int = 1,
    months_per_request: int = 1,
) -> list[RequestSpec]:
    """Split [start, end] (inclusive) into day- or month-sized requests.

    ``months_per_request`` > 1 (with ``granularity="month"``, single levels only, at most
    ``request.max_months_per_request`` in ``configs/era5.yaml``) merges consecutive months
    into one request, in calendar blocks of that many months counted from January, never
    across a year: with 3, January–March, April–June, … (D63). Only a block whose months
    are all in the plan whole merges; any other month (a plan starting on the 10th, or in
    February) stays a request of its own, as in a monthly plan. So a block's key never
    depends on where a plan starts. A merged request over the CDS cost limit is refused,
    never split.

    With ``split`` (the default), any request over the CDS cost limit for its dataset
    (:func:`max_fields`) is cut into the fewest near-equal runs of days under it; a
    whole month of 5×5-box pressure levels (107,880 fields) becomes two requests.

    ``day_step`` > 1 keeps only days 1, 1 + step, 1 + 2·step, … of each month (e.g.
    Priyatikanto et al.'s 20 years sampled every 4th day, D31); mark such plans in the
    region name (e.g. ``timau@every4d``) so their stores are never mistaken for full ones.
    """
    if day_step < 1:
        raise ValueError("day_step must be >= 1")
    cfg = load_config("era5")["datasets"][kind]
    variables = tuple(variables or cfg["variables"].keys())
    if kind == "pl":
        levels = tuple(levels or cfg["levels_hpa"])
    if granularity not in ("day", "month"):
        raise ValueError("granularity must be 'day' or 'month'")
    if months_per_request < 1:
        raise ValueError("months_per_request must be >= 1")
    if months_per_request > 1:
        cap = max_months(kind)
        if months_per_request > cap:
            raise ValueError(
                f"{kind} requests may span at most {cap} month(s) "
                f"(configs/era5.yaml request.max_months_per_request), not {months_per_request}"
            )
        if granularity != "month":
            raise ValueError("months_per_request > 1 needs granularity='month'")
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    days = [d for d in days if (d.day - 1) % day_step == 0]
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
    per_day = len(variables) * (len(levels) if kind == "pl" else 1) * len(hours)
    if months_per_request > 1:
        groups = _merge_months(groups, months_per_request, day_step)
    if split:
        groups = [
            c
            for g in groups
            for c in (
                _split_to_limit(g, per_day, max_fields(kind))
                if len({(d.year, d.month) for d in g}) == 1
                else _refuse_over_limit(g, per_day, max_fields(kind))
            )
        ]
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


#: Region prefix for measurement requests, so their keys never mix with stored ones.
MEASURE_PREFIX = "measure-"


def measurement_request(
    kind: str,
    date: dt.date,
    hours: tuple[int, ...],
    area: Area | None = None,
    variables: tuple[str, ...] | None = None,
    levels: tuple[int, ...] | None = None,
    label: str | None = None,
) -> RequestSpec:
    """A one-off CDS test request (ticket #10): downloaded under the CDS gate (D39) and
    verified like any request, but never ingested and never reported as refused.

    ``area`` None means the whole globe. The default variables and levels are the
    kind's defaults (pressure levels: z, t, u, v, cc on 29 levels). The region is
    ``measure-<label>`` (default ``global``, or ``box`` with an area).
    """
    cfg = load_config("era5")["datasets"][kind]
    variables = tuple(variables or cfg["variables"].keys())
    if kind == "pl":
        levels = tuple(levels or cfg["levels_hpa"])
    elif levels is not None:
        raise ValueError(f"{kind} has no levels")
    label = label or ("global" if area is None else "box")
    return RequestSpec(
        kind=kind,
        region=MEASURE_PREFIX + label,
        dates=(date,),
        area=area,
        variables=variables,
        levels=levels if kind == "pl" else None,
        hours=tuple(hours),
        purpose="measure",
    )
