"""``astro`` command line: plan, download, verify, ingest, clean up, report.

Every command reads paths from the environment (see ``astroseeing.paths``) and
logs to ``logs/astro-YYYYMMDD.log`` as well as stderr.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from pathlib import Path

from astroseeing.config import load_config
from astroseeing.paths import Paths
from astroseeing.provenance import REPO_ROOT, git_state, software_versions

log = logging.getLogger("astro")


def log_dir() -> Path:
    """``$ASTRO_LOG_DIR``, else ``logs/`` in the repo checkout, else the state directory."""
    env = os.environ.get("ASTRO_LOG_DIR")
    if env:
        return Path(env)
    if (REPO_ROOT / "pyproject.toml").is_file():
        return REPO_ROOT / "logs"
    return Paths.from_env().state_dir / "logs"


def _setup_logging(verbose: bool) -> None:
    logs = log_dir()
    logs.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)sZ %(levelname)s %(name)s: %(message)s"
    logging.Formatter.converter = time.gmtime
    handlers = [
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(logs / f"astro-{dt.datetime.now(dt.UTC):%Y%m%d}.log"),
    ]
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO, format=fmt, handlers=handlers
    )


def _manifest(paths: Paths):
    from astroseeing.manifest import Manifest

    return Manifest(paths.manifest)


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def cmd_status(args, paths: Paths) -> int:
    m = _manifest(paths)
    print(json.dumps({"manifest": str(paths.manifest), "counts": m.counts()}, indent=2))
    ctl = m.cds_control()
    if ctl.get("paused_at"):
        print(f"CDS SUBMISSIONS PAUSED since {ctl['paused_at']}: {ctl['pause_reason']}")
        print("  check the ECMWF forum and the log, then `astro cds-resume --reason ...` (D39)")
    since = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=24)).isoformat(timespec="seconds")
    if rej := m.rejections_since(since):
        print(f"CDS rejections in the last 24 h (since the last resume): {len(rej)}, "
              f"last at {rej[-1]}")  # fmt: skip
    for r in m.by_state("failed"):
        print(f"FAILED {r.key} (attempts {r.attempts}): {r.last_error}")
    return 0


def cmd_plan_box(args, paths: Paths) -> int:
    from astroseeing.download.requests import Area, plan_requests, static_request

    area = Area.around(args.lat, args.lon, args.half_width, load_config("era5")["grid_deg"])
    hours = tuple(int(h) for h in args.hours.split(",")) if args.hours else tuple(range(24))
    m = _manifest(paths)
    n = 0
    for kind in args.kinds.split(","):
        if kind == "static":
            specs = [static_request(args.region, area)]
        else:
            specs = plan_requests(
                kind,
                args.region,
                _date(args.start),
                _date(args.end),
                area,
                granularity=args.granularity,
                hours=hours,
            )
        for s in specs:
            m.add_request(s)
            n += 1
    log.info("planned %d requests for %s, area %s", n, args.region, area.as_cds())
    return 0


def _backend():
    from astroseeing.download.cds import DatastoresBackend

    return DatastoresBackend()


def cmd_download(args, paths: Paths) -> int:
    from astroseeing.download.downloader import Downloader

    dl = Downloader(_manifest(paths), _backend(), paths.grib_dir, max_active=args.max_active)
    max_s = args.max_hours * 3600 if args.max_hours else None
    s = dl.run(poll_seconds=args.poll, max_seconds=max_s)
    log.info("download finished: %s", s)
    if s.paused:
        log.error("CDS submissions are paused (D39); see `astro status`")
        return 3
    if s.backoff_until:
        log.warning("CDS backoff after a rejection: nothing submitted until %s (D39)",
                    s.backoff_until.isoformat(timespec="seconds"))  # fmt: skip
    if s.failed or s.rejected:
        log.error("%d request(s) failed and %d submission(s) were rejected in this run; see "
                  "`astro status`", s.failed, s.rejected)  # fmt: skip
        return 1
    return 0


def cmd_cds_resume(args, paths: Paths) -> int:
    m = _manifest(paths)
    if not m.cds_control().get("paused_at"):
        log.info("CDS submissions were not paused; recording the resume anyway")
    m.resume_cds(args.reason)
    log.info("CDS submissions allowed again; earlier rejections no longer count (D39)")
    return 0


def cmd_verify(args, paths: Paths) -> int:
    from astroseeing.ingest.pipeline import verify_pending

    out = verify_pending(_manifest(paths))
    log.info("verify: %s", out)
    return 1 if out["failed"] else 0


def cmd_ingest(args, paths: Paths) -> int:
    from astroseeing.download.areas import mask_fn
    from astroseeing.ingest.pipeline import ingest_pending

    # Validation boxes keep the grid layout; declared validation areas store only their
    # site boxes (cells layout, D31); anything else large is refused (D18).
    cfg = {"era5": load_config("era5"), "validation_areas": load_config("validation_areas")}
    out = ingest_pending(_manifest(paths), paths.data_root, cfg, mask_fn=mask_fn)
    log.info("ingest: %s", out)
    return 1 if out["failed"] or out["refused_unmasked"] else 0


def cmd_cleanup_raw(args, paths: Paths) -> int:
    from astroseeing.download.areas import mask_fn
    from astroseeing.ingest.pipeline import cleanup_raw

    out = cleanup_raw(_manifest(paths), paths.staging, mask_fn=mask_fn)
    log.info("cleanup: %s", out)
    return 1 if out["failed"] or out["skipped"] else 0


def cmd_archive_raw(args, paths: Paths) -> int:
    """Kept raw GRIB from /staging to the write-once archive on the NAS (D55 item 7, D64)."""
    from astroseeing.download.areas import mask_fn
    from astroseeing.rawarchive import (
        ArchiveSettings,
        IngestStoreCheck,
        PlanRefused,
        archive_raw,
        format_plan,
        plan_archive,
        run_lock,
    )

    settings = ArchiveSettings.from_config(paths.data_root)
    m = _manifest(paths)
    if args.dry_run:
        plan = plan_archive(m, paths.staging, settings)
        print(format_plan(plan, settings, args.delete_measured, files=args.files))
        return 0
    try:
        with run_lock(paths.state_dir):
            # D12: each store is checked against its GRIB (with the ingest's mask, as
            # `cleanup-raw` does) right before the /staging copy goes.
            s = archive_raw(
                m,
                paths.staging,
                settings,
                store_check=IngestStoreCheck(m, mask_fn),
                delete_measured=args.delete_measured,
                max_copy_gb=args.max_gb,
            )
    except PlanRefused as e:
        log.error("archive-raw refused: %s", e)
        return 2
    log.info(
        "archive-raw: %d copied (%.2f GB), %d already there, %d /staging copies deleted, "
        "%d recovered, %d measurement(s) kept on /staging, %d refused, %d failed",
        s.copied, s.copied_bytes / 1e9, s.present, s.staging_deleted, s.recovered,
        s.measured_kept, s.refused, s.failed,
    )  # fmt: skip
    if s.stale_temps:
        log.warning("%d temp file(s) on the NAS to remove by hand (listed above)",
                    len(s.stale_temps))  # fmt: skip
    for p in s.problems:
        log.error("  %s", p)
    if s.hung:
        log.error("stopped: the NAS stopped answering (%s); run again once it answers", s.hung)
        return 3
    return 0 if s.ok else 1


def cmd_retry_failed(args, paths: Paths) -> int:
    log.info(
        "moved %d failed requests back to planned", _manifest(paths).retry_failed(args.max_attempts)
    )
    return 0


def cmd_cancel(args, paths: Paths) -> int:
    n = _manifest(paths).cancel(args.prefix, args.reason)
    log.info("cancelled %d planned/held requests with keys starting %r", n, args.prefix)
    return 0


def _parse_variables(kind: str, spec: str) -> tuple[str, ...] | None:
    if not spec:
        return None
    ds = load_config("era5")["datasets"][kind]
    allvars = {**ds["variables"], **ds.get("optional_variables", {})}
    by_short = {v["short_name"]: name for name, v in allvars.items()}
    out = []
    for v in spec.split(","):
        name = by_short.get(v, v)
        if name not in allvars:
            raise SystemExit(f"unknown {kind} variable {v!r}")
        out.append(name)
    return tuple(out)


def _subset_region(region: str, kind: str, variables: tuple[str, ...] | None) -> str:
    """``chile@vars-lcc-zust`` for a subset of a kind's default variables (D40).

    Like ``@every4d``, the suffix keeps keys and stores of a subset apart from full ones.
    """
    ds = load_config("era5")["datasets"][kind]
    if variables is None or set(variables) == set(ds["variables"]):
        return region
    allvars = {**ds["variables"], **ds.get("optional_variables", {})}
    return f"{region}@vars-" + "-".join(allvars[v]["short_name"] for v in variables)


def cmd_plan_area(args, paths: Paths) -> int:
    """Plan downloads for a validation area (configs/validation_areas.yaml, D31)."""
    from astroseeing.download.areas import load_areas
    from astroseeing.download.requests import plan_requests, static_request

    areas = load_areas()
    if args.name not in areas:
        raise SystemExit(f"unknown area {args.name!r}; known: {sorted(areas)}")
    area = areas[args.name]
    if args.hours == "all":
        hours = tuple(range(24))
    elif args.hours == "night":
        hours = area.night_hours()
    else:
        hours = tuple(int(h) for h in args.hours.split(","))
    cfg_pl = load_config("era5")["datasets"]["pl"]
    levels = {"29": None, "37": tuple(cfg_pl["levels_hpa_all"])}.get(args.levels)
    if levels is None and args.levels not in ("29",):
        levels = tuple(int(x) for x in args.levels.split(","))
    region = args.name + (f"@every{args.day_step}d" if args.day_step > 1 else "")
    kinds = args.kinds.split(",")
    # Check every kind's variables before planning anything, so a bad name never
    # leaves a partial plan behind (D40).
    variables = {k: _parse_variables(k, args.variables) for k in kinds if k != "static"}
    specs = []
    for kind in kinds:
        if kind == "static":
            specs.append(static_request(region, area.area))
            continue
        specs += plan_requests(
            kind,
            _subset_region(region, kind, variables[kind]),
            _date(args.start),
            _date(args.end),
            area.area,
            granularity="month",
            variables=variables[kind],
            levels=levels if kind == "pl" else None,
            hours=hours,
            day_step=args.day_step,
        )
    m = _manifest(paths)
    for spec in specs:  # a key already used by a different request: refuse before adding
        row = m.conn.execute(
            "SELECT request_hash FROM requests WHERE key=?", (spec.key,)
        ).fetchone()
        if row is not None and row["request_hash"] != spec.request_hash():
            raise SystemExit(f"{spec.key} is already planned as a different request; nothing added")
    total_fields = n = 0
    for spec in specs:
        m.add_request(spec)
        total_fields += spec.n_fields
        n += 1
    rate = load_config("era5")["request"]["fields_per_s"]  # measured, one job at a time (D40)
    log.info(
        "planned %d requests for area %s (%s; UTC hours %s): %.2f M fields, ~%.1f days of CDS "
        "processing at %.1f fields/s (measured on pressure levels, one job at a time)",
        n, region, area.area.as_cds(), ",".join(map(str, hours)), total_fields / 1e6,
        total_fields / rate / 86400, rate,
    )  # fmt: skip
    return 0


def cmd_plan_measure(args, paths: Paths) -> int:
    """One-off CDS test request (ticket #10): downloaded and verified, never ingested."""
    from astroseeing.download.requests import Area, measurement_request

    area = None
    if args.area:
        n, w, s, e = (float(x) for x in args.area.split(","))
        area = Area(n, w, s, e)
    levels = None
    if args.kind == "pl" and args.levels != "29":
        cfg_pl = load_config("era5")["datasets"]["pl"]
        levels = (
            tuple(cfg_pl["levels_hpa_all"])
            if args.levels == "37"
            else tuple(int(x) for x in args.levels.split(","))
        )
    try:
        spec = measurement_request(
            args.kind,
            _date(args.date),
            tuple(int(h) for h in args.hours.split(",")),
            area=area,
            variables=_parse_variables(args.kind, args.variables),
            levels=levels,
            label=args.label,
        )
    except ValueError as e:
        raise SystemExit(str(e)) from e
    m = _manifest(paths)
    rid = m.add_request(spec)
    if (state := m.get(rid).state) != "planned":
        log.warning("%s already exists (id %d, state %s); nothing new planned. Use another "
                    "--label or --date to measure again", spec.key, rid, state)  # fmt: skip
        return 0
    log.info(
        "planned measurement %s (id %d): %d fields, area %s; it is submitted in turn with the "
        "other planned requests, one CDS job at a time (D39), and never ingested",
        spec.key, rid, spec.n_fields, area.as_cds() if area else "global",
    )  # fmt: skip
    return 0


def cmd_requeue_refused(args, paths: Paths) -> int:
    n = _manifest(paths).requeue_refused(args.prefix)
    log.info("requeued %d refused requests with keys starting %r", n, args.prefix)
    return 0


def cmd_hold(args, paths: Paths) -> int:
    n = _manifest(paths).hold(args.prefix)
    log.info("held %d planned requests with keys starting %r", n, args.prefix)
    return 0


def cmd_release(args, paths: Paths) -> int:
    n = _manifest(paths).release(args.prefix)
    log.info("released %d held requests with keys starting %r", n, args.prefix)
    return 0


def cmd_notify(args, paths: Paths) -> int:
    from astroseeing.notify import ntfy_url, send_ntfy

    send_ntfy(ntfy_url(), args.message, title=args.title)
    log.info("notification sent")
    return 0


def cmd_notify_watch(args, paths: Paths) -> int:
    from astroseeing.notify import watch

    log.info("watching downloads; checking every %.0f s", args.interval)
    watch(
        paths,
        interval_s=args.interval,
        stall_hours=args.stall_hours,
        daily_hour_utc=args.daily_hour_utc,
    )
    return 0


def cmd_export_manifest(args, paths: Paths) -> int:
    from astroseeing.paths import probe_responsive

    # A hung NFS mount blocks in uninterruptible I/O, which no timeout can stop: check
    # the NAS answers (in a child process with a timeout) before writing to it.
    probe_responsive(paths.data_root, timeout_s=60)
    out = _manifest(paths).export(paths.manifest_exports)
    log.info("exported manifest to %s", out)
    return 0


DEFAULT_LANDMASK_SUMMARY = str(REPO_ROOT / "reports" / "landmask_summary.json")


def validation_sites() -> dict[str, tuple[float, float]]:
    """``group/site`` → (lat, lon) for every site in configs/sites.yaml."""
    return {
        f"{group}/{name}": (float(s["lat"]), float(s["lon"]))
        for group, sites in load_config("sites").items()
        for name, s in sites.items()
    }


def cmd_build_landmask(args, paths: Paths) -> int:
    """Land plus 1 km buffer at 30″ and the ERA5 cells kept (AGENTS.md "Coverage"; D20, D22)."""
    from astroseeing.paths import probe_responsive
    from astroseeing.terrain import landmask as lm

    cfg = load_config("landmask")
    mask = lm.build(buffer_m=cfg["buffer_m"], grid_deg=cfg["grid_deg"], measure=cfg["measure"])
    summary = mask.summary(validation_sites())
    mask.qc.log(log, context="landmask ")
    sites = summary["sites"]
    # A site on GLOBE land must lie in a kept cell (else the aggregation is wrong);
    # a site whose listed coordinates are at sea is a finding about the coordinates.
    inconsistent = [n for n, s in sites.items() if s["globe_land"] and not s["era5_cell_kept"]]
    at_sea = [n for n, s in sites.items() if not s["globe_land"]]
    summary_out = args.summary_out or (None if args.dry_run else DEFAULT_LANDMASK_SUMMARY)
    if summary_out:
        p = Path(summary_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "sites"}, indent=2))
    if at_sea:
        log.warning("validation sites not on GLOBE land (check their coordinates): %s", at_sea)
    if inconsistent:
        log.error("sites on land outside the kept cells: %s; not writing", inconsistent)
        return 1
    if args.dry_run:
        return 0
    probe_responsive(paths.data_root)
    out_dir = paths.data_root / cfg["store_dir"]
    for key, res in lm.write_stores(mask, out_dir, cfg["stores"], summary).items():
        state = "already present (identical)" if res.already_present else "written"
        log.info("landmask %s: %s %s (sha256 %s)", key, res.path, state, res.content_sha256)
    return 0


def cmd_fetch_sp(args, paths: Paths) -> int:
    """Surface pressure at the Haslebacher sites from the CDS time-series product (D62)."""
    from astroseeing.download.timeseries import (
        PlanConflict,
        PointFetchConfig,
        PointFetcher,
        site_points,
    )
    from astroseeing.paths import probe_responsive

    cfg = PointFetchConfig.from_config()
    m = _manifest(paths)
    if args.status:
        return _print_ts_status(m)
    points = site_points(cfg.sites)
    if args.sites:
        wanted = args.sites.split(",")
        unknown = sorted(set(wanted) - {p.site for p in points})
        if unknown:
            log.error("not in %s: %s (known: %s)", cfg.sites, ", ".join(unknown),
                      ", ".join(p.site for p in points))  # fmt: skip
            return 2
        points = [p for p in points if p.site in wanted]
    probe_responsive(paths.data_root)
    fetcher = PointFetcher(m, _backend(), paths.staging, paths.data_root / cfg.store_dir)
    try:
        fetcher.plan(cfg, points, chunk_years=args.chunk_years, replan=args.replan)
    except PlanConflict as e:
        log.error("%s", e)
        return 2
    if args.retry_failed:
        log.info("%d failed chunk(s) planned again", fetcher.retry_failed())
    if args.plan_only:
        return _print_ts_status(m)
    max_s = args.max_hours * 3600 if args.max_hours else None
    s = fetcher.run(poll_seconds=args.poll, max_seconds=max_s)
    log.info("fetch-sp finished: %s", s)
    _print_ts_status(m)
    if s.paused:
        log.error("CDS submissions are paused (D39); see `astro status`")
        return 3
    if s.failed or s.rejected or s.store_errors:
        log.error(
            "%d chunk(s) failed, %d rejected, %d store(s) not written; see `astro fetch-sp "
            "--status`", s.failed, s.rejected, len(s.store_errors),
        )  # fmt: skip
        return 1
    if s.left.get("planned") or s.left.get("submitted"):
        log.warning("time ran out with chunks left; run the command again to continue")
        return 2
    return 0


def _print_ts_status(m) -> int:
    from astroseeing.download.timeseries import TimeseriesRecords

    rec = TimeseriesRecords(m)
    out = {
        "counts": rec.counts(),
        "failed": [
            {"key": r.key, "attempts": r.attempts, "error": r.last_error}
            for r in rec.by_state("failed")
        ],
        "stores": [
            {
                k: s[k]
                for k in ("site", "short_name", "start_date", "end_date", "path", "content_sha256")
            }
            for s in rec.stores()
        ],
    }
    print(json.dumps(out, indent=2))
    return 0


def cmd_cds_smoke_test(args, paths: Paths) -> int:
    """Phase 1 step 2: one hour, small box, GRIB; record queue time, throughput, limits."""
    from astroseeing.download.downloader import Downloader
    from astroseeing.download.requests import Area, RequestSpec, plan_requests
    from astroseeing.ingest.pipeline import verify_pending

    backend = _backend()
    report: dict = {
        "started_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git": git_state(),
        "software": software_versions(),
    }
    try:
        auth = backend.check_authentication()
        report["authentication"] = {"ok": True, "user_fields": sorted(auth)}  # never the key
    except Exception as e:
        report["authentication"] = {"ok": False, "error": str(e)}
        _write_report(args.out, report)
        log.error("authentication failed: %s — [ASK] Riley (token or licences)", e)
        return 2
    try:
        report["accepted_licences"] = sorted(
            f"{lic.get('id')} (revision {lic.get('revision')})"
            for lic in backend.client.get_accepted_licences()
        )
    except Exception as e:  # informational; the requests below are the real test
        report["accepted_licences"] = {"error": str(e)}

    area = Area.around(-24.63, -70.40, 2)  # 5×5 points at Paranal
    day = _date(args.date)
    region = f"smoke-{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%S}"
    specs = [
        *plan_requests("pl", region, day, day, area, hours=(0,)),
        *plan_requests("sl", region, day, day, area, hours=(0,)),
    ]
    m = _manifest(paths)
    ids = [m.add_request(s) for s in specs]
    dl = Downloader(m, backend, paths.grib_dir)  # one at a time (D39)
    t0 = time.monotonic()
    summary = dl.run(poll_seconds=args.poll, max_seconds=args.timeout_hours * 3600)
    report["download"] = summary.__dict__
    report["wall_seconds"] = round(time.monotonic() - t0, 1)
    report["verify"] = verify_pending(m)
    report["requests"] = []
    for rid in ids:
        row = m.conn.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
        f = m.current_file(rid)
        entry = {
            k: row[k]
            for k in (
                "key",
                "state",
                "cds_request_id",
                "submitted_at",
                "cds_started_at",
                "cds_finished_at",
                "last_error",
            )
        }
        if f is not None:
            entry.update(
                size_bytes=f["size"], download_seconds=f["download_seconds"], sha256=f["sha256"]
            )
            if f["download_seconds"]:
                entry["throughput_MB_s"] = round(f["size"] / 1e6 / f["download_seconds"], 3)
        report["requests"].append(entry)

    # Request-size limits: ask the CDS what one global day would cost (no download).
    report["cost_estimates"] = {}
    for kind in ("pl", "sl"):
        spec = RequestSpec(
            kind=kind,
            region="global",
            dates=(day,),
            area=None,
            variables=tuple(load_config("era5")["datasets"][kind]["variables"]),
            levels=tuple(load_config("era5")["datasets"]["pl"]["levels_hpa"])
            if kind == "pl"
            else None,
        )
        try:
            report["cost_estimates"][f"{kind}_global_day"] = backend.client.estimate_costs(
                spec.dataset, spec.cds_request()
            )
        except Exception as e:
            report["cost_estimates"][f"{kind}_global_day"] = {"error": str(e)}
    # Month-sized validation-box requests (D16): is a 31-day 5×5 box within the limits,
    # and is each chunk of the split plan (D23)?
    jan = (dt.date(2023, 1, 1), dt.date(2023, 1, 31))
    for kind in ("pl", "sl"):
        whole = plan_requests(kind, "box", *jan, area, granularity="month", split=False)
        chunks = plan_requests(kind, "box", *jan, area, granularity="month")
        for name, specs_ in ((f"{kind}_box_month", whole), (f"{kind}_box_month_split", chunks)):
            try:
                est = [backend.client.estimate_costs(s.dataset, s.cds_request()) for s in specs_]
                report["cost_estimates"][name] = est[0] if len(est) == 1 else est
            except Exception as e:
                report["cost_estimates"][name] = {"error": str(e)}
    states = {r["key"]: r["state"] for r in report["requests"]}
    not_verified = {k: v for k, v in states.items() if v != "verified"}
    report["ok"] = not not_verified
    _write_report(args.out, report)
    log.info("smoke test report written to %s", args.out)
    if not_verified:
        log.error("smoke test incomplete; requests not verified: %s", not_verified)
        return 1
    return 0


def _write_report(path: str, report: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2, default=str) + "\n")


def cmd_forecast_place_height(args, paths: Paths) -> int:
    from astroseeing.forecast.http import HttpClient
    from astroseeing.forecast.places import PlaceHeightError, set_place_height
    from astroseeing.forecast.settings import default_settings_path

    settings = Path(args.settings) if args.settings else default_settings_path()
    try:
        r = set_place_height(settings, args.place, http=HttpClient(), work_dir=paths.tmp_dir,
                             dem_url=args.dem_url)  # fmt: skip
    except PlaceHeightError as e:
        print(f"place-height {args.place}: FAILED, nothing written: {e}", file=sys.stderr)
        return 1
    f, p = r.lookup, r.lookup.posting
    print(f"{r.place}: {f.metres:.2f} m (GLO-30, posting row {p.row} col {p.col} at "
          f"{p.lat:.6f}, {p.lon:.6f} in {f.tile}, sha256 {f.sha256})")  # fmt: skip
    if r.published_difference_m is not None:
        print(f"{r.place}: minus the published {r.published_height_m:g} m = "
              f"{r.published_difference_m:+.1f} m{'  FLAG' if r.flagged else ''}")  # fmt: skip
    print(f"written to {settings}")
    return 0


def cmd_forecast_tick(args, paths: Paths) -> int:
    """One forecast tick (F1 spec Module 8): what's new is fetched, stored and published."""
    from astroseeing.forecast.http import HttpClient
    from astroseeing.forecast.places import PlaceHeightMissing, require_looked_up_heights
    from astroseeing.forecast.settings import load_settings
    from astroseeing.forecast.tick import BuildInfo, ForecastPaths, default_adapters, tick
    from astroseeing.solar.sun import load_ephemeris

    settings = load_settings(Path(args.settings) if args.settings else None)
    try:
        require_looked_up_heights(settings)  # refuse before touching the network (#54)
    except PlaceHeightMissing as e:
        print(f"forecast tick: refused: {e}", file=sys.stderr)
        return 1
    from astroseeing.forecast.alerts import phone_notifier

    manifest = _manifest(paths)
    try:
        report = tick(dt.datetime.now(dt.UTC), settings,
                      default_adapters(settings, HttpClient()), manifest,
                      ForecastPaths.from_paths(paths), ephemeris=load_ephemeris(),
                      build=BuildInfo.current(), http=HttpClient(),
                      notify=phone_notifier())  # fmt: skip
    finally:
        manifest.close()
    print(json.dumps(report.as_dict(), indent=2))
    return 1 if any(r["state"] == "failed" for r in report.runs) else 0  # locked: 0


def _utc(text: str) -> dt.datetime:
    """An ISO time (``Z`` or an offset; naive means UTC), for ``--now`` and ranges."""
    t = dt.datetime.fromisoformat(text)
    return t.replace(tzinfo=dt.UTC) if t.tzinfo is None else t.astimezone(dt.UTC)


def cmd_forecast_status(args, paths: Paths) -> int:
    """Each forecast model's latest runs and the last tick (read only; ticket #60)."""
    from astroseeing.forecast.report import (
        ManifestMissing,
        ReadOnlyManifest,
        forecast_status,
        format_status,
    )
    from astroseeing.forecast.settings import load_settings

    settings = load_settings(Path(args.settings) if args.settings else None)
    try:
        with ReadOnlyManifest(paths.manifest) as m:
            status = forecast_status(m, settings, args.now or dt.datetime.now(dt.UTC), args.runs)
    except ManifestMissing as e:
        print(f"forecast status: {e}", file=sys.stderr)
        return 1
    print(format_status(status), end="")
    return 0


def cmd_forecast_size_report(args, paths: Paths) -> int:
    """The measured-size report over the last 7 days or a range (read only; ticket #60)."""
    from astroseeing.forecast.report import (
        ManifestMissing,
        ReadOnlyManifest,
        render_size_report,
        size_report,
    )
    from astroseeing.forecast.settings import load_settings
    from astroseeing.forecast.store import write_atomic
    from astroseeing.forecast.tick import ForecastPaths

    settings = load_settings(Path(args.settings) if args.settings else None)
    now = args.now or dt.datetime.now(dt.UTC)
    end = args.end or now
    start = args.start or end - dt.timedelta(days=7)
    state = git_state()
    commit = f"{state['commit'] or 'unknown'}{' (dirty)' if state['dirty'] else ''}"
    try:
        with ReadOnlyManifest(paths.manifest) as m:
            fp = ForecastPaths.from_paths(paths)
            rep = size_report(m, settings, fp.place_days, fp.products, start, end, now, commit)
    except ManifestMissing as e:
        print(f"forecast size-report: {e}", file=sys.stderr)
        return 1
    text = render_size_report(rep)
    out = Path(args.out) if args.out else (
        REPO_ROOT / "reports" / f"forecast_sizes_{start:%Y%m%d}-{end:%Y%m%d}.md"
    )  # fmt: skip
    write_atomic(out, text.encode())
    print(text)
    print(f"written to {out}")
    return 0


def cmd_web_deploy(args, paths: Paths) -> int:
    """Put this checkout's committed ``web/`` live, or switch back (F1 spec Module 11)."""
    from astroseeing.forecast.deploy import DeployError, deploy, rollback
    from astroseeing.forecast.tick import ForecastPaths

    site, now = ForecastPaths.from_paths(paths).site, dt.datetime.now(dt.UTC)
    try:
        r = rollback(site, now=now) if args.rollback else deploy(REPO_ROOT, site, now=now)
    except DeployError as e:
        print(f"web deploy: refused, the live page is unchanged: {e}", file=sys.stderr)
        return 1
    what = "rolled back to" if args.rollback else ("live" if r.changed else "already live")
    print(f"{what}: {r.commit} (was {r.previous or 'nothing'}); {site / 'current'}")
    return 0


def _eso_fetcher(paths: Paths):
    """The ESO fetcher on the CT layout: raw CSVs under $ASTRO_DATA_ROOT (D54 item 8)."""
    from astroseeing.download.eso import EsoFetcher, Settings
    from astroseeing.forecast.http import HttpClient

    settings = Settings.load()
    client = HttpClient(timeout_s=settings.timeout_s)
    return EsoFetcher(client, _manifest(paths), paths.data_root / settings.store_dir,
                      settings=settings)  # fmt: skip


def _eso_run(fn) -> int:
    """Run one ESO step; a failure is logged (what was stored stays recorded) and gives 1."""
    from astroseeing.download.eso import EsoFetchFailed, EsoFormatError, WriteOnceError
    from astroseeing.paths import StorageUnresponsive

    try:
        fn()
    except (EsoFetchFailed, EsoFormatError, WriteOnceError, StorageUnresponsive) as e:
        log.error("eso: %s", e)
        return 1
    return 0


def _eso_print(got) -> None:
    print(json.dumps({"path": str(got.path), "sha256": got.sha256, **got.rows.counts()}))


def _eso_tables(args, default: list[str]) -> list[str]:
    return args.tables.split(",") if args.tables else default


def cmd_eso_fetch(args, paths: Paths) -> int:
    """One ESO table over one UTC range [start, end)."""

    def run():
        start, end = args.start, args.end
        _eso_print(_eso_fetcher(paths).fetch(args.table, start, end, label=args.label))

    return _eso_run(run)


def cmd_eso_night(args, paths: Paths) -> int:
    """Each table's rows for the Night named by its evening date (local mean noon to noon
    at the table's site). Run again later for the re-fetch: it is stored as fetch 2."""

    def run():
        f = _eso_fetcher(paths)
        evening = dt.date.fromisoformat(args.evening)
        for key in _eso_tables(args, ["paranal-dimm", "paranal-mass"]):
            _eso_print(f.fetch_night(key, evening, purpose=args.purpose))

    return _eso_run(run)


def cmd_eso_bulk(args, paths: Paths) -> int:
    """Every table, month by month (resumes: stored table-months are skipped)."""

    def run():
        done = _eso_fetcher(paths).bulk(_eso_tables(args, eso_tables()), args.first, args.last)
        print(json.dumps({"fetched": len(done.fetched), "skipped": len(done.skipped)}))

    return _eso_run(run)


def eso_tables() -> list[str]:
    """The ESO tables in ``configs/eso.yaml``."""
    return list(load_config("eso")["tables"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="astro", description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="manifest counts and failures").set_defaults(fn=cmd_status)

    p = sub.add_parser("plan-box", help="add requests for a small box around a site")
    p.add_argument("--region", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--half-width", type=int, default=2, help="grid cells each side (2 → 5×5)")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--kinds", default="pl,sl", help="comma list of pl, sl, static")
    p.add_argument(
        "--granularity",
        choices=("day", "month"),
        default=load_config("era5")["request"]["validation_box_granularity"],
        help="request size (default from configs/era5.yaml: month for validation boxes, D16)",
    )
    p.add_argument("--hours", default="", help="comma list of UTC hours (default all 24)")
    p.set_defaults(fn=cmd_plan_box)

    p = sub.add_parser("download", help="submit, poll and download planned requests")
    p.add_argument(
        "--max-active", type=int, default=1, choices=[1],
        help="jobs at the CDS at once; only 1 is allowed (D39, needs Riley's OK to change)",
    )  # fmt: skip
    p.add_argument("--poll", type=float, default=60.0)
    p.add_argument("--max-hours", type=float, default=None)
    p.set_defaults(fn=cmd_download)
    p = sub.add_parser("cds-resume", help="allow CDS submissions again after a pause (D39)")
    p.add_argument("--reason", required=True, help="what was checked, for the event log")
    p.set_defaults(fn=cmd_cds_resume)

    sub.add_parser("verify", help="verify downloaded GRIB files").set_defaults(fn=cmd_verify)
    sub.add_parser("ingest", help="ingest verified files into Zarr").set_defaults(fn=cmd_ingest)
    sub.add_parser("cleanup-raw", help="delete raw GRIB after verified ingest").set_defaults(
        fn=cmd_cleanup_raw
    )

    p = sub.add_parser(
        "archive-raw",
        help="copy kept raw GRIB from /staging to the write-once archive on the NAS, verify "
        "it, then delete the /staging copy (D55 item 7, D64)",
    )
    p.add_argument("--dry-run", action="store_true", help="print sizes and the plan only")
    p.add_argument("--files", action="store_true", help="with --dry-run: list every file")
    p.add_argument(
        "--delete-measured",
        action="store_true",
        help="also delete the /staging copy of measurement-only files (Riley's call)",
    )
    p.add_argument("--max-gb", type=float, help="size limit for this run (default: config)")
    p.set_defaults(fn=cmd_archive_raw)

    p = sub.add_parser("retry-failed", help="move failed requests back to planned")
    p.add_argument("--max-attempts", type=int, default=5)
    p.set_defaults(fn=cmd_retry_failed)

    p = sub.add_parser("notify", help="send one notification (ntfy; ~/.config/astro/notify.env)")
    p.add_argument("message")
    p.add_argument("--title", default="astro-seeing")
    p.set_defaults(fn=cmd_notify)
    p = sub.add_parser("notify-watch", help="notify on finish, problems and daily progress")
    p.add_argument("--interval", type=float, default=600.0, help="seconds between checks")
    p.add_argument("--stall-hours", type=float, default=3.0)
    p.add_argument("--daily-hour-utc", type=int, default=6)
    p.set_defaults(fn=cmd_notify_watch)

    p = sub.add_parser("plan-area", help="plan downloads for a validation area (D31)")
    p.add_argument("name", help="area in configs/validation_areas.yaml")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--kinds", default="pl", help="comma list of pl, sl, static")
    p.add_argument("--hours", default="all", help="all | night | comma list of UTC hours")
    p.add_argument(
        "--variables", default="",
        help="variables for every kind in --kinds, e.g. z,t,u,v for pl or lcc,zust for sl "
        "(default all); a name the kind doesn't have is an error, so plan pl and sl separately",
    )  # fmt: skip
    p.add_argument("--levels", default="29", help="29 (default) | 37 | comma list of hPa")
    p.add_argument("--day-step", type=int, default=1, help="keep every Nth day of each month")
    p.set_defaults(fn=cmd_plan_area)
    p = sub.add_parser(
        "plan-measure",
        help="plan a one-off CDS test request: downloaded and verified, never ingested (#10)",
    )
    p.add_argument("--kind", choices=("pl", "sl"), default="pl")
    p.add_argument("--date", required=True)
    p.add_argument("--hours", default="0", help="comma list of UTC hours (default 0)")
    p.add_argument("--area", default="", help="N,W,S,E in degrees (default: the whole globe)")
    p.add_argument("--variables", default="", help="comma list (default: the kind's defaults)")
    p.add_argument("--levels", default="29", help="29 (default) | 37 | comma list of hPa")
    p.add_argument("--label", default=None, help="region becomes measure-LABEL (default global)")
    p.set_defaults(fn=cmd_plan_measure)
    p = sub.add_parser("cancel", help="drop planned/held requests whose key starts with PREFIX")
    p.add_argument("prefix")
    p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_cancel)

    p = sub.add_parser("requeue-refused", help="move refused requests back to verified")
    p.add_argument("prefix")
    p.set_defaults(fn=cmd_requeue_refused)

    p = sub.add_parser("hold", help="pause planned requests whose key starts with PREFIX")
    p.add_argument("prefix", help="e.g. pl/paranal/2021 (keys are kind/region/period)")
    p.set_defaults(fn=cmd_hold)
    p = sub.add_parser("release", help="move held requests whose key starts with PREFIX to planned")
    p.add_argument("prefix")
    p.set_defaults(fn=cmd_release)

    sub.add_parser(
        "export-manifest", help="copy the manifest to /data/astro/manifest-exports"
    ).set_defaults(fn=cmd_export_manifest)

    p = sub.add_parser(
        "build-landmask", help="land + 1 km buffer (GLOBE 30″) and the ERA5 cells kept"
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="compute and print; write no stores (and no summary unless --summary-out is given)",
    )
    p.add_argument(
        "--summary-out",
        default=None,
        help=f"JSON summary path (default without --dry-run: {DEFAULT_LANDMASK_SUMMARY})",
    )
    p.set_defaults(fn=cmd_build_landmask)

    p = sub.add_parser("fetch-sp", help="surface pressure at the Haslebacher sites, 1979-2020, "
                       "from the CDS time-series product (own CDS slot; D57, D62)")  # fmt: skip
    p.add_argument("--sites", help="comma-separated sites of the group (default: all 8)")
    p.add_argument("--chunk-years", type=int, help="calendar years per request (default: "
                   "configs/timeseries.yaml)")  # fmt: skip
    p.add_argument(
        "--replan",
        action="store_true",
        help="replace unfinished chunks planned with another chunk size",
    )
    p.add_argument("--retry-failed", action="store_true", help="plan failed chunks again first")
    p.add_argument(
        "--plan-only", action="store_true", help="plan, print the status, submit nothing"
    )
    p.add_argument("--status", action="store_true", help="print chunks and stores (read only)")
    p.add_argument("--poll", type=float, default=10.0, help="seconds between polls")
    p.add_argument("--max-hours", type=float, default=6.0, help="stop after this long (0: never)")
    p.set_defaults(fn=cmd_fetch_sp)

    p = sub.add_parser("cds-smoke-test", help="phase 1 step 2: one hour, small box")
    p.add_argument("--date", default="2023-06-21")
    p.add_argument("--poll", type=float, default=5.0)
    p.add_argument("--timeout-hours", type=float, default=6.0)
    p.add_argument("--out", default=str(REPO_ROOT / "reports" / "cds_smoke_test.json"))
    p.set_defaults(fn=cmd_cds_smoke_test)

    eso_p = sub.add_parser("eso", help="ESO ambient conditions: Paranal DIMM and MASS, La Silla "
                           "DIMM; raw CSVs written once (D54 item 8, D65)")  # fmt: skip
    esub = eso_p.add_subparsers(dest="eso_cmd", required=True)
    p = esub.add_parser("fetch", help="one table over one UTC range [start, end)")
    p.add_argument("table", choices=eso_tables())
    p.add_argument("--start", required=True, type=_utc, help="UTC, e.g. 2026-11-13T16:41:36")
    p.add_argument("--end", required=True, type=_utc, help="UTC, exclusive")
    p.add_argument("--label", help="name part of the file (default: the range)")
    p.set_defaults(fn=cmd_eso_fetch)
    p = esub.add_parser("night", help="the tables for one Night, by its evening date")
    p.add_argument("--evening", required=True, help="YYYY-MM-DD")
    p.add_argument("--tables", help="comma-separated (default: paranal-dimm,paranal-mass)")
    p.add_argument("--purpose", default="nightly", help="recorded in the manifest, e.g. refetch")
    p.set_defaults(fn=cmd_eso_night)
    p = esub.add_parser("bulk", help="month by month, one request every few seconds; resumes")
    p.add_argument("--from", dest="first", required=True, help="first month, YYYY-MM")
    p.add_argument("--to", dest="last", required=True, help="last month, YYYY-MM")
    p.add_argument("--tables", help="comma-separated (default: every table in configs/eso.yaml)")
    p.set_defaults(fn=cmd_eso_bulk)

    forecast = sub.add_parser("forecast", help="the forecast track (F1)")
    fsub = forecast.add_subparsers(dest="forecast_cmd", required=True)
    p = fsub.add_parser("place-height", help="look up a saved place's GLO-30 ground height "
                        "and write it into the forecast settings")  # fmt: skip
    p.add_argument("place", help="saved place id, e.g. kongsberg")
    p.add_argument("--settings", help="settings file (default: configs/forecast.yaml)")
    p.add_argument("--dem-url", help="GLO-30 bucket URL (default: from the settings; tests)")
    p.set_defaults(fn=cmd_forecast_place_height)
    p = fsub.add_parser("tick", help="fetch new forecast runs, store them and publish the page "
                        "files (every 15 min from astro-forecast.timer)")  # fmt: skip
    p.add_argument("--settings", help="settings file (default: configs/forecast.yaml)")
    p.set_defaults(fn=cmd_forecast_tick)
    p = fsub.add_parser("status", help="each model's latest runs and the last tick (read only)")
    p.add_argument("--settings", help="settings file (default: configs/forecast.yaml)")
    p.add_argument("--runs", type=int, default=4, help="runs listed per model and area")
    p.add_argument("--now", type=_utc, help="the time to report at (default: now; tests)")
    p.set_defaults(fn=cmd_forecast_status)
    p = fsub.add_parser("size-report", help="measured run and store sizes against the "
                        "estimates, as Markdown in reports/ (read only)")  # fmt: skip
    p.add_argument("--settings", help="settings file (default: configs/forecast.yaml)")
    p.add_argument("--start", type=_utc, help="first run time (default: 7 days before --end)")
    p.add_argument("--end", type=_utc, help="run times before this (default: now)")
    p.add_argument("--out", help="report file (default: reports/forecast_sizes_<range>.md)")
    p.add_argument("--now", type=_utc, help="the time to report at (default: now; tests)")
    p.set_defaults(fn=cmd_forecast_size_report)

    web = sub.add_parser("web", help="the forecast page's site (F1)")
    wsub = web.add_subparsers(dest="web_cmd", required=True)
    p = wsub.add_parser("deploy", help="copy this checkout's committed web/ to "
                        "/staging/forecast/site/<commit>/ and make it the live page")  # fmt: skip
    p.add_argument("--rollback", action="store_true",
                   help="switch back to the commit live before (again: forward)")  # fmt: skip
    p.set_defaults(fn=cmd_web_deploy)

    args = ap.parse_args(argv)
    _setup_logging(args.verbose)
    return int(args.fn(args, Paths.from_env()) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
