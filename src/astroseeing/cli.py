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


def cmd_export_manifest(args, paths: Paths) -> int:
    out = _manifest(paths).export(paths.manifest_exports)
    log.info("exported manifest to %s", out)
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

    sub.add_parser(
        "export-manifest", help="copy the manifest to /data/astro/manifest-exports"
    ).set_defaults(fn=cmd_export_manifest)

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
