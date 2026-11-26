"""The forecast page in headless Chromium (F1 spec Testing seam 5; ticket #52).

The page's data are what F1-2's tick really writes: the tick runs on the saved GFS
samples (``forecast_world.World``) at 09:00 UTC on 26 November, before the 06z run is
published (set A: every GFS hour missing), and at 10:00, with it (set B). Each test
serves a copy of those products and may edit the copy to set up its case (a blanked
hour, a stale run), as the back end would write it.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from forecast_world import DAY, World
from page_browser import Browser, PageSite, require_browser

PAGE = "/forecast/"
OSLO = ZoneInfo("Europe/Oslo")
PAGE_COMMIT = "c" * 40


@pytest.fixture(scope="module")
def products(tmp_path_factory, ephemeris) -> dict[str, Path]:
    """The tick's products folder after the 09:00 tick (``"a"``) and the 10:00 tick
    (``"b"``)."""
    require_browser()
    root = tmp_path_factory.mktemp("tick")
    world = World(root / "world", ephemeris)
    out = {}
    try:
        for name, hour in (("a", 9), ("b", 10)):
            world.at(DAY + dt.timedelta(hours=hour))
            out[name] = root / name
            shutil.copytree(
                world.paths.products, out[name], ignore=shutil.ignore_patterns("places")
            )
    finally:
        world.close()
    return out


class Case:
    """One served copy of the products, a site and a browser."""

    def __init__(self, tmp_path: Path, products: dict[str, Path], which: str):
        self.data = tmp_path / "data"
        shutil.copytree(products["b"], self.data)
        # set A's files sit beside set B's (the tick keeps the last 3 sets)
        shutil.copytree(products["a"] / "sets", self.data / "sets", dirs_exist_ok=True)
        self.latest_a = json.loads((products["a"] / "latest.json").read_text())
        self.latest_b = json.loads((products["b"] / "latest.json").read_text())
        self.use_latest(self.latest_a if which == "a" else self.latest_b)
        self.site_files = tmp_path / "site"
        self.site_files.mkdir()
        # what `astro web deploy` (F1-13) records beside the page: its own commit
        (self.site_files / "version.json").write_text(json.dumps({"commit": PAGE_COMMIT}))
        self.site = PageSite(self.data, self.site_files).__enter__()
        self.browser: Browser | None = None
        self.expect_console_errors = 0

    # the served files ------------------------------------------------------------
    def latest(self) -> dict:
        return json.loads((self.data / "latest.json").read_text())

    def use_latest(self, latest: dict) -> None:
        (self.data / "latest.json").write_text(json.dumps(latest))

    def place_path(self, latest: dict | None = None) -> Path:
        latest = latest or self.latest()
        return self.data / latest["set_path"] / "place-kongsberg.json"

    def place(self) -> dict:
        return json.loads(self.place_path().read_text())

    def edit_place(self, edit) -> dict:
        doc = self.place()
        edit(doc)
        self.place_path().write_text(json.dumps(doc))
        return doc

    # the browser -----------------------------------------------------------------
    def open(self, clock: str, **viewport) -> Browser:
        self.browser = Browser(self.site.origin, **viewport)
        self.browser.open(PAGE, clock=clock)
        return self.browser

    def close_browser(self) -> None:
        """Close the browser, checking the page logged no errors beyond those expected."""
        if self.browser is None:
            return
        try:
            errors = self.browser.call("consoleErrors")
        finally:
            self.browser.close()
            self.browser = None
        assert len(errors) == self.expect_console_errors, errors

    def close(self) -> None:
        try:
            self.close_browser()
        finally:
            self.site.__exit__(None, None, None)


@pytest.fixture
def case_b(tmp_path, products):
    c = Case(tmp_path, products, "b")
    yield c
    c.close()


def cells(browser: Browser, model: str, quantity: str) -> list[dict]:
    """The table's cells for one model and quantity, in hour order."""
    return browser.eval(
        f"""[...document.querySelectorAll(
            'td[data-model="{model}"][data-quantity="{quantity}"]')].map(td => ({{
            time: td.dataset.time, text: td.textContent.trim(),
            value: td.dataset.value === undefined ? null : td.dataset.value,
            title: td.title }}))"""
    )


def latest_checks(case: Case) -> list:
    """The page's requests for latest.json, as the server answered them."""
    return [r for r in case.site.requests if r.path == "/data/latest.json"]


def wait_until(probe, timeout_s: float = 10.0):
    """Poll ``probe`` (real time) until it returns something truthy, and return that."""
    deadline = time.monotonic() + timeout_s
    while (value := probe()) is None or value is False:
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        time.sleep(0.05)
    return value


def oslo_hour(utc_text: str) -> str:
    t = dt.datetime.fromisoformat(utc_text.replace("Z", "+00:00"))
    return t.astimezone(OSLO).strftime("%H")


def test_the_table_shows_gfs_hours_with_the_place_files_values_in_oslo_time(case_b):
    place = case_b.place()
    b = case_b.open("2026-11-26T10:05:00Z")

    heads = b.eval(
        """[...document.querySelectorAll('thead th[data-time]')].map(th => ({
            time: th.dataset.time, hour: th.querySelector('.hour').textContent.trim(),
            sun: th.dataset.sun }))"""
    )
    assert [h["time"] for h in heads] == [h["time"] for h in place["hours"]]
    # 12 UTC on 26 November is 13:00 in Kongsberg (CET); the night ends at 12:00 local
    assert heads[0]["hour"] == "13" and heads[-1]["hour"] == "12"
    assert [h["hour"] for h in heads] == [oslo_hour(h["time"]) for h in place["hours"]]
    assert [h["sun"] for h in heads] == [h["sun_class"] for h in place["hours"]]

    quantities = {
        "total": lambda g: g["cloud"]["total_pct"],
        "low": lambda g: g["cloud"]["low_pct"],
        "mid": lambda g: g["cloud"]["mid_pct"],
        "high": lambda g: g["cloud"]["high_pct"],
        "wind200": lambda g: g["wind_200hpa_ms"],
    }
    for cn2 in ("osborn_sarazin", "tatarskii"):
        for key, name in (
            ("free_atmosphere_arcsec", "fa"),
            ("total_arcsec", "total_seeing"),
            ("hbar_km", "hbar"),
        ):
            quantities[f"{name}_{cn2}"] = lambda g, c=cn2, k=key: g["seeing"][c][k]
    for quantity, pick in quantities.items():
        shown = cells(b, "gfs", quantity)
        assert [c["time"] for c in shown] == [h["time"] for h in place["hours"]], quantity
        for c, hour in zip(shown, place["hours"], strict=True):
            assert float(c["value"]) == pick(hour["models"]["gfs"]), (quantity, c)
            assert c["text"] != ""

    by_time = {c["time"]: c["text"] for c in cells(b, "gfs", "low")}
    # GFS's low cloud at Kongsberg in the sample: 0.3 % at 02 UTC (never shown as 0),
    # 91.2 % at 06 UTC, none at 12 UTC
    assert by_time["2026-11-27T02:00:00Z"] == "0.3"
    assert by_time["2026-11-27T06:00:00Z"] == "91.2"
    assert by_time["2026-11-26T12:00:00Z"] == "0"
    fa = {c["time"]: c["text"] for c in cells(b, "gfs", "fa_osborn_sarazin")}
    raw = place["hours"][0]["models"]["gfs"]["seeing"]["osborn_sarazin"]["free_atmosphere_arcsec"]
    assert fa["2026-11-26T12:00:00Z"] == f"{raw:.2f}"


def test_every_seeing_value_carries_the_d47_labels(case_b):
    place = case_b.place()
    gfs = place["models"]["gfs"]
    b = case_b.open("2026-11-26T10:05:00Z")
    describe = """(td) => td.getAttribute('aria-describedby').split(' ')
        .map(id => document.getElementById(id).textContent).join(' | ')"""
    for cn2, cn2_name in (
        ("osborn_sarazin", "Osborn–Sarazin"),
        ("tatarskii", "Tatarskii + HMNSP99"),
    ):
        for quantity in ("fa", "total_seeing", "hbar"):
            labels = b.eval(
                f"""[...document.querySelectorAll(
                    'td[data-model="gfs"][data-quantity="{quantity}_{cn2}"]')].map({describe})"""
            )
            assert len(labels) == 24
            for text in labels:
                assert "uncalibrated" in text
                assert f"{cn2_name} Cₙ² model" in text
                assert "39 pressure levels" in text
                # Kongsberg's 162 m, raised 165 m to GFS's ground at 327 m (D47 item 1)
                assert "Observer at 327 m: the place's 162 m, raised 165 m" in text
            if quantity == "fa":
                assert all("above observer + 1 km" in t for t in labels)
            if quantity == "total_seeing":
                # GFS's first usable level is 137 m above its ground in the sample
                assert round(gfs["gap_to_first_level_m"]) == 137
                note = "no ground layer; the column starts 0.14 km above the model ground"
                assert all(note in t for t in labels)
    # the caution also sits on the page itself
    assert "uncalibrated" in b.eval("document.querySelector('.note').textContent")


def test_a_blanked_model_hour_shows_blank_cells_never_zero(case_b):
    blank, off_step, no_seeing = (
        "2026-11-26T20:00:00Z",
        "2026-11-26T21:00:00Z",
        "2026-11-26T22:00:00Z",
    )

    def edit(doc):
        for hour in doc["hours"]:
            if hour["time"] == blank:
                hour["models"]["gfs"] = {"missing": "partial"}
            if hour["time"] == off_step:
                hour["models"]["gfs"] = {"missing": "off_step"}
            if hour["time"] == no_seeing:
                hour["models"]["gfs"]["seeing"]["osborn_sarazin"]["free_atmosphere_arcsec"] = None

    case_b.edit_place(edit)
    b = case_b.open("2026-11-26T10:05:00Z")
    for quantity in ("total", "low", "wind200", "fa_osborn_sarazin", "hbar_tatarskii"):
        by_time = {c["time"]: c for c in cells(b, "gfs", quantity)}
        for t, reason in ((blank, "lacks this step"), (off_step, "no forecast step")):
            assert by_time[t]["text"] == "" and by_time[t]["value"] is None, (quantity, t)
            assert reason in by_time[t]["title"]
    fa = {c["time"]: c for c in cells(b, "gfs", "fa_osborn_sarazin")}
    assert fa[no_seeing]["text"] == "" and fa[no_seeing]["value"] is None
    # the hour's other values are still shown
    total = {c["time"]: c for c in cells(b, "gfs", "total_seeing_osborn_sarazin")}
    assert total[no_seeing]["text"] not in ("", "0", "0.00")


def runs_text(b: Browser) -> str:
    return b.eval("document.querySelector('#runs li[data-model=gfs]').textContent")


def test_each_run_shows_its_time_and_age_and_a_stale_run_is_marked(case_b):
    b = case_b.open("2026-11-26T10:05:00Z")
    run = runs_text(b)
    assert "GFS 0.25°" in run and "06 UTC 26 Nov" in run and "4 h 5 min old" in run
    assert "stale" not in run
    b.run_clock(60 * 60 * 1000)  # an hour later the age has moved on
    assert "5 h 5 min old" in runs_text(b)
    case_b.close_browser()

    latest = case_b.latest()
    latest["runs"]["gfs"]["stale"] = True
    case_b.use_latest(latest)
    b = case_b.open("2026-11-26T10:05:00Z")
    assert "stale, not counted" in runs_text(b)


def test_the_page_says_when_the_data_were_updated_in_the_places_time(case_b):
    assert case_b.latest()["written_at"] == "2026-11-26T10:00:00Z"
    b = case_b.open("2026-11-26T10:05:00Z")
    assert b.eval("document.getElementById('updated').textContent") == "Updated 11:00"


def test_a_changed_set_id_reloads_the_place_view(tmp_path, products):
    case = Case(tmp_path, products, "a")
    try:
        b = case.open("2026-11-26T09:05:00Z")
        set_a, set_b = case.latest_a["set_id"], case.latest_b["set_id"]
        assert set_a != set_b
        assert b.eval("document.body.dataset.setId") == set_a
        # set A has no GFS run yet: every GFS cell is blank
        assert {c["text"] for c in cells(b, "gfs", "total")} == {""}
        assert "no run yet" in b.eval("document.getElementById('runs').textContent")

        # five minutes on, latest.json is asked for again with its ETag: unchanged
        b.run_clock(5 * 60 * 1000)
        checks = wait_until(lambda: latest_checks(case) if len(latest_checks(case)) >= 2 else None)
        assert checks[0].status == 200 and "if-none-match" not in checks[0].headers
        assert checks[1].status == 304 and checks[1].headers["if-none-match"]
        assert b.eval("document.body.dataset.setId") == set_a

        # the tick writes set B; the next check loads it
        case.use_latest(case.latest_b)
        b.run_clock(5 * 60 * 1000)
        b.wait_for(f"document.body.dataset.setId === '{set_b}'")
        place = json.loads(case.place_path(case.latest_b).read_text())
        shown = cells(b, "gfs", "total")
        assert [float(c["value"]) for c in shown] == [
            h["models"]["gfs"]["cloud"]["total_pct"] for h in place["hours"]
        ]
        assert "3 h 15 min old" in runs_text(b)  # 09:15 UTC by the page's clock
        assert b.eval("document.getElementById('updated').textContent") == "Updated 11:00"
    finally:
        case.close()


def test_latest_json_unchanged_for_an_hour_shows_the_not_updating_banner(case_b):
    b = case_b.open("2026-11-26T10:00:30Z")  # 30 s after the set was written
    banner = "document.getElementById('banner')"
    assert b.eval(f"{banner}.hidden") is True
    b.run_clock(55 * 60 * 1000)  # 10:55:30; the checks found nothing new
    assert b.eval(f"{banner}.hidden") is True
    b.run_clock(6 * 60 * 1000)  # 11:01:30: more than an hour without a change
    b.wait_for(f"{banner}.hidden === false")
    text = b.eval(f"{banner}.textContent")
    assert "Data not updating" in text and "11:00" in text
    statuses = [r.status for r in case_b.site.requests if r.path == "/data/latest.json"]
    assert statuses[0] == 200 and set(statuses[1:]) == {304} and len(statuses) >= 12


def test_no_request_leaves_the_host(case_b):
    b = case_b.open("2026-11-26T10:05:00Z")
    b.call("click", selector="#about summary")
    b.call("click", selector="#sources summary")
    b.run_clock(10 * 60 * 1000)
    requests = b.call("requests")
    assert requests and all(not r["blocked"] for r in requests), requests
    assert all(r["url"].startswith(case_b.site.origin + "/") for r in requests)
    # and nothing in the page's markup points elsewhere to be fetched
    page_files = b.eval(
        "[...document.querySelectorAll('[src], link[href]')].map(e => e.src || e.href)"
    )
    origin = case_b.site.origin + "/"
    assert all(u.startswith(origin) or u.startswith("data:") for u in page_files)


def screenshot_dir() -> Path | None:
    """Where to save the PR's screenshots, if ``ASTRO_PAGE_SCREENSHOTS`` names a folder."""
    d = os.environ.get("ASTRO_PAGE_SCREENSHOTS")
    return Path(d) if d else None


def test_a_390px_phone_width_needs_no_horizontal_page_scroll(case_b):
    b = case_b.open("2026-11-26T10:05:00Z", width=390, height=844, scale=2)
    b.call("click", selector="#about summary")
    b.call("click", selector="#sources summary")
    widths = b.eval(
        """({ page: document.documentElement.scrollWidth, view: window.innerWidth,
              body: document.body.scrollWidth,
              wrap: document.querySelector('.table-wrap').clientWidth,
              table: document.querySelector('#hours').scrollWidth })"""
    )
    assert widths["view"] == 390
    assert widths["page"] <= 390 and widths["body"] <= 390, widths
    # the 24 hours scroll sideways inside the table's own box instead
    assert widths["wrap"] <= 390 - 2 * 16 and widths["table"] > widths["wrap"]
    if (d := screenshot_dir()) is not None:
        d.mkdir(parents=True, exist_ok=True)
        b.call("screenshot", path=str(d / "phone-390-panels.png"), fullPage=True)
        b.call("click", selector="#about summary")  # closed again for the main picture
        b.call("click", selector="#sources summary")
        b.call("screenshot", path=str(d / "phone-390.png"), fullPage=True)


def test_desktop_width(case_b):
    b = case_b.open("2026-11-26T10:05:00Z", width=1440, height=900, scale=2)
    assert b.eval("document.documentElement.scrollWidth") <= 1440
    if (d := screenshot_dir()) is not None:
        d.mkdir(parents=True, exist_ok=True)
        b.call("screenshot", path=str(d / "desktop-1440.png"), fullPage=True)


def about_panel(b: Browser) -> dict[str, str]:
    """The About this data panel's entries, by their labels."""
    return b.eval(
        """Object.fromEntries([...document.querySelectorAll('#about-list dt')]
            .map(dt => [dt.textContent, dt.nextElementSibling.textContent]))"""
    )


def test_about_credits_and_data_sources(case_b):
    place = case_b.place()
    latest = case_b.latest()
    b = case_b.open("2026-11-26T10:05:00Z")
    about = about_panel(b)
    assert about["Back-end commit"] == latest["provenance"]["commit"] == "a" * 40
    assert about["Config hash"] == latest["provenance"]["config_hash"]
    assert about["Run IDs"] == f"GFS 0.25°: {place['provenance']['run_ids']['gfs']}"
    assert about["This page's commit"] == PAGE_COMMIT
    assert latest["set_id"] in about["Data set"]
    assert "astroseeing 0.1.0" in about["Software"]

    credits = b.eval("[...document.querySelectorAll('#credits li')].map(li => li.textContent)")
    assert credits == [place["models"]["gfs"]["credit"]]
    sources = b.eval(
        """Object.fromEntries([...document.querySelectorAll('#sources-list .source')]
            .map(s => [s.dataset.source, s.textContent]))"""
    )
    assert "not permissible to state or imply endorsement" in sources["gfs"]
    assert "Datenbasis: Deutscher Wetterdienst" in sources["icon"]
    assert "Based on data from MET Norway" in sources["meps"]
    assert "based on data and products of the European Centre" in sources["ifs"]
    assert "Copernicus WorldDEM-30" in sources["glo30"]


def test_without_a_recorded_page_commit_the_about_panel_says_so(case_b):
    (case_b.site_files / "version.json").unlink()
    case_b.expect_console_errors = 1  # the 404 for version.json
    b = case_b.open("2026-11-26T10:05:00Z")
    assert about_panel(b)["This page's commit"].startswith("not recorded")


def test_past_hours_are_greyed_only_where_the_place_file_says_so(case_b):
    place = case_b.place()
    assert {h["past"] for h in place["hours"]} == {None}  # F1-14 fills the flags (D72)
    b = case_b.open("2026-11-26T19:05:00Z")
    assert b.eval("document.querySelectorAll('#hours .past').length") == 0
    case_b.close_browser()

    def edit(doc):
        for hour in doc["hours"]:
            hour["past"] = hour["time"] < "2026-11-26T19:00:00Z"

    case_b.edit_place(edit)
    b = case_b.open("2026-11-26T19:05:00Z")
    greyed = b.eval(
        "[...new Set([...document.querySelectorAll('td.past, th.past')].map(e => e.dataset.time))]"
    )
    assert greyed == [h["time"] for h in place["hours"] if h["time"] < "2026-11-26T19:00:00Z"]


@pytest.mark.slow  # ~45 s: the tick fetches 5244 files from the fake DWD
def test_icon_eu_shows_in_the_table_beside_gfs_with_no_page_change(tmp_path, ephemeris):
    """Ticket #55: the tick's files with ICON-EU added (a fake DWD beside the fake NOMADS)."""
    require_browser()
    world = World(tmp_path / "world", ephemeris, icon_eu=True)
    products = {}
    try:
        for name, hour in (("a", 9), ("b", 10)):
            world.at(DAY + dt.timedelta(hours=hour))
            products[name] = tmp_path / name
            shutil.copytree(
                world.paths.products, products[name], ignore=shutil.ignore_patterns("places")
            )
    finally:
        world.close()
    case = Case(tmp_path / "case", products, "b")
    try:
        place = case.place()
        b = case.open("2026-11-26T10:05:00Z")
        for model in ("gfs", "icon_eu"):
            shown = cells(b, model, "total")
            assert [c["time"] for c in shown] == [h["time"] for h in place["hours"]]
            for c, hour in zip(shown, place["hours"], strict=True):
                assert float(c["value"]) == hour["models"][model]["cloud"]["total_pct"]
        credits = b.eval("[...document.querySelectorAll('#credits li')].map(li => li.textContent)")
        assert credits == [place["models"][m]["credit"] for m in ("gfs", "icon_eu")]
        assert "Deutscher Wetterdienst" in credits[1]
    finally:
        case.close()
