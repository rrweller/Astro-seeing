"""Schemas of the files the F1 page reads (spec Module 7; ticket #50): ``latest.json``
(``f1-latest/1``) and the per-place file (``f1-place/1``)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from astroseeing.forecast.schemas import (
    SCHEMA_FILES,
    SchemaError,
    SchemaViolation,
    schema_path,
    validate,
)

FIXTURES = Path(__file__).parent / "fixtures" / "forecast"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def latest():
    return load("latest-spec-example.json")


@pytest.fixture
def place():
    return load("place-minimal.json")


def test_schema_files_are_plain_json_any_test_can_read():
    assert set(SCHEMA_FILES) == {"f1-latest/1", "f1-place/1"}
    for name in SCHEMA_FILES:
        doc = json.loads(schema_path(name).read_text())
        assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert doc["properties"]["schema"]["const"] == name


def test_the_specs_example_latest_json_validates(latest):
    validate(latest)  # the document names its own schema
    validate(latest, "f1-latest/1")


def test_a_hand_written_minimal_place_file_validates(place):
    validate(place, "f1-place/1")
    assert len(place["hours"]) == 24


def drop(doc: dict, path: str) -> dict:
    """A copy of ``doc`` without the key at a dotted path (list indexes as numbers)."""
    doc = copy.deepcopy(doc)
    *parents, key = path.split(".")
    node = doc
    for p in parents:
        node = node[int(p)] if isinstance(node, list) else node[p]
    del node[key]
    return doc


@pytest.mark.parametrize(
    "path",
    ["set_id", "provenance.config_hash", "grid.nlat", "layers.clear_left.dtype",
     "runs.gfs.stale", "places.0.file", "written_at"],
)  # fmt: skip
def test_latest_missing_a_required_key_fails(latest, path):
    with pytest.raises(SchemaViolation, match=rf"missing required key '{path.split('.')[-1]}'"):
        validate(drop(latest, path), "f1-latest/1")


@pytest.mark.parametrize(
    "path",
    ["tonight", "tonight.basis", "tonight.current_hour", "hours.5.models.gfs.cloud",
     "hours.0.agreement",
     "models.ifs.observer_height_m", "moon.rise", "provenance.run_ids", "place.time_zone"],
)  # fmt: skip
def test_place_missing_a_required_key_fails(place, path):
    with pytest.raises(SchemaViolation, match=rf"missing required key '{path.split('.')[-1]}'"):
        validate(drop(place, path), "f1-place/1")


@pytest.mark.parametrize(
    "edit, where",
    [
        (lambda d: d.update(set_id="2026-11-26 18:30"), r"\$\.set_id"),
        (lambda d: d.update(schema="f1-latest/2"), r"\$\.schema"),
        (lambda d: d["grid"].update(nlat=160.5), r"\$\.grid\.nlat"),
        (lambda d: d["layers"]["clear_left"].update(dtype="float64"), r"dtype"),
        (lambda d: d["layers"]["clear_left"]["codes"].update(x="?"), r"codes"),
        (lambda d: d["runs"]["gfs"].update(state="done"), r"state"),
        (lambda d: d.update(colour="blue"), r"unexpected key 'colour'"),
        (lambda d: d["runs"]["gfs"].update(run_time="2026-11-26T12:00:00+01:00"), r"run_time"),
    ],
)
def test_latest_with_a_wrong_value_fails_naming_where(latest, edit, where):
    edit(latest)
    with pytest.raises(SchemaViolation, match=where):
        validate(latest, "f1-latest/1")


@pytest.mark.parametrize(
    "edit, where",
    [
        (lambda d: d["hours"].pop(), r"\$\.hours"),  # 23 hours
        (lambda d: d["hours"][3]["models"]["ifs"].update(missing="filled"), r"hours\[3\]"),
        (lambda d: d["hours"][0]["models"]["gfs"]["fog"].update(visibility_m=None), r"fog"),
        (lambda d: d["tonight"].update(basis="twilight"), r"basis"),
        (lambda d: d["hours"][0]["models"]["gfs"]["cloud"].update(total_pct=101), r"total_pct"),
    ],
)
def test_place_with_a_wrong_value_fails_naming_where(place, edit, where):
    edit(place)
    with pytest.raises(SchemaViolation, match=where):
        validate(place, "f1-place/1")


def test_every_problem_is_reported_at_once(latest):
    bad = drop(drop(latest, "set_id"), "grid.nlon")
    with pytest.raises(SchemaViolation) as e:
        validate(bad, "f1-latest/1")
    assert len(e.value.errors) == 2


def test_unknown_schema_names_are_refused(latest):
    latest["schema"] = "f9-nothing/1"
    with pytest.raises(SchemaError, match="no schema 'f9-nothing/1'"):
        validate(latest)


def test_the_validator_refuses_keywords_it_does_not_check():
    # A schema keyword the validator doesn't implement would be silently ignored, so a
    # schema that uses one is refused rather than half-checked.
    from astroseeing.forecast.schemas import check_document

    with pytest.raises(SchemaError, match="format"):
        check_document({"x": "2026"}, {"type": "object", "properties": {"x": {"format": "date"}}})
