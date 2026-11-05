# Proposal: AGENTS.md changes for the forecast track (D43, D44)

**Status: all seven items approved by Riley on 2026-11-05 and applied (D46).** Item 2 was widened to "D44 and D45" when ICON global was approved in D45.

Principle: AGENTS.md states the rule and points to the decision; the detail lives in `docs/decisions.md` (D43, D44) and later in the forecast spec, so each fact has one home.

---

## 1. Mission (replace the first paragraph and the "Main layer" lead-in)

**Now:**
> Build a self-hostable web app: a 3D globe you can drag and zoom, with toggleable layers.

**Proposed:**
> Build a self-hostable web app: a 3D globe you can drag and zoom, with toggleable layers, serving two products on one shared physics engine (D43):
>
> - **Forecast track:** tonight's cloud and seeing, forecast model by forecast model, for any place the user picks.
> - **Historical track:** the climatology of good nights for every land location, described below.
>
> Both tracks go ahead in parallel. They share `src/astroseeing/physics/` and differ in data and UI.

The rest of the Mission section stays as it is, under the historical track.

## 2. Working with Riley → Stop and ask [ASK] (add one bullet)

> - adding a forecast source, or a seeing-measurement source, beyond those approved in D44 and D45.

(D44 approved GFS, ICON-EU, MEPS and ECMWF IFS open data; ESO is D28.)

## 3. Data safety → What gets stored (add after the current bullet)

> - **Forecast track:** download only the fields a run needs, into `/staging`. Delete raw forecast files as soon as their derived values are computed and verified; `/data` keeps computed values only, under the retention in D45. The night mask is a historical-track rule: forecasts keep every hour for their area (D43).

## 4. Secrets and licences (add one bullet)

> - **Validation-only sources** (Maunakea MKWC, ING R2D2, Calar Alto; D44): use them for internal checks only. Anything published uses ESO's data (CC BY 4.0, D28) or our own.

## 5. Architecture (add after the pipeline line)

> Forecast pipeline: `fetch run (subset) → verify → physics per forecast model (pressure levels) → hourly values per cell → tonight summary → web`. It reuses the physics module, the manifest (for provenance) and the verify step; sources and their level counts are in D44.

## 6. Phases and gates (rename and add)

- Rename "## Phases and gates" to "## Historical track: phases and gates". The text of phases 1–3 is unchanged.
- Add a new section before it:

> ## Forecast track: milestones
>
> Each milestone is approved by Riley before the next starts [ASK].
>
> - **F1, private, Kongsberg.** The box around Kongsberg (D44), four runs a day from the D44 sources; the hourly multi-model table, the tonight map and the verdict (prototype verdict, D44); seeing from both Cₙ² models labelled uncalibrated; a nightly Paranal comparison against ESO. Runs unattended on the CT.
> - **F2, any place in a wider domain, on the globe.** Domain grown from measured timings; regional and global sources blended at domain edges (D45); model-level seeing where open.
> - **F3, global and public.** Attribution panel, hosting via Pangolin on Riley's domain, calibrated seeing once the historical track's calibration exists.

## 7. Decisions already made (two edits)

- "**Data source:** ERA5 via CDS in GRIB…" → add: "Forecast track: open forecast-model output per D44."
- "**Layers:** … Not now: moonlight, light pollution, τ₀/θ₀ layers." → add: "(historical layers). The forecast shows Moon rise, set, phase and altitude (D43)."

---

**Not proposed:** the Environment section (the forecast runs on CT 350 like everything else, D43) and the "Open decisions" list (the forecast's open questions live on its wayfinder map).
