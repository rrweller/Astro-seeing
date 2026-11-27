"""``astro archive-raw``: kept raw GRIB from /staging to a write-once archive (D55 item 7, D64).

Temp directories stand in for /staging and /data. A fake archive filesystem wraps the
real one and can hang, trickle or "crash" (raise :class:`Crash`, a BaseException that
nothing in the code catches, like a killed process) before or after any operation.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import threading
import time
from pathlib import Path

import pytest

from astroseeing.download.requests import Area, RequestSpec
from astroseeing.manifest import Manifest
from astroseeing.rawarchive import (
    ArchiveSettings,
    LocalArchiveFS,
    PlanRefused,
    archive_raw,
    format_plan,
    plan_archive,
    run_lock,
)

AREA = Area.around(-24.63, -70.40, half_width_cells=1)


class Crash(BaseException):
    """The process dies here (not an Exception, so no handler in the code sees it)."""


class FakeFS(LocalArchiveFS):
    """The real archive filesystem, with hooks run before (``before[op]``) or after
    (``after[op]``) an operation. A hook may block, sleep or raise."""

    def __init__(self, chunk_bytes: int = 1 << 20):
        super().__init__(chunk_bytes=chunk_bytes)
        self.before: dict[str, object] = {}
        self.after: dict[str, object] = {}
        self.calls: list[str] = []

    def _wrap(self, op, fn, *a):
        self.calls.append(op)
        if op in self.before:
            self.before[op](*a)
        out = fn(*a)
        if op in self.after:
            self.after[op](*a)
        return out

    def free_bytes(self, path):
        return self._wrap("free_bytes", super().free_bytes, path)

    def exists(self, path):
        return self._wrap("exists", super().exists, path)

    def makedirs(self, path):
        return self._wrap("makedirs", super().makedirs, path)

    def listdir(self, path):
        return self._wrap("listdir", super().listdir, path)

    def sha256(self, path, beat):
        return self._wrap("sha256", super().sha256, path, beat)

    def write_copy(self, src, tmp, beat):
        return self._wrap("write_copy", super().write_copy, src, tmp, beat)

    def link_new(self, tmp, final):
        return self._wrap("link_new", super().link_new, tmp, final)

    def remove_own_temp(self, tmp):
        return self._wrap("remove_own_temp", super().remove_own_temp, tmp)


def crash(*_a):
    raise Crash


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def tree(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` (relative path → bytes)."""
    if not root.exists():
        return {}
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def assert_only_grew(before: dict[str, bytes], after: dict[str, bytes]) -> None:
    """Nothing under /data was removed or changed (D64: the archive only grows)."""
    for k, v in before.items():
        assert after.get(k) == v, f"{k} was removed or changed under /data"


class World:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.m = Manifest(tmp / "state" / "manifest.sqlite")
        self.staging = tmp / "staging"
        self.grib = self.staging / "grib"
        self.grib.mkdir(parents=True)
        self.data = tmp / "data"
        self.data.mkdir()
        self.root = self.data / "raw-archive"
        self.settings = ArchiveSettings(
            root=self.root, timeout_base_s=5.0, min_rate_mb_s=1.0, stall_s=0.5, poll_s=0.01,
            max_copy_gb=1.0,
        )  # fmt: skip
        self.content: dict[int, bytes] = {}

    def add(self, kind: str, region: str, day: dt.date, state: str, size: int = 50_000,
            purpose: str = "store", path: Path | None = None) -> int:  # fmt: skip
        spec = RequestSpec(
            kind=kind, region=region, dates=(day,), area=AREA,
            variables=("temperature",) if kind == "pl" else ("2m_temperature",),
            levels=(500,) if kind == "pl" else None, hours=(0,), purpose=purpose,
        )  # fmt: skip
        rid = self.m.add_request(spec)
        data = os.urandom(size)
        p = path or self.grib / f"{spec.key.replace('/', '__')}.grib"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.m.add_file(rid, p, len(data), sha(data), 1.0)
        self.m.transition(rid, ["planned"], state)
        self.content[rid] = data
        return rid

    def staged(self, rid: int) -> Path:
        return Path(self.m.latest_file(rid)["path"])

    def archived(self, rid: int) -> Path:
        r = self.m.get(rid)
        return self.root / "era5" / r.kind / r.region / f"{r.period}.grib"

    def run(self, fs=None, **kw):
        return archive_raw(self.m, self.staging, self.settings, fs=fs or LocalArchiveFS(), **kw)


@pytest.fixture
def w(tmp_path):
    world = World(tmp_path)
    world.a = world.add("pl", "chile", dt.date(2021, 1, 1), "ingested")
    world.b = world.add("pl", "chile", dt.date(2021, 1, 2), "ingested", size=120_000)
    world.c = world.add("sl", "paranal", dt.date(2016, 4, 1), "ingested")
    world.meas = world.add("pl", "measure-global", dt.date(2023, 6, 21), "measured",
                           purpose="measure")  # fmt: skip
    yield world
    world.m.close()


def done(w: World, rid: int) -> None:
    """The file is in the archive, recorded, and gone from /staging; state raw_deleted."""
    assert w.archived(rid).read_bytes() == w.content[rid]
    assert not w.staged(rid).exists()
    assert w.m.get(rid).state == "raw_deleted"
    assert w.m.current_file(rid) is None  # the file row is marked deleted
    rec = w.m.raw_archive(w.m.latest_file(rid)["id"])
    assert rec["archive_path"] == str(w.archived(rid)) and rec["sha256"] == sha(w.content[rid])
    assert rec["staging_deleted_at"] is not None


# --- crash recovery (D12's ordering, applied to the archive) -------------------------
def test_a_crash_after_the_copy_lands_but_before_it_is_recorded_is_finished_next_run(w):
    fs = FakeFS()
    fs.after["link_new"] = crash  # the file is in the archive; the manifest doesn't know
    with pytest.raises(Crash):
        w.run(fs)
    first = w.archived(w.a)
    assert first.read_bytes() == w.content[w.a]
    assert w.staged(w.a).exists() and w.m.get(w.a).state == "ingested"
    assert w.m.raw_archive(w.m.latest_file(w.a)["id"]) is None

    s = w.run()
    assert s.present == 1 and s.copied == 3 and s.staging_deleted == 3
    for rid in (w.a, w.b, w.c):
        done(w, rid)
    assert w.m.raw_archive(w.m.latest_file(w.a)["id"])["outcome"] == "present"


def test_a_crash_after_the_staging_delete_but_before_it_is_recorded_is_recovered(w, monkeypatch):
    real = Manifest.mark_staging_deleted_after_archive
    calls = []

    def dies_once(self, *a, **kw):
        if not calls:
            calls.append(a)
            raise Crash  # the /staging copy is unlinked, the transaction never ran
        return real(self, *a, **kw)

    monkeypatch.setattr(Manifest, "mark_staging_deleted_after_archive", dies_once)
    with pytest.raises(Crash):
        w.run()
    assert not w.staged(w.a).exists()
    assert w.m.get(w.a).state == "ingested" and w.m.current_file(w.a) is not None

    s = w.run()
    assert s.recovered == 1 and s.staging_deleted == 2 and s.ok
    for rid in (w.a, w.b, w.c):
        done(w, rid)


def test_recovery_records_nothing_if_the_archive_copy_no_longer_matches(w, monkeypatch):
    real = Manifest.mark_staging_deleted_after_archive
    monkeypatch.setattr(Manifest, "mark_staging_deleted_after_archive", lambda *a, **k: crash())
    with pytest.raises(Crash):
        w.run()
    monkeypatch.setattr(Manifest, "mark_staging_deleted_after_archive", real)
    w.archived(w.a).write_bytes(b"damaged on the NAS")  # the only copy left is now wrong

    s = w.run()
    assert s.refused == 1 and s.recovered == 0 and not s.ok
    assert w.m.get(w.a).state == "ingested" and w.m.current_file(w.a) is not None
    assert w.archived(w.a).read_bytes() == b"damaged on the NAS"  # never overwritten
    assert any("no longer matches" in p for p in s.problems)


def test_a_crash_mid_copy_leaves_a_temp_file_that_is_reported_and_never_deleted(w):
    fs = FakeFS(chunk_bytes=10_000)

    def half_then_die(src, tmp, beat):
        Path(tmp).write_bytes(Path(src).read_bytes()[:20_000])
        raise Crash

    fs.write_copy = half_then_die
    with pytest.raises(Crash):
        w.run(fs)
    (temp,) = [p for p in w.archived(w.a).parent.iterdir() if p.name.startswith(".")]

    s = w.run()
    assert s.ok and s.copied == 4 and s.stale_temps == [temp]  # 3 + the measurement
    assert temp.exists() and len(temp.read_bytes()) == 20_000  # left for Riley
    for rid in (w.a, w.b, w.c):
        done(w, rid)


def test_an_interrupted_run_resumes_where_it_stopped_without_copying_twice(w):
    fs = FakeFS()
    n = []

    def die_on_second_copy(*_a):
        n.append(1)
        if len(n) == 2:
            raise Crash

    fs.before["write_copy"] = die_on_second_copy
    with pytest.raises(Crash):
        w.run(fs)
    done(w, w.a)
    s = w.run()
    assert (s.copied, s.present, s.staging_deleted) == (3, 0, 2)  # b, c, measurement
    for rid in (w.a, w.b, w.c):
        done(w, rid)
    assert w.run().copied == 0  # nothing left to do


def test_a_crash_while_recording_the_archive_copy_leaves_the_staging_copy(w, monkeypatch):
    monkeypatch.setattr(Manifest, "record_raw_archive", lambda *a, **k: crash())
    with pytest.raises(Crash):
        w.run()
    assert w.staged(w.a).exists() and w.m.get(w.a).state == "ingested"
    monkeypatch.undo()
    s = w.run()
    assert s.ok and s.present == 1  # the unrecorded copy is found identical
    done(w, w.a)


# --- a hung or slow NAS --------------------------------------------------------------
HANG_OPS = ["free_bytes", "makedirs", "listdir", "exists", "write_copy", "sha256", "link_new"]


@pytest.mark.parametrize("op", HANG_OPS)
def test_a_hung_nas_call_stops_the_run_and_records_and_deletes_nothing(w, op):
    release = threading.Event()
    fs = FakeFS()
    fs.before[op] = lambda *_a: release.wait(30)  # blocks, no progress: the NAS hangs
    before = tree(w.data)
    t0 = time.monotonic()
    try:
        s = w.run(fs)
    finally:
        elapsed = time.monotonic() - t0
        release.set()
    assert s.hung
    assert elapsed < 5  # stall_s is 1 s; the run gave up instead of hanging with the NAS
    assert s.staging_deleted == 0 and not s.ok
    for rid in (w.a, w.b, w.c, w.meas):
        assert w.staged(rid).exists() and w.m.get(rid).state in ("ingested", "measured")
        assert w.m.raw_archive(w.m.latest_file(rid)["id"]) is None
    assert fs.calls.count(op) == 1  # nothing else was tried after the hang
    time.sleep(0.2)  # let the released thread finish before reading the tree
    assert_only_grew(before, tree(w.data))


def test_after_a_hang_the_next_run_finishes_the_job(w):
    release = threading.Event()
    fs = FakeFS()
    fs.before["sha256"] = lambda *_a: release.wait(30)
    try:
        assert w.run(fs).hung
    finally:
        release.set()
    time.sleep(0.2)  # the hung thread finishes its read-back and returns to nobody
    s = w.run()
    assert s.ok and s.copied + s.present == 4
    for rid in (w.a, w.b, w.c):
        done(w, rid)


def test_a_slow_copy_that_keeps_making_progress_is_not_stopped(w):
    w.settings = ArchiveSettings(**{**w.settings.__dict__, "stall_s": 0.3})
    fs = FakeFS(chunk_bytes=10_000)
    real = LocalArchiveFS.write_copy

    def slow(src, tmp, beat):
        def slow_beat(n):
            time.sleep(0.05)  # each chunk is slow, but each one arrives
            beat(n)

        return real(fs, src, tmp, slow_beat)

    fs.write_copy = slow  # 120 kB file: 12 chunks, 0.6 s in all, > stall_s
    s = w.run(fs)
    assert s.ok and s.copied == 4


def test_a_copy_that_trickles_past_its_deadline_is_stopped(w):
    w.settings = ArchiveSettings(**{**w.settings.__dict__, "timeout_base_s": 0.3,
                                    "min_rate_mb_s": 1000.0})  # fmt: skip
    fs = FakeFS(chunk_bytes=1_000)
    real = LocalArchiveFS.write_copy

    def trickle(src, tmp, beat):
        def slow_beat(n):
            time.sleep(0.02)  # progress keeps coming, far too slowly: 50 chunks, 1 s
            beat(n)

        return real(fs, src, tmp, slow_beat)

    fs.write_copy = trickle
    s = w.run(fs)
    assert s.hung and "not finished within" in s.hung
    assert w.staged(w.a).exists() and w.m.raw_archive(w.m.latest_file(w.a)["id"]) is None
    time.sleep(1.2)


# --- what a run does ---------------------------------------------------------------
def test_a_run_archives_ingested_files_and_keeps_the_measurement_on_staging(w):
    s = w.run()
    assert (s.copied, s.staging_deleted, s.measured_kept) == (4, 3, 1) and s.ok
    assert s.copied_bytes == sum(len(w.content[r]) for r in (w.a, w.b, w.c, w.meas))
    for rid in (w.a, w.b, w.c):
        done(w, rid)
    # Layout: era5/<kind>/<region>/<period>.grib under the archive root.
    assert w.archived(w.a) == w.root / "era5" / "pl" / "chile" / "2021-01-01.grib"
    assert w.archived(w.c) == w.root / "era5" / "sl" / "paranal" / "2016-04-01.grib"
    meas = w.m.raw_archive(w.m.latest_file(w.meas)["id"])
    assert w.archived(w.meas).read_bytes() == w.content[w.meas]
    assert w.staged(w.meas).exists() and meas["staging_deleted_at"] is None
    assert w.m.get(w.meas).state == "measured" and w.m.current_file(w.meas) is not None
    assert not [p for p in w.root.rglob(".*")]  # no temp files left behind

    again = w.run()  # the measurement is recorded; nothing is copied twice
    assert (again.copied, again.present, again.measured_kept) == (0, 0, 1)


def test_the_measurement_staging_copy_goes_only_when_asked(w):
    w.run()
    s = w.run(delete_measured=True)
    assert s.staging_deleted == 1 and s.copied == 0 and s.ok
    assert not w.staged(w.meas).exists() and w.m.current_file(w.meas) is None
    assert w.m.get(w.meas).state == "measured"  # terminal state unchanged
    assert w.m.raw_archive(w.m.latest_file(w.meas)["id"])["staging_deleted_at"]


def test_an_identical_file_already_in_the_archive_is_a_no_op(w):
    d = w.archived(w.a)
    d.parent.mkdir(parents=True)
    d.write_bytes(w.content[w.a])
    os.utime(d, (1_000_000, 1_000_000))
    ino = d.stat().st_ino
    s = w.run()
    assert s.present == 1 and s.copied == 3 and s.ok
    assert d.stat().st_ino == ino and d.stat().st_mtime == 1_000_000  # untouched
    done(w, w.a)


def test_a_destination_with_other_content_is_refused_and_left_as_it_is(w):
    d = w.archived(w.a)
    d.parent.mkdir(parents=True)
    d.write_bytes(b"someone else's file")
    before = tree(w.data)
    s = w.run()
    assert s.refused == 1 and not s.ok and s.copied == 3
    assert d.read_bytes() == b"someone else's file"
    assert w.staged(w.a).exists() and w.m.get(w.a).state == "ingested"
    assert w.m.raw_archive(w.m.latest_file(w.a)["id"]) is None
    assert_only_grew(before, tree(w.data))
    for rid in (w.b, w.c):
        done(w, rid)
    events = [r["event"] for r in w.m.conn.execute(
        "SELECT event FROM events WHERE request_id=?", (w.a,))]  # fmt: skip
    assert "archive_refused" in events


def test_a_staging_file_that_no_longer_matches_its_checksum_is_refused(w):
    p = w.staged(w.a)
    p.write_bytes(bytes(len(w.content[w.a])))  # same size, other bytes: bit rot
    s = w.run()
    assert s.refused == 1 and not s.ok
    assert not w.archived(w.a).exists()
    assert not [x for x in w.archived(w.a).parent.iterdir() if x.name.startswith(".")]
    assert p.exists() and w.m.get(w.a).state == "ingested"


def test_a_staging_file_of_the_wrong_size_is_not_copied(w):
    w.staged(w.a).write_bytes(b"short")
    s = w.run()
    assert s.refused == 1 and not w.archived(w.a).exists() and w.staged(w.a).exists()


def test_a_missing_staging_file_with_no_archive_record_fails_without_recording(w):
    w.staged(w.a).unlink()
    s = w.run()
    assert s.failed == 1 and not s.ok and w.m.get(w.a).state == "ingested"
    assert w.m.current_file(w.a) is not None


def test_files_outside_staging_and_other_states_are_left_alone(w, tmp_path):
    out = w.add("pl", "chile", dt.date(2021, 2, 1), "ingested", path=tmp_path / "elsewhere.grib")
    ver = w.add("pl", "chile", dt.date(2021, 2, 2), "verified")
    s = w.run()
    assert s.ok
    for rid in (out, ver):
        assert w.staged(rid).exists() and not w.archived(rid).exists()
        assert w.m.raw_archive(w.m.latest_file(rid)["id"]) is None


# --- the plan and the limits ---------------------------------------------------------
def test_the_plan_lists_sizes_and_measurements_separately_and_touches_nothing(w, tmp_path):
    w.add("pl", "chile", dt.date(2021, 2, 2), "verified")
    (w.grib / "stray.grib.part").write_bytes(b"x" * 10)
    plan = plan_archive(w.m, w.staging, w.settings)
    assert [i.request_id for i in plan.archive] == [w.a, w.b, w.c]
    assert [i.request_id for i in plan.measured] == [w.meas]
    assert plan.to_copy_bytes() == sum(len(w.content[r]) for r in (w.a, w.b, w.c, w.meas))
    assert [why for _, why, *_ in plan.left_alone] == ["state verified"]
    assert [p.name for p, _ in plan.unknown] == ["stray.grib.part"]
    text = format_plan(plan, w.settings, delete_measured=False, files=True)
    assert "3 files, 0.00 GB" in text and "KEPT" in text and "stray.grib.part" in text
    assert str(w.archived(w.a)) in text
    assert not w.root.exists()  # the plan never touches the NAS


def test_a_run_over_the_size_limit_is_refused_before_anything_is_copied(w):
    w.settings = ArchiveSettings(**{**w.settings.__dict__, "max_copy_gb": 0.0001})
    with pytest.raises(PlanRefused, match="limit"):
        w.run()
    assert not w.root.exists()
    assert w.run(max_copy_gb=1).ok  # --max-gb raises it for one run


def test_a_run_without_room_on_the_nas_is_refused(w):
    fs = FakeFS()
    fs.free_bytes = lambda _p: 10
    with pytest.raises(PlanRefused, match="free"):
        w.run(fs)
    assert not w.root.exists()


def test_two_runs_at_once_are_refused(tmp_path):
    with run_lock(tmp_path), pytest.raises(PlanRefused, match="running"), run_lock(tmp_path):
        pass
    with run_lock(tmp_path):  # released
        pass


def test_an_unmounted_nas_is_never_mistaken_for_an_empty_directory(w):
    w.settings = ArchiveSettings(**{**w.settings.__dict__,
                                    "root": w.tmp / "not-mounted" / "raw-archive"})  # fmt: skip
    with pytest.raises(PlanRefused, match="does not exist"):
        w.run()
    assert not (w.tmp / "not-mounted").exists()
    assert all(w.staged(r).exists() for r in (w.a, w.b, w.c, w.meas))


def test_the_settings_come_from_config_under_the_data_root(tmp_path):
    s = ArchiveSettings.from_config(tmp_path, {"root": "raw-archive", "stall_s": 7})
    assert s.root == tmp_path / "raw-archive" and s.stall_s == 7
    assert ArchiveSettings.from_config(tmp_path, {"root": "/x/y"}).root == Path("/x/y")
    cfg = ArchiveSettings.from_config(Path("/data/astro"))  # configs/raw_archive.yaml
    assert cfg.root == Path("/data/astro/raw-archive")
    assert cfg.deadline_s(500_000_000) == cfg.timeout_base_s + 500 / cfg.min_rate_mb_s


# --- the command ---------------------------------------------------------------------
@pytest.fixture
def ct(w, monkeypatch):
    monkeypatch.setenv("ASTRO_DATA_ROOT", str(w.data))
    monkeypatch.setenv("ASTRO_STAGING", str(w.staging))
    monkeypatch.setenv("ASTRO_STATE_DIR", str(w.tmp / "state"))
    monkeypatch.setenv("ASTRO_LOG_DIR", str(w.tmp / "logs"))
    return w


def test_the_dry_run_prints_the_plan_and_changes_nothing(ct, capsys):
    from astroseeing import cli

    assert cli.main(["archive-raw", "--dry-run", "--files"]) == 0
    out = capsys.readouterr().out
    assert "Dry run" in out and "pl/chile" in out and "measure-global" in out
    assert str(ct.data / "raw-archive") in out
    assert not (ct.data / "raw-archive").exists()
    assert all(ct.staged(r).exists() for r in (ct.a, ct.b, ct.c, ct.meas))


def test_the_command_archives_and_exits_zero_then_nothing_is_left(ct, capsys):
    from astroseeing import cli

    assert cli.main(["archive-raw"]) == 0
    for rid in (ct.a, ct.b, ct.c):
        done(ct, rid)
    assert ct.staged(ct.meas).exists()
    assert cli.main(["archive-raw", "--delete-measured"]) == 0
    assert not ct.staged(ct.meas).exists()


def test_the_command_exits_non_zero_on_a_refusal_and_on_the_size_limit(ct):
    from astroseeing import cli

    d = ct.archived(ct.a)
    d.parent.mkdir(parents=True)
    d.write_bytes(b"other")
    assert cli.main(["archive-raw", "--max-gb", "0.00001"]) == 2  # over the limit
    assert cli.main(["archive-raw"]) == 1  # one refusal
    assert ct.staged(ct.a).exists()
