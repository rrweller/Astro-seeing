"""The forecast's manifest records: ``forecast_runs``, ``forecast_files``,
``forecast_step_tries`` and ``forecast_hosts`` (spec Module 2, D51 items 6, 7, 11 and
14). The tables live in the same SQLite manifest as the CDS requests
(``manifest.FORECAST_SCHEMA``) and only this class writes them.

Run states: ``seen`` → ``fetching`` → ``fetched`` → ``verified`` → ``processed``, or
``partial`` (stored for its verified steps only; still retrying while a missing step
has tries left), ``failed`` (with ``last_error``) or ``abandoned`` (given up while steps
were still to fetch; it keeps whatever it stored). Transitions are compare-and-set,
like the CDS requests'. Every time is passed in by the caller, so the tick's clock (a
fake one in tests) is the only clock.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astroseeing.forecast.sources.interface import FetchedFile
from astroseeing.manifest import Manifest, StateError

RUN_STATES = (
    "seen",
    "fetching",
    "fetched",
    "verified",
    "processed",
    "partial",
    "failed",
    "abandoned",
)
#: States whose stored values the page uses (an abandoned run only if it stored any).
USABLE_STATES = ("processed", "partial", "abandoned")
#: States of a run the tick still works on (fetching steps, or recovering from a stop).
OPEN_STATES = ("seen", "fetching", "fetched", "verified", "partial")


@dataclass(frozen=True)
class ForecastRun:
    id: int
    model: str
    area: str
    run_time: dt.datetime
    state: str
    steps_expected: tuple[int, ...]
    steps_verified: dict[int, str] | None
    bytes: int | None
    derived_bytes: int | None
    attempts: int
    last_error: str | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> ForecastRun:
        steps = r["steps_verified"]
        return cls(
            id=r["id"],
            model=r["model"],
            area=r["area"],
            run_time=dt.datetime.fromisoformat(r["run_time"]),
            state=r["state"],
            steps_expected=tuple(json.loads(r["steps_expected"])),
            steps_verified=None
            if steps is None
            else {int(k): v for k, v in json.loads(steps).items()},
            bytes=r["bytes"],
            derived_bytes=r["derived_bytes"],
            attempts=r["attempts"],
            last_error=r["last_error"],
        )


@dataclass(frozen=True)
class StepTry:
    """One try to fetch one step of a run: when, on which host, and the error (None: ok)."""

    at: dt.datetime
    host: str
    error: str | None


@dataclass(frozen=True)
class HostState:
    """A model's host choice (D51 item 14): ``current`` is ``main`` or ``fallback``;
    ``main_failing_since`` is the first failed check of the main host since it last
    answered."""

    current: str
    main_failing_since: dt.datetime | None
    switched_at: dt.datetime | None


def _time(text: str | None) -> dt.datetime | None:
    return None if text is None else dt.datetime.fromisoformat(text)


def _iso(t: dt.datetime) -> str:
    if t.tzinfo is None:
        raise ValueError(f"naive datetime {t!r}; forecast records are UTC-aware")
    return t.astimezone(dt.UTC).isoformat(timespec="seconds")


class ForecastRecords:
    def __init__(self, manifest: Manifest):
        self.manifest = manifest

    def seen(
        self, model: str, area: str, run_time: dt.datetime, steps: Iterable[int], at: dt.datetime
    ) -> int:
        """Record a newly published run (idempotent: an existing run keeps its row)."""
        with self.manifest.tx() as c:
            row = c.execute(
                "SELECT id FROM forecast_runs WHERE model=? AND area=? AND run_time=?",
                (model, area, _iso(run_time)),
            ).fetchone()
            if row is not None:
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO forecast_runs (model, area, run_time, first_seen_at, state,"
                " steps_expected, updated_at) VALUES (?,?,?,?,?,?,?)",
                (model, area, _iso(run_time), _iso(at), "seen", json.dumps(list(steps)), _iso(at)),
            )
            return int(cur.lastrowid)

    def find(self, model: str, area: str, run_time: dt.datetime) -> ForecastRun | None:
        r = self.manifest.conn.execute(
            "SELECT * FROM forecast_runs WHERE model=? AND area=? AND run_time=?",
            (model, area, _iso(run_time)),
        ).fetchone()
        return None if r is None else ForecastRun.from_row(r)

    def get(self, run_id: int) -> ForecastRun:
        r = self.manifest.conn.execute(
            "SELECT * FROM forecast_runs WHERE id=?", (run_id,)
        ).fetchone()
        if r is None:
            raise KeyError(run_id)
        return ForecastRun.from_row(r)

    def latest(
        self,
        model: str,
        area: str,
        states: Iterable[str] = USABLE_STATES,
        not_after: dt.datetime | None = None,
    ) -> ForecastRun | None:
        """The newest run of a model and area in one of ``states`` (an abandoned run only
        if it stored values)."""
        states = tuple(states)
        q = (
            f"SELECT * FROM forecast_runs WHERE model=? AND area=?"
            f" AND state IN ({','.join('?' * len(states))})"
            " AND (state != 'abandoned' OR derived_bytes IS NOT NULL)"
        )
        args: list[Any] = [model, area, *states]
        if not_after is not None:
            q += " AND run_time <= ?"
            args.append(_iso(not_after))
        r = self.manifest.conn.execute(q + " ORDER BY run_time DESC LIMIT 1", args).fetchone()
        return None if r is None else ForecastRun.from_row(r)

    def runs_in(self, model: str, area: str, states: Iterable[str]) -> list[ForecastRun]:
        """Every run of a model and area in one of ``states``, newest first."""
        states = tuple(states)
        rows = self.manifest.conn.execute(
            f"SELECT * FROM forecast_runs WHERE model=? AND area=?"
            f" AND state IN ({','.join('?' * len(states))}) ORDER BY run_time DESC",
            (model, area, *states),
        ).fetchall()
        return [ForecastRun.from_row(r) for r in rows]

    def newest(self, model: str, area: str) -> ForecastRun | None:
        """The newest run of a model and area in any state."""
        r = self.manifest.conn.execute(
            "SELECT * FROM forecast_runs WHERE model=? AND area=? ORDER BY run_time DESC LIMIT 1",
            (model, area),
        ).fetchone()
        return None if r is None else ForecastRun.from_row(r)

    def count_attempt(self, run_id: int, at: dt.datetime) -> None:
        """One more tick has tried to fetch this run's steps."""
        with self.manifest.tx() as c:
            c.execute(
                "UPDATE forecast_runs SET attempts = attempts + 1, updated_at=? WHERE id=?",
                (_iso(at), run_id),
            )

    def add_try(
        self, run_id: int, step: int, host: str, at: dt.datetime, error: str | None
    ) -> None:
        with self.manifest.tx() as c:
            c.execute(
                "INSERT INTO forecast_step_tries (run_id, step, host, at, error)"
                " VALUES (?,?,?,?,?)",
                (run_id, step, host, _iso(at), error),
            )

    def tries(self, run_id: int) -> dict[int, list[StepTry]]:
        """Every try of each step of a run, oldest first."""
        out: dict[int, list[StepTry]] = {}
        for r in self.manifest.conn.execute(
            "SELECT * FROM forecast_step_tries WHERE run_id=? ORDER BY id", (run_id,)
        ):
            out.setdefault(r["step"], []).append(StepTry(_time(r["at"]), r["host"], r["error"]))
        return out

    def host_state(self, model: str) -> HostState:
        r = self.manifest.conn.execute(
            "SELECT * FROM forecast_hosts WHERE model=?", (model,)
        ).fetchone()
        if r is None:
            return HostState("main", None, None)
        return HostState(r["current"], _time(r["main_failing_since"]), _time(r["switched_at"]))

    def set_host_state(self, model: str, state: HostState, at: dt.datetime) -> None:
        """Record a model's host choice; nothing is written if it is unchanged."""
        if state == self.host_state(model):
            return
        since, switched = state.main_failing_since, state.switched_at
        with self.manifest.tx() as c:
            c.execute(
                "INSERT INTO forecast_hosts (model, current, main_failing_since, switched_at,"
                " updated_at) VALUES (?,?,?,?,?) ON CONFLICT (model) DO UPDATE SET"
                " current=excluded.current, main_failing_since=excluded.main_failing_since,"
                " switched_at=excluded.switched_at, updated_at=excluded.updated_at",
                (
                    model,
                    state.current,
                    None if since is None else _iso(since),
                    None if switched is None else _iso(switched),
                    _iso(at),
                ),
            )

    def transition(
        self,
        run_id: int,
        from_states: Iterable[str],
        to_state: str,
        at: dt.datetime,
        increment_attempts: bool = False,
        **fields: Any,
    ) -> None:
        """Compare-and-set state change; ``fields`` are other columns to set."""
        if to_state not in RUN_STATES:
            raise ValueError(to_state)
        from_states = tuple(from_states)
        if "steps_verified" in fields and fields["steps_verified"] is not None:
            fields["steps_verified"] = json.dumps(
                {str(k): v for k, v in sorted(fields["steps_verified"].items())}
            )
        sets = "".join(f", {k}=?" for k in fields)
        if increment_attempts:
            sets += ", attempts = attempts + 1"
        with self.manifest.tx() as c:
            cur = c.execute(
                f"UPDATE forecast_runs SET state=?, updated_at=?{sets} WHERE id=?"
                f" AND state IN ({','.join('?' * len(from_states))})",
                (to_state, _iso(at), *fields.values(), run_id, *from_states),
            )
            if cur.rowcount != 1:
                row = c.execute("SELECT state FROM forecast_runs WHERE id=?", (run_id,)).fetchone()
                raise StateError(
                    f"forecast run {run_id}: expected {from_states}, found {row and row[0]}"
                )

    def add_file(self, run_id: int, f: FetchedFile, at: dt.datetime) -> int:
        with self.manifest.tx() as c:
            cur = c.execute(
                "INSERT INTO forecast_files (run_id, url, host, path, bytes, seconds, sha256,"
                " fetched_at) VALUES (?,?,?,?,?,?,?,?)",
                (run_id, f.url, f.host, str(f.path), f.bytes, f.seconds, f.sha256, _iso(at)),
            )
            return int(cur.lastrowid)

    def files(self, run_id: int) -> list[sqlite3.Row]:
        return self.manifest.conn.execute(
            "SELECT * FROM forecast_files WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()

    def raw_files(self, run_id: int) -> list[FetchedFile]:
        """The run's recorded files whose raw copy has not been deleted."""
        return [
            FetchedFile(r["url"], r["host"], Path(r["path"]), r["bytes"], r["seconds"], r["sha256"])
            for r in self.files(run_id)
            if r["raw_deleted_at"] is None
        ]

    def mark_files_verified(self, run_id: int) -> None:
        with self.manifest.tx() as c:
            c.execute("UPDATE forecast_files SET verified=1 WHERE run_id=?", (run_id,))

    def mark_raw_deleted(self, run_id: int, at: dt.datetime) -> None:
        with self.manifest.tx() as c:
            c.execute(
                "UPDATE forecast_files SET raw_deleted_at=? WHERE run_id=?"
                " AND raw_deleted_at IS NULL",
                (_iso(at), run_id),
            )
