# Vendored files for the page (ticket #66, D52 item 4, D56 item 1)

The page loads nothing from another server: these files are served from the site
itself. `CHECKSUMS.sha256` lists the SHA-256 of each one (`sha256sum -c CHECKSUMS.sha256`
in this folder), and `tests/test_forecast_map_page.py` checks them on every test run.
No file here was edited.

| Files | From | Version | Licence |
|---|---|---|---|
| `maplibre-gl-5.24.1/maplibre-gl.js`, `maplibre-gl.css` | npm package `maplibre-gl`, `dist/` | 5.24.1 | BSD-3-Clause (`maplibre-gl-5.24.1/LICENSE.txt`, the package's own `LICENSE.txt`; it also carries the BSD-3-Clause notice of mapbox-gl-js v1.13 and earlier) |
| `natural-earth/outline-kongsberg-box.json` | Natural Earth 1:10m Admin 0 countries, version 4.1.0, as TopoJSON in the npm package `world-atlas` (`countries-10m.json`) | world-atlas 2.0.2 | Natural Earth: public domain. world-atlas: ISC |

## How they were fetched and checked (2026-11-27)

- **MapLibre GL JS.** `https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-5.24.1.tgz`.
  Its SHA-512 matched the registry's `dist.integrity`,
  `sha512-HyiYBwtsbk3L1n1EPLJHWqdoyMiF80n7tEYXFZyu2m1TjvaNx6KMLiFeDdmszt1/mq2zvsR1TJuX/NMu5BonXQ==`
  (tarball SHA-256 `b84d7fdf7fba5922fd3fff9a92733936c7a03b99165afc6c84f41c311bdbfa9d`).
  The version and licence were read from the package's `package.json` and `LICENSE.txt`.
  The three files match, byte for byte, those the globe-library prototype vendored
  (branch `prototype/globe-library`, D56).
  - `maplibre-gl.js` is the UMD build: a plain `<script>`, no bundler. Its web worker
    is built from a blob inside the script, so it fetches nothing else. Its last line
    names a source map, `maplibre-gl.js.map`, which isn't vendored; browsers ask for it
    only while their developer tools are open.
- **The outline.** `https://registry.npmjs.org/world-atlas/-/world-atlas-2.0.2.tgz`; its
  SHA-512 matched the registry's `dist.integrity`,
  `sha512-IXfV0qwlKXpckz1FhwXVwKRjiIhOnWttOskm5CtxMsjgE/MXAYRHWJqgXOpM8IkcPBoXnyTU5lFHcYa5ChG0LQ==`
  (`countries-10m.json` SHA-256 `3bc6f1d367a9bcec479841bae0e76092f512838411d0cef124e92eec4db45f79`).
  `scripts/make_map_outline.py` turned it into coastlines and borders cut to the F1 box
  (4.65–14.65° E × 54.67–64.67° N, D44 item 3) widened by 1°:

  ```
  pixi run python -I scripts/make_map_outline.py <unpacked>/package/countries-10m.json \
      --box 4.65 54.67 14.65 64.67 --out web/vendor/natural-earth/outline-kongsberg-box.json
  ```

  Natural Earth's terms (https://www.naturalearthdata.com/about/terms-of-use/, read
  2026-11-27): "All versions of Natural Earth raster + vector map data found on this
  website are in the public domain." The map credits it in its corner all the same.
