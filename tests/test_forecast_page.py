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
from forecast_nights import place_file

from astroseeing.forecast.schemas import validate
from astroseeing.forecast.store import utc_text

from forecast_world import DAY, World
from icon_eu_samples import IconWorld
from page_browser import Browser, PageSite, require_browser

# The place view of the default saved place; the page itself opens on the map (ticket #66).
PAGE = "/forecast/#place/kongsberg"
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
def case_b(tmp_path, products, ephemeris):
    c = Case(tmp_path, products, "b")
    c.ephemeris = ephemeris
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

    # the stale flag is the place's own verdict's (ticket #63)
    case_b.edit_place(lambda doc: doc["tonight"]["runs"]["gfs"].update(stale=True))
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
    assert {h["past"] for h in place["hours"]} == {False}  # written before Tonight started
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
    world = IconWorld(tmp_path / "world", ephemeris)
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


# -- the verdict (ticket #63) ----------------------------------------------------------
#
# Hand-made nights at Kongsberg with all four forecast models of its box, built by the
# tick's own build_place_file (forecast_nights), so each file carries the verdict
# tonight() really gives. Expected wording is written out here; the numbers in it are
# checked against the night's construction first.

RUNS_26 = {
    "gfs": DAY + dt.timedelta(hours=6),
    "icon_eu": DAY + dt.timedelta(hours=6),
    "meps": DAY + dt.timedelta(hours=6),
    "ifs": DAY,
}


def normal_cloud(model: str, t: dt.datetime) -> float | str:
    """Clear, except: GFS and ICON-EU cloudy at 22 and 23 UTC; at 00 UTC GFS some cloud,
    ICON-EU cloudy, IFS clear (split); IFS cloudy at 21 UTC (2/3 clear); ICON-EU's run
    lacks 02 UTC, where IFS has no step either (incomplete). MEPS is clear all night."""
    if model == "meps":
        return 0.0
    if model == "icon_eu" and t.hour == 2:
        return "partial"
    if model in ("gfs", "icon_eu") and t.hour in (22, 23):
        return 80.0
    if t.hour == 0:
        return {"gfs": 30.0, "icon_eu": 80.0, "ifs": 5.0}[model]
    if model == "ifs" and t.hour == 21:
        return 80.0
    return 3.0


def all_clear(model: str, t: dt.datetime) -> float:
    return 2.0


def night(case: Case, now: dt.datetime, runs=RUNS_26, cloud=normal_cloud, ground_m=None) -> dict:
    """Serve the hand-made night at ``now`` as the current set's place file."""
    doc = place_file(now, case.ephemeris, runs, cloud, ground_m)
    validate(doc, "f1-place/1")
    case.place_path().write_text(json.dumps(doc))
    latest = case.latest()
    latest["written_at"] = utc_text(now.replace(second=0) - dt.timedelta(minutes=5))
    case.use_latest(latest)
    return doc


def open_night(case: Case, now: dt.datetime, **viewport) -> Browser:
    """Open the page a minute after ``now`` (sharp, for the PR's screenshots)."""
    return case.open(utc_text(now + dt.timedelta(minutes=1)), **{"scale": 2, **viewport})


def verdict_text(b: Browser) -> dict:
    return b.eval(
        """({ headline: document.getElementById('headline').textContent,
              basis: document.getElementById('basis-note').hidden ? null
                     : document.getElementById('basis-note').textContent,
              meps: document.getElementById('meps-line').hidden ? null
                    : document.getElementById('meps-line').textContent,
              seeing: document.getElementById('seeing-line').hidden ? null
                      : document.getElementById('seeing-line').textContent,
              moon: document.getElementById('moon-line').textContent,
              strip: document.getElementById('strip').textContent,
              chips: [...document.querySelectorAll('#strip .chip')].map(c => ({
                  cls: c.dataset.class, label: c.querySelector('.chip-class').textContent,
                  time: c.querySelector('.chip-time').textContent,
                  start: c.dataset.start, end: c.dataset.end })) })"""
    )


CHIP_LABELS = {
    "clear": "Clear",
    "some_cloud": "Some cloud",
    "cloudy": "Cloudy",
    "split": "Split",
    "incomplete": "Incomplete",
}


def expected_chips(doc: dict) -> list[dict]:
    out = []
    for c in doc["tonight"]["chips"]:
        first, last = oslo_hour(c["start"]), oslo_hour(c["end"])
        out.append(
            {
                "cls": c["class"],
                "label": CHIP_LABELS[c["class"]],
                "time": first if c["start"] == c["end"] else f"{first}–{last}",
                "start": c["start"],
                "end": c["end"],
            }
        )
    return out


def dark_hours(doc: dict, since: str = "") -> list[str]:
    return [h["time"] for h in doc["hours"] if h["sun_class"] == "dark" and h["time"] >= since]


def oslo_clock(utc: str) -> str:
    t = dt.datetime.fromisoformat(utc.replace("Z", "+00:00"))
    return t.astimezone(OSLO).strftime("%H:%M")


def save_screenshot(b: Browser, name: str) -> None:
    if (d := screenshot_dir()) is not None:
        d.mkdir(parents=True, exist_ok=True)
        b.call("screenshot", path=str(d / f"{name}.png"), fullPage=True)


def test_a_normal_night_shows_the_headline_chips_seeing_meps_and_moon(case_b):
    now = DAY + dt.timedelta(hours=10, minutes=5)  # before Tonight starts (11:21 UTC)
    doc = night(case_b, now)
    t = doc["tonight"]
    dark = dark_hours(doc)
    cloudy = [h for h in dark if h[11:13] in ("22", "23", "00")]
    assert len(cloudy) == 3 and "2026-11-27T02:00:00Z" in dark
    # n = the dark hours; x = n less the three cloudy or split ones and the incomplete one
    assert (t["counted_hours"], t["clear_hours"], t["incomplete_hours"]) == (
        len(dark),
        len(dark) - 4,
        1,
    )
    assert not t["started"] and t["basis"] == "dark"

    b = open_night(case_b, now)
    v = verdict_text(b)
    n, x = len(dark), len(dark) - 4
    assert v["headline"] == f"{x} of {n} dark hours look clear on most models (1 hour incomplete)"
    assert v["basis"] is None
    assert v["chips"] == expected_chips(doc)
    assert [c["cls"] for c in v["chips"]] == [
        "clear", "cloudy", "split", "clear", "incomplete", "clear",
    ]  # fmt: skip
    # MEPS is clear all night: its own line, never in the counts or the strip
    assert v["meps"] == f"MEPS (regional, not counted): {n} of {n} clear"
    assert "MEPS" not in v["strip"] and "MEPS" not in v["headline"]
    assert v["seeing"] == (
        "Seeing 0.55–0.81″ (free atmosphere, Osborn–Sarazin, 3 models), uncalibrated"
    )
    moon = doc["moon"]
    lit = round(moon["illuminated_fraction"] * 100)
    waxing = "waxing" if moon["phase_deg"] < 180 else "waning"
    rise = f"rises {oslo_clock(moon['rise'])}" if moon["rise"] else "does not rise tonight"
    sets = f"sets {oslo_clock(moon['set'])}" if moon["set"] else "does not set tonight"
    assert v["moon"] == f"Moon: {rise}, {sets}, {lit} % lit, {waxing}"
    save_screenshot(b, "verdict-normal")


def test_each_hours_agreement_shows_count_denominator_and_majority_or_split(case_b):
    now = DAY + dt.timedelta(hours=10, minutes=5)
    doc = night(case_b, now)
    b = open_night(case_b, now)
    shown = {c["time"]: c for c in cells(b, "all", "agreement")}
    assert list(shown) == [h["time"] for h in doc["hours"]]
    # 21 UTC: GFS, ICON-EU clear, IFS cloudy; 19 UTC: IFS has no step; 00 UTC: one of
    # each class; 22 UTC: GFS and ICON-EU cloudy, no IFS step; 02 UTC: GFS alone
    assert shown["2026-11-26T21:00:00Z"]["text"] == "2/3 clearclear"
    assert shown["2026-11-26T19:00:00Z"]["text"] == "2/2 clearclear"
    assert shown["2026-11-27T00:00:00Z"]["text"] == "1/3 clearsplit"
    assert shown["2026-11-26T22:00:00Z"]["text"] == "0/2 clearcloudy"
    assert shown["2026-11-27T02:00:00Z"]["text"] == "1/1 clearincomplete"
    moon = {c["time"]: c for c in cells(b, "all", "moon")}
    for h in doc["hours"]:
        assert float(moon[h["time"]]["value"]) == h["moon_altitude_deg"]
        assert moon[h["time"]]["text"] == f"{round(h['moon_altitude_deg'])}".replace("-", "−")
    counted = b.eval("[...document.querySelectorAll('thead th.counted')].map(t => t.dataset.time)")
    assert counted == [h["time"] for h in doc["hours"] if h["counted"]]
    # MEPS is shown in the table, marked as not counted
    heads = b.eval("[...document.querySelectorAll('.model-head')].map(t => t.textContent)")
    assert "MEPS (regional, not counted)" in heads


def test_a_started_night_counts_the_hours_left_and_greys_the_past(case_b):
    now = DAY + dt.timedelta(hours=22, minutes=10)  # 22 UTC is the current hour
    doc = night(case_b, now)
    left = dark_hours(doc, since="2026-11-26T22:00:00Z")
    t = doc["tonight"]
    # left: 22, 23 cloudy, 00 split, 02 incomplete; the rest clear
    assert (t["counted_hours"], t["clear_hours"], t["incomplete_hours"]) == (
        len(left),
        len(left) - 4,
        1,
    )
    b = open_night(case_b, now)
    v = verdict_text(b)
    assert v["headline"] == (
        f"{len(left) - 4} of {len(left)} dark hours left look clear on most models "
        "(1 hour incomplete)"
    )
    assert v["chips"] == expected_chips(doc)
    assert v["chips"][0]["start"] == "2026-11-26T22:00:00Z"
    assert v["meps"] == f"MEPS (regional, not counted): {len(left)} of {len(left)} clear"
    greyed = b.eval("[...document.querySelectorAll('thead th.past')].map(t => t.dataset.time)")
    assert greyed == [h["time"] for h in doc["hours"] if h["time"] < "2026-11-26T22:00:00Z"]
    save_screenshot(b, "verdict-started")


def test_a_june_night_names_its_fallback_basis(case_b):
    now = dt.datetime(2026, 6, 20, 10, 5, tzinfo=dt.UTC)
    run_06z, run_00z = now.replace(hour=6, minute=0), now.replace(hour=0, minute=0)
    runs = {"gfs": run_06z, "icon_eu": run_06z, "meps": run_06z, "ifs": run_00z}
    doc = night(case_b, now, runs=runs, cloud=all_clear)
    t = doc["tonight"]
    # at 59.7° N on 20 June the Sun gets no lower than about 7° below the horizon
    assert min(h["sun_altitude_deg"] for h in doc["hours"]) > -12
    down = [h for h in doc["hours"] if h["sun_altitude_deg"] < -0.833]
    assert t["basis"] == "sun_down" and t["counted_hours"] == t["clear_hours"] == len(down)
    b = open_night(case_b, now)
    v = verdict_text(b)
    n = len(down)
    assert v["headline"] == f"{n} of {n} night hours (Sun down) look clear on most models"
    assert v["basis"] == (
        "No dark time tonight: the Sun never gets 18° below the horizon, nor 12°, "
        "so the count uses the hours with the Sun down."
    )
    assert v["chips"] == expected_chips(doc)
    assert [c["cls"] for c in v["chips"]] == ["clear"]
    save_screenshot(b, "verdict-june")


def test_when_dark_time_has_ended_the_page_says_when(case_b):
    now = DAY + dt.timedelta(days=1, hours=6, minutes=10)  # before sunrise (about 07:20)
    doc = night(case_b, now)
    nothing = doc["tonight"]["nothing_to_count"]
    assert nothing["reason"] == "dark_time_ended" and doc["tonight"]["counted_hours"] == 0
    last_dark = dark_hours(doc)[-1]
    assert nothing["dark_time_ended_at"] == last_dark.replace(":00:00Z", ":30:00Z")
    b = open_night(case_b, now)
    v = verdict_text(b)
    assert v["headline"] == f"Dark time ended at {oslo_clock(nothing['dark_time_ended_at'])}"
    assert v["chips"] == [] and v["meps"] is None and v["seeing"] is None
    # the table stays
    assert len(cells(b, "gfs", "total")) == 24
    save_screenshot(b, "verdict-dark-time-ended")


def test_not_enough_models_names_each_models_state(case_b):
    now = DAY + dt.timedelta(hours=19, minutes=5)
    runs = {
        "gfs": DAY + dt.timedelta(hours=12),
        "meps": DAY + dt.timedelta(hours=12),
        "ifs": DAY - dt.timedelta(hours=24),  # 43 h old: stale
    }  # no ICON-EU run
    doc = night(case_b, now, runs=runs, cloud=all_clear)
    nothing = doc["tonight"]["nothing_to_count"]
    assert nothing["families"] == {"gfs": "ok", "icon": "missing", "ifs": "stale"}
    b = open_night(case_b, now)
    v = verdict_text(b)
    assert v["headline"] == (
        "Not enough models for a verdict: GFS 0.25° has values; ICON has no run for "
        "these hours; ECMWF IFS 0.25° has a stale run (not counted)"
    )
    assert v["chips"] == expected_chips(doc)
    assert {c["cls"] for c in v["chips"]} == {"incomplete"}
    runs_shown = b.eval(
        "Object.fromEntries([...document.querySelectorAll('#runs li')]"
        ".map(li => [li.dataset.model, li.textContent]))"
    )
    assert "stale, not counted" in runs_shown["ifs"] and "43 h 6 min old" in runs_shown["ifs"]
    assert "stale" not in runs_shown["gfs"] and "no run yet" in runs_shown["icon_eu"]
    save_screenshot(b, "verdict-not-enough-models")


def test_the_verdict_fits_a_390px_phone(case_b):
    now = DAY + dt.timedelta(hours=10, minutes=5)
    night(case_b, now)
    b = open_night(case_b, now, width=390, height=844, scale=2)
    widths = b.eval(
        """({ page: document.documentElement.scrollWidth,
              strip: document.getElementById('strip').scrollWidth,
              verdict: document.getElementById('verdict').clientWidth })"""
    )
    assert widths["page"] <= 390 and widths["strip"] <= widths["verdict"] <= 390 - 2 * 16
    save_screenshot(b, "verdict-phone-390")


# -- fog signals, terrain and the missing column (ticket #64) ----------------------------
#
# The same hand-made nights: each model's fog signals are the ones its settings list
# (D49 item 3), with a foggy hour at 06 UTC, and "absent" for the signals it lacks.

FOGGY, CLEARER = "2026-11-27T06:00:00Z", "2026-11-26T21:00:00Z"

#: What each fog row shows for each model at 06 UTC and at 21 UTC (None: the model has
#: no such field), written out by hand from forecast_nights and normal_cloud.
FOG_ROWS = {
    "fog_fraction": {"gfs": None, "icon_eu": None, "meps": ("82.5", "0"), "ifs": None},
    "visibility": {
        "gfs": ("0.35", "24.0"),
        "icon_eu": ("0.35", "24.0"),
        "meps": ("0.35", "24.0"),
        "ifs": None,
    },
    "weather_code": {"gfs": None, "icon_eu": ("45", "0"), "meps": None, "ifs": None},
    "dewpoint_depression": {"gfs": None, "icon_eu": None, "meps": None, "ifs": ("0.2", "3.1")},
    "fog_low_cloud": {
        "gfs": ("3", "3"),
        "icon_eu": ("3", "3"),
        "meps": ("0", "0"),
        "ifs": ("3", "80"),
    },
}


def test_the_fog_row_shows_each_models_signals_and_absent_for_a_field_it_lacks(case_b):
    now = DAY + dt.timedelta(hours=10, minutes=5)
    doc = night(case_b, now)
    b = open_night(case_b, now)
    for quantity, per_model in FOG_ROWS.items():
        for model, expected in per_model.items():
            shown = {c["time"]: c for c in cells(b, model, quantity)}
            assert list(shown) == [h["time"] for h in doc["hours"]], (quantity, model)
            if expected is None:
                # the model has no such field: "absent" on every hour it has values,
                # never blank and never 0
                for h in doc["hours"]:
                    if "missing" in h["models"][model]:
                        continue
                    c = shown[h["time"]]
                    assert c["text"] == "absent" and c["value"] is None, (quantity, model, c)
                    assert "has no such field" in c["title"]
            else:
                got = (shown[FOGGY]["text"], shown[CLEARER]["text"])
                assert got == expected, (quantity, model)
                assert shown[FOGGY]["value"] is not None
    # an hour a model has no value for stays blank, never "absent": IFS's off-steps and
    # ICON-EU's partial 02 UTC
    ifs_off = {c["time"]: c for c in cells(b, "ifs", "visibility")}["2026-11-26T19:00:00Z"]
    icon_02 = {c["time"]: c for c in cells(b, "icon_eu", "weather_code")}["2026-11-27T02:00:00Z"]
    for c in (ifs_off, icon_02):
        assert c["text"] == "" and c["value"] is None
    caps = b.eval("[...document.querySelectorAll('tr.fog-head .cap')].map(c => c.textContent)")
    assert len(caps) == 4
    assert all("experimental" in t and "not counted" in t for t in caps)


def terrain_warnings(b: Browser) -> dict[str, str] | None:
    """The terrain warnings by model, or None while the list is hidden."""
    return b.eval(
        """document.getElementById('terrain').hidden ? null : Object.fromEntries(
            [...document.querySelectorAll('#terrain li')]
            .map(li => [li.dataset.model, li.textContent]))"""
    )


def test_a_place_below_a_models_ground_gets_the_terrain_warning_with_the_metres(case_b):
    now = DAY + dt.timedelta(hours=10, minutes=5)
    # Kongsberg's ground is 162.28 m: below GFS's 327.4 m, ICON-EU's 346.9 m and IFS's
    # 301.2 m, above MEPS's 120 m here
    doc = night(case_b, now, ground_m={"meps": 120.0})
    assert doc["models"]["meps"]["terrain_caveat_m"] is None
    b = open_night(case_b, now)
    warnings = terrain_warnings(b)
    assert set(warnings) == {"gfs", "icon_eu", "ifs"}  # none for MEPS
    tail = (
        "fog or cold air pooling in terrain below the model's ground is not forecast by this model."
    )
    assert warnings["gfs"] == (
        f"Kongsberg (162 m) is 165 m below GFS 0.25°'s ground (327 m): {tail}"
    )
    assert warnings["icon_eu"] == (
        f"Kongsberg (162 m) is 185 m below ICON-EU's ground (347 m): {tail}"
    )
    assert warnings["ifs"] == (
        f"Kongsberg (162 m) is 139 m below ECMWF IFS 0.25°'s ground (301 m): {tail}"
    )


def test_the_fog_rows_and_terrain_warning_fit_a_390px_phone(case_b):
    now = DAY + dt.timedelta(hours=10, minutes=5)
    night(case_b, now, ground_m={"meps": 120.0})
    b = open_night(case_b, now, width=390, height=844)
    widths = b.eval(
        """({ page: document.documentElement.scrollWidth,
              terrain: document.getElementById('terrain').getBoundingClientRect().right,
              wrap: document.querySelector('.table-wrap').clientWidth,
              caps: Math.max(...[...document.querySelectorAll(
                  'tr.fog-head .cap, tr.missing-column .cap')]
                  .map(c => c.getBoundingClientRect().width)) })"""
    )
    assert widths["page"] <= 390 and widths["terrain"] <= 390 - 16, widths
    # the fog and missing-column captions wrap inside the table's box
    assert widths["caps"] <= widths["wrap"], widths
    save_screenshot(b, "phone-390-terrain-fog")
    # the ICON-EU block's fog rows and missing column, scrolled to the foggy hour
    b.eval(
        f"""(() => {{
            document.querySelector('tr.fog-head[data-model=icon_eu]').scrollIntoView();
            const wrap = document.querySelector('.table-wrap');
            const corner = document.querySelector('thead th.corner').offsetWidth;
            wrap.scrollLeft = document.querySelector('thead th[data-time="{FOGGY}"]')
                .offsetLeft - corner - 80;
        }})()"""
    )
    if (d := screenshot_dir()) is not None:
        b.call("screenshot", path=str(d / "phone-390-icon-eu-fog-gap.png"))


def test_the_fog_rows_terrain_warning_and_missing_column_at_desktop_width(case_b):
    now = DAY + dt.timedelta(hours=10, minutes=5)
    night(case_b, now, ground_m={"meps": 120.0})
    b = open_night(case_b, now, width=1440, height=900)
    assert b.eval("document.documentElement.scrollWidth") <= 1440
    assert b.eval("document.querySelectorAll('#terrain li, tr.fog-head, tr.missing-column')"
                  ".length") == 3 + 4 + 4  # fmt: skip
    # drawing them asks nothing of another host
    requests = b.call("requests")
    assert requests and all(not r["blocked"] for r in requests), requests
    assert all(r["url"].startswith(case_b.site.origin + "/") for r in requests)
    save_screenshot(b, "desktop-1440-terrain-fog")


def test_each_models_missing_column_is_shown_beside_its_seeing(case_b):
    now = DAY + dt.timedelta(hours=10, minutes=5)
    doc = night(case_b, now)
    b = open_night(case_b, now)
    lines = b.eval(
        """Object.fromEntries([...document.querySelectorAll('tr.missing-column')]
            .map(tr => [tr.dataset.model, tr.textContent]))"""
    )
    # the gaps written into the night: GFS 137 m, ICON-EU 352, MEPS 548, IFS 561
    expected = {
        "gfs": ("0.14 km", "GFS 0.25°", "327 m"),
        "icon_eu": ("0.35 km", "ICON-EU", "347 m"),
        "meps": ("0.55 km", "MEPS", "255 m"),
        "ifs": ("0.56 km", "ECMWF IFS 0.25°", "301 m"),
    }
    assert set(lines) == set(expected)
    for model, (gap, name, ground) in expected.items():
        assert lines[model] == (
            f"Missing column: the {gap} from {name}'s ground ({ground}) up to its first "
            "usable pressure level is not in its seeing (the deepest gap over tonight's "
            "hours)."
        )
    # every seeing value points at its model's line, as at its D47 labels
    for model in expected:
        for quantity in ("fa_osborn_sarazin", "total_seeing_tatarskii", "hbar_osborn_sarazin"):
            described = b.eval(
                f"""[...document.querySelectorAll(
                    'td[data-model="{model}"][data-quantity="{quantity}"]')].map(td =>
                    td.getAttribute('aria-describedby').split(' ')
                      .map(id => document.getElementById(id).textContent).join(' | '))"""
            )
            assert len(described) == len(doc["hours"])
            assert all(lines[model] in d for d in described), (model, quantity)


def test_a_place_above_every_models_ground_shows_no_terrain_warning(case_b):
    now = DAY + dt.timedelta(hours=10, minutes=5)
    night(case_b, now, ground_m={"gfs": 150.0, "icon_eu": 100.0, "meps": 120.0, "ifs": 162.28})
    b = open_night(case_b, now)
    assert terrain_warnings(b) is None
    assert b.eval("document.querySelectorAll('#terrain li').length") == 0
