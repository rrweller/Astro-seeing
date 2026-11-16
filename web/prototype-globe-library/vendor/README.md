# Vendored libraries (prototype, ticket #25)
Obtained with `npm pack`; each tarball's sha512 matched the registry's `dist.integrity` (2026-11-16).
| Library | Version | Licence (from the package's own LICENSE file) | Files used |
|---|---|---|---|
| maplibre-gl | 5.24.1 | BSD-3-Clause | `dist/maplibre-gl.js` (UMD), `.css` |
| maplibre-gl | 6.18.0 | BSD-3-Clause | `dist/maplibre-gl.mjs`, `maplibre-gl-worker.mjs` (ESM only), `.css` |
| cesium | 1.147.0 | Apache-2.0 (LICENSE.md also lists patents) | `Build/Cesium/{Cesium.js,Workers,ThirdParty,Widgets}`, `Assets/{Images,IAU2006_XYS,approximateTerrainHeights.json}` |
`CHECKSUMS.sha256` lists every vendored file. Cesium's `Assets/Textures` (2.6 MB) is left out; nothing here requests it.
