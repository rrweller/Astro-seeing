"""``astro forecast size-report`` (ticket #60; D51 item 11): what each forecast run
really cost, read from the manifest, and how big the stores are, set against the
estimates of D45 item 5 and D51 (evidence and item 3). The per-place day stores are the
ones the manifest records as settled (``forecast_place_days``, D80), measured on disk.

Read only: the manifest is opened with ``mode=ro`` and the folders are only listed and
measured. A value the manifest doesn't hold is shown as ``missing``, never as zero, and
every total says over how many runs it is taken.
"""

from __future__ import annotations

import datetime as dt
import os
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import astroseeing
from astroseeing.forecast.report.readonly import (
    PlaceDayRecord,
    ReadOnlyManifest,
    RunRecord,
)
from astroseeing.forecast.settings import ForecastSettings
from astroseeing.forecast.store import utc_text

MISSING = "missing"
#: A settled day whose store is on /data (``refused`` keeps the other store there).
STORED_OUTCOMES = ("written", "exists")


@dataclass(frozen=True)
class Estimate:
    what: str
    source: str
    estimate: str
    estimate_bytes: float
    note: str


#: Raw bytes per run of each model in the default place's area: D51 item 3 (ICON-EU at
#: 48 h) and D51's evidence (steps 0-36, the F1 box). MEPS's own figure was an estimate.
RUN_ESTIMATES: Mapping[str, Estimate] = {
    "icon_eu_48h": Estimate(
        "ICON-EU raw per 48 h run",
        "D51 item 3",
        "~4.4 GB",
        4.4e9,
        "passes through /staging; bytes as downloaded (bz2)",
    ),
    "gfs": Estimate(
        "GFS raw per run",
        "D51 evidence",
        "~30 MB",
        30e6,
        "estimate for steps 0-36; our runs are 0-48 h",
    ),
    "icon_eu": Estimate(
        "ICON-EU raw per run",
        "D51 evidence",
        "~3.3 GB",
        3.3e9,
        "estimate for steps 0-36; our runs are 0-48 h",
    ),
    "meps": Estimate(
        "MEPS raw per run",
        "D51 evidence",
        "~1 GB",
        1e9,
        "itself an estimate, for steps 0-36; our runs are 0-48 h",
    ),
    "ifs": Estimate(
        "IFS raw per run",
        "D51 evidence",
        "~0.46 GB",
        0.46e9,
        "estimate for steps 0-36; our runs are 0-48 h",
    ),
}
STORE_ESTIMATE = Estimate(
    "Store per saved place per day",
    "D45 item 5",
    "~46 KB",
    46e3,
    "mean over the day stores in the range",
)
GRIDS_ESTIMATE = Estimate(
    "F1 area grids", "D45 item 5", "under 1 GB", 1e9, "everything under /staging/forecast/products"
)


@dataclass(frozen=True)
class FolderSize:
    files: int
    bytes: int


@dataclass(frozen=True)
class PlaceStores:
    """One saved place's day stores on /data, as measured on disk (``files`` = days);
    ``None`` when the manifest records none for it."""

    place: str
    in_range: FolderSize | None
    all: FolderSize | None
    not_on_disk: tuple[str, ...]  # days recorded as stored whose store isn't there
    refused: tuple[str, ...]  # days refused: another store with other content is there
    not_counted: tuple[str, ...]  # entries in the place's folder the manifest doesn't record


@dataclass(frozen=True)
class SizeReport:
    start: dt.datetime
    end: dt.datetime
    now: dt.datetime
    manifest_path: Path
    places_root: Path
    products_root: Path
    commit: str
    config_hash: str
    default_area: str
    pairs: Sequence[tuple[str, str]]  # (model, area): the settings' own, then any other run's
    runs: Sequence[RunRecord]
    stores: Sequence[PlaceStores]
    products: Mapping[str, FolderSize] | None  # top-level entry → size; None: no folder


def _measure(path: Path) -> FolderSize:
    """Files and bytes under ``path`` (a file counts as itself); links not followed."""
    if not path.is_dir():
        return FolderSize(1, path.lstat().st_size)
    files = size = 0
    for root, _dirs, names in os.walk(path):
        for n in names:
            files += 1
            size += (Path(root) / n).lstat().st_size
    return FolderSize(files, size)


def _place_stores(
    folder: Path,
    place: str,
    days: Sequence[PlaceDayRecord],
    start: dt.datetime,
    end: dt.datetime,
) -> PlaceStores:
    """Measure the place's recorded day stores (each at its recorded path); a day is in
    the range when its 00 UTC is."""
    on_disk = sorted(e.name for e in folder.iterdir()) if folder.is_dir() else []
    recorded = {d.path.name for d in days}
    not_counted = tuple(n for n in on_disk if n not in recorded)
    stored = [d for d in days if d.outcome in STORED_OUTCOMES]
    refused = tuple(d.day.isoformat() for d in days if d.outcome not in STORED_OUTCOMES)
    if not stored:
        return PlaceStores(place, None, None, (), refused, not_counted)
    n_in = b_in = n_all = b_all = 0
    missing = []
    for d in stored:
        if not d.path.exists():
            missing.append(d.day.isoformat())
            continue
        size = _measure(d.path).bytes
        n_all, b_all = n_all + 1, b_all + size
        if start <= dt.datetime.combine(d.day, dt.time(), dt.UTC) < end:
            n_in, b_in = n_in + 1, b_in + size
    return PlaceStores(
        place, FolderSize(n_in, b_in), FolderSize(n_all, b_all), tuple(missing), refused,
        not_counted,
    )  # fmt: skip


def size_report(
    manifest: ReadOnlyManifest,
    settings: ForecastSettings,
    places_root: Path,
    products_root: Path,
    start: dt.datetime,
    end: dt.datetime,
    now: dt.datetime,
    commit: str,
) -> SizeReport:
    """Gather the runs with ``start <= run time < end``, the day stores whose day starts
    in that range (and all of them), and the SSD products as they are now.
    ``places_root`` is ``ForecastPaths.place_days``."""
    days = manifest.place_days()
    places = list(settings.places)
    places += sorted({d.place for d in days} - set(places))
    runs = manifest.runs(start, end)
    pairs = [(m, a.id) for a in settings.areas.values() for m in a.models]
    pairs += [p for p in dict.fromkeys((r.model, r.area) for r in runs) if p not in pairs]
    products = None
    if products_root.is_dir():
        products = {e.name: _measure(e) for e in sorted(products_root.iterdir())}
    return SizeReport(
        start=start,
        end=end,
        now=now,
        manifest_path=manifest.path,
        places_root=places_root,
        products_root=products_root,
        commit=commit,
        config_hash=settings.config_hash,
        default_area=settings.places[settings.default_place].area,
        pairs=pairs,
        runs=runs,
        stores=[
            _place_stores(places_root / p, p, [d for d in days if d.place == p], start, end)
            for p in places
        ],
        products=products,
    )


# -- Markdown ------------------------------------------------------------------------


def _human(n: float) -> str:
    """Decimal units, as the estimates are written."""
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= scale:
            return f"{n / scale:.{2 if unit == 'GB' else 1}f} {unit}"
    return f"{n:.0f} B"


def _secs(x: float | None) -> str:
    return MISSING if x is None else f"{x:.3f}"


def _exact(x: int | None) -> str:
    return MISSING if x is None else str(x)


def _row(cells: Sequence[object]) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _table(head: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    return [_row(head), _row(["---"] * len(head)), *(_row(r) for r in rows)]


def _total(values: Sequence[float | None], n_runs: int, fmt) -> str:
    """A total over the runs that have a value, saying how many do."""
    have = [v for v in values if v is not None]
    if not have:
        return f"{MISSING} (0 of {n_runs} runs)"
    return f"{fmt(sum(have))} ({len(have)} of {n_runs} runs)"


def _run_rows(runs: Sequence[RunRecord]) -> list[list[object]]:
    rows = []
    for r in runs:
        ok = r.steps_ok
        rows.append(
            [
                r.model,
                r.area,
                utc_text(r.run_time),
                r.state,
                utc_text(r.first_seen_at),
                f"{r.publishing_delay_h:.2f}",
                MISSING if ok is None else f"{ok}/{len(r.steps_expected)}",
                _exact(r.bytes),
                _secs(r.download_seconds),
                _secs(r.processing_seconds),
                _exact(r.derived_bytes),
                r.id,
            ]
        )
    return rows


def _model_rows(pairs: Sequence[tuple[str, str]], runs: Sequence[RunRecord]) -> list[list[object]]:
    rows = []
    for model, area in pairs:
        rs = [r for r in runs if (r.model, r.area) == (model, area)]
        n = len(rs)
        checked = [r for r in rs if r.steps_ok is not None]
        if checked:
            ok = sum(r.steps_ok for r in checked)
            expected = sum(len(r.steps_expected) for r in checked)
            steps = f"{ok} of {expected} ({len(checked)} of {n} runs)"
        else:
            steps = f"{MISSING} (0 of {n} runs)"
        sizes = [r.bytes for r in rs if r.bytes is not None]
        delays = [r.publishing_delay_h for r in rs]
        rows.append(
            [
                model,
                area,
                n,
                steps,
                _total([r.bytes for r in rs], n, str),
                f"{statistics.median(sizes):.0f}" if sizes else MISSING,
                f"{statistics.median(delays):.2f}" if delays else MISSING,
                f"{max(delays):.2f}" if delays else MISSING,
                _total([r.download_seconds for r in rs], n, _secs),
                _total([r.processing_seconds for r in rs], n, _secs),
                _total([r.derived_bytes for r in rs], n, str),
            ]
        )
    return rows


def _median_raw(runs: Sequence[RunRecord], model: str, area: str) -> str:
    sizes = [r.bytes for r in runs if r.model == model and r.area == area and r.bytes is not None]
    if not sizes:
        return f"{MISSING} (no {model} run in {area} with a size)"
    return f"{_human(statistics.median(sizes))} (median of {len(sizes)} runs)"


def _estimate_rows(rep: SizeReport) -> list[list[object]]:
    rows = []
    for key, e in RUN_ESTIMATES.items():
        model = "icon_eu" if key == "icon_eu_48h" else key
        rows.append(
            [e.what, e.source, e.estimate, _median_raw(rep.runs, model, rep.default_area), e.note]
        )
    in_range = [s.in_range for s in rep.stores if s.in_range is not None and s.in_range.files]
    days = sum(s.files for s in in_range)
    store = (
        f"{_human(sum(s.bytes for s in in_range) / days)} ({days} days)"
        if days
        else f"{MISSING} (no day store in the range)"
    )
    rows.append(
        [
            STORE_ESTIMATE.what,
            STORE_ESTIMATE.source,
            STORE_ESTIMATE.estimate,
            store,
            STORE_ESTIMATE.note,
        ]
    )
    products = (
        _human(sum(f.bytes for f in rep.products.values()))
        if rep.products is not None
        else f"{MISSING} (no products folder)"
    )
    rows.append(
        [
            GRIDS_ESTIMATE.what,
            GRIDS_ESTIMATE.source,
            GRIDS_ESTIMATE.estimate,
            products,
            GRIDS_ESTIMATE.note,
        ]
    )
    return rows


def render_size_report(rep: SizeReport) -> str:
    out = [
        f"# Forecast measured sizes, {utc_text(rep.start)} to {utc_text(rep.end)}",
        "",
        f"Written {utc_text(rep.now)} by `astro forecast size-report` (ticket #60, D51 item "
        f"11) from the manifest `{rep.manifest_path}`, opened read only. Commit "
        f"`{rep.commit}`, astroseeing {astroseeing.__version__}, forecast settings hash "
        f"`{rep.config_hash}`.",
        "",
        "Runs are those whose run time falls in the range. A value the manifest doesn't "
        "hold is shown as **missing**, never as zero; each total says how many runs it "
        "covers. Bytes are exact; seconds are rounded to the millisecond; the publishing "
        "delay is from run time to when the tick first saw the run. Bytes are as "
        "downloaded (ICON-EU's files are bz2). `run id` is the manifest's "
        "`forecast_runs.id`.",
        "",
        "## Runs",
        "",
        *_table(
            [
                "model",
                "area",
                "run time",
                "state",
                "first seen",
                "delay h",
                "steps verified",
                "bytes",
                "download s",
                "processing s",
                "derived bytes",
                "run id",
            ],
            _run_rows(rep.runs),
        ),
        "",
        "## Per model",
        "",
        *_table(
            [
                "model",
                "area",
                "runs",
                "steps verified",
                "bytes",
                "median bytes per run",
                "median delay h",
                "max delay h",
                "download s",
                "processing s",
                "derived bytes",
            ],
            _model_rows(rep.pairs, rep.runs),
        ),
        "",
        "## Saved places' day stores on /data",
        "",
        f"The day stores the manifest records as settled, measured on disk under "
        f"`{rep.places_root}`; a day is in the range when its 00 UTC is.",
        "",
    ]
    store_rows = []
    for s in rep.stores:
        if s.in_range is None or s.all is None:
            store_rows.append([s.place, MISSING, MISSING, MISSING, MISSING, MISSING])
            continue
        mean = str(round(s.in_range.bytes / s.in_range.files)) if s.in_range.files else MISSING
        store_rows.append(
            [s.place, s.in_range.files, s.in_range.bytes, mean, s.all.files, s.all.bytes]
        )
    out += _table(
        [
            "place",
            "days in range",
            "bytes in range",
            "mean bytes per day",
            "days in all",
            "bytes in all",
        ],
        store_rows,
    )
    for s in rep.stores:
        for what, names in (
            ("Recorded as stored but not on disk", s.not_on_disk),
            ("Refused (another store with other content is there)", s.refused),
            ("Not counted (not in the manifest)", s.not_counted),
        ):
            if names:
                out.append(f"\n{what}, {s.place}: {', '.join(names)}.")
    out += ["", "## SSD products", "", f"Under `{rep.products_root}`, as they are now.", ""]
    if rep.products is None:
        out += _table(["entry", "files", "bytes"], [[MISSING, MISSING, MISSING]])
    else:
        rows = [[k, v.files, v.bytes] for k, v in rep.products.items()]
        rows.append(
            [
                "total",
                sum(v.files for v in rep.products.values()),
                sum(v.bytes for v in rep.products.values()),
            ]
        )
        out += _table(["entry", "files", "bytes"], rows)
    out += [
        "",
        "## Against the estimates",
        "",
        f"Raw sizes are for the default place's area, `{rep.default_area}`.",
        "",
        *_table(["what", "source", "estimate", "measured", "note"], _estimate_rows(rep)),
        "",
    ]
    return "\n".join(out)
