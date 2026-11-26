"""Forecast settings: the one file (``configs/forecast.yaml``) every forecast part reads.

``load_settings()`` parses and validates the file into frozen dataclasses and refuses
anything it can't vouch for: a missing value, an unknown key (a typo would otherwise
be ignored), a wrong type, or settings that contradict each other. Nothing has a
default in code, so the file alone says what ran, and ``ForecastSettings.config_hash``
(SHA-256 of the file's data as canonical JSON) identifies it in every product's
provenance.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from astroseeing.config import config_dir
from astroseeing.provenance import config_hash

SCHEMA = "forecast-settings/1"

#: Fog signals a model can carry, in RunFields' vocabulary (D49 item 3).
FOG_SIGNALS = ("fog_fraction_pct", "visibility_m", "weather_code", "dewpoint_depression_2m_k")


class SettingsError(ValueError):
    """The forecast settings file is missing a value, has an unknown one, or is inconsistent."""


@dataclass(frozen=True)
class Host:
    name: str
    url: str
    max_requests_per_s: float | None


@dataclass(frozen=True)
class Hosts:
    main: Host
    fallback: Host | None


@dataclass(frozen=True)
class Grid:
    """A model's native grid: regular lat-lon (spacing in degrees) or Lambert (km)."""

    kind: str  # "regular_latlon" or "lambert"
    spacing: float
    units: str  # "deg" or "km"


@dataclass(frozen=True)
class Model:
    """One forecast model version and what its runs must contain (spec Module 1)."""

    id: str
    name: str
    family: str
    regional: bool
    runs_utc: tuple[int, ...]
    steps_h: tuple[int, ...]
    publish_delay_h: float
    online_window_h: float
    hosts: Hosts
    grid: Grid
    pressure_levels_hpa: tuple[float, ...]  # bottom → top
    level_cloud: bool
    fog_signals: tuple[str, ...]

    @property
    def level_count(self) -> int:
        return len(self.pressure_levels_hpa)


@dataclass(frozen=True)
class Box:
    west: float
    east: float
    south: float
    north: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east


@dataclass(frozen=True)
class Area:
    id: str
    box: Box
    models: tuple[str, ...]
    map_grid_model: str


@dataclass(frozen=True)
class PlaceHeight:
    """A saved place's ground height (GLO-30), and where the number came from."""

    metres: float
    source: str  # "hand-entered" or "glo30"
    tile: str | None
    sha256: str | None


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    lat: float
    lon: float
    time_zone: str
    area: str
    height: PlaceHeight | None


@dataclass(frozen=True)
class CloudClasses:
    clear_max_pct: float
    some_cloud_max_pct: float


@dataclass(frozen=True)
class RunRules:
    stale_after_h: float
    late_after_delay_h: float
    abandon_before_window_end_h: float
    file_retries: int
    retry_spacing_min: float
    fallback_after_main_failed_h: float


@dataclass(frozen=True)
class Alerts:
    no_complete_run_h: float
    no_tick_h: float
    staging_min_free_gb: float


@dataclass(frozen=True)
class Eso:
    fetch_time_utc: str
    refetch_after_days: int


@dataclass(frozen=True)
class ForecastSettings:
    models: Mapping[str, Model]
    areas: Mapping[str, Area]
    default_place: str
    places: Mapping[str, Place]
    cloud_classes: CloudClasses
    run_rules: RunRules
    alerts: Alerts
    eso: Eso
    config_hash: str
    raw: Mapping[str, Any]  # the file's data, as hashed: treat as read-only


def default_settings_path() -> Path:
    return Path(str(config_dir() / "forecast.yaml"))


def load_settings(path: Path | None = None) -> ForecastSettings:
    """Load and validate the forecast settings (default: ``<config dir>/forecast.yaml``)."""
    path = Path(path) if path is not None else default_settings_path()
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise SettingsError(f"forecast settings {path}: not valid YAML: {e}") from e
    return _parse_settings(raw, source=str(path))


def _parse_settings(raw: Any, source: str) -> ForecastSettings:
    """Validate loaded settings data; ``source`` names the file in error messages."""
    root = _Node(raw, "", source)
    root.text("schema", allowed=(SCHEMA,))
    models = {mid: _model(mid, node) for mid, node in root.map("models").items()}
    areas = {aid: _area(aid, node, models) for aid, node in root.map("areas").items()}
    places = {pid: _place(pid, node, areas) for pid, node in root.map("places").items()}
    default_place = root.text("default_place", allowed=tuple(places))
    cc = root.node("cloud_classes")
    cloud = CloudClasses(cc.number("clear_max_pct"), cc.number("some_cloud_max_pct"))
    if not 0 <= cloud.clear_max_pct < cloud.some_cloud_max_pct <= 100:
        raise cc.error("needs 0 <= clear_max_pct < some_cloud_max_pct <= 100")
    cc.done()
    rr = root.node("run_rules")
    run_rules = RunRules(
        stale_after_h=rr.number("stale_after_h", positive=True),
        late_after_delay_h=rr.number("late_after_delay_h", positive=True),
        abandon_before_window_end_h=rr.number("abandon_before_window_end_h", positive=True),
        file_retries=rr.integer("file_retries", minimum=1),
        retry_spacing_min=rr.number("retry_spacing_min", positive=True),
        fallback_after_main_failed_h=rr.number("fallback_after_main_failed_h", positive=True),
    )
    rr.done()
    al = root.node("alerts")
    alerts = Alerts(
        no_complete_run_h=al.number("no_complete_run_h", positive=True),
        no_tick_h=al.number("no_tick_h", positive=True),
        staging_min_free_gb=al.number("staging_min_free_gb", positive=True),
    )
    al.done()
    es = root.node("eso")
    eso = Eso(es.text("fetch_time_utc"), es.integer("refetch_after_days", minimum=1))
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", eso.fetch_time_utc):
        raise es.error(f"fetch_time_utc must be HH:MM (UTC), got {eso.fetch_time_utc!r}")
    es.done()
    root.done()
    return ForecastSettings(
        models=models,
        areas=areas,
        default_place=default_place,
        places=places,
        cloud_classes=cloud,
        run_rules=run_rules,
        alerts=alerts,
        eso=eso,
        config_hash=config_hash(raw),
        raw=raw,
    )


def _model(mid: str, n: _Node) -> Model:
    runs = n.seq("runs_utc", int)
    if not runs or any(not 0 <= h <= 23 for h in runs) or list(runs) != sorted(set(runs)):
        raise n.error("runs_utc must be distinct UTC hours 0-23, in order")
    st = n.node("steps")
    first, last = st.integer("first_h", minimum=0), st.integer("last_h")
    every = st.integer("every_h", minimum=1)
    if last < first:
        raise st.error("last_h must not be before first_h")
    st.done()
    hosts_n = n.node("hosts")
    fallback = hosts_n.node("fallback", nullable=True)
    hosts = Hosts(_host(hosts_n.node("main")), _host(fallback) if fallback else None)
    hosts_n.done()
    ex = n.node("expected")
    g = ex.node("grid")
    kind = g.text("kind", allowed=("regular_latlon", "lambert"))
    units = "deg" if kind == "regular_latlon" else "km"
    grid = Grid(kind, g.number(f"spacing_{units}", positive=True), units)
    g.done()
    levels = ex.seq("pressure_levels_hpa", (int, float))
    if not levels or any(b <= a for a, b in zip(levels[1:], levels, strict=False)):
        raise ex.error("pressure_levels_hpa must be strictly decreasing (bottom → top)")
    level_cloud = ex.flag("level_cloud")
    fog = ex.seq("fog_signals", str)
    unknown = sorted(set(fog) - set(FOG_SIGNALS))
    if unknown:
        raise ex.error(f"unknown fog signal(s) {unknown}; known: {list(FOG_SIGNALS)}")
    ex.done()
    model = Model(
        id=mid,
        name=n.text("name"),
        family=n.text("family"),
        regional=n.flag("regional"),
        runs_utc=runs,
        steps_h=tuple(range(first, last + 1, every)),
        publish_delay_h=n.number("publish_delay_h", positive=True),
        online_window_h=n.number("online_window_h", positive=True),
        hosts=hosts,
        grid=grid,
        pressure_levels_hpa=tuple(float(p) for p in levels),
        level_cloud=level_cloud,
        fog_signals=fog,
    )
    n.done()
    return model


def _host(n: _Node) -> Host:
    url = n.text("url")
    if not re.fullmatch(r"https://[^/\s]+", url):
        raise n.error(f"url must be https://<host> with no path, got {url!r}")
    rate = n.get("max_requests_per_s", (int, float), nullable=True)
    if rate is not None and rate <= 0:
        raise n.error("max_requests_per_s must be positive or null")
    host = Host(n.text("name"), url, None if rate is None else float(rate))
    n.done()
    return host


def _area(aid: str, n: _Node, models: Mapping[str, Model]) -> Area:
    b = n.node("box")
    box = Box(b.number("west"), b.number("east"), b.number("south"), b.number("north"))
    if not (-180 <= box.west < box.east <= 180 and -90 <= box.south < box.north <= 90):
        raise b.error("needs -180 <= west < east <= 180 and -90 <= south < north <= 90")
    b.done()
    area_models = n.seq("models", str)
    unknown = sorted(set(area_models) - set(models))
    if unknown or not area_models:
        raise n.error(f"models must name configured models; unknown: {unknown}")
    grid_model = n.text("map_grid_model", allowed=area_models)
    if models[grid_model].regional:
        raise n.error(f"map_grid_model {grid_model!r} is regional-only; the grid is a global one")
    n.done()
    return Area(aid, box, area_models, grid_model)


def _place(pid: str, n: _Node, areas: Mapping[str, Area]) -> Place:
    tz = n.text("time_zone")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise n.error(f"time_zone {tz!r} is not an IANA time zone") from e
    area = n.text("area", allowed=tuple(areas))
    lat, lon = n.number("lat"), n.number("lon")
    if not areas[area].box.contains(lat, lon):
        raise n.error(f"({lat}, {lon}) lies outside area {area!r}")
    h = n.node("height", nullable=True)
    height = None
    if h is not None:
        height = PlaceHeight(
            metres=h.number("metres"),
            source=h.text("source", allowed=("hand-entered", "glo30")),
            tile=h.get("tile", str, nullable=True),
            sha256=h.get("sha256", str, nullable=True),
        )
        if height.source == "glo30" and not (height.tile and height.sha256):
            raise h.error("a GLO-30 height needs its tile and sha256")
        h.done()
    place = Place(pid, n.text("name"), lat, lon, tz, area, height)
    n.done()
    return place


class _Node:
    """One mapping in the settings, read key by key so leftovers can be refused."""

    def __init__(self, data: Any, path: str, source: str):
        self.path, self.source = path, source
        if not isinstance(data, Mapping):
            raise self.error(f"must be a mapping, got {type(data).__name__}")
        self.data, self.seen = data, set()

    def error(self, msg: str) -> SettingsError:
        return SettingsError(f"{self.source}: {self.path or '(top level)'}: {msg}")

    def _key(self, key: str) -> str:
        return f"{self.path}.{key}" if self.path else key

    def get(self, key: str, types: type | tuple[type, ...], nullable: bool = False) -> Any:
        self.seen.add(key)
        if key not in self.data:
            raise SettingsError(f"{self.source}: missing required value {self._key(key)}")
        value = self.data[key]
        if value is None and nullable:
            return None
        if isinstance(value, bool) and bool not in _as_tuple(types):
            value_ok = False  # YAML true/false is not a number
        else:
            value_ok = isinstance(value, types)
        if not value_ok:
            raise SettingsError(
                f"{self.source}: {self._key(key)} must be {_type_names(types)}"
                f"{' or null' if nullable else ''}, got {value!r}"
            )
        return value

    def text(self, key: str, allowed: tuple[str, ...] | None = None) -> str:
        value = self.get(key, str)
        if allowed is not None and value not in allowed:
            raise SettingsError(f"{self.source}: {self._key(key)} is {value!r}; one of {allowed}")
        return value

    def number(self, key: str, positive: bool = False) -> float:
        value = float(self.get(key, (int, float)))
        if positive and not value > 0:
            raise SettingsError(f"{self.source}: {self._key(key)} must be positive")
        return value

    def integer(self, key: str, minimum: int | None = None) -> int:
        value = self.get(key, int)
        if minimum is not None and value < minimum:
            raise SettingsError(f"{self.source}: {self._key(key)} must be >= {minimum}")
        return value

    def flag(self, key: str) -> bool:
        return self.get(key, bool)

    def seq(self, key: str, item_types: type | tuple[type, ...]) -> tuple[Any, ...]:
        value = self.get(key, list)
        for i, item in enumerate(value):
            if isinstance(item, bool) or not isinstance(item, item_types):
                raise SettingsError(
                    f"{self.source}: {self._key(key)}[{i}] must be {_type_names(item_types)}, "
                    f"got {item!r}"
                )
        return tuple(value)

    def node(self, key: str, nullable: bool = False) -> _Node | None:
        value = self.get(key, Mapping, nullable=nullable)
        return None if value is None else _Node(value, self._key(key), self.source)

    def map(self, key: str) -> dict[str, _Node]:
        """A mapping of id → entry (models, areas, places); ids are lowercase words."""
        outer = self.node(key)
        out = {}
        for k in outer.data:
            if not (isinstance(k, str) and re.fullmatch(r"[a-z][a-z0-9_]*", k)):
                raise outer.error(f"ids must be lowercase words, got {k!r}")
            out[k] = outer.node(k)
        if not out:
            raise outer.error("must not be empty")
        return out

    def done(self) -> None:
        extra = sorted(str(k) for k in set(self.data) - self.seen)
        if extra:
            raise self.error(f"unknown key(s) {extra}")


def _as_tuple(types: type | tuple[type, ...]) -> tuple[type, ...]:
    return types if isinstance(types, tuple) else (types,)


def _type_names(types: type | tuple[type, ...]) -> str:
    names = {int: "an integer", float: "a number", str: "text", bool: "true/false",
             list: "a list", Mapping: "a mapping"}  # fmt: skip
    return " or ".join(names.get(t, t.__name__) for t in _as_tuple(types))
