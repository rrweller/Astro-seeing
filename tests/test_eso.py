"""The ESO ambient-conditions fetcher (roadmap C8, ticket #101, D65).

Parsing is tested on real ESO answers saved in ``tests/fixtures/eso`` (CC BY 4.0, ESO
credit in its README); fetching on a scripted HTTP client, a temp store and a temp
manifest; the wire request on the shared fake HTTP host.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from astroseeing.download import eso
from astroseeing.forecast.http import HttpError, HttpResponse, HttpUnavailable
from astroseeing.manifest import Manifest

FIXTURES = Path(__file__).parent / "fixtures" / "eso"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


# --- parsing ------------------------------------------------------------------------


def test_parses_real_paranal_dimm_answer():
    rows = eso.parse_csv(eso.table("paranal-dimm"), fixture("paranal-dimm.csv"))

    assert rows.rows == 8
    seeing = rows.series["seeing"]
    assert seeing.unit == "arcsec"
    assert seeing.times[0] == np.datetime64("2026-11-14T00:00:13", "s")
    assert seeing.times[-1] == np.datetime64("2026-11-14T00:09:36", "s")
    np.testing.assert_array_equal(
        seeing.values, [0.945, 0.849, 0.746, 0.824, 1.089, 0.828, 0.866, 0.993]
    )
    assert rows.series["airmass"].values[0] == 1.391
    assert rows.dropped() == 0


def test_parses_real_paranal_mass_answer_with_all_four_columns():
    rows = eso.parse_csv(eso.table("paranal-mass"), fixture("paranal-mass.csv"))

    assert rows.rows == 8
    first = {name: s.values[0] for name, s in rows.series.items()}
    assert first == {
        "free_atmosphere_seeing": 0.800,
        "turbulence_altitude": 3856.0,
        "ground_fraction": 0.324,
        "mass_dimm_seeing": 1.000,
    }
    assert rows.series["turbulence_altitude"].unit == "m"


def test_parses_real_la_silla_answer():
    rows = eso.parse_csv(eso.table("lasilla-dimm"), fixture("lasilla-dimm.csv"))

    assert rows.rows == 10
    assert rows.series["seeing"].values[0] == 0.40
    assert rows.series["airmass"].values[0] == 1.20
    assert rows.series["seeing"].times[0] == np.datetime64("2025-06-01T00:00:28", "s")


def test_an_answer_with_no_rows_is_an_empty_table_not_an_error():
    rows = eso.parse_csv(eso.table("paranal-dimm"), fixture("paranal-dimm-empty.csv"))

    assert rows.rows == 0
    assert rows.series["seeing"].values.size == 0
    assert rows.series["seeing"].times.dtype == np.dtype("datetime64[s]")


def test_a_cut_answer_is_refused():
    with pytest.raises(eso.EsoTruncated, match="maximum of 3"):
        eso.parse_csv(eso.table("paranal-dimm"), fixture("paranal-dimm-truncated.csv"))


def _without_line(text: str, starts: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith(starts))


@pytest.mark.parametrize(
    ("damage", "message"),
    [
        (lambda t: "<html><body>Service unavailable</body></html>", "record count"),
        (lambda t: _without_line(t, "# A total of"), "record count"),
        (lambda t: _without_line(t, "2026-11-14T00:04:10"), "8 records but 7 rows"),
        (lambda t: t.replace('DIMM Seeing ["]', "DIMM Seeing [arcsec]"), 'DIMM Seeing \\["\\]'),
        (lambda t: t.replace("Date time,", "Time,"), "Date time"),
    ],
    ids=["html-page", "no-footer", "row-missing", "column-renamed", "no-time-column"],
)
def test_an_unknown_answer_layout_is_refused(damage, message):
    text = damage(fixture("paranal-dimm.csv"))
    with pytest.raises(eso.EsoFormatError, match=message):
        eso.parse_csv(eso.table("paranal-dimm"), text)


DAMAGED_DIMM = """
Date time,DIMM Seeing ["],Relative Flux RMS,Relative Flux RMS base time [s],Airmass
2026-11-14T00:00:13,0.945,0.002100,537,1.391
2026-11-14T00:01:32,,0.001994,537,1.387
2026-11-14T00:02:51,nan,0.002859,535,1.384
2026-11-14T00:04:10,abc,0.003005,535,
2026-11-14T00:05:30,inf,0.004122,536,1.377
2026-11-14T00:06:58,-0.100,0.016797,545,1.373
2026-11-14T00:08:17,0.866,0.018888,544
not-a-time,0.993,0.017946,544,1.366

# A total of 8 records were found matching the provided criteria.
#
"""


def test_missing_and_non_numeric_values_are_dropped_per_column_and_counted(caplog):
    with caplog.at_level("WARNING", logger="astroseeing.download.eso"):
        rows = eso.parse_csv(eso.table("paranal-dimm"), DAMAGED_DIMM)

    seeing, airmass = rows.series["seeing"], rows.series["airmass"]
    # Nothing is clipped: the negative value is kept as ESO wrote it.
    np.testing.assert_array_equal(seeing.values, [0.945, -0.100])
    assert list(seeing.times.astype(str)) == ["2026-11-14T00:00:13", "2026-11-14T00:06:58"]
    np.testing.assert_array_equal(airmass.values, [1.391, 1.387, 1.384, 1.377, 1.373])
    assert rows.counts() == {
        "rows": 8,
        "malformed_rows": 1,  # wrong number of fields: dropped from every column
        "bad_times": 1,
        "duplicate_times": 0,
        "out_of_order_times": 0,
        "columns": {
            "seeing": {"kept": 2, "missing": 1, "nonnumeric": 3},
            "airmass": {"kept": 5, "missing": 1, "nonnumeric": 0},
        },
    }
    assert "paranal-dimm" in caplog.text
    assert "nonnumeric" in caplog.text


_FIELD = st.one_of(
    st.just(""),
    st.floats(allow_nan=True, allow_infinity=True).map(repr),
    st.sampled_from(["abc", "-", "N/A", " "]),
)


@given(st.lists(st.tuples(st.booleans(), _FIELD, _FIELD), max_size=30))
def test_every_row_is_kept_or_counted_once_per_column(spec):
    """kept + missing + nonnumeric + malformed + bad times == rows, for every column."""
    lines = ['Date time,DIMM Seeing ["],Airmass']
    for i, (short, seeing, airmass) in enumerate(spec):
        t = f"2026-11-14T00:{i // 60:02d}:{i % 60:02d}"
        lines.append(f"{t},{seeing}" if short else f"{t},{seeing},{airmass}")
    text = "\n".join([*lines, f"# A total of {len(spec)} records were found matching"])
    rows = eso.parse_csv(eso.table("paranal-dimm"), text)

    c = rows.counts()
    for col in c["columns"].values():
        total = col["kept"] + col["missing"] + col["nonnumeric"]
        assert total + c["malformed_rows"] + c["bad_times"] == len(spec)
    for s in rows.series.values():
        assert s.times.size == s.values.size
        assert np.isfinite(s.values).all()


# --- fetching -----------------------------------------------------------------------

UTC = dt.UTC
NIGHT = (
    dt.datetime(2026, 11, 13, 16, 41, 36, tzinfo=UTC),
    dt.datetime(2026, 11, 14, 16, 41, 36, tzinfo=UTC),
)


class ScriptedClient:
    """Stands in for ``forecast.http.HttpClient``: answers ``get`` from a script of bodies
    (bytes) or exceptions, in order, and records every call."""

    def __init__(self, *script, clock=None):
        self.script = list(script)
        self.clock = clock
        self.calls: list[dict] = []

    def get(self, url, *, headers=None, params=None, timeout_s=None):
        at = self.clock.monotonic() if self.clock else None
        self.calls.append({"url": url, "params": dict(params or {}), "at": at})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return HttpResponse(url, 200, {}, item)


class Clock:
    """A fake wall clock and monotonic clock; ``sleep`` moves both."""

    def __init__(self, start=dt.datetime(2026, 11, 14, 17, 0, 3, tzinfo=UTC)):
        self.t = start
        self.slept: list[float] = []

    def now(self):
        return self.t

    def monotonic(self):
        return self.t.timestamp()

    def sleep(self, s):
        self.slept.append(s)
        self.t += dt.timedelta(seconds=s)


@dataclass
class World:
    fetcher: Callable  # fetcher(*script, probe=...) -> (EsoFetcher, ScriptedClient)
    clock: Clock
    root: Path  # the store root (validation/eso-asm under a temp data root)


@pytest.fixture
def world(tmp_path):
    clock = Clock()
    manifest = Manifest(tmp_path / "state" / "manifest.sqlite")
    root = tmp_path / "data" / "validation" / "eso-asm"

    def fetcher(*script, probe=lambda path: None):
        client = ScriptedClient(*script, clock=clock)
        f = eso.EsoFetcher(
            client,
            manifest,
            root,
            now=clock.now,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            probe=probe,
        )
        return f, client

    yield World(fetcher, clock, root)
    manifest.close()


def test_a_fetch_stores_esos_bytes_unchanged_and_records_them(world):
    body = (FIXTURES / "paranal-mass.csv").read_bytes()
    f, _ = world.fetcher(body)

    got = f.fetch("paranal-mass", *NIGHT, label="night-2026-11-13")

    assert got.path == (
        world.root
        / "paranal-mass"
        / "2026"
        / "paranal-mass_night-2026-11-13_fetch1_20261114T170003Z.csv"
    )
    assert got.path.read_bytes() == body
    assert got.sha256 == hashlib.sha256(body).hexdigest()
    assert got.rows.series["free_atmosphere_seeing"].values.size == 8
    [rec] = f.history("paranal-mass", *NIGHT)
    assert (rec.path, rec.sha256, rec.bytes, rec.fetch_no) == (got.path, got.sha256, len(body), 1)
    assert rec.fetched_at == dt.datetime(2026, 11, 14, 17, 0, 3, tzinfo=UTC)
    assert rec.counts["rows"] == 8


def test_a_refetch_of_the_same_night_is_a_second_named_file(world):
    first_body = (FIXTURES / "paranal-dimm.csv").read_bytes()
    later_body = first_body.replace(b"0.993", b"0.990")  # ESO revised a value meanwhile
    f, _ = world.fetcher(first_body, later_body)

    first = f.fetch("paranal-dimm", *NIGHT, label="night-2026-11-13", purpose="nightly")
    world.clock.t += dt.timedelta(days=3)
    second = f.fetch("paranal-dimm", *NIGHT, label="night-2026-11-13", purpose="refetch")

    assert first.path.name == "paranal-dimm_night-2026-11-13_fetch1_20261114T170003Z.csv"
    assert second.path.name == "paranal-dimm_night-2026-11-13_fetch2_20261117T170003Z.csv"
    assert first.path.read_bytes() == first_body  # untouched
    assert second.path.read_bytes() == later_body
    assert [(r.fetch_no, r.purpose, r.sha256) for r in f.history("paranal-dimm", *NIGHT)] == [
        (1, "nightly", first.sha256),
        (2, "refetch", second.sha256),
    ]


def test_a_fetch_never_overwrites_an_existing_file(world):
    dest = (
        world.root
        / "paranal-dimm"
        / "2026"
        / ("paranal-dimm_night-2026-11-13_fetch1_20261114T170003Z.csv")
    )
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"already here")
    f, _ = world.fetcher((FIXTURES / "paranal-dimm.csv").read_bytes())

    with pytest.raises(eso.WriteOnceError):
        f.fetch("paranal-dimm", *NIGHT, label="night-2026-11-13")

    assert dest.read_bytes() == b"already here"
    assert f.history("paranal-dimm", *NIGHT) == []
    assert sorted(p.name for p in dest.parent.iterdir()) == [dest.name]  # no temp left


def test_transient_failures_are_retried_a_minute_apart_and_recorded(world):
    url = "https://archive.eso.org/wdb/wdb/asm/mass_paranal/query"
    f, client = world.fetcher(
        HttpError(url, 503, "Service Unavailable"),
        HttpUnavailable(url, "no complete answer (ConnectionError)"),
        (FIXTURES / "paranal-mass.csv").read_bytes(),
    )

    got = f.fetch("paranal-mass", *NIGHT)

    assert len(client.calls) == 3
    assert world.clock.slept == [60.0, 60.0]
    assert got.record.tries == 3
    errors = [e for _, e in f.failed_tries("paranal-mass", *NIGHT)]
    assert len(errors) == 2
    assert "503" in errors[0]
    assert "no complete answer" in errors[1]


_URL = "https://archive.eso.org/wdb/wdb/asm/dimm_paranal/query"


@pytest.mark.parametrize(
    ("script", "error", "calls"),
    [
        ([HttpError(_URL, 502, "Bad Gateway")] * 5, eso.EsoFetchFailed, 5),
        ([HttpError(_URL, 404, "Not Found")], eso.EsoFetchFailed, 1),
        ([b"<html>maintenance</html>"], eso.EsoFormatError, 1),
        ([(FIXTURES / "paranal-dimm-truncated.csv").read_bytes()], eso.EsoTruncated, 1),
    ],
    ids=["five-transient-failures", "http-404", "html-page", "cut-answer"],
)
def test_a_failed_fetch_stores_nothing_and_records_why(world, script, error, calls):
    f, client = world.fetcher(*script)

    with pytest.raises(error):
        f.fetch("paranal-dimm", *NIGHT)

    assert len(client.calls) == calls
    assert not world.root.exists() or not any(p.is_file() for p in world.root.rglob("*"))
    assert f.history("paranal-dimm", *NIGHT) == []
    assert len(f.failed_tries("paranal-dimm", *NIGHT)) == calls


def test_rows_outside_the_asked_range_are_refused(world):
    f, _ = world.fetcher((FIXTURES / "paranal-dimm.csv").read_bytes())  # rows on 2026-11-14
    later = (
        dt.datetime(2026, 11, 10, 16, 41, 36, tzinfo=UTC),
        dt.datetime(2026, 11, 11, 16, 41, 36, tzinfo=UTC),
    )

    with pytest.raises(eso.EsoFormatError, match="outside"):
        f.fetch("paranal-dimm", *later)

    assert f.history("paranal-dimm", *later) == []


def test_the_request_on_the_wire_names_the_utc_range_and_no_contact_details(world):
    from dataclasses import replace

    from astroseeing.forecast.http import HttpClient

    from fake_http import FakeHttpServer

    f, _ = world.fetcher()
    with FakeHttpServer() as host:  # no route: it answers 404, which ends the fetch
        f.client = HttpClient(timeout_s=5)
        f.settings = replace(f.settings, base_url=host.url + "/wdb/wdb/asm")
        with pytest.raises(eso.EsoFetchFailed, match="404"):
            f.fetch("paranal-mass", *NIGHT)
        [req] = host.requests

    assert req.path == "/wdb/wdb/asm/mass_paranal/query"
    assert req.query == {
        "wdbo": ["csv"],
        "start_date": ["2026-11-13T16:41:36..2026-11-14T16:41:35"],  # ESO's A..B includes B
        "tab_fwhm": ["on"],
        "tab_alt": ["on"],
        "tab_fracgl": ["on"],
        "tab_turbfwhm": ["on"],
        "max_rows_returned": ["200000"],
    }
    ua = req.headers["User-Agent"]
    assert ua.startswith("astro-seeing/")
    assert "@" not in ua and "http" not in ua


# --- spans --------------------------------------------------------------------------


def test_a_night_runs_from_local_mean_solar_noon_to_the_next():
    # Paranal at 70.40° W: noon is 12:00 + 70.40/15 h = 16:41:36 UTC.
    assert eso.night_span(dt.date(2026, 11, 13), -70.40) == NIGHT
    # La Silla at 70.73° W: 16:42:55.2 UTC, floored to ESO's whole seconds.
    start, end = eso.night_span(dt.date(2025, 6, 1), -70.73)
    assert start == dt.datetime(2025, 6, 1, 16, 42, 55, tzinfo=UTC)
    assert end - start == dt.timedelta(days=1)


def test_months_are_whole_utc_calendar_months_that_tile_the_period():
    spans = eso.month_spans("2021-01", "2025-12")

    assert len(spans) == 60
    assert spans[0] == (
        "2021-01",
        dt.datetime(2021, 1, 1, tzinfo=UTC),
        dt.datetime(2021, 2, 1, tzinfo=UTC),
    )
    assert spans[-1] == (
        "2025-12",
        dt.datetime(2025, 12, 1, tzinfo=UTC),
        dt.datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert all(a[2] == b[1] for a, b in itertools.pairwise(spans))


# --- bulk ---------------------------------------------------------------------------


def _month_answer(table_key: str, month: str) -> bytes:
    """A one-row answer inside ``month`` for ``table_key`` (headers from the fixtures)."""
    name = {"paranal-dimm": "paranal-dimm.csv", "paranal-mass": "paranal-mass.csv"}[table_key]
    lines = (FIXTURES / name).read_text().splitlines()
    header = next(ln for ln in lines if ln.startswith("Date time"))
    row = next(ln for ln in lines if ln.startswith("2026-"))
    row = f"{month}-02T03:04:05" + row[len("2026-11-14T00:00:13") :]
    return f"\n{header}\n{row}\n\n# A total of 1 records were found matching\n".encode()


def test_bulk_fetches_each_table_month_by_month_a_few_seconds_apart(world):
    answers = [
        _month_answer(t, m)
        for m in ("2023-06", "2023-07")
        for t in ("paranal-dimm", "paranal-mass")
    ]
    f, client = world.fetcher(*answers)

    done = f.bulk(["paranal-dimm", "paranal-mass"], "2023-06", "2023-07")

    assert [(r.table, r.label, r.purpose) for r in done.fetched] == [
        ("paranal-dimm", "2023-06", "bulk"),
        ("paranal-mass", "2023-06", "bulk"),
        ("paranal-dimm", "2023-07", "bulk"),
        ("paranal-mass", "2023-07", "bulk"),
    ]
    assert [c["params"]["start_date"] for c in client.calls[::2]] == [
        "2023-06-01T00:00:00..2023-06-30T23:59:59",
        "2023-07-01T00:00:00..2023-07-31T23:59:59",
    ]
    gaps = [b["at"] - a["at"] for a, b in itertools.pairwise(client.calls)]
    assert min(gaps) >= 5.0
    assert done.fetched[0].path.name.startswith("paranal-dimm_2023-06_fetch1_")


def test_bulk_stops_at_a_failure_and_a_rerun_fetches_only_what_is_missing(world):
    tables = ["paranal-dimm", "paranal-mass"]
    f, _ = world.fetcher(
        _month_answer("paranal-dimm", "2023-06"), HttpError(_URL, 400, "Bad Request")
    )
    with pytest.raises(eso.EsoFetchFailed):
        f.bulk(tables, "2023-06", "2023-07")

    world.clock.t += dt.timedelta(hours=1)
    f2, client = world.fetcher(
        _month_answer("paranal-mass", "2023-06"),
        _month_answer("paranal-dimm", "2023-07"),
        _month_answer("paranal-mass", "2023-07"),
    )
    done = f2.bulk(tables, "2023-06", "2023-07")

    assert done.skipped == [("paranal-dimm", "2023-06")]
    assert [(r.table, r.label) for r in done.fetched] == [
        ("paranal-mass", "2023-06"),
        ("paranal-dimm", "2023-07"),
        ("paranal-mass", "2023-07"),
    ]
    assert len(client.calls) == 3


def test_bulk_refuses_a_month_that_has_not_ended(world):
    f, client = world.fetcher()  # the clock reads 2026-11-14

    with pytest.raises(ValueError, match="2026-11"):
        f.bulk(["paranal-dimm"], "2026-10", "2026-11")

    assert client.calls == []


def test_a_store_that_does_not_answer_stops_the_fetch_before_any_request(world):
    from astroseeing.paths import StorageUnresponsive

    probed = []

    def hung(path):
        probed.append(path)
        raise StorageUnresponsive(f"{path} did not respond within 30 s")

    f, client = world.fetcher(b"never asked for", probe=hung)
    with pytest.raises(StorageUnresponsive):
        f.fetch("paranal-dimm", *NIGHT)

    assert client.calls == []
    assert probed == [world.root]


def test_probing_a_store_not_yet_created_checks_its_nearest_parent(tmp_path):
    from astroseeing.paths import probe_store

    probe_store(tmp_path / "validation" / "eso-asm")  # no error: tmp_path answers


# --- reading back -------------------------------------------------------------------


def test_a_stored_file_reads_back_as_its_typed_table_and_is_checked(world):
    f, _ = world.fetcher((FIXTURES / "paranal-mass.csv").read_bytes())
    [rec] = [f.fetch("paranal-mass", *NIGHT).record]

    rows = eso.read_stored(rec)
    assert rows.series["ground_fraction"].values[0] == 0.324

    rec.path.write_bytes(rec.path.read_bytes().replace(b"0.324", b"0.325"))
    with pytest.raises(eso.StoredFileChanged, match="SHA-256"):
        eso.read_stored(rec)


# --- command line -------------------------------------------------------------------


def test_cli_night_fetches_paranal_dimm_and_mass_for_the_named_night(
    world, monkeypatch, capsys, tmp_path
):
    from astroseeing import cli

    monkeypatch.setenv("ASTRO_LOG_DIR", str(tmp_path / "logs"))
    f, _ = world.fetcher(
        (FIXTURES / "paranal-dimm.csv").read_bytes(), (FIXTURES / "paranal-mass.csv").read_bytes()
    )
    monkeypatch.setattr(cli, "_eso_fetcher", lambda paths: f)

    assert cli.main(["eso", "night", "--evening", "2026-11-13"]) == 0

    assert [r.fetch_no for r in f.history("paranal-dimm", *NIGHT)] == [1]
    assert [r.label for r in f.history("paranal-mass", *NIGHT)] == ["night-2026-11-13"]
    assert "paranal-mass_night-2026-11-13_fetch1_" in capsys.readouterr().out


def test_cli_bulk_reports_a_failure_with_exit_code_1(world, monkeypatch, tmp_path):
    from astroseeing import cli

    monkeypatch.setenv("ASTRO_LOG_DIR", str(tmp_path / "logs"))
    f, _ = world.fetcher(_month_answer("paranal-dimm", "2023-06"), *[HttpError(_URL, 503, "x")] * 5)
    monkeypatch.setattr(cli, "_eso_fetcher", lambda paths: f)

    args = ["eso", "bulk", "--from", "2023-06", "--to", "2023-07", "--tables", "paranal-dimm"]
    assert cli.main(args) == 1
    june = eso.month_spans("2023-06", "2023-06")[0][1:]
    assert [r.label for r in f.history("paranal-dimm", *june)] == ["2023-06"]
    july = eso.month_spans("2023-07", "2023-07")[0][1:]
    assert f.history("paranal-dimm", *july) == []


def test_a_row_outside_the_range_is_refused_even_with_every_value_missing(world):
    body = (
        (FIXTURES / "lasilla-dimm.csv")
        .read_text()
        .replace("2025-06-01T00:09:56,0.51,1.20", "2025-06-03T00:00:00,,")
    )
    f, _ = world.fetcher(body.encode())
    day = (dt.datetime(2025, 6, 1, tzinfo=UTC), dt.datetime(2025, 6, 2, tzinfo=UTC))

    with pytest.raises(eso.EsoFormatError, match="outside"):
        f.fetch("lasilla-dimm", *day)


@pytest.mark.parametrize(
    "span",
    [
        (dt.datetime(2026, 11, 13, 16, 41, 36), dt.datetime(2026, 11, 14, 16, 41, 36)),
        (NIGHT[1], NIGHT[0]),
        (NIGHT[0].replace(microsecond=5), NIGHT[1]),
    ],
    ids=["naive-times", "end-before-start", "fractional-second"],
)
def test_a_range_must_be_whole_utc_seconds_with_start_before_end(world, span):
    f, client = world.fetcher()
    with pytest.raises(ValueError):
        f.fetch("paranal-dimm", *span)
    assert client.calls == []


# --- review fixes -------------------------------------------------------------------


def test_a_range_not_yet_over_is_refused_so_no_partial_night_is_stored(world):
    f, client = world.fetcher()  # the clock reads 2026-11-14 17:00:03
    tonight = eso.night_span(dt.date(2026, 11, 14), -70.40)

    with pytest.raises(ValueError, match="not over"):
        f.fetch("paranal-dimm", *tonight)

    assert client.calls == []


def test_fetch_night_names_the_night_and_its_refetch_by_the_same_range(world):
    f, _ = world.fetcher(
        (FIXTURES / "paranal-mass.csv").read_bytes(), (FIXTURES / "paranal-mass.csv").read_bytes()
    )

    first = f.fetch_night("paranal-mass", dt.date(2026, 11, 13), purpose="nightly")
    world.clock.t += dt.timedelta(days=3)
    again = f.fetch_night("paranal-mass", dt.date(2026, 11, 13), purpose="refetch")

    assert (first.record.start, first.record.end) == NIGHT
    assert first.record.label == "night-2026-11-13"
    assert [r.fetch_no for r in f.history("paranal-mass", *NIGHT)] == [1, 2]
    assert again.path.name.startswith("paranal-mass_night-2026-11-13_fetch2_")


def test_stored_files_are_readable_by_everyone(world):
    f, _ = world.fetcher((FIXTURES / "paranal-dimm.csv").read_bytes())
    got = f.fetch("paranal-dimm", *NIGHT)
    assert got.path.stat().st_mode & 0o777 == 0o644


def test_the_store_is_probed_again_just_before_the_write(world):
    from astroseeing.paths import StorageUnresponsive

    calls = []

    def hangs_second_time(path):
        calls.append(path)
        if len(calls) == 2:
            raise StorageUnresponsive(f"{path} did not respond within 30 s")

    f, client = world.fetcher((FIXTURES / "paranal-dimm.csv").read_bytes(), probe=hangs_second_time)
    with pytest.raises(StorageUnresponsive):
        f.fetch("paranal-dimm", *NIGHT)

    assert len(client.calls) == 1
    assert f.history("paranal-dimm", *NIGHT) == []


def test_repeated_and_out_of_order_times_are_counted_not_dropped():
    text = fixture("paranal-dimm.csv").replace(
        "2026-11-14T00:02:51,",
        "2026-11-14T00:00:13,",  # a repeat of row 1, then back in time
    )
    rows = eso.parse_csv(eso.table("paranal-dimm"), text)

    assert rows.series["seeing"].values.size == 8
    assert rows.counts()["duplicate_times"] == 1
    assert rows.counts()["out_of_order_times"] == 1


def test_cli_fetch_takes_utc_times_and_converts_zoned_ones(world, monkeypatch, tmp_path):
    from astroseeing import cli

    monkeypatch.setenv("ASTRO_LOG_DIR", str(tmp_path / "logs"))
    f, _ = world.fetcher((FIXTURES / "paranal-dimm.csv").read_bytes())
    monkeypatch.setattr(cli, "_eso_fetcher", lambda paths: f)

    args = [
        "eso",
        "fetch",
        "paranal-dimm",
        "--start",
        "2026-11-13T13:41:36-03:00",
        "--end",
        "2026-11-14T16:41:36",
    ]
    assert cli.main(args) == 0
    assert len(f.history("paranal-dimm", *NIGHT)) == 1
