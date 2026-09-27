# Decision log

Format: date · decision · options · evidence · choice · who decided. "Agent
(provisional)" means the agent chose it inside the approved phase 1 bootstrap
and it is open to Riley's review; anything marked **[ASK]** waits for Riley.

Decisions made before this log existed are in AGENTS.md "Decisions already made
(2026-09-26)".

---

## 2026-09-27 — Phase 1 bootstrap (cloud session, no CT access)

### D1. Environment: Python 3.13 on conda-forge via pixi, lock for linux-64
- **Options:** Python 3.12 or 3.13; lock for linux-64 only, or also macOS/Windows.
- **Evidence:** every dependency (python-eccodes 2.48, zarr 3.4, skyfield 1.54, cdsapi 0.7.7, ecmwf-datastores-client 0.5.3) resolved for 3.13 on conda-forge; the CT is linux-64.
- **Choice:** Python 3.13, linux-64 only, pixi 0.81 workspace, `pixi.lock` committed. Add platforms later if Riley wants to run on another machine.
- **Who:** agent (provisional).

### D2. CDS client: ecmwf-datastores-client, used asynchronously
- **Options:** `cdsapi.Client().retrieve()` (blocking), or submit/poll/download by request id with `ecmwf.datastores.Client`, the library `cdsapi 0.7.7` wraps for the current CDS.
- **Evidence:** a blocking retrieve cannot resume a request still queued at the CDS after a restart; the datastores client exposes `submit`, `get_remote(id).status`, `get_results(id).download` and `estimate_costs` (read from the installed source).
- **Choice:** the async path; the CDS request id is stored in the manifest the moment the CDS accepts a request. Credentials are read from `~/.cdsapirc` (mode 600 enforced); the key is never logged or stored. `cdsapi` stays installed.
- **Who:** agent (provisional).

### D3. Column discretisation
- **Choice:** Cₙ² constant per slab between neighbouring valid levels; T_mid = mean of the two levels, P_mid = √(p₁p₂) (log-p midpoint), θ_mid = T_mid(1000/P_mid)^0.286; gradients by finite difference; S² = (Δu/Δz)² + (Δv/Δz)². Levels with p > surface pressure or Z ≤ orography are masked and counted. Non-increasing heights in valid slabs raise an error instead of being repaired.
- **Evidence:** RESEARCH §4.3 prescribes slabs and the log-p midpoint; the rest is our choice.
- **Who:** agent (provisional).

### D4. Troposphere/stratosphere switch for HMNSP99
- **Options:** WMO lapse-rate tropopause with or without a pressure bound; how to handle ERA5's sparse levels near the tropopause.
- **Evidence:** the WMO definition (RESEARCH §4.4). A deep low-level isothermal layer satisfies the WMO criterion without a bound (tested).
- **Choice:** the lowest level with p ≤ **500 hPa** whose lapse rate to the next level is ≤ 2 K/km, and whose average lapse rate to every level within 2 km, and to T linearly interpolated at +2 km, is ≤ 2 K/km. If none is found, all slabs use troposphere coefficients and the column is counted (`tropopause_not_found`). Slabs whose base is at or above the tropopause level use stratosphere coefficients. The 500 hPa bound is our choice and needs checking against the polar winter tropopause *[check]*.
- **Who:** agent (provisional).

### D5. Osborn–Sarazin unstable layers (N² ≤ 0)
- **Options:** `zero` (Cₙ² = 0), `abs` (use |∂θ/∂z|), `nan`.
- **Evidence:** in the stable closed form Cₙ² ∝ S^(4/3) |∂θ/∂z|^(4/3), so Cₙ² → 0 continuously as N² → 0⁺ under both `zero` and `abs`. The O&S paper does not say.
- **Choice:** default `zero`, count firings (`os_unstable_layers`). Compare `zero` and `abs` in the phase 1 ground-layer experiment.
- **Who:** agent (provisional).

### D6. Cloud-above-height overlap
- **Choice:** implement random, maximum and maximum-random (Geleyn & Hollingsworth 1979); default max-random until the phase 1 consistency check (C at the ERA5 surface vs ERA5 `tcc`) picks one. cc outside [0, 1] is clipped and counted; invalid levels count as clear and are counted.
- **Who:** agent (provisional); final rule **[ASK]** with phase 1 evidence.

### D7. O&S ground-layer relocation generalised to any height
- **Choice:** J(h) = I(max(h, z_g + 1 km)) + [I(z_g) − I(z_g + 1 km)], with I(x) = ∫ₓ^top Cₙ² dz. This equals O&S at the site (h ≥ z_g + 1 km), gives the full model column for valley pixels (no double counting), and stays continuous and non-increasing in h (property-tested).
- **Evidence:** O&S §5.4 (relocation of 926–1926 m to 2635–3635 m at Paranal); the split at 1 km is from their §5.7.
- **Who:** agent (provisional); ground-layer treatment itself remains an open **[ASK]**.

### D8. Darkness and the night mask
- **Choice:** Sun GHA and declination from Skyfield (DE440s, SHA-256 pinned), tabulated every 10 min and interpolated (error < 0.5″, tested); geometric altitude, no refraction (as Skyfield's `dark_twilight_day`). Dark minutes counted at minute midpoints of each night window (local mean noon to local mean noon, keyed by evening date). **Ingest night mask:** keep hour t if the Sun is below −12° at any minute in [t − 30 min, t + 30 min), so every hour that touches astronomical darkness is kept with margin (tested).
- **Evidence:** vs Skyfield `almanac.dark_twilight_day` at 9 sites × 6 dates: crossings within 3.7 s, minute counts within 0.96 min.
- **Who:** agent (provisional).

### D9. Unix time → Skyfield time
- **Choice:** pass whole days plus seconds of day to `ts.utc`. `ts.utc(1970, 1, 1, 0, 0, u)` counts leap seconds and lands 27 s early in 2023 (found and tested).
- **Who:** agent.

### D10. Zarr layout for ingested ERA5
- **Options:** one store per request, per month, or per year; append vs write-once.
- **Choice (phase 1):** one Zarr v3 store per manifest request at `/data/astro/era5/{kind}/{region}/{period}.zarr`, written once to a temp directory, read back bit-for-bit, fsynced, renamed, and read back again. Never overwritten (same content → no-op; different content → error). float32 (GRIB is 16-bit packed, so nothing is lost), Blosc zstd level 5 with byte shuffle, chunks ≤ 4 MB with time and level whole, one shard per array (one file per variable per request); the shard is the array shape rounded up to whole chunks, because Zarr v3 needs shards to be multiples of chunks (e.g. 721 latitudes → 23-row chunks → 736-row shard; found in PR review). No consolidated metadata (not in the v3 spec). A `cells` layout (land cells plus a counted night mask) is implemented for phase 2/3. Whether day-sized stores are right for the global run is a phase 2 decision.
- **Who:** agent (provisional).

### D11. Manifest location and export
- **Choice:** `~/.local/state/astro/manifest.sqlite` (WAL mode); opening it on a network filesystem raises. The nightly export backs up to a local temp file with the SQLite backup API, then copies, fsyncs and renames onto `/data/astro/manifest-exports/manifest-<UTC stamp>.sqlite`. SQLite never writes on NFS.
- **Evidence:** RESEARCH §9 pitfall 16.
- **Who:** agent (provisional).

### D12. Raw GRIB deletion
- **Choice:** delete a raw GRIB only if it is under the staging directory, its ingest is recorded as verified, and the store still matches the arrays rebuilt from that GRIB bit-for-bit at deletion time. The file row and the `raw_deleted` state are then written in one transaction. If a run dies between deleting the file and that write, the next run checks the store against its recorded content hash and finishes the transition (or skips it if the check fails). Nothing under `/data` is ever deleted by code.
- **Who:** agent.

### D13. c_p
- **Choice:** c_p = 3.5 R_d (R_d = 287.06), so g/c_p = 9.7607e-3 K/m. It only enters through g/c_p; RESEARCH §4.9's O&S values (N² = 1.279e-4, Ri = 5.12) are reproduced with it. *[check]* that 3.5 R_d is the IFS convention.
- **Who:** agent (provisional).

### D14. ERA5 attribution text
- **Choice:** copy the wording from the CDS dataset pages' "Citation and attribution" block (read via the CDS catalogue API) into `provenance.py` and RESEARCH §7; every store carries it. The first version of `provenance.py` had text written from memory; it was replaced with the verified wording before any commit.
- **Who:** agent.

### D15. Corrections to docs/RESEARCH.md from the PDFs (Riley to review)
1. §3.3: the O&S free-atmosphere/ground-layer split is **1 km** above the observatory (O&S §5.7, Fig. 9), not "about 1–2 km".
2. §3.4: Haslebacher et al. use **ε = 0.976 λ/r₀** at 500 nm (eqs. 5–6); Euler-forward integration; Table 4 lower levels recorded.
3. §3.2: Priyatikanto et al. interpolated linearly to 5 hPa steps (10–1000 hPa) before computing, and their printed eqs. 4, 6 and 7 differ from §4.4 (sign of a₃, ∂θ/∂h with P/T², θ with 100 hPa). All three variants are implemented (`Cn2Model`) for the reproduction.
4. §6.4: TMT Table 2 checked; Mauna Kea 13N θ₀ = 2.69″ filled in.
5. §7: CDS variable names confirmed on the live forms; attribution text and request keys added.
6. §4.1: measured nights-per-year added next to the estimates.
- **Not verified here:** Bi et al. 2023 (MDPI blocks this container, HTTP 403). Check §3.1 and §4.4 against the PDF on the CT.
- **Who:** agent; Riley to confirm.

### D16. Request granularity for validation boxes **[ASK]**
- **Options:** day-sized requests (AGENTS.md) or month-sized for small boxes.
- **Evidence:** phase 1 needs roughly 20,000 box-days (see `reports/phase1_plan.md`); at one request per day per dataset that is about 40,000 CDS requests, each queued separately. A 5×5-point month of pressure levels is 29 × 5 × 24 × 31 ≈ 108,000 fields; whether the CDS accepts that is what the smoke test's cost estimate will tell.
- **Choice:** code supports both (`--granularity month`); the default stays `day` until Riley decides.
- **Who:** Riley.

### D17. Missing values in ERA5 GRIB
- **Choice:** a bitmap-missing value fails verification, except for variables where missing is physically expected. For now that is only `cbh` (no cloud → no cloud base). Those counts are recorded as warnings, decoded to NaN, and stored in the Zarr `qc` attribute (`grib_missing_values_<var>`). The grid-size check uses `numberOfDataPoints`, because `numberOfValues` excludes missing points (found by the test). If the smoke test shows other variables with legitimate gaps, they get added here explicitly, never silently.
- **Who:** agent (provisional).

### D18. No unmasked ingest outside validation boxes
- **Options:** let the CLI ingest any request on the full grid, or require the land/night mask for anything that is not a validation box.
- **Evidence:** AGENTS.md "What gets stored": only land cells (with the 1 km buffer) and night hours; validation boxes keep all hours. The land mask is not built yet (its source is an open [ASK]). Copilot's review of PR #1 flagged that the CLI would store any request unmasked.
- **Choice:** without a mask function, `ingest_pending` stores only requests of at most 121 grid points (11×11, i.e. validation boxes). Larger requests stay in `verified`, are logged and counted (`refused_unmasked`), and the CLI exits non-zero. Cleanup refuses to delete the raw file of a `cells`-layout store unless it is given the same mask function. `download`, `verify`, `ingest` and `cleanup-raw` now exit non-zero when anything failed, so systemd and scripts see it.
- **Who:** agent (provisional).
