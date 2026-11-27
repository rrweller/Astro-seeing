"""The place file's fog signals and models section (F1 spec Module 7; ticket #64).

Each Kongsberg model's run goes the tick's way from ``RunFields`` (fog signals only
where the model has them) through ``column_products``, ``run_document`` and the SSD
store to ``build_place_file``. The fields each model should have are D49 item 3's list
(low cloud is a field of its own, in ``cloud``); the terrain caveat is D49 item 4's rule.
"""

from __future__ import annotations

import datetime as dt

import pytest
from place_days_world import COMMIT, run_doc

from astroseeing.forecast.publish.place_file import build_place_file
from astroseeing.forecast.schemas import validate
from astroseeing.forecast.settings import load_settings
from astroseeing.forecast.store import PlaceStore
from astroseeing.forecast.tonight import sun_track

RUN_TIME = dt.datetime(2026, 11, 26, 6, tzinfo=dt.UTC)
NOW = dt.datetime(2026, 11, 26, 10, 5, tzinfo=dt.UTC)

#: D49 item 3: each F1 model's own fog and visibility outputs.
FOG_FIELDS = {
    "gfs": {"visibility_m"},
    "icon_eu": {"visibility_m", "weather_code"},
    "meps": {"fog_fraction_pct", "visibility_m"},
    "ifs": {"dewpoint_depression_2m_k"},
}

#: Model grounds for the case: GFS, ICON-EU and IFS above Kongsberg's 162.28 m, MEPS
#: below it.
GROUND_M = {"gfs": 327.4, "icon_eu": 346.9, "meps": 120.0, "ifs": 261.0}


@pytest.fixture(scope="module")
def place(tmp_path_factory, ephemeris) -> dict:
    settings = load_settings()
    kongsberg = settings.places["kongsberg"]
    models = [settings.models[m] for m in settings.areas[kongsberg.area].models]
    store = PlaceStore(tmp_path_factory.mktemp("places"))
    for run_id, m in enumerate(models, start=1):
        store.put_run(
            run_doc(settings, "kongsberg", m.id, RUN_TIME, run_id, ground_m=GROUND_M[m.id])
        )
    sun = sun_track(kongsberg.lat, kongsberg.lon, NOW, *ephemeris)
    hours = store.hours_for("kongsberg", models, sun.hours)
    doc = build_place_file(
        kongsberg, models, hours, sun, NOW, settings=settings, ephemeris=ephemeris, commit=COMMIT
    )
    validate(doc, "f1-place/1")
    return doc


def test_a_fog_field_a_model_lacks_is_written_absent_never_null_or_zero(place):
    assert set(place["models"]) == set(FOG_FIELDS)
    for model_id, fields in FOG_FIELDS.items():
        with_values = [h["models"][model_id] for h in place["hours"]]
        with_values = [v for v in with_values if "missing" not in v]
        assert with_values, model_id
        for value in with_values:
            for name, got in value["fog"].items():
                if name in fields:
                    assert isinstance(got, float), (model_id, name, got)
                else:
                    assert got == "absent" and isinstance(got, str), (model_id, name, got)
            # the low-cloud signal is the model's own low cloud, which every model has
            assert isinstance(value["cloud"]["low_pct"], float)


def test_the_models_section_gives_ground_gap_and_the_terrain_caveat_in_metres(place):
    height = place["place"]["height_m"]
    for model_id, ground in GROUND_M.items():
        m = place["models"][model_id]
        assert m["model_ground_m"] == pytest.approx(ground)
        assert m["gap_to_first_level_m"] > 0
        if ground > height:
            # Kongsberg lies below this model's ground: by how much
            assert m["terrain_caveat_m"] == pytest.approx(ground - height)
        else:
            # Kongsberg lies above MEPS's ground: no caveat
            assert m["terrain_caveat_m"] is None
    assert place["models"]["gfs"]["terrain_caveat_m"] == pytest.approx(327.4 - 162.28, abs=0.01)
