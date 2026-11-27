"""The forecast manifest tables, read only (ticket #60).

``astro forecast status`` and ``astro forecast size-report`` must never write to the
manifest, so they don't open it through :class:`astroseeing.manifest.Manifest` (which
creates tables and upgrades columns on every open). They open the SQLite file with
``mode=ro`` instead: any write raises, and a manifest that doesn't exist is an error,
never created.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

#: The table the tick's heartbeat goes in (the tick writes it from ticket #61, F1-12).
#: Until a manifest has it, the last tick time is shown as not recorded.
HEARTBEAT_TABLE = "forecast_heartbeat"


class ManifestMissing(FileNotFoundError):
    pass


@dataclass(frozen=True)
class RunRecord:
    """One ``forecast_runs`` row as the reports show it: ``None`` means not recorded."""

    id: int
    model: str
    area: str
    run_time: dt.datetime
    first_seen_at: dt.datetime
    state: str
    steps_expected: tuple[int, ...]
    steps_verified: dict[int, str] | None
    bytes: int | None
    download_seconds: float | None
    processing_seconds: float | None
    derived_bytes: int | None

    @property
    def steps_ok(self) -> int | None:
        """How many expected steps verified, or None when no step has been checked."""
        if self.steps_verified is None:
            return None
        return sum(1 for s in self.steps_expected if self.steps_verified.get(s) == "ok")

    @property
    def publishing_delay_h(self) -> float:
        """Hours from run time to when we first saw the run published."""
        return (self.first_seen_at - self.run_time) / dt.timedelta(hours=1)


def _time(text: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(text)
    return t if t.tzinfo is not None else t.replace(tzinfo=dt.UTC)


def _record(r: sqlite3.Row) -> RunRecord:
    steps = r["steps_verified"]
    return RunRecord(
        id=r["id"],
        model=r["model"],
        area=r["area"],
        run_time=_time(r["run_time"]),
        first_seen_at=_time(r["first_seen_at"]),
        state=r["state"],
        steps_expected=tuple(json.loads(r["steps_expected"])),
        steps_verified=None if steps is None else {int(k): v for k, v in json.loads(steps).items()},
        bytes=r["bytes"],
        download_seconds=r["download_seconds"],
        processing_seconds=r["processing_seconds"],
        derived_bytes=r["derived_bytes"],
    )


def _iso(t: dt.datetime) -> str:
    """The manifest's own time text (``ForecastRecords``), for comparisons in SQL."""
    return t.astimezone(dt.UTC).isoformat(timespec="seconds")


class ReadOnlyManifest:
    """The forecast tables of a manifest file, opened read only."""

    def __init__(self, path: Path):
        path = Path(path)
        if not path.is_file():
            raise ManifestMissing(f"no manifest at {path}")
        self.path = path
        self.conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=60)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> ReadOnlyManifest:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _has_table(self, name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    def runs(
        self,
        start: dt.datetime | None = None,
        end: dt.datetime | None = None,
    ) -> list[RunRecord]:
        """Every forecast run with ``start <= run time < end``, by model, area and run
        time (none if the manifest predates the forecast tables)."""
        if not self._has_table("forecast_runs"):
            return []
        q, args = "SELECT * FROM forecast_runs WHERE 1=1", []
        if start is not None:
            q += " AND run_time >= ?"
            args.append(_iso(start))
        if end is not None:
            q += " AND run_time < ?"
            args.append(_iso(end))
        rows = self.conn.execute(q + " ORDER BY model, area, run_time", args).fetchall()
        return [_record(r) for r in rows]

    def last_tick(self) -> dt.datetime | None:
        """When the tick last ran, from its heartbeat; None if none is recorded."""
        if not self._has_table(HEARTBEAT_TABLE):
            return None
        row = self.conn.execute(f"SELECT max(at) FROM {HEARTBEAT_TABLE}").fetchone()
        return None if row is None or row[0] is None else _time(row[0])
