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
    if s.failed:
        log.error("%d request(s) failed in this run; see `astro status`", s.failed)
        return 1
    return 0


def cmd_verify(args, paths: Paths) -> int:
    from astroseeing.ingest.pipeline import verify_pending

    out = verify_pending(_manifest(paths))
    log.info("verify: %s", out)
    return 1 if out["failed"] else 0


def cmd_ingest(args, paths: Paths) -> int:
    from astroseeing.ingest.pipeline import ingest_pending

    # No land/night mask is wired in yet (the land-mask source is an open [ASK]), so
    # only validation boxes are ingested; larger requests are refused and counted.
    cfg = {"era5": load_config("era5"), "layout": "grid"}
    out = ingest_pending(_manifest(paths), paths.data_root, cfg)
    log.info("ingest: %s", out)
    return 1 if out["failed"] or out["refused_unmasked"] else 0


def cmd_cleanup_raw(args, paths: Paths) -> int:
    from astroseeing.ingest.pipeline import cleanup_raw

    out = cleanup_raw(_manifest(paths), paths.staging)
    log.info("cleanup: %s", out)
    return 1 if out["failed"] or out["skipped"] else 0


def cmd_retry_failed(args, paths: Paths) -> int:
    log.info(
        "moved %d failed requests back to planned", _manifest(paths).retry_failed(args.max_attempts)
    )
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
    out = _manifest(paths).export(paths.manifest_exports)
    log.info("exported manifest to %s", out)
    return 0


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
    if args.summary_out:
        p = Path(args.summary_out)
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
    dl = Downloader(m, backend, paths.grib_dir, max_active=len(specs))
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
    p.add_argument("--max-active", type=int, default=4)
    p.add_argument("--poll", type=float, default=60.0)
    p.add_argument("--max-hours", type=float, default=None)
    p.set_defaults(fn=cmd_download)

    sub.add_parser("verify", help="verify downloaded GRIB files").set_defaults(fn=cmd_verify)
    sub.add_parser("ingest", help="ingest verified files into Zarr").set_defaults(fn=cmd_ingest)
    sub.add_parser("cleanup-raw", help="delete raw GRIB after verified ingest").set_defaults(
        fn=cmd_cleanup_raw
    )

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
    p.add_argument("--dry-run", action="store_true", help="compute and report; write nothing")
    p.add_argument("--summary-out", default=str(REPO_ROOT / "reports" / "landmask_summary.json"))
    p.set_defaults(fn=cmd_build_landmask)

    p = sub.add_parser("cds-smoke-test", help="phase 1 step 2: one hour, small box")
    p.add_argument("--date", default="2023-06-21")
    p.add_argument("--poll", type=float, default=5.0)
    p.add_argument("--timeout-hours", type=float, default=6.0)
    p.add_argument("--out", default=str(REPO_ROOT / "reports" / "cds_smoke_test.json"))
    p.set_defaults(fn=cmd_cds_smoke_test)

    args = ap.parse_args(argv)
    _setup_logging(args.verbose)
    return int(args.fn(args, Paths.from_env()) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
