#!/usr/bin/env python3
"""CDS throughput at one job at a time (D39), measured from a copy of the manifest.

For each request that finished at the CDS in [--since, --until):

- queue wait = ``cds_started_at - submitted_at``;
- CDS run time = ``cds_finished_at - cds_started_at``;
- fields = the CDS cost of ``request_json`` (``notify.request_fields``), checked against
  the GRIB message count recorded at verification;
- the download's size and seconds;
- idle before submit = this ``submitted_at`` minus the previous job's ``cds_finished_at``
  (time the account's one slot sat unused on our side). A negative value would mean two
  jobs at the CDS at once, which D39 forbids.

Then per UTC day (by ``cds_finished_at``) and kind: requests, fields, and fields per
second of the whole day (wall), of CDS run time (run), and of slot time, i.e. from submit
to finish (slot). Plus the median and spread of queue wait vs run time per request group.

``cds_started_at`` and ``cds_finished_at`` are the CDS's own job timestamps; ``submitted_at``
is the CT's clock, so the queue wait also holds the submit call and any clock offset.

Read-only. Point it at a copy, never at the live manifest: an export from
``/data/astro/manifest-exports/``, or a copy made with the SQLite backup API.

Run on the CT:
    pixi run python scripts/cds_throughput.py COPY.sqlite --since 2026-10-30 \
        [--until 2026-11-12T21:34:52Z] [--csv rows.csv] [--plot figure.png]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys

import pandas as pd

from astroseeing.notify import request_fields

QUERY = """
SELECT r.id, r.key, r.kind, r.region, r.request_json, r.submitted_at, r.cds_started_at,
       r.cds_finished_at, f.size, f.download_seconds,
       (SELECT v.report_json FROM verifications v WHERE v.file_id = f.id
        ORDER BY v.id DESC LIMIT 1) AS verification
FROM requests r
LEFT JOIN files f ON f.id = (SELECT max(id) FROM files WHERE request_id = r.id)
WHERE r.cds_finished_at IS NOT NULL AND r.submitted_at IS NOT NULL
"""
DAY_S = 86400.0


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, format="ISO8601")


def load(path: str, since: pd.Timestamp, until: pd.Timestamp | None) -> tuple[pd.DataFrame, dict]:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    if until is None:  # the copy's own end: its last manifest update
        until = pd.Timestamp(db.execute("SELECT max(updated_at) FROM requests").fetchone()[0])
    df = pd.read_sql_query(QUERY, db)
    for c in ("submitted_at", "cds_started_at", "cds_finished_at"):
        df[c] = _ts(df[c])
    keep = (df.cds_finished_at >= since) & (df.cds_finished_at < until)
    df = df[keep].sort_values("submitted_at").reset_index(drop=True)
    window = (since.isoformat(), until.isoformat())
    extra = {
        "until": until,
        "rejections": db.execute(
            "SELECT count(*) FROM cds_rejections WHERE at >= ? AND at < ?", window
        ).fetchone()[0],
        "pauses": db.execute(
            "SELECT count(*) FROM cds_control WHERE paused_at >= ? AND paused_at < ?", window
        ).fetchone()[0],
        "events": db.execute(
            "SELECT event, count(*) FROM events WHERE at >= ? AND at < ?"
            " GROUP BY event ORDER BY event",
            window,
        ).fetchall(),
    }
    db.close()

    df["group"] = df.kind + "/" + df.region.str.replace(r"@vars-.*", "@vars", regex=True)
    df["fields"] = [request_fields(json.loads(j)) for j in df.request_json]
    df["n_messages"] = [
        json.loads(v).get("n_messages") if isinstance(v, str) else None for v in df.verification
    ]
    df["queue_s"] = (df.cds_started_at - df.submitted_at).dt.total_seconds()
    df["run_s"] = (df.cds_finished_at - df.cds_started_at).dt.total_seconds()
    df["slot_s"] = (df.cds_finished_at - df.submitted_at).dt.total_seconds()
    df["idle_before_s"] = (df.submitted_at - df.cds_finished_at.shift(1)).dt.total_seconds()
    df["mb_per_s"] = df["size"] / 1e6 / df.download_seconds
    df["day"] = df.cds_finished_at.dt.strftime("%Y-%m-%d")
    return df.drop(columns=["request_json", "verification"]), extra


def q(s: pd.Series, p: float) -> float:
    return float(s.quantile(p)) if len(s) else float("nan")


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def per_day(df: pd.DataFrame, first_submit: pd.Timestamp, until: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for day, d in df.groupby("day"):
        start = pd.Timestamp(day, tz="UTC")
        full = first_submit <= start and until >= start + pd.Timedelta(days=1)
        row = {"day": day, "full": "yes" if full else "partial"}
        for kind in ("pl", "sl"):
            k = d[d.kind == kind]
            f = int(k.fields.sum())
            row[f"{kind} req"] = len(k)
            row[f"{kind} fields"] = f
            row[f"{kind} wall f/s"] = f"{f / DAY_S:.2f}" if full else "-"
            row[f"{kind} run f/s"] = f"{f / k.run_s.sum():.0f}" if len(k) else "-"
            row[f"{kind} slot f/s"] = f"{f / k.slot_s.sum():.2f}" if len(k) else "-"
        tot = int(d.fields.sum())
        row["all wall f/s"] = f"{tot / DAY_S:.2f}" if full else "-"
        row["queue min (median)"] = f"{d.queue_s.median() / 60:.0f}"
        sub = df[df.submitted_at.dt.strftime("%Y-%m-%d") == day]
        row["idle h"] = f"{sub.idle_before_s.clip(lower=0).sum() / 3600:.2f}"
        rows.append(row)
    return pd.DataFrame(rows)


def per_group(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, g in [*df.groupby("group"), ("all", df)]:
        m = 60.0
        rows.append({
            "group": name,
            "n": len(g),
            "fields/req (median)": int(g.fields.median()),
            "queue min: median": f"{g.queue_s.median() / m:.0f}",
            "p10-p90": f"{q(g.queue_s, .1) / m:.0f}-{q(g.queue_s, .9) / m:.0f}",
            "min-max": f"{g.queue_s.min() / m:.1f}-{g.queue_s.max() / m:.0f}",
            "run min: median": f"{g.run_s.median() / m:.1f}",
            "run p10-p90": f"{q(g.run_s, .1) / m:.1f}-{q(g.run_s, .9) / m:.1f}",
            "run share of slot": f"{g.run_s.sum() / g.slot_s.sum():.1%}",
            "run f/s (median)": f"{(g.fields / g.run_s).median():.0f}",
            "slot f/s (sum/sum)": f"{g.fields.sum() / g.slot_s.sum():.2f}",
        })  # fmt: skip
    return pd.DataFrame(rows)


def plot(df: pd.DataFrame, path: str) -> None:
    """Queue wait (top) and CDS run time (bottom) per request against submit time."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    # Reference palette (dataviz skill): categorical slots 1-3, which validate all-pairs.
    surf, ink, ink2, muted, grid, axis = (
        "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7",
    )  # fmt: skip
    vars6 = df.region.str.contains("@vars")
    bands = [
        ("pressure levels", df.kind == "pl", "#2a78d6", "o"),
        ("single levels, 17 variables", (df.kind == "sl") & ~vars6, "#eb6834", "s"),
        ("single levels, 6 variables", (df.kind == "sl") & vars6, "#1baf7a", "^"),
    ]
    fig, (a1, a2) = plt.subplots(
        2, 1, figsize=(10, 6.2), sharex=True, height_ratios=[3, 1.3], facecolor=surf
    )
    for label, mask, color, marker in bands:
        d = df[mask]
        if d.empty:
            continue
        lo, hi = d.fields.min() / 1000, d.fields.max() / 1000
        size = f"{lo:.1f}k" if lo == hi else f"{lo:.1f}-{hi:.1f}k"
        name = f"{label}: {size} fields per request (n={len(d)})"
        kw = dict(color=color, marker=marker, s=40, edgecolors=surf, linewidths=1, zorder=3)
        a1.scatter(d.submitted_at, d.queue_s / 3600, label=name, **kw)
        a2.scatter(d.submitted_at, d.run_s / 60, **kw)
    a1.set_ylabel("queue wait (h)", color=ink2)
    a2.set_ylabel("CDS run time (min)", color=ink2)
    a1.set_ylim(0, df.queue_s.max() / 3600 * 1.35)  # headroom for the legend
    a2.set_ylim(bottom=0)
    for a in (a1, a2):
        a.set_facecolor(surf)
        a.grid(axis="y", color=grid, linewidth=1)
        a.set_axisbelow(True)
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            a.spines[side].set_color(axis)
        a.tick_params(colors=muted, labelcolor=ink2)
    a2.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    a2.set_xlabel("submitted (UTC)", color=ink2)
    a1.set_title(
        "Each CDS request at one job at a time (D39): waiting vs running",
        loc="left", color=ink, fontsize=12,
    )  # fmt: skip
    a1.legend(loc="upper left", frameon=False, labelcolor=ink2, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=surf)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifest", help="a COPY of manifest.sqlite (opened read-only)")
    ap.add_argument("--since", default="2026-10-30", help="cds_finished_at on or after (UTC)")
    ap.add_argument("--until", help="cds_finished_at before (UTC); default: the copy's end")
    ap.add_argument("--csv", help="also write the per-request rows here")
    ap.add_argument("--plot", help="also draw queue wait and run time per request (PNG)")
    a = ap.parse_args()
    since = pd.Timestamp(a.since, tz="UTC")
    until = pd.Timestamp(a.until).tz_convert("UTC") if a.until else None
    df, extra = load(a.manifest, since, until)
    if df.empty:
        print("no finished requests in the window")
        return 1
    until = extra["until"]
    if a.csv:
        df.to_csv(a.csv, index=False)
    if a.plot:
        plot(df, a.plot)

    print(f"# CDS throughput, finished {a.since} to {until.isoformat()}\n")
    print(f"- requests finished at the CDS: {len(df)}; fields: {int(df.fields.sum()):,}")
    mism = df[df.n_messages.notna() & (df.n_messages != df.fields)]
    print(f"- fields vs GRIB messages at verification: {len(mism)} mismatches"
          f" ({int(df.n_messages.notna().sum())} verified)")  # fmt: skip
    print(f"- jobs overlapping at the CDS (idle_before < 0): {(df.idle_before_s < 0).sum()}")
    print(f"- CDS rejections recorded: {extra['rejections']}; pauses: {extra['pauses']}")
    print(f"- events: {dict(extra['events'])}")
    print(f"- first submit {df.submitted_at.min().isoformat()},"
          f" last finish {df.cds_finished_at.max().isoformat()}\n")  # fmt: skip

    print("## Per request group\n")
    print(md(per_group(df)), "\n")

    print("## Per UTC day (by cds_finished_at)\n")
    pdays = per_day(df, df.submitted_at.min(), until)
    print(md(pdays), "\n")
    full = pdays[pdays.full == "yes"].day
    fd = df[df.day.isin(full)]
    pl, sl = (int(fd[fd.kind == k].fields.sum()) for k in ("pl", "sl"))
    print(f"Full days {full.min()} to {full.max()} ({len(full)} days): "
          f"{int(fd.fields.sum()):,} fields = {fd.fields.sum() / (len(full) * DAY_S):.2f} f/s"
          f" (pl {pl:,}, sl {sl:,})\n")  # fmt: skip

    print("## Queue wait by UTC hour of submission\n")
    b = pd.cut(df.submitted_at.dt.hour, [0, 6, 12, 18, 24], right=False,
               labels=["00-06", "06-12", "12-18", "18-24"])  # fmt: skip
    t = df.groupby(b, observed=False).queue_s.agg(["count", "median"])
    t["median"] = (t["median"] / 60).round(0)
    print(md(t.reset_index().rename(columns={"submitted_at": "submit hour",
                                             "median": "median queue min"})), "\n")  # fmt: skip

    print("## Our side: idle between a job finishing and the next submit\n")
    idle = df.idle_before_s.dropna()
    print(f"median {idle.median():.0f} s, p90 {q(idle, .9):.0f} s, max {idle.max() / 3600:.2f} h,"
          f" total {idle.clip(lower=0).sum() / 3600:.1f} h\n")  # fmt: skip
    top = df.loc[df.idle_before_s.nlargest(4).index, ["key", "submitted_at", "idle_before_s"]]
    top["idle h"] = (top.pop("idle_before_s") / 3600).round(2)
    print(md(top), "\n")

    print("## Downloads\n")
    print(f"total {df['size'].sum() / 1e9:.2f} GB in {df.download_seconds.sum() / 60:.1f} min;"
          f" MB/s median {df.mb_per_s.median():.1f}, p10-p90 {q(df.mb_per_s, .1):.1f}-"
          f"{q(df.mb_per_s, .9):.1f}")  # fmt: skip
    for name, g in df.groupby("group"):
        print(f"- {name}: size median {g['size'].median() / 1e6:.1f} MB,"
              f" MB/s median {g.mb_per_s.median():.1f}, max {g.mb_per_s.max():.1f}")  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
