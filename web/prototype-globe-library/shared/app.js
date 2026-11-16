// PROTOTYPE (throwaway), ticket #25: everything except the globe itself.
// The B layout (tonight map; click a place for C's table; optional hour slider) lives here once,
// so MapLibre and CesiumJS are compared on the same UI, the same synthetic data and the same tile painter.
// Data come from shared/core.js (copied unchanged from branch prototype/forecast-views): all synthetic
// except the Sun and Moon positions.
'use strict';

const APP = { adapters: {}, registry: new Map(), metrics: { tiles: 0, tileMs: 0, lastTileMs: 0, maxTileMs: 0, fps: 0, firstTileAt: null, t0: performance.now(), log: [] } };
window.__APP = APP;

// ---------- small helpers (same as the forecast-views prototype) ----------
function ramp(stops) {
  return (v) => {
    if (v <= stops[0][0]) return stops[0][1];
    for (let i = 1; i < stops.length; i++) if (v <= stops[i][0]) {
      const [a, ca] = stops[i - 1], [b, cb] = stops[i], f = (v - a) / (b - a);
      return [0, 1, 2].map((k) => Math.round(ca[k] + (cb[k] - ca[k]) * f));
    }
    return stops[stops.length - 1][1];
  };
}
const CLOUD_STOPS = [[0, [12, 26, 64]], [0.3, [40, 64, 112]], [0.6, [122, 140, 168]], [1, [234, 239, 245]]];
const SEE_STOPS = [[0.5, [31, 170, 135]], [0.9, [150, 200, 70]], [1.3, [238, 190, 76]], [1.8, [232, 122, 78]], [2.4, [196, 62, 94]]];
const CLEARH_STOPS = [[0, [52, 56, 72]], [3, [56, 78, 130]], [8, [48, 140, 186]], [14, [150, 228, 200]]];
const cloudRamp = ramp(CLOUD_STOPS), seeRamp = ramp(SEE_STOPS), clearHRamp = ramp(CLEARH_STOPS);
const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
const inkOn = (c) => (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) > 140 ? '#0d1422' : '#eef3f9';
function legend(stops, fmt, label, extra) {
  const lo = stops[0][0], hi = stops[stops.length - 1][0];
  const g = stops.map(([v, c]) => `${rgb(c)} ${((v - lo) / (hi - lo) * 100).toFixed(0)}%`).join(',');
  return `<div class="legend"><div>${label}</div><div class="bar" style="background:linear-gradient(90deg,${g})"></div><div class="ticks">${stops.map(([v]) => `<span>${fmt(v)}</span>`).join('')}</div>${extra || ''}</div>`;
}
const pad2 = (n) => String(n).padStart(2, '0');
const localHour = (ms, lon) => new Date(ms + tzOf(lon) * 3600000).getUTCHours();
const localHM = (ms, lon) => { const d = new Date(ms + tzOf(lon) * 3600000); return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`; };
const tzLabel = (lon) => { const z = tzOf(lon); return `UTC${z >= 0 ? '+' : '−'}${Math.abs(z)}`; };
const fmtLL = (p) => `${Math.abs(p.lat).toFixed(2)}°${p.lat >= 0 ? 'N' : 'S'} ${Math.abs(p.lon).toFixed(2)}°${p.lon >= 0 ? 'E' : 'W'}`;
const wrapLon = (l) => ((l + 540) % 360) - 180;

const PLACES = [
  { name: 'Kongsberg', lat: 59.669, lon: 9.652 },
  { name: 'La Palma', lat: 28.76, lon: -17.89 },
  { name: 'Paranal', lat: -24.63, lon: -70.40 },
  { name: 'Mauna Kea', lat: 19.82, lon: -155.47 },
  { name: 'South Pole', lat: -89.9, lon: 0 },
];
// The F1 box (D44 item 3): 4.65–14.65° E × 54.67–64.67° N, shown here at ERA5/GFS 0.25° cells.
const BOX = { lon0: 4.65, lon1: 14.65, lat0: 54.67, lat1: 64.67, d: 0.25 };

// ---------- cell grids: blocks, never interpolated ----------
function makeGrid(g, fn, opts) {
  const nI = Math.round((g.lat1 - g.lat0) / g.d), nJ = Math.round((g.lon1 - g.lon0) / g.d);
  const out = { ...g, nI, nJ, rgb: new Uint8ClampedArray(nI * nJ * 3), nodata: new Uint8Array(nI * nJ), dim: new Float32Array(nI * nJ), hatch: !!(opts && opts.hatch) };
  for (let i = 0; i < nI; i++) for (let j = 0; j < nJ; j++) {
    const lat = g.lat1 - g.d * (i + 0.5), lon = g.lon0 + g.d * (j + 0.5), k = i * nJ + j;
    const r = fn(lat, lon);
    if (!r || !r.c) out.nodata[k] = 1; else { out.rgb[k * 3] = r.c[0]; out.rgb[k * 3 + 1] = r.c[1]; out.rgb[k * 3 + 2] = r.c[2]; }
    if (r && r.dim) out.dim[k] = r.dim;
  }
  return out;
}
const WORLD = (d) => ({ lat0: -90, lat1: 90, lon0: -180, lon1: 180, d });

function hourFn(layer, modelId, h) {
  const sp = sunParams(T0 + h * 3600000);
  const md = MODELS.find((m) => m.id === modelId);
  return (lat, lon) => {
    const alt = sunAlt(sp, lat, lon), dim = alt > -12 ? 0.62 : alt > -18 ? 0.28 : 0;
    if (layer === 'agree') {
      let n = 0, c = 0; for (const m of MODELS) { const r = modelHour(m, lat, lon, h); if (r) { n++; if (r.cls === 'clear') c++; } }
      return { c: cloudRamp(1 - c / n), dim };
    }
    return { dim };
  };
}
function tonightFn(layer) {
  return (lat, lon) => {
    const h0 = windowStart(lon); let dark = 0, clear = 0; const see = [];
    for (let h = h0; h < h0 + 24; h++) {
      if (sunAlt(sunParams(T0 + h * 3600000), lat, lon) > -18) continue;
      dark++;
      if (layer === 'dark') continue;
      let n = 0, c = 0; const os = [];
      for (const m of MODELS) { const r = modelHour(m, lat, lon, h); if (r) { n++; if (r.cls === 'clear') c++; if (r.os != null) os.push(r.os); } }
      if (c * 2 > n) clear++;
      see.push(median(os));
    }
    if (!dark) return null; // hatched: no dark time tonight
    if (layer === 'dark') return { c: clearHRamp(dark) };
    if (layer === 'clear') return { c: clearHRamp(clear) };
    return { c: seeRamp(median(see)) };
  };
}
// Test pattern: a checkerboard of the grid's own cells, to see whether blocks stay square and sharp at every zoom.
const checkerFn = (d) => (lat, lon) => (((Math.floor((lat + 90) / d) + Math.floor((lon + 180) / d)) & 1) ? { c: [233, 169, 75] } : { c: [38, 52, 84] });
const LAYERS = {
  checker: { label: 'Test pattern: checkerboard of cells', tonight: true, d: 3, test: true },
  clear: { label: 'Clear dark hours (most models clear)', tonight: true, d: 3 },
  see: { label: 'Median seeing in dark time (O&S)', tonight: true, d: 3 },
  dark: { label: 'Dark hours tonight', tonight: true, d: 3 },
  agree: { label: 'Hour by hour: models saying clear', tonight: false, d: 2 },
};
const gridCache = new Map();
function cachedGrid(key, build) { if (!gridCache.has(key)) gridCache.set(key, build()); return gridCache.get(key); }
// A field = a stack of grids (coarse global first, finer box on top). `key` names it for tile URLs and caches.
function fieldSpec(layer, h, box) {
  const L = LAYERS[layer], tk = L.tonight ? layer : `${layer}|${h}`;
  const fn = (d) => L.test ? checkerFn(d) : L.tonight ? tonightFn(layer) : hourFn(layer, 'A', h);
  const hatch = L.tonight && !L.test;
  const grids = [cachedGrid(`g|${tk}|${L.d}`, () => makeGrid(WORLD(L.d), fn(L.d), { hatch }))];
  if (box) grids.push(cachedGrid(`b|${tk}`, () => makeGrid(BOX, fn(BOX.d), { hatch })));
  const key = `${layer}-${L.tonight ? 'n' : h}-${box ? 'box' : 'glob'}`;
  APP.registry.set(key, grids);
  return { key, grids };
}

// ---------- tile painter: shared by both libraries (this is the "tiles generated in the browser" part) ----------
function paintRGBA(grids, N, lons, lats) {
  const out = new Uint8ClampedArray(N * N * 4), G = grids.slice().reverse(), per = 7 * Math.abs(lons[1] - lons[0]) || 1; // finest first; hatch period = 7 tile pixels
  const colIdx = G.map((g) => { const a = new Int32Array(N); for (let c = 0; c < N; c++) { const j = Math.floor((lons[c] - g.lon0) / g.d); a[c] = j >= 0 && j < g.nJ ? j : -1; } return a; });
  const rowIdx = new Int32Array(G.length);
  for (let r = 0; r < N; r++) {
    for (let k = 0; k < G.length; k++) { const i = Math.floor((G[k].lat1 - lats[r]) / G[k].d); rowIdx[k] = i >= 0 && i < G[k].nI ? i : -1; }
    for (let c = 0; c < N; c++) {
      let k = 0; for (; k < G.length; k++) if (rowIdx[k] >= 0 && colIdx[k][c] >= 0) break;
      if (k === G.length) continue;
      const g = G[k], idx = rowIdx[k] * g.nJ + colIdx[k][c], o = (r * N + c) * 4;
      if (g.nodata[idx]) { if (g.hatch && (Math.floor((lons[c] + lats[r]) / per) & 3) === 0) { out[o] = 140; out[o + 1] = 150; out[o + 2] = 170; out[o + 3] = 150; } continue; }
      const f = 1 - 0.6 * g.dim[idx];
      out[o] = g.rgb[idx * 3] * f; out[o + 1] = g.rgb[idx * 3 + 1] * f; out[o + 2] = g.rgb[idx * 3 + 2] * f; out[o + 3] = 255;
    }
  }
  return out;
}
function noteTile(ms, tag) {
  const m = APP.metrics; m.tiles++; m.tileMs += ms; m.lastTileMs = ms; if (ms > m.maxTileMs) m.maxTileMs = ms;
  if (m.firstTileAt == null) m.firstTileAt = performance.now() - m.t0;
  m.log.push(tag);
}
// Web Mercator XYZ tile (MapLibre): rows are linear in Mercator y.
function mercatorAxes(z, x, y, N) {
  const n = 2 ** z, lons = new Float64Array(N), lats = new Float64Array(N);
  for (let c = 0; c < N; c++) lons[c] = (x + (c + 0.5) / N) / n * 360 - 180;
  for (let r = 0; r < N; r++) { const t = Math.PI - 2 * Math.PI * (y + (r + 0.5) / N) / n; lats[r] = Math.atan(Math.sinh(t)) / DEG; }
  return { lons, lats };
}
// Geographic tile (Cesium GeographicTilingScheme): rows linear in latitude. Rectangle in degrees.
function geographicAxes(w, s, e, nth, N) {
  const lons = new Float64Array(N), lats = new Float64Array(N);
  for (let c = 0; c < N; c++) lons[c] = w + (c + 0.5) / N * (e - w);
  for (let r = 0; r < N; r++) lats[r] = nth - (r + 0.5) / N * (nth - s);
  return { lons, lats };
}
function paintCanvas(grids, axes, N) {
  const t0 = performance.now();
  const px = paintRGBA(grids, N, axes.lons, axes.lats);
  const cv = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(N, N) : Object.assign(document.createElement('canvas'), { width: N, height: N });
  cv.getContext('2d').putImageData(new ImageData(px, N, N), 0, 0);
  return { cv, ms: performance.now() - t0 };
}

// ---------- synthetic relief for the "terrain later" test (NOT real terrain) ----------
function demHeight(lat, lon) {
  const x = lon * DEG, y = lat * DEG;
  const ridge = (a) => 1 - Math.abs(Math.sin(a));
  // broad massifs (tens of degrees), ridges about 1.4 degrees wide, and fine ridges about 0.4 degrees wide
  const base = 0.4 * ridge(9 * x + 4 * y) * ridge(6 * y - 3 * x) + 0.25 * ridge(17 * x - 5 * y)
    + 0.25 * ridge(260 * x + 90 * y) * ridge(310 * y - 120 * x) + 0.1 * ridge(900 * x - 400 * y);
  const mask = 0.5 + 0.5 * Math.sin(2.1 * x + 1.3) * Math.cos(1.7 * y - 0.4); // broad highlands and lowlands
  return Math.max(0, 3200 * base * mask * mask - 120);
}
function terrariumTile(z, x, y, N) { // Terrarium encoding: h = (R*256 + G + B/256) - 32768
  const ax = mercatorAxes(z, x, y, N), px = new Uint8ClampedArray(N * N * 4);
  for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) {
    const v = demHeight(ax.lats[r], ax.lons[c]) + 32768, o = (r * N + c) * 4;
    px[o] = Math.floor(v / 256); px[o + 1] = Math.floor(v) % 256; px[o + 2] = Math.floor((v - Math.floor(v)) * 256); px[o + 3] = 255;
  }
  const cv = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(N, N) : Object.assign(document.createElement('canvas'), { width: N, height: N });
  cv.getContext('2d').putImageData(new ImageData(px, N, N), 0, 0);
  return cv;
}

// ---------- coast and graticule lines (GeoJSON; identical input for both libraries) ----------
function graticuleGeoJSON() {
  const f = [];
  for (let lon = -180; lon < 180; lon += 30) { const c = []; for (let lat = -85; lat <= 85; lat += 5) c.push([lon, lat]); f.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: c } }); }
  for (let lat = -60; lat <= 60; lat += 30) { const c = []; for (let lon = -180; lon <= 180; lon += 5) c.push([lon, lat]); f.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: c } }); }
  return { type: 'FeatureCollection', features: f };
}
function boxGeoJSON() {
  return { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [[BOX.lon0, BOX.lat0], [BOX.lon1, BOX.lat0], [BOX.lon1, BOX.lat1], [BOX.lon0, BOX.lat1], [BOX.lon0, BOX.lat0]] } };
}

// ---------- verdict and C's table (from the prototype, trimmed) ----------
const SUNLAB = { day: 'Day', civil: 'Civil twilight', nautical: 'Nautical twilight', astro: 'Astronomical twilight', dark: 'Dark time' };
function moonLine(p) {
  const h0 = windowStart(p.lon), a = T0 + h0 * 3600000, b = a + 24 * 3600000;
  const ev = moonEvents(p.lat, p.lon, a, b).map((e) => `${e.kind === 'rise' ? 'rises' : 'sets'} ${localHM(e.ms, p.lon)}`);
  return `Moon ${Math.round(moonPhase(a + 12 * 3600000) * 100)}% lit${ev.length ? ' · ' + ev.join(' · ') : ''}`;
}
function verdictHTML(p, tn) {
  const name = p.name || fmtLL(p), n = tn.hours[0].n;
  const basisTxt = { dark: 'dark hours', nautical: 'hours with the Sun below −12° (no astronomical darkness tonight)', 'below horizon': 'hours with the Sun down (no darkness below −12° tonight)' }[tn.basis];
  const big = tn.pick.length ? `${tn.clearHours} of ${tn.pick.length} ${tn.basis === 'dark' ? 'dark hours' : 'night hours'} look clear on most models` : 'The Sun stays up all night';
  const runs = tn.runs.map((r) => { const a = tn.hours.find((x) => x.h === r.start), b = tn.hours.find((x) => x.h === r.end); const c = r.st === 'clear' ? cloudRamp(0.05) : cloudRamp(0.85); return `<span class="run" style="background:${rgb(c)};color:${inkOn(c)}">${r.st === 'clear' ? 'Mostly clear' : 'Cloud likely'} ${pad2(localHour(a.ms, p.lon))}–${pad2((localHour(b.ms, p.lon) + 1) % 24)}</span>`; }).join('');
  return `<div class="verdict"><div class="note">${name} · tonight · ${n} model${n === 1 ? '' : 's'} cover this place</div><div class="big">${big}</div><div class="runs">${runs}</div>
    <div class="meta"><span>Counted over ${basisTxt}</span><span>Median seeing <b>${tn.osMed == null ? '–' : tn.osMed.toFixed(1) + '″'}</b> <span class="tag warn">uncalibrated</span></span><span>${moonLine(p)}</span></div></div>`;
}
function tableHTML(p, tn) {
  const cov = MODELS.filter((m) => m.cov(p.lat, p.lon));
  const bar = (r) => `<span class="lmh">${['L', 'M', 'H'].map((k) => `<i style="background:${rgb(cloudRamp(r[k] / 100))};outline:1px solid rgba(127,127,127,.35)"></i>`).join('')}</span>`;
  let s = `<table class="night"><thead><tr><th rowspan="2">${tzLabel(p.lon)}</th><th rowspan="2">Sky</th><th rowspan="2">Moon</th><th rowspan="2">Models clear</th><th class="grp" colspan="${cov.length}">Total cloud % (bar: low · mid · high)</th><th class="grp" colspan="${cov.length}">Seeing ″, O&amp;S <span class="tag warn">uncalibrated</span></th><th rowspan="2">200 hPa<br>m/s</th><th rowspan="2">Worst layer<br>km</th></tr><tr>${cov.map((m) => `<th>${m.name}</th>`).join('')}${cov.map((m) => `<th>${m.name}</th>`).join('')}</tr></thead><tbody>`;
  for (const x of tn.hours) {
    const ag = cloudRamp(1 - x.fracClear);
    s += `<tr><td class="t">${pad2(localHour(x.ms, p.lon))}:00</td><td><span class="skych" style="background:var(--s-${x.sun});color:${x.sun === 'day' || x.sun === 'civil' ? 'var(--fg)' : '#e9eef7'}">${{ day: 'day', civil: 'civil', nautical: 'naut.', astro: 'astro.', dark: 'dark' }[x.sun]}</span></td><td>${x.moon > 0 ? Math.round(x.moon) + '°' : ''}</td><td><span class="run" style="background:${rgb(ag)};color:${inkOn(ag)}">${x.count.clear}/${x.n}</span></td>`;
    for (const m of cov) { const r = x.models[MODELS.indexOf(m)], c = cloudRamp(r.T / 100); s += `<td><div class="cc" style="background:${rgb(c)};color:${inkOn(c)}">${r.T}${bar(r)}</div></td>`; }
    for (const m of cov) { const r = x.models[MODELS.indexOf(m)]; if (r.os == null) { s += '<td style="color:var(--muted)">–</td>'; continue; } const c = seeRamp(r.os); s += `<td><span class="run" style="background:${rgb(c)};color:${inkOn(c)}" title="Bi et al.: ${r.bi.toFixed(2)}″">${r.os.toFixed(2)}</span></td>`; }
    s += `<td style="${x.v200Med != null && x.v200Med >= 20 ? 'font-weight:600' : 'color:var(--muted)'}">${x.v200Med == null ? '–' : Math.round(x.v200Med)}</td><td style="color:var(--muted)">${x.layerMed == null ? '–' : x.layerMed.toFixed(1)}</td></tr>`;
  }
  return s + '</tbody></table>';
}

// ---------- the page ----------
// opts: { id, title, libLabel, makeAdapter(host, app) -> Promise<adapter> }
// adapter: { setField({key,grids}), setPlace(p, fly), setTerrain(bool), destroy(), onPick, version }
APP.start = async function (opts) {
  const root = document.getElementById('app');
  const st = { layer: 'clear', h: 0, box: false, terrain: false, place: null, playing: null };
  root.innerHTML = `
  <div class="wrap">
    <header>
      <div class="eyebrow">Prototype · ticket #25 · synthetic forecast data · night of 5–6 Nov 2026</div>
      <h1>${opts.title}</h1>
      <p class="lede">The approved B layout: one map for tonight, click a place for its verdict and C's table, optional hour slider. Same UI and data in both libraries; only the globe differs.</p>
      <div class="places" id="places"></div>
    </header>
    <main id="view">
      <div class="row2">
        <div class="panel" style="display:grid;gap:12px">
          <div id="globe" class="globe-host" aria-label="Globe. Drag to turn, scroll or pinch to zoom, click to pick a place."></div>
          <div class="controls">
            <label>Map <select id="layer">${Object.entries(LAYERS).map(([k, v]) => `<option value="${k}">${v.label}</option>`).join('')}</select></label>
            <label><input type="checkbox" id="box"> F1 box at 0.25° cells</label>
            <label><input type="checkbox" id="terr"> Synthetic relief (terrain test)</label>
          </div>
          <div id="hourbox" hidden>
            <div class="controls"><button class="btn primary" id="play">Play</button><span class="frame-time" id="ft"></span></div>
            <input type="range" id="slider" min="0" max="${NH - 1}" step="1" aria-label="Forecast hour">
          </div>
          <div id="leg"></div>
        </div>
        <div style="display:grid;gap:16px;min-width:0;align-content:start">
          <div class="panel" id="vd"><div class="note">Click a place on the globe, or pick one above.</div></div>
          <div class="panel diag" id="diag"></div>
        </div>
      </div>
      <div class="panel" id="tablePanel" hidden><div class="scroll" id="tbl"></div><p class="note" id="foot"></p></div>
    </main>
  </div>
  <nav class="switcher" aria-label="Prototype variant">${[['maplibre.html?v=5', 'MapLibre 5.24.1'], ['maplibre.html?v=6', 'MapLibre 6.18.0'], ['cesium.html', 'CesiumJS 1.147.0']].map(([h, t]) => `<a href="${h}" class="${opts.id === h ? 'on' : ''}">${t}</a>`).join('')}</nav>`;
  const $ = (s) => root.querySelector(s);

  const renderPlaces = () => {
    const custom = st.place && !PLACES.includes(st.place);
    $('#places').innerHTML = PLACES.map((p, i) => `<button class="chip" data-i="${i}" aria-pressed="${p === st.place}">${p.name}</button>`).join('') +
      `<span class="here">${st.place ? (custom ? 'Picked ' : '') + fmtLL(st.place) + ' · ' + tzLabel(st.place.lon) + ' (approx.)' : 'no place picked'}</span>`;
    $('#places').querySelectorAll('.chip').forEach((b) => b.onclick = () => setPlace(PLACES[+b.dataset.i], true));
  };
  const setPlace = (p, fly) => {
    st.place = p; renderPlaces();
    const tn = tonight(p.lat, p.lon);
    $('#vd').innerHTML = verdictHTML(p, tn);
    $('#tablePanel').hidden = false;
    $('#tbl').innerHTML = tableHTML(p, tn);
    $('#foot').textContent = `Hover a seeing value for the Bi et al. figure. 200 hPa wind and worst layer are medians across models. Model D has no seeing column. ${moonLine(p)}.`;
    adapter.setPlace(p, fly);
  };
  const legendFor = () => {
    const hatch = '<div class="note">Hatched: no astronomical darkness tonight.</div>';
    $('#leg').innerHTML = st.layer === 'checker' ? '<div class="legend"><div>Test pattern: each square is one grid cell (3° globally, 0.25° inside the F1 box when ticked). Edges must stay square and sharp when you zoom.</div></div>' : st.layer === 'see' ? legend(SEE_STOPS, (v) => v.toFixed(1) + '″', 'Median seeing over dark hours and models, arcsec (uncalibrated)', hatch)
      : st.layer === 'agree' ? legend(CLOUD_STOPS, (v) => `${Math.round((1 - v) * 100)}%`, 'Share of covering models that say clear (≤10% total cloud); daylight dimmed')
      : legend(CLEARH_STOPS, (v) => v + ' h', st.layer === 'clear' ? 'Dark hours that most covering models call clear' : 'Hours of astronomical darkness tonight', hatch);
  };
  let applying = 0;
  const applyField = async () => {
    const my = ++applying;
    $('#diag-busy') && ($('#diag-busy').textContent = 'computing…');
    await new Promise((r) => setTimeout(r, 15)); // let the UI paint before the (synchronous) synthetic compute
    const t0 = performance.now();
    const spec = fieldSpec(st.layer, st.h, st.box);
    APP.metrics.lastFieldMs = performance.now() - t0;
    if (my !== applying) return;
    adapter.setField(spec);
    legendFor();
  };
  const setH = (h) => {
    st.h = Math.max(0, Math.min(NH - 1, h)); $('#slider').value = st.h;
    const ms = T0 + st.h * 3600000;
    $('#ft').textContent = `${new Date(ms).toISOString().slice(0, 16).replace('T', ' ')} UTC` + (st.place ? ` · ${localHM(ms, st.place.lon)} at ${st.place.name || 'the picked place'}` : '');
    applyField();
  };
  $('#layer').value = st.layer;
  $('#layer').onchange = (e) => { st.layer = e.target.value; $('#hourbox').hidden = st.layer !== 'agree'; if (st.layer === 'agree') setH(st.h || windowStart((st.place || PLACES[0]).lon) + 10); else applyField(); };
  $('#box').onchange = (e) => { st.box = e.target.checked; applyField(); };
  $('#terr').onchange = (e) => { st.terrain = e.target.checked; adapter.setTerrain(st.terrain); };
  $('#slider').oninput = (e) => setH(+e.target.value);
  $('#play').onclick = () => { if (st.playing) { clearInterval(st.playing); st.playing = null; $('#play').textContent = 'Play'; } else { st.playing = setInterval(() => setH((st.h + 1) % NH), 900); $('#play').textContent = 'Pause'; } };

  const adapter = await opts.makeAdapter($('#globe'), APP);
  adapter.onPick = (lat, lon) => setPlace({ lat, lon: wrapLon(lon) }, false);
  window.__adapter = adapter; APP.state = st; APP.setPlace = setPlace; APP.setLayer = (l) => { $('#layer').value = l; $('#layer').onchange({ target: { value: l } }); };
  APP.setBox = (b) => { $('#box').checked = b; $('#box').onchange({ target: { checked: b } }); };
  APP.setTerrainUI = (b) => { $('#terr').checked = b; $('#terr').onchange({ target: { checked: b } }); };
  APP.setHour = (h) => { APP.setLayer('agree'); setH(h); };
  renderPlaces(); legendFor(); await applyField();

  // diagnostics: frame cadence from requestAnimationFrame (not GPU time), tile cost, heap
  let last = performance.now(), acc = [];
  const frame = (t) => { acc.push(t - last); last = t; if (acc.length >= 30) { APP.metrics.fps = 1000 / (acc.reduce((a, b) => a + b, 0) / acc.length); acc = []; } requestAnimationFrame(frame); };
  requestAnimationFrame(frame);
  const diag = () => {
    const m = APP.metrics, heap = performance.memory ? (performance.memory.usedJSHeapSize / 1048576).toFixed(0) + ' MB JS heap' : '';
    $('#diag').innerHTML = `<div class="note"><b>${opts.libLabel}</b> · ${adapter.version || ''}<br>cell tiles painted: ${m.tiles}${m.tiles ? ` · last ${m.lastTileMs.toFixed(1)} ms · worst ${m.maxTileMs.toFixed(1)} ms` : ''} · field compute ${(m.lastFieldMs || 0).toFixed(0)} ms<br>frames/s (rAF, includes render load): ${m.fps ? m.fps.toFixed(0) : '…'} ${heap ? '· ' + heap : ''}${m.firstTileAt != null ? `<br>first cell tile after ${(m.firstTileAt / 1000).toFixed(2)} s` : ''}</div>`;
  };
  setInterval(diag, 1000); diag();
  document.body.dataset.ready = '1';
};
