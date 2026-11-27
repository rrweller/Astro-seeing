"""A fake CDS backend that serves synthetic GRIB files (no network)."""

from __future__ import annotations

import datetime as dt
import itertools
from pathlib import Path
from typing import Any

from astroseeing.config import load_config
from astroseeing.download.cds import RemoteInfo
from astroseeing.provenance import canonical_json
from astroseeing.synthetic import write_synthetic_grib


def era5_param_ids() -> dict[str, int]:
    out: dict[str, int] = {}
    for d in load_config("era5")["datasets"].values():
        for v in {**d["variables"], **d.get("optional_variables", {})}.values():
            out[v["short_name"]] = v["param_id"]
    return out


class FakeCdsBackend:
    """Jobs go accepted → running → successful after ``polls_to_finish`` polls.

    ``behaviour`` maps a request key (canonical JSON of the request) to one of:
    "reject", "queue_limit" / "queue_limit_new" (rejected once with the old or the
    2026-10 wording, then fine), "expire", "lost" (always 404, like D34), "truncate",
    "drop", "duplicate", "shift".

    ``calls`` logs ("submit"|"download", id) in order; ``max_in_flight`` is the most
    jobs ever queued or running at once, as the CDS would count them.
    """

    def __init__(self, expected_by_request: dict[str, dict], polls_to_finish: int = 2):
        self.expected = expected_by_request
        self.polls_to_finish = polls_to_finish
        self.behaviour: dict[str, str] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.ids = (f"job-{i}" for i in itertools.count(1))
        self.submits = 0
        self.deleted: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.max_in_flight = 0
        self.submit_error: Exception | None = None  # raised by the next submit, once

    def active_jobs(self) -> list[str]:
        return [rid for rid, j in self.jobs.items() if not j.get("terminal")]

    @staticmethod
    def req_key(request: dict) -> str:
        return canonical_json(request)

    def submit(self, dataset: str, request: dict[str, Any]) -> str:
        if self.submit_error is not None:
            e, self.submit_error = self.submit_error, None
            raise e
        self.submits += 1
        rid = next(self.ids)
        key = self.req_key(request)
        self.jobs[rid] = {"key": key, "polls": 0, "behaviour": self.behaviour.get(key)}
        self.calls.append(("submit", rid))
        self.max_in_flight = max(self.max_in_flight, len(self.active_jobs()))
        return rid

    def info(self, request_id: str) -> RemoteInfo:
        job = self.jobs[request_id]
        job["polls"] += 1
        if job["behaviour"] == "lost":
            job["terminal"] = True
            return RemoteInfo(status="deleted", error="job not found at the CDS (HTTP 404)")
        if job["polls"] < job.get("polls_to_finish", self.polls_to_finish):
            return RemoteInfo(status="accepted" if job["polls"] == 1 else "running")
        job["terminal"] = True
        if job["behaviour"] == "reject":
            return RemoteInfo(status="rejected", error="cost limits exceeded (fake)")
        if job["behaviour"] == "queue_limit":
            job["behaviour"] = None  # the resubmitted job will succeed
            self.behaviour.pop(job["key"], None)
            return RemoteInfo(
                status="rejected",
                error="HTTPError: 400 Client Error: Bad Request\nThe job has been rejected\n"
                "Number queued requests for this dataset is temporarily limited. Please "
                "configure your scripts accordingly",
            )
        if job["behaviour"] == "queue_limit_new":
            job["behaviour"] = None
            self.behaviour.pop(job["key"], None)
            return RemoteInfo(
                status="rejected",
                error="HTTPError: 400 Client Error: Bad Request\nThe job has been rejected\n"
                "Maximum number queued requests for this dataset has been reached. Please "
                "configure your scripts to request data sequentially",
            )
        if job["behaviour"] == "expire":
            job["behaviour"] = None  # the resubmitted job will succeed
            self.behaviour.pop(job["key"], None)
            return RemoteInfo(status="dismissed")
        return RemoteInfo(
            status="successful", started_at="2026-09-27T00:00:00", finished_at="2026-09-27T00:01:00"
        )

    def download(self, request_id: str, target: Path) -> int:
        job = self.jobs[request_id]
        self.calls.append(("download", request_id))
        b = job["behaviour"]
        kwargs = {"drop": 1} if b == "drop" else {"duplicate": 1} if b == "duplicate" else {}
        if b == "shift":
            kwargs = {"shift_grid_deg": 0.25}
        write_synthetic_grib(target, self.expected[job["key"]], era5_param_ids(), **kwargs)
        size = Path(target).stat().st_size
        if b == "truncate":
            with open(target, "r+b") as f:
                f.truncate(size // 2)
            raise OSError("Download failed: downloaded fewer bytes than the server's size (fake)")
        return size

    def delete(self, request_id: str) -> None:
        self.deleted.append(request_id)


class Clock:
    """A settable clock for the downloader (``now=``), so tests can step past backoffs."""

    def __init__(self, t: dt.datetime = dt.datetime(2026, 10, 30, tzinfo=dt.UTC)):
        self.t = t

    def __call__(self) -> dt.datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += dt.timedelta(**kw)


# --- the CDS time-series product (D62) -----------------------------------------------

#: What a fake time-series job returns, keyed by request (canonical JSON):
#: "partial" (the data stop at the end of June of the first year), "nan" (3 NaN
#: values), "gap" (one hour missing), "wrong_point" (a neighbouring grid point),
#: "lost" (the CDS forgets the job, HTTP 404, every time), "lost_once" (once),
#: "reject" (the CDS rejects it), "bare" (a bare NetCDF file instead of a zip).
TS_BEHAVIOURS = ("partial", "nan", "gap", "wrong_point", "lost", "lost_once", "reject", "bare")


def write_point_netcdf(
    path: Path,
    *,
    short_name: str,
    lon: float,
    lat: float,
    start: dt.date,
    end: dt.date,
    units: str = "Pa",
    zipped: bool = True,
    behaviour: str | None = None,
    lon_0_360: bool = False,
) -> None:
    """A file shaped like the time-series product's NetCDF: ``<var>(valid_time)``.

    ``latitude`` and ``longitude`` are scalar coordinates, as in the earthkit tutorial
    for this product; the CDS sends a zip holding one NetCDF4 file (RESEARCH §7).
    """
    import zipfile

    import numpy as np
    import xarray as xr

    t0 = np.datetime64(start.isoformat(), "h")
    t1 = np.datetime64((end + dt.timedelta(days=1)).isoformat(), "h")
    if behaviour == "partial":
        t1 = np.datetime64(f"{start.year}-07-01", "h")
    times = np.arange(t0, t1, np.timedelta64(1, "h")).astype("datetime64[ns]")
    if behaviour == "gap":
        times = np.delete(times, 100)
    hours = np.arange(times.size)
    values = (74300.0 + 80.0 * np.sin(2 * np.pi * hours / 24)).astype("float32")
    if behaviour == "nan":
        values[[5, 6, 2000 % values.size]] = np.nan
    if behaviour == "wrong_point":
        lon += 0.25
    if lon_0_360:
        lon %= 360.0
    ds = xr.Dataset(
        {short_name: ("valid_time", values, {"units": units})},
        coords={"valid_time": times, "latitude": lat, "longitude": lon},
    )
    path = Path(path)
    if not zipped or behaviour == "bare":
        ds.to_netcdf(path, engine="netcdf4", format="NETCDF4")
        return
    inner = path.with_name(path.name + ".inner.nc")
    ds.to_netcdf(inner, engine="netcdf4", format="NETCDF4")
    with zipfile.ZipFile(path, "w") as z:
        z.write(inner, "reanalysis-era5-single-levels-timeseries-fake.nc")
    inner.unlink()


#: CDS variable name → NetCDF short name, for the fake time-series files.
TS_SHORT_NAMES = {"surface_pressure": "sp", "2m_temperature": "t2m"}


class FakeTimeseriesBackend:
    """The CDS time-series product, offline. Jobs finish after ``polls_to_finish`` polls.

    ``behaviour`` maps a request key (canonical JSON of the request) to one of
    ``TS_BEHAVIOURS``. ``other_jobs`` holds (job id, dataset) pairs queued at the CDS by
    someone else. ``max_in_flight`` is the most time-series jobs ever at the CDS at once.
    """

    def __init__(self, polls_to_finish: int = 2):
        self.polls_to_finish = polls_to_finish
        self.behaviour: dict[str, str] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.ids = (f"ts-job-{i}" for i in itertools.count(1))
        self.submitted: list[tuple[str, dict]] = []  # (dataset, request) in order
        self.deleted: list[str] = []
        self.other_jobs: list[tuple[str, str | None]] = []
        self.max_in_flight = 0
        self.list_error: Exception | None = None

    @staticmethod
    def req_key(request: dict) -> str:
        return canonical_json(request)

    def _in_flight(self) -> list[str]:
        return [rid for rid, j in self.jobs.items() if not j.get("terminal")]

    def active_timeseries_jobs(self) -> list[str]:
        if self.list_error is not None:
            raise self.list_error
        return self._in_flight() + [rid for rid, _ in self.other_jobs]

    def submit(self, dataset: str, request: dict[str, Any]) -> str:
        rid = next(self.ids)
        key = self.req_key(request)
        b = self.behaviour.get(key)
        if b == "lost_once":
            self.behaviour.pop(key)
            b = "lost"
        self.jobs[rid] = {"key": key, "request": request, "polls": 0, "behaviour": b}
        self.submitted.append((dataset, request))
        self.max_in_flight = max(self.max_in_flight, len(self._in_flight()))
        return rid

    def info(self, request_id: str) -> RemoteInfo:
        job = self.jobs[request_id]
        job["polls"] += 1
        if job["behaviour"] == "lost":
            job["terminal"] = True
            return RemoteInfo(status="deleted", error="job not found at the CDS (HTTP 404)")
        if job["polls"] < self.polls_to_finish:
            return RemoteInfo(status="accepted" if job["polls"] == 1 else "running")
        job["terminal"] = True
        if job["behaviour"] == "reject":
            return RemoteInfo(status="rejected", error="request too large (fake)")
        return RemoteInfo(status="successful", finished_at="2026-11-27T00:00:05")

    def download(self, request_id: str, target: Path) -> int:
        job = self.jobs[request_id]
        req = job["request"]
        start, end = (dt.date.fromisoformat(d) for d in req["date"][0].split("/"))
        write_point_netcdf(
            target,
            short_name=TS_SHORT_NAMES[req["variable"][0]],
            lon=req["location"]["longitude"],
            lat=req["location"]["latitude"],
            start=start,
            end=end,
            behaviour=job["behaviour"],
        )
        return Path(target).stat().st_size

    def delete(self, request_id: str) -> None:
        self.deleted.append(request_id)
