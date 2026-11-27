"""Shared fixtures."""

from __future__ import annotations

import datetime as dt

import pytest

pytest_plugins = ["pytester"]


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "data: needs the NAS stores under ASTRO_DATA_ROOT (default /data/astro); "
        "skipped when that folder is absent (golden tests, D57 item 5)",
    )


def pytest_collection_modifyitems(config, items):
    from astroseeing.paths import Paths

    root = Paths.from_env().data_root
    if root.is_dir():
        return
    skip = pytest.mark.skip(reason=f"needs the NAS stores: {root} is absent")
    for item in items:
        if item.get_closest_marker("data") is not None:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def ephemeris():
    """(eph, ts) for DE440s; downloads once into $ASTRO_EPHEMERIS_DIR (checksum-verified)."""
    from astroseeing.solar.sun import load_ephemeris

    return load_ephemeris()


@pytest.fixture(scope="session")
def sun_table_2021_2025(ephemeris):
    from astroseeing.solar.sun import SunTable

    eph, ts = ephemeris
    return SunTable.build(
        dt.datetime(2020, 12, 30, tzinfo=dt.UTC),
        dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        eph,
        ts,
        step_minutes=10.0,
    )
