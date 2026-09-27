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
from hypothesis import given, settings
from hypothesis import strategies as st

from astroseeing.download.downloader import Downloader
from astroseeing.download.requests import (
    Area,
    RequestSpec,
    max_fields,
    plan_requests,
    static_request,
)
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
    # Partial months are labelled by their first and last day, so two plans over the
    # same month can never share a store path.
    assert [s.key for s in monthly] == ["sl/x/2023-01-30_2023-01-31", "sl/x/2023-02-01_2023-02-02"]
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
    assert cleanup_raw(m, tmp / "staging") == {
        "deleted": 3,
        "recovered": 0,
        "skipped": 0,
        "failed": 0,
    }
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


def test_never_more_than_max_active_in_flight(env):
    """Regression (found on the CT, 2026-09-27): with max_active jobs still queued at
    the CDS, the next step asked for ``limit=0`` planned requests, which by_state took
    as "no limit", and submitted everything that was planned."""
    m, fake = env["m"], env["fake"]
    fake.polls_to_finish = 10  # jobs stay queued for several steps
    for _ in range(4):
        env["dl"].step()
        assert len(m.by_state("submitted")) <= 2
    assert fake.submits == 2 and len(m.by_state("planned")) == 1
    assert m.by_state("planned", limit=0) == []


def test_queue_limit_rejection_is_planned_again(env):
    """A CDS "queued requests ... temporarily limited" rejection is transient."""
    m, fake = env["m"], env["fake"]
    fake.behaviour[FakeCdsBackend.req_key(env["specs"][0].cds_request())] = "queue_limit"
    drain(env["dl"])
    assert m.counts() == {"downloaded": 3} and fake.submits == 4
    assert len(fake.deleted) == 4  # the rejected job too, as a courtesy
    assert m.by_state("downloaded")[0].attempts == 0  # not counted as a failure


def test_real_backend_reads_the_message_of_a_rejected_job():
    """Rejected jobs raise requests.HTTPError, not ProcessingFailedError (seen on the CT)."""
    import requests

    from astroseeing.download.cds import DatastoresBackend, is_queue_limit_rejection

    class _Remote:
        status = "rejected"

        @property
        def results_ready(self):
            raise requests.HTTPError(
                "400 Client Error: Bad Request\nThe job has been rejected\nNumber queued "
                "requests for this dataset is temporarily limited. Please configure your "
                "scripts accordingly"
            )

    class _Client:
        @staticmethod
        def get_remote(request_id):
            return _Remote()

    backend = object.__new__(DatastoresBackend)
    backend.client = _Client()
    info = backend.info("abc")
    assert info.status == "rejected" and "HTTPError" in info.error
    assert is_queue_limit_rejection(info.error)
    assert not is_queue_limit_rejection("cost limits exceeded")


def test_held_requests_are_not_submitted_until_released(env):
    m, fake = env["m"], env["fake"]
    assert m.hold("pl/") == 2 and m.counts() == {"held": 2, "planned": 1}
    drain(env["dl"])
    assert fake.submits == 1 and m.counts() == {"held": 2, "downloaded": 1}
    assert m.hold("pl/") == 0  # only planned requests can be held
    assert m.release("pl/paranal/2023-06-20") == 1
    drain(env["dl"])
    assert m.counts() == {"held": 1, "downloaded": 2}


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
    assert cleanup_raw(m, elsewhere) == {"deleted": 0, "recovered": 0, "skipped": 3, "failed": 0}
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
    assert out == {"deleted": 2, "recovered": 0, "skipped": 1, "failed": 0}
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


# --- review follow-ups (PR #1) ----------------------------------------------------------


def _ingested(env):
    m, dl, tmp = env["m"], env["dl"], env["tmp"]
    drain(dl)
    verify_pending(m)
    assert ingest_pending(m, tmp / "data", {})["ingested"] == 3
    return m, tmp


def test_shards_are_whole_chunks_for_the_global_grid():
    from astroseeing.ingest.store import choose_shards

    shape = (24, 29, 721, 1440)
    chunks = choose_chunks(shape, ("time", "level", "latitude", "longitude"))
    assert 721 % chunks[2] != 0  # the case the review found
    shards = choose_shards(shape, chunks)
    assert all(sh % c == 0 and sh >= s for sh, c, s in zip(shards, chunks, shape, strict=True))


def test_write_with_chunks_that_do_not_divide_the_array(tmp_path, monkeypatch):
    import zarr

    from astroseeing.ingest.store import Prepared
    from astroseeing.qc import QCCounts

    rng = np.random.default_rng(0)
    shape = (2, 3, 37, 41)
    prep = Prepared(
        dims=("time", "level", "latitude", "longitude"),
        coords={
            "time": (("time",), np.array([0, 3600], dtype=np.int64)),
            "level": (("level",), np.array([1000.0, 500.0, 50.0])),
            "latitude": (("latitude",), np.linspace(10, 1, 37)),
            "longitude": (("longitude",), np.linspace(0, 10, 41)),
        },
        data={"t": rng.normal(250, 10, shape).astype(np.float32)},
        qc=QCCounts(),
    )
    monkeypatch.setattr("astroseeing.ingest.store.TARGET_CHUNK_BYTES", 4096)
    res = write_store_atomic(tmp_path / "odd.zarr", prep, {})
    arr = zarr.open_group(str(res.path), mode="r", zarr_format=3)["t"]
    assert any(s % c for s, c in zip(shape, arr.chunks, strict=True))  # non-dividing chunks
    np.testing.assert_array_equal(arr[...], prep.data["t"])


def test_ingest_refuses_large_requests_without_a_mask(tmp_path):
    m = Manifest(tmp_path / "state" / "m.sqlite")
    (tmp_path / "data").mkdir()
    big = Area(0.0, 0.0, -2.75, 2.75)  # 12×12 = 144 points > 121
    spec = plan_requests(
        "sl", "region", dt.date(2023, 6, 20), dt.date(2023, 6, 20), big, hours=(0,)
    )[0]
    fake = FakeCdsBackend({FakeCdsBackend.req_key(spec.cds_request()): spec.expected()})
    rid = m.add_request(spec)
    drain(Downloader(m, fake, tmp_path / "staging" / "grib"))
    verify_pending(m)
    out = ingest_pending(m, tmp_path / "data", {})
    assert out["refused_unmasked"] == 1 and out["ingested"] == 0
    # Refused is its own state: not a failure (never retried) and not pending work.
    assert m.get(rid).state == "refused" and m.get(rid).attempts == 0
    assert not (tmp_path / "data" / "era5").exists()

    def land_and_night(req, dec):
        return np.ones((dec.lat.size, dec.lon.size), bool), np.ones((dec.times.size, 144), bool)

    assert m.requeue_refused("sl/") == 1 and m.get(rid).state == "verified"
    assert ingest_pending(m, tmp_path / "data", {}, mask_fn=land_and_night)["ingested"] == 1
    m.close()


def test_cleanup_recovers_after_crash_between_delete_and_manifest_update(env):
    m, tmp = _ingested(env)
    for rid in env["ids"]:  # simulate: files deleted, process died before the manifest write
        Path(m.current_file(rid)["path"]).unlink()
    out = cleanup_raw(m, tmp / "staging")
    assert out == {"deleted": 0, "recovered": 3, "skipped": 0, "failed": 0}
    assert m.counts() == {"raw_deleted": 3}
    assert all(m.latest_file(rid)["deleted_at"] for rid in env["ids"])


def test_cleanup_recovery_refuses_a_tampered_store(env):
    import zarr

    m, tmp = _ingested(env)
    req = m.get(env["ids"][0])
    Path(m.current_file(req.id)["path"]).unlink()
    g = zarr.open_group(str(store_path(tmp / "data", req)), mode="r+", zarr_format=3)
    g["t"][0, 0, 0, 0] = g["t"][0, 0, 0, 0] + 1.0
    out = cleanup_raw(m, tmp / "staging")
    assert out == {"deleted": 2, "recovered": 0, "skipped": 1, "failed": 0}
    assert m.get(req.id).state == "ingested"


def test_cleanup_recovers_recorded_deletion_without_state_change(env):
    m, tmp = _ingested(env)
    rid = env["ids"][0]
    f = m.current_file(rid)
    Path(f["path"]).unlink()
    m.conn.execute("UPDATE files SET deleted_at='2026-09-27T00:00:00+00:00' WHERE id=?", (f["id"],))
    out = cleanup_raw(m, tmp / "staging")
    assert out["recovered"] == 1 and out["deleted"] == 2
    assert m.get(rid).state == "raw_deleted"


def test_one_bad_request_does_not_stop_cleanup(env):
    m, tmp = _ingested(env)
    bad = Path(m.current_file(env["ids"][0])["path"])
    bad.write_bytes(bad.read_bytes()[:100])  # corrupt, still present
    out = cleanup_raw(m, tmp / "staging")
    assert out == {"deleted": 2, "recovered": 0, "skipped": 0, "failed": 1}
    assert bad.exists() and m.get(env["ids"][0]).state == "ingested"


def test_reingest_keeps_the_stores_own_provenance(env):
    """An identical store is kept; the manifest records the provenance the store carries."""
    m, tmp = _ingested(env)
    first = json.loads(
        m.conn.execute("SELECT provenance_json FROM ingests ORDER BY id LIMIT 1").fetchone()[0]
    )
    # A second manifest (e.g. rebuilt state) ingests the same requests with another config.
    m2 = Manifest(tmp / "state2" / "manifest.sqlite")
    for s in env["specs"]:
        m2.add_request(s)
    drain(Downloader(m2, env["fake"], tmp / "staging2" / "grib", max_active=3))
    verify_pending(m2)
    out = ingest_pending(m2, tmp / "data", {"config": "changed"})
    assert out["already_present"] == 3 and out["ingested"] == 0
    row = m2.conn.execute(
        "SELECT provenance_json, report_json FROM ingests ORDER BY id LIMIT 1"
    ).fetchone()
    stored, report = json.loads(row[0]), json.loads(row[1])
    assert stored["config_hash"] == first["config_hash"]
    assert report["this_run"]["config_hash"] != first["config_hash"]
    m2.close()


def test_all_ocean_mask_gives_an_empty_valid_store(tmp_path):
    dec = _decoded(tmp_path)
    prep = prepare(dec, np.zeros((3, 3), bool), np.zeros((24, 0), bool))
    assert prep.data["t"].shape == (24, 29, 0)
    res = write_store_atomic(tmp_path / "empty.zarr", prep, {})
    arrays, attrs = read_store(res.path)
    assert arrays["t"].shape == (24, 29, 0) and arrays["cell_index"].shape == (0,)
    assert attrs["qc"]["cells_dropped_not_land"]["count"] == 9
    assert write_store_atomic(tmp_path / "empty.zarr", prep, {}).already_present


# --- CDS cost limits (D23) ----------------------------------------------------------------


def test_month_of_pressure_levels_splits_under_the_cds_limit():
    jan = (dt.date(2023, 1, 1), dt.date(2023, 1, 31))
    whole = plan_requests("pl", "x", *jan, AREA, granularity="month", split=False)
    assert len(whole) == 1 and whole[0].n_fields == 107_880 > max_fields("pl") == 60_000
    specs = plan_requests("pl", "x", *jan, AREA, granularity="month")
    assert [s.key for s in specs] == ["pl/x/2023-01-01_2023-01-16", "pl/x/2023-01-17_2023-01-31"]
    assert all(s.n_fields <= 60_000 for s in specs)
    assert [s.cds_request()["day"][0] for s in specs] == ["01", "17"]
    (sl,) = plan_requests("sl", "x", *jan, AREA, granularity="month")
    assert sl.key == "sl/x/2023-01" and sl.n_fields == 12_648


def test_a_day_over_the_limit_is_refused(monkeypatch):
    from astroseeing.download import requests as rq

    monkeypatch.setattr(rq, "max_fields", lambda kind: 1000)
    with pytest.raises(ValueError, match="over the CDS limit"):
        plan_requests("pl", "x", dt.date(2023, 1, 1), dt.date(2023, 1, 1), AREA)


@settings(max_examples=60, deadline=None)
@given(
    start=st.dates(dt.date(2019, 1, 1), dt.date(2025, 12, 31)),
    ndays=st.integers(1, 120),
    kind=st.sampled_from(["pl", "sl"]),
    granularity=st.sampled_from(["day", "month"]),
)
def test_split_plans_cover_every_day_once_under_the_limit(start, ndays, kind, granularity):
    end = start + dt.timedelta(days=ndays - 1)
    specs = plan_requests(kind, "x", start, end, AREA, granularity=granularity)
    days = [d for s in specs for d in s.dates]
    assert days == [start + dt.timedelta(days=i) for i in range(ndays)]
    assert all(s.n_fields <= max_fields(kind) for s in specs)
    assert len({s.key for s in specs}) == len(specs)  # distinct store paths
    for s in specs:  # contiguous, within one month, and a valid CDS date product
        assert (s.dates[-1] - s.dates[0]).days == len(s.dates) - 1
        assert (s.dates[0].year, s.dates[0].month) == (s.dates[-1].year, s.dates[-1].month)
        s.cds_request()
    if granularity == "month":  # the fewest chunks per month
        per_month: dict = {}
        for s in specs:
            per_month.setdefault((s.dates[0].year, s.dates[0].month), []).append(s)
        for group in per_month.values():
            total = sum(s.n_fields for s in group)
            assert len(group) == -(-total // max_fields(kind))
