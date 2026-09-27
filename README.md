# Astro-seeing

A self-hostable 3D globe of good astronomical viewing nights per year, built from
ERA5 reanalysis profiles (seeing and cloud) and Copernicus DEM terrain.

- **Start here:** `AGENTS.md` (mission, rules, phases) and `docs/RESEARCH.md` (physics, sources).
- **Current plan:** `reports/phase1_plan.md`. **Decisions:** `docs/decisions.md`.
- **Running on the CT:** `docs/handoff_ct.md` (start here on the CT) and `docs/ct_runbook.md`.

## Quick start

```bash
pixi install --locked
pixi run test        # known-answer, property, darkness and pipeline tests
pixi run lint
pixi run astro --help
```

## Layout

```
src/astroseeing/
  physics/     column prep, Cn2 models, J(h), optics, cloud overlap, ground layer
  solar/       Sun position and astronomical darkness (Skyfield)
  download/    CDS requests and the resumable downloader
  verify/      GRIB verification
  ingest/      GRIB → Zarr v3 (atomic, verified), raw cleanup
  manifest.py  SQLite manifest (request → file → checksum → verification → ingest)
  cli.py       the `astro` command
configs/  era5.yaml (datasets, variables, levels), sites.yaml (validation sites)
scripts/  CT bootstrap, paper fetcher, Haslebacher clone, systemd units
tests/    pytest + hypothesis
```

Data attribution: ERA5 (Copernicus Climate Change Service, CC-BY 4.0) and
Copernicus DEM; the exact wording is in `src/astroseeing/provenance.py`.
