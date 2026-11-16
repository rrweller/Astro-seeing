# PROTOTYPE (throwaway): globe library for the viewer (ticket #25)
The approved B layout (tonight map; click a place for C's table; optional hour slider) built twice on the synthetic data of `prototype/forecast-views`:
`maplibre.html?v=5` (5.24.1), `maplibre.html?v=6` (6.18.0), `cesium.html` (1.147.0). Shared UI/data/tile painter: `shared/`.
Run: `cd web/prototype-globe-library && python3 -m http.server 8765`, open `index.html` (needs HTTP, not file://).
All libraries load from `vendor/`; no CDN, no ion. Data are synthetic except Sun and Moon. Not for `main` or `dev`.
Comparison and decision: pending Riley's reaction (D56).
