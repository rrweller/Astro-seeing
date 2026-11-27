"""Kept raw GRIB from /staging to a write-once archive on the NAS (D55 item 7, D64).

``astro archive-raw`` copies the raw GRIB of ``ingested`` requests (the validation
downloads, kept on the SSD) to ``<archive root>/era5/<kind>/<region>/<period>.grib``,
then removes the /staging copy. Measurement-only files (state ``measured``, D50) are
copied too, but their /staging copy is removed only with ``delete_measured`` (Riley's
call). For each file, in this order (D12's ordering and crash recovery):

1. copy to a temp name beside the destination, fsync it, drop it from the page cache;
2. read the temp copy back and compare its SHA-256 with the manifest's checksum;
3. link it to its final name, which fails if that name exists (never overwrites);
4. record the archive copy in the manifest;
5. only then delete the /staging copy, and record that in one transaction (the file
   row, the archive row, and ``ingested`` → ``raw_deleted``).

A destination that already holds the same bytes is a no-op (recorded as ``present``);
one with other bytes is refused and left as it is. Nothing under the archive root is
ever overwritten or deleted, except this run's own temp file when its copy fails the
checksum (it never held archive content). Temp files left by a run that died or hung
are reported, never deleted.

Crash recovery: a run that died after step 3 is finished by the next run (the
destination is found identical and recorded). One that died between deleting the
/staging copy and recording it is finished by checking the archive copy against the
checksum again, then recording the deletion; if the check fails, nothing is recorded
and the problem is logged (the same rule as D12).

The NAS hangs rather than failing (AGENTS.md), so every call to the archive runs in a
daemon thread under :class:`Watchdog`: a call that shows no progress for ``stall_s``,
or runs past its per-file deadline (``timeout_base_s`` plus the size at
``min_rate_mb_s``), stops the whole run. Nothing is recorded for that file, so the next
run starts it again (resumable).
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import logging
import os
import secrets
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from astroseeing.config import load_config
from astroseeing.manifest import Manifest
from astroseeing.paths import StorageUnresponsive

log = logging.getLogger(__name__)

T = TypeVar("T")
Beat = Callable[[int], None]

GB = 1e9
MB = 1e6
#: Free space kept on the NAS beyond the bytes this run copies.
FREE_MARGIN_BYTES = int(1 * GB)
TEMP_MARK = ".tmp-"


# -- settings -------------------------------------------------------------------------
@dataclass(frozen=True)
class ArchiveSettings:
    """``configs/raw_archive.yaml``; the root is under ``$ASTRO_DATA_ROOT`` if relative."""

    root: Path
    timeout_base_s: float = 120.0
    min_rate_mb_s: float = 5.0
    stall_s: float = 120.0
    poll_s: float = 0.5
    max_copy_gb: float = 45.0

    @classmethod
    def from_config(cls, data_root: Path, cfg: dict[str, Any] | None = None) -> ArchiveSettings:
        cfg = dict(cfg if cfg is not None else load_config("raw_archive"))
        root = Path(cfg.pop("root"))
        return cls(root=root if root.is_absolute() else Path(data_root) / root, **cfg)

    def deadline_s(self, size: int) -> float:
        """Per-file time limit for one call on a file of ``size`` bytes."""
        return self.timeout_base_s + size / (self.min_rate_mb_s * MB)


# -- the archive filesystem (the seam the tests fake) ---------------------------------
class LocalArchiveFS:
    """Plain file operations on the archive. Every call is made under a Watchdog."""

    def __init__(self, chunk_bytes: int = 8 << 20):
        self.chunk_bytes = chunk_bytes

    def free_bytes(self, path: Path) -> int:
        p = Path(path)
        while not p.exists():
            p = p.parent
        st = os.statvfs(p)
        return st.f_bavail * st.f_frsize

    def exists(self, path: Path) -> bool:
        return os.path.lexists(path)

    def makedirs(self, path: Path) -> None:
        os.makedirs(path, exist_ok=True)

    def listdir(self, path: Path) -> list[str]:
        try:
            return sorted(os.listdir(path))
        except FileNotFoundError:
            return []

    def sha256(self, path: Path, beat: Beat) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(self.chunk_bytes):
                h.update(chunk)
                beat(len(chunk))
        return h.hexdigest()

    def write_copy(self, src: Path, tmp: Path, beat: Beat) -> None:
        """Copy ``src`` to the new file ``tmp`` (exclusive create), fsync it, and drop
        its pages from the cache so the read-back comes from the NAS, as far as the
        client allows."""
        with open(src, "rb") as fi, open(tmp, "xb") as fo:
            while chunk := fi.read(self.chunk_bytes):
                fo.write(chunk)
                beat(len(chunk))
            fo.flush()
            os.fsync(fo.fileno())
            if hasattr(os, "posix_fadvise"):
                os.posix_fadvise(fo.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)

    def link_new(self, tmp: Path, final: Path) -> None:
        """Give ``tmp`` the name ``final``, failing if ``final`` exists; fsync the dir.

        A hard link never replaces an existing name. Where the filesystem has no hard
        links, fall back to a rename after checking ``final`` is absent (one archive run
        at a time holds the lock, and nothing else writes in the archive)."""
        try:
            os.link(tmp, final)
        except OSError as e:
            if e.errno not in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EMLINK):
                raise
            log.warning("hard links not supported at %s (%s); using a checked rename", final, e)
            if os.path.lexists(final):
                raise FileExistsError(errno.EEXIST, "exists", str(final)) from e
            os.rename(tmp, final)
        else:
            os.unlink(tmp)  # the temp name only; the content now has its final name
        _fsync_dir(final.parent)

    def remove_own_temp(self, tmp: Path) -> None:
        os.unlink(tmp)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# -- the watchdog ---------------------------------------------------------------------
class Watchdog:
    """Runs each archive call in a daemon thread and gives up on it if it shows no
    progress for ``stall_s`` or passes its deadline. After one call has hung, every
    later call fails at once: the run stops (a hung NAS costs one timeout)."""

    def __init__(self, stall_s: float, poll_s: float = 0.5):
        self.stall_s = stall_s
        self.poll_s = poll_s
        self.hung: str | None = None

    def call(self, what: str, fn: Callable[[Beat], T], deadline_s: float) -> T:
        if self.hung is not None:
            raise StorageUnresponsive(f"{what}: not tried, an earlier call hung ({self.hung})")
        box: dict[str, Any] = {}
        last = [time.monotonic()]

        def beat(_n: int) -> None:
            last[0] = time.monotonic()

        def run() -> None:
            try:
                box["value"] = fn(beat)
            except BaseException as e:  # handed to the caller below
                box["error"] = e

        start = time.monotonic()
        thread = threading.Thread(target=run, name=f"archive: {what}", daemon=True)
        thread.start()
        while True:
            thread.join(self.poll_s)
            if not thread.is_alive():
                break
            now = time.monotonic()
            if now - last[0] > self.stall_s:
                self.hung = f"{what}: no progress for {self.stall_s:g} s"
                raise StorageUnresponsive(self.hung)
            if now - start > deadline_s:
                self.hung = f"{what}: not finished within {deadline_s:.0f} s"
                raise StorageUnresponsive(self.hung)
        if "error" in box:
            raise box["error"]
        return box["value"]


# -- the plan -------------------------------------------------------------------------
@dataclass(frozen=True)
class Item:
    request_id: int
    key: str
    state: str
    file_id: int
    staging: Path
    size: int
    sha256: str
    dest: Path
    archived: bool  # an archive copy is already recorded (an earlier run)


@dataclass
class Plan:
    root: Path
    archive: list[Item] = field(default_factory=list)  # ingested: copy, then delete
    measured: list[Item] = field(default_factory=list)  # copy; delete only on request
    left_alone: list[tuple[str, str, Path, int]] = field(default_factory=list)  # why
    unknown: list[tuple[Path, int]] = field(default_factory=list)  # not in the manifest

    def to_copy_bytes(self) -> int:
        return sum(i.size for i in self.archive + self.measured if not i.archived)


def dest_path(root: Path, kind: str, region: str, period: str) -> Path:
    for part in (kind, region, period):
        if not part or part in (".", "..") or "/" in part or "\0" in part:
            raise ValueError(f"unsafe path component {part!r}")
    return Path(root) / "era5" / kind / region / f"{period}.grib"


def plan_archive(m: Manifest, staging_root: Path, settings: ArchiveSettings) -> Plan:
    """What a run would do, from the manifest and /staging only (never touches the NAS)."""
    staging_root = Path(staging_root).resolve()
    plan = Plan(root=settings.root)
    rows = m.conn.execute(
        "SELECT r.id rid, r.key, r.kind, r.region, r.period, r.state, f.id fid, f.path,"
        " f.size, f.sha256 FROM files f JOIN requests r ON r.id = f.request_id"
        " WHERE f.deleted_at IS NULL"
        " AND f.id = (SELECT MAX(id) FROM files WHERE request_id = r.id) ORDER BY r.id"
    ).fetchall()
    known: set[Path] = set()
    seen: dict[Path, str] = {}
    for r in rows:
        path = Path(r["path"])
        known.add(path.resolve())
        if r["state"] not in ("ingested", "measured"):
            plan.left_alone.append((r["key"], f"state {r['state']}", path, r["size"]))
            continue
        if not path.resolve().is_relative_to(staging_root):
            plan.left_alone.append((r["key"], "outside /staging", path, r["size"]))
            continue
        dest = dest_path(settings.root, r["kind"], r["region"], r["period"])
        if dest in seen:
            raise ValueError(f"{r['key']} and {seen[dest]} would share {dest}")
        seen[dest] = r["key"]
        item = Item(
            request_id=r["rid"], key=r["key"], state=r["state"], file_id=r["fid"],
            staging=path, size=r["size"], sha256=r["sha256"], dest=dest,
            archived=m.raw_archive(r["fid"]) is not None,
        )  # fmt: skip
        (plan.archive if r["state"] == "ingested" else plan.measured).append(item)
    grib = staging_root / "grib"
    if grib.is_dir():
        for p in sorted(grib.iterdir()):
            if p.is_file() and p.resolve() not in known:
                plan.unknown.append((p, p.stat().st_size))
    return plan


def format_plan(plan: Plan, settings: ArchiveSettings, delete_measured: bool,
                files: bool = False) -> str:  # fmt: skip
    """The dry run's printout: sizes, destinations, limits."""

    def gb(n: int) -> str:
        return f"{n / GB:.2f} GB"

    def group(items: list[Item]) -> list[str]:
        by: dict[str, list[Item]] = defaultdict(list)
        for i in items:
            by["/".join(i.key.split("/")[:2])].append(i)
        out = [f"    {k:<32} {len(v):>4} files {gb(sum(i.size for i in v)):>11}"
               for k, v in sorted(by.items())]  # fmt: skip
        if files:
            out += [f"      {i.staging} -> {i.dest} ({i.size:,} B)"
                    + (" [archive copy already recorded]" if i.archived else "")
                    for i in items]  # fmt: skip
        return out

    a, me = plan.archive, plan.measured
    biggest = max((i.size for i in a + me), default=0)
    lines = [
        "Raw GRIB archive plan (D64). Dry run: nothing is copied, recorded or deleted.",
        f"Archive root: {plan.root}  (layout: era5/<kind>/<region>/<period>.grib)",
        "",
        f"1. Copy, verify, record, then delete the /staging copy (state ingested): "
        f"{len(a)} files, {gb(sum(i.size for i in a))}",
        *group(a),
        f"   of which already archived by an earlier run (only the /staging delete is "
        f"left): {sum(i.archived for i in a)}",
        "",
        f"2. Measurement-only (state measured): {len(me)} files, "
        f"{gb(sum(i.size for i in me))}. Copied and verified; the /staging copy is "
        + (
            "DELETED (--delete-measured)."
            if delete_measured
            else "KEPT (deleting it is Riley's call: --delete-measured)."
        ),
        *group(me),
        "",
        f"3. Left alone (other states or outside /staging): {len(plan.left_alone)} files, "
        f"{gb(sum(s for *_, s in plan.left_alone))}",
        *[f"    {k}: {why} ({p})" for k, why, p, _ in plan.left_alone],
        f"4. In /staging/grib but not in the manifest (left alone): {len(plan.unknown)} "
        f"files, {gb(sum(s for _, s in plan.unknown))}",
        *[f"    {p}" for p, _ in plan.unknown],
        "",
        f"To copy now: {gb(plan.to_copy_bytes())} (limit {settings.max_copy_gb:g} GB, "
        f"--max-gb to change). Largest file {gb(biggest)}: time limit per call "
        f"{settings.deadline_s(biggest):.0f} s, stall limit {settings.stall_s:g} s.",
    ]
    return "\n".join(lines)


# -- the run --------------------------------------------------------------------------
class ArchiveConflict(RuntimeError):
    """The archive already holds other bytes under that name, or a copy failed its
    checksum: refused, nothing overwritten, the /staging copy kept."""


class PlanRefused(RuntimeError):
    """The whole run is refused before anything is copied (size limit, free space)."""


@dataclass
class Summary:
    copied: int = 0  # new archive files written and verified
    present: int = 0  # identical file already in the archive (no-op)
    staging_deleted: int = 0
    recovered: int = 0  # /staging copy already gone; archive checked, deletion recorded
    measured_kept: int = 0  # archived, /staging copy kept (no --delete-measured)
    refused: int = 0
    failed: int = 0
    copied_bytes: int = 0
    hung: str | None = None
    stale_temps: list[Path] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.refused or self.failed or self.hung)


@contextmanager
def run_lock(state_dir: Path) -> Iterator[None]:
    """One archive run at a time (a lock file on the local state disk, not the NAS)."""
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    with open(Path(state_dir) / "archive-raw.lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise PlanRefused("another `astro archive-raw` is running") from e
        yield


def archive_raw(
    m: Manifest,
    staging_root: Path,
    settings: ArchiveSettings,
    *,
    fs: LocalArchiveFS | None = None,
    delete_measured: bool = False,
    max_copy_gb: float | None = None,
) -> Summary:
    """Archive every kept raw GRIB in the plan (see the module docstring)."""
    fs = fs or LocalArchiveFS()
    dog = Watchdog(settings.stall_s, settings.poll_s)
    plan = plan_archive(m, staging_root, settings)
    s = Summary()
    items = plan.archive + plan.measured
    if not items:
        return s
    limit = settings.max_copy_gb if max_copy_gb is None else max_copy_gb
    need = plan.to_copy_bytes()
    if need > limit * GB:
        raise PlanRefused(f"{need / GB:.2f} GB to copy is over the {limit:g} GB limit")
    try:
        parent = settings.root.parent
        if not dog.call(f"exists {parent}", lambda _b: fs.exists(parent), settings.timeout_base_s):
            raise PlanRefused(f"{parent} does not exist: is the NAS mounted? Not creating it")
        free = dog.call("free space", lambda _b: fs.free_bytes(settings.root),
                        settings.timeout_base_s)  # fmt: skip
        if free < need + FREE_MARGIN_BYTES:
            raise PlanRefused(f"{free / GB:.2f} GB free at {settings.root}, "
                              f"{(need + FREE_MARGIN_BYTES) / GB:.2f} GB needed")  # fmt: skip
        for item in items:
            delete = item.state == "ingested" or delete_measured
            try:
                _one(m, fs, dog, settings, item, delete, s)
            except ArchiveConflict as e:
                log.error("%s: refused: %s", item.key, e)
                m.archive_event(item.request_id, "archive_refused", str(e))
                s.refused += 1
                s.problems.append(f"{item.key}: {e}")
            except StorageUnresponsive:
                raise
            except Exception as e:
                log.exception("%s: archive failed", item.key)
                s.failed += 1
                s.problems.append(f"{item.key}: {e}")
    except StorageUnresponsive as e:
        log.error("the NAS stopped answering: %s; stopping, nothing recorded for that file",
                  e)  # fmt: skip
        s.hung = str(e)
    return s


def _one(m: Manifest, fs: LocalArchiveFS, dog: Watchdog, cfg: ArchiveSettings, item: Item,
         delete: bool, s: Summary) -> None:  # fmt: skip
    limit = cfg.deadline_s(item.size)
    rec = m.raw_archive(item.file_id)
    verified_now = False
    if rec is None:
        if not item.staging.exists():
            raise FileNotFoundError(f"{item.staging} is gone and no archive copy is recorded")
        if item.staging.stat().st_size != item.size:
            raise ArchiveConflict(
                f"{item.staging} is {item.staging.stat().st_size} B, the manifest says "
                f"{item.size} B; not copied"
            )
        outcome = _publish(fs, dog, cfg, item, limit, s)
        m.record_raw_archive(item.request_id, item.file_id, item.dest, item.size, item.sha256,
                             outcome)  # fmt: skip
        verified_now = True
    if not delete:
        s.measured_kept += 1
        log.info("%s: archived at %s; /staging copy kept (measurement)", item.key, item.dest)
        return
    if not verified_now:
        # Recorded by an earlier run: check the archive copy again right before the
        # /staging copy goes (D12: check at deletion time).
        got = dog.call(f"check {item.dest}", lambda b: fs.sha256(item.dest, b), limit)
        if got != item.sha256:
            raise ArchiveConflict(
                f"archive copy {item.dest} no longer matches the manifest ({got} != "
                f"{item.sha256}); /staging copy kept"
            )
    if item.staging.exists():
        item.staging.unlink()
        m.mark_staging_deleted_after_archive(
            item.request_id, item.file_id, f"archived at {item.dest}; {item.staging} deleted"
        )
        s.staging_deleted += 1
    else:
        m.mark_staging_deleted_after_archive(
            item.request_id, item.file_id,
            f"recovered: archived at {item.dest}; {item.staging} already gone",
        )  # fmt: skip
        s.recovered += 1


def _publish(fs: LocalArchiveFS, dog: Watchdog, cfg: ArchiveSettings, item: Item,
             limit: float, s: Summary) -> str:  # fmt: skip
    """Put the file at ``item.dest`` once; return ``copied`` or ``present``."""
    d = item.dest
    base = cfg.timeout_base_s
    dog.call(f"mkdir {d.parent}", lambda _b: fs.makedirs(d.parent), base)
    stale = [d.parent / n for n in dog.call(f"list {d.parent}", lambda _b: fs.listdir(d.parent),
                                            base)
             if n.startswith(f".{d.name}{TEMP_MARK}")]  # fmt: skip
    for t in stale:
        log.warning("%s: temp file %s left by an earlier run that died or hung; not deleted "
                    "(remove it by hand once no run is active)", item.key, t)  # fmt: skip
    s.stale_temps += stale
    if dog.call(f"exists {d}", lambda _b: fs.exists(d), base):
        got = dog.call(f"checksum {d}", lambda b: fs.sha256(d, b), limit)
        if got != item.sha256:
            raise ArchiveConflict(f"{d} already exists with other content ({got} != "
                                  f"{item.sha256}); left as it is")  # fmt: skip
        log.info("%s: identical copy already at %s", item.key, d)
        s.present += 1
        return "present"
    tmp = d.parent / f".{d.name}{TEMP_MARK}{os.getpid()}-{secrets.token_hex(4)}"
    dog.call(f"copy to {tmp}", lambda b: fs.write_copy(item.staging, tmp, b), limit)
    got = dog.call(f"read back {tmp}", lambda b: fs.sha256(tmp, b), limit)
    if got != item.sha256:
        dog.call(f"remove {tmp}", lambda _b: fs.remove_own_temp(tmp), base)
        raise ArchiveConflict(f"the copy's checksum {got} != the manifest's {item.sha256}; "
                              "temp copy removed, /staging copy kept")  # fmt: skip
    dog.call(f"link {d}", lambda _b: fs.link_new(tmp, d), base)
    s.copied += 1
    s.copied_bytes += item.size
    log.info("%s: copied to %s (%d B, checksum verified)", item.key, d, item.size)
    return "copied"
