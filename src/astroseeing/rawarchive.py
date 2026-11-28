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
5. check the request's Zarr store against the GRIB (D12, Riley 2026-11-28); a store
   that fails keeps the /staging copy;
6. only then delete the /staging copy, and record that in one transaction (the file
   row, the archive row, and ``ingested`` → ``raw_deleted``).

A destination that already holds the same bytes is a no-op (recorded as ``present``);
one with other bytes is refused and left as it is. No content under the archive root is
ever overwritten or deleted. The one name ever removed there is a temp name, right
after the same file has been hard-linked to its final name. Temp files left by a run
that died or hung, or by a copy that failed its checksum, are reported, never deleted.

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
import mmap
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
#: The copy is flushed to the NAS every this many bytes (see ``write_copy``).
SYNC_EVERY_BYTES = 256 << 20
#: Block size for reads that bypass the client cache (O_DIRECT needs aligned buffers).
DIRECT_BLOCK = 1 << 20


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
        """SHA-256 of a file on the archive, read past the client's cache where the
        filesystem allows (``O_DIRECT``, which the Linux NFS client supports), so the
        check reads what the NAS holds; otherwise an ordinary read."""
        try:
            return _sha256_direct(path, beat)
        except OSError as e:
            if e.errno != errno.EINVAL:
                raise
            log.debug("O_DIRECT not supported for %s; ordinary read", path)
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
        since_sync = 0
        with open(src, "rb") as fi, open(tmp, "xb") as fo:
            while chunk := fi.read(self.chunk_bytes):
                fo.write(chunk)
                since_sync += len(chunk)
                if since_sync >= SYNC_EVERY_BYTES:  # keeps the final fsync, which shows
                    fo.flush()  # no progress to the watchdog, short on a large file
                    os.fdatasync(fo.fileno())
                    since_sync = 0
                beat(len(chunk))
            fo.flush()
            os.fsync(fo.fileno())
            if hasattr(os, "posix_fadvise"):
                os.posix_fadvise(fo.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)

    def link_new(self, tmp: Path, final: Path) -> None:
        """Give ``tmp`` the name ``final``, failing if ``final`` exists; fsync the dir.

        A hard link never replaces an existing name, even against a thread of an earlier
        run still hanging on the NAS. There is no rename fallback (a rename replaces):
        where the filesystem has no hard links, :class:`NoHardLinks` stops the run."""
        try:
            os.link(tmp, final)
        except OSError as e:
            if e.errno in (errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EMLINK):
                raise NoHardLinks(f"no hard links at {final.parent} ({e})") from e
            raise
        os.unlink(tmp)  # the temp name only; the content now has its final name
        _fsync_dir(final.parent)


def _sha256_direct(path: Path, beat: Beat) -> str:
    """Read with ``O_DIRECT`` into a page-aligned buffer (EINVAL where unsupported)."""
    flag = getattr(os, "O_DIRECT", None)
    if flag is None:
        raise OSError(errno.EINVAL, "no O_DIRECT on this platform")
    h = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | flag)
    try:
        with mmap.mmap(-1, DIRECT_BLOCK) as buf:
            view = memoryview(buf)
            try:
                while n := os.readv(fd, [buf]):
                    h.update(view[:n])
                    beat(n)
            finally:
                view.release()
    finally:
        os.close(fd)
    return h.hexdigest()


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# -- the watchdog ---------------------------------------------------------------------
#: Archive calls given up on that may still be running, process-wide (D80 item 5).
_HUNG: list[tuple[str, threading.Thread]] = []


class Watchdog:
    """Runs each archive call in a daemon thread and gives up on it if it shows no
    progress for ``stall_s`` or passes its deadline. After one call has hung, every
    later call fails at once: the run stops (a hung NAS costs one timeout). The memory
    of a hang outlives the Watchdog, so no call in this process starts beside a thread
    that is still hanging (cleared once that thread ends)."""

    def __init__(self, stall_s: float, poll_s: float = 0.5):
        self.stall_s = stall_s
        self.poll_s = poll_s
        self.hung: str | None = None

    def call(
        self, what: str, fn: Callable[[Beat], T], deadline_s: float, stall_s: float | None = None
    ) -> T:
        """Run ``fn(beat)``; ``stall_s`` overrides the stall limit for one call (a call
        that can't report progress passes its deadline here)."""
        stall = self.stall_s if stall_s is None else stall_s
        if self.hung is not None:
            raise StorageUnresponsive(f"{what}: not tried, an earlier call hung ({self.hung})")
        _HUNG[:] = [(w, t) for w, t in _HUNG if t.is_alive()]
        if _HUNG:
            raise StorageUnresponsive(f"{what}: not tried, an earlier call is still hanging "
                                      f"({_HUNG[0][0]})")  # fmt: skip
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
            if now - last[0] > stall:
                self.hung = f"{what}: no progress for {stall:g} s"
            elif now - start > deadline_s:
                self.hung = f"{what}: not finished within {deadline_s:.0f} s"
            if self.hung:
                _HUNG.append((what, thread))
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


@dataclass(frozen=True)
class LeftAlone:
    """A raw file the run never touches, and why."""

    key: str
    why: str
    path: Path
    size: int


@dataclass
class Plan:
    root: Path
    archive: list[Item] = field(default_factory=list)  # ingested: copy, then delete
    measured: list[Item] = field(default_factory=list)  # copy; delete only on request
    left_alone: list[LeftAlone] = field(default_factory=list)
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
    rows = m.current_files()
    known: set[Path] = set()
    seen: dict[Path, str] = {}
    for r in rows:
        path = Path(r["path"])
        known.add(path.resolve())
        if r["state"] not in ("ingested", "measured"):
            plan.left_alone.append(LeftAlone(r["key"], f"state {r['state']}", path, r["size"]))
            continue
        if not path.resolve().is_relative_to(staging_root):
            plan.left_alone.append(LeftAlone(r["key"], "outside /staging", path, r["size"]))
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

    ingested, measured = plan.archive, plan.measured
    biggest = max((i.size for i in ingested + measured), default=0)
    lines = [
        "Raw GRIB archive plan (D64). Dry run: nothing is copied, recorded or deleted.",
        f"Archive root: {plan.root}  (layout: era5/<kind>/<region>/<period>.grib)",
        "",
        f"1. Copy, verify, record, then delete the /staging copy (state ingested): "
        f"{len(ingested)} files, {gb(sum(i.size for i in ingested))}",
        *group(ingested),
        f"   of which already archived by an earlier run (only the /staging delete is "
        f"left): {sum(i.archived for i in ingested)}",
        "",
        f"2. Measurement-only (state measured): {len(measured)} files, "
        f"{gb(sum(i.size for i in measured))}. Copied and verified; the /staging copy is "
        + (
            "DELETED (--delete-measured)."
            if delete_measured
            else "KEPT (deleting it is Riley's call: --delete-measured)."
        ),
        *group(measured),
        "",
        f"3. Left alone (other states or outside /staging): {len(plan.left_alone)} files, "
        f"{gb(sum(x.size for x in plan.left_alone))}",
        *[f"    {x.key}: {x.why} ({x.path})" for x in plan.left_alone],
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
#: ``store_check(item, raw, read)``: problems with the request's Zarr store (empty: good).
#: ``raw`` is the /staging copy, or None once it is gone (a crash recovery); ``read(what,
#: fn)`` runs a store read under the watchdog.
StoreCheck = Callable[[Item, "Path | None", Callable[[str, Callable[[], Any]], Any]], list[str]]


class IngestStoreCheck:
    """D12's store check before a raw GRIB leaves /staging: the store must match the
    arrays rebuilt from the GRIB bit for bit (with the ingest's ``mask_fn``), or, once the
    /staging copy is gone, its recorded content hash (``ingest.pipeline.store_problems``)."""

    def __init__(self, m: Manifest, mask_fn=None):
        self.m = m
        self.mask_fn = mask_fn

    def __call__(self, item: Item, raw: Path | None, read) -> list[str]:
        from astroseeing.ingest.pipeline import store_problems

        return store_problems(self.m, item.request_id, item.file_id, raw, self.mask_fn, read)


class ArchiveConflict(RuntimeError):
    """The archive already holds other bytes under that name, or a copy failed its
    checksum: refused, nothing overwritten, the /staging copy kept."""


class NoHardLinks(RuntimeError):
    """The archive filesystem has no hard links, so no file can be put in place without
    risking a replace: the run stops (D64 item 7)."""


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
    store_check: StoreCheck,
    fs: LocalArchiveFS | None = None,
    delete_measured: bool = False,
    max_copy_gb: float | None = None,
) -> Summary:
    """Archive every kept raw GRIB in the plan (see the module docstring).

    ``store_check`` is required, so no caller can skip the store check by omission; the
    command passes :class:`IngestStoreCheck` with the ingest's mask function."""
    fs = fs or LocalArchiveFS()
    watchdog = Watchdog(settings.stall_s, settings.poll_s)
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
        if not watchdog.call(f"exists {parent}", lambda _b: fs.exists(parent),
                             settings.timeout_base_s):  # fmt: skip
            raise PlanRefused(f"{parent} does not exist: is the NAS mounted? Not creating it")
        free = watchdog.call("free space", lambda _b: fs.free_bytes(settings.root),
                        settings.timeout_base_s)  # fmt: skip
        if free < need + FREE_MARGIN_BYTES:
            raise PlanRefused(f"{free / GB:.2f} GB free at {settings.root}, "
                              f"{(need + FREE_MARGIN_BYTES) / GB:.2f} GB needed")  # fmt: skip
        for item in items:
            delete = item.state == "ingested" or delete_measured
            try:
                _archive_one(m, fs, watchdog, settings, item, delete, store_check, s)
            except ArchiveConflict as e:
                log.error("%s: refused: %s", item.key, e)
                m.archive_event(item.request_id, "archive_refused", str(e))
                s.refused += 1
                s.problems.append(f"{item.key}: {e}")
            except (StorageUnresponsive, NoHardLinks):
                raise
            except Exception as e:
                log.exception("%s: archive failed", item.key)
                s.failed += 1
                s.problems.append(f"{item.key}: {e}")
    except StorageUnresponsive as e:
        log.error("the NAS stopped answering: %s; stopping, nothing recorded for that file",
                  e)  # fmt: skip
        s.hung = str(e)
    except NoHardLinks as e:
        raise PlanRefused(f"{e}; nothing can be put in place without risking a replace. "
                          "Stopped; the temp copy is left and reported") from e  # fmt: skip
    return s


def _archive_one(
    m: Manifest,
    fs: LocalArchiveFS,
    watchdog: Watchdog,
    settings: ArchiveSettings,
    item: Item,
    delete: bool,
    store_check: StoreCheck,
    s: Summary,
) -> None:
    """One file: archive it (unless recorded already), then maybe delete /staging."""
    limit = settings.deadline_s(item.size)
    record = m.raw_archive(item.file_id)
    verified_now = False
    if record is None:
        if not item.staging.exists():
            raise FileNotFoundError(f"{item.staging} is gone and no archive copy is recorded")
        if item.staging.stat().st_size != item.size:
            raise ArchiveConflict(
                f"{item.staging} is {item.staging.stat().st_size} B, the manifest says "
                f"{item.size} B; not copied"
            )
        outcome = _publish(fs, watchdog, settings, item, limit, s)
        m.record_raw_archive(item.request_id, item.file_id, item.dest, item.size, item.sha256,
                             outcome)  # fmt: skip
        verified_now = True
    if not delete:
        s.measured_kept += 1
        log.info("%s: archived at %s; /staging copy kept (measurement)", item.key, item.dest)
        return
    if not verified_now:
        # Recorded by an earlier run: check the recorded archive copy again right before
        # the /staging copy goes (D12: check at deletion time).
        archived = Path(record["archive_path"])
        got = watchdog.call(f"check {archived}", lambda b: fs.sha256(archived, b), limit)
        if got != item.sha256:
            raise ArchiveConflict(
                f"archive copy {archived} no longer matches the manifest ({got} != "
                f"{item.sha256}); /staging copy kept"
            )
    staged = item.staging.exists()
    if item.state == "ingested":
        # D12: the store is checked right before its raw GRIB leaves /staging, against
        # the GRIB itself, or against its recorded hash once the /staging copy is gone.
        def read(what: str, fn: Callable[[], Any]) -> Any:
            return watchdog.call(what, lambda _b: fn(), limit, stall_s=limit)

        problems = store_check(item, item.staging if staged else None, read)
        if problems:
            raise ArchiveConflict(
                f"its Zarr store fails the check ({'; '.join(problems[:3])}); /staging copy "
                "kept, archive copy kept"
            )
    if staged:
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


def _publish(fs: LocalArchiveFS, watchdog: Watchdog, settings: ArchiveSettings, item: Item,
             limit: float, s: Summary) -> str:  # fmt: skip
    """Put the file at ``item.dest`` once; return ``copied`` or ``present``."""
    d = item.dest
    base = settings.timeout_base_s
    watchdog.call(f"mkdir {d.parent}", lambda _b: fs.makedirs(d.parent), base)
    names = watchdog.call(f"list {d.parent}", lambda _b: fs.listdir(d.parent), base)
    stale = [d.parent / n for n in names if n.startswith(f".{d.name}{TEMP_MARK}")]
    for t in stale:
        log.warning("%s: temp file %s left by an earlier run that died or hung; not deleted "
                    "(remove it by hand once no run is active)", item.key, t)  # fmt: skip
    s.stale_temps += stale
    if watchdog.call(f"exists {d}", lambda _b: fs.exists(d), base):
        got = watchdog.call(f"checksum {d}", lambda b: fs.sha256(d, b), limit)
        if got != item.sha256:
            raise ArchiveConflict(f"{d} already exists with other content ({got} != "
                                  f"{item.sha256}); left as it is")  # fmt: skip
        log.info("%s: identical copy already at %s", item.key, d)
        s.present += 1
        return "present"
    tmp = d.parent / f".{d.name}{TEMP_MARK}{os.getpid()}-{secrets.token_hex(4)}"
    watchdog.call(f"copy to {tmp}", lambda b: fs.write_copy(item.staging, tmp, b), limit)
    got = watchdog.call(f"read back {tmp}", lambda b: fs.sha256(tmp, b), limit)
    if got != item.sha256:
        s.stale_temps.append(tmp)
        raise ArchiveConflict(
            f"the copy's checksum {got} != the manifest's {item.sha256}; "
            f"temp copy {tmp} left (not deleted), /staging copy kept"
        )
    watchdog.call(f"link {d}", lambda _b: fs.link_new(tmp, d), base)
    s.copied += 1
    s.copied_bytes += item.size
    log.info("%s: copied to %s (%d B, checksum verified)", item.key, d, item.size)
    return "copied"
