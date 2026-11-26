"""Forecast settings (F1 spec #47, Config; ticket #50): the file loads, validates,
and gives a stable config hash."""

from __future__ import annotations

import copy
import re

import pytest
import yaml

from astroseeing.forecast.settings import Grid, SettingsError, load_settings


def test_committed_settings_hold_the_decided_values():
    s = load_settings()

    kb = s.areas["kongsberg"]
    assert (kb.box.west, kb.box.east, kb.box.south, kb.box.north) == (4.65, 14.65, 54.67, 64.67)
    assert kb.models == ("gfs", "icon_eu", "meps", "ifs")  # D51 item 3
    assert kb.map_grid_model == "icon_eu"  # D60 item 2
    assert s.areas["paranal"].models == ("gfs", "ifs")  # D51 item 3

    place = s.places["kongsberg"]
    assert (place.lat, place.lon, place.time_zone) == (59.669, 9.652, "Europe/Oslo")
    assert place.height is not None
    assert (place.height.metres, place.height.source) == (162.0, "hand-entered")  # D47
    assert s.default_place == "kongsberg"

    levels = {m: len(s.models[m].pressure_levels_hpa) for m in s.models}
    assert levels == {"gfs": 39, "icon_eu": 20, "meps": 13, "ifs": 13}  # D44 item 2
    assert s.models["ifs"].steps_h == tuple(range(0, 49, 3))  # D51 item 3
    assert s.models["gfs"].steps_h == tuple(range(49))
    assert s.models["meps"].regional and not s.models["gfs"].regional  # D45 item 3
    assert s.models["icon_eu"].family == "icon"
    assert s.models["icon_eu"].grid == Grid("regular_latlon", 0.0625, "deg")  # D60 item 2
    assert s.models["meps"].grid == Grid("lambert", 2.5, "km")
    assert s.models["ifs"].level_cloud is False  # no cloud fraction on IFS levels
    assert s.models["gfs"].hosts.main.max_requests_per_s == 1  # D51 item 14
    assert s.models["ifs"].hosts.fallback is not None
    assert s.models["icon_eu"].hosts.fallback is None

    assert (s.cloud_classes.clear_max_pct, s.cloud_classes.some_cloud_max_pct) == (10, 50)
    assert s.alerts.staging_min_free_gb == 20  # D51 items 5 and 9
    assert s.alerts.no_complete_run_h == 24
    assert s.alerts.no_tick_h == 1
    assert s.eso.fetch_time_utc == "17:00"  # D54 item 8
    assert s.eso.refetch_after_days == 3


def _write(tmp_path, data, name="forecast.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def _parent(raw, path):
    """The mapping that holds the last key of a key path, and that key."""
    *parents, key = path
    node = raw
    for p in parents:
        node = node[p]
    return node, key


@pytest.fixture
def raw():
    """The committed settings as plain data, to edit one value at a time."""
    return copy.deepcopy(dict(load_settings().raw))


def test_config_hash_is_stable_and_ignores_layout(tmp_path, raw):
    h = load_settings().config_hash
    assert h == load_settings().config_hash
    assert len(h) == 64 and int(h, 16) >= 0
    # Same data, keys reversed and comments gone: same hash.
    reordered = dict(reversed(list(raw.items())))
    assert load_settings(_write(tmp_path, reordered)).config_hash == h


@pytest.mark.parametrize(
    "path, value",
    [
        (("cloud_classes", "clear_max_pct"), 20),
        (("places", "kongsberg", "height", "metres"), 163.0),
        (("models", "gfs", "publish_delay_h"), 3.7),
        (("areas", "kongsberg", "models"), ["gfs", "icon_eu", "ifs"]),
    ],
)
def test_a_changed_value_changes_the_hash(tmp_path, raw, path, value):
    node, key = _parent(raw, path)
    node[key] = value
    assert load_settings(_write(tmp_path, raw)).config_hash != load_settings().config_hash


@pytest.mark.parametrize(
    "path",
    [
        ("eso", "fetch_time_utc"),
        ("models", "ifs", "steps", "every_h"),
        ("places", "kongsberg", "time_zone"),
        ("areas", "paranal", "map_grid_model"),
        ("alerts", "staging_min_free_gb"),
        ("models", "meps", "expected", "pressure_levels_hpa"),
    ],
)
def test_a_missing_required_value_is_refused_by_name(tmp_path, raw, path):
    node, key = _parent(raw, path)
    del node[key]
    with pytest.raises(SettingsError, match=rf"missing required value {re.escape('.'.join(path))}"):
        load_settings(_write(tmp_path, raw))


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda r: r["alerts"].update(stagin_min_free_gb=20), r"alerts: unknown key"),
        (lambda r: r["models"]["gfs"]["expected"].update(pressure_levels_hpa=[50, 100, 1000]),
         r"strictly decreasing \(bottom → top\)"),
        (lambda r: r["areas"]["kongsberg"].update(models=["gfs", "harmonie"]), r"harmonie"),
        (lambda r: r["areas"]["kongsberg"].update(map_grid_model="meps"), r"regional-only"),
        (lambda r: r["places"]["kongsberg"].update(lat=-24.6), r"outside area 'kongsberg'"),
        (lambda r: r["places"]["kongsberg"].update(time_zone="Europe/Kongsberg"),
         r"not an IANA time zone"),
        (lambda r: r["cloud_classes"].update(clear_max_pct=60), r"clear_max_pct < some_cloud"),
        (lambda r: r["eso"].update(fetch_time_utc="5pm"), r"HH:MM"),
        (lambda r: r["run_rules"].update(file_retries="five"), r"must be an integer"),
        (lambda r: r["models"]["gfs"].update(regional="no"), r"must be true/false"),
        (lambda r: r["places"]["kongsberg"]["height"].update(source="glo30"),
         r"needs its tile and sha256"),
        (lambda r: r.update(default_place="oslo"), r"default_place is 'oslo'"),
        (lambda r: r["models"]["ifs"]["expected"].update(fog_signals=["fog_risk"]),
         r"unknown fog signal"),
    ],
)  # fmt: skip
def test_inconsistent_or_mistyped_settings_are_refused(tmp_path, raw, edit, message):
    edit(raw)
    with pytest.raises(SettingsError, match=message):
        load_settings(_write(tmp_path, raw))


def test_a_place_without_a_height_loads_as_none(tmp_path, raw):
    raw["places"]["kongsberg"]["height"] = None
    assert load_settings(_write(tmp_path, raw)).places["kongsberg"].height is None
