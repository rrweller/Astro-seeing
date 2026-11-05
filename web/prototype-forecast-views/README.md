# PROTOTYPE (throwaway): forecast views

**Question it answered:** what should the forecast track look like: a globe stepping hour by hour, a "tonight" summary map, or a meteoblue-style table?

**Verdict (Riley, 2026-11-05):** "I like the layouts and visualizations"; UI details and wording come later. Use **B (tonight summary map) as the landing view, with C's table when a place is clicked, and A's hour slider as an optional layer** on the globe.

**How to run:** open `index.html` in a browser (needs internet for d3 and topojson-client from CDNs). Switch variants with the bottom bar or ←/→; `#radar`, `#tonight-map`, `#table` in the URL pick one.

**What's real:** Sun and Moon positions (NOAA solar approximation; Astronomical Almanac low-precision Moon), checked against meteoblue's Kongsberg page for 5 Nov 2026 to within 3 minutes. **Everything else is synthetic**: cloud, seeing, wind, "Model A–D" and their domains. Coastlines: Natural Earth via `world-atlas@2.0.2` (ISC), inlined.

**Files:** `index.html` (built, standalone), `page.src.html` + `core.js` (sources; `__LAND__` and `__CORE__` are substituted at build). Prototype code: no tests, not for `main` or `dev`. Rewrite properly when building the real viewer. Decision log: D44 in `docs/decisions.md`.
