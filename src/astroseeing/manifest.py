"""SQLite manifest: request → file → checksum → verification → ingest (AGENTS.md).

Lives on the local root disk (``~/.local/state/astro/manifest.sqlite``), never on
NFS; opening it on a network filesystem raises. A nightly export copies it to
``/data/astro/manifest-exports`` with the SQLite backup API (atomic rename).

States::

    planned → submitted → downloaded → verified → ingested → raw_deleted
         ↘        ↘            ↘            ↘ failed (with last_error; retry → planned)

Transitions are compare-and-set (``UPDATE … WHERE state IN (…)``) inside a
transaction, and every transition is appended to the ``events`` table.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astroseeing.paths import assert_local_filesystem

STATES = ("planned", "submitted", "downloaded", "verified", "ingested", "raw_deleted", "failed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id              INTEGER PRIMARY KEY,
    key             TEXT NOT NULL UNIQUE,
    dataset         TEXT NOT NULL,
    kind            TEXT NOT NULL,
    region          TEXT NOT NULL,
    period          TEXT NOT NULL,
    request_json    TEXT NOT NULL,
    request_hash    TEXT NOT NULL UNIQUE,
    expected_json   TEXT NOT NULL,
    state           TEXT NOT NULL,
    cds_request_id  TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    submitted_at    TEXT,
    cds_started_at  TEXT,
    cds_finished_at TEXT
);
CREATE INDEX IF NOT EXISTS requests_state ON requests(state);
CREATE TABLE IF NOT EXISTS files (
    id               INTEGER PRIMARY KEY,
    request_id       INTEGER NOT NULL REFERENCES requests(id),
    path             TEXT NOT NULL,
    size             INTEGER NOT NULL,
    sha256           TEXT NOT NULL,
    downloaded_at    TEXT NOT NULL,
    download_seconds REAL,
    deleted_at       TEXT
);
CREATE TABLE IF NOT EXISTS verifications (
    id          INTEGER PRIMARY KEY,
    file_id     INTEGER NOT NULL REFERENCES files(id),
    ok          INTEGER NOT NULL,
    report_json TEXT NOT NULL,
    verified_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingests (
    id              INTEGER PRIMARY KEY,
    file_id         INTEGER NOT NULL REFERENCES files(id),
    store_path      TEXT NOT NULL,
    content_sha256  TEXT,
    ok              INTEGER NOT NULL,
    report_json     TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    ingested_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY,
    request_id INTEGER REFERENCES requests(id),
    at         TEXT NOT NULL,
    event      TEXT NOT NULL,
    detail     TEXT
);
"""


def utcnow() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


class StateError(RuntimeError):
    """A transition was attempted from an unexpected state (lost a race or a bug)."""


@dataclass
class Request:
    id: int
    key: str
    dataset: str
    kind: str
    region: str
    period: str
    request: dict[str, Any]
    request_hash: str
    expected: dict[str, Any]
    state: str
    cds_request_id: str | None
    attempts: int
    last_error: str | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> Request:
        return cls(
            id=r["id"],
            key=r["key"],
            dataset=r["dataset"],
            kind=r["kind"],
            region=r["region"],
            period=r["period"],
            request=json.loads(r["request_json"]),
            request_hash=r["request_hash"],
            expected=json.loads(r["expected_json"]),
            state=r["state"],
            cds_request_id=r["cds_request_id"],
            attempts=r["attempts"],
            last_error=r["last_error"],
        )


class Manifest:
    def __init__(self, path: Path, allow_network_fs: bool = False):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not allow_network_fs:
            assert_local_filesystem(path.parent)
        self.path = path
        self.conn = sqlite3.connect(path, timeout=60, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=60000")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    # --- requests ---------------------------------------------------------------
    def add_request(self, spec) -> int:
        """Insert a request (from ``download.requests.RequestSpec``); idempotent.

        Re-adding the identical request returns the existing id. Re-using a key for
        a *different* request raises instead of silently replacing it.
        """
        req = spec.cds_request()
        h = spec.request_hash()
        now = utcnow()
        with self.tx() as c:
            row = c.execute(
                "SELECT id, request_hash FROM requests WHERE key=?", (spec.key,)
            ).fetchone()
            if row is not None:
                if row["request_hash"] != h:
                    raise ValueError(f"key {spec.key} already used by a different request")
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO requests (key, dataset, kind, region, period, request_json,"
                " request_hash, expected_json, state, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    spec.key,
                    spec.dataset,
                    spec.kind,
                    spec.region,
                    spec.period_label,
                    json.dumps(req, sort_keys=True),
                    h,
                    json.dumps(spec.expected(), sort_keys=True),
                    "planned",
                    now,
                    now,
                ),
            )
            rid = int(cur.lastrowid)
            c.execute(
                "INSERT INTO events (request_id, at, event) VALUES (?,?,?)", (rid, now, "planned")
            )
            return rid

    def get(self, request_id: int) -> Request:
        r = self.conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if r is None:
            raise KeyError(request_id)
        return Request.from_row(r)

    def by_state(self, *states: str, limit: int | None = None) -> list[Request]:
        q = f"SELECT * FROM requests WHERE state IN ({','.join('?' * len(states))}) ORDER BY id"
        if limit:
            q += f" LIMIT {int(limit)}"
        return [Request.from_row(r) for r in self.conn.execute(q, states)]

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT state, COUNT(*) n FROM requests GROUP BY state")
        return {r["state"]: r["n"] for r in rows}

    def transition(
        self,
        request_id: int,
        from_states: Iterable[str],
        to_state: str,
        detail: str | None = None,
        increment_attempts: bool = False,
        **fields: Any,
    ) -> None:
        with self.tx() as c:
            self._transition(
                c, request_id, from_states, to_state, detail, increment_attempts, fields
            )

    def _transition(
        self,
        c: sqlite3.Connection,
        request_id: int,
        from_states: Iterable[str],
        to_state: str,
        detail: str | None,
        increment_attempts: bool,
        fields: dict[str, Any],
    ) -> None:
        """Compare-and-set state change plus event row; caller holds the transaction."""
        if to_state not in STATES:
            raise ValueError(to_state)
        from_states = tuple(from_states)
        now = utcnow()
        sets = "".join(f", {k}=?" for k in fields)
        if increment_attempts:
            sets += ", attempts = attempts + 1"
        placeholders = ",".join("?" * len(from_states))
        sql = (
            f"UPDATE requests SET state=?, updated_at=?{sets}"
            f" WHERE id=? AND state IN ({placeholders})"
        )
        cur = c.execute(sql, (to_state, now, *fields.values(), request_id, *from_states))
        if cur.rowcount != 1:
            state = c.execute("SELECT state FROM requests WHERE id=?", (request_id,)).fetchone()
            raise StateError(
                f"request {request_id}: expected {from_states}, found {state and state[0]}"
            )
        c.execute(
            "INSERT INTO events (request_id, at, event, detail) VALUES (?,?,?,?)",
            (request_id, now, to_state, detail),
        )

    def fail(self, request_id: int, from_states: Iterable[str], error: str) -> None:
        self.transition(
            request_id,
            from_states,
            "failed",
            detail=error,
            increment_attempts=True,
            last_error=error,
        )

    def retry_failed(self, max_attempts: int = 5) -> int:
        """Move failed requests with attempts < max back to planned; returns how many."""
        n = 0
        for r in self.by_state("failed"):
            if r.attempts < max_attempts:
                self.transition(r.id, ["failed"], "planned", detail="retry", cds_request_id=None)
                n += 1
        return n

    # --- files, verification, ingest ---------------------------------------------
    def add_file(
        self, request_id: int, path: Path, size: int, sha256: str, seconds: float | None
    ) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO files (request_id, path, size, sha256, downloaded_at,"
                " download_seconds) VALUES (?,?,?,?,?,?)",
                (request_id, str(path), size, sha256, utcnow(), seconds),
            )
            return int(cur.lastrowid)

    def current_file(self, request_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM files WHERE request_id=? AND deleted_at IS NULL"
            " ORDER BY id DESC LIMIT 1",
            (request_id,),
        ).fetchone()

    def add_verification(self, file_id: int, ok: bool, report: dict[str, Any]) -> int:
        cur = self.conn.execute(
            "INSERT INTO verifications (file_id, ok, report_json, verified_at) VALUES (?,?,?,?)",
            (file_id, int(ok), json.dumps(report, sort_keys=True, default=str), utcnow()),
        )
        return int(cur.lastrowid)

    def add_ingest(
        self,
        file_id: int,
        store_path: Path,
        ok: bool,
        report: dict,
        provenance: dict,
        content_sha256: str | None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO ingests (file_id, store_path, content_sha256, ok, report_json,"
            " provenance_json, ingested_at) VALUES (?,?,?,?,?,?,?)",
            (
                file_id,
                str(store_path),
                content_sha256,
                int(ok),
                json.dumps(report, sort_keys=True, default=str),
                json.dumps(provenance, sort_keys=True, default=str),
                utcnow(),
            ),
        )
        return int(cur.lastrowid)

    def mark_raw_deleted(self, request_id: int, file_id: int, detail: str) -> None:
        """Record a deleted raw file and move ingested → raw_deleted in one transaction."""
        with self.tx() as c:
            c.execute(
                "UPDATE files SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                (utcnow(), file_id),
            )
            self._transition(c, request_id, ("ingested",), "raw_deleted", detail, False, {})

    def latest_file(self, request_id: int) -> sqlite3.Row | None:
        """Most recent file row for a request, deleted or not."""
        return self.conn.execute(
            "SELECT * FROM files WHERE request_id=? ORDER BY id DESC LIMIT 1", (request_id,)
        ).fetchone()

    # --- export ------------------------------------------------------------------
    def export(self, dest_dir: Path) -> Path:
        """Consistent copy via the SQLite backup API, written to a temp name then renamed.

        Never overwrites: each export gets a new timestamped name.
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        final = dest_dir / f"manifest-{stamp}.sqlite"
        if final.exists():
            raise FileExistsError(final)
        # Back up to the local state directory first so SQLite never takes locks on
        # the (possibly NFS) destination, then byte-copy, fsync and rename there.
        local = self.path.parent / f".export-{stamp}-{os.getpid()}.sqlite"
        dst = sqlite3.connect(local)
        try:
            self.conn.backup(dst)
        finally:
            dst.close()
        tmp = dest_dir / f".{final.name}.tmp-{os.getpid()}"
        try:
            shutil.copyfile(local, tmp)
            with open(tmp, "rb") as f:
                os.fsync(f.fileno())
            os.rename(tmp, final)
        finally:
            local.unlink(missing_ok=True)
        return final
