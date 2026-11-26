"""Working a run through the tick: steps fetched with retries, processing, abandoning
and raw-file deletion (F1 spec Modules 2 and 8; D51 items 5 and 7; tickets #51, #58).

A run is worked over as many ticks as it needs. Each tick asks the adapter, in one
``fetch``, for the steps the run rules say are ready (``verify.rules``: at most 5 tries
per step, at least 1 min apart), from the host ``tick.hosts`` picked; a host that
didn't answer the tick's first check isn't asked at all, so an outage costs no tries.
Every try of every step is recorded in ``forecast_step_tries``.

A tick that fetched new steps reads, verifies and stores the run from **all** its
fetched files, so a partial run counts for its verified steps at once and gains the
others as they arrive. Its raw files stay on ``/staging`` while a step still has tries
left, and go once the run is final (every step fetched or out of tries), always after
its stored values have been read back and checked (D51 item 5). A failed run keeps its
raw files (for the fix, D51 item 8) until it would have been abandoned; then they go.
Only files recorded in the manifest and inside the run's own raw folder are ever
deleted: nothing else under ``/staging`` is touched.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from astroseeing.forecast.column import column_products
from astroseeing.forecast.grid import nearest_point
from astroseeing.forecast.settings import Area, ForecastSettings, Model, Place
from astroseeing.forecast.sources.interface import (
    FetchedFile,
    FetchResult,
    FormatMismatch,
    RunFields,
    RunRef,
    SourceAdapter,
)
from astroseeing.forecast.store import PlaceStore, run_document, utc_text
from astroseeing.forecast.tick.hosts import HostPick
from astroseeing.forecast.verify import ForecastRecords, ForecastRun, verify_run
from astroseeing.forecast.verify.records import OPEN_STATES
from astroseeing.forecast.verify.rules import (
    StepStatus,
    abandon_reason,
    ready_steps,
    step_status,
)

log = logging.getLogger(__name__)

GB = 1e9  # bytes in the settings' gigabytes (alerts.staging_min_free_gb)


@dataclass(frozen=True)
class RunWork:
    """What working a model's runs needs (one per tick)."""

    now: dt.datetime
    settings: ForecastSettings
    adapters: Mapping[str, SourceAdapter]  # each model's (main-host) adapter, for read
    records: ForecastRecords
    store: PlaceStore
    raw_dir: Callable[[RunRef, str], Path]  # ForecastPaths.raw_dir
    staging: Path  # where free space is measured
    build: object  # tick.BuildInfo
    free_bytes: Callable[[Path], float]

    def work_model(
        self, model: Model, area: Area, places: list[Place], pick: HostPick
    ) -> list[dict]:
        """Record the newest published run, then work every open run of the model in
        the area, newest first; return one entry per run whose state changed."""
        rec = self.records
        if pick.newest is not None:
            have = rec.newest(model.id, area.id)
            if have is None or have.run_time < pick.newest.run_time:
                rec.seen(model.id, area.id, pick.newest.run_time, model.steps_h, at=self.now)
        out = []
        for run in rec.runs_in(model.id, area.id, OPEN_STATES):
            status = step_status(run.steps_expected, rec.tries(run.id), self.settings.run_rules)
            if run.state == "partial" and status.final:
                continue  # done: out of tries for its missing steps
            complete = rec.latest(model.id, area.id, states=("processed",))
            why = abandon_reason(
                run.run_time,
                model,
                self.settings.run_rules,
                self.now,
                None if complete is None else complete.run_time,
            )
            if why is not None:
                out.append(self._abandon(run, model, area, status, why))
                continue
            changed = self._work_run(run, model, area, places, pick)
            if changed is not None:
                out.append(changed)
        self._sweep_failed(model, area)
        return out

    # -- one run --------------------------------------------------------------------
    def _work_run(
        self, run: ForecastRun, model: Model, area: Area, places: list[Place], pick: HostPick
    ) -> dict | None:
        rec, rules = self.records, self.settings.run_rules
        ref = RunRef(model.id, run.run_time)
        dest = self.raw_dir(ref, area.id)
        steps = run.steps_expected
        new, tried = [], False
        ready = (
            [] if pick.adapter is None else ready_steps(steps, rec.tries(run.id), rules, self.now)
        )
        if ready and not self._enough_disk(ref):
            ready = []
        if ready:
            if run.state == "seen":
                rec.transition(run.id, ("seen",), "fetching", at=self.now, increment_attempts=True)
            else:
                rec.count_attempt(run.id, at=self.now)
        if ready:
            tried = True
            try:
                got = pick.adapter.fetch(ref, area, tuple(sorted(ready)), dest)
            except FormatMismatch as e:
                return self._fail(run.id, ref, area, places, str(e))
            except Exception as e:  # recorded and logged, never left half-done
                return self._fail(run.id, ref, area, places, f"fetch error: {e!r}")
            for f in got.files:  # a failed step's other files too: fetched again whole
                rec.add_file(run.id, f, at=self.now)
            for step in sorted(ready):
                why = got.missing_steps.get(step)
                rec.add_try(run.id, step, pick.host, self.now, why)
                if why is None:
                    new.append(step)
            if got.missing_steps:
                log.info(  # the adapter has logged each error itself
                    "%s %s %s: %d of %d steps tried on %s failed this tick",
                    model.id, area.id, ref.label, len(got.missing_steps), len(ready), pick.host,
                )  # fmt: skip

        status = step_status(steps, rec.tries(run.id), rules)
        run = rec.get(run.id)
        if new or run.state in ("fetched", "verified") or (tried and status.final):
            return self._process(run, ref, area, places, status, dest)
        if tried and run.state == "partial":  # a retry failed: keep the reasons current
            merged = {
                **(run.steps_verified or {}),
                **{s: f"not fetched: {why}" for s, why in status.reasons.items()},
            }
            rec.transition(run.id, ("partial",), "partial", at=self.now, steps_verified=merged)
        return None

    def _enough_disk(self, ref: RunRef) -> bool:
        free = self.free_bytes(self.staging)
        min_free = self.settings.alerts.staging_min_free_gb * GB
        if free < min_free:
            log.error(
                "skipping %s %s: /staging has %.1f GB free, needs %.0f GB",
                ref.model,
                ref.label,
                free / GB,
                min_free / GB,
            )
            return False
        return True

    def _process(
        self,
        run: ForecastRun,
        ref: RunRef,
        area: Area,
        places: list[Place],
        status: StepStatus,
        dest: Path,
    ) -> dict | None:
        rec, model = self.records, self.settings.models[ref.model]
        steps = run.steps_expected
        if not status.fetched:
            if not status.final:
                return None
            reasons = "; ".join(f"step {s}: {why}" for s, why in sorted(status.reasons.items()))
            return self._fail(run.id, ref, area, places, f"no step could be fetched: {reasons}")
        files = rec.raw_files(run.id)
        missing = {s: why for s, why in status.reasons.items()}
        fetched = FetchResult(ref, area.id, dest, tuple(files), tuple(steps), missing)
        rec.transition(
            run.id,
            ("seen", "fetching", "fetched", "verified", "partial"),
            "fetched",
            at=self.now,
            bytes=fetched.bytes,
            download_seconds=sum(f.seconds for f in files),
        )
        t1 = time.monotonic()
        try:
            fields = self.adapters[ref.model].read(fetched)
        except FormatMismatch as e:
            return self._fail(run.id, ref, area, places, str(e))
        except Exception as e:  # an unreadable file (eccodes error) fails the run loudly too
            return self._fail(run.id, ref, area, places, f"read error: {e!r}")
        report = verify_run(fields, model, steps, missing)
        if not report.ok:
            why = "; ".join(report.problems)
            return self._fail(run.id, ref, area, places, f"verify failed: {why}")
        if not report.verified_steps:
            if not status.final:  # nothing usable yet; later steps may still come
                rec.transition(
                    run.id, ("fetched",), "fetching", at=self.now, steps_verified=report.steps
                )
                return None
            return self._fail(run.id, ref, area, places, "verify failed: no step verified")
        rec.transition(run.id, ("fetched",), "verified", at=self.now, steps_verified=report.steps)
        rec.mark_files_verified(run.id)

        derived = 0
        for place in places:
            stored = self._store_place(place, fields, report, missing, run.id, ref)
            if stored is None:
                return self._fail(
                    run.id, ref, area, places, f"stored values for {place.id} did not read back"
                )
            derived += stored
        state = "processed" if len(report.verified_steps) == len(steps) else "partial"
        rec.transition(
            run.id,
            ("verified",),
            state,
            at=self.now,
            derived_bytes=derived,
            processing_seconds=time.monotonic() - t1,
        )
        if status.final:
            self._delete_raw(run.id, ref, area)
        log.info(
            "%s %s %s %s: %d of %d steps%s",
            ref.model,
            area.id,
            ref.label,
            state,
            len(report.verified_steps),
            len(steps),
            "" if status.final else f", {len(status.pending)} still to try",
        )
        return self._entry(ref, area, state, None)

    def _store_place(
        self, place: Place, fields: RunFields, report, missing, run_id: int, ref: RunRef
    ) -> int | None:
        """Compute and store one place's values; return the bytes written, or None if the
        file does not read back as written."""
        i, j = nearest_point(fields.lat, fields.lon, place.lat, place.lon)
        at = _at_point(fields, i, j)
        products = column_products(at, observer_height_m=place.height.metres)
        provenance = {
            "commit": self.build.commit,
            "config_hash": self.settings.config_hash,
            "manifest_run_id": run_id,
            "software": dict(self.build.software),
        }
        doc = run_document(
            place,
            at,
            (0, 0),
            products,
            report.verified_steps,
            missing,
            run_id,
            self.adapters[ref.model].credit,
            self.settings.cloud_classes,
            provenance,
        )
        stored = self.store.put_run(doc)
        if self.store.read_run(stored.path) != json.loads(json.dumps(doc)):
            return None
        return stored.bytes

    # -- endings --------------------------------------------------------------------
    def _fail(self, run_id: int, ref: RunRef, area: Area, places: list[Place], error: str):
        rec = self.records
        run = rec.get(run_id)
        rec.transition(run_id, (run.state,), "failed", at=self.now, last_error=error)
        if run.derived_bytes is not None:  # an earlier partial store must not stay shown
            for place in places:
                self.store.remove_run(place.id, ref.model, ref.run_time)
        log.error("%s %s %s failed: %s", ref.model, area.id, ref.label, error)
        return self._entry(ref, area, "failed", error)

    def _abandon(
        self, run: ForecastRun, model: Model, area: Area, status: StepStatus, why: str
    ) -> dict:
        ref = RunRef(model.id, run.run_time)
        steps = dict(run.steps_verified or {})
        for s in run.steps_expected:
            if steps.get(s) != "ok":
                before = status.reasons.get(s) or steps.get(s) or "not fetched"
                steps[s] = f"abandoned ({why}): {before}"
        self.records.transition(
            run.id,
            OPEN_STATES,
            "abandoned",
            at=self.now,
            steps_verified=steps,
            last_error=f"abandoned: {why}",
        )
        self._delete_raw(run.id, ref, area)
        n_ok = sum(v == "ok" for v in steps.values())
        log.info(
            "%s %s %s abandoned (%s); it keeps %d stored step(s)",
            model.id,
            area.id,
            ref.label,
            why,
            n_ok,
        )
        return self._entry(ref, area, "abandoned", f"abandoned: {why}")

    def _sweep_failed(self, model: Model, area: Area) -> None:
        """A failed run's raw files go once it would have been abandoned (D51 item 5)."""
        rec = self.records
        complete = rec.latest(model.id, area.id, states=("processed",))
        for run in rec.runs_in(model.id, area.id, ("failed",)):
            if not rec.raw_files(run.id):
                continue
            why = abandon_reason(
                run.run_time,
                model,
                self.settings.run_rules,
                self.now,
                None if complete is None else complete.run_time,
            )
            if why is not None:
                ref = RunRef(model.id, run.run_time)
                self._delete_raw(run.id, ref, area)
                log.info(
                    "%s %s %s (failed): raw files deleted, %s", model.id, area.id, ref.label, why
                )

    def _delete_raw(self, run_id: int, ref: RunRef, area: Area) -> None:
        _delete_files(self.records.raw_files(run_id), self.raw_dir(ref, area.id))
        self.records.mark_raw_deleted(run_id, at=self.now)

    @staticmethod
    def _entry(ref: RunRef, area: Area, state: str, error: str | None) -> dict:
        return {
            "model": ref.model,
            "area": area.id,
            "run_time": utc_text(ref.run_time),
            "state": state,
            "error": error,
        }


def _delete_files(files: tuple[FetchedFile, ...] | list[FetchedFile], dest: Path) -> None:
    """Delete raw files, only inside the run's own raw folder ``dest``; then remove the
    run's folders if empty. A path anywhere else is never touched (logged)."""
    root = Path(dest).resolve()
    for f in files:
        path = Path(f.path)
        if root not in path.resolve().parents:
            log.error("not deleting %s: outside the run's raw folder %s", path, root)
            continue
        path.unlink(missing_ok=True)
    for d in (dest, dest.parent, dest.parent.parent):
        try:
            d.rmdir()  # only if empty
        except OSError:
            break


def _at_point(f: RunFields, i: int, j: int) -> RunFields:
    """The run's fields at one grid point, as a 1 × 1 grid."""

    def cut(a):
        return None if a is None else a[:, i : i + 1, j : j + 1]

    return RunFields(
        run=f.run,
        model=f.model,
        lat=f.lat[i : i + 1, j : j + 1],
        lon=f.lon[i : i + 1, j : j + 1],
        valid_times=f.valid_times,
        pressure_hpa=f.pressure_hpa,
        geopotential_height_m=cut(f.geopotential_height_m),
        temperature_k=cut(f.temperature_k),
        u_ms=cut(f.u_ms),
        v_ms=cut(f.v_ms),
        level_cloud_pct=cut(f.level_cloud_pct),
        total_cloud_pct=cut(f.total_cloud_pct),
        low_cloud_pct=cut(f.low_cloud_pct),
        mid_cloud_pct=cut(f.mid_cloud_pct),
        high_cloud_pct=cut(f.high_cloud_pct),
        surface_pressure_hpa=cut(f.surface_pressure_hpa),
        model_ground_m=f.model_ground_m[i : i + 1, j : j + 1],
        fog={k: cut(v) for k, v in f.fog.items()},
        run_id=f.run_id,
        qc=f.qc,  # the cloud range rule's counts over the whole run, as read
    )
