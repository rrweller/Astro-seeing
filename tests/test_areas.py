"""Validation areas (download/areas.py, D31): geometry, masks, night hours, sampling,
cancelling, and an end-to-end ingest that stores only the site boxes."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import numpy as np
import pytest

from astroseeing.config import load_config
from astroseeing.download import areas as ar
from astroseeing.download.downloader import Downloader
from astroseeing.download.requests import plan_requests
from astroseeing.ingest.pipeline import RefusedUnmasked, ingest_pending, verify_pending
from astroseeing.ingest.store import read_store
from astroseeing.manifest import Manifest

from fakes import FakeCdsBackend

TWO = ar.ValidationArea("two", (("a/x", -24.63, -70.40), ("a/y", -25.10, -69.20)))


def test_area_holds_every_box_and_masks_their_union():
    a = TWO.area
    for b in TWO.boxes().values():
        assert a.north >= b.north and a.south <= b.south and a.west <= b.west and a.east >= b.east
    lat = np.arange(a.north, a.south - 1e-9, -0.25)
    lon = np.arange(a.west, a.east + 1e-9, 0.25)
    m = TWO.cell_mask(lat, lon)
    assert m.shape == (lat.size, lon.size)
    assert m.sum() == 50  # two disjoint 5×5 boxes
    assert TWO.points()[0].size == 50
    assert not m.all()  # the rectangle between the boxes is not stored


def test_mask_fn_areas_small_boxes_and_refusal(monkeypatch):
    monkeypatch.setattr(ar, "load_areas", lambda: {"two": TWO})
    a = TWO.area
    dec = SimpleNamespace(lat=np.arange(a.north, a.south - 1e-9, -0.25),
                          lon=np.arange(a.west, a.east + 1e-9, 0.25))  # fmt: skip
    mask, keep = ar.mask_fn(SimpleNamespace(region="two@every4d", key="k"), dec)
    assert keep is None and mask.sum() == 50
    small = SimpleNamespace(lat=np.arange(5.0), lon=np.arange(5.0))
    assert ar.mask_fn(SimpleNamespace(region="paranal", key="k"), small) == (None, None)
    big = SimpleNamespace(lat=np.arange(12.0), lon=np.arange(12.0))
    with pytest.raises(RefusedUnmasked, match="not a declared validation area"):
        ar.mask_fn(SimpleNamespace(region="elsewhere", key="k"), big)


def test_configured_areas_cover_the_papers_grid_points():
    areas = ar.load_areas()
    assert set(areas) == {"chile", "tibet", "timau", "haikou", "rongcheng"}
    sites = load_config("sites")
    for area in areas.values():
        for ref, la, lo in area.sites:
            group, name = ref.split("/")
            lat_p, lon_p = (sites[group][name].get("era5_point") or [lo, la])[::-1]
            box = area.boxes()[ref]
            assert box.south <= lat_p <= box.north and box.west <= lon_p <= box.east, ref
    assert areas["tibet"].area.shape(0.25) == (43, 105)


def test_chile_night_hours_are_the_local_night(ephemeris):
    hours = ar.load_areas()["chile"].night_hours()
    # Local midnight at 70° W is ~04:40 UTC and local noon ~16:40 UTC.
    assert 4 in hours and 5 in hours and 16 not in hours and 17 not in hours
    assert 8 <= len(hours) <= 16
    ring = sorted((h - 23) % 24 for h in hours)  # contiguous around local midnight
    assert ring == list(range(ring[0], ring[0] + len(ring)))


def test_every_fourth_day_plans():
    specs = plan_requests("pl", "timau@every4d", dt.date(2003, 1, 1), dt.date(2003, 2, 28),
                          TWO.area, granularity="month", day_step=4)  # fmt: skip
    days = [[d.day for d in s.dates] for s in specs]
    assert days == [[1, 5, 9, 13, 17, 21, 25, 29], [1, 5, 9, 13, 17, 21, 25]]
    for s in specs:
        s.cds_request()  # a valid year x month x day product
        assert s.key.startswith("pl/timau@every4d/")


def test_cancel_drops_planned_and_held(tmp_path):
    m = Manifest(tmp_path / "m.sqlite")
    for s in plan_requests("sl", "x", dt.date(2023, 1, 1), dt.date(2023, 3, 31), TWO.area,
                           granularity="month"):  # fmt: skip
        m.add_request(s)
    m.hold("sl/x/2023-02")
    assert m.cancel("sl/x", "superseded") == 3
    assert m.counts() == {"cancelled": 3}
    m.close()


def test_area_ingest_stores_only_the_site_boxes(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "load_areas", lambda: {"two": TWO})
    m = Manifest(tmp_path / "state" / "m.sqlite")
    specs = plan_requests("pl", "two", dt.date(2023, 6, 20), dt.date(2023, 6, 20), TWO.area,
                          variables=("temperature",), levels=(500, 850), hours=(0, 6))  # fmt: skip
    fake = FakeCdsBackend({FakeCdsBackend.req_key(s.cds_request()): s.expected() for s in specs},
                          polls_to_finish=1)  # fmt: skip
    for s in specs:
        m.add_request(s)
    dl = Downloader(m, fake, tmp_path / "staging" / "grib", max_active=2)
    for _ in range(10):
        dl.step()
    assert verify_pending(m)["verified"] == 1
    (tmp_path / "data").mkdir()
    out = ingest_pending(m, tmp_path / "data", {"test": True}, mask_fn=ar.mask_fn)
    assert out["ingested"] == 1
    store = tmp_path / "data" / "era5" / "pl" / "two" / "2023-06-20.zarr"
    arrays, attrs = read_store(store)
    assert attrs["layout"] == "cells"
    assert arrays["t"].shape == (2, 2, 50)  # time, level, the 50 site-box cells
    assert arrays["cell_lat"].size == 50
    m.close()


def test_undeclared_large_request_is_refused_not_failed(tmp_path, monkeypatch):
    """Copilot review of PR #2: a refusal must not be retried like a transient failure."""
    monkeypatch.setattr(ar, "load_areas", lambda: {})
    m = Manifest(tmp_path / "state" / "m.sqlite")
    big = TWO.area  # 60 points, but not declared: pretend the cap is lower
    monkeypatch.setattr(ar, "MAX_UNMASKED_POINTS", 25)
    spec = plan_requests("pl", "somewhere", dt.date(2023, 6, 20), dt.date(2023, 6, 20), big,
                         variables=("temperature",), levels=(500,), hours=(0,))[0]  # fmt: skip
    fake = FakeCdsBackend({FakeCdsBackend.req_key(spec.cds_request()): spec.expected()},
                          polls_to_finish=1)  # fmt: skip
    rid = m.add_request(spec)
    dl = Downloader(m, fake, tmp_path / "staging" / "grib")
    for _ in range(5):
        dl.step()
    verify_pending(m)
    (tmp_path / "data").mkdir()
    out = ingest_pending(m, tmp_path / "data", {}, mask_fn=ar.mask_fn)
    assert out == {"ingested": 0, "already_present": 0, "failed": 0, "refused_unmasked": 1}
    assert m.get(rid).state == "refused" and m.retry_failed() == 0
    m.close()
