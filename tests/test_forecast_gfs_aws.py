"""GFS from its fallback host, AWS ``noaa-gfs-bdp-pds`` (F1 spec Testing seam 3; ticket
#58, D51 item 14).

The bucket keeps NOAA's whole files (global, every field) with an ``.idx`` beside each,
so the fallback asks only the needed messages' byte ranges, and ``read`` cuts the
global fields to the area. ``fixtures/forecast/gfs/aws-idx/`` holds two real ``.idx``
files of the 2026-11-26 06z run (step 12); the fake bucket serves the NOMADS samples'
messages laid out as the bucket's files.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pytest

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.sources import FormatMismatch
from astroseeing.forecast.sources.gfs import GfsAdapter, RatePacer

from fake_http import FakeHttpServer
from forecast_samples import (
    SAMPLE_RUN,
    SAMPLES,
    aws_file,
    copy_samples,
    serve_aws_samples,
    serve_samples,
    small_box_settings,
)

IDX = Path(__file__).resolve().parent / "fixtures" / "forecast" / "gfs" / "aws-idx"
DAY_DIR = "/gfs.20261126/06/atmos"


def adapters(tmp_path, nomads, aws):
    """The small-box area, a GFS adapter on the fake NOMADS, and its fallback."""
    settings = small_box_settings(tmp_path / "config")
    gfs = GfsAdapter(
        settings.models["gfs"],
        HttpClient(timeout_s=5),
        settings.areas,
        base_url=nomads.url,
        pacer=RatePacer(None),
        fallback_url=aws.url,
    )
    return settings.areas["kongsberg"], gfs, gfs.on_fallback()


@pytest.fixture
def hosts():
    with FakeHttpServer() as nomads, FakeHttpServer() as aws:
        yield nomads, aws


def test_the_fallback_asks_only_the_needed_messages_of_the_real_index(tmp_path, hosts):
    """Against the bucket's real ``.idx`` of step 12: the 23 + 16 levels' four fields,
    cloud on 22 + 17 levels, the four cloud layers, surface pressure, ground height and
    visibility (D72's evidence), all instantaneous ("12 hour fcst"), never the 6-12 h
    averages; each message from its offset to the next one's."""
    _, _, aws = adapters(tmp_path, *hosts)
    pgrb2 = (IDX / "gfs.t06z.pgrb2.0p25.f012.idx").read_text()
    pgrb2b = (IDX / "gfs.t06z.pgrb2b.0p25.f012.idx").read_text()
    a = aws.aws_selection(pgrb2, SAMPLE_RUN, "pgrb2", 12)
    b = aws.aws_selection(pgrb2b, SAMPLE_RUN, "pgrb2b", 12)
    assert len(a) == 23 * 4 + 22 + 4 + 3
    assert len(b) == 16 * 4 + 17
    assert all(m.forecast == "12 hour fcst" for m in a + b)
    vis = next(m for m in a if m.var == "VIS")
    assert (vis.level, vis.start, vis.end) == ("surface", 4143745, 4917180 - 1)
    tcc = next(m for m in a if (m.var, m.level) == ("TCDC", "entire atmosphere"))
    assert tcc.n == 636  # line 637 is its 6-12 h average, never asked
    assert {m.level for m in b if m.var == "TCDC"} >= {"70 mb", "125 mb"}


def test_an_index_without_a_needed_message_is_a_format_mismatch(tmp_path, hosts):
    _, _, aws = adapters(tmp_path, *hosts)
    lines = (IDX / "gfs.t06z.pgrb2.0p25.f012.idx").read_text().splitlines()
    no_vis = "\n".join(line for line in lines if ":VIS:surface:" not in line)
    with pytest.raises(FormatMismatch, match="VIS:surface"):
        aws.aws_selection(no_vis, SAMPLE_RUN, "pgrb2", 12)
    twice = "\n".join([*lines, lines[9].replace("10:", "744:", 1)])
    with pytest.raises(FormatMismatch, match=r"VIS:surface.*twice"):
        aws.aws_selection(twice, SAMPLE_RUN, "pgrb2", 12)


def test_a_run_from_the_fallback_reads_the_same_as_from_nomads(tmp_path, hosts):
    nomads, bucket = hosts
    area, gfs, aws = adapters(tmp_path, nomads, bucket)
    steps = (0, 1, 12)
    serve_samples(nomads, gfs, area, steps)
    serve_aws_samples(bucket, steps)
    ref = gfs.read(gfs.fetch(SAMPLE_RUN, area, steps, tmp_path / "nomads"))

    asked_nomads = len(nomads.requests)
    now = dt.datetime(2026, 11, 26, 10, tzinfo=dt.UTC)
    serve_aws_samples(bucket, (48,))  # the last step's index says the run is out
    assert aws.latest_published(now) == SAMPLE_RUN
    fetched = aws.fetch(SAMPLE_RUN, area, steps, tmp_path / "aws")
    assert not fetched.missing_steps and len(fetched.files) == 6
    assert all(f.host == "aws" and f.url.startswith(bucket.url + DAY_DIR) for f in fetched.files)
    got = aws.read(fetched)
    names = (
        "geopotential_height_m",
        "temperature_k",
        "u_ms",
        "v_ms",
        "level_cloud_pct",
        "total_cloud_pct",
        "low_cloud_pct",
        "surface_pressure_hpa",
        "model_ground_m",
    )
    for name in names:
        np.testing.assert_array_equal(getattr(got, name), getattr(ref, name))
    np.testing.assert_array_equal(got.fog["visibility_m"], ref.fog["visibility_m"])
    # one index and ranged GETs per file; nothing else, nothing to NOMADS
    gets = [r for r in bucket.requests if r.method == "GET"]
    assert sum(r.path.endswith(".idx") for r in gets) == 6
    assert all("Range" in r.headers for r in gets if not r.path.endswith(".idx"))
    assert len(nomads.requests) == asked_nomads


def test_a_failed_range_leaves_the_step_missing_with_the_reason(tmp_path, hosts):
    nomads, bucket = hosts
    area, _, aws = adapters(tmp_path, nomads, bucket)
    serve_aws_samples(bucket, (0, 1))
    bucket.fail(f"{DAY_DIR}/gfs.t06z.pgrb2b.0p25.f001", status=503)
    fetched = aws.fetch(SAMPLE_RUN, area, (0, 1), tmp_path / "raw")
    assert set(fetched.missing_steps) == {1} and "503" in fetched.missing_steps[1]
    assert aws.read(fetched).n_steps == 1


def globalise(nomads_file: Path) -> bytes:
    """The sample's messages re-encoded on the bucket's global 0.25° grid (721 × 1440
    points from 90° N, 0° E), the sample values in place and every other point missing
    (a bitmap, which keeps the files small), packed as 64-bit floats so no value changes."""
    import eccodes as ec

    out = b""
    with open(nomads_file, "rb") as f:
        while (h := ec.codes_grib_new_from_file(f)) is not None:
            try:
                nj, ni = ec.codes_get(h, "Nj"), ec.codes_get(h, "Ni")
                north = ec.codes_get(h, "latitudeOfLastGridPointInDegrees")
                west = ec.codes_get(h, "longitudeOfFirstGridPointInDegrees")
                rows = ec.codes_get_values(h).reshape(nj, ni)[::-1]  # scanned south → north
                whole = np.full((721, 1440), 9999.0)
                r0, c0 = round((90 - north) / 0.25), round(west / 0.25)
                whole[r0 : r0 + nj, c0 : c0 + ni] = rows
                for key, value in (
                    ("jScansPositively", 0),
                    ("Ni", 1440),
                    ("Nj", 721),
                    ("latitudeOfFirstGridPointInDegrees", 90.0),
                    ("latitudeOfLastGridPointInDegrees", -90.0),
                    ("longitudeOfFirstGridPointInDegrees", 0.0),
                    ("longitudeOfLastGridPointInDegrees", 359.75),
                    ("bitmapPresent", 1),
                    ("missingValue", 9999.0),
                    ("packingType", "grid_ieee"),
                    ("precision", 2),
                ):
                    ec.codes_set(h, key, value)
                ec.codes_set_values(h, whole.ravel())
                out += ec.codes_get_message(h)
            finally:
                ec.codes_release(h)
    return out


def test_global_fields_from_the_bucket_are_cut_to_the_area(tmp_path, hosts):
    nomads, bucket = hosts
    area, gfs, aws = adapters(tmp_path, nomads, bucket)
    serve_samples(nomads, gfs, area, (1,))
    ref = gfs.read(gfs.fetch(SAMPLE_RUN, area, (1,), tmp_path / "nomads"))

    folder = copy_samples(tmp_path / "global")
    for part in ("pgrb2", "pgrb2b"):
        name = f"gfs.t06z.{part}.0p25.f001"
        (folder / f"{name}.grb2").write_bytes(globalise(SAMPLES / "box1deg" / f"{name}.grb2"))
        body, idx = aws_file(folder / f"{name}.grb2", SAMPLE_RUN)
        bucket.route(f"{DAY_DIR}/{name}", body)
        bucket.route(f"{DAY_DIR}/{name}.idx", idx.encode())
    got = aws.read(aws.fetch(SAMPLE_RUN, area, (1,), tmp_path / "aws"))
    assert got.grid_shape == ref.grid_shape == (5, 5)
    np.testing.assert_array_equal(got.lat, ref.lat)
    np.testing.assert_array_equal(got.lon, ref.lon)
    for name in (
        "temperature_k",
        "geopotential_height_m",
        "u_ms",
        "total_cloud_pct",
        "surface_pressure_hpa",
        "model_ground_m",
    ):
        np.testing.assert_array_equal(getattr(got, name), getattr(ref, name))
