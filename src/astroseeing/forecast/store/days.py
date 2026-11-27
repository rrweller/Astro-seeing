"""Per-place daily stores on ``/data`` (F1 spec Module 6; D45 item 5, D51 item 12;
ticket #59, D80).

Once every run a saved place's area expects on a UTC day is final, that day's stored
values move from the SSD (one JSON file per run, :class:`~astroseeing.forecast.store.
PlaceStore`) to one Zarr v3 store, ``<data>/forecast/places/<place>/<YYYY-MM-DD>.zarr``,
written once and never touched again:

- **Final** (:func:`day_status`): every run of each of the area's models at its
  ``runs_utc`` hours is ``processed``, ``abandoned``, ``failed``, ``partial`` with no
  step left to try, or was never seen and can no longer be (a newer run of the model
  has been seen, or the source's online window, less the abandon margin, has passed).
- **Written atomically** (:meth:`DayStores.put`): into a temp folder beside the store,
  read back and compared with the SSD documents, then renamed into place. A store that
  already exists is never written again: with the same content it is only recorded,
  with other content it is refused (:class:`DayStoreConflict`) and logged.
- **Lossless:** :meth:`DayStores.read` gives back each run's document exactly as the
  SSD held it, so ``PlaceStore.hours_for`` reads either the same way.
- **The NAS hangs rather than failing** (AGENTS.md): every call to ``/data`` goes
  through :class:`NasGuard`, which gives up after a timeout and leaves the call to
  finish (or not) on its own; the day is tried again next tick.

Layout of a store (all floats are float64, NaN where the document has null):

- root attributes: ``schema``, ``place``, ``day``, ``provenance`` (commit, config hash
  and software of the code that wrote the store, and the manifest run ids in it),
  ``runs_missing`` (each expected run with no stored values, and its state),
  ``credits`` (each model's credit line, and the Copernicus DEM credit for the place
  height) and ``content_sha256`` (of the run documents as canonical JSON);
- one group per model, with ``step_values`` (run × step × field: every number of every
  stored step, ``stored`` = 1 where the step is in the run) and ``run_values`` (run ×
  field: run id, run time, observer height, raise, model ground, place height, level
  count); its attributes name the fields, the steps, the codes of the cloud classes,
  the fog signals each run lacks, and the rest of each run's document (metadata,
  missing steps with reasons, QC counts, provenance).
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import logging
import math
import os
import shutil
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import numpy as np

from astroseeing.forecast.settings import ForecastSettings
from astroseeing.forecast.verify.records import ForecastRecords
from astroseeing.forecast.verify.rules import step_status, window_end_abandon_at
from astroseeing.paths import StorageUnresponsive
from astroseeing.provenance import canonical_json

if TYPE_CHECKING:
    from astroseeing.forecast.store import PlaceStore
    from astroseeing.forecast.tick import BuildInfo

log = logging.getLogger(__name__)

DAY_SCHEMA = "forecast-place-day/1"
#: Run states that are final for the day store (``partial`` only once out of tries).
FINAL_STATES = ("processed", "abandoned", "failed")
#: Outcomes recorded in ``forecast_place_days`` once a day is settled.
SETTLED = ("written", "exists")

#: A run document's numbers that are per run, not per step (dotted paths).
_RUN_FIELDS = (
    "run_id",
    "run_time",
    "meta.observer_height_m",
    "meta.raise_m",
    "meta.model_ground_m",
    "meta.place_height_m",
    "meta.level_count",
)
_TIME_FIELDS = ("run_time", "valid_time")
_STORED = "stored"
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)

T = TypeVar("T")


# -- the NAS guard --------------------------------------------------------------------
class NasGuard:
    """Calls to ``/data`` with a timeout (a hard NFS mount hangs instead of failing).

    Each call runs in a daemon thread; if it hasn't returned within ``timeout_s`` the
    guard raises :class:`StorageUnresponsive` and leaves the thread to finish on its
    own. While a call is still hanging, every later call fails at once, so one dead NAS
    costs one timeout, not one per day or per read.
    """

    def __init__(self, timeout_s: float):
        if not timeout_s > 0:
            raise ValueError(f"timeout_s must be positive, got {timeout_s!r}")
        self.timeout_s = timeout_s
        self._hanging: tuple[str, threading.Thread] | None = None

    def call(self, what: str, fn: Callable[[], T]) -> T:
        if self._hanging is not None:
            earlier, thread = self._hanging
            if thread.is_alive():
                raise StorageUnresponsive(f"{what}: not tried, the NAS has still not "
                                          f"answered an earlier call ({earlier})")  # fmt: skip
            self._hanging = None
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                box["value"] = fn()
            except BaseException as e:  # handed to the caller below
                box["error"] = e

        thread = threading.Thread(target=run, name=f"nas: {what}", daemon=True)
        thread.start()
        thread.join(self.timeout_s)
        if thread.is_alive():
            self._hanging = (what, thread)
            raise StorageUnresponsive(f"{what}: no answer from the NAS within "
                                      f"{self.timeout_s:g} s")  # fmt: skip
        if "error" in box:
            raise box["error"]
        return box["value"]


# -- one day's content ----------------------------------------------------------------
@dataclass(frozen=True)
class DayContent:
    """One saved place's stored runs of one UTC day, as the SSD held them."""

    place: str
    day: dt.date
    runs: tuple[dict, ...]  # run documents (``forecast-place-run/1``), by model and time
    provenance: Mapping[str, Any]
    runs_missing: tuple[dict, ...] = ()
    credits: Mapping[str, str] | None = None

    def run(self, model: str, run_time: str) -> dict | None:
        for doc in self.runs:
            if doc["model"] == model and doc["run_time"] == run_time:
                return doc
        return None

    @property
    def content_sha256(self) -> str:
        return content_sha256(self.runs)


def content_sha256(runs: Sequence[dict]) -> str:
    """SHA-256 of the run documents as canonical JSON, in model and run-time order."""
    ordered = sorted(runs, key=lambda d: (d["model"], d["run_time"]))
    return hashlib.sha256(canonical_json(ordered).encode()).hexdigest()


class DayStoreConflict(RuntimeError):
    """A store for this place and day already exists with other content: never replaced."""


@dataclass(frozen=True)
class PutResult:
    outcome: str  # "written" (new store) or "exists" (the same content was already there)
    path: Path
    bytes: int
    content_sha256: str


class DayStores:
    """The per-place daily Zarr stores under ``root`` (``<data>/forecast/places``).

    Plain file I/O: callers wrap each call in a :class:`NasGuard`."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def path_for(self, place: str, day: dt.date) -> Path:
        return self.root / place / f"{day.isoformat()}.zarr"

    def read(self, place: str, day: dt.date) -> DayContent | None:
        """The day's content, or None if there is no store for it."""
        path = self.path_for(place, day)
        if not path.exists():
            return None
        return _read_store(path)

    def put(self, content: DayContent) -> PutResult:
        """Write the day's store once: temp folder → read back and compare → rename.
        An existing store is never written again: the same content gives ``exists``,
        other content raises :class:`DayStoreConflict`."""
        path = self.path_for(content.place, content.day)
        digest = content.content_sha256
        if path.exists():
            have = _read_store(path)
            if _same_runs(have.runs, content.runs):
                return PutResult("exists", path, _tree_bytes(path), digest)
            raise DayStoreConflict(
                f"{path} already exists with other content (sha256 {have.content_sha256}, "
                f"the SSD holds {digest}); it is never replaced"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        left = sorted(p.name for p in path.parent.glob(f".{path.name}.*.tmp"))
        if left:  # from a write that hung and died: never content, never deleted here
            log.warning("%s: %d unfinished temp folder(s) from earlier writes beside it: %s",
                        path, len(left), ", ".join(left))  # fmt: skip
        tmp = Path(tempfile.mkdtemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"))
        try:
            store = tmp / "store"  # mkdtemp's folder is private (0700); the store isn't
            _write_store(store, content)
            back = _read_store(store)
            if not _same_runs(back.runs, content.runs) or back.provenance != dict(
                content.provenance
            ):
                raise RuntimeError(f"{store} does not read back as written")
            _fsync_tree(store)
            os.rename(store, path)  # fails if the path appeared meanwhile: never replaced
            _fsync_dir(path.parent)
        finally:
            # our own temp folder, never renamed into place (empty after a good rename)
            shutil.rmtree(tmp, ignore_errors=True)
        return PutResult("written", path, _tree_bytes(path), digest)


def _same_runs(a: Sequence[dict], b: Sequence[dict]) -> bool:
    key = lambda d: (d["model"], d["run_time"])  # noqa: E731
    return sorted(a, key=key) == sorted(b, key=key)


def _tree_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_tree(root: Path) -> None:
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            fd = os.open(os.path.join(dirpath, f), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        _fsync_dir(Path(dirpath))


# -- encoding -------------------------------------------------------------------------
def _flatten(d: Mapping, prefix: str = "") -> dict[str, Any]:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, Mapping):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _put(d: dict, dotted: str, value: Any) -> None:
    *head, last = dotted.split(".")
    for k in head:
        d = d.setdefault(k, {})
    d[last] = value


def _pop(d: dict, dotted: str) -> Any:
    *head, last = dotted.split(".")
    for k in head:
        d = d[k]
    return d.pop(last)


def _seconds(text: str) -> float:
    t = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return (t - _EPOCH).total_seconds()


def _time_text(seconds: float) -> str:
    return (_EPOCH + dt.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kind(key: str, values: list[Any]) -> str:
    """How a field is held as a float64: ``time``, ``code`` (text values), ``fog``
    (a number or ``"absent"``), ``int`` or ``float`` (null → NaN)."""
    if key.split(".")[-1] in _TIME_FIELDS:
        return "time"
    if key.startswith("fog."):
        return "fog"
    present = [v for v in values if v is not None]
    if present and all(isinstance(v, str) for v in present):
        return "code"
    if present and all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        return "int"
    if all(isinstance(v, float) for v in present):
        return "float"
    raise ValueError(f"field {key!r} has values a day store cannot hold: {present[:3]!r}")


def _encode(value: Any, kind: str, codes: list[str] | None) -> float:
    if kind == "time":
        return _seconds(value)
    if kind == "code":
        return float(codes.index(value))
    if value is None or value == "absent":
        return math.nan
    return float(value)


def _decode(x: float, kind: str, codes: list[str] | None, absent: bool) -> Any:
    if kind == "time":
        return _time_text(x)
    if kind == "code":
        return codes[int(x)]
    if kind == "fog" and absent:
        return "absent"
    if math.isnan(x):
        return None
    return int(x) if kind == "int" else float(x)


def _model_arrays(docs: Sequence[dict]) -> tuple[np.ndarray, np.ndarray, dict]:
    """One model's runs as (step_values, run_values, attributes)."""
    steps = list(docs[0]["steps_expected"])
    if any(list(d["steps_expected"]) != steps for d in docs):
        raise ValueError(f"{docs[0]['model']}: the day's runs expect different steps")
    flat_steps = [[_flatten({k: v for k, v in s.items() if k != "step"}) for s in d["steps"]]
                  for d in docs]  # fmt: skip
    step_fields = sorted({k for runs in flat_steps for s in runs for k in s})
    if _STORED in step_fields:
        raise ValueError(f"a step field may not be called {_STORED!r}")
    values = {k: [s.get(k) for runs in flat_steps for s in runs] for k in step_fields}
    step_kinds = {k: _kind(k, values[k]) for k in step_fields}
    per_run = {k: [_flatten(d)[k] for d in docs] for k in _RUN_FIELDS}
    run_kinds = {k: _kind(k, per_run[k]) for k in _RUN_FIELDS}
    codes = {
        k: sorted({v for v in values[k] if v is not None})
        for k, kind in step_kinds.items()
        if kind == "code"
    }

    fields = [_STORED, *step_fields]
    step_values = np.full((len(docs), len(steps), len(fields)), np.nan)
    step_values[..., 0] = 0.0
    run_values = np.full((len(docs), len(_RUN_FIELDS)), np.nan)
    fog_absent, rest = [], []
    for r, (doc, runs) in enumerate(zip(docs, flat_steps, strict=True)):
        for step, flat in zip(doc["steps"], runs, strict=True):
            if step["step"] not in steps:
                raise ValueError(f"{doc['model']} {doc['run_time']}: step {step['step']} "
                                 "is not one it expects")  # fmt: skip
            k = steps.index(step["step"])
            step_values[r, k, 0] = 1.0
            for f, key in enumerate(step_fields, start=1):
                if key not in flat:
                    raise ValueError(f"{doc['model']} {doc['run_time']} step {step['step']}"
                                     f" lacks {key}")  # fmt: skip
                step_values[r, k, f] = _encode(flat[key], step_kinds[key], codes.get(key))
        fog_absent.append(sorted({k[4:] for s in runs for k, v in s.items()
                                  if k.startswith("fog.") and v == "absent"}))  # fmt: skip
        for f, key in enumerate(_RUN_FIELDS):
            run_values[r, f] = _encode(per_run[key][r], run_kinds[key], None)
        left = copy.deepcopy({k: v for k, v in doc.items() if k != "steps"})
        for key in _RUN_FIELDS:
            _pop(left, key)
        rest.append(left)
    attrs = {
        "steps": steps,
        "step_fields": fields,
        "step_kinds": step_kinds,
        "run_fields": list(_RUN_FIELDS),
        "run_kinds": run_kinds,
        "codes": codes,
        "fog_absent": fog_absent,
        "runs": rest,
    }
    return step_values, run_values, attrs


def _model_docs(step_values: np.ndarray, run_values: np.ndarray, attrs: Mapping) -> list[dict]:
    """The inverse of :func:`_model_arrays`."""
    steps, fields = attrs["steps"], attrs["step_fields"]
    kinds, codes = attrs["step_kinds"], attrs["codes"]
    docs = []
    for r, left in enumerate(attrs["runs"]):
        doc = copy.deepcopy(dict(left))
        for f, key in enumerate(attrs["run_fields"]):
            _put(doc, key, _decode(run_values[r, f], attrs["run_kinds"][key], None, False))
        absent = set(attrs["fog_absent"][r])
        doc["steps"] = []
        for k, step in enumerate(steps):
            if step_values[r, k, 0] != 1.0:
                continue
            s: dict[str, Any] = {"step": step}
            for f, key in enumerate(fields[1:], start=1):
                is_absent = key.startswith("fog.") and key[4:] in absent
                _put(s, key, _decode(step_values[r, k, f], kinds[key], codes.get(key), is_absent))
            doc["steps"].append(s)
        docs.append(doc)
    return docs


def _write_store(path: Path, content: DayContent) -> None:
    import zarr
    from zarr.codecs import BloscCodec

    comp = [BloscCodec(cname="zstd", clevel=5, shuffle="shuffle")]
    root = zarr.open_group(str(path), mode="w-", zarr_format=3)
    by_model: dict[str, list[dict]] = {}
    for doc in sorted(content.runs, key=lambda d: (d["model"], d["run_time"])):
        by_model.setdefault(doc["model"], []).append(doc)
    for model, docs in by_model.items():
        step_values, run_values, attrs = _model_arrays(docs)
        g = root.create_group(model, attributes=attrs)
        for name, arr, dims in (
            ("step_values", step_values, ("run", "step", "field")),
            ("run_values", run_values, ("run", "field")),
        ):
            a = g.create_array(name, shape=arr.shape, dtype=arr.dtype, chunks=arr.shape,
                               compressors=comp, fill_value=np.nan,
                               dimension_names=dims)  # fmt: skip
            a[...] = arr
    root.attrs.update(
        {
            "schema": DAY_SCHEMA,
            "place": content.place,
            "day": content.day.isoformat(),
            "provenance": dict(content.provenance),
            "runs_missing": list(content.runs_missing),
            "credits": dict(content.credits or {}),
            "content_sha256": content.content_sha256,
        }
    )


def _read_store(path: Path) -> DayContent:
    import zarr

    root = zarr.open_group(str(path), mode="r", zarr_format=3)
    attrs = dict(root.attrs)
    if attrs.get("schema") != DAY_SCHEMA:
        raise ValueError(f"{path}: not a {DAY_SCHEMA} store")
    runs = []
    for _name, g in sorted(root.groups()):
        runs += _model_docs(g["step_values"][...], g["run_values"][...], g.attrs)
    content = DayContent(
        place=attrs["place"],
        day=dt.date.fromisoformat(attrs["day"]),
        runs=tuple(runs),
        provenance=attrs["provenance"],
        runs_missing=tuple(attrs["runs_missing"]),
        credits=attrs["credits"],
    )
    if content.content_sha256 != attrs["content_sha256"]:
        raise ValueError(f"{path}: content does not match its content_sha256")
    return content


# -- finalising -----------------------------------------------------------------------
@dataclass(frozen=True)
class DayStatus:
    final: bool
    waiting: tuple[str, ...]  # runs not final yet, with their state
    runs_missing: tuple[dict, ...]  # expected runs that stored nothing, and why


def day_status(
    settings: ForecastSettings, records: ForecastRecords, place_id: str, day: dt.date,
    now: dt.datetime,
) -> DayStatus:  # fmt: skip
    """Whether every run the place's area expects on ``day`` is final (D80)."""
    area = settings.areas[settings.places[place_id].area]
    start = dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC)
    rules = settings.run_rules
    waiting, missing = [], []
    for model_id in area.models:
        model = settings.models[model_id]
        newest = records.newest(model_id, area.id)
        for hour in model.runs_utc:
            run_time = start + dt.timedelta(hours=hour)
            label = f"{model_id} {run_time:%Y-%m-%dT%HZ}"
            run = records.find(model_id, area.id, run_time)
            if run is None:
                gone_at = window_end_abandon_at(run_time, model, rules)
                if newest is not None and newest.run_time > run_time:
                    # the tick only ever fetches each model's newest published run
                    why = f"the newer run {newest.run_time:%Y-%m-%dT%HZ} was seen first"
                elif now >= gone_at:
                    why = f"not seen before its online window ended ({gone_at:%Y-%m-%dT%H:%MZ})"
                else:
                    waiting.append(f"{label}: not seen yet")
                    continue
                missing.append({"model": model_id, "run_time": _utc(run_time),
                                "state": "never seen", "why": why})  # fmt: skip
                continue
            final = run.state in FINAL_STATES or (
                run.state == "partial"
                and step_status(run.steps_expected, records.tries(run.id), rules).final
            )
            if not final:
                waiting.append(f"{label}: {run.state}")
            elif run.state == "failed" or run.derived_bytes is None:
                missing.append({"model": model_id, "run_time": _utc(run_time),
                                "state": run.state, "why": run.last_error})  # fmt: skip
    return DayStatus(not waiting, tuple(waiting), tuple(missing))


def _utc(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def finalise_days(
    now: dt.datetime,
    settings: ForecastSettings,
    records: ForecastRecords,
    store: PlaceStore,
    build: BuildInfo,
) -> list[dict]:
    """Write each saved place's final UTC days from the SSD to ``/data``, once
    (idempotent; safe to call every tick). ``build`` has the ``commit`` and
    ``software`` of this code. Returns one entry per day acted on: ``written``,
    ``exists`` (the same store was already there), ``refused`` (one with other content
    is), ``timed_out`` (the NAS did not answer: tried again next tick) or ``error``."""
    out: list[dict] = []
    if store.days is None:
        raise ValueError("finalise_days needs a PlaceStore with day stores")
    for place in settings.places.values():
        settled = records.place_days(place.id)
        for day in store.ssd_days(place.id):
            if day in settled:
                continue
            status = day_status(settings, records, place.id, day, now)
            if not status.final:
                log.debug("%s %s not final yet: %s", place.id, day, "; ".join(status.waiting))
                continue
            entry = _finalise_day(now, settings, records, store, build, place, day, status)
            out.append(entry)
            if entry["outcome"] == "timed_out":
                log.error("the NAS is not answering: the remaining days wait for the next tick")
                return out
        _purge_ssd(now, settings, records, store, place.id)
    return out


def _finalise_day(now, settings, records, store, build, place, day, status) -> dict:
    docs = store.day_docs(place.id, day)
    credits = {d["model"]: d["meta"]["credit"] for d in docs}
    if place.height is not None and place.height.attribution:
        credits["place_height"] = place.height.attribution
    content = DayContent(
        place=place.id,
        day=day,
        runs=tuple(docs),
        provenance={
            "commit": build.commit,
            "config_hash": settings.config_hash,
            "software": dict(build.software),
            "manifest_run_ids": sorted(d["run_id"] for d in docs),
        },
        runs_missing=status.runs_missing,
        credits=credits,
    )
    entry = {"place": place.id, "day": day.isoformat(), "runs": len(docs),
             "path": str(store.days.path_for(place.id, day))}  # fmt: skip
    what = f"day store {place.id} {day}"
    try:
        result = store.guard.call(what, lambda: store.days.put(content))
    except StorageUnresponsive as e:
        log.error("%s timed out, tried again next tick: %s", what, e)
        return {**entry, "outcome": "timed_out", "error": str(e)}
    except DayStoreConflict as e:
        log.error("%s refused: %s", what, e)
        records.record_place_day(place.id, day, "refused", entry["path"], None,
                                 content.content_sha256, str(e), at=now)  # fmt: skip
        return {**entry, "outcome": "refused", "error": str(e)}
    except Exception as e:  # logged; nothing recorded, so the next tick tries again
        log.error("%s failed, tried again next tick: %r", what, e)
        return {**entry, "outcome": "error", "error": repr(e)}
    records.record_place_day(place.id, day, result.outcome, str(result.path), result.bytes,
                             result.content_sha256, None, at=now)  # fmt: skip
    log.info("%s %s: %d runs, %d bytes", what, result.outcome, len(docs), result.bytes)
    return {**entry, "outcome": result.outcome, "bytes": result.bytes}


def _purge_ssd(now, settings, records, store, place_id: str) -> None:
    """Remove a settled day's SSD copy once it is more than ``ssd_keep_days`` old, oldest
    first, stopping at the first day that isn't settled (so every day on ``/data`` only
    is older than every day still on the SSD)."""
    keep = settings.place_stores.ssd_keep_days
    settled = records.place_days(place_id)
    for day in store.ssd_days(place_id):
        if (now.date() - day).days <= keep or settled.get(day) not in SETTLED:
            break
        n = store.remove_ssd_day(place_id, day)
        log.info("%s %s: SSD copy removed (%d files), kept on /data", place_id, day, n)


__all__ = [
    "DAY_SCHEMA",
    "DayContent",
    "DayStatus",
    "DayStoreConflict",
    "DayStores",
    "NasGuard",
    "PutResult",
    "content_sha256",
    "day_status",
    "finalise_days",
]
