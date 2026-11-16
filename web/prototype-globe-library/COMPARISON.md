# Globe library comparison (ticket #25): evidence so far, no choice made
Measured 2026-11-16 in headless Chromium with SwiftShader (software GL) on a cloud container. Library facts are from the packages' own files (LICENSE, package.json, .d.ts, CHANGELOG, migration guide). Not yet reacted to by Riley.

| Criterion | MapLibre 5.24.1 | MapLibre 6.18.0 | CesiumJS 1.147.0 |
|---|---|---|---|
| Licence | BSD-3-Clause | BSD-3-Clause | Apache-2.0; LICENSE.md also names patents (not legal advice) |
| Bundler needed (D52) | No (UMD script) | No (ESM `import`; worker auto-located) | No (prebuilt `Build/Cesium/Cesium.js`, set `CESIUM_BASE_URL`) |
| Needs WebGL2 | no | yes (v6 dropped WebGL1) | not checked |
| Page load, raw / gzip (this page, nothing cached) | 1.31 / 0.36 MB | 1.86 / 0.52 MB | 6.43 / 1.92 MB |
| Vendored size in repo | 1.1 MB | 1.7 MB | 11 MB (after pruning `Assets/Textures`) |
| Requests to other origins / paid services | 0 | 0 | 0 (needs `baseLayer:false`; default base layer is ion imagery) |
| First cell tile painted | ~0.2 s | ~0.2 s | ~0.75 s |
| Per-cell blocks, no interpolation | yes: `raster-resampling: nearest`; tiles from `addProtocol` | same | yes: `magnificationFilter: NEAREST`; custom `ImageryProvider`, geographic tiling |
| Checkerboard at globe, 6x, deep zoom | sharp, square | not rerun | sharp, square |
| Reaches the poles | **No true cells beyond 85.05°** (Web Mercator tiles; view centre clamps to ±85.051°; cap is the edge row smeared to the pole) | same engine, not rerun | yes, true cells to the pole |
| Hour slider | works (`setTiles` reloads) | works | works (new layer swapped in) |
| 0.25° box over a 3° world grid | works | not rerun | works |
| Click to pick, drag does not pick, phone tap, no horizontal overflow (390 px) | pass | click/drag pass | pass |
| Terrain from DEM generated in the browser | works: `raster-dem` + `addProtocol`; engine elevation 2827 m vs 4 x 689 m = 2756 m (2.6% off) | **hung under software GL, untested** | draws; `globe.getHeight` check **unresolved** (my compare ignored that exaggeration may be included) |
| Warnings seen | "calculateFogMatrix not supported on globe"; hillshade+terrain on one source | | default "Cesium ion" logo credit (settable via `CreditDisplay.cesiumCredit`) |

## Not established
- Phone performance: frame-rate runs under software GL were erratic (0.7–13 fps, no ranking possible). Needs a real phone.
- Whole globe at 0.25° (1 M cells): not tested.
- Self-hosted terrain at 30 m for Cesium (quantized-mesh) and for MapLibre at scale: not tested. MapLibre docs list a quantized-mesh example (title verified, not run).
- A MapLibre workaround for the polar cap: not tested.
- MapLibre states Semantic Versioning; I found no stated support window for v5 (5.24.1 and 6.18.0 were both published 2026-11-11).
