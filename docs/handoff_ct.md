# Handoff: from the cloud bootstrap session to Claude Code on CT 350

- **Written:** 2026-09-27, at the end of the cloud session that did phase 1 step 1 (bootstrap).
- **Merged to `main`:** PR rrweller/Astro-seeing#1 (the bootstrap, after two Copilot reviews; all eight findings fixed).
- **For:** Claude Code running on CT 350 `astro-seeing`, which has `/data`, `/staging` and (once Riley sets it up) CDS access. The cloud session had none of these.

## 1. Where things stand

**Built and tested (111 tests, `ruff` clean):**
- Physics: Cₙ² models (Tatarskii + HMNSP99, Osborn–Sarazin), WMO tropopause, exact J(h), optics, cloud cover above a height (three overlap rules), ground-layer options, model-level heights. Every value in RESEARCH §4.9 reproduces to its printed digits.
- Darkness: Skyfield-based (DE440s, checksum-pinned); within 3.7 s / 0.96 min of `almanac.dark_twilight_day`.
- Data pipeline: SQLite manifest, resumable CDS downloader, GRIB verification, atomic Zarr v3 ingest with bit-for-bit read-back, crash-safe raw cleanup, the `astro` CLI (`pixi run astro --help`).
- Scripts: `scripts/ct_bootstrap.sh`, `scripts/fetch_papers.py`, `scripts/clone_haslebacher.sh`, systemd user units in `scripts/systemd/`.
- Only synthetic GRIB and a fake CDS have been used so far. **Nothing has touched real ERA5 data yet.**

**Decided by Riley (see `docs/decisions.md`):**
- **D16:** validation boxes use **month-sized** CDS requests (`plan-box` defaults to `month`). Global and regional runs stay day-sized. AGENTS.md still says "day-sized requests"; the exception is proposed in `reports/phase1_plan.md` §9 for Riley to add. Don't edit AGENTS.md yourself.
- **D19:** the reproduction tolerances in `reports/phase1_plan.md` §5 are fixed.
- **D20:** land mask from `global-land-mask` (checked: lakes count as land, floating ice shelves as sea; 28.905% land; 365,088 ERA5 cells with land before the 1 km buffer).

**Provisional choices of the cloud session**, to confirm or revise with real data (each logged in `docs/decisions.md`): tropopause 500 hPa bound (D4), O&S unstable-layer rule `zero` (D5), max-random cloud overlap (D6), O&S relocation generalised to any height (D7), c_p = 3.5 R_d (D13), unmasked ingest only for ≤121-point boxes (D18).

**Not verified yet:**
- Bi et al. 2023 (MDPI blocked the cloud container): RESEARCH §3.1, §4.4 and §6.1 still need checking against the PDF.
- T_v = T(1 + 0.608 q) and c_p = 3.5 R_d against ECMWF's own recipe.
- The cos ζ factor in RESEARCH §4.5's τ₀ formula. Our product is zenith-only, so it doesn't matter yet.

## 2. Read first, in full and in this order

1. `AGENTS.md`: mission, rules, [ASK] triggers, phases.
2. `docs/RESEARCH.md`: physics and sources. It has 2026-09-27 corrections from the PDFs (listed in decision D15).
3. This file.
4. `reports/phase1_plan.md`: tasks, order, tolerances, volumes.
5. `docs/decisions.md`: D1–D21.
6. `docs/ct_runbook.md`: the exact commands.

## 3. Git workflow

- **Branches:** work on `dev`. If it doesn't exist, create it from `main` and push it (`git switch -c dev && git push -u origin dev`). Make small commits with clear messages.
- **Main:** `main` only gets checkpoints that Riley approves, via a PR from `dev`. Never force-push `main`.
- **Credentials:** check `git push` works early. Push credentials are Riley's to set up; ask if pushing fails.
- **Never commit:** `papers/`, `external/`, data, `~/.cdsapirc` or tokens (`.gitignore` covers them; check `git status` before committing).

## 4. First tasks, in order

1. **Bootstrap the CT.** Run `bash scripts/ct_bootstrap.sh 2>&1 | tee logs/bootstrap.log`.
   - Expect `/data/astro` on `nfs4`, the state directory on a local filesystem, and all tests passing.
   - If pixi is missing, use its user-level installer (runbook §1).
   - If `/staging` isn't writable, or anything needs root, sudo or a host change, stop and ask Riley.
   - Record what the machine actually is (OS, cores, RAM, free disk on `/data`, `/staging` and root) for the first report.
2. **Papers.** Run `pixi run python scripts/fetch_papers.py` and check `papers/INDEX.md`.
   - If the Bi et al. PDF downloaded, check RESEARCH §3.1, §4.4 and §6.1 against it: λ = 550 nm, the 5.25 coefficient, the lapse-rate typo, Tables 2–3, which ERA5 product and levels, and how they switch troposphere/stratosphere.
   - The PDF wins: fix the note, log it in `docs/decisions.md`, and tell Riley.
3. **Haslebacher et al.** Run `bash scripts/clone_haslebacher.sh`, then read `calc_model_seeing_values.py` and whatever it reads. Work out exactly which ERA5 inputs, variables, levels, periods and time resolution their outputs need, and the download volume. **Over 50 GB → [ASK].** Their code is GPL-3.0: run it from `external/`, never copy it into `src/`.
4. **CDS smoke test.**
   - Check `~/.cdsapirc` exists with mode 600; never print its contents. If it's missing, or a request fails with an authentication or licence error, ask Riley: the account, token and the three ERA5 licence acceptances are his to do.
   - Run `pixi run astro cds-smoke-test` inside `tmux` and commit `reports/cds_smoke_test.json`.
   - Before planning downloads, also ask the CDS (`estimate_costs`) whether a **month-sized** 5×5 validation-box request is within its limits. If not, fall back to day-sized requests for boxes and log it.
5. **Update the plan's numbers.** Put the measured queue time, throughput, bytes per box-day and cost limits into `reports/phase1_plan.md` §6. If phase 1 downloads would then exceed 50 GB or 24 h of wall time beyond what the plan lists, **[ASK]**.
6. **Land mask (plan task 7).**
   - Add `global-land-mask` to `pixi.toml` (PyPI dependency) and re-lock.
   - Build the 1 km buffer. Mind that 1 km spans more 30″ pixels in longitude at high latitudes.
   - Derive the ERA5 cell list and compare with 365,088 cells unbuffered and 367,051 buffered.
   - Write the result atomically under `/data/astro/static`, with provenance and the GLOBE citation (D20).
   - Add tests and write a short report.
7. **Continue phase 1** (plan §4, tasks 8–14): validation-box downloads, reproductions (one notebook per paper), experiments, calibration, then the good-night proposal. Write a report in `reports/` at each milestone.

## 5. Rules that bite (quick reference; AGENTS.md is authoritative)

- **[ASK] before:** a new phase; downloads over 50 GB or 24 h not already in an approved plan; deleting or overwriting anything under `/data`; changing a validated method or constant; a data source with new licence terms; anything that costs money.
- **Only Riley can:** set up CDS credentials and licences, GitHub credentials, the TMT database login, and make any Proxmox or QNAP change.
- **Compute:** at most 5 worker processes; long jobs in `tmux` or systemd user units, logging to `logs/`, resumable.
- **NAS:** if the NAS drops, I/O hangs instead of failing. Keep the probes and timeouts, and never put SQLite on `/data`.
- **No silent fixes:** count and log every mask, clip or fallback (`QCCounts`).
- **Sources:** verify every link before citing it; prefer peer-reviewed papers and primary docs; never Grokipedia or other AI-generated sites; say plainly when unsure.
- **Decisions:** log every non-trivial decision in `docs/decisions.md` (date, options, evidence, choice, who).

## 6. Known traps (already fixed; don't reintroduce)

- **Leap seconds:** `ts.utc(1970, 1, 1, 0, 0, unix_seconds)` counts leap seconds and lands 27 s early; use `solar.sun.unix_to_time`.
- **GRIB missing values:** eccodes `numberOfValues` excludes bitmap-missing points; use `numberOfDataPoints` for grid size.
- **Cloud base height:** ERA5 `cbh` is legitimately missing where there is no cloud (D17). If the smoke test shows other variables with gaps, add them explicitly.
- **Zarr sharding:** Zarr v3 shards must be whole multiples of chunks (721 latitudes → 736-row shard), and chunks must be ≥ 1 even for empty arrays.

## 7. First report back

At the end of the first CT session, write `reports/ct_first_run.md` covering:
- the machine facts;
- the bootstrap result;
- papers fetched and the Bi et al. check;
- Haslebacher's data needs;
- the smoke-test numbers;
- the updated volume and time estimates;
- the questions for Riley.

Summarise it in chat and commit it to `dev`.
