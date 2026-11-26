"""The ECMWF IFS source adapter (F1 spec Testing seam 3; ticket #56)."""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pytest
from forecast_ifs_samples import (
    PORTAL_DIR,
    SAMPLE_RUN,
    SAMPLES,
    copy_samples,
    read_index,
    rewrite_step,
    serve_samples,
)

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.settings import load_settings
from astroseeing.forecast.sources import FetchedFile, FetchResult, FormatMismatch
from astroseeing.forecast.sources.ifs import IfsAdapter, file_name, file_path

from fake_http import FakeHttpServer

SETTINGS = load_settings()
IFS = SETTINGS.models["ifs"]
KONGSBERG = SETTINGS.areas["kongsberg"]
PARANAL = SETTINGS.areas["paranal"]
RUN = SAMPLE_RUN


def adapter_for(server, settings=SETTINGS) -> IfsAdapter:
    """The adapter, pointed at a fake server (``None``: for ``read`` alone, no HTTP)."""
    if server is None:
        return IfsAdapter(settings.models["ifs"], None, settings.areas)
    return IfsAdapter(
        settings.models["ifs"], HttpClient(timeout_s=5), settings.areas, base_url=server.url
    )


def _row(param, levtype, offset, length, level=None, step=0):
    row = {"date": "20261126", "time": "0600", "step": str(step), "levtype": levtype,
           "param": param, "_offset": offset, "_length": length}  # fmt: skip
    if level is not None:
        row["levelist"] = str(level)
    return row


def handmade_step(step: int):
    """An index and file for one step: every field IFS needs, in runs, between fields
    it never reads (q, skt, and the 10 hPa level). Returns (index rows, body, needed
    rows)."""
    levels = [int(p) for p in IFS.pressure_levels_hpa]
    fields = [("skt", "sfc", None)]
    if step == 0:
        fields.append(("z", "sfc", None))
    fields += [("2t", "sfc", None), ("2d", "sfc", None), ("tcrw", "sfc", None)]
    fields += [("tcc", "sfc", None), ("lcc", "sfc", None), ("mcc", "sfc", None),
               ("hcc", "sfc", None), ("sp", "sfc", None)]  # fmt: skip
    for param in ("gh", "q", "t", "u", "v"):
        fields += [(param, "pl", lev) for lev in [10, *levels]]
    body, rows, needed = b"", [], []
    for i, (param, levtype, level) in enumerate(fields):
        chunk = f"<{param}{level or ''}>".encode() * (1 + i % 3)
        row = _row(param, levtype, len(body), len(chunk), level, step)
        rows.append(row)
        body += chunk
        if param not in ("skt", "tcrw", "q") and level != 10:
            needed.append(row)
    return rows, body, needed


def merged_ranges(needed):
    out = []
    for r in needed:
        a, b = r["_offset"], r["_offset"] + r["_length"] - 1
        if out and out[-1][1] + 1 == a:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def serve_handmade(server, steps):
    expected = {}
    for step in steps:
        rows, body, needed = handmade_step(step)
        name = f"20261126060000-{step}h-oper-fc"
        server.route(f"{PORTAL_DIR}/{name}.index", "\n".join(json.dumps(r) for r in rows).encode())
        server.route(f"{PORTAL_DIR}/{name}.grib2", body)
        expected[step] = (needed, body)
    return expected


def test_fetch_asks_only_the_byte_ranges_of_the_needed_fields(tmp_path):
    """Adjacent needed fields share one request; no byte of any other field is asked."""
    with FakeHttpServer() as portal:
        expected = serve_handmade(portal, (0, 3))
        fetched = adapter_for(portal).fetch(RUN, KONGSBERG, (0, 3), tmp_path / "raw")
        assert not fetched.missing_steps
        for step, (needed, body) in expected.items():
            name = f"{PORTAL_DIR}/20261126060000-{step}h-oper-fc.grib2"
            got = [r.headers["Range"] for r in portal.requests if r.path == name]
            assert got == [f"bytes={a}-{b}" for a, b in merged_ranges(needed)]
            want = b"".join(body[r["_offset"] : r["_offset"] + r["_length"]] for r in needed)
            (f,) = [
                f for f in fetched.files if f.path.name == f"20261126060000-{step}h-oper-fc.grib2"
            ]
            assert f.path.read_bytes() == want and f.bytes == len(want)
            assert f.host == "ecmwf-opendata" and f.url == portal.url + name
        # step 0 alone carries the model ground (z at the surface)
        assert len(expected[0][0]) == len(expected[3][0]) + 1 == 60


# -- fetch and read against the saved samples ------------------------------------------


@pytest.fixture
def portal():
    with FakeHttpServer() as s:
        yield s


def test_reads_the_whole_kongsberg_box_with_13_levels_and_3_hourly_steps(portal, tmp_path):
    ifs = adapter_for(portal)
    serve_samples(portal, (0, 3), "kongsberg")
    fetched = ifs.fetch(SAMPLE_RUN, KONGSBERG, (0, 3), tmp_path / "raw")
    assert not fetched.missing_steps and len(fetched.files) == 2

    f = ifs.read(fetched)
    assert f.grid_shape == (40, 40)  # 54.75-64.5° N × 4.75-14.5° E, as GFS's
    assert f.lat[0, 0] == 64.5 and f.lat[-1, 0] == 54.75  # rows north → south
    assert f.lon[0, 0] == 4.75 and f.lon[0, -1] == 14.5
    assert f.level_count == 13
    assert list(f.pressure_hpa) == [1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150,
                                    100, 50]  # fmt: skip
    assert f.valid_times.tolist() == [dt.datetime(2026, 11, 26, 6), dt.datetime(2026, 11, 26, 9)]
    assert f.level_cloud_pct is None  # IFS open data has no cloud on levels
    # heights rise with each level, temperatures and pressures are physical
    assert (np.diff(f.geopotential_height_m, axis=-1) > 0).all()
    assert f.temperature_k.min() > 180 and f.temperature_k.max() < 320
    assert f.surface_pressure_hpa.min() > 800 and f.surface_pressure_hpa.max() < 1060
    # cloud fractions 0-1 in the file, percent in RunFields; some cloud somewhere
    for c in (f.total_cloud_pct, f.low_cloud_pct, f.mid_cloud_pct, f.high_cloud_pct):
        assert c.min() >= 0 and c.max() <= 100 + 1e-6 and c.max() > 1
    # the fog signal: 2 m temperature minus dewpoint, never negative beyond packing
    dd = f.fog["dewpoint_depression_2m_k"]
    assert dd is not None and dd.min() > -0.5 and dd.max() < 40
    assert f.fog["visibility_m"] is None and f.fog["fog_fraction_pct"] is None
    # D47's evidence: IFS's ground (z/g0) is 261 m at 59.75° N 9.75° E
    i, j = int(np.argmin(abs(f.lat[:, 0] - 59.75))), int(np.argmin(abs(f.lon[0] - 9.75)))
    assert f.model_ground_m[i, j] == pytest.approx(261, abs=1)
    assert f.wind_200hpa_ms[0].shape == (2, 40, 40)


def test_reads_every_step_0_to_48_every_3_hours_of_the_small_box(portal, tmp_path):
    from forecast_samples import small_box_settings

    settings = small_box_settings(tmp_path)
    area = settings.areas["kongsberg"]
    ifs = adapter_for(portal, settings)
    serve_samples(portal, IFS.steps_h)
    f = ifs.read(ifs.fetch(SAMPLE_RUN, area, IFS.steps_h, tmp_path / "raw"))
    assert IFS.steps_h == tuple(range(0, 49, 3))
    assert f.grid_shape == (5, 5) and f.n_steps == 17
    hours = (f.valid_times - f.valid_times[0]) / np.timedelta64(1, "h")
    assert hours.tolist() == list(range(0, 49, 3))  # 3-hourly; nothing in between


def test_reads_the_paranal_box_in_west_longitudes(portal, tmp_path):
    ifs = adapter_for(portal)
    serve_samples(portal, (0, 3), "paranal")
    f = ifs.read(ifs.fetch(SAMPLE_RUN, PARANAL, (0, 3), tmp_path / "raw"))
    assert f.grid_shape == (4, 4)
    assert f.lat[:, 0].tolist() == [-24.25, -24.5, -24.75, -25.0]
    assert f.lon[0].tolist() == [-70.75, -70.5, -70.25, -70.0]
    assert 1000 < f.model_ground_m.max() < 3000  # the Andean coast range, smoothed


def globalise(folder, step):
    """Re-encode one step's sample messages on the portal's global grid (721 × 1440
    points, 90° N to 90° S, longitudes from 180°), the sample values in place and a
    marker value everywhere else, as the portal would send them."""
    import eccodes as ec

    lats = 90.0 - 0.25 * np.arange(721)
    lons = (180.0 + 0.25 * np.arange(1440) + 180.0) % 360.0 - 180.0

    def edit(row, chunk):
        if chunk.startswith(b"not downloaded"):
            return row, chunk
        h = ec.codes_new_from_message(chunk)
        try:
            nj, ni = ec.codes_get(h, "Nj"), ec.codes_get(h, "Ni")
            lat0 = ec.codes_get(h, "latitudeOfFirstGridPointInDegrees")
            lon0 = (ec.codes_get(h, "longitudeOfFirstGridPointInDegrees") + 180) % 360 - 180
            vals = ec.codes_get_values(h).reshape(nj, ni)
            whole = np.full((721, 1440), vals.mean())
            r0 = int(np.flatnonzero(np.isclose(lats, lat0))[0])
            c0 = int(np.flatnonzero(np.isclose(lons, lon0))[0])
            whole[r0 : r0 + nj, c0 : c0 + ni] = vals
            for key, value in (("Ni", 1440), ("Nj", 721),
                               ("latitudeOfFirstGridPointInDegrees", 90.0),
                               ("latitudeOfLastGridPointInDegrees", -90.0),
                               ("longitudeOfFirstGridPointInDegrees", 180.0),
                               ("longitudeOfLastGridPointInDegrees", 179.75)):  # fmt: skip
                ec.codes_set(h, key, value)
            ec.codes_set_values(h, whole.ravel())
            return row, ec.codes_get_message(h)
        finally:
            ec.codes_release(h)

    rewrite_step(folder, step, edit)


def test_global_fields_are_cut_to_the_area_after_download(tmp_path):
    folder = copy_samples(tmp_path / "global", "kongsberg")
    globalise(folder, 0)
    with FakeHttpServer() as portal:
        ifs = adapter_for(portal)
        serve_samples(portal, (0,), folder=folder)
        cut = ifs.read(ifs.fetch(SAMPLE_RUN, KONGSBERG, (0,), tmp_path / "raw"))
    with FakeHttpServer() as portal:
        ifs = adapter_for(portal)
        serve_samples(portal, (0,), "kongsberg")
        ref = ifs.read(ifs.fetch(SAMPLE_RUN, KONGSBERG, (0,), tmp_path / "raw-ref"))
    assert cut.grid_shape == ref.grid_shape == (40, 40)
    np.testing.assert_array_equal(cut.lat, ref.lat)
    np.testing.assert_array_equal(cut.lon, ref.lon)
    for name in ("temperature_k", "geopotential_height_m", "u_ms", "total_cloud_pct",
                 "surface_pressure_hpa", "model_ground_m"):  # fmt: skip
        np.testing.assert_allclose(getattr(cut, name), getattr(ref, name), atol=0.02)


def fetched_copy(tmp_path, steps=(0, 3), sample_set="kongsberg", area="kongsberg"):
    """A FetchResult over a copy of the samples, as if just downloaded."""
    folder = copy_samples(tmp_path / "samples", sample_set)
    files = tuple(
        FetchedFile("u", "ecmwf-opendata", folder / file_name(RUN, s, "grib2"), 0, 0.0, "")
        for s in steps
    )
    return folder, FetchResult(RUN, area, folder, files, tuple(steps))


def without(param, level=None):
    def edit(row, chunk):
        hit = row["param"] == param and row.get("levelist") == (
            None if level is None else str(level)
        )
        return None if hit else (row, chunk)

    return edit


@pytest.mark.parametrize(
    ("step", "param", "level", "named"),
    [
        (3, "sp", None, "sp"),
        (3, "t", 500, "t:500 hPa"),
        (0, "gh", 50, "gh:50 hPa"),
        (0, "2d", None, "2d"),
        (0, "z", None, "z"),
    ],
)
def test_a_sample_with_a_variable_or_level_removed_raises_format_mismatch(
    tmp_path, step, param, level, named
):
    folder, fetched = fetched_copy(tmp_path)
    assert rewrite_step(folder, step, without(param, level)) == 1
    with pytest.raises(FormatMismatch, match=f"step {step} .*missing {named}$") as e:
        adapter_for(None).read(fetched)
    assert e.value.model == "ifs"


def test_a_field_missing_from_the_index_fails_the_fetch_naming_it(portal, tmp_path):
    folder = copy_samples(tmp_path / "samples", "kongsberg")
    rewrite_step(folder, 3, without("v", 925))
    serve_samples(portal, (0, 3), folder=folder)
    with pytest.raises(FormatMismatch, match=r"-3h-oper-fc.index: missing v:925 hPa"):
        adapter_for(portal).fetch(RUN, KONGSBERG, (0, 3), tmp_path / "raw")
    assert list((tmp_path / "raw").iterdir()) == []  # step 0's file isn't left unrecorded


def test_a_run_from_another_area_is_refused(tmp_path):
    _, fetched = fetched_copy(tmp_path, area="paranal")
    with pytest.raises(FormatMismatch, match=r"does not hold every 0.25° point of area paranal"):
        adapter_for(None).read(fetched)


def test_a_failed_file_leaves_its_step_missing_with_the_reason(portal, tmp_path):
    ifs = adapter_for(portal)
    serve_samples(portal, (0, 3), "kongsberg")
    portal.fail(f"{PORTAL_DIR}/{file_name(RUN, 3, 'grib2')}", status=503, times=1)
    fetched = ifs.fetch(RUN, KONGSBERG, (0, 3), tmp_path / "raw")
    assert set(fetched.missing_steps) == {3} and "503" in fetched.missing_steps[3]
    assert not (tmp_path / "raw" / file_name(RUN, 3, "grib2")).exists()
    assert ifs.read(fetched).n_steps == 1


def test_latest_published_is_the_newest_run_with_its_last_step_indexed(portal):
    ifs = adapter_for(portal)
    portal.route(f"{PORTAL_DIR}/{file_name(RUN, 48, 'index')}", b"")
    # the 06z run is out at 12:27 (forecast-sources.md); at 13:40 the 12z isn't
    assert ifs.latest_published(dt.datetime(2026, 11, 26, 13, 40, tzinfo=dt.UTC)) == RUN
    heads = [r.path.split("/")[-1] for r in portal.requests if r.method == "HEAD"]
    assert heads == ["20261126120000-48h-oper-fc.index", "20261126060000-48h-oper-fc.index"]
    assert ifs.latest_published(dt.datetime(2026, 11, 26, 5, tzinfo=dt.UTC)) is None


def test_the_aws_mirror_has_the_same_files_without_the_forecasts_prefix():
    main, fallback = IFS.hosts.main, IFS.hosts.fallback
    assert fallback.name == "aws" and "ecmwf-forecasts" in fallback.url
    name = "20261126/06z/ifs/0p25/oper/20261126060000-48h-oper-fc.index"
    assert file_path(RUN, 48, "index", main) == "/forecasts/" + name
    assert file_path(RUN, 48, "index", fallback) == "/" + name


def test_the_samples_index_their_own_files():
    """The saved index of each step points at whole messages of its own file."""
    for folder in SAMPLES.iterdir():
        for index in folder.glob("*.index"):
            data = (folder / index.name.replace(".index", ".grib2")).read_bytes()
            rows = read_index(index)
            assert sum(r["_length"] for r in rows) == len(data)
            starts = [data[r["_offset"] : r["_offset"] + 4] for r in rows]
            assert all(s in (b"GRIB", b"not ") for s in starts)
            assert json.dumps(rows)  # plain JSON
