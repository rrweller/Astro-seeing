# Handoff: CT → cloud planning sessions (2026-10-24)

**Who this is for.** From now on, planning happens in Claude Code cloud sessions using the wayfinder, grill-with-docs, to-spec and to-tickets skills. The CT (Proxmox CT 350) does the data work from the tickets they produce.

**What the planning session can't see.** It can read the repo, but it has no `/data`, `/staging`, CDS access, logs or manifest. Everything below that exists only on the CT, or only in the last CT agent's context, is written down here.

- **Read first:** `AGENTS.md`, then `docs/RESEARCH.md`, then `docs/decisions.md` (D22–D37), then `reports/validation_downloads.md`.
- **The tag** `pre-skills-pivot` marks the last CT commit before the pivot. The CT agent won't commit to `dev` again until Riley brings back the cloud session's results.

## 1. What's running and queued

| What | State | Expected finish | How to check (on the CT) |
|---|---|---|---|
| TMT option A ERA5 (D36): `chile` 2006–2007, `tmt_spm`, `tmt_mauna_kea` | **HELD** (D37): 143 of 146 requests, 4.34 M fields in all. The CDS rejected our parallel submissions under its new sequential-only policy. | not running; ~9–10 days at one request at a time, once the downloader is fixed and the holds released | `pixi run astro status` (counts under `held`) |
| 3 single-level Chile months (`sl/chile/2006-06…08`) | accepted at the CDS before the hold; collected by a one-off `astro download --max-active 1` (no retries, no new submissions), then verify and ingest | within ~4 h of 2026-10-24 22:06 UTC | `tail logs/manual_collect3.log`; `astro status` |
| `astro-boxes.service` | **stopped on purpose** (D37). It runs `scripts/run_boxes.sh`: download → verify → ingest loop, retrying failures up to 5 times. Don't start it until the downloader submits one at a time and backs off on rejections. | — | `systemctl status astro-boxes` |
| `astro-notify.service` | `astro notify-watch`, checks every 10 min, posts to Riley's ntfy topic | always on | `tail logs/notify_watch.log` |
| `astro-manifest-export.timer` | 03:17 UTC daily: copies the manifest to `/data/astro/manifest-exports/` | always on | `systemctl list-timers` |
| tmux | no sessions | — | `tmux ls` |

**What each alert means** (`src/astroseeing/notify.py`):
- **Finished:** nothing left to download, verify or ingest. Held requests don't count. When more work is queued, the watcher re-arms by itself. **Expect a "Finished (143 on hold)" message once the 3 single-level jobs are in: it means the held TMT queue is waiting, not done.**
- **Finished with problems:** the queue drained, but some requests failed 5 times or were refused by ingest.
- **Problem: failed N times:** a request has used up its retries. Look at `last_error` in the manifest, fix the cause, then run `astro retry-failed`.
- **Problem: refused:** ingest refused a large request that isn't a declared validation area (D18, D33). That's expected for any global test until a measurement-only mode exists.
- **Problem: no download progress for N h:** usually the CDS queue or an incident at the CDS. Since D34, jobs that come back 404 (lost by the CDS) are resubmitted automatically.
- **Problem: submitted more than 12 h ago:** the backstop for other ways the CDS can lose a job. Check the job on the CDS website.
- **Problem: download loop not running / NAS not answering:** check `systemctl status astro-boxes` and the `/data` mount. NFS I/O hangs rather than failing.
- **Daily (06:00 UTC):** done, left and failed counts, plus an estimated finish from the last 24 h's throughput.

## 2. Status of each item in `reports/validation_downloads.md` §7

| Item | Status | What isn't written down elsewhere |
|---|---|---|
| Reproductions: Haslebacher (a) | **partial** | Their code and ours agree to 9.4 × 10⁻⁷ on one hour, 25 columns (the smoke test; `reports/haslebacher2022_code_vs_code.json`, `notebooks/haslebacher2022_code_vs_code.py`). Still to do: monthly means over Paranal 2016–2018 (tolerance 0.1%), at settings 0.976, 500 nm, k per site, Table 4 lower level, 28 levels without 70 hPa. Their code runs from `external/haslebacher` (GPL, never copied into `src/`). |
| Haslebacher (b) Table 4 lower levels | not started | Needs surface pressure at the 8 sites, from the time-series fetcher below. |
| Haslebacher (c) written account | not started | — |
| Priyatikanto (Timau 0.79″ ± 0.03″) | not started | The data are complete: `timau@every4d`, 2002–2021, 37 levels, all hours, 42 cells. Three variants of their printed equations are implemented (`m_form`); try them all. A quick check of all 42 cells and all hours, with no surface masking, gave a median of 0.564″. That figure is not comparable with their 0.79″: their value is for the site point, and underground levels have to be masked. |
| Bi (7 sites, ±0.05″) | not started; PDF checked (D35) | Tibet, Haikou and Rongcheng have all 24 hours, so the all-hours, night-hours and launch-hours variants are all possible. Our data stop at 50 hPa, which costs about 0.002″. Use Bi's listed ERA5 points: Rongcheng's coordinates are in the sea in the paper itself. |
| O&S (Paranal ±0.1″) | not started | Paranal pressure and single levels, 2016-04–2018-01, all hours, 5×5 grid. Their SCIDAR campaign dates are needed from the paper. |
| Single levels from the CDS time-series product (D29) | not started (no code) | The product runs in its own CDS slot and takes seconds per point. It lacks lcc, mcc, hcc, zust, ishf and tcwv (D29). |
| ESO DIMM/MASS 2021–2025 | not started (no code) | Source approved (D28; CC BY 4.0, ESO acknowledgement). The WDB forms load and offer `wdbo=csv/download`: `archive.eso.org/wdb/wdb/asm/dimm_paranal/form`, `…/mass_paranal/form`, `…/ambient_lasilla/form` (La Silla DIMM). There is a `max_rows_returned` field (default 1500), so fetch month by month. DIMM data are about 1 row per minute. |
| Chile's extra single levels (lcc, mcc, hcc, zust, ishf, tcwv) | **blocked: needs a code change** (D36) | In `cmd_plan_area`, `src/astroseeing/cli.py` passes `--variables` only for `pl`, so `sl` always gets all 17 variables. Fix: pass `args.variables` for `sl` too (`_parse_variables` already handles it). Then run `astro plan-area chile --start 2021-01-01 --end 2025-12-31 --kinds sl --variables lcc,mcc,hcc,zust,ishf,tcwv --hours night`: ~0.14 M fields, 4–11 h. |
| Global-hour test | not started; needs a measurement-only mode | Ingest would refuse a global request (D18), and the watcher would raise a "refused" alert. It needs a request flag or region that verify checks but ingest skips, without alerting. Then one hour of 29 levels × 5 variables is 145 fields, ~300 MB. |
| TMT login | Riley registering | Credentials go in `/root/.config/astro/tmt.env` (mode 600; the agent will use `TMT_USER` and `TMT_PASSWORD`). Downloads need the login; the data-availability page doesn't. The database has weather, DIMM, MASS, dust, sonic and tower data. It has **no all-sky-camera cloud data**. Usage terms: cite Schöck et al. 2009, PASP 121, 384; emailing TMT about publications is voluntary. No fetcher yet. |
| TMT ERA5 (option A) | **planned and held** (D37) | Variables and levels checked against phase 1's needs (D36). It needs the sequential-downloader fix before it can run. |
| PR to main | done in PR #3 | See §8. |
| CDS token rotation | done by Riley | Checked 2026-10-24 with `check_authentication`: OK. |
| AGENTS.md wording | Riley, in the cloud session | All proposals are in §4. |
| La Palma and model levels (ERA5 complete) | not sized | ERA5 complete is untested here: its cost estimator returned HTTP 500 errors, and the data are on MARS tape, which can take hours per request (D29). |

## 3. CT-only facts

**Paths:**
- **Repo:** `/home/astro-seeing`. Everything runs as root, with `HOME=/root`.
- **pixi:** in `/root/.pixi/bin`, which isn't on `PATH` in non-interactive shells. Prefix with `export PATH=/root/.pixi/bin:$PATH`.

**Data:**
- **NAS:** `/data/astro` (NFS from 10.0.1.10, 3.4 TB, 2.8 GB used on 2026-10-24).
  - `era5/pl/{chile,tibet,timau@every4d,haikou,rongcheng,paranal,smoke-…}`, `era5/sl/{paranal,smoke-…}`, `static/` (per area, plus `static/landmask/`), `manifest-exports/`.
  - All stores passed `scripts/survey_stores.py` on 2026-10-17.
- **Store layout:** one Zarr v3 store per request.
  - Areas use the `cells` layout: only the 5×5 site-box cells.
  - `paranal` and the new `tmt_*` boxes use the `grid` layout.
- **Staging:** `/staging/grib`, 39 GiB of raw GRIB (472 files, 35.7 GB of it Tibet, because the whole 43 × 105 rectangle comes back).
  - **Retention rule:** keep the raw GRIB until the reproductions have used the stores. Then `astro cleanup-raw` deletes files whose ingest is verified.
  - It's on the local SSD (150 GB), not the NAS. Riley asked that nothing be deleted during the pivot.
- **Manifest:** `/root/.local/state/astro/manifest.sqlite`, local, never on NFS.
  - Tables: `requests` (with `cds_started_at` and `cds_finished_at`, so per-job CDS processing times can be measured), `files`, `verifications`, `ingests`, `events`.
  - Watcher state: `notify_state.json` in the same directory.
  - Latest export: `/data/astro/manifest-exports/manifest-20261024T214128Z.sqlite`.

**Logs:** `logs/` (89 MB): `run_boxes.log`, `notify_watch.log`, `astro-YYYYMMDD.log`.

**Services:**
- **Units:** `scripts/systemd/system/*.service` and `*.timer`, installed by `scripts/install_services.sh`. They are system units, because root has no user manager (D26, D32).
- **Restarts:** after a code change, restart `astro-notify`. `astro-boxes` picks up new code on each `pixi run`.

**Credentials (contents never printed or committed):**
- `/root/.cdsapirc`: CDS URL and token, mode 600. Rotated by Riley before 2026-10-24.
- `/root/.config/astro/notify.env`: `NTFY_URL`, mode 600, which the code enforces.
- `/root/.config/astro/tmt.env`: not there yet (Riley).
- `gh` is logged in as rrweller.

**external/:** `external/haslebacher`, the `code` branch at `1da37124f6dd41b9e4d1b24f4b289c02b4aaa760` (also in `external/haslebacher.COMMIT`). It's GPL-3.0: run it from there only.

**papers/:** 20 papers, all opened and indexed with SHA-256 in `papers/INDEX.md`, including the hand-added Bi et al. PDF and the GLOBE manual. Still to add by hand: Racine 2005 and the García-Lorenzo 2011 corrigendum. Not in git.

**CDS behaviour (measured):**
- **Cost:** counted in fields; 60,000 per request for pressure levels, 121,000 for single levels.
- **Running jobs:** one at a time per user, across ERA5 datasets.
- **Queue limit:** about 5 queued per dataset; beyond that it answers "temporarily limited", which we treat as transient.
- **Rate:** 10.3 fields/s over 19 days (26.4 only on day 1). Single levels ran at ~3.7 fields/s. Area size made no visible difference.
- **Lost jobs:** jobs can vanish and return 404 (D34).
- **Policy since 2026-10-22:** submit sequentially. The CDS rejects parallel jobs with "Maximum number queued requests for this dataset has been reached", and repeated invalid submissions may get the account disabled (D37).
- **DNS:** it failed once, briefly, on 2026-10-24 (the CDS host name didn't resolve for a minute). The downloader treats this as transient.

**Harness gotcha:** foreground `sleep` is blocked in Claude Code here. Wait with a background until-loop.

## 4. Pending AGENTS.md wording proposals (exact text)

None of these is in AGENTS.md as of 2026-10-24.

1. **Data safety → Downloads** (D16, D23, D24; `reports/phase1_plan.md` §9, `reports/ct_first_run.md` §10). Proposed: "Validation boxes use month-sized requests, split to the CDS cost limit (60,000 fields for pressure levels; D16, D23); at most 4 requests in flight (the CDS rejects more queued jobs per dataset, D24). Global and regional runs stay one day per request."
2. **Data safety → What gets stored** (D31; `reports/validation_downloads.md` §7). Replace "Validation boxes keep all hours" with: "Validation boxes keep all hours, except areas used only for night-time comparisons, which may be night-only (D31)."
3. **Code → Environment** (`reports/phase1_plan.md` §9). Add: "CDS access uses `ecmwf-datastores-client` (the library behind `cdsapi 0.7.7`) asynchronously, reading `~/.cdsapirc`."
4. **Environment** (`reports/ct_first_run.md` §10; D26, D32). Proposed: "The repo is at `/home/astro-seeing` and everything runs as root. Long jobs run as system-level systemd services (`astro-boxes`, `astro-notify`, `astro-manifest-export.timer`; D32); systemd user units need a non-root user or lingering. tmux is installed via `pixi global`." This also replaces "Long jobs: run under systemd user services or `tmux`" under Code.
5. **New, from this handoff:** under "Working with Riley", say that planning happens in cloud sessions and the CT works from tickets, if that is the new rule.

## 5. Open questions for Riley, and what each blocks

| Question | Blocks |
|---|---|
| **Sequential-downloader fix (D37):** `max_active` 1 by default; treat "Maximum number queued requests … reached" as a queue-limit rejection; back off 30–60 min after any rejection, cap rejections per day, and alert. A ticket for the CT. | **all CDS downloads**, starting with the held TMT queue. Running the current loop risks the account: ECMWF may disable accounts that keep submitting invalid requests (forum.ecmwf.int/t/15481) |
| **CDS terms of use, Art. 1, change on 2026-10-28.** Using the CDS after that counts as acceptance; anyone objecting must tell ECMWF before 27 Oct (forum.ecmwf.int/t/15374). | any CDS use after 28 Oct |
| **Phase 2 via global downloads?** The CDS works per field, not per area, so 8 separate regions take ~64–76 days, against ~8–9.5 for the whole globe (`reports/validation_downloads.md` §4). A gate 1 decision. | the phase 2 and phase 3 plans, and how the downloader should be built for global days |
| **The CLI fix for single-level `--variables`** (§2): a ticket? | Chile's extra single levels, and with them the W71 and cloud-layer experiments with ESO data |
| **A measurement-only mode** for test requests (§2): a ticket? | the global-hour test, and the gate 1 projections |
| **Time-series fetcher, or main-slot single levels?** For sites without single levels (Timau, Tibet, Haikou, Rongcheng, Chile 2021–2025). The fetcher is new code; main-slot downloads cost queue time (~1 h per 13,000 fields at 3.7 fields/s). | Haslebacher (b); masking underground levels by surface pressure (orography from the static stores is an alternative) |
| **The TMT login** (in progress) | fetching the TMT DIMM/MASS data; calibration and the terrain experiment at the TMT sites |
| **When to delete the raw GRIB** (41.6 GB on `/staging`) | nothing yet; `/staging` has ~100 GB free |
| **Which experiments get which sites and periods** (La Palma, model levels) | sizing the next download batch |

## 6. Fragile or unfinished in the code

- **Rejections (D37):** the downloader submits up to 4 requests at once and resubmits right after a rejection. The CDS now asks for sequential requests and may disable accounts that keep sending invalid ones. The queue-limit matcher in `src/astroseeing/download/cds.py` (`QUEUE_LIMIT_MESSAGE`) knows only the old wording. **Fix this before any unattended download.**
- **CLI variable selection:** `astro plan-area` silently ignores `--variables` for single levels, and `astro plan-box` has no `--variables` at all, so it always requests every variable (§2).
- **Stale rate in the log:** `plan-area` still reports "~N days of CDS processing at 26.4 fields/s". The measured rate is 10.3, so its estimates are 2.5× optimistic. The constant belongs in config.
- **No measurement-only mode** for test requests (§2).
- **Hard-coded test:** `tests/test_areas.py::test_configured_areas_cover_the_papers_grid_points` asserts the exact set of area names. Adding an area to `configs/validation_areas.yaml` fails it, which is why the new TMT boxes use `plan-box`. Better to assert a subset.
- **Misleading counter name:** the QC counter `cells_dropped_not_land` also counts cells outside the site boxes in area stores. Cosmetic.
- **Lost-job detection:** only HTTP 404 is detected (D34). Other ways the CDS might lose a job are caught only by the 12 h "stuck" alert, which needs a person.
- **Notifications:** the finish estimate uses the last 24 h of throughput only. It is noisy when the CDS rate swings (it ranged 5–16 fields/s per day).
- **NFS hangs:** ingest probes `/data` in a child process with a timeout. A hang in the middle of a write still blocks that process, and systemd's restart plus the manifest's resumability are the only recovery.
- **Reviewer request:** `gh api …/requested_reviewers -f "reviewers[]=Copilot"` returns an empty list even when it works. The other spellings fail with HTTP 422.
- **Not built yet:** time-series single levels, ESO and TMT fetchers, reproduction notebooks (except Haslebacher's single hour), nightly aggregation, tiles and the web viewer.
- **With more time:** fix the first three items, add a `--dry-run` that prints fields, days at the measured rate and GB before anything is queued, and make the area-name test a subset check.

## 7. Retro: what took longer than it should have

- **Six Copilot rounds on PR #2.** The PR held a whole session's work: the land mask, real-CDS fixes, validation areas, the watcher and the services. The watcher and refusal logic has many edge cases, and each round found new ones in code I'd added to fix the round before. Smaller PRs, plus a self-review against a checklist of states (failed, refused, held, retry pending, a queue that drains with problems), would have caught most of them in one pass.
- **Lost CDS jobs: 5 days.** I had tested the downloader against our fake backend and the CDS failures I'd seen, not against a job disappearing. A 404 was treated as transient, so the loop polled forever. The watcher's alert fired correctly every 12 h, but nobody acts on an alert while no session is open, and it didn't say what to do. The 3 dead jobs also took 3 of the 4 queue places, which halved throughput for the other 47 requests. Lessons: treat any unexpected status as a reason to resubmit after a bound, and make each alert say what to do next.
- **Planning on the first day's throughput.** The 26.4 fields/s from the first 9 files went into the plan and the D29 estimates. The sustained rate was 10.3. Planning numbers should come from at least several days.
- **Sizing before measuring.** The phase 1 plan's "1–3.5 days" of downloads came from the cloud session, before any CDS measurement. It turned out to be ~37 days, which forced a re-plan (options A, B and C) and a day of back-and-forth.
- **The CDS policy change, 2026-10-24.** I queued 146 requests and started the service without first checking ECMWF's forum for changes since the last run. The CDS had moved to sequential-only requests two days earlier, and 29 jobs were rejected in minutes before I stopped the loop. Lesson: before restarting a download campaign after a pause, submit one request, check that it's accepted, and read the CDS announcements.
- **Questions to Riley.** My first CT report's questions were too terse, and Riley had to ask for clearer ones. Since then, each question states the context, the options with numbers, and a recommendation.
- **The Bi et al. PDF.** MDPI blocks non-browser clients, so the check waited three weeks for Riley to save the file by hand. Asking for it at bootstrap would have avoided that.

## 8. PR #3

**Merged** 2026-10-24 21:52 UTC as squash commit `c00bce0` on `main`. Main was then merged back into `dev` (`239c186`), and the two have the same content.

- **Round 1 (Copilot), 2 findings, both real and fixed in `f7188ed`:**
  - `scripts/survey_stores.py` ignored `raw_deleted` requests when building the expected coverage;
  - it never compared regions that are missing from disk against the manifest. It now walks the union of manifest and on-disk regions and fails on a region with no stores (tested with an empty data root: exit 1).
- **Round 2:** no new findings.
- **Nothing left over.**

## 9. What I'd do next, in order, and why

1. **Make the downloader sequential and safe on rejections (D37), then release the TMT holds** and confirm with `scripts/survey_stores.py` when they're done (~9–10 days at one request at a time). The CDS queue is the bottleneck, and the account is the single point of failure.
2. **Fix single-level `--variables`, then queue Chile's extra single levels.** It's a one-line change, unblocks the W71 and cloud-layer experiments with ESO data, and is ~0.14 M fields of queue time.
3. **Reproductions in this order: Haslebacher (a) monthly → Priyatikanto → Bi → O&S.** The data are already on the NAS, and they're the core of gate 1. Haslebacher first, because an independent code checks our O&S implementation. Then Priyatikanto, a single site with one clear target. Bi has several variants to try. O&S needs campaign dates from the paper.
4. **Time-series single-level fetcher.** Needed for Haslebacher (b) and for surface masking at sites without single levels. It doesn't use the main queue.
5. **ESO fetcher, then the TMT fetcher** once the login exists. This is the calibration data (plan task 12): fit on held-out years.
6. **Measurement-only mode, then the global-hour test.** This settles the phase 2 and phase 3 projections, which decide whether phase 2 is cut out of global downloads.
7. **Experiments** (pressure vs model levels, terrain-aware, cloud above height, 3-hourly, ground-layer options), then the **good-night proposal [ASK]**, then **gate 1** (`reports/phase1.md`). Size the La Palma and model-level downloads once the experiment designs are fixed.
