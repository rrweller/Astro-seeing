# CDS throughput at one job at a time (#11)

Ticket #11 (part of map #6) asks what the CDS delivers under the D39 gate (one job queued or running per account), and for the phase 2 and 3 download estimates of `reports/validation_downloads.md` §4 to be restated with the answer.

- **§1–§5, throughput:** written on 2026-11-12 from a read-only copy of the manifest, taken with the SQLite backup API at 21:34:52 UTC. The live manifest was not written.
- **§6, one global hour and the cost limits:** added on 2026-11-13. The global hour ran through the live queue on 12–13 Nov on Riley's go-ahead, using the measurement-only mode (#10, D50).
- **§7, phase 2 and 3 estimates:** restated on 2026-11-13. They replace the estimates in `reports/validation_downloads.md` §4, which assumed up to 4 jobs in flight.
- **Scripts:** `scripts/cds_throughput.py` (§1–§5) and `scripts/download_estimates.py` (§7).
- **Figure:** `reports/figures/cds_throughput_one_job.png`.

## Summary

- **Request count, not fields, sets the download time.** The CDS needs about 3 days of processing for five years of hourly global pressure and single levels (7.1 M fields). Everything else is queue wait, about 4 h per request this month, whatever the request's size (§6, §7).
- **A global field costs the CDS no more time than a box field.** One global hour (145 fields, 721 × 1440 points each) ran in 12.9 s on 13 Nov. The same 145 fields over a 5 × 5 box at Paranal ran in 16.0 s in the smoke test on 27 Sep. The global hour still waited 4 h 16 min in the queue, as long as the 58,435-field request before it (§6).
- **The cost limits are unchanged:** 60,000 fields per pressure-level request and 121,000 per single-level one, for the whole globe as for a 5 × 5 box (CDS cost estimates on 13 Nov; nothing submitted). The largest global pressure-level request is 17 hourly days (59,160 fields, about 110 GB).
- **Phase 3, restated:** five years of hourly global data would take about **1.5 years** of CDS time at one day per request, which is what AGENTS.md specifies now. With fewer, bigger requests it takes about **2 months** (weekly pressure-level requests) or **1 month** (half-monthly). September's estimate, with up to 4 jobs in flight, was 8–9.5 days. Request size is then limited by `/staging`, not by the CDS (§7).
- **Phase 2, restated:** downloading the 8 regions separately would take **160 days** (night hours only) to **252 days** (all hours), against 35–76 days in September. Cutting them out of the global download costs no extra requests (§7, for #13).

- **Waiting, not processing, is the cost.** Over 107 requests (1.50 M fields, 30 Oct to 12 Nov) the median request waited 2.7 h in the CDS queue and then ran for 3.1 min. Running took 5.5% of the time from submit to finish: 2.5–3.2% for single-level requests, 9–14% for pressure-level ones.
- **Pressure levels: 2.66 fields/s**, averaged over the 4 full days that ran only pressure levels (5–8 Nov; daily 2.13–3.19). That is about a quarter of September's 10.3 fields/s with up to 4 jobs in flight. It is also half the 5.6 fields/s that `configs/era5.yaml` (`request.fields_per_s`) uses for planning estimates.
- **Single levels are lower: 0.36 fields/s** for Chile's 6-variable subset (4 full days, 31 Oct–3 Nov; daily 0.22–0.49), and **0.58 fields/s** for the 17-variable set (2 full days, 10–11 Nov). The requests are small (2,400 and 6,900 fields), but each one still waits hours.
- **Processing rate once a job runs:** about 29 fields/s for pressure levels and 15–17 fields/s for single levels. For single levels the run time is linear in fields with almost no fixed cost: 22 s + fields ÷ 17 fields/s, r = 0.94. The area makes no difference: a 5 × 5 box ran at 27 fields/s and the 38 × 16 Chile area at 29.
- **The queue wait follows the CDS's load more than request size.**
  - Same-sized requests (2,184–2,418 fields, Chile's 6-variable subset) waited a median of 75–81 min on 31 Oct and 1 Nov, but 162 min on 2 and 3 Nov.
  - Since 7 Nov, ~45,000-field pressure-level requests waited a median of 4.0 h, and 6,900-field single-level ones 3.25 h.
  - On 12–13 Nov, the 145-field global hour waited 4 h 16 min, longer than the 58,435-field request before it (4 h 04 min; §6).
- **So bigger requests are cheaper per field.** A wait of hours per request against ~29 fields/s of processing means each request should be as close to the CDS cost limit as possible.
- **Nothing went wrong at the CDS** in §1–§5's period. There were 0 rejections, 0 pauses and 0 lost jobs, and never two jobs at once (D39 held). Every request's field count matched its GRIB message count at verification.
- **Our side costs almost nothing:** a median of 18 s from one job finishing to the next submission. The only real loss was a CT outage on 12 Nov, which left the slot unused for 3.2 h.

## 1. Method

- **The copy:** taken with the SQLite backup API from the live manifest opened read-only (`mode=ro`) at 2026-11-12 21:34:52 UTC; `integrity_check` returned ok.
- **Which requests:** every request whose `cds_finished_at` falls between 2026-10-30 00:00 and the copy. That is 107 requests, each with one file, all downloaded, verified and ingested.
  - The request still at the CDS (`pl/tmt_spm/2006-03`, submitted 18:37 UTC) is left out.
- **Timestamps:**
  - `cds_started_at` and `cds_finished_at` are the CDS's own job timestamps (the client's `started_at` and `finished_at`).
  - `submitted_at` is the CT's clock, which is synchronised. So the queue wait also includes the submit call itself, about 1 s.
- **Definitions:**
  - **Queue wait** = `cds_started_at − submitted_at`.
  - **Run time** = `cds_finished_at − cds_started_at`.
  - **Slot time** = `cds_finished_at − submitted_at`, the time a request held the account's one place at the CDS (D39).
  - **Idle** = this request's `submitted_at` minus the previous job's `cds_finished_at`.
- **Fields:** the CDS cost computed from `request_json` (variables × levels × hours × days, `notify.request_fields`). For all 107 requests it equals the GRIB message count found at verification.
- **Days:**
  - Each request counts on the UTC day its CDS job finished.
  - A full day is one the loop ran from start to end: 31 Oct to 11 Nov, 12 days.
  - With 4–6 pressure-level requests a day, one request more or less moves that day's rate by about ±0.5 fields/s. The means over several days are therefore the numbers to use.
- **To reproduce:** `pixi run python scripts/cds_throughput.py COPY.sqlite --since 2026-10-30 --until 2026-11-12T21:34:52Z --plot reports/figures/cds_throughput_one_job.png`. Any manifest export from the 13 Nov 03:17 UTC run onward (`/data/astro/manifest-exports/`) should give the same numbers with these flags.

## 2. Queue wait and run time per request group

| Group | Requests | Fields per request | Queue wait, median | p10–p90 | min–max | Run time, median | p10–p90 | Running, share of slot time | Fields/s while running (median) | Fields/s over slot time |
|---|---|---|---|---|---|---|---|---|---|---|
| `pl/chile` 2006–07 (z t u v, 13 h) | 24 | 42,224–46,748 | **255 min** | 208–332 | 169–405 | 26.4 min | 23.6–28.9 | 9.3% | 29 | 2.61 |
| `pl/tmt_spm` (z t u v cc, 13 h) | 2 | 52,780; 58,435 | 89 and 327 min | — | — | 37.7 and 32.0 min | — | 14.4% | 27 | 3.82 |
| `sl/chile` 2006–07 (17 variables) | 21 | 6,851 max | **195 min** | 165–278 | 160–312 | 7.2 min | 5.9–7.7 | 3.2% | 15 | 0.51 |
| `sl/chile@vars-…` 2021–25 (6 variables) | 60 | 2,418 max | **85 min** | 63–185 | 0.7–237 | 2.6 min | 2.1–3.2 | 2.5% | 15 | 0.36 |
| all | 107 | | **162 min** | 70–284 | 0.7–405 | 3.1 min | 2.2–27.9 | 5.5% | 17 | 1.33 |

- **Shortest waits:** apart from the first request (39 s, submitted by hand on 30 Oct after 5.6 days with no CDS jobs), no request waited less than 59 min.
- **Longest wait:** 6.75 h, for `pl/chile/2006-02`, submitted at 08:14 on 4 Nov, the second request after the TMT release.

![Queue wait and run time per request](figures/cds_throughput_one_job.png)

The top panel is the queue wait per request against submit time; the bottom panel is the CDS run time. Each colour is one kind of request (legend). The two panels have different units: hours on top, minutes below.

## 3. Per day

| Day (UTC) | What ran | Requests | Fields | Fields/s over the day | Fields/s while running | Queue wait, median | Notes |
|---|---|---|---|---|---|---|---|
| 30 Oct (from 14:36) | sl, 6 variables | 5 | 11,778 | partial | 14 | 104 min | loop started 14:40 |
| 31 Oct | sl, 6 variables | 18 | 42,744 | 0.49 | 15 | 81 min | |
| 1 Nov | sl, 6 variables | 18 | 42,744 | 0.49 | 16 | 75 min | |
| 2 Nov | sl, 6 variables | 9 | 21,294 | 0.25 | 13 | 162 min | same requests, wait doubled |
| 3 Nov | sl, 6 variables | 8 | 19,110 | 0.22 | 14 | 162 min | |
| 4 Nov | sl, 6 variables (2), then pl (3) | 5 | 140,478 | 1.63 | pl 23, sl 14 | 172 min | Chile subset done 04:44; TMT released 05:00 (16 min idle) |
| 5 Nov | pl | 4 | 183,976 | **2.13** | 30 | 330 min | |
| 6 Nov | pl | 5 | 230,724 | **2.67** | 30 | 280 min | two clean CT halts, 12:23–14:14; no CDS time lost |
| 7 Nov | pl | 5 | 227,708 | **2.64** | 30 | 244 min | |
| 8 Nov | pl | 6 | 275,964 | **3.19** | 28 | 223 min | |
| 9 Nov | pl (1), then sl, 17 variables (4) | 5 | 73,268 | 0.85 | pl 28, sl 17 | 273 min | |
| 10 Nov | sl, 17 variables | 8 | 53,703 | 0.62 | 16 | 187 min | |
| 11 Nov | sl, 17 variables | 7 | 47,294 | 0.55 | 16 | 190 min | |
| 12 Nov (to 21:35) | sl, 17 variables (2), pl (2) | 4 | 124,696 | partial | pl 27, sl 16 | 245 min | CT down 12:10–16:31, unclean stop; 3.2 h of slot time lost |

**Averages over full days:**

| Kind | Days | Fields | Fields/s |
|---|---|---|---|
| Pressure levels (z t u v, ~45,000 per request) | 5–8 Nov (4) | 918,372 | **2.66** (daily 2.13–3.19) |
| Single levels, 6 variables (2,418 per request) | 31 Oct–3 Nov (4) | 125,892 | **0.36** (daily 0.22–0.49) |
| Single levels, 17 variables (6,851 per request) | 10–11 Nov (2) | 100,997 | **0.58** (daily 0.55–0.62) |
| Everything, mixed | 31 Oct–11 Nov (12) | 1,359,007 | 1.31 |

## 4. Other observations

- **Time of day.** By UTC hour of submission, the median queue wait was 139 min for 18–24, 158 for 00–06, 195 for 12–18 and 215 for 06–12, from 22–30 requests each.
  - This hints that European working hours are busier.
  - But the mix of request kinds differs between those slots, so it is weak evidence.
- **Idle before a submission.** All three submissions that followed a stretch with no job at the CDS got the shortest wait of their kind:
  - 30 Oct, after 5.6 days: 39 s;
  - 4 Nov, after 16 min (waiting for the TMT release): 169 min, the shortest of the 24 `pl/chile` waits;
  - 12 Nov, after 3.2 h (the CT outage): 89 min, the shortest pressure-level wait.

  Every other submission came within a minute of the previous job finishing. This fits a CDS priority that drops with an account's recent use. But it is only three cases, and I have not found ECMWF documentation describing such a rule, so treat it as a lead, not a finding.
- **Downloads.** In total, 1.84 GB took 4.1 min, which is negligible next to the queue waits.
  - The rate grows with file size, because small files are dominated by latency: the 62 MB pressure-level files came at a median of 21 MB/s (max 25.6), and the 3 MB single-level files at 2.3 MB/s.
  - September's transfers reached 21–47 MB/s. This month's files are too small to show the top rate; the global hour (~300 MB) will.
- **Our side.**
  - Idle time per submission: median 18 s and p90 30 s (the downloader polls every 30 s).
  - In total, 4.0 h idle over the 13 days: 3.2 h of it the 12 Nov outage, and 0.27 h waiting for the hourly TMT release check on 4 Nov.
  - The two clean CT halts on 6 Nov cost nothing, because the job was still queued at the CDS and the restarted loop picked it up.

## 5. What this means for requests

- **Time per request.** At one job at a time, a request takes about **W + F ÷ R**:
  - W is the queue wait: medians between 1.3 h and 5.5 h depending on the day;
  - F is the request's fields;
  - R is the processing rate: ~29 fields/s for pressure levels, ~17 for single levels.
  
  For example, a pressure-level request of 58,000 fields with a 4 h wait takes 4.6 h, or 3.5 fields/s. The global hour (§6) found no sign that R is lower for global fields; its queue wait is one more sample of W.
- **Request size.** Requests should be as large as the cost limit allows. For single levels, that probably means merging variables, months or areas up to the 121,000-field limit, if verification and the manifest can handle larger requests (D16, D23).
- **The planning rate in config is optimistic.** `configs/era5.yaml` `request.fields_per_s: 5.6` is about twice the measured pressure-level rate (2.66). It only feeds the estimate that `plan-area` prints. Not changed here; a small ticket could set it from these numbers, ideally per kind.
- **The stall alert fires on normal waits.** Its 3 h threshold is below the median pressure-level wait (4.3 h), so it fired 36 times between 4 and 12 Nov without anything being wrong (status comment on #11, 2026-11-12). Ticket #34 fixes it.

## 6. One global hour, and the cost limits in force

### 6.1 What ran

- **The request:** `pl/measure-global/2023-06-21`, a measurement-only request (D50: downloaded and verified, never ingested).
  - Whole globe on the 0.25° grid (721 × 1440 points), 29 levels, z t u v cc, 2023-06-21 00:00 UTC. That is 145 fields.
  - Same date, hour, levels and variables as the smoke-test request of 27 Sep, which covered a 5 × 5 box at Paranal (`reports/cds_smoke_test.json`).
- **How:** planned with `astro plan-measure` and run through the live loop, following `docs/ct_runbook.md` §7.
  - The 95 TMT requests still waiting were held so that the measurement came next, then released when it was done.
  - The TMT request already at the CDS (`pl/tmt_spm/2006-03`) finished first.

| Step | Time (UTC) |
|---|---|
| Planned; 95 TMT requests held | 12 Nov 22:34 |
| Submitted, 7 s after `pl/tmt_spm/2006-03` finished at the CDS | 12 Nov 23:24:22 |
| Started at the CDS | 13 Nov 03:40:30 |
| Finished at the CDS | 03:40:43 |
| Downloaded: 270,996,300 bytes in 15.0 s | 03:41:04 |
| Verified (`measured`): 145 messages, no missing or NaN values | 03:41:09 |
| 95 TMT requests released; next TMT request submitted | 03:42:47; 03:42:49 |

### 6.2 Results

- **Queue wait: 4 h 16 min.**
  - That is within the range of this month's pressure-level waits: a median of 4.04 h for requests submitted since 7 Nov (p10–p90 3.38–4.28 h, 15 requests including this one).
  - The request before it, `pl/tmt_spm/2006-03` with 58,435 fields, waited 4 h 04 min and ran 42.8 min.
  - So a request of 145 fields got no shorter wait than one of 58,435. It is one request, but it fits §4: the wait follows the CDS's load, not the request's size.
- **Run time: 12.9 s,** against 16.0 s for the same 145 fields over the 5 × 5 Paranal box on 27 Sep.
  - A global field has about 41,500 times the points of a 5 × 5 field. There is no sign that it costs the CDS more time.
  - Both runs are mostly fixed overhead (22.5 s per request for single-level boxes, §1–§5). So these two can't give a per-field rate for global fields. §7 uses the box rate, 28 fields/s.
  - September's campaign also found that area made no visible difference (`reports/validation_downloads.md` §4).
- **Size: 1.87 MB per global pressure-level field.** A global day of hourly pressure levels (3,480 fields) is 6.50 GB; AGENTS.md says "about 7 GB".
- **Transfer: 18.0 MB/s** for this one file. September's transfers reached 21–47 MB/s.

### 6.3 What it cost the TMT queue

- **About 4.3 h of TMT time.** From 12 Nov 23:24 to 13 Nov 03:42, no TMT request was at the CDS. The TMT finish date (about 28 Nov, status comment on #11) moves by that much.
- **Two harmless alerts:**
  - "the download loop is not running but 96 requests are pending" at 22:34, in the minute the loop was stopped to hold the queue;
  - "no download progress for 3.1 h" at 02:44, the alert that #34 fixes.
- **The raw file is kept:** 271 MB in `/staging/grib`. Nothing deletes it automatically, because it has no ingest (`docs/ct_runbook.md` §7). Deleting it is Riley's call.

### 6.4 The cost limits in force

Asked from the CDS on 13 Nov 03:45 UTC with `estimate_costs`, which prices a request without submitting it:

| Request (2023-06, hourly) | Cost | Limit |
|---|---|---|
| Pressure levels, global, 1 day | 3,480 | 60,000 |
| Pressure levels, global, 17 days | 59,160 | 60,000 |
| Pressure levels, global, 18 days | 62,640 | 60,000: over |
| Pressure levels, 5 × 5 box, 17 days | 59,160 | 60,000 |
| Single levels (17 variables), global, 30 days | 12,240 | 121,000 |

- **The limits are the same as on 27 Sep** (`reports/cds_smoke_test.json`).
- **The cost is the field count, whatever the area.**
- **No rejections:** none since 30 Oct, the global hour included.

## 7. Phase 2 and 3 download estimates, restated

These replace the estimates in `reports/validation_downloads.md` §4 ("What this means for phases 2 and 3"), which assumed up to 4 jobs in flight at 10.3 fields/s.

### 7.1 Method

- **Time per request.** At one job at a time, each request holds the account's only place at the CDS from submit to finish. So a campaign takes the sum, over its requests, of queue wait + run time + 18 s idle (the measured median).
- **Queue wait:** the waits of requests submitted since 7 Nov:
  - pressure levels: median 4.04 h (p10 3.38, p90 4.28; 15 requests);
  - single levels: median 3.25 h (p10 2.76, p90 4.63; 21 requests).

  The range in the table assumes every wait at p10, or every wait at p90. The CDS's load moves all waits together, so this is a range of scenarios, not a confidence interval.
- **Run time:** pressure levels fields ÷ 28 fields/s; single levels 22.5 s + fields ÷ 17 (§1–§5).
- **Requests:** each stays inside one month, as the request code requires (`RequestSpec.cds_request`). 2021–2025 is 1,826 days in 60 months. Fields per hour: 145 on pressure levels (29 levels × 5 variables), 17 on single levels.
- **To reproduce:** `pixi run python scripts/download_estimates.py COPY.sqlite --since 2026-11-07`, on a manifest copy taken after 13 Nov 03:41 UTC. Later copies add later requests to the wait sample.

### 7.2 Results

| Plan | Pressure-level requests | Largest pressure-level request | Single-level requests | CDS days, pressure levels | CDS days, single levels | **Total days** (waits at p10–p90) |
|---|---|---|---|---|---|---|
| **Phase 3, global, hourly** | | | | | | |
| One day per request (AGENTS.md now) | 1,826 | 3,480 fields, 6.5 GB | 1,826 | 310 | 249 | **559** (471–682) |
| Pressure levels about weekly (4–5 a month), single levels monthly | 296 | 24,360 fields, 45.5 GB | 60 | 52 | 9 | **61** (52–68) |
| Pressure levels half-monthly (the cost limit), single levels monthly | 120 | 55,680 fields, 104 GB | 60 | 23 | 9 | **32** (27–36) |
| **Phase 3, global, 3-hourly** | | | | | | |
| Pressure levels half-monthly, single levels monthly | 120 | 18,560 fields, 34.7 GB | 60 | 21 | 8 | **29** (25–34) |
| Pressure levels monthly, single levels monthly | 60 | 35,960 fields, 67.2 GB | 60 | 11 | 8 | **19** (16–23) |
| **Phase 2, 8 regions of 20° × 20°, downloaded separately, hourly** | | | | | | |
| All hours; pressure levels half-monthly, single levels monthly | 960 | 55,680 fields | 480 | 183 | 69 | **252** (216–289) |
| About 13 night hours (`reports/validation_downloads.md` §4); both monthly | 480 | 58,435 fields | 480 | 92 | 67 | **160** (137–192) |

**Against September's estimates:**

| | September: up to 4 jobs in flight, 10.3 fields/s | Now: one job at a time |
|---|---|---|
| Phase 3, global, hourly | 8–9.5 days | 32–61 days with weekly to half-monthly requests; 559 days at one day per request |
| Phase 2, 8 regions separately, all hours | 64–76 days | 252 days |
| Phase 2, 8 regions separately, night hours only | 35–41 days | 160 days |

### 7.3 What this means

- **Processing is a small share.** All 7.1 M fields of five hourly years need only about 3.1 days of CDS processing: 2.6 for pressure levels at 28 fields/s, 0.5 for single levels. The rest of every estimate is queue wait.
- **One day per request doesn't work for phase 3.** AGENTS.md says global and regional runs "stay one day per request unless gate 1 changes it". At this month's waits that is about 1.5 years. So gate 1 has to change it. That is Riley's decision.
- **`/staging` limits the request size, not the CDS cost limit.**
  - `/staging` has 147 GB; 41 GB of it is raw validation GRIB kept under the retention rule, so 99 GB is free (13 Nov).
  - Weekly global pressure-level requests (up to 45.5 GB) fit, even with one request ingesting while the next downloads.
  - Half-monthly ones (up to 104 GB) don't fit today. They would need the kept validation GRIB moved off `/staging`, and each request ingested and deleted before the next one downloads. They would save about a month over weekly requests.
- **Single levels could use fewer, bigger requests.**
  - A month of hourly global single levels is 12,648 fields, about a tenth of the 121,000 limit.
  - Requests spanning up to 9 months would cut the 8–9 single-level days to about 1.
  - That needs a code change, because `RequestSpec.cds_request` allows one month at most. It also needs a cost check: whether the CDS counts non-existent dates (such as 30 February) in a months × days request is untested.
- **Phase 2 regions cost far more requests separately.** The 8 regions downloaded separately need 960 requests (night hours only) to 1,440 (all hours). One global run with weekly requests needs 356. This supports cutting the regions out of global days, the recommendation September's report expected to make at gate 1. #13 decides it.
- **Mirrors:** #12 put NCAR's 11.9 TB at 3–7 days of transfer, and compared that with about 15 days of CDS processing. The CDS figure is now 32–61 days with big requests, or about 1.5 years at one day per request. The choice is #13's.
- **Transfer and ingest can hide inside the queue wait, if they don't block submission.**
  - The downloader submits the next request before downloading the finished one (`Downloader.step`). A 45.5 GB download takes 42 min at 18 MB/s, and a 104 GB one 1.6 h, both inside the next request's ~4 h wait.
  - But `scripts/run_boxes.sh` downloads, verifies and ingests in turn, so nothing polls the CDS while a request ingests. Phase 3's downloader (AGENTS.md phase 3) should keep polling and submitting while ingest runs.
  - How long a global ingest takes is unmeasured.
- **Volume:** 11.9 TB of raw pressure levels for five hourly years (6.50 GB a day), plus single levels. The size of a global single-level field wasn't measured; at the same 1.87 MB per field it would be 1.4 TB.
- **3-hourly profiles** (an open gate 2 decision) would bring phase 3 down to 19–29 days, mostly because bigger requests then fit in `/staging`.

## 8. What's uncertain

- **The CDS's load is invisible to us.** It changed from one day to the next: the median wait for identical requests doubled overnight on 1–2 Nov. These two weeks are one sample of it.
  - The estimates in §7 scale almost linearly with the wait: a 2 h median would halve them, and a 6 h one would add half.
  - Re-measure before any large campaign.
- **Request size and load are confounded.** Pressure and single levels ran in different weeks, except around 9 and 12 Nov.
  - The comparison since 7 Nov (pressure levels 4.0 h, single levels 3.25 h) is the cleanest available, and still only 15 against 21 requests.
  - The global hour suggests the wait doesn't depend on size, but it is one request.
- **Big global requests are untested.**
  - The global hour's run time is mostly fixed overhead, so the run rate for large global requests (45–104 GB of output each) is an assumption: 28 fields/s, the box rate. If it were a third of that, a weekly request would run 44 min instead of 15, adding about 10% to phase 3.
  - The cost check only counts fields. Whether a 45–104 GB result downloads and verifies cleanly in one piece is untested.
  - Submitting one weekly global request before committing to a plan would settle both.
- **Transfer:** one 271 MB file at 18 MB/s.
- **Small samples:**
  - `pl/tmt_spm` has only 2 requests in §2.
  - The 17-variable single levels have 2 full days, below the 3 days asked for. Counting the 6-variable subset, single levels have 6 full days in all.
- **Per-day noise:** each request counts on the day it finished, so pressure-level days carry ±0.5 fields/s of rounding.
- **Cost limits:** checked by estimate on 13 Nov (§6.4), not by submitting requests at the limit. They change with the CDS's workload (forum.ecmwf.int/t/15337).
