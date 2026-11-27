"""Tonight on hand-made nights (F1 spec Module 5, Testing seam 2; ticket #53).

Each case gives Sun altitudes, per-family total cloud and J per hour, run times and
``now``, and checks that the counts, chips, seeing range, MEPS line, stale flags and
nothing-to-count states follow uniquely from D48. Expected values are worked out by
hand from D48's wording, never recomputed the way the code does.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from astroseeing.forecast.schemas import check_document, load_schema
from astroseeing.forecast.settings import CloudClasses, load_settings
from astroseeing.forecast.tonight import (
    HourTable,
    HourValue,
    Missing,
    ModelHours,
    RunInfo,
    SunTrack,
    cloud_class,
    tonight,
)
from astroseeing.physics.optics import j_from_seeing

UTC = dt.UTC
CLASSES = CloudClasses(clear_max_pct=10, some_cloud_max_pct=50)
STALE_AFTER_H = 24.0

# A Kongsberg-like Night (9.652° E): local mean noon is 12:00 UTC - 38.6 min, so
# Tonight's hourly rows run 12:00 UTC to 11:00 UTC the next day.
NIGHT = dt.date(2026, 12, 10)
START = dt.datetime(2026, 12, 10, 11, 21, 23, tzinfo=UTC)
HOURS = tuple(dt.datetime(2026, 12, 10, 12, tzinfo=UTC) + dt.timedelta(hours=i) for i in range(24))


def at(day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 12, day, hour, minute, tzinfo=UTC)


def row(hour_utc: int) -> int:
    """Index of the hh:00 UTC row (12 UTC is row 0)."""
    return (hour_utc - 12) % 24


# Sun altitude at each row, hand-made: sunset about 14:30 UTC, dark (< -18°) from
# 18 to 06 UTC (13 rows), sunrise about 09:30 UTC.
WINTER_ALTS = (
    5.0, 2.0, 0.5,  # 12, 13, 14
    -3.0, -9.0, -15.0,  # 15, 16, 17
    -19.0, -25.0, -30.0, -35.0, -40.0, -42.0, -43.0,  # 18 ... 00
    -42.0, -40.0, -35.0, -30.0, -25.0, -19.0,  # 01 ... 06
    -14.0, -7.0, -2.0,  # 07, 08, 09
    1.0, 4.0,  # 10, 11
)  # fmt: skip


WINTER_SUNSET, WINTER_SUNRISE = at(10, 14, 30), at(11, 9, 30)


def sun(alts=WINTER_ALTS, sunset=WINTER_SUNSET, sunrise=WINTER_SUNRISE) -> SunTrack:
    return SunTrack(
        night=NIGHT,
        start=START,
        end=START + dt.timedelta(days=1),
        hours=HOURS,
        altitude_deg=tuple(alts),
        sunset=sunset,
        sunrise=sunrise,
    )


def run(day: int, hour: int, run_id: int = 1) -> RunInfo:
    return RunInfo(run_id=run_id, run_time=at(day, hour))


def model(mid, family, values, run_info=None, regional=False) -> ModelHours:
    """One model's 24 hourly values: a float is total cloud with J = 1e-14 m^(1/3)."""
    out = []
    for v in values:
        if isinstance(v, (HourValue, Missing)):
            out.append(v)
        else:
            out.append(HourValue(total_cloud_pct=float(v), j_free_atmosphere=1e-14))
    return ModelHours(
        model=mid,
        family=family,
        regional=regional,
        run=run_info if run_info is not None else run(10, 9),  # fresh for every `now` used
        values=tuple(out),
    )


def table(*models) -> HourTable:
    return HourTable(night=NIGHT, hours=HOURS, models=tuple(models))


def verdict(tbl, now, sun_track=None):
    return tonight(tbl, sun_track or sun(), now, cloud_classes=CLASSES, stale_after_h=STALE_AFTER_H)


def test_all_clear_winter_night_before_it_starts_counts_every_dark_hour():
    tbl = table(model("gfs", "gfs", [0.0] * 24), model("icon_eu", "icon", [5.0] * 24))
    t = verdict(tbl, now=at(10, 10))  # morning, after the previous sunrise
    # Dark rows: 18 ... 06 UTC = 13 hours.
    assert t.basis == "dark"
    assert (t.clear_hours, t.counted_hours, t.incomplete_hours) == (13, 13, 0)
    assert t.started is False
    assert t.current_hour is None


def clouds(default: float, **by_hour: float) -> list[float]:
    """24 total-cloud values, ``default`` except ``h<UTC hour>=value``."""
    out = [default] * 24
    for key, value in by_hour.items():
        out[row(int(key[1:]))] = value
    return out


def test_mostly_clear_needs_more_than_half_of_the_families_with_a_value():
    gfs = model("gfs", "gfs", clouds(0.0, h20=60.0, h21=30.0, h22=60.0))
    icon = model("icon_eu", "icon", clouds(10.0, h20=60.0, h21=5.0, h22=30.0))
    ifs = model("ifs", "ifs", clouds(50.0, h20=60.0, h21=80.0, h22=10.0))
    t = verdict(table(gfs, icon, ifs), now=at(10, 10))
    by_time = {h.time: h for h in t.hours}
    # 18 UTC: 0 / 10 / 50 -> clear, clear (10 is clear: T <= 10), some cloud.
    assert by_time[at(10, 18)].agreement == ("mostly_clear", 2, 3, "clear")
    # 20 UTC: all cloudy.
    assert by_time[at(10, 20)].agreement == ("not_clear", 0, 3, "cloudy")
    # 21 UTC: some cloud, clear, cloudy: no class has a strict majority.
    assert by_time[at(10, 21)].agreement == ("not_clear", 1, 3, "split")
    # 22 UTC: cloudy, some cloud, clear: split, 1 of 3 clear.
    assert by_time[at(10, 22)].agreement == ("not_clear", 1, 3, "split")
    # 13 dark rows, 3 of them (20, 21, 22) not mostly clear.
    assert (t.clear_hours, t.counted_hours, t.incomplete_hours) == (10, 13, 0)


def test_two_of_two_clear_and_one_of_two_clear():
    gfs = model("gfs", "gfs", clouds(0.0))
    icon = model("icon_eu", "icon", clouds(0.0, h19=10.01))  # just above the clear limit
    t = verdict(table(gfs, icon), now=at(10, 10))
    by_time = {h.time: h for h in t.hours}
    assert by_time[at(10, 18)].agreement == ("mostly_clear", 2, 2, "clear")
    # 1 of 2 is not more than half; clear and some cloud tie, so split.
    assert by_time[at(10, 19)].agreement == ("not_clear", 1, 2, "split")
    assert (t.clear_hours, t.counted_hours) == (12, 13)


ALL_CLEAR = (model("gfs", "gfs", [0.0] * 24), model("icon_eu", "icon", [0.0] * 24))


@pytest.mark.parametrize(
    ("now", "current", "left"),
    [
        (at(10, 12, 5), at(10, 12), 13),  # Tonight has started; no dark hour is past yet
        (at(10, 23, 29), at(10, 23), 8),  # 23:00 still counts until 23:30: 23 ... 06
        (at(10, 23, 30), at(11, 0), 7),  # from 23:30 the current hour is 00:00
        (at(11, 6, 29), at(11, 6), 1),  # the last dark hour
    ],
)
def test_a_night_already_started_counts_from_the_current_hour(now, current, left):
    t = verdict(table(*ALL_CLEAR), now=now)
    assert t.started is True
    assert t.current_hour == current
    assert (t.clear_hours, t.counted_hours) == (left, left)
    past = [h.time for h in t.hours if h.past]
    assert past == [h for h in HOURS if h < current]
    assert not any(h.counted for h in t.hours if h.past)


def test_now_after_the_nights_sunrise_is_refused():
    with pytest.raises(ValueError, match="sunrise"):
        verdict(table(*ALL_CLEAR), now=at(11, 9, 30))


# Kongsberg in June: no astronomical darkness, and late June not even -12°.
JUNE_ALTS_NAUTICAL = (
    40.0, 38.0, 35.0, 31.0, 26.0, 21.0, 15.0, 10.0, 5.0, 1.0,  # 12 ... 21
    -2.0, -6.0, -11.0, -12.5, -13.0, -12.1, -10.0, -6.0, -1.5,  # 22 ... 06
    3.0, 8.0, 14.0, 20.0, 26.0,  # 07 ... 11
)  # fmt: skip
JUNE_ALTS_CIVIL = tuple(max(a, -6.9) for a in JUNE_ALTS_NAUTICAL)


def test_a_night_with_no_dark_time_falls_back_to_sun_below_minus_12():
    t = verdict(
        table(*ALL_CLEAR),
        now=at(10, 10),
        sun_track=sun(JUNE_ALTS_NAUTICAL, sunset=at(10, 21, 20), sunrise=at(11, 6, 20)),
    )
    # Rows below -12°: 01 (-12.5), 02 (-13.0), 03 (-12.1).
    assert t.basis == "sun_below_12"
    assert [h.time for h in t.hours if h.counted] == [at(11, 1), at(11, 2), at(11, 3)]


def test_a_night_with_no_hour_below_minus_12_falls_back_to_sun_down():
    t = verdict(
        table(*ALL_CLEAR),
        now=at(10, 10),
        sun_track=sun(JUNE_ALTS_CIVIL, sunset=at(10, 21, 20), sunrise=at(11, 6, 20)),
    )
    # Rows below -0.833°: 22 ... 06 UTC.
    assert t.basis == "sun_down"
    assert t.counted_hours == 9


def test_a_single_dark_hour_stays_the_basis():
    alts = list(JUNE_ALTS_NAUTICAL)
    alts[row(2)] = -18.2
    t = verdict(table(*ALL_CLEAR), now=at(10, 10),
                sun_track=sun(alts, sunset=at(10, 21, 20), sunrise=at(11, 6, 20)))  # fmt: skip
    assert t.basis == "dark"
    assert [h.time for h in t.hours if h.counted] == [at(11, 2)]


def test_the_basis_comes_from_the_whole_night_not_the_hours_left():
    # Started after the last dark hour: still the dark basis, with nothing left to count.
    t = verdict(table(*ALL_CLEAR), now=at(11, 7))
    assert t.basis == "dark"
    assert t.counted_hours == 0


# Paranal (70.404° W): local mean noon is 16:41:37 UTC, so rows run 17:00 to 16:00 UTC.
# Hand-made December night: dark rows 02 ... 08 UTC (7 rows), sunset 23:50, sunrise 09:40.
P_NIGHT = dt.date(2026, 12, 10)
P_START = dt.datetime(2026, 12, 10, 16, 41, 37, tzinfo=UTC)
P_HOURS = tuple(
    dt.datetime(2026, 12, 10, 17, tzinfo=UTC) + dt.timedelta(hours=i) for i in range(24)
)
P_ALTS = (
    60.0, 50.0, 40.0, 30.0, 20.0, 9.0, 3.0,  # 17 ... 23
    -5.0, -12.0, -19.0, -25.0, -30.0, -32.0, -30.0, -24.0, -18.5,  # 00 ... 08
    -9.0, 2.0, 12.0, 25.0, 37.0, 50.0, 62.0, 70.0,  # 09 ... 16
)  # fmt: skip
P_SUN = SunTrack(night=P_NIGHT, start=P_START, end=P_START + dt.timedelta(days=1), hours=P_HOURS,
                 altitude_deg=P_ALTS, sunset=at(10, 23, 50), sunrise=at(11, 9, 40))  # fmt: skip


def ifs_every_3h(cloud: float, hours=P_HOURS) -> list:
    return [cloud if t.hour % 3 == 0 else Missing("off_step") for t in hours]


def paranal(*models, now):
    return tonight(HourTable(P_NIGHT, P_HOURS, tuple(models)), P_SUN, now,
                   cloud_classes=CLASSES, stale_after_h=STALE_AFTER_H)  # fmt: skip


def test_ifs_off_steps_at_paranal_are_incomplete_hours():
    gfs = model("gfs", "gfs", [0.0] * 24, run(10, 12))
    ifs = model("ifs", "ifs", ifs_every_3h(0.0), run(10, 12))
    t = paranal(gfs, ifs, now=at(10, 18))
    # Dark rows 02 ... 08; IFS has 03 and 06 only, so those two are 2/2 clear.
    assert (t.clear_hours, t.counted_hours, t.incomplete_hours) == (2, 7, 5)
    by_time = {h.time: h for h in t.hours}
    assert by_time[at(11, 3)].agreement == ("mostly_clear", 2, 2, "clear")
    # One family's value: incomplete, though that family alone is a strict majority.
    assert by_time[at(11, 4)].agreement == ("incomplete", 1, 1, "clear")


def test_run_ages_and_a_stale_run_left_out_of_the_counts():
    now = at(10, 19)
    gfs = model("gfs", "gfs", clouds(0.0), run(10, 12, run_id=7))
    icon = model("icon_eu", "icon", clouds(0.0), run(9, 19, run_id=5))  # exactly 24 h: not stale
    ifs = model("ifs", "ifs", clouds(90.0), run(9, 18, run_id=3))  # 25 h: stale
    t = verdict(table(gfs, icon, ifs), now=now)
    assert t.runs["gfs"] == (7, at(10, 12), 7.0, False)
    assert t.runs["icon_eu"] == (5, at(9, 19), 24.0, False)
    assert t.runs["ifs"] == (3, at(9, 18), 25.0, True)
    # IFS's cloudy values are shown in the table but not counted: 2/2 clear.
    assert t.hours[row(20)].agreement == ("mostly_clear", 2, 2, "clear")
    assert (t.clear_hours, t.counted_hours) == (12, 12)  # 19 ... 06; 19:00 is current


def test_a_model_with_no_run_has_no_run_age():
    gfs = model("gfs", "gfs", clouds(0.0))
    icon = ModelHours("icon_eu", "icon", False, None, (Missing("no_run"),) * 24)
    t = verdict(table(gfs, icon), now=at(10, 10))
    assert set(t.runs) == {"gfs"}
    assert t.incomplete_hours == t.counted_hours == 13


def chip_night():
    gfs = model("gfs", "gfs", clouds(0.0, h20=80.0, h21=0.0, h22=30.0))
    icon_values = clouds(0.0, h20=80.0, h21=80.0, h22=30.0)
    icon_values[row(3)] = Missing("partial")
    return table(gfs, model("icon_eu", "icon", icon_values))


def test_chips_merge_consecutive_counted_hours_of_one_class():
    t = verdict(chip_night(), now=at(10, 10))
    assert [(c.cls, c.start, c.end) for c in t.chips] == [
        ("clear", at(10, 18), at(10, 19)),
        ("cloudy", at(10, 20), at(10, 20)),
        ("split", at(10, 21), at(10, 21)),
        ("some_cloud", at(10, 22), at(10, 22)),
        ("clear", at(10, 23), at(11, 2)),
        ("incomplete", at(11, 3), at(11, 3)),
        ("clear", at(11, 4), at(11, 6)),
    ]
    assert (t.clear_hours, t.counted_hours, t.incomplete_hours) == (9, 13, 1)


def test_chips_cover_only_the_counted_hours_left():
    t = verdict(chip_night(), now=at(10, 21, 10))
    assert [(c.cls, c.start, c.end) for c in t.chips][:2] == [
        ("split", at(10, 21), at(10, 21)),
        ("some_cloud", at(10, 22), at(10, 22)),
    ]
    assert t.chips[-1].end == at(11, 6)


def j_for(seeing_arcsec: float) -> float:
    """The J (m^(1/3)) that gives this seeing at 500 nm, zenith (the engine's inverse)."""
    return float(j_from_seeing(seeing_arcsec))


def with_j(cloud: float, seeing: float | None) -> HourValue:
    return HourValue(cloud, None if seeing is None else j_for(seeing))


def test_seeing_range_is_each_familys_median_j_over_the_counted_hours():
    # GFS: 13 counted rows, 9 at 0.6", 4 at 2.0": the median (7th of 13) is 0.6".
    gfs_values = [with_j(0.0, 0.6) for _ in range(24)]
    for h in (18, 19, 20, 21):
        gfs_values[row(h)] = with_j(0.0, 2.0)
    gfs_values[row(14)] = with_j(0.0, 9.0)  # daytime: not a counted hour
    # ICON: J on 4 counted rows only (an even count): 0.4", 0.5", 0.7", 1.5".
    icon_values = [with_j(0.0, None) for _ in range(24)]
    for h, s in ((22, 0.4), (23, 0.5), (0, 0.7), (1, 1.5)):
        icon_values[row(h)] = with_j(0.0, s)
    # IFS has seeing too, but its run is stale, so it is not a counting family.
    ifs = model("ifs", "ifs", [with_j(0.0, 0.3)] * 24, run(9, 6))
    t = verdict(table(model("gfs", "gfs", gfs_values), model("icon_eu", "icon", icon_values), ifs),
                now=at(10, 10))  # fmt: skip
    # ICON: mean of the two middle Js (0.5" and 0.7"), then converted, since seeing ~ J^(3/5).
    icon_expected = 0.5 * ((1 + (0.7 / 0.5) ** (5 / 3)) / 2) ** (3 / 5)  # = 0.6081"
    assert t.seeing.per_family == pytest.approx({"gfs": 0.6, "icon": icon_expected}, rel=1e-9)
    assert t.seeing.min_arcsec == pytest.approx(0.6, rel=1e-9)
    assert t.seeing.max_arcsec == pytest.approx(icon_expected, rel=1e-9)


def test_seeing_ignores_past_hours_and_counts_incomplete_ones():
    # Started at 23:10: rows 23 ... 06 are left (8). GFS's bad seeing is all in the past.
    gfs_values = [with_j(0.0, 2.0) if row(18) <= i < row(23) else with_j(0.0, 0.5)
                  for i in range(24)]  # fmt: skip
    icon_values = [Missing("partial")] * 24  # every hour incomplete; GFS's J still counts
    t = verdict(table(model("gfs", "gfs", gfs_values), model("icon_eu", "icon", icon_values)),
                now=at(10, 23, 10))  # fmt: skip
    assert t.seeing.per_family == pytest.approx({"gfs": 0.5}, rel=1e-9)


def test_no_family_with_seeing_tonight_gives_no_range():
    no_j = [with_j(0.0, None)] * 24
    t = verdict(table(model("gfs", "gfs", no_j), model("icon_eu", "icon", no_j)), now=at(10, 10))
    assert t.seeing is None


def meps(values, run_info=None) -> ModelHours:
    return model("meps", "meps", values, run_info, regional=True)


def test_meps_is_never_counted_and_gets_its_own_line():
    gfs = model("gfs", "gfs", clouds(0.0))
    icon = model("icon_eu", "icon", clouds(0.0))
    # MEPS cloudy all night but clear at 23 and 00: it changes no count.
    t = verdict(table(gfs, icon, meps(clouds(90.0, h23=10.0, h0=3.0))), now=at(10, 10))
    assert (t.clear_hours, t.counted_hours) == (13, 13)
    assert t.hours[row(20)].agreement == ("mostly_clear", 2, 2, "clear")
    assert (t.meps.clear_hours, t.meps.counted_hours) == (2, 13)
    assert "meps" not in t.seeing.per_family
    assert t.runs["meps"].stale is False


def test_no_meps_line_where_meps_does_not_cover_the_place():
    gfs = model("gfs", "gfs", [0.0] * 24, run(10, 12))
    ifs = model("ifs", "ifs", ifs_every_3h(0.0), run(10, 12))
    assert paranal(gfs, ifs, now=at(10, 18)).meps is None


# Riley's choice on ticket #53 (2026-11-26, D74 item 10): n stays Tonight's counted
# hours, the hours MEPS lacks are reported as missing, and a stale MEPS run's hours all
# count as missing (as for the global models).
def test_meps_line_reports_its_missing_hours():
    values = clouds(0.0)
    values[row(3)] = Missing("partial")
    values[row(4)] = Missing("partial")
    t = verdict(table(*ALL_CLEAR, meps(values)), now=at(10, 10))
    assert (t.meps.clear_hours, t.meps.counted_hours, t.meps.missing_hours) == (11, 13, 2)
    assert t.meps.stale is False


def test_a_stale_meps_run_is_shown_but_its_line_counts_nothing():
    t = verdict(table(*ALL_CLEAR, meps(clouds(0.0), run(9, 6))), now=at(10, 10))  # 28 h old
    assert t.runs["meps"].stale is True
    assert (t.meps.clear_hours, t.meps.counted_hours, t.meps.missing_hours) == (0, 13, 13)
    assert t.meps.stale is True


def test_dark_time_ended_when_no_counted_hour_is_left_before_sunrise():
    t = verdict(table(*ALL_CLEAR), now=at(11, 7, 45))
    assert (t.clear_hours, t.counted_hours, t.incomplete_hours) == (0, 0, 0)
    assert t.nothing_to_count.reason == "dark_time_ended"
    assert t.chips == ()
    assert t.seeing is None


# Riley's choice on ticket #53 (2026-11-26, D74 item 10): the time in "Dark time ended
# at hh:mm" is when the last counted hour stopped counting (its hh:00 + 30 min, D48
# item 3), the moment this message appears.
def test_dark_time_ended_at_is_when_the_last_counted_hour_stopped_counting():
    t = verdict(table(*ALL_CLEAR), now=at(11, 6, 30))
    assert t.nothing_to_count.dark_time_ended_at == at(11, 6, 30)
    assert t.nothing_to_count.families == {}


def test_every_hour_incomplete_means_not_enough_models_naming_each_familys_state():
    now = at(10, 19)
    gfs = model("gfs", "gfs", clouds(0.0), run(10, 12))
    icon = model("icon_eu", "icon", clouds(0.0), run(9, 12))  # 31 h: stale
    ifs = ModelHours("ifs", "ifs", False, None, (Missing("no_run"),) * 24)
    t = verdict(table(gfs, icon, ifs, meps(clouds(0.0), run(10, 12))), now=now)
    assert t.nothing_to_count.reason == "not_enough_models"
    assert t.nothing_to_count.dark_time_ended_at is None
    assert t.nothing_to_count.families == {"gfs": "ok", "icon": "stale", "ifs": "missing"}
    # The counts are still there (the page shows none): 12 left, all incomplete.
    assert (t.clear_hours, t.counted_hours, t.incomplete_hours) == (0, 12, 12)
    assert [(c.cls, c.start, c.end) for c in t.chips] == [("incomplete", at(10, 19), at(11, 6))]


def test_not_enough_models_at_paranal_on_an_ifs_off_step_and_a_partial_run():
    # 08 UTC is the last dark row; IFS has no 08 step, and GFS's run lacks it.
    gfs_values = [0.0] * 24
    gfs_values[P_HOURS.index(at(11, 8))] = Missing("partial")
    t = paranal(model("gfs", "gfs", gfs_values, run(11, 0)),
                model("ifs", "ifs", ifs_every_3h(0.0), run(10, 12)), now=at(11, 7, 40))  # fmt: skip
    assert t.nothing_to_count.families == {"gfs": "partial", "ifs": "off_step"}


def test_some_incomplete_hours_still_give_a_verdict():
    gfs = model("gfs", "gfs", clouds(0.0))
    icon_values = clouds(0.0)
    icon_values[row(5)] = Missing("partial")
    t = verdict(table(gfs, model("icon_eu", "icon", icon_values)), now=at(10, 10))
    assert t.nothing_to_count is None
    assert (t.clear_hours, t.counted_hours, t.incomplete_hours) == (12, 13, 1)


def tonight_schema_errors(document) -> list[str]:
    """Problems with ``document`` as the per-place file's ``tonight`` block."""
    defs = load_schema("f1-place/1")["$defs"]
    return check_document(document, {"$defs": defs, "$ref": "#/$defs/tonight"})


@pytest.mark.parametrize(
    "case",
    ["verdict", "dark_time_ended", "not_enough_models", "paranal"],
)
def test_the_json_form_is_the_place_files_tonight_block(case):
    if case == "verdict":
        t = verdict(table(*ALL_CLEAR, meps(clouds(0.0))), now=at(10, 23, 10))
    elif case == "dark_time_ended":
        t = verdict(table(*ALL_CLEAR), now=at(11, 7))
    elif case == "not_enough_models":
        t = verdict(table(model("gfs", "gfs", clouds(0.0))), now=at(10, 10))
    else:
        gfs = model("gfs", "gfs", [0.0] * 24, run(10, 12))
        t = paranal(gfs, model("ifs", "ifs", ifs_every_3h(0.0), run(10, 12)), now=at(10, 18))
    doc = t.to_json()
    assert tonight_schema_errors(doc) == []
    assert json.loads(json.dumps(doc, allow_nan=False)) == doc


def test_the_json_form_spells_out_times_and_values():
    doc = verdict(table(*ALL_CLEAR, meps(clouds(0.0))), now=at(10, 23, 10)).to_json()
    assert doc["night"] == "2026-12-10"
    assert doc["basis"] == "dark"
    assert doc["started"] is True
    assert doc["current_hour"] == "2026-12-10T23:00:00Z"
    assert (doc["clear_hours"], doc["counted_hours"], doc["incomplete_hours"]) == (8, 8, 0)
    assert doc["chips"] == [
        {"class": "clear", "start": "2026-12-10T23:00:00Z", "end": "2026-12-11T06:00:00Z"}
    ]
    assert doc["seeing"]["per_family"].keys() == {"gfs", "icon"}
    assert doc["meps"] == {"clear_hours": 8, "counted_hours": 8, "missing_hours": 0,
                           "stale": False}  # fmt: skip
    assert doc["nothing_to_count"] is None
    assert doc["runs"]["gfs"] == {"run_id": 1, "run_time": "2026-12-10T09:00:00Z",
                                  "age_h": pytest.approx(14 + 10 / 60), "stale": False}  # fmt: skip


@pytest.mark.parametrize(
    ("total", "expected"),
    [(0.0, "clear"), (10.0, "clear"), (10.0001, "some_cloud"), (50.0, "some_cloud"),
     (50.0001, "cloudy"), (100.0, "cloudy")],
)  # fmt: skip
def test_cloud_classes_use_the_unrounded_value_and_the_settings_thresholds(total, expected):
    # D48 item 6: clear T <= 10 %, some cloud 10 < T <= 50 %, cloudy T > 50 %, from the
    # settings file; 10.0001 would round to 10 but is not clear.
    assert cloud_class(total, load_settings().cloud_classes) == expected


def test_a_run_that_ends_before_the_hours_left_names_its_family_missing():
    # Ticket #63: the store gives no_run for the hours a model's run doesn't reach,
    # though the model has a run. ICON's run (22 h old: not stale) ends at 04 UTC; at
    # 04:40 every counted hour left (05, 06) has GFS only, so nothing can be counted.
    icon_values = clouds(0.0)
    for h in (5, 6, 7, 8, 9, 10, 11):
        icon_values[row(h)] = Missing("no_run")
    icon = model("icon_eu", "icon", icon_values, run(10, 6))
    t = verdict(table(model("gfs", "gfs", clouds(0.0), run(11, 0)), icon), now=at(11, 4, 40))
    assert t.nothing_to_count.reason == "not_enough_models"
    assert t.nothing_to_count.families == {"gfs": "ok", "icon": "missing"}
    assert t.runs["icon_eu"].stale is False
