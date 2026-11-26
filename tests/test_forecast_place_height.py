"""Saved places' GLO-30 ground heights (ticket #54, F1 spec #47 Module 6, D75).

The lookup runs against a fake tile server serving small synthetic tiles laid out
like the real ones (``glo30_tiles``). Each synthetic tile spans 1° with 36 rows and
24 or 36 columns, and holds ``offset + 1000 * row + col``, so a height names its own
tile and pixel. Expected rows and columns are worked out by hand in each test.
"""

from __future__ import annotations

import hashlib
import logging

import numpy as np
import pytest
import yaml

from astroseeing.forecast.http import HttpClient
from astroseeing.forecast.places import (
    PlaceHeightError,
    PlaceHeightMissing,
    look_up_height,
    require_looked_up_heights,
    set_place_height,
)
from astroseeing.forecast.settings import Posting, default_settings_path, load_settings
from astroseeing.provenance import DEM_ATTRIBUTION

from fake_http import FakeHttpServer
from glo30_tiles import tile_name, tile_path, write_tile


def _heights(rows: int, cols: int, offset: float = 0.0) -> np.ndarray:
    r, c = np.mgrid[0:rows, 0:cols]
    return (offset + 1000.0 * r + c).astype(np.float32)


@pytest.fixture
def bucket(tmp_path):
    """A fake GLO-30 bucket; ``put(south, west, cols, offset)`` adds a synthetic tile."""
    root = tmp_path / "bucket"
    root.mkdir()
    with FakeHttpServer(root) as server:

        def put(south: int, west: int, cols: int = 24, offset: float = 0.0, **kw) -> bytes:
            path = root / tile_path(south, west).lstrip("/")
            return write_tile(path, _heights(36, cols, offset), north=south + 1, west=west, **kw)

        server.put = put
        yield server


def test_place_inside_a_tile_reads_its_nearest_posting(bucket, tmp_path):
    bucket.put(59, 9, cols=24)  # 36 rows (1/36°), 24 columns (1/24°), like N59's 1.5×
    # Kongsberg: row (60 - 59.669) * 36 = 11.916 -> 12; col (9.652 - 9) * 24 = 15.648 -> 16
    found = look_up_height(59.669, 9.652, http=HttpClient(), dem_url=bucket.url,
                           work_dir=tmp_path / "work")  # fmt: skip
    assert found.metres == 12016.0
    assert found.tile == tile_name(59, 9) == "Copernicus_DSM_COG_10_N59_00_E009_00_DEM"
    assert (found.row, found.col) == (12, 16)
    assert found.pixel_lat == pytest.approx(60 - 12 / 36)
    assert found.pixel_lon == pytest.approx(9 + 16 / 24)


def _look_up(bucket, tmp_path, lat, lon):
    return look_up_height(lat, lon, http=HttpClient(), dem_url=bucket.url,
                          work_dir=tmp_path / "work")  # fmt: skip


def test_place_whose_nearest_posting_is_on_the_south_edge_reads_the_tile_below(bucket, tmp_path):
    bucket.put(59, 9, offset=0.0)
    bucket.put(58, 9, offset=500_000.0)
    # row (60 - 59.01) * 36 = 35.64 -> 36: one past N59's last row, i.e. N58's row 0
    found = _look_up(bucket, tmp_path, 59.01, 9.652)
    assert found.tile == tile_name(58, 9)
    assert (found.row, found.col) == (0, 16)
    assert found.metres == 500_016.0
    assert found.pixel_lat == pytest.approx(59.0)


def test_place_whose_nearest_posting_is_on_the_east_edge_reads_the_tile_east(bucket, tmp_path):
    bucket.put(59, 9, offset=0.0)
    bucket.put(59, 10, offset=700_000.0)
    # col (9.99 - 9) * 24 = 23.76 -> 24: one past E009's last column, i.e. E010's column 0
    found = _look_up(bucket, tmp_path, 59.669, 9.99)
    assert found.tile == tile_name(59, 10)
    assert (found.row, found.col) == (12, 0)
    assert found.metres == 712_000.0
    assert found.pixel_lon == pytest.approx(10.0)


def test_place_just_inside_the_north_and_west_edges_stays_in_its_tile(bucket, tmp_path):
    bucket.put(59, 9)
    # row (60 - 59.99) * 36 = 0.36 -> 0; col (9.01 - 9) * 24 = 0.24 -> 0
    found = _look_up(bucket, tmp_path, 59.99, 9.01)
    assert (found.tile, found.row, found.col, found.metres) == (tile_name(59, 9), 0, 0, 0.0)


def test_place_exactly_halfway_between_postings_takes_the_south_west_one(bucket, tmp_path):
    bucket.put(59, 9)
    # row (60 - 59.875) * 36 = 4.5 -> 5 (south); col (9.0625 - 9) * 24 = 1.5 -> 1 (west)
    found = _look_up(bucket, tmp_path, 59.875, 9.0625)
    assert (found.row, found.col, found.metres) == (5, 1, 5001.0)


def test_place_in_the_southern_and_western_hemispheres(bucket, tmp_path):
    bucket.put(-25, -71, cols=36)  # S25 W071 spans 25-24° S, 71-70° W
    # Paranal: row (-24 + 24.6279483) * 36 = 22.606 -> 23; col (-70.40479659 + 71) * 36
    # = 21.427 -> 21
    found = _look_up(bucket, tmp_path, -24.6279483, -70.40479659)
    assert found.tile == "Copernicus_DSM_COG_10_S25_00_W071_00_DEM"
    assert (found.row, found.col, found.metres) == (23, 21, 23021.0)


def test_checksum_of_the_tile_read_is_recorded(bucket, tmp_path):
    data = bucket.put(59, 9)
    found = _look_up(bucket, tmp_path, 59.669, 9.652)
    assert found.sha256 == hashlib.sha256(data).hexdigest()
    assert not any((tmp_path / "work").iterdir())  # the tile itself is not kept


@pytest.mark.parametrize(
    ("etag", "why"),
    [
        ('"0123456789abcdef0123456789abcdef"', "MD5"),  # the bytes don't match the ETag
        ('"0123456789abcdef0123456789abcdef-4"', "ETag"),  # multipart: not an MD5
        (None, "ETag"),  # nothing to check against
    ],
)
def test_a_tile_whose_checksum_cannot_be_confirmed_fails_loudly(bucket, tmp_path, etag, why):
    bucket.put(59, 9)
    bucket.header(tile_path(59, 9), "ETag", etag)
    with pytest.raises(PlaceHeightError, match=why) as err:
        _look_up(bucket, tmp_path, 59.669, 9.652)
    assert tile_name(59, 9) in str(err.value)
    assert not any((tmp_path / "work").iterdir())


def test_a_missing_tile_fails_loudly_naming_it(bucket, tmp_path):
    with pytest.raises(PlaceHeightError, match="N59_00_E009") as err:
        _look_up(bucket, tmp_path, 59.669, 9.652)
    assert "404" in str(err.value)


def test_a_missing_neighbour_tile_fails_loudly_too(bucket, tmp_path):
    bucket.put(59, 9)  # no N58 tile served
    with pytest.raises(PlaceHeightError, match="N58_00_E009"):
        _look_up(bucket, tmp_path, 59.01, 9.652)


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (dict(raster_type=1), "pixel is point"),  # pixel-is-area would shift by half a pixel
        (dict(predictor=1), "predictor"),
        (dict(north=60.5), "north-west corner"),  # tiepoint not on the tile corner
    ],
)
def test_a_tile_laid_out_differently_from_glo30_is_refused(bucket, tmp_path, change, why):
    path = bucket.root / tile_path(59, 9).lstrip("/")
    write_tile(path, _heights(36, 24), **{"north": 60.0, "west": 9.0, **change})
    with pytest.raises(PlaceHeightError, match=why):
        _look_up(bucket, tmp_path, 59.669, 9.652)


@pytest.mark.parametrize("bad", [-32767.0, np.nan])
def test_a_posting_without_data_is_refused_not_filled(bucket, tmp_path, bad):
    h = _heights(36, 24)
    h[12, 16] = bad
    write_tile(bucket.root / tile_path(59, 9).lstrip("/"), h, north=60.0, west=9.0)
    with pytest.raises(PlaceHeightError, match="no data"):
        _look_up(bucket, tmp_path, 59.669, 9.652)


def test_spacing_stored_a_rounding_step_off_is_read_as_meant(bucket, tmp_path):
    # The real N59 E009 tile stores its column spacing as 0.00041666666666666664, one
    # rounding step below 1/2400; the same kind of value here must give the same pixel.
    dlon = float(np.nextafter(1 / 24, 0))
    write_tile(bucket.root / tile_path(59, 9).lstrip("/"), _heights(36, 24), north=60.0,
               west=9.0, scale=(dlon, 1 / 36))  # fmt: skip
    found = _look_up(bucket, tmp_path, 59.669, 9.652)
    assert (found.row, found.col) == (12, 16)


# -- writing the height into the settings file ---------------------------------------


@pytest.fixture
def settings_file(tmp_path):
    """A copy of the committed settings file to write into."""
    path = tmp_path / "forecast.yaml"
    path.write_text(default_settings_path().read_text())
    return path


def _set(bucket, tmp_path, settings_file, place):
    return set_place_height(settings_file, place, http=HttpClient(), work_dir=tmp_path / "w",
                            dem_url=bucket.url)  # fmt: skip


def test_the_looked_up_height_is_written_with_its_tile_checksum_and_credit(
    bucket, tmp_path, settings_file
):
    data = bucket.put(59, 9)
    before = load_settings(settings_file)
    _set(bucket, tmp_path, settings_file, "kongsberg")

    after = load_settings(settings_file)
    h = after.places["kongsberg"].height
    assert h.metres == 12016.0  # row 12, col 16 (worked out above)
    assert (h.source, h.tile) == ("glo30", "Copernicus_DSM_COG_10_N59_00_E009_00_DEM")
    assert h.sha256 == hashlib.sha256(data).hexdigest()
    assert h.posting == Posting(row=12, col=16, lat=pytest.approx(60 - 12 / 36),
                                lon=pytest.approx(9 + 16 / 24))  # fmt: skip
    assert h.attribution == DEM_ATTRIBUTION  # RESEARCH §7, for the credits panel

    # Nothing else in the file changed, comments included.
    raw_before = yaml.safe_load(default_settings_path().read_text())
    raw_after = yaml.safe_load(settings_file.read_text())
    raw_before["places"]["kongsberg"]["height"] = raw_after["places"]["kongsberg"]["height"]
    assert raw_after == raw_before
    assert after.config_hash != before.config_hash
    comments = [ln for ln in default_settings_path().read_text().splitlines() if
                ln.lstrip().startswith("#")]  # fmt: skip
    assert all(c in settings_file.read_text().splitlines() for c in comments)


def test_a_second_lookup_rewrites_the_entry_in_place(bucket, tmp_path, settings_file):
    bucket.put(59, 9)
    _set(bucket, tmp_path, settings_file, "kongsberg")
    first = settings_file.read_text()
    _set(bucket, tmp_path, settings_file, "kongsberg")
    assert settings_file.read_text() == first  # idempotent


@pytest.mark.parametrize("problem", ["missing tile", "bad checksum"])
def test_a_failed_lookup_writes_nothing(bucket, tmp_path, settings_file, problem):
    if problem == "bad checksum":
        bucket.put(59, 9)
        bucket.header(tile_path(59, 9), "ETag", '"0123456789abcdef0123456789abcdef"')
    before = settings_file.read_bytes()
    with pytest.raises(PlaceHeightError):
        _set(bucket, tmp_path, settings_file, "kongsberg")
    assert settings_file.read_bytes() == before
    assert sorted(p.name for p in settings_file.parent.iterdir() if p.is_file()) == [
        "forecast.yaml"
    ]  # no temp file left beside it


def test_an_unknown_place_is_refused(bucket, tmp_path, settings_file):
    with pytest.raises(PlaceHeightError, match="no saved place 'oslo'"):
        _set(bucket, tmp_path, settings_file, "oslo")


@pytest.mark.parametrize(("published", "flagged"), [(12_000, False), (11_950, True)])
def test_the_difference_from_a_published_height_is_logged_and_flagged_above_50_m(
    bucket, tmp_path, settings_file, caplog, published, flagged
):
    raw = yaml.safe_load(settings_file.read_text())
    raw["places"]["kongsberg"]["published_height_m"] = published
    settings_file.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
    bucket.put(59, 9)
    with caplog.at_level(logging.INFO, logger="astroseeing.forecast.places"):
        result = _set(bucket, tmp_path, settings_file, "kongsberg")
    assert result.published_difference_m == pytest.approx(12016.0 - published)
    assert result.flagged is flagged
    msgs = [r for r in caplog.records if "published" in r.getMessage()]
    assert msgs and f"{12016.0 - published:+.1f} m" in msgs[0].getMessage()
    assert (msgs[0].levelno == logging.WARNING) is flagged


# -- the tick's check ----------------------------------------------------------------


def _with_heights(settings_file, **heights):
    """The settings with each named place's ``height`` entry replaced."""
    raw = yaml.safe_load(settings_file.read_text())
    for place, height in heights.items():
        raw["places"][place]["height"] = height
    settings_file.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
    return load_settings(settings_file)


_LOOKED_UP = {"metres": 162.28006, "source": "glo30",
              "tile": "Copernicus_DSM_COG_10_N59_00_E009_00_DEM", "sha256": "ab" * 32,
              "posting": {"row": 1192, "col": 1565, "lat": 59.66888888888889,
                          "lon": 9.652083333333334},
              "attribution": DEM_ATTRIBUTION}  # fmt: skip
_HAND_ENTERED = {"metres": 162.0, "source": "hand-entered", "tile": None, "sha256": None,
                 "posting": None, "attribution": None}  # fmt: skip


def test_the_tick_check_passes_when_every_place_has_a_looked_up_height(settings_file):
    settings = _with_heights(settings_file, kongsberg=_LOOKED_UP, paranal=_LOOKED_UP)
    require_looked_up_heights(settings)  # no error


@pytest.mark.parametrize("height", [None, _HAND_ENTERED], ids=["no height", "hand-entered"])
def test_the_tick_check_refuses_a_place_without_a_looked_up_height(settings_file, height):
    settings = _with_heights(settings_file, kongsberg=_LOOKED_UP, paranal=height)
    with pytest.raises(PlaceHeightMissing) as err:
        require_looked_up_heights(settings)
    message = str(err.value)
    assert "paranal" in message and "kongsberg" not in message
    assert "astro forecast place-height paranal" in message  # says how to fix it
    assert err.value.places == ("paranal",)


def test_the_tick_check_names_every_place_missing_one(settings_file):
    settings = _with_heights(settings_file, kongsberg=_HAND_ENTERED, paranal=None)
    with pytest.raises(PlaceHeightMissing) as err:
        require_looked_up_heights(settings)
    assert err.value.places == ("kongsberg", "paranal")


# -- the command ----------------------------------------------------------------------


@pytest.fixture
def ct(tmp_path, monkeypatch):
    for name in ("data", "staging", "state", "logs"):
        (tmp_path / name).mkdir()
    monkeypatch.setenv("ASTRO_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("ASTRO_STAGING", str(tmp_path / "staging"))
    monkeypatch.setenv("ASTRO_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ASTRO_LOG_DIR", str(tmp_path / "logs"))
    return tmp_path


def test_astro_forecast_place_height_writes_the_height(bucket, ct, settings_file, capsys):
    from astroseeing import cli

    bucket.put(59, 9)
    code = cli.main(["forecast", "place-height", "kongsberg", "--settings", str(settings_file),
                     "--dem-url", bucket.url])  # fmt: skip
    assert code == 0
    assert load_settings(settings_file).places["kongsberg"].height.metres == 12016.0
    out = capsys.readouterr().out
    assert "12016" in out and "Copernicus_DSM_COG_10_N59_00_E009_00_DEM" in out
    assert not any((ct / "staging").rglob("*.tif"))  # the tile isn't kept


def test_astro_forecast_place_height_fails_loudly_and_writes_nothing(
    bucket, ct, settings_file, capsys
):
    from astroseeing import cli

    before = settings_file.read_bytes()
    code = cli.main(["forecast", "place-height", "kongsberg", "--settings", str(settings_file),
                     "--dem-url", bucket.url])  # fmt: skip
    assert code != 0
    assert "404" in capsys.readouterr().err
    assert settings_file.read_bytes() == before
