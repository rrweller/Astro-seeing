"""The CDS gate (D39): one job at a time, backoff, pause after 3 rejections, bounded resubmits."""

from __future__ import annotations

import datetime as dt

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from astroseeing.download.cds import is_queue_limit_rejection
from astroseeing.download.downloader import Downloader
from astroseeing.download.requests import Area, plan_requests
from astroseeing.manifest import Manifest
from astroseeing.notify import WatchState, check_once

from fakes import Clock, FakeCdsBackend

AREA = Area.around(-24.63, -70.40, half_width_cells=1)
HOURS = (0, 6, 12, 18)
T0 = dt.datetime(2026, 10, 30, 12, 0, tzinfo=dt.UTC)

OLD = (
    "HTTPError: 400 Client Error: Bad Request\nThe job has been rejected\nNumber queued "
    "requests for this dataset is temporarily limited. Please configure your scripts accordingly"
)
NEW = (
    "HTTPError: 400 Client Error: Bad Request\nThe job has been rejected\nMaximum number queued "
    "requests for this dataset has been reached. Please configure your scripts to request data "
    "sequentially"
)


BEHAVIOURS = [None, None, "queue_limit", "queue_limit_new", "reject", "expire", "lost"]


def make(tmp_path, days: int = 4, polls_to_finish: int = 2):
    m = Manifest(tmp_path / "state" / "manifest.sqlite")
    specs = plan_requests(
        "pl", "paranal", dt.date(2023, 6, 1), dt.date(2023, 6, days), AREA, hours=HOURS
    )
    fake = FakeCdsBackend(
        {FakeCdsBackend.req_key(s.cds_request()): s.expected() for s in specs}, polls_to_finish
    )
    for s in specs:
        m.add_request(s)
    clock = Clock(T0)
    dl = Downloader(m, fake, tmp_path / "staging" / "grib", now=clock)
    return m, fake, dl, clock, specs


def key(spec) -> str:
    return FakeCdsBackend.req_key(spec.cds_request())


def test_both_queue_limit_wordings_are_recognised():
    assert is_queue_limit_rejection(OLD) and is_queue_limit_rejection(NEW)
    assert is_queue_limit_rejection(NEW.upper())
    assert not is_queue_limit_rejection("cost limits exceeded")
    assert not is_queue_limit_rejection(None)


def test_more_than_one_job_at_the_cds_is_refused(tmp_path):
    m = Manifest(tmp_path / "manifest.sqlite")
    with pytest.raises(ValueError, match="Riley"):
        Downloader(m, FakeCdsBackend({}), tmp_path / "grib", max_active=2)


def test_next_request_is_submitted_before_the_finished_one_is_downloaded(tmp_path):
    m, fake, dl, clock, _ = make(tmp_path, days=3)
    for _ in range(20):
        dl.step()
        clock.advance(minutes=1)
    assert m.counts() == {"downloaded": 3} and fake.max_in_flight == 1
    # job-1 finishes; job-2 goes in before job-1's result is fetched.
    assert fake.calls[:3] == [("submit", "job-1"), ("submit", "job-2"), ("download", "job-1")]


def test_a_job_already_at_the_cds_blocks_submission(tmp_path):
    """A job left at the CDS (crash, timed-out submit, another process) counts too."""
    _m, fake, dl, _clock, _ = make(tmp_path)
    fake.jobs["stray"] = {"key": "x", "polls": 0, "behaviour": None}
    dl.step()
    assert fake.submits == 0
    fake.jobs["stray"]["terminal"] = True
    dl.step()
    assert fake.submits == 1


def test_no_submission_when_the_cds_job_list_cannot_be_read(tmp_path):
    m, fake, dl, _clock, _ = make(tmp_path)

    def broken():
        raise OSError("connection reset")

    fake.active_jobs = broken
    dl.step()
    assert fake.submits == 0 and m.counts() == {"planned": 4}


@pytest.mark.parametrize("behaviour", ["queue_limit", "queue_limit_new"])
def test_queue_limit_rejection_is_planned_again_after_a_backoff(tmp_path, behaviour):
    m, fake, dl, clock, specs = make(tmp_path, polls_to_finish=1)
    fake.behaviour[key(specs[0])] = behaviour
    dl.step()  # submit job-1
    dl.step()  # rejected: planned again, backoff starts
    req = m.get(1)
    assert req.state == "planned" and req.attempts == 0
    for _ in range(59):
        clock.advance(minutes=1)
        dl.step()
    assert fake.submits == 1  # nothing during the 60 min
    clock.advance(minutes=1, seconds=1)
    dl.step()
    assert fake.submits == 2


def test_backoff_doubles_and_retry_failed_does_not_bypass_it(tmp_path):
    m, fake, dl, clock, specs = make(tmp_path, polls_to_finish=1)
    fake.behaviour[key(specs[0])] = "reject"
    fake.behaviour[key(specs[1])] = "reject"
    dl.step()
    dl.step()  # job-1 rejected → failed, backoff 60 min
    assert m.get(1).state == "failed"
    assert m.retry_failed() == 1  # what run_boxes.sh does every round
    clock.advance(minutes=59)
    dl.step()
    assert fake.submits == 1
    clock.advance(minutes=2)
    dl.step()  # job-2 (request 1 again, still rejected by the fake)
    dl.step()  # second rejection → 120 min
    assert fake.submits == 2
    m.retry_failed()
    clock.advance(minutes=119)
    dl.step()
    assert fake.submits == 2
    clock.advance(minutes=2)
    dl.step()
    assert fake.submits == 3


def test_a_submit_error_counts_as_a_rejection(tmp_path):
    m, fake, dl, _clock, _ = make(tmp_path)
    fake.submit_error = RuntimeError("500 Server Error (something new)")
    s = dl.step()
    assert s.rejected == 1 and m.counts() == {"failed": 1, "planned": 3}
    assert m.get(1).attempts == 1 and "500 Server Error" in m.get(1).last_error
    m.retry_failed()  # replanned, but the backoff still holds
    assert m.rejections_since("2000") and dl.backoff_until() == T0 + dt.timedelta(hours=1)
    dl.step()
    assert fake.submits == 0


def test_three_rejections_in_24h_pause_and_alert(tmp_path):
    m, fake, dl, clock, specs = make(tmp_path)
    for s in specs:
        fake.behaviour[key(s)] = "reject"
    for _ in range(12 * 60):  # 12 h of 1-min steps
        dl.step()
        m.retry_failed()
        clock.advance(minutes=1)
    assert fake.submits == 3 and m.cds_control()["paused_at"]
    assert "3 CDS rejections" in m.cds_control()["pause_reason"]
    clock.advance(days=3)  # the pause doesn't expire by itself
    for _ in range(5):
        dl.step()
        m.retry_failed()
    assert fake.submits == 3

    sent = []
    check_once(m, WatchState(), lambda msg, t, p: sent.append((t, msg)), clock(),
               loop_running=lambda: True)  # fmt: skip
    paused = [msg for t, msg in sent if t == "astro-seeing: CDS paused"]
    assert not [t for t, _ in sent if t == "astro-seeing: stalled"]  # the pause explains it
    assert len(paused) == 1 and "astro cds-resume" in paused[0] and "forum" in paused[0]

    fake.behaviour.clear()
    m.resume_cds("checked the forum", at=clock().isoformat(timespec="seconds"))
    dl.step()
    assert fake.submits == 4  # earlier rejections no longer count


def test_rejections_older_than_24h_do_not_count(tmp_path):
    m, fake, dl, clock, specs = make(tmp_path)
    fake.behaviour[key(specs[0])] = "queue_limit"
    fake.behaviour[key(specs[1])] = "queue_limit"
    fake.behaviour[key(specs[2])] = "queue_limit"
    for _ in range(3):
        while fake.submits == len(m.rejections_since("2000")):
            dl.step()
            clock.advance(minutes=1)
        dl.step()  # the rejection
        clock.advance(hours=13)
    assert not m.cds_control().get("paused_at")


def test_lost_job_resubmission_is_bounded(tmp_path):
    m, fake, dl, clock, specs = make(tmp_path, days=1)
    fake.behaviour[key(specs[0])] = "lost"  # every job for it vanishes (HTTP 404)
    for _ in range(50):
        dl.step()
        clock.advance(minutes=1)
    r = m.get(1)
    assert fake.submits == 3 and r.state == "failed" and "lost at the CDS 3 times" in r.last_error
    m.retry_failed()  # a retry gets one more go, not another two
    for _ in range(20):
        dl.step()
        clock.advance(minutes=1)
    assert fake.submits == 4 and m.get(1).state == "failed"


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    plan=st.lists(
        st.tuples(
            st.sampled_from(BEHAVIOURS),
            st.integers(1, 6),
        ),
        min_size=1,
        max_size=6,
    ),
    poll_errors=st.lists(st.booleans(), min_size=1, max_size=20),
    minutes=st.lists(st.sampled_from([1, 1, 5, 30, 61, 121, 300]), min_size=1, max_size=20),
)
def test_never_more_than_one_job_in_flight(tmp_path_factory, plan, poll_errors, minutes):
    tmp = tmp_path_factory.mktemp("gate")
    m, fake, dl, clock, specs = make(tmp, days=len(plan))
    for s, (b, _) in zip(specs, plan, strict=False):
        if b:
            fake.behaviour[key(s)] = b
    finish = {key(s): n for s, (_, n) in zip(specs, plan, strict=False)}
    submit = fake.submit

    def submit_with_finish(dataset, request):
        rid = submit(dataset, request)
        fake.jobs[rid]["polls_to_finish"] = finish[FakeCdsBackend.req_key(request)]
        return rid

    fake.submit = submit_with_finish
    info = fake.info
    i = 0

    def flaky_info(rid):
        nonlocal i
        i += 1
        if poll_errors[i % len(poll_errors)] and i % 3 == 0:
            raise OSError("poll timeout")
        return info(rid)

    fake.info = flaky_info
    for step in range(200):
        dl.step()
        m.retry_failed()
        clock.advance(minutes=minutes[step % len(minutes)])
        assert len(fake.active_jobs()) <= 1
    assert fake.max_in_flight <= 1
