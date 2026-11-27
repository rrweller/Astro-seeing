"""ESO's ambient-conditions archive: Paranal DIMM and MASS, La Silla DIMM (D28, D54, D65).

One fetcher for both tracks: the forecast tick's daily Paranal step (D54 item 8) and
the historical calibration's 2021–2025 bulk fetch (roadmap K8).
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import logging
import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from astroseeing.config import load_config
from astroseeing.forecast.http import HttpError, HttpUnavailable, RatePacer
from astroseeing.manifest import Manifest
from astroseeing.paths import probe_responsive

log = logging.getLogger(__name__)

TIME_HEADER = "Date time"
_CUT = re.compile(r"^# A maximum of (\d+) records were found")
_TOTAL = re.compile(r"^# A total of (\d+) records were found")


class EsoFormatError(ValueError):
    """ESO's answer is not the CSV layout we know; nothing from it is stored."""


class EsoTruncated(EsoFormatError):
    """ESO stopped at ``max_rows_returned``: the answer is incomplete, so it is refused."""


@dataclass(frozen=True)
class Column:
    name: str  # our name in the typed table
    flag: str  # the query form's switch, e.g. "tab_fwhm"
    header: str  # the column name in ESO's CSV answer
    unit: str


@dataclass(frozen=True)
class Table:
    """One ESO query form and the columns we take from it (``configs/eso.yaml``)."""

    key: str
    form: str
    lon_deg: float
    columns: tuple[Column, ...]


def table(key: str) -> Table:
    t = load_config("eso")["tables"][key]
    cols = tuple(
        Column(name, c["flag"], c["header"], c["unit"]) for name, c in t["columns"].items()
    )
    return Table(key, t["form"], float(t["lon_deg"]), cols)


@dataclass(frozen=True)
class Series:
    """One column's numeric samples; rows where it was missing or non-numeric are left
    out and counted."""

    name: str
    header: str
    unit: str
    times: np.ndarray  # datetime64[s], UTC
    values: np.ndarray  # float64, exactly as ESO wrote them (nothing clipped)
    missing: int
    nonnumeric: int


@dataclass(frozen=True)
class EsoRows:
    """A parsed ESO answer: one :class:`Series` per configured column."""

    table: str
    rows: int  # data rows in the answer
    times: np.ndarray  # datetime64[s] of every row with a readable time and field count
    series: Mapping[str, Series]
    malformed_rows: int  # wrong number of fields: dropped from every column
    bad_times: int  # unreadable time: dropped from every column

    def dropped(self) -> int:
        """Values left out, over all columns (each malformed or bad-time row counts once
        per column)."""
        per_row = (self.malformed_rows + self.bad_times) * len(self.series)
        return per_row + sum(s.missing + s.nonnumeric for s in self.series.values())

    def counts(self) -> dict:
        return {
            "rows": self.rows,
            "malformed_rows": self.malformed_rows,
            "bad_times": self.bad_times,
            "columns": {
                n: {"kept": int(s.values.size), "missing": s.missing, "nonnumeric": s.nonnumeric}
                for n, s in self.series.items()
            },
        }


def parse_csv(tbl: Table, text: str) -> EsoRows:
    """Parse one ESO CSV answer into a typed table.

    The layout is checked first: a ``# A total of N records`` footer, a header starting
    with ``Date time`` that names every configured column, and exactly N rows. Anything
    else (an HTML error page, a cut answer, a renamed column) raises
    :class:`EsoFormatError`, so nothing is stored from it.
    """
    expected = _record_count(tbl, text)
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        if expected:
            raise EsoFormatError(f"{tbl.key}: footer says {expected} records but no rows")
        no_times = np.empty(0, "datetime64[s]")
        return EsoRows(tbl.key, 0, no_times, _series(tbl, no_times, [], []), 0, 0)
    reader = csv.reader(lines)
    header = next(reader)
    if not header or header[0] != TIME_HEADER:
        raise EsoFormatError(f"{tbl.key}: first column is {header[:1]}, not {TIME_HEADER!r}")
    missing = [c.header for c in tbl.columns if c.header not in header]
    if missing:
        raise EsoFormatError(f"{tbl.key}: answer lacks column(s) {missing}; has {header}")
    data = list(reader)
    if len(data) != expected:
        raise EsoFormatError(f"{tbl.key}: footer says {expected} records but {len(data)} rows")
    good, times, malformed, bad_times = [], [], 0, 0
    for r in data:
        if len(r) != len(header):
            malformed += 1
            continue
        try:
            t = dt.datetime.fromisoformat(r[0])
        except ValueError:
            bad_times += 1
            continue
        good.append(r)
        if t.tzinfo is not None:  # ESO writes naive UTC; convert any other zone
            t = t.astimezone(dt.UTC).replace(tzinfo=None)
        times.append(np.datetime64(t, "s"))
    t64 = np.array(times, "datetime64[s]")
    rows = EsoRows(tbl.key, len(data), t64, _series(tbl, t64, header, good), malformed, bad_times)
    if rows.dropped():
        log.warning("%s: values left out of the typed table: %s", tbl.key, rows.counts())
    return rows


def _record_count(tbl: Table, text: str) -> int:
    for ln in text.splitlines():
        if _CUT.match(ln):
            raise EsoTruncated(f"{tbl.key}: {ln.lstrip('# ').strip()}")
        if m := _TOTAL.match(ln):
            return int(m.group(1))
    raise EsoFormatError(f"{tbl.key}: no '# A total of N records' record count in the answer")


def _number(text: str) -> float | str | None:
    """The value, ``None`` if the field is empty, or ``"nonnumeric"``."""
    if not text.strip():
        return None
    try:
        x = float(text)
    except ValueError:
        return "nonnumeric"
    return x if math.isfinite(x) else "nonnumeric"


def _series(tbl: Table, times: np.ndarray, header: list[str], data) -> dict[str, Series]:
    series = {}
    for c in tbl.columns:
        j = header.index(c.header) if data else 0
        keep, vals, missing, nonnumeric = [], [], 0, 0
        for i, r in enumerate(data):
            v = _number(r[j])
            if v is None:
                missing += 1
            elif v == "nonnumeric":
                nonnumeric += 1
            else:
                keep.append(i)
                vals.append(v)
        ts = times[np.array(keep, np.int64)] if keep else np.empty(0, "datetime64[s]")
        series[c.name] = Series(
            c.name, c.header, c.unit, ts, np.array(vals, np.float64), missing, nonnumeric
        )
    return series


# --- spans -------------------------------------------------------------------------


def night_span(evening: dt.date, lon_deg: float) -> tuple[dt.datetime, dt.datetime]:
    """The Night named by ``evening`` at longitude ``lon_deg`` (east-positive): local mean
    solar noon, 12:00 UTC - λ/15 h, to the next (``CONTEXT.md``), floored to whole
    seconds as ESO's times are."""
    noon = dt.datetime(evening.year, evening.month, evening.day, 12, tzinfo=dt.UTC)
    after_noon_s = round(-lon_deg * 240.0, 6)  # 3600 s / 15°; rounded off float noise
    start = noon + dt.timedelta(seconds=math.floor(after_noon_s))
    return start, start + dt.timedelta(days=1)


def month_spans(first: str, last: str) -> list[tuple[str, dt.datetime, dt.datetime]]:
    """(label ``YYYY-MM``, start, end) for each UTC calendar month from ``first`` to
    ``last`` (both ``YYYY-MM``, inclusive)."""
    y, m = (int(x) for x in first.split("-"))
    ly, lm = (int(x) for x in last.split("-"))
    out = []
    while (y, m) <= (ly, lm):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append(
            (
                f"{y:04d}-{m:02d}",
                dt.datetime(y, m, 1, tzinfo=dt.UTC),
                dt.datetime(ny, nm, 1, tzinfo=dt.UTC),
            )
        )
        y, m = ny, nm
    return out


# --- fetching and storing -----------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """``configs/eso.yaml``."""

    base_url: str
    store_dir: str
    max_rows: int
    timeout_s: float
    min_interval_s: float
    attempts: int
    spacing_s: float

    @classmethod
    def load(cls) -> Settings:
        c = load_config("eso")
        return cls(
            c["base_url"].rstrip("/"),
            c["store_dir"],
            int(c["max_rows"]),
            float(c["timeout_s"]),
            float(c["min_interval_s"]),
            int(c["retries"]["attempts"]),
            float(c["retries"]["spacing_s"]),
        )


@dataclass(frozen=True)
class FetchRecord:
    """One raw CSV written once, as the manifest records it."""

    table: str
    start: dt.datetime
    end: dt.datetime
    label: str
    purpose: str
    fetch_no: int  # 1 for the first fetch of this table and range, 2 for the next, ...
    url: str
    path: Path
    bytes: int
    sha256: str
    counts: dict
    tries: int
    fetched_at: dt.datetime


@dataclass(frozen=True)
class Fetched:
    """What :meth:`EsoFetcher.fetch` returns: the stored file and its typed table."""

    record: FetchRecord
    rows: EsoRows

    @property
    def path(self) -> Path:
        return self.record.path

    @property
    def sha256(self) -> str:
        return self.record.sha256


@dataclass
class BulkResult:
    fetched: list[FetchRecord]
    skipped: list[tuple[str, str]]  # (table, month) already stored before this run


def _stamp(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def _iso(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).isoformat(timespec="seconds")


class EsoFetcher:
    """Fetches ESO answers by UTC range and writes each one once under ``root``.

    ``client`` is a ``forecast.http.HttpClient`` (generic User-Agent, one attempt per
    call); ``now``, ``sleep`` and ``monotonic`` are injectable for tests.
    """

    def __init__(
        self,
        client,
        manifest: Manifest,
        root: Path,
        *,
        settings: Settings | None = None,
        now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        probe: Callable[[Path], None] | None = None,
    ):
        self.client = client
        self.manifest = manifest
        self.root = Path(root)
        self.settings = settings or Settings.load()
        self.now, self.sleep, self.monotonic = now, sleep, monotonic
        self.probe = probe or probe_store
        self.pacer = RatePacer(1.0 / self.settings.min_interval_s, monotonic, sleep)

    def fetch(
        self,
        table_key: str,
        start: dt.datetime,
        end: dt.datetime,
        *,
        label: str | None = None,
        purpose: str = "adhoc",
    ) -> Fetched:
        _check_span(start, end)
        tbl = table(table_key)
        self.probe(self.root)  # a dropped NAS hangs instead of failing (AGENTS.md)
        label = label or f"{_stamp(start)}-{_stamp(end)}"
        url = f"{self.settings.base_url}/{tbl.form}/query"
        resp, tries = self._get(tbl, url, self._params(tbl, start, end), start, end)
        fetched_at = self.now().astimezone(dt.UTC).replace(microsecond=0)
        try:
            rows = parse_csv(tbl, _decode(tbl, resp.body))
            _check_range(rows, start, end)
        except EsoFormatError as e:
            self._failed_try(tbl, start, end, f"try {tries}: {e}")
            raise
        fetch_no = len(self.history(table_key, start, end)) + 1
        name = f"{tbl.key}_{label}_fetch{fetch_no}_{_stamp(fetched_at)}.csv"
        dest = self.root / tbl.key / f"{start.astimezone(dt.UTC):%Y}" / name
        sha = write_once(dest, resp.body)
        rec = FetchRecord(
            tbl.key,
            start,
            end,
            label,
            purpose,
            fetch_no,
            url,
            dest,
            len(resp.body),
            sha,
            rows.counts(),
            tries,
            fetched_at,
        )
        self._record(rec)
        return Fetched(rec, rows)

    def bulk(self, table_keys: list[str], first: str, last: str) -> BulkResult:
        """Fetch every table for each UTC calendar month from ``first`` to ``last``
        (``YYYY-MM``), skipping a table-month already stored, so a rerun resumes.

        Requests start at least ``min_interval_s`` apart. The first failure stops the
        run (ESO down, or a changed format): what was stored stays recorded, and the
        error is raised for the caller to report.
        """
        spans = month_spans(first, last)
        unfinished = [label for label, _, end in spans if end > self.now()]
        if unfinished:
            raise ValueError(
                f"months not yet over, so their files would be incomplete: {unfinished}"
            )
        result = BulkResult([], [])
        for label, start, end in spans:
            for key in table_keys:
                if self.history(key, start, end):
                    result.skipped.append((key, label))
                    continue
                got = self.fetch(key, start, end, label=label, purpose="bulk")
                result.fetched.append(got.record)
                log.info("%s %s: %d rows -> %s", key, label, got.rows.rows, got.path)
        return result

    def history(self, table_key: str, start: dt.datetime, end: dt.datetime) -> list[FetchRecord]:
        """Every stored fetch of this table and range, oldest first."""
        cur = self.manifest.conn.execute(
            "SELECT * FROM eso_fetches WHERE table_key=? AND start_utc=? AND end_utc=? "
            "ORDER BY fetch_no",
            (table_key, _iso(start), _iso(end)),
        )
        return [_record_from_row(r) for r in cur]

    def failed_tries(
        self, table_key: str, start: dt.datetime, end: dt.datetime
    ) -> list[tuple[dt.datetime, str]]:
        """Every failed try for this table and range: (when, error), oldest first."""
        cur = self.manifest.conn.execute(
            "SELECT at, error FROM eso_fetch_tries WHERE table_key=? AND start_utc=? "
            "AND end_utc=? ORDER BY id",
            (table_key, _iso(start), _iso(end)),
        )
        return [(dt.datetime.fromisoformat(r["at"]), r["error"]) for r in cur]

    def _get(
        self, tbl: Table, url: str, params: dict[str, str], start: dt.datetime, end: dt.datetime
    ):
        """GET with D51 item 7's retries: up to ``attempts`` tries, ``spacing_s`` apart,
        for no answer or HTTP 429/5xx. Any other HTTP error ends at once."""
        n = self.settings.attempts
        for attempt in range(1, n + 1):
            self.pacer.wait()
            try:
                return self.client.get(
                    url, params=params, timeout_s=self.settings.timeout_s
                ), attempt
            except HttpError as e:
                self._failed_try(tbl, start, end, f"try {attempt}/{n}: {e}")
                if not _transient(e):
                    raise EsoFetchFailed(f"{tbl.key}: {e} (not retried)") from e
                if attempt == n:
                    raise EsoFetchFailed(f"{tbl.key}: {n} tries failed; last: {e}") from e
                log.warning(
                    "%s: try %d/%d failed (%s); again in %.0f s",
                    tbl.key,
                    attempt,
                    n,
                    e,
                    self.settings.spacing_s,
                )
                self.sleep(self.settings.spacing_s)
        raise AssertionError("unreachable")

    def _failed_try(self, tbl: Table, start: dt.datetime, end: dt.datetime, error: str) -> None:
        with self.manifest.tx() as c:
            c.execute(
                "INSERT INTO eso_fetch_tries (table_key, start_utc, end_utc, at, error) "
                "VALUES (?,?,?,?,?)",
                (tbl.key, _iso(start), _iso(end), _iso(self.now()), error),
            )

    def _params(self, tbl: Table, start: dt.datetime, end: dt.datetime) -> dict[str, str]:
        last = end - dt.timedelta(seconds=1)  # ESO's A..B includes B
        fmt = "%Y-%m-%dT%H:%M:%S"
        p = {
            "wdbo": "csv",
            "start_date": f"{start.astimezone(dt.UTC):{fmt}}..{last.astimezone(dt.UTC):{fmt}}",
        }
        p |= {c.flag: "on" for c in tbl.columns}
        p["max_rows_returned"] = str(self.settings.max_rows)
        return p

    def _record(self, r: FetchRecord) -> None:
        with self.manifest.tx() as c:
            c.execute(
                "INSERT INTO eso_fetches (table_key, start_utc, end_utc, label, purpose, "
                "fetch_no, url, path, bytes, sha256, counts_json, tries, fetched_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r.table,
                    _iso(r.start),
                    _iso(r.end),
                    r.label,
                    r.purpose,
                    r.fetch_no,
                    r.url,
                    str(r.path),
                    r.bytes,
                    r.sha256,
                    json.dumps(r.counts, sort_keys=True),
                    r.tries,
                    _iso(r.fetched_at),
                ),
            )


def _check_span(start: dt.datetime, end: dt.datetime) -> None:
    for t in (start, end):
        if t.tzinfo is None or t.utcoffset() is None:
            raise ValueError(f"{t} has no time zone; give UTC times")
        if t.microsecond:
            raise ValueError(f"{t} is not a whole second (ESO's times are)")
    if not start < end:
        raise ValueError(f"empty range: {start} to {end}")


def _check_range(rows: EsoRows, start: dt.datetime, end: dt.datetime) -> None:
    """Every row's time must lie in [start, end): otherwise ESO did not answer what was
    asked (a changed query syntax, say), and the answer must not be filed under it."""
    lo = np.datetime64(start.astimezone(dt.UTC).replace(tzinfo=None), "s")
    hi = np.datetime64(end.astimezone(dt.UTC).replace(tzinfo=None), "s")
    out = int(((rows.times < lo) | (rows.times >= hi)).sum())
    if out:
        raise EsoFormatError(
            f"{rows.table}: {out} rows outside the asked range [{_iso(start)}, {_iso(end)})"
        )


def _decode(tbl: Table, body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as e:
        raise EsoFormatError(f"{tbl.key}: answer is not UTF-8 text ({e})") from e


class EsoFetchFailed(RuntimeError):
    """ESO did not answer usefully within the allowed tries; nothing was stored."""


def _transient(e: HttpError) -> bool:
    return isinstance(e, HttpUnavailable) or e.status == 429 or (e.status or 0) >= 500


def _record_from_row(r) -> FetchRecord:
    return FetchRecord(
        r["table_key"],
        dt.datetime.fromisoformat(r["start_utc"]),
        dt.datetime.fromisoformat(r["end_utc"]),
        r["label"],
        r["purpose"],
        r["fetch_no"],
        r["url"],
        Path(r["path"]),
        r["bytes"],
        r["sha256"],
        json.loads(r["counts_json"]),
        r["tries"],
        dt.datetime.fromisoformat(r["fetched_at"]),
    )


class StoredFileChanged(RuntimeError):
    """A stored raw file no longer has the SHA-256 the manifest recorded."""


def read_stored(rec: FetchRecord) -> EsoRows:
    """The typed table of a stored raw file, after checking it still has the SHA-256 the
    manifest recorded when it was written."""
    data = rec.path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != rec.sha256:
        raise StoredFileChanged(f"{rec.path}: SHA-256 {sha} differs from the recorded {rec.sha256}")
    return parse_csv(table(rec.table), _decode(table(rec.table), data))


def probe_store(root: Path, timeout_s: float = 30.0) -> None:
    """Raise ``StorageUnresponsive`` if the store (or, before its first file, its nearest
    existing parent) does not answer a ``stat`` within ``timeout_s``."""
    p = Path(root)
    while True:  # every stat happens in the probe's child process, never here
        try:
            return probe_responsive(p, timeout_s)
        except FileNotFoundError:
            if p == p.parent:
                raise
            p = p.parent


class WriteOnceError(FileExistsError):
    """The destination already exists; raw files are never overwritten."""


def write_once(dest: Path, data: bytes) -> str:
    """Write ``data`` to ``dest`` atomically, refusing to replace anything, and return
    its SHA-256 as read back from disk.

    The bytes go to a temp file in the same folder (fsync), which is then hard-linked to
    ``dest``: ``link`` fails if ``dest`` exists, so even a race can't overwrite a file.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise WriteOnceError(f"{dest} already exists; raw ESO files are never overwritten")
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, dest)
        except FileExistsError as e:
            raise WriteOnceError(
                f"{dest} already exists; raw ESO files are never overwritten"
            ) from e
    finally:
        Path(tmp).unlink(missing_ok=True)
    sha = hashlib.sha256(dest.read_bytes()).hexdigest()
    if sha != hashlib.sha256(data).hexdigest():
        raise OSError(f"{dest}: read back a different SHA-256 than was written")
    return sha
