"""Per-place daily stores on the NAS (F1 spec Module 6; ticket #59; D51 item 12).

Once a UTC day's runs for a saved place are final, its values go from the SSD to one
Zarr v3 store under ``<data>/forecast/places/<place>/<YYYY-MM-DD>.zarr``, written once
(temp → verify → rename) and never touched again. ``/data`` is a temp folder here.
"""

from __future__ import annotations

import copy
import datetime as dt
import tempfile
import threading
import time

import pytest
from hypothesis import given
from hypothesis import settings as settings_
from hypothesis import strategies as st
from place_days_world import COMMIT, SOFTWARE, finish, store_day

from astroseeing.forecast.settings import load_settings
from astroseeing.forecast.store import PlaceStore
from astroseeing.forecast.store.days import DayContent, DayStores, NasGuard, finalise_days
from astroseeing.forecast.verify import ForecastRecords
from astroseeing.manifest import Manifest


class Build:
    commit = COMMIT
    software = SOFTWARE


DAY = dt.date(2026, 11, 25)
LATER = dt.datetime(2026, 11, 26, 12, tzinfo=dt.UTC)


@pytest.fixture
def settings():
    return load_settings()


@pytest.fixture
def ct(tmp_path):
    """A temp manifest, SSD and NAS."""
    manifest = Manifest(tmp_path / "state" / "manifest.sqlite")
    days = DayStores(tmp_path / "data" / "forecast" / "places")
    store = PlaceStore(tmp_path / "staging" / "places", days=days, guard=NasGuard(5))
    yield ForecastRecords(manifest), store, days
    manifest.close()


def test_a_store_appears_once_the_days_runs_are_final_and_holds_every_run(settings, ct):
    records, store, days = ct
    docs = store_day(settings, records, store, "kongsberg", DAY, except_runs=(("ifs", 18),))

    out = finalise_days(LATER, settings, records, store, Build())
    assert not days.path_for("kongsberg", DAY).exists()  # ifs 18z still fetching
    assert [d["outcome"] for d in out if d["place"] == "kongsberg"] == []

    ifs18 = records.find("ifs", "kongsberg", dt.datetime(2026, 11, 25, 18, tzinfo=dt.UTC))
    docs.update(_store_run(settings, records, store, ifs18))
    out = finalise_days(LATER, settings, records, store, Build())

    (entry,) = [d for d in out if d["place"] == "kongsberg"]
    assert entry["outcome"] == "written" and entry["day"] == "2026-11-25"
    content = days.read("kongsberg", DAY)
    assert len(content.runs) == 16
    assert {(r["model"], r["run_time"]) for r in content.runs} == {
        (m, t.strftime("%Y-%m-%dT%H:%M:%SZ")) for m, t in docs
    }
    for doc in docs.values():
        assert content.run(doc["model"], doc["run_time"]) == doc
    prov = content.provenance
    assert prov["commit"] == COMMIT and prov["software"] == SOFTWARE
    assert prov["config_hash"] == settings.config_hash
    assert sorted(prov["manifest_run_ids"]) == sorted(d["run_id"] for d in docs.values())


def _store_run(settings, records, store, run):
    from place_days_world import run_doc

    doc = run_doc(settings, "kongsberg", run.model, run.run_time, run.id)
    stored = store.put_run(doc)
    finish(records, run.id, "processed", LATER, stored.bytes)
    return {(run.model, run.run_time): store.read_run(stored.path)}


def tree(path) -> dict:
    """Every file under a store: (mtime_ns, bytes)."""
    return {
        str(p.relative_to(path)): (p.stat().st_mtime_ns, p.read_bytes())
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


def test_calling_again_changes_nothing(settings, ct):
    records, store, days = ct
    store_day(settings, records, store, "kongsberg", DAY)
    (first,) = finalise_days(LATER, settings, records, store, Build())
    path = days.path_for("kongsberg", DAY)
    before = tree(path)

    assert finalise_days(LATER, settings, records, store, Build()) == []
    assert finalise_days(LATER + dt.timedelta(hours=6), settings, records, store, Build()) == []
    assert tree(path) == before
    assert first["outcome"] == "written" and first["bytes"] > 0


def test_a_store_already_there_with_the_same_content_is_only_recorded(settings, ct, tmp_path):
    records, store, days = ct
    store_day(settings, records, store, "kongsberg", DAY)
    finalise_days(LATER, settings, records, store, Build())
    path = days.path_for("kongsberg", DAY)
    before = tree(path)

    # the manifest is lost (a new one with the same runs); the SSD and the store are not
    other = ForecastRecords(Manifest(tmp_path / "state2" / "manifest.sqlite"))
    store_day(settings, other, PlaceStore(tmp_path / "scratch"), "kongsberg", DAY)
    (entry,) = finalise_days(LATER, settings, other, store, Build())
    assert entry["outcome"] == "exists"
    assert tree(path) == before
    assert other.place_days("kongsberg") == {DAY: "exists"}
    other.manifest.close()


def test_a_store_with_other_content_is_refused_never_overwritten_and_logged(settings, ct, caplog):
    records, store, days = ct
    docs = store_day(settings, records, store, "kongsberg", DAY)
    path = days.path_for("kongsberg", DAY)
    gfs00 = docs[("gfs", dt.datetime(2026, 11, 25, tzinfo=dt.UTC))]
    other = {**gfs00, "steps": gfs00["steps"][:-1]}  # one step fewer than the SSD has
    days.put(DayContent("kongsberg", DAY, (other,), {"commit": "c" * 40}))
    before = tree(path)

    (entry,) = finalise_days(LATER, settings, records, store, Build())
    assert entry["outcome"] == "refused"
    assert "already exists with other content" in caplog.text
    assert tree(path) == before
    assert records.place_days("kongsberg") == {DAY: "refused"}
    assert finalise_days(LATER, settings, records, store, Build()) == []  # logged once
    assert tree(path) == before


def fail_runs(records, model, day, at):
    start = dt.datetime.combine(day, dt.time(), tzinfo=dt.UTC)
    for hour in (0, 6, 12, 18):
        run = records.find(model, "kongsberg", start + dt.timedelta(hours=hour))
        records.transition(run.id, (run.state,), "failed", at=at, last_error="verify failed")


def test_hours_for_gives_the_same_hours_before_and_after_the_days_are_finalised(settings, ct):
    """Tonight spans two UTC days; IFS's newest run is on the first, kept only on /data
    once the SSD copy goes, while the others' newest runs are on the SSD."""
    records, store, days = ct
    day2 = DAY + dt.timedelta(days=1)
    store_day(settings, records, store, "kongsberg", DAY)
    ifs = tuple(("ifs", h) for h in (0, 6, 12, 18))
    store_day(settings, records, store, "kongsberg", day2, except_runs=ifs)
    fail_runs(records, "ifs", day2, LATER)
    models = [settings.models[m] for m in settings.areas["kongsberg"].models]
    first = dt.datetime(2026, 11, 26, 11, tzinfo=dt.UTC)
    hours = [first + dt.timedelta(hours=k) for k in range(24)]
    before = store.hours_for("kongsberg", models, hours)
    assert before.runs["ifs"]["run_time"] == "2026-11-25T18:00:00Z"
    assert before.runs["gfs"]["run_time"] == "2026-11-26T18:00:00Z"

    # 28 Nov: both days are written; the 25th's SSD copy goes (older than 2 days)
    out = finalise_days(dt.datetime(2026, 11, 28, 12, tzinfo=dt.UTC), settings, records,
                        store, Build())  # fmt: skip
    assert [(d["day"], d["outcome"]) for d in out] == [
        ("2026-11-25", "written"), ("2026-11-26", "written"),
    ]  # fmt: skip
    assert store.ssd_days("kongsberg") == [day2]
    assert store.hours_for("kongsberg", models, hours) == before

    # 30 Nov: the 26th's SSD copy goes too; everything is read from /data
    finalise_days(dt.datetime(2026, 11, 30, 12, tzinfo=dt.UTC), settings, records, store,
                  Build())  # fmt: skip
    assert store.ssd_days("kongsberg") == []
    assert store.hours_for("kongsberg", models, hours) == before
    assert days.path_for("kongsberg", DAY).exists() and days.path_for("kongsberg", day2).exists()


def test_failed_abandoned_and_never_seen_runs_are_final_and_named_in_the_store(settings, ct):
    """Paranal: GFS and IFS, 8 runs a day. A partial run waits until it is out of tries."""
    records, store, days = ct
    t = lambda h: dt.datetime(2026, 11, 25, h, tzinfo=dt.UTC)  # noqa: E731
    at = t(23)
    put = lambda model, h, state, missing=None: _put(  # noqa: E731
        settings, records, store, model, t(h), state, at, missing
    )
    for h in (6, 12, 18):
        put("gfs", h, "processed")  # gfs 00z was never seen: the 06z run is newer
    ifs00 = records.seen("ifs", "paranal", t(0), settings.models["ifs"].steps_h, at=at)
    records.transition(ifs00, ("seen",), "failed", at=at, last_error="verify failed: x")
    ifs06 = put("ifs", 6, "partial", missing={48: "try 1 of 5 failed: HTTP 500"})
    for s in settings.models["ifs"].steps_h:
        records.add_try(ifs06, s, "ecmwf-opendata", at, "HTTP 500" if s == 48 else None)
    put("ifs", 12, "abandoned")  # stored some steps first
    ifs18 = records.seen("ifs", "paranal", t(18), settings.models["ifs"].steps_h, at=at)
    records.transition(ifs18, ("seen",), "abandoned", at=at, last_error="abandoned: window")

    assert finalise_days(LATER, settings, records, store, Build()) == []  # ifs 06z: tries left
    for k in range(4):
        records.add_try(ifs06, 48, "ecmwf-opendata", at + dt.timedelta(minutes=k + 1), "500")
    (entry,) = finalise_days(LATER, settings, records, store, Build())

    assert entry["outcome"] == "written" and entry["runs"] == 5
    content = days.read("paranal", DAY)
    assert [(d["model"], d["run_time"][11:13]) for d in content.runs] == [
        ("gfs", "06"), ("gfs", "12"), ("gfs", "18"), ("ifs", "06"), ("ifs", "12"),
    ]  # fmt: skip
    assert content.run("ifs", "2026-11-25T06:00:00Z")["missing_steps"] == {
        "48": "try 1 of 5 failed: HTTP 500"
    }
    missing = {(m["model"], m["run_time"][11:13]): m for m in content.runs_missing}
    assert set(missing) == {("gfs", "00"), ("ifs", "00"), ("ifs", "18")}
    assert missing["gfs", "00"]["state"] == "never seen"
    assert missing["gfs", "00"]["why"] == "the newer run 2026-11-25T18Z was seen first"
    assert missing["ifs", "00"] == {"model": "ifs", "run_time": "2026-11-25T00:00:00Z",
                                    "state": "failed", "why": "verify failed: x"}  # fmt: skip
    assert missing["ifs", "18"]["state"] == "abandoned"


def test_a_day_waits_for_a_run_not_seen_yet_that_can_still_appear(settings, ct):
    records, store, days = ct
    store_day(settings, records, store, "paranal", DAY, except_runs=(("gfs", 18),))
    gfs18 = records.find("gfs", "paranal", dt.datetime(2026, 11, 25, 18, tzinfo=dt.UTC))
    records.manifest.conn.execute("DELETE FROM forecast_runs WHERE id=?", (gfs18.id,))
    records.manifest.conn.commit()

    assert finalise_days(LATER, settings, records, store, Build()) == []
    # GFS's online window (240 h) less 4 h has passed: the run can't appear any more
    gone = dt.datetime(2026, 12, 5, 14, tzinfo=dt.UTC)
    (entry,) = finalise_days(gone, settings, records, store, Build())
    assert entry["outcome"] == "written"
    (m,) = days.read("paranal", DAY).runs_missing
    assert (m["model"], m["state"]) == ("gfs", "never seen") and "online window" in m["why"]


def _put(settings, records, store, model, run_time, state, at, missing=None) -> int:
    from place_days_world import run_doc

    run_id = records.seen(model, "paranal", run_time, settings.models[model].steps_h, at=at)
    stored = store.put_run(run_doc(settings, "paranal", model, run_time, run_id, missing))
    finish(records, run_id, state, at, stored.bytes)
    return run_id


class SlowNas(DayStores):
    """A NAS that hangs (a hard NFS mount) until ``release`` is set."""

    def __init__(self, root):
        super().__init__(root)
        self.release = threading.Event()
        self.calls = 0

    def put(self, content):
        self.calls += 1
        self.release.wait(30)
        return super().put(content)


def test_a_hanging_nas_times_out_is_logged_and_the_day_is_tried_again(settings, tmp_path, caplog):
    records = ForecastRecords(Manifest(tmp_path / "state" / "manifest.sqlite"))
    nas = SlowNas(tmp_path / "data")
    store = PlaceStore(tmp_path / "ssd", days=nas, guard=NasGuard(2))
    store_day(settings, records, store, "kongsberg", DAY)
    store_day(settings, records, store, "kongsberg", DAY + dt.timedelta(days=1))
    now = dt.datetime(2026, 11, 27, 12, tzinfo=dt.UTC)

    t0 = time.monotonic()
    out = finalise_days(now, settings, records, store, Build())
    assert time.monotonic() - t0 < 6  # one timeout, not one per day
    assert [(d["day"], d["outcome"]) for d in out] == [("2026-11-25", "timed_out")]
    assert "no answer from the NAS within 2 s" in caplog.text
    assert records.place_days("kongsberg") == {}

    # the next tick, NAS still hanging: nothing new is sent to it, no time is lost
    t0 = time.monotonic()
    out = finalise_days(now, settings, records, store, Build())
    assert time.monotonic() - t0 < 0.5 and nas.calls == 1
    assert [d["outcome"] for d in out] == ["timed_out"]

    # the NAS answers again: the hung write finishes on its own, and the next call
    # finds that store (same content) and writes the second day
    nas.release.set()
    for _ in range(200):  # each call fails fast while the hung write is still running
        out = finalise_days(now, settings, records, store, Build())
        if out[0]["outcome"] != "timed_out":
            break
        time.sleep(0.05)
    assert nas.calls == 3  # the hung one, then one per day
    assert [(d["day"], d["outcome"]) for d in out] == [
        ("2026-11-25", "exists"), ("2026-11-26", "written"),
    ]  # fmt: skip
    records.manifest.close()


def test_nulls_and_absent_fog_signals_come_back_as_they_were(settings, ct):
    """A column with no turbulence (H̄ null), no valid level (gap null), a fog signal
    the model lacks, and a place with no height read back exactly (never filled)."""
    records, store, days = ct
    docs = store_day(settings, records, store, "kongsberg", DAY)
    gfs = docs[("gfs", dt.datetime(2026, 11, 25, 6, tzinfo=dt.UTC))]
    step = gfs["steps"][3]
    step["cn2"]["osborn_sarazin"]["hbar_m"] = None
    step["gap_to_first_level_m"] = None
    gfs["meta"]["place_height_m"] = None
    for s in gfs["steps"]:
        s["fog"]["visibility_m"] = "absent"
    gfs["steps"] = gfs["steps"][:3] + gfs["steps"][4:10] + gfs["steps"][11:]  # 2 missing
    store.put_run(gfs)

    finalise_days(LATER, settings, records, store, Build())
    assert days.read("kongsberg", DAY).run("gfs", "2026-11-25T06:00:00Z") == gfs


def test_the_store_is_plain_zarr_v3_with_named_arrays_and_provenance(settings, ct):
    """What a reader without our code finds (the layout in ``store.days``)."""
    import zarr

    records, store, days = ct
    store_day(settings, records, store, "kongsberg", DAY)
    finalise_days(LATER, settings, records, store, Build())

    root = zarr.open_group(str(days.path_for("kongsberg", DAY)), mode="r", zarr_format=3)
    assert root.attrs["schema"] == "forecast-place-day/1" and root.attrs["day"] == "2026-11-25"
    assert root.attrs["provenance"]["commit"] == COMMIT
    assert "Copernicus" in root.attrs["credits"]["place_height"]
    assert sorted(name for name, _ in root.groups()) == ["gfs", "icon_eu", "ifs", "meps"]
    ifs = root["ifs"]
    sv = ifs["step_values"]
    assert sv.shape == (4, 17, len(ifs.attrs["step_fields"]))  # 4 runs, steps 0-48 every 3 h
    assert sv.metadata.dimension_names == ("run", "step", "field")
    fields = ifs.attrs["step_fields"]
    for name in ("stored", "valid_time", "cloud.total_pct", "cloud.low_pct", "cloud_class",
                 "cn2.osborn_sarazin.j_free", "cn2.tatarskii.seeing_total_arcsec",
                 "cn2.tatarskii.hbar_m", "wind_200hpa_ms", "fog.dewpoint_depression_2m_k",
                 "gap_to_first_level_m", "valid_levels"):  # fmt: skip
        assert name in fields
    assert ifs.attrs["steps"] == list(range(0, 49, 3))
    assert ifs.attrs["run_fields"][:2] == ["run_id", "run_time"]
    assert {"meta.observer_height_m", "meta.raise_m", "meta.level_count"} <= set(
        ifs.attrs["run_fields"]
    )
    assert ifs["run_values"].shape == (4, len(ifs.attrs["run_fields"]))


def test_a_full_synthetic_day_measures_the_store_size(settings, ct, capsys):
    """For the size report: one full synthetic day per saved place (Kongsberg 16 runs,
    Paranal 8)."""
    records, store, _days = ct
    store_day(settings, records, store, "kongsberg", DAY)
    store_day(settings, records, store, "paranal", DAY)
    out = finalise_days(LATER, settings, records, store, Build())
    size = {d["place"]: d["bytes"] for d in out}
    ssd = {p: sum(f.stat().st_size for f in (store.root / p / "2026-11-25").glob("*.json"))
           for p in size}  # fmt: skip
    with capsys.disabled():
        print(f"\nper-place day store, one full synthetic day: {size} bytes (SSD JSON: {ssd})")
    assert set(size) == {"kongsberg", "paranal"}
    assert 0 < size["paranal"] < size["kongsberg"] < 1_000_000


def test_an_unfinished_temp_folder_is_logged_and_left_alone(settings, ct, caplog):
    records, store, days = ct
    store_day(settings, records, store, "kongsberg", DAY)
    left = days.root / "kongsberg" / ".2026-11-25.zarr.abc123.tmp"
    (left / "store").mkdir(parents=True)  # a write that hung, then its process died

    (entry,) = finalise_days(LATER, settings, records, store, Build())
    assert entry["outcome"] == "written"
    assert "1 unfinished temp folder(s)" in caplog.text and left.name in caplog.text
    assert (left / "store").is_dir()  # never deleted: /data only grows


_TEMPLATE: dict = {}


def _template() -> dict:
    """One GFS run at Kongsberg, made once."""
    if not _TEMPLATE:
        from place_days_world import run_doc

        t = dt.datetime(2026, 11, 25, 6, tzinfo=dt.UTC)
        _TEMPLATE.update(run_doc(load_settings(), "kongsberg", "gfs", t, 7))
    return copy.deepcopy(_TEMPLATE)


_NULLABLE = ("j_total", "j_free", "hbar_m", "seeing_total_arcsec", "seeing_free_arcsec")


@settings_(max_examples=25, deadline=None)
@given(
    kept=st.sets(st.integers(0, 48), min_size=1),
    nulls=st.sets(st.tuples(st.integers(0, 48), st.sampled_from(_NULLABLE))),
    null_gaps=st.sets(st.integers(0, 48)),
    fog_absent=st.booleans(),
)
def test_any_run_reads_back_exactly_from_its_day_store(kept, nulls, null_gaps, fog_absent):
    """Whatever steps a run kept, and wherever a value is null or a fog signal absent,
    the day store gives the run back exactly (never filled, never dropped)."""
    doc = _template()
    doc["steps"] = [s for s in doc["steps"] if s["step"] in kept]
    for s in doc["steps"]:
        for step, name in nulls:
            if s["step"] == step:
                s["cn2"]["tatarskii"][name] = None
        if s["step"] in null_gaps:
            s["gap_to_first_level_m"] = None
        if fog_absent:
            s["fog"]["visibility_m"] = "absent"
    doc["missing_steps"] = {str(k): "5 tries failed" for k in range(49) if k not in kept}
    with tempfile.TemporaryDirectory() as tmp:
        days = DayStores(tmp)
        days.put(DayContent("kongsberg", DAY, (doc,), {"commit": COMMIT}))
        assert days.read("kongsberg", DAY).runs == (doc,)
