"""Property tests for Tonight (F1 spec Testing seam 2; ticket #53): x <= n; adding a
clear family to an hour never turns mostly clear into not; the result doesn't depend
on the order of the families."""

from __future__ import annotations

import datetime as dt

from hypothesis import given, settings
from hypothesis import strategies as st

from astroseeing.forecast.settings import CloudClasses
from astroseeing.forecast.tonight import (
    HourTable,
    HourValue,
    Missing,
    ModelHours,
    RunInfo,
    SunTrack,
    tonight,
)

UTC = dt.UTC
CLASSES = CloudClasses(clear_max_pct=10, some_cloud_max_pct=50)
NIGHT = dt.date(2026, 12, 10)
START = dt.datetime(2026, 12, 10, 11, 21, 23, tzinfo=UTC)
HOURS = tuple(dt.datetime(2026, 12, 10, 12, tzinfo=UTC) + dt.timedelta(hours=i) for i in range(24))
SUNSET = dt.datetime(2026, 12, 10, 14, 30, tzinfo=UTC)
SUNRISE = dt.datetime(2026, 12, 11, 9, 30, tzinfo=UTC)
GLOBAL = (("gfs", "gfs"), ("icon_eu", "icon"), ("ifs", "ifs"))

# Sun altitudes: positive until 14 UTC and from 10 UTC, below the horizon in between,
# each night-time row free to fall anywhere from -1° to -45° (so every basis occurs).
altitudes = st.tuples(*([st.just(5.0)] * 3 + [st.floats(-45.0, -1.0)] * 19 + [st.just(4.0)] * 2))
values = st.one_of(
    st.floats(0.0, 100.0).map(lambda c: HourValue(c, 1e-14)),
    st.floats(0.0, 100.0).map(lambda c: HourValue(c, None)),
    st.sampled_from([Missing("off_step"), Missing("partial")]),
)
ages_h = st.sampled_from([0, 3, 7, 13, 24, 25, 31])  # run age at `now`, hours (> 24: stale)
nows = st.integers(0, int((SUNRISE - START).total_seconds() // 60) - 1).map(
    lambda m: START - dt.timedelta(hours=2) + dt.timedelta(minutes=m)
)


@st.composite
def families(draw, now, min_size=0):
    chosen = draw(st.lists(st.sampled_from(GLOBAL), min_size=min_size, unique=True))
    out = []
    for i, (mid, fam) in enumerate(chosen):
        run_time = now - dt.timedelta(hours=draw(ages_h))
        out.append(ModelHours(mid, fam, False, RunInfo(i + 1, run_time),
                              tuple(draw(st.lists(values, min_size=24, max_size=24)))))  # fmt: skip
    return out


def sun(alts) -> SunTrack:
    return SunTrack(NIGHT, START, START + dt.timedelta(days=1), HOURS, alts, SUNSET, SUNRISE)


def verdict(models, alts, now):
    return tonight(HourTable(NIGHT, HOURS, tuple(models)), sun(alts), now,
                   cloud_classes=CLASSES, stale_after_h=24.0)  # fmt: skip


@settings(max_examples=300, deadline=None)
@given(altitudes, nows, st.data())
def test_x_never_exceeds_n(alts, now, data):
    models = data.draw(families(now))
    t = verdict(models, alts, now)
    assert 0 <= t.clear_hours <= t.counted_hours
    assert t.clear_hours + t.incomplete_hours <= t.counted_hours
    assert sum((c.end - c.start) // dt.timedelta(hours=1) + 1 for c in t.chips) == t.counted_hours


@settings(max_examples=300, deadline=None)
@given(altitudes, nows, st.data())
def test_adding_a_clear_family_never_turns_mostly_clear_into_not(alts, now, data):
    models = data.draw(families(now, min_size=2))
    present = {m.family for m in models}
    absent = [g for g in GLOBAL if g[1] not in present]
    before = verdict(models, alts, now)
    if absent:  # a new family, clear in some hours and missing in the others
        mid, fam = absent[0]
        clear_rows = data.draw(st.sets(st.integers(0, 23)))
        added = tuple(HourValue(data.draw(st.floats(0.0, 10.0)), None) if i in clear_rows
                      else Missing("off_step") for i in range(24))  # fmt: skip
        fresh = RunInfo(99, now - dt.timedelta(hours=data.draw(st.integers(0, 24))))
        after = verdict([*models, ModelHours(mid, fam, False, fresh, added)], alts, now)
    else:  # a family that had no value in some hours gets a clear value there
        k = data.draw(st.integers(0, len(models) - 1))
        target = models[k]
        filled = tuple(HourValue(5.0, None) if isinstance(v, Missing) else v
                       for v in target.values)  # fmt: skip
        changed = ModelHours(target.model, target.family, False, target.run, filled)
        after = verdict([*models[:k], changed, *models[k + 1 :]], alts, now)
    for b, a in zip(before.hours, after.hours, strict=True):
        if b.agreement.state == "mostly_clear":
            assert a.agreement.state == "mostly_clear"
    assert after.clear_hours >= before.clear_hours


@settings(max_examples=200, deadline=None)
@given(altitudes, nows, st.data(), st.randoms(use_true_random=False))
def test_the_result_does_not_depend_on_family_order(alts, now, data, rnd):
    models = data.draw(families(now))
    shuffled = list(models)
    rnd.shuffle(shuffled)
    a, b = verdict(models, alts, now), verdict(shuffled, alts, now)
    assert a.to_json() == b.to_json()
    assert a.hours == b.hours
