"""The map page in headless Chromium (F1 spec Testing seam 5, Module 10; ticket #66).

The landing view is the map of the Kongsberg area. Its data are what the tick really
writes: F1-2's tick on the saved GFS samples (``forecast_world.World``) at 10:00 UTC
on 26 November, the 06z run in. Each test serves a copy and may edit it to set up its
case, as the tick would write it: a cell with no counted hours left (255), one whose
counted hours are all incomplete (254), one with none clear (0), an hour with no
value, or the IFS layers the tick writes for a family with no run yet (D86 item 5).

Colours are read back from the screen: a small square round a map cell's centre is
cut from a screenshot and its colours compared, so the tests see what a reader sees.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from forecast_world import DAY, World
from icon_eu_samples import IconWorld
from page_browser import Browser, PageSite, require_browser

MAP = "/forecast/"
CLOCK = "2026-11-26T10:05:00Z"


@pytest.fixture(scope="module")
def products(tmp_path_factory, ephemeris) -> Path:
    """The tick's products folder after the 10:00 tick."""
    require_browser()
    root = tmp_path_factory.mktemp("tick")
    world = World(root / "world", ephemeris)
    try:
        world.at(DAY + dt.timedelta(hours=10))
        shutil.copytree(
            world.paths.products,
            root / "products",
            ignore=shutil.ignore_patterns("places", "areas"),
        )
    finally:
        world.close()
    return root / "products"


class MapCase:
    """A served copy of the products, a site and a browser."""

    def __init__(self, tmp_path: Path, products: Path):
        self.data = tmp_path / "data"
        shutil.copytree(products, self.data)
        self.site_files = tmp_path / "site"
        self.site_files.mkdir()
        (self.site_files / "version.json").write_text(json.dumps({"commit": "c" * 40}))
        self.site = PageSite(self.data, self.site_files).__enter__()
        self.browser: Browser | None = None
        self.shots = tmp_path / "shots"
        self.shots.mkdir()

    # the served files ------------------------------------------------------------
    def latest(self) -> dict:
        return json.loads((self.data / "latest.json").read_text())

    def set_folder(self) -> Path:
        return self.data / self.latest()["set_path"]

    def layer(self, name: str) -> np.ndarray:
        e = self.latest()["layers"][name]
        raw = (self.set_folder() / e["file"]).read_bytes()
        return np.frombuffer(raw, np.dtype(e["dtype"]).newbyteorder("<")).reshape(e["shape"])

    def put_layer(self, name: str, values: np.ndarray, **entry) -> None:
        """Write a layer as the tick does (little-endian bytes, its entry's sha256)."""
        latest = self.latest()
        e = latest["layers"].get(name) or entry
        e.update(entry)
        arr = np.ascontiguousarray(values, dtype=np.dtype(e["dtype"]).newbyteorder("<"))
        data = arr.tobytes()
        (self.data / latest["set_path"] / e["file"]).write_bytes(data)
        e["shape"] = list(arr.shape)
        e["sha256"] = hashlib.sha256(data).hexdigest()
        latest["layers"][name] = e
        (self.data / "latest.json").write_text(json.dumps(latest))

    def add_family_without_run(self, family: str) -> None:
        """The three layers the tick writes for a global family with no run yet."""
        shape = self.layer("clear_left").shape
        hours = self.latest()["layers"]["total_cloud_gfs"]["hours"]
        seeing = {"file": f"seeing_fa_{family}.u16", "dtype": "uint16", "codes": {"65535": "none"}}
        cloud = {"file": f"total_cloud_{family}.u8", "dtype": "uint8", "codes": {"255": "no value"}}
        ground = {
            "file": f"model_ground_{family}.i16",
            "dtype": "int16",
            "codes": {"-32768": "no run"},
        }
        self.put_layer(
            f"seeing_fa_{family}", np.full(shape, 65535), **seeing, units="arcsec", scale=0.001
        )
        self.put_layer(f"total_cloud_{family}", np.full((len(hours), *shape), 255), **cloud,
                       units="percent", hours=hours)  # fmt: skip
        self.put_layer(f"model_ground_{family}", np.full(shape, -32768), **ground, units="m")

    # the browser -----------------------------------------------------------------
    def open(self, path: str = MAP, clock: str = CLOCK, **viewport) -> Browser:
        self.browser = Browser(self.site.origin, **viewport)
        self.browser.open(path, clock=clock)
        return self.browser

    def close(self) -> None:
        try:
            if self.browser is not None:
                errors = self.browser.call("consoleErrors")
                self.browser.close()
                assert errors == [], errors
        finally:
            self.site.__exit__(None, None, None)


@pytest.fixture
def case(tmp_path, products):
    c = MapCase(tmp_path, products)
    yield c
    c.close()


# -- reading the map back -------------------------------------------------------------


def wait_drawn(b: Browser) -> str:
    """Wait until the map has drawn the layer it shows now; return that layer's key."""
    body = "document.body.dataset"
    b.wait_for(f"{body}.mapDrawn && {body}.mapDrawn === {body}.mapKey", timeout_ms=20000)
    return b.eval("document.body.dataset.mapKey")


def cell_point(b: Browser, i: int, j: int, dy: float = 0.0, dx: float = 0.0) -> dict:
    """The page coordinates (CSS px) of map cell (i, j)'s centre, shifted by a fraction
    of a cell."""
    return b.eval(
        f"""(() => {{
          const g = window.forecastMap.grid, m = window.forecastMap.map;
          const lat = g.lat_north - ({i} + {dy}) * g.dlat, lon = g.lon_west + ({j} + {dx}) * g.dlon;
          const p = m.project([lon, lat]), r = m.getContainer().getBoundingClientRect();
          return {{ x: r.left + p.x, y: r.top + p.y }};
        }})()"""
    )


def colours(case: MapCase, b: Browser, i: int, j: int, half: int = 8) -> set[tuple[int, int, int]]:
    """The colours of a square of ``2 * half`` CSS px round map cell (i, j)'s centre."""
    p = cell_point(b, i, j)
    path = case.shots / f"cell-{i}-{j}.png"
    b.call("screenshot", path=str(path), clip={"x": p["x"] - half, "y": p["y"] - half,
                                               "width": 2 * half, "height": 2 * half})  # fmt: skip
    img = Image.open(io.BytesIO(path.read_bytes())).convert("RGB")
    return {tuple(p) for p in np.asarray(img).reshape(-1, 3)}


def card(b: Browser) -> dict:
    """The cell card's fields: field[/family] → (data-value, text)."""
    return b.eval(
        """(() => {
          const c = document.getElementById('cell-card');
          if (c.hidden) return null;
          const out = { row: +c.dataset.row, col: +c.dataset.col, text: c.textContent };
          for (const e of c.querySelectorAll('[data-field]')) {
            const k = e.dataset.field + (e.dataset.family ? '/' + e.dataset.family : '');
            out[k] = [e.dataset.value ?? null, e.textContent.trim()];
          }
          return out;
        })()"""
    )


def click_cell(b: Browser, i: int, j: int) -> None:
    p = cell_point(b, i, j, dy=0.2, dx=0.2)  # off the centre: no place marker there
    b.call("mouseClick", x=p["x"], y=p["y"])
    b.wait_for(f"document.getElementById('cell-card').dataset.row === '{i}' && "
               f"document.getElementById('cell-card').dataset.col === '{j}'")  # fmt: skip


def screenshot_dir() -> Path | None:
    d = os.environ.get("ASTRO_PAGE_SCREENSHOTS")
    if not d:
        return None
    Path(d).mkdir(parents=True, exist_ok=True)
    return Path(d)


# -- the tests ------------------------------------------------------------------------


def test_the_page_opens_on_the_clear_layer_with_254_and_255_drawn_distinctly_from_0(case):
    clear = case.layer("clear_left").copy()
    assert set(clear.ravel()) == {254}  # GFS alone: every counted hour incomplete
    clear[0, 0], clear[0, 2], clear[0, 3] = 255, 0, 6
    case.put_layer("clear_left", clear)

    b = case.open()
    assert b.eval("document.body.dataset.view") == "map"
    assert b.eval("document.getElementById('tonight').hidden") is True
    assert b.eval("document.querySelector('input[name=layer]:checked').value") == "clear"
    key = wait_drawn(b)
    assert case.latest()["set_id"] in key and "clear_left" in key
    if (d := screenshot_dir()) is not None:
        b.call("screenshot", path=str(d / "clear-desktop-small-box.png"), fullPage=True)

    no_counted, incomplete, none_clear, six = (colours(case, b, 0, j) for j in (0, 1, 2, 3))
    # 0 and 6 are flat colours; 254 and 255 are patterns of two colours each
    assert len(none_clear) == 1 and len(six) == 1, (none_clear, six)
    assert len(no_counted) >= 2 and len(incomplete) >= 2, (no_counted, incomplete)
    assert len({frozenset(s) for s in (no_counted, incomplete, none_clear, six)}) == 4
    assert not (none_clear & no_counted) and not (none_clear & incomplete)
    # the legend names both codes
    legend = b.eval("document.getElementById('legend').textContent")
    assert "No counted hours left" in legend and "every counted hour left is incomplete" in legend


def test_clicking_kongsberg_opens_its_table_and_back_returns_to_the_map(case):
    b = case.open()
    wait_drawn(b)
    b.call("click", selector=".place-marker")
    b.wait_for("document.body.dataset.view === 'place'")
    assert b.eval("location.hash") == "#place/kongsberg"
    assert b.eval("document.getElementById('map-view').hidden") is True
    assert b.eval("document.getElementById('tonight').hidden") is False
    assert b.eval("document.getElementById('place-name').textContent") == "Kongsberg"
    assert b.eval("document.querySelectorAll('#hours td[data-model=\"gfs\"]').length") > 0
    assert b.eval("document.getElementById('cell-card').hidden") is True  # no card from the click

    b.call("click", selector=".back a")
    b.wait_for("document.body.dataset.view === 'map'")
    assert b.eval("document.getElementById('tonight').hidden") is True
    wait_drawn(b)


def test_a_place_link_opens_its_view_straight_away(case):
    b = case.open("/forecast/#place/kongsberg")
    assert b.eval("document.body.dataset.view") == "place"
    assert b.eval("document.getElementById('place-name').textContent") == "Kongsberg"


def test_clicking_elsewhere_opens_the_cell_card_with_that_cells_layer_values(case):
    clear, counted, incomplete = (
        case.layer(n).copy() for n in ("clear_left", "counted_left", "incomplete_left")
    )
    clear[4, 1], counted[4, 1], incomplete[4, 1] = 5, 11, 2  # as if a second model had values
    clear[4, 3], counted[4, 3], incomplete[4, 3] = 255, 0, 0
    for name, arr in (
        ("clear_left", clear),
        ("counted_left", counted),
        ("incomplete_left", incomplete),
    ):
        case.put_layer(name, arr)
    seeing, ground, dark = (
        case.layer("seeing_fa_gfs"),
        case.layer("model_ground_gfs"),
        case.layer("dark_left_min"),
    )

    b = case.open()
    wait_drawn(b)
    assert b.eval("document.getElementById('cell-card').hidden") is True

    click_cell(b, 4, 1)
    c = card(b)
    assert c["clear_left"][0] == "5"
    assert (
        c["clear_left"][1] == "5 of 11 counted hours left look clear on most models (2 incomplete)."
    )
    assert "at the models' ground, not your terrain height" in c["text"].lower()
    assert "uncalibrated" in c["text"]
    assert c["seeing/gfs"] == [str(seeing[4, 1]), f"seeing {seeing[4, 1] / 1000:.2f}″"]
    assert c["model_ground/gfs"] == [str(ground[4, 1]), f"model ground {ground[4, 1]} m"]
    minutes = int(dark[4, 1])
    assert c["dark_left"] == [
        str(minutes),
        f"{minutes // 60} h {minutes % 60} min of dark time left.",
    ]
    assert "GFS 0.25° (39 levels)" in c["text"]

    click_cell(b, 0, 0)
    c = card(b)
    assert c["clear_left"] == [
        "254",
        "Not known: all 12 counted hours left are incomplete (fewer than two models have a value).",
    ]
    assert c["seeing/gfs"][0] == str(seeing[0, 0])

    click_cell(b, 4, 3)
    assert card(b)["clear_left"] == ["255", "No counted hours left tonight."]

    b.call("click", selector=".card-close")
    b.wait_for("document.getElementById('cell-card').hidden")


def test_the_model_picker_changes_the_seeing_layer_default_gfs(case):
    case.add_family_without_run("ifs")  # IFS's layers before its first run: no values
    b = case.open()
    wait_drawn(b)
    assert b.eval("document.getElementById('model-pick').hidden") is True  # not for clear hours

    b.call("click", selector="input[name=layer][value=seeing]")
    key = wait_drawn(b)
    assert "seeing_fa_gfs" in key
    assert b.eval("document.getElementById('model').value") == "gfs"
    options = b.eval(
        "[...document.querySelectorAll('#model option')].map(o => [o.value, o.textContent])"
    )
    assert options == [["gfs", "GFS 0.25°"], ["ifs", "IFS"]]
    legend = b.eval("document.getElementById('legend').textContent")
    assert "uncalibrated" in legend and "GFS 0.25°" in legend
    gfs = [colours(case, b, 0, j) for j in range(5)]  # row 0: no coast or marker on it
    assert all(len(s) == 1 for s in gfs)  # GFS has seeing everywhere: flat colours
    assert len({frozenset(s) for s in gfs}) > 1  # which differ from cell to cell

    b.call("selectOption", selector="#model", value="ifs")
    key = wait_drawn(b)
    assert "seeing_fa_ifs" in key
    ifs = [colours(case, b, 0, j) for j in range(5)]
    assert all(len(s) >= 2 for s in ifs)  # "no value" everywhere: the hatch
    assert len({frozenset(s) for s in ifs}) == 1 and not ifs[0] & gfs[0]
    assert "IFS" in b.eval("document.getElementById('legend').textContent")

    click_cell(b, 2, 2)
    c = card(b)
    assert c["seeing/ifs"] == ["65535", "seeing: no value"]
    assert c["model_ground/ifs"] == ["-32768", "no run"]


def test_the_hour_slider_steps_through_the_hours_and_a_no_value_hour_shows_no_value(case):
    cloud = case.layer("total_cloud_gfs").copy()
    hours = case.latest()["layers"]["total_cloud_gfs"]["hours"]
    assert len(hours) == 24 and 255 not in cloud
    cloud[9] = 255  # 21 UTC: as on one of IFS's in-between hours
    cloud[8, 2, 2] = 0
    cloud[10, 2, 2] = 100
    case.put_layer("total_cloud_gfs", cloud)

    b = case.open(clock="2026-11-26T19:40:00Z")  # 20:40 in Kongsberg
    wait_drawn(b)
    assert b.eval("document.getElementById('hour-pick').hidden") is True
    b.call("click", selector="input[name=layer][value=cloud]")
    key = wait_drawn(b)
    # the slider starts at the hour that holds the page's "now"
    assert key.endswith("/total_cloud_gfs/7")
    label = "document.getElementById('hour-label')"
    assert b.eval(f"{label}.dataset.time") == hours[7] == "2026-11-26T19:00:00Z"
    assert b.eval(f"{label}.textContent") == "Thu 26 Nov 20:00"

    b.call("press", selector="#hour", key="ArrowRight")
    assert wait_drawn(b).endswith("/total_cloud_gfs/8")
    clear_sky = colours(case, b, 2, 2)
    assert len(clear_sky) == 1
    click_cell(b, 2, 2)
    assert card(b)["cloud/gfs"] == ["0", "cloud at 21:00: 0 %"]

    b.call("press", selector="#hour", key="ArrowRight")
    assert wait_drawn(b).endswith("/total_cloud_gfs/9")
    assert b.eval(f"{label}.dataset.none") == "true"
    assert "No value from GFS 0.25° at this hour" in b.eval(f"{label}.textContent")
    none = [colours(case, b, i, j) for i, j in ((0, 0), (2, 2), (4, 4))]
    assert all(len(s) >= 2 for s in none) and not none[0] & clear_sky  # the hatch, never 0 %
    assert card(b)["cloud/gfs"] == ["255", "cloud at 22:00: no value"]

    b.call("press", selector="#hour", key="ArrowRight")
    assert wait_drawn(b).endswith("/total_cloud_gfs/10")
    assert b.eval(f"{label}.dataset.none") == "false"
    overcast = colours(case, b, 2, 2)
    assert len(overcast) == 1 and overcast != clear_sky
    assert card(b)["cloud/gfs"] == ["100", "cloud at 23:00: 100 %"]


def test_the_dark_hours_layer_shows_the_minutes_left_and_none_as_its_own_colour(case):
    dark = case.layer("dark_left_min").copy()
    dark[0, 0], dark[0, 1], dark[0, 2] = 0, 0, 16 * 60
    case.put_layer("dark_left_min", dark)
    b = case.open()
    wait_drawn(b)
    b.call("click", selector="input[name=layer][value=dark]")
    assert wait_drawn(b).endswith("/dark_left_min/")
    assert b.eval("document.getElementById('model-pick').hidden") is True
    legend = b.eval("document.getElementById('legend').textContent")
    assert legend.startswith("Dark time left tonight") and "null" not in legend
    none, none2, long = (colours(case, b, 0, j) for j in range(3))
    assert none == none2 and len(none) == 1 and len(long) == 1 and none != long
    click_cell(b, 0, 0)
    assert card(b)["dark_left"] == ["0", "No dark time left tonight."]
    click_cell(b, 0, 2)
    assert card(b)["dark_left"] == ["960", "16 h 0 min of dark time left."]


def test_no_request_leaves_the_host(case):
    case.add_family_without_run("ifs")
    b = case.open()
    wait_drawn(b)
    for layer in ("seeing", "dark", "cloud"):
        b.call("click", selector=f"input[name=layer][value={layer}]")
        wait_drawn(b)
    b.call("selectOption", selector="#model", value="ifs")
    wait_drawn(b)
    click_cell(b, 1, 1)
    b.call("click", selector=".place-marker")
    b.wait_for("document.body.dataset.view === 'place'")
    requests = b.call("requests")
    assert requests and not [r for r in requests if r["blocked"]], requests
    http = [r["url"] for r in requests if r["url"].startswith("http")]
    assert all(u.startswith(case.site.origin + "/") for u in http), http
    paths = {r.path for r in case.site.requests}
    assert {"/vendor/maplibre-gl-5.24.1/maplibre-gl.js", "/vendor/natural-earth/outline-kongsberg-box.json"} <= paths
    # the map's tiles are painted in the page itself, never fetched
    assert not [p for p in paths if "cells" in p]


def test_a_390px_phone_width_works(case):
    b = case.open(width=390, height=844, scale=2, touch=True)
    wait_drawn(b)
    widths = b.eval(
        """({ page: document.documentElement.scrollWidth, view: window.innerWidth,
              map: document.getElementById('map').getBoundingClientRect().width })"""
    )
    assert widths["view"] == 390 and widths["page"] <= 390, widths
    assert 300 <= widths["map"] <= 390 - 2 * 16
    p = cell_point(b, 1, 3, dy=0.2, dx=0.2)
    b.call("tap", x=p["x"], y=p["y"])
    b.wait_for("document.getElementById('cell-card').dataset.row === '1'")
    assert b.eval("document.documentElement.scrollWidth") <= 390
    card_box = b.eval("document.getElementById('cell-card').getBoundingClientRect().toJSON()")
    assert card_box["left"] >= 16 and card_box["right"] <= 390 - 16 + 0.5
    b.call("click", selector="input[name=layer][value=cloud]")
    wait_drawn(b)
    assert b.eval("document.documentElement.scrollWidth") <= 390


def test_a_new_set_redraws_the_map_and_the_open_card(case):
    b = case.open()
    first = wait_drawn(b)
    click_cell(b, 1, 1)
    old = case.latest()
    # the tick writes a new set: the same files under a new set id, one cell changed
    new_id = "20261126T101500Z-0123abcd"
    shutil.copytree(case.set_folder(), case.data / f"sets/{new_id}")
    latest = {
        **old,
        "set_id": new_id,
        "set_path": f"sets/{new_id}/",
        "written_at": "2026-11-26T10:15:00Z",
    }
    (case.data / "latest.json").write_text(json.dumps(latest))
    clear = case.layer("clear_left").copy()
    clear[1, 1] = 3
    case.put_layer("clear_left", clear)

    b.run_clock(5 * 60 * 1000)
    b.wait_for(f"document.body.dataset.setId === '{new_id}'")
    key = wait_drawn(b)
    assert key != first and key.startswith(new_id + "/")
    b.wait_for("document.querySelector('#cell-card [data-field=clear_left]').dataset.value === '3'")


# -- with ICON-EU: the map grid is ICON-EU's, GFS shows as coarser blocks ----------------


@pytest.fixture(scope="module")
def icon_products(tmp_path_factory, ephemeris) -> Path:
    """The tick's products after the 10:00 tick with GFS and ICON-EU (17 × 17 cells)."""
    require_browser()
    root = tmp_path_factory.mktemp("icon-tick")
    world = IconWorld(root / "world", ephemeris)
    try:
        world.at(DAY + dt.timedelta(hours=10))
        shutil.copytree(
            world.paths.products,
            root / "products",
            ignore=shutil.ignore_patterns("places", "areas"),
        )
    finally:
        world.close()
    return root / "products"


def row_colours(case: MapCase, b: Browser, i: int, n: int) -> list[frozenset]:
    return [frozenset(colours(case, b, i, j, half=3)) for j in range(n)]


@pytest.mark.slow  # ~35 s: the tick fetches the ICON-EU samples from the fake DWD
def test_gfs_is_drawn_in_coarser_blocks_than_icon_eu(tmp_path, icon_products):
    case = MapCase(tmp_path, icon_products)
    try:
        g = case.latest()["grid"]
        assert (g["nlat"], g["nlon"], g["dlat"]) == (17, 17, 0.0625)  # ICON-EU's grid
        gfs, icon = case.layer("seeing_fa_gfs"), case.layer("seeing_fa_icon")
        row = 0  # no coast or marker on it
        b = case.open()
        wait_drawn(b)
        b.call("click", selector="input[name=layer][value=seeing]")
        assert "seeing_fa_gfs" in wait_drawn(b)
        shown_gfs = row_colours(case, b, row, 17)
        b.call("selectOption", selector="#model", value="icon")
        assert "seeing_fa_icon" in wait_drawn(b)
        shown_icon = row_colours(case, b, row, 17)
        assert (
            b.eval("document.querySelector('#model option[value=icon]').textContent") == "ICON-EU"
        )

        # each cell is one flat colour, the same wherever the layer holds the same value
        for shown, values in ((shown_gfs, gfs[row]), (shown_icon, icon[row])):
            assert all(len(s) == 1 for s in shown)
            for j in range(1, 17):
                if values[j] == values[j - 1]:
                    assert shown[j] == shown[j - 1], (j, values)
        # GFS's 0.25° points cover several map cells each; ICON-EU's change cell by cell
        assert len(set(gfs[row])) <= 5 < len(set(icon[row]))
        assert len(set(shown_gfs)) <= 5 < len(set(shown_icon))
    finally:
        case.close()


def _screenshot_case(case: MapCase) -> None:
    """Cells with no counted hours left (255) and all incomplete (254) beside the real
    values, as the tick writes them later in the night or with a model missing."""
    clear, counted, incomplete = (
        case.layer(n).copy() for n in ("clear_left", "counted_left", "incomplete_left")
    )
    clear[13:17, 0:3], counted[13:17, 0:3], incomplete[13:17, 0:3] = 255, 0, 0
    clear[13:17, 3:6], incomplete[13:17, 3:6] = 254, counted[13:17, 3:6]
    for name, arr in (
        ("clear_left", clear),
        ("counted_left", counted),
        ("incomplete_left", incomplete),
    ):
        case.put_layer(name, arr)


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("ASTRO_PAGE_SCREENSHOTS"), reason="only for the PR's screenshots"
)
@pytest.mark.parametrize("width", [1440, 390])
def test_screenshots(tmp_path, icon_products, width):
    """The PR's screenshots (ticket #66): ``ASTRO_PAGE_SCREENSHOTS=<folder>``."""
    case = MapCase(tmp_path, icon_products)
    try:
        _screenshot_case(case)
        d = screenshot_dir()
        phone = width == 390
        b = case.open(width=width, height=844 if phone else 900, scale=2, touch=phone)
        wait_drawn(b)
        click_cell(b, 12, 12)  # clear of the Kongsberg label
        b.call("screenshot", path=str(d / f"{width}-clear-and-card.png"), fullPage=True)
        b.call("click", selector=".card-close")
        b.call("click", selector="input[name=layer][value=seeing]")
        wait_drawn(b)
        b.call("screenshot", path=str(d / f"{width}-seeing-gfs.png"), fullPage=True)
        b.call("selectOption", selector="#model", value="icon")
        wait_drawn(b)
        click_cell(b, 4, 4)
        b.call("screenshot", path=str(d / f"{width}-seeing-icon-eu-and-card.png"), fullPage=True)
        b.call("click", selector=".card-close")
        b.call("click", selector="input[name=layer][value=cloud]")
        for _ in range(12):  # to 01:00 in Kongsberg, as the front comes in
            b.call("press", selector="#hour", key="ArrowRight")
        wait_drawn(b)
        b.call("screenshot", path=str(d / f"{width}-cloud-by-hour.png"), fullPage=True)
        b.call("click", selector="input[name=layer][value=dark]")
        wait_drawn(b)
        b.call("screenshot", path=str(d / f"{width}-dark-hours-left.png"), fullPage=not phone)
    finally:
        case.close()


def test_the_vendored_files_match_their_recorded_checksums():
    vendor = Path(__file__).resolve().parent.parent / "web" / "vendor"
    listed = {}
    for line in (vendor / "CHECKSUMS.sha256").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        listed[name] = digest
    on_disk = {
        p.relative_to(vendor).as_posix()
        for p in vendor.rglob("*")
        if p.is_file() and p.name not in {"README.md", "CHECKSUMS.sha256"}
    }
    assert set(listed) == on_disk
    for name, digest in listed.items():
        assert hashlib.sha256((vendor / name).read_bytes()).hexdigest() == digest, name
    page = (vendor.parent / "forecast" / "index.html").read_text()
    assert '<script src="../vendor/maplibre-gl-5.24.1/maplibre-gl.js"' in page
