"""Shared helpers for tests that use the saved ICON-EU samples (ticket #55).

The samples are real ICON-EU fields of the 2026-11-26 06 UTC run from DWD opendata
(Deutscher Wetterdienst, CC BY 4.0; ``tests/fixtures/forecast/icon_eu/README.md``):

- ``box1deg``: every field the adapter reads, cut by us to 59.2-60.3° N × 9.2-10.3° E
  (17 × 17 points), every step 0-48, saved one bundle per step;
- ``whole-domain``: the step-0 ``WW`` file exactly as DWD served it.

A fake DWD serves each message as its own bz2 file at DWD's path, as the real server
does, plus the ``ww/`` directory listing ``latest_published`` reads.
"""

from __future__ import annotations

import bz2
import datetime as dt
import json
from pathlib import Path

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.sources import RunRef
from astroseeing.forecast.sources.gfs import RatePacer
from astroseeing.forecast.sources.icon_eu import DATA_DIR, IconEuAdapter

from fake_http import FakeHttpServer
from forecast_world import PUBLISHED, World

ICON_SAMPLES = (
    Path(__file__).resolve().parent / "fixtures" / "forecast" / "icon_eu" / "20261126T06Z"
)
ICON_RUN = RunRef("icon_eu", dt.datetime(2026, 11, 26, 6, tzinfo=dt.UTC))


def sample_messages(folder: Path = ICON_SAMPLES / "box1deg") -> dict[str, bytes]:
    """Every saved message, keyed by the DWD file name it was cut from (uncompressed)."""
    import eccodes as ec

    sources = json.loads((folder / "SOURCES.json").read_text())
    out: dict[str, bytes] = {}
    for bundle, entries in sources["bundles"].items():
        data = bz2.decompress((folder / bundle).read_bytes())
        messages = []
        while data:
            h = ec.codes_new_from_message(data)
            try:
                msg = ec.codes_get_message(h)
            finally:
                ec.codes_release(h)
            messages.append(msg)
            data = data[len(msg) :]
        if len(messages) != len(entries):
            raise ValueError(f"{bundle}: {len(messages)} messages, SOURCES lists {len(entries)}")
        out.update({e["file"]: m for e, m in zip(entries, messages, strict=True)})
    return out


def whole_domain_file(name: str) -> bytes:
    """A whole-domain sample, bz2-compressed exactly as DWD served it."""
    return (ICON_SAMPLES / "whole-domain" / name).read_bytes()


def dwd_path(name: str) -> str:
    """The URL path DWD serves a file at: ``<DATA_DIR>/<HH>/<field folder>/<name>``."""
    stamp = name.split("_")[4]  # icon-eu_europe_regular-lat-lon_<kind>_<YYYYMMDDHH>_...
    field = name.removesuffix(".grib2.bz2").rsplit("_", 1)[1].lower()
    return f"{DATA_DIR}/{stamp[8:10]}/{field}/{name}"


def serve_icon_samples(server, messages: dict[str, bytes], raw: dict[str, bytes] | None = None,
                       listed: bool = True) -> None:  # fmt: skip
    """Serve each message bz2-compressed at its DWD path (``raw`` entries as given, already
    compressed), and, if ``listed``, the ``ww/`` listings of the cycles they belong to."""
    raw = raw or {}
    for name, msg in messages.items():
        if name not in raw:
            server.route(dwd_path(name), bz2.compress(msg))
    for name, body in raw.items():
        server.route(dwd_path(name), body)
    if listed:
        listings: dict[str, list[str]] = {}
        for name in [*messages, *raw]:
            path = dwd_path(name)
            if "/ww/" in path:
                listings.setdefault(path.rsplit("/", 1)[0] + "/", []).append(name)
        for folder, names in listings.items():
            server.route(folder, listing_html(folder, sorted(names)))


def listing_html(folder: str, names: list[str]) -> bytes:
    """A directory listing in the form opendata.dwd.de serves (nginx autoindex)."""
    rows = "".join(
        f'<a href="{n}">{n[:50]}..&gt;</a> 26-Nov-2026 09:00:00              230425\n'
        for n in names
    )
    return (
        f"<html>\n<head><title>Index of {folder}</title></head>\n<body>\n"
        f'<h1>Index of {folder}</h1><hr><pre><a href="../">../</a>\n{rows}</pre><hr></body>\n'
        "</html>\n"
    ).encode()


def edit_message(message: bytes, **keys) -> bytes:
    """The message with GRIB keys changed (``level=400``, ``dataTime=1200``)."""
    import eccodes as ec

    h = ec.codes_new_from_message(message)
    try:
        for k, v in keys.items():
            ec.codes_set(h, k, v)
        return ec.codes_get_message(h)
    finally:
        ec.codes_release(h)


class IconWorld(World):
    """The tick test's CT in miniature with ICON-EU beside GFS in the Kongsberg area: a
    fake DWD opendata publishes the ICON-EU samples (the same 06z run) when the fake
    NOMADS publishes GFS's. ICON-EU's grid is the map grid, the finest global family."""

    def __init__(self, tmp_path, ephemeris):
        super().__init__(
            tmp_path,
            ephemeris,
            settings_edits={
                "areas.kongsberg.models": ["gfs", "icon_eu"],
                "areas.kongsberg.map_grid_model": "icon_eu",
            },
        )
        self.dwd = FakeHttpServer()
        self.dwd.__enter__()
        self.icon_eu = IconEuAdapter(
            self.settings.models["icon_eu"],
            HttpClient(timeout_s=5),
            self.settings.areas,
            base_url=self.dwd.url,
            pacer=RatePacer(None),
        )
        self.icon_published = False

    def at(self, now: dt.datetime):
        if now >= PUBLISHED and not self.icon_published:
            serve_icon_samples(self.dwd, sample_messages())
            self.icon_published = True
        return super().at(now)

    def adapters(self) -> dict:
        return {**super().adapters(), "icon_eu": self.icon_eu}

    def close(self):
        super().close()
        self.dwd.__exit__(None, None, None)
