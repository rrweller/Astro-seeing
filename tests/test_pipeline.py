"""Manifest → download → verify → ingest → cleanup, on synthetic GRIB and a fake CDS."""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from astroseeing.download.downloader import Downloader
from astroseeing.download.requests import Area, RequestSpec, plan_requests, static_request
from astroseeing.ingest.decode import decode_grib
from astroseeing.ingest.pipeline import cleanup_raw, ingest_pending, store_path, verify_pending
from astroseeing.ingest.store import choose_chunks, prepare, read_store, write_store_atomic
from astroseeing.manifest import Manifest, StateError
from astroseeing.paths import assert_local_filesystem, filesystem_type
from astroseeing.synthetic import write_synthetic_grib
from astroseeing.verify.grib import verify_grib

from fakes import FakeCdsBackend, era5_param_ids

AREA = Area.around(-24.63, -70.40, half_width_cells=1)  # 3×3 box at Paranal
HOURS = (0, 6, 12, 18)  # keeps synthetic files small; full days are tested in _decoded


@pytest.fixture
def env(tmp_path):
    m = Manifest(tmp_path / "state" / "manifest.sqlite")
    specs = plan_requests(
        "pl", "paranal", dt.date(2023, 6, 20), dt.date(2023, 6, 21), AREA, hours=HOURS
    ) + plan_requests(
        "sl", "paranal", dt.date(2023, 6, 20), dt.date(2023, 6, 20), AREA, hours=HOURS
    )
    expected = {FakeCdsBackend.req_key(s.cds_request()): s.expected() for s in specs}
    fake = FakeCdsBackend(expected)
    ids = [m.add_request(s) for s in specs]
    dl = Downloader(m, fake, tmp_path / "staging" / "grib", max_active=2)
    (tmp_path / "data").mkdir()  # on the CT this is /data/astro (must already exist)
    yield {"m": m, "fake": fake, "dl": dl, "specs": specs, "ids": ids, "tmp": tmp_path}
    m.close()


def drain(dl: Downloader, max_steps: int = 50) -> None:
    for _ in range(max_steps):
        dl.step()
        if not dl.m.by_state("planned", "submitted"):
            return
    raise AssertionError("downloader did not finish")


# --- requests ------------------------------------------------------------------------


def test_request_builder_matches_cds_form_keys():
    spec = plan_requests("pl", "x", dt.date(2023, 1, 31), dt.date(2023, 2, 1), AREA)
    assert [s.key for s in spec] == ["pl/x/2023-01-31", "pl/x/2023-02-01"]
    req = spec[0].cds_request()
    assert set(req) == {
        "product_type",
        "variable",
        "year",
        "month",
        "day",
        "time",
        "pressure_level",
        "data_format",
        "download_format",
        "area",
    }
    assert req["data_format"] == "grib" and len(req["pressure_level"]) == 29
    assert req["area"] == [-24.5, -70.75, -25.0, -70.25]
    monthly = plan_requests(
        "sl", "x", dt.date(2023, 1, 30), dt.date(2023, 2, 2), AREA, granularity="month"
    )
    assert [s.key for s in monthly] == ["sl/x/2023-01", "sl/x/2023-02"]
    assert monthly[0].cds_request()["day"] == ["30", "31"]
    st = static_request("x", AREA).cds_request()
    assert st["variable"] == ["geopotential", "land_sea_mask", "standard_deviation_of_orography"]


def test_area_refuses_to_snap_silently():
    with pytest.raises(ValueError, match="not a multiple"):
        RequestSpec(
            "pl", "x", (dt.date(2023, 1, 1),), Area(10.1, 0, 0, 10), ("temperature",), (500,)
        ).cds_request()


# --- manifest ------------------------------------------------------------------------


def test_manifest_add_is_idempotent_and_detects_changed_requests(env):
    m, spec = env["m"], env["specs"][0]
    assert m.add_request(spec) == env["ids"][0]
    changed = RequestSpec(
        spec.kind, spec.region, spec.dates, spec.area, spec.variables[:2], spec.levels
    )
    with pytest.raises(ValueError, match="different request"):
        m.add_request(changed)


def test_manifest_transitions_are_compare_and_set(env):
    m, rid = env["m"], env["ids"][0]
    with pytest.raises(StateError):
        m.transition(rid, ["submitted"], "downloaded")
    m.transition(rid, ["planned"], "submitted", cds_request_id="x")
    events = m.conn.execute("SELECT event FROM events WHERE request_id=?", (rid,)).fetchall()
    assert [e[0] for e in events] == ["planned", "submitted"]


def test_manifest_refuses_network_filesystem(monkeypatch, tmp_path):
    monkeypatch.setattr("astroseeing.paths.filesystem_type", lambda p: "nfs4")
    with pytest.raises(RuntimeError, match="network filesystem"):
        assert_local_filesystem(tmp_path)
    assert filesystem_type(Path("/")) != ""


def test_manifest_export_is_a_consistent_copy(env):
    out = env["m"].export(env["tmp"] / "exports")
    rows = sqlite3.connect(out).execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    assert rows == len(env["specs"])
    assert not list((env["tmp"] / "exports").glob(".*tmp*"))


# --- downloader ----------------------------------------------------------------------


def test_full_pipeline_happy_path(env):
    m, dl, fake, tmp = env["m"], env["dl"], env["fake"], env["tmp"]
    drain(dl)
    assert m.counts() == {"downloaded": 3}
    assert fake.submits == 3 and len(fake.deleted) == 3
    assert verify_pending(m) == {"verified": 3, "failed": 0}
    data_root = tmp / "data"
    assert ingest_pending(m, data_root, {"test": True})["ingested"] == 3
    # the stores are readable by xarray and match the GRIB exactly
    req = m.get(env["ids"][0])
    ds = xr.open_zarr(store_path(data_root, req), zarr_format=3, consolidated=False)
    assert dict(ds.sizes) == {"time": 4, "level": 29, "latitude": 3, "longitude": 3}
    np.testing.assert_array_equal(ds.time.dt.hour.values, HOURS)
    dec = decode_grib(Path(m.current_file(req.id)["path"]), req.expected)
    np.testing.assert_array_equal(ds["t"].values, dec.data["t"])
    assert ds.attrs["provenance"]["manifest"]["request_id"] == req.id
    assert "Copernicus Climate Change Service" in ds.attrs["attribution"]
    assert ds.level.values[0] == 1000 and ds.level.values[-1] == 50
    # raw files are deleted only now, and only from staging
    assert cleanup_raw(m, tmp / "staging") == {"deleted": 3, "skipped": 0}
    assert m.counts() == {"raw_deleted": 3}
    assert not list((tmp / "staging" / "grib").glob("*.grib"))


def test_resume_after_crash_does_not_resubmit(env):
    m, fake, tmp = env["m"], env["fake"], env["tmp"]
    env["dl"].step()  # submits 2 (max_active), nothing finished yet
    assert fake.submits == 2 and len(m.by_state("submitted")) == 2
    dl2 = Downloader(m, fake, tmp / "staging" / "grib", max_active=2)  # "restart"
    drain(dl2)
    assert fake.submits == 3  # the two in-flight jobs were re-attached, not resubmitted
    assert m.counts() == {"downloaded": 3}


def test_cds_rejection_is_recorded_and_retryable(env):
    m, fake, dl = env["m"], env["fake"], env["dl"]
    fake.behaviour[FakeCdsBackend.req_key(env["specs"][0].cds_request())] = "reject"
    drain(dl)
    failed = m.by_state("failed")
    assert len(failed) == 1 and "cost limits" in failed[0].last_error and failed[0].attempts == 1
    fake.behaviour.clear()
    assert m.retry_failed() == 1
    drain(dl)
    assert m.counts() == {"downloaded": 3}


def test_expired_result_is_resubmitted(env):
    m, fake, dl = env["m"], env["fake"], env["dl"]
    fake.behaviour[FakeCdsBackend.req_key(env["specs"][1].cds_request())] = "expire"
    drain(dl)
    assert m.counts() == {"downloaded": 3} and fake.submits == 4


def test_truncated_download_fails_and_leaves_no_file(env):
    m, fake, dl = env["m"], env["fake"], env["dl"]
    fake.behaviour[FakeCdsBackend.req_key(env["specs"][0].cds_request())] = "truncate"
    drain(dl)
    assert m.counts() == {"downloaded": 2, "failed": 1}
    assert not list((env["tmp"] / "staging" / "grib").glob("*.part"))


@pytest.mark.parametrize("fault", ["drop", "duplicate", "shift"])
def test_verification_catches_bad_files(env, fault):
    m, fake, dl = env["m"], env["fake"], env["dl"]
    fake.behaviour[FakeCdsBackend.req_key(env["specs"][0].cds_request())] = fault
    drain(dl)
    assert verify_pending(m) == {"verified": 2, "failed": 1}
    bad = m.by_state("failed")[0]
    assert bad.last_error.startswith("verify:")
    rep = json.loads(
        m.conn.execute("SELECT report_json FROM verifications WHERE ok=0").fetchone()[0]
    )
    assert rep["problems"]


def test_verification_detects_file_changed_after_download(env):
    m, dl = env["m"], env["dl"]
    drain(dl)
    path = Path(m.current_file(env["ids"][0])["path"])
    with open(path, "ab") as f:
        f.write(b"x")
    assert verify_pending(m)["failed"] == 1


def test_missing_values_fail_verification(tmp_path):
    import eccodes as ec

    spec = plan_requests("sl", "x", dt.date(2023, 6, 20), dt.date(2023, 6, 20), AREA, hours=(0,))[0]
    exp = spec.expected()
    good = tmp_path / "good.grib"
    write_synthetic_grib(good, exp, era5_param_ids())
    bad = tmp_path / "bad.grib"
    with open(good, "rb") as fin, open(bad, "wb") as fout:
        first = True
        while (h := ec.codes_grib_new_from_file(fin)) is not None:
            if first:
                ec.codes_set(h, "bitmapPresent", 1)
                ec.codes_set(h, "missingValue", 9999)
                vals = ec.codes_get_values(h)
                vals[0] = 9999
                ec.codes_set_values(h, vals)
                first = False
            ec.codes_write(h, fout)
            ec.codes_release(h)
    rep = verify_grib(bad, exp)
    assert not rep.ok and any("missing" in p for p in rep.problems)
    assert verify_grib(good, exp).ok


# --- ingest / store --------------------------------------------------------------------


def _decoded(tmp_path, kind="pl"):
    spec = plan_requests(kind, "x", dt.date(2023, 6, 20), dt.date(2023, 6, 20), AREA)[0]
    p = tmp_path / f"{kind}.grib"
    write_synthetic_grib(p, spec.expected(), era5_param_ids())
    return decode_grib(p, spec.expected())


def test_store_write_is_idempotent_and_never_overwrites(tmp_path):
    dec = _decoded(tmp_path)
    prep = prepare(dec)
    final = tmp_path / "data" / "s.zarr"
    r1 = write_store_atomic(final, prep, {"a": 1})
    assert not r1.already_present
    r2 = write_store_atomic(final, prep, {"a": 1})
    assert r2.already_present and r2.content_sha256 == r1.content_sha256
    dec.data["t"][0, 0, 0, 0] += 1.0
    with pytest.raises(FileExistsError):
        write_store_atomic(final, prepare(dec), {"a": 1})
    assert not [p for p in final.parent.iterdir() if ".tmp-" in p.name]


def test_failed_write_leaves_no_temp_and_no_final(tmp_path, monkeypatch):
    dec = _decoded(tmp_path)
    prep = prepare(dec)
    final = tmp_path / "data" / "s.zarr"
    monkeypatch.setattr(
        "astroseeing.ingest.store.compare_store", lambda path, prep: ["forced failure"]
    )
    with pytest.raises(OSError, match="read-back"):
        write_store_atomic(final, prep, {})
    assert not final.exists()
    assert not list(final.parent.iterdir())


def test_cells_layout_with_night_mask_counts_everything(tmp_path):
    dec = _decoded(tmp_path)
    cell_mask = np.zeros((3, 3), bool)
    cell_mask[1:, :] = True  # 6 "land" cells
    keep = np.zeros((24, 6), bool)
    keep[:10] = True  # first 10 hours are "night"
    prep = prepare(dec, cell_mask, keep)
    assert prep.data["t"].shape == (24, 29, 6)
    assert prep.qc["cells_dropped_not_land"] == 3
    assert prep.qc["night_masked_values_t"] == 14 * 29 * 6
    assert np.isnan(prep.data["t"][10:]).all() and np.isfinite(prep.data["t"][:10]).all()
    res = write_store_atomic(tmp_path / "c.zarr", prep, {})
    arrays, attrs = read_store(res.path)
    np.testing.assert_array_equal(arrays["cell_index"], [3, 4, 5, 6, 7, 8])
    assert attrs["qc"]["night_masked_values_t"]["count"] == 14 * 29 * 6


def test_chunks_respect_target_and_keep_time_whole():
    ch = choose_chunks((24, 29, 721, 1440), ("time", "level", "latitude", "longitude"))
    assert ch[:2] == (24, 29) and np.prod(ch) * 4 <= 4 << 20
    assert choose_chunks((24, 29, 3, 3), ("time", "level", "latitude", "longitude")) == (
        24,
        29,
        3,
        3,
    )


def test_cleanup_refuses_files_outside_staging(env):
    m, dl, tmp = env["m"], env["dl"], env["tmp"]
    drain(dl)
    verify_pending(m)
    ingest_pending(m, tmp / "data", {})
    elsewhere = tmp / "elsewhere"
    elsewhere.mkdir()
    assert cleanup_raw(m, elsewhere) == {"deleted": 0, "skipped": 3}
    assert len(list((tmp / "staging" / "grib").glob("*.grib"))) == 3


def test_cleanup_refuses_when_store_was_tampered(env):
    import zarr

    m, dl, tmp = env["m"], env["dl"], env["tmp"]
    drain(dl)
    verify_pending(m)
    ingest_pending(m, tmp / "data", {})
    req = m.get(env["ids"][0])
    g = zarr.open_group(str(store_path(tmp / "data", req)), mode="r+", zarr_format=3)
    arr = g["t"]
    arr[0, 0, 0, 0] = arr[0, 0, 0, 0] + 1.0
    out = cleanup_raw(m, tmp / "staging")
    assert out == {"deleted": 2, "skipped": 1}
    assert Path(m.current_file(req.id)["path"]).exists()


def test_ingest_probes_storage_first(env, monkeypatch):
    from astroseeing.paths import StorageUnresponsive

    m, dl, tmp = env["m"], env["dl"], env["tmp"]
    drain(dl)
    verify_pending(m)

    def hang(path, timeout_s):
        raise StorageUnresponsive("fake hang")

    monkeypatch.setattr("astroseeing.ingest.pipeline.probe_responsive", hang)
    with pytest.raises(StorageUnresponsive):
        ingest_pending(m, tmp / "data", {})
    assert m.counts() == {"verified": 3}


def test_cdsapirc_permissions_are_enforced(tmp_path):
    from astroseeing.download.cds import read_cdsapirc

    rc = tmp_path / "rc"
    rc.write_text("url: https://cds.climate.copernicus.eu/api\nkey: abc\n")
    os.chmod(rc, 0o644)
    with pytest.raises(PermissionError):
        read_cdsapirc(rc)
    os.chmod(rc, 0o600)
    assert read_cdsapirc(rc) == ("https://cds.climate.copernicus.eu/api", "abc")


def test_missing_cloud_base_height_is_expected_and_counted(tmp_path):
    """ERA5 cbh is missing where there is no cloud: allowed, stored as NaN, counted."""
    import eccodes as ec

    spec = plan_requests("sl", "x", dt.date(2023, 6, 20), dt.date(2023, 6, 20), AREA, hours=(0,))[0]
    exp = spec.expected()
    good = tmp_path / "good.grib"
    write_synthetic_grib(good, exp, era5_param_ids())
    path = tmp_path / "cbh_missing.grib"
    with open(good, "rb") as fin, open(path, "wb") as fout:
        while (h := ec.codes_grib_new_from_file(fin)) is not None:
            if ec.codes_get(h, "shortName") == "cbh":
                ec.codes_set(h, "bitmapPresent", 1)
                ec.codes_set(h, "missingValue", 9999)
                vals = ec.codes_get_values(h)
                vals[:4] = 9999
                ec.codes_set_values(h, vals)
            ec.codes_write(h, fout)
            ec.codes_release(h)
    rep = verify_grib(path, exp)
    assert rep.ok and rep.missing_values["cbh"] == 4
    assert any("cbh" in w for w in rep.warnings)
    dec = decode_grib(path, exp)
    assert dec.missing == {"cbh": 4}
    assert int(np.isnan(dec.data["cbh"]).sum()) == 4
    assert np.isfinite(dec.data["tcc"]).all()
    prep = prepare(dec)
    assert prep.qc["grib_missing_values_cbh"] == 4
    res = write_store_atomic(tmp_path / "s.zarr", prep, {})
    arrays, attrs = read_store(res.path)
    assert int(np.isnan(arrays["cbh"]).sum()) == 4
    assert attrs["qc"]["grib_missing_values_cbh"]["count"] == 4
