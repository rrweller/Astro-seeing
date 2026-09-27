"""Download notifications (notify.py): what is sent, when, and only once."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from astroseeing.download.requests import Area, plan_requests
from astroseeing.manifest import Manifest
from astroseeing.notify import WatchState, check_once, request_fields, snapshot

AREA = Area.around(-24.63, -70.40, half_width_cells=1)
NOW = dt.datetime(2026, 10, 1, 7, 0, tzinfo=dt.UTC)


RECENT = (NOW - dt.timedelta(minutes=10)).isoformat(timespec="seconds")


@pytest.fixture
def m(tmp_path):
    """Three planned requests, last changed 10 minutes before NOW."""
    man = Manifest(tmp_path / "manifest.sqlite")
    for s in plan_requests("sl", "x", dt.date(2023, 1, 1), dt.date(2023, 3, 31), AREA,
                           granularity="month"):  # fmt: skip
        man.add_request(s)
    man.conn.execute("UPDATE requests SET updated_at=?, created_at=?", (RECENT, RECENT))
    man.conn.commit()
    yield man
    man.close()


def set_state(m, rid, state, updated=RECENT, **fields):
    cur = m.conn.execute("SELECT state FROM requests WHERE id=?", (rid,)).fetchone()[0]
    m.transition(rid, [cur], state, **fields)
    m.conn.execute("UPDATE requests SET updated_at=? WHERE id=?", (updated, rid))
    m.conn.commit()


def run(m, state, **kw):
    sent = []
    msgs = check_once(m, state, lambda msg, title, prio: sent.append((title, prio, msg)), NOW,
                      loop_running=kw.pop("loop_running", lambda: True), **kw)  # fmt: skip
    assert len(msgs) == len(sent)
    return sent


def test_request_fields_matches_the_planner():
    for s in plan_requests("pl", "x", dt.date(2023, 1, 1), dt.date(2023, 1, 31), AREA,
                           granularity="month"):  # fmt: skip
        assert request_fields(s.cds_request()) == s.n_fields


def test_finished_is_sent_once(m):
    ids = [r[0] for r in m.conn.execute("SELECT id FROM requests")]
    for rid in ids:
        set_state(m, rid, "ingested")
    st = WatchState(last_daily=NOW.date().isoformat())
    first = run(m, st)
    assert [t for t, _, _ in first] == ["astro-seeing: downloads finished"]
    assert "3 requests" in first[0][2]
    assert run(m, st) == []  # not repeated


def test_failures_are_reported_once_when_retries_are_used_up(m):
    set_state(m, 1, "failed", last_error="cds rejected: cost limits exceeded")
    st = WatchState(last_daily=NOW.date().isoformat())
    assert run(m, st) == []  # 1 attempt of 5: run_boxes.sh will retry it
    assert snapshot(m, NOW).pending == 3  # and it still counts as unfinished
    m.conn.execute("UPDATE requests SET attempts=5 WHERE id=1")
    m.conn.commit()
    sent = run(m, st)
    assert len(sent) == 1 and sent[0][1] == "high" and "cost limits" in sent[0][2]
    assert run(m, st) == []


def test_not_finished_while_a_failed_request_will_be_retried(m):
    for rid in (1, 2):
        set_state(m, rid, "ingested")
    set_state(m, 3, "failed", last_error="timeout")
    st = WatchState(last_daily=NOW.date().isoformat())
    assert run(m, st) == []  # the loop's backoff: nothing pending but a retry to come


def test_stall_and_stopped_loop(m):
    old = (NOW - dt.timedelta(hours=5)).isoformat(timespec="seconds")
    for rid in (1, 2, 3):
        m.conn.execute("UPDATE requests SET updated_at=?, created_at=? WHERE id=?", (old, old, rid))
    m.conn.commit()
    st = WatchState(last_daily=NOW.date().isoformat())
    titles = [t for t, _, _ in run(m, st, loop_running=lambda: False)]
    assert titles == ["astro-seeing: stalled", "astro-seeing: loop stopped"]
    assert run(m, st, loop_running=lambda: False) == []  # re-alerts only after 12 h


def test_retries_without_progress_still_count_as_a_stall(m):
    """A failing request retried every few minutes touches updated_at but isn't progress."""
    old = (NOW - dt.timedelta(hours=5)).isoformat(timespec="seconds")
    m.conn.execute("UPDATE requests SET created_at=?", (old,))
    m.conn.commit()
    set_state(m, 1, "failed", last_error="HTTP 503")  # updated just now (RECENT)
    set_state(m, 1, "planned")  # retried: planned again, also RECENT
    st = WatchState(last_daily=NOW.date().isoformat())
    assert [t for t, _, _ in run(m, st)] == ["astro-seeing: stalled"]


def test_daily_progress_once_per_day_with_eta(m):
    set_state(m, 1, "ingested", cds_started_at=(NOW - dt.timedelta(hours=3)).isoformat(),
              cds_finished_at=(NOW - dt.timedelta(hours=2)).isoformat())  # fmt: skip
    st = WatchState()
    sent = run(m, st)
    assert [t for t, _, _ in sent] == ["astro-seeing: daily progress"]
    assert "1 requests done, 2 pending" in sent[0][2] and "done around" in sent[0][2]
    assert run(m, st) == []
    s = snapshot(m, NOW)
    assert s.fields_done_24h == 12_648 and s.fields_left == 11_424 + 12_648  # Feb + Mar left


def test_eta_uses_the_span_the_work_took_not_a_full_day(m):
    """Regression (2026-09-27): 7 h of work divided by 24 h made the first ETA ~3x too late."""
    t1 = NOW - dt.timedelta(hours=7)
    set_state(m, 1, "ingested", cds_started_at=t1.isoformat(),
              cds_finished_at=(t1 + dt.timedelta(hours=1)).isoformat())  # fmt: skip
    s = snapshot(m, NOW)
    assert s.span_24h_s == 3600.0
    eta = s.eta(NOW)
    # January (12,648 fields) took 1 h, so the 24,072 fields left take ~1.9 h.
    assert abs((eta - NOW).total_seconds() - 3600 * 24_072 / 12_648) < 1


def test_state_round_trip(tmp_path):
    st = WatchState(last_daily="2026-10-01", failed_reported=2, finished_reported=True)
    p = tmp_path / "s.json"
    st.save(p)
    assert WatchState.load(p) == st
    p.write_text("{not json")
    assert WatchState.load(p) == WatchState()
    assert json.loads(json.dumps(st.__dict__))
