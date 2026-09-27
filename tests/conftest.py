"""Shared fixtures."""

from __future__ import annotations

import datetime as dt

import pytest


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
