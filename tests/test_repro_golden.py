"""Golden-result JSON helpers (D57 item 5) and the ``data`` marker."""

from __future__ import annotations

import json

import numpy as np
import pytest

from astroseeing.repro import (
    GoldenResult,
    check_golden,
    load_golden,
    meets_target,
    summary_statistics,
    write_golden,
)


def _result(**kw):
    base = dict(
        site="ali",
        variant="night-mask",
        status="gating",
        settings={"rule": {"rule": "nearest"}, "wavelength_nm": 550.0},
        inputs=[{"store": "era5/pl/tibet/2017-03.zarr", "content_sha256": "ab" * 32}],
        statistics={"median": 0.871, "q1": 0.79, "q3": 1.004, "hours": 1234, "masked_levels": 9},
        target={"median": 0.87, "q1": 0.79, "q3": 1.00},
        tolerance={"abs": 0.05, "on": ["median", "q1", "q3"]},
    )
    return GoldenResult(**{**base, **kw})


def test_summary_statistics_by_hand():
    # Linear quantiles of 1..8: Q1 = 2.75, median 4.5, Q3 = 6.25.
    s = summary_statistics(np.arange(1.0, 9.0))
    assert s == {"median": 4.5, "q1": 2.75, "q3": 6.25, "hours": 8}


def test_summary_statistics_refuses_nan_and_empty_input():
    with pytest.raises(ValueError, match="1 NaN"):
        summary_statistics(np.array([1.0, np.nan, 2.0]))
    with pytest.raises(ValueError, match="no values"):
        summary_statistics(np.array([]))


def test_golden_file_round_trips_with_everything_d57_asks_for(tmp_path):
    path = tmp_path / "golden" / "bi2023.json"
    results = [
        _result(),
        _result(variant="all-hours", status="informational", target=None, tolerance=None),
    ]
    write_golden(path, "bi2023", results)

    paper, back = load_golden(path)
    assert paper == "bi2023"
    assert sorted(back, key=lambda r: r.variant) == sorted(results, key=lambda r: r.variant)
    raw = json.loads(path.read_text())
    assert raw["schema"] == "astro-golden/1"
    assert set(raw["results"][0]) == {
        "site",
        "variant",
        "status",
        "settings",
        "inputs",
        "statistics",
        "target",
        "tolerance",
        "note",
    }


def test_golden_refuses_unknown_status_and_duplicate_variants(tmp_path):
    with pytest.raises(ValueError, match="status"):
        _result(status="maybe")
    with pytest.raises(ValueError, match="twice"):
        write_golden(tmp_path / "g.json", "bi2023", [_result(), _result()])
    with pytest.raises(ValueError, match="NaN"):
        write_golden(tmp_path / "g.json", "bi2023", [_result(statistics={"median": float("nan")})])


def test_check_golden_passes_a_faithful_recomputation_and_names_every_difference(tmp_path):
    path = tmp_path / "bi2023.json"
    write_golden(path, "bi2023", [_result()])
    assert (
        check_golden(path, [_result(statistics={**_result().statistics, "median": 0.871 + 1e-13})])
        == []
    )

    moved = _result(statistics={**_result().statistics, "median": 0.9})
    other_store = _result(
        inputs=[{"store": "era5/pl/tibet/2017-03.zarr", "content_sha256": "cd" * 32}]
    )
    other_settings = _result(settings={"rule": {"rule": "bilinear"}, "wavelength_nm": 550.0})
    unknown = _result(variant="new")
    problems = check_golden(path, [moved, other_store, other_settings, unknown])
    assert any("ali/night-mask: median 0.9 != recorded 0.871" in p for p in problems)
    assert any("inputs differ" in p for p in problems)
    assert any("settings differ" in p for p in problems)
    assert any("ali/new: not in the golden file" in p for p in problems)


def test_a_gating_number_moves_only_with_approval(tmp_path):
    path = tmp_path / "bi2023.json"
    write_golden(path, "bi2023", [_result()])
    moved = _result(statistics={**_result().statistics, "median": 0.9})
    with pytest.raises(ValueError, match=r"gating.*Riley"):
        write_golden(path, "bi2023", [moved])
    write_golden(path, "bi2023", [moved], allow_gating_change=True)
    assert load_golden(path)[1][0].statistics["median"] == 0.9


def test_an_informational_number_moves_only_with_a_note(tmp_path):
    path = tmp_path / "bi2023.json"
    info = _result(status="informational")
    write_golden(path, "bi2023", [info])
    moved = _result(status="informational", statistics={**info.statistics, "q3": 1.1})
    with pytest.raises(ValueError, match="note"):
        write_golden(path, "bi2023", [moved])
    write_golden(
        path,
        "bi2023",
        [
            _result(
                status="informational",
                statistics=moved.statistics,
                note="2026-12-01: store re-ingested, see D99",
            )
        ],
    )


def test_meets_target_absolute_and_relative():
    assert meets_target(_result()) is True  # 0.871/0.79/1.004 within 0.05 of 0.87/0.79/1.00
    assert meets_target(_result(statistics={**_result().statistics, "q3": 1.06})) is False
    rel = _result(
        target={"median": 1.0},
        tolerance={"rel": 0.001, "on": ["median"]},
        statistics={"median": 1.0009},
    )
    assert meets_target(rel) is True
    assert meets_target(_result(target=None, tolerance=None)) is None


def test_summary_statistics_carry_the_masked_level_count():
    s = summary_statistics(np.arange(1.0, 9.0), masked_levels=12)
    assert s["masked_levels"] == 12 and s["median"] == 4.5


@pytest.mark.parametrize(
    "change",
    [
        {"tolerance": {"abs": 0.5, "on": ["median", "q1", "q3"]}},
        {"target": {"median": 0.9, "q1": 0.79, "q3": 1.00}},
        {"settings": {"rule": {"rule": "bilinear"}, "wavelength_nm": 550.0}},
        {"inputs": []},
    ],
)
def test_any_change_to_a_gating_result_needs_approval(tmp_path, change):
    path = tmp_path / "bi2023.json"
    write_golden(path, "bi2023", [_result()])
    with pytest.raises(ValueError, match="Riley"):
        write_golden(path, "bi2023", [_result(**change)])
    # A note alone may change.
    write_golden(path, "bi2023", [_result(note="re-read 2026-12-01")])


def test_check_golden_reports_recorded_results_that_were_not_recomputed(tmp_path):
    path = tmp_path / "bi2023.json"
    write_golden(path, "bi2023", [_result(), _result(site="lenghu")])
    assert check_golden(path, [_result()]) == [
        "lenghu/night-mask: in the golden file, not recomputed"
    ]


def test_a_tolerance_must_say_one_kind_and_name_statistics_the_target_has():
    with pytest.raises(ValueError, match="one of"):
        _result(tolerance={"abs": 0.05, "rel": 0.01, "on": ["median"]})
    with pytest.raises(ValueError, match="target"):
        _result(tolerance={"abs": 0.05, "on": ["iqr"]})


# --- the ``data`` marker ---------------------------------------------------------------

_MARKED = """
import pytest

@pytest.mark.data
def test_needs_the_nas():
    assert True
"""


def test_data_marker_skips_without_the_data_root_and_runs_with_it(pytester, monkeypatch, tmp_path):
    from pathlib import Path

    pytester.makeconftest(Path(__file__).with_name("conftest.py").read_text())
    pytester.makepyfile(_MARKED)

    monkeypatch.setenv("ASTRO_DATA_ROOT", str(tmp_path / "absent"))
    r = pytester.runpytest("--strict-markers", "-rs")
    r.assert_outcomes(skipped=1)
    r.stdout.fnmatch_lines(["*needs the NAS stores*absent*"])

    monkeypatch.setenv("ASTRO_DATA_ROOT", str(tmp_path))
    pytester.runpytest("--strict-markers").assert_outcomes(passed=1)
