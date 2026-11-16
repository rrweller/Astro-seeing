// PROTOTYPE core: Sun, Moon, synthetic forecast fields, tonight summary. Throwaway.
// Everything here is synthetic except the Sun/Moon positions (low-precision formulas).
const DEG = Math.PI / 180;
const T0 = Date.UTC(2026, 10, 5, 0, 0); // first frame: 2026-11-05 00:00 UTC
const NH = 48; // hourly frames, enough for every time zone's tonight
// Prototype: time zone approximated from longitude; the real thing uses a tz database.
const tzOf = (lon) => Math.round(lon / 15);
const windowStart = (lon) => 12 - tzOf(lon); // frame of local noon on 5 Nov

function jdOf(ms) { return ms / 86400000 + 2440587.5; }

// --- Sun: NOAA approximation (same as the scratch check for Kongsberg) ---
function sunParams(ms) {
  const T = (jdOf(ms) - 2451545) / 36525;
  const L0 = (280.46646 + T * (36000.76983 + T * 0.0003032)) % 360;
  const M = 357.52911 + T * (35999.05029 - 0.0001537 * T);
  const e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T);
  const Mr = M * DEG;
  const C = Math.sin(Mr) * (1.914602 - T * (0.004817 + 0.000014 * T)) + Math.sin(2 * Mr) * (0.019993 - 0.000101 * T) + Math.sin(3 * Mr) * 0.000289;
  const om = 125.04 - 1934.136 * T;
  const lam = L0 + C - 0.00569 - 0.00478 * Math.sin(om * DEG);
  const eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60;
  const eps = eps0 + 0.00256 * Math.cos(om * DEG);
  const dec = Math.asin(Math.sin(eps * DEG) * Math.sin(lam * DEG));
  const y = Math.tan(eps * DEG / 2) ** 2;
  const L0r = L0 * DEG;
  const eqt = 4 / DEG * (y * Math.sin(2 * L0r) - 2 * e * Math.sin(Mr) + 4 * e * y * Math.sin(Mr) * Math.cos(2 * L0r) - 0.5 * y * y * Math.sin(4 * L0r) - 1.25 * e * e * Math.sin(2 * Mr));
  const d = new Date(ms);
  const utcMin = d.getUTCHours() * 60 + d.getUTCMinutes() + d.getUTCSeconds() / 60;
  return { dec, eqt, utcMin, lam };
}
function sunAlt(p, lat, lon) {
  const ha = ((p.utcMin + p.eqt + 4 * lon) / 4 - 180) * DEG;
  const la = lat * DEG;
  return Math.asin(Math.sin(la) * Math.sin(p.dec) + Math.cos(la) * Math.cos(p.dec) * Math.cos(ha)) / DEG;
}
function sunClass(alt) {
  if (alt > -0.833) return 'day';
  if (alt > -6) return 'civil';
  if (alt > -12) return 'nautical';
  if (alt > -18) return 'astro';
  return 'dark';
}

// --- Moon: Astronomical Almanac low-precision series (~0.3 deg) ---
function moonEcl(ms) {
  const T = (jdOf(ms) - 2451545) / 36525;
  const s = (a, b) => Math.sin((a + b * T) * DEG);
  const c = (a, b) => Math.cos((a + b * T) * DEG);
  const lam = 218.32 + 481267.881 * T + 6.29 * s(135.0, 477198.87) - 1.27 * s(259.3, -413335.36) + 0.66 * s(235.7, 890534.22) + 0.21 * s(269.9, 954397.74) - 0.19 * s(357.5, 35999.05) - 0.11 * s(186.5, 966404.03);
  const bet = 5.13 * s(93.3, 483202.02) + 0.28 * s(228.2, 960400.89) - 0.28 * s(318.3, 6003.15) - 0.17 * s(217.6, -407332.21);
  const par = 0.9508 + 0.0518 * c(135.0, 477198.87) + 0.0095 * c(259.3, -413335.36) + 0.0078 * c(235.7, 890534.22) + 0.0028 * c(269.9, 954397.74);
  return { lam, bet, par, T };
}
function moonAlt(ms, lat, lon) {
  const m = moonEcl(ms);
  const eps = (23.439 - 0.013 * m.T) * DEG;
  const l = m.lam * DEG, b = m.bet * DEG;
  const ra = Math.atan2(Math.sin(l) * Math.cos(eps) - Math.tan(b) * Math.sin(eps), Math.cos(l));
  const dec = Math.asin(Math.sin(b) * Math.cos(eps) + Math.cos(b) * Math.sin(eps) * Math.sin(l));
  const gmst = (280.46061837 + 360.98564736629 * (jdOf(ms) - 2451545)) % 360;
  const ha = (gmst + lon) * DEG - ra;
  const la = lat * DEG;
  const geo = Math.asin(Math.sin(la) * Math.sin(dec) + Math.cos(la) * Math.cos(dec) * Math.cos(ha)) / DEG;
  return { geo, topo: geo - m.par * Math.cos(geo * DEG) };
}
function moonPhase(ms) {
  const m = moonEcl(ms);
  const sp = sunParams(ms);
  const cosPsi = Math.cos(m.bet * DEG) * Math.cos((m.lam - sp.lam) * DEG);
  return (1 - cosPsi) / 2; // illuminated fraction
}
// Rise/set: geocentric altitude crosses +0.125 deg (standard lunar h0), 1-minute scan.
function moonEvents(lat, lon, startMs, endMs) {
  const out = [];
  let prev = moonAlt(startMs, lat, lon).geo - 0.125;
  for (let t = startMs + 60000; t <= endMs; t += 60000) {
    const a = moonAlt(t, lat, lon).geo - 0.125;
    if (prev < 0 && a >= 0) out.push({ kind: 'rise', ms: t });
    if (prev >= 0 && a < 0) out.push({ kind: 'set', ms: t });
    prev = a;
  }
  return out;
}

// --- Synthetic forecast fields (NOT real data) ---
function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
function makeTerms(seed, n) {
  const r = mulberry32(seed); const out = [];
  for (let i = 0; i < n; i++) out.push({ n: 2 + Math.floor(r() * 8), m: (1 + Math.floor(r() * 6)) * (r() < 0.5 ? -1 : 1), a: 0.2 + r() * 0.25, u: 0.01 + r() * 0.02, p: r() * 6.283 });
  return out;
}
const TERMS = { low: makeTerms(11, 5), mid: makeTerms(23, 4), high: makeTerms(37, 4) };
const MODELS = [
  { id: 'A', name: 'Model A', scope: 'global', cov: () => true, phase: 0.0, bias: 0.0, tShift: 0, seeing: true },
  { id: 'B', name: 'Model B', scope: 'global', cov: () => true, phase: 0.35, bias: 0.06, tShift: 1.5, seeing: true },
  { id: 'C', name: 'Model C', scope: 'Europe', cov: (la, lo) => la >= 30 && la <= 70.5 && lo >= -23.5 && lo <= 62.5, phase: -0.25, bias: -0.05, tShift: -1, seeing: true },
  { id: 'D', name: 'Model D', scope: 'Nordic', cov: (la, lo) => la >= 52 && la <= 73 && lo >= -12 && lo <= 38, phase: 0.15, bias: 0.03, tShift: 0.5, seeing: false },
];
const gauss = (x, w) => Math.exp(-(x / w) * (x / w));
function biasFor(layer, lat) {
  const al = Math.abs(lat);
  if (layer === 'low') return 0.35 * gauss(al - 55, 15) - 0.55 * gauss(al - 25, 10) + 0.2 * gauss(lat, 8) - 0.2;
  if (layer === 'mid') return 0.25 * gauss(al - 55, 15) - 0.45 * gauss(al - 25, 10) - 0.25;
  return 0.35 * gauss(lat, 10) + 0.2 * gauss(al - 50, 15) - 0.35;
}
function layerFrac(layer, md, lat, lon, h) {
  const x = lon * DEG, y = lat * DEG;
  let s = 0;
  for (const k of TERMS[layer]) s += k.a * Math.sin(k.n * (x - k.u * (h + md.tShift)) + k.m * y + k.p + md.phase * k.n * 0.15);
  // a front that crosses southern Norway overnight, timed differently by each model
  const hh = h - 11; // the front was tuned on frames counted from 11 UTC
  const c = -16 + 1.6 * (hh - md.tShift);
  const front = gauss(((lon - c + 540) % 360) - 180, 6) * gauss(lat - (60 + 0.2 * hh), 7);
  const ridge = gauss(((lon - (c + 16) + 540) % 360) - 180, 10) * gauss(lat - 60, 9);
  if (layer !== 'high') s += 1.6 * front - 1.1 * ridge; else s += 0.6 * front - 0.6 * ridge;
  s += biasFor(layer, lat) + md.bias - 0.3; // drier baseline so clear areas show up
  const f = 1 / (1 + Math.exp(-3.2 * s));
  return Math.min(1, Math.max(0, (f - 0.2) / 0.6));
}
function seeingFor(md, lat, lon, h) {
  const x = lon * DEG, y = lat * DEG;
  const v200 = 14 + 32 * gauss(Math.abs(lat) - 40 - 7 * Math.sin(3 * x - 0.04 * h + md.phase), 8) + 4 * Math.sin(5 * x + 2 * y - 0.05 * h) + 16 * gauss(Math.abs(lat) - 58, 10) * (0.5 + 0.5 * Math.sin(2 * x - 0.15 * h + md.phase * 3));
  const eFA = 0.22 + 0.014 * v200;
  const eGL = 0.45 + 0.6 * (0.5 + 0.5 * Math.sin(4 * x + 3 * y + 0.12 * h + md.phase * 2));
  const os = Math.pow(Math.pow(eFA, 5 / 3) + Math.pow(eGL, 5 / 3), 3 / 5);
  const bi = os * (0.92 + 0.12 * (0.5 + 0.5 * Math.sin(2 * x - y + 0.07 * h)));
  const layerKm = Math.pow(eFA, 5 / 3) > Math.pow(eGL, 5 / 3) ? 8.5 + 2 * Math.sin(x + 0.05 * h) : 0.8 + 0.6 * (0.5 + 0.5 * Math.sin(2 * x + y));
  return { v200, os, bi, layerKm };
}
function cloudClass(T) { return T <= 10 ? 'clear' : T <= 50 ? 'some' : 'cloudy'; }
function modelHour(md, lat, lon, h) {
  if (!md.cov(lat, lon)) return null;
  const L = layerFrac('low', md, lat, lon, h), M = layerFrac('mid', md, lat, lon, h), H = layerFrac('high', md, lat, lon, h);
  const T = 1 - (1 - L) * (1 - M) * (1 - H); // random overlap: total is not the sum
  const r = { L: Math.round(L * 100), M: Math.round(M * 100), H: Math.round(H * 100), T: Math.round(T * 100) };
  r.cls = cloudClass(r.T);
  if (md.seeing) Object.assign(r, seeingFor(md, lat, lon, h)); else r.os = r.bi = r.v200 = r.layerKm = null;
  return r;
}
function median(a) { const s = a.filter((v) => v != null).sort((p, q) => p - q); if (!s.length) return null; const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }
function pointHour(lat, lon, h) {
  const ms = T0 + h * 3600000;
  const sa = sunAlt(sunParams(ms), lat, lon);
  const models = MODELS.map((md) => modelHour(md, lat, lon, h));
  const cov = models.filter(Boolean);
  const n = cov.length;
  const count = { clear: 0, some: 0, cloudy: 0 };
  cov.forEach((m) => count[m.cls]++);
  return { h, ms, sunAlt: sa, sun: sunClass(sa), moon: moonAlt(ms, lat, lon).topo, models, n, count, fracClear: n ? count.clear / n : null,
    osMed: median(cov.map((m) => m.os)), v200Med: median(cov.map((m) => m.v200)), layerMed: median(cov.map((m) => m.layerKm)) };
}
// Tonight summary: which hours count as "dark" falls back when there is no astronomical darkness.
function tonight(lat, lon) {
  const h0 = windowStart(lon);
  const hours = []; for (let h = h0; h < h0 + 24; h++) hours.push(pointHour(lat, lon, h));
  let basis = 'dark', pick = hours.filter((x) => x.sun === 'dark');
  if (!pick.length) { basis = 'nautical'; pick = hours.filter((x) => x.sunAlt <= -12); }
  if (!pick.length) { basis = 'below horizon'; pick = hours.filter((x) => x.sunAlt <= -0.833); }
  const mostlyClear = (x) => x.n && x.count.clear * 2 > x.n;
  const runs = []; let cur = null;
  for (const x of pick) {
    const st = mostlyClear(x) ? 'clear' : 'not';
    if (cur && cur.st === st && x.h === cur.end + 1) cur.end = x.h; else { cur = { st, start: x.h, end: x.h }; runs.push(cur); }
  }
  return { hours, basis, pick, clearHours: pick.filter(mostlyClear).length, runs,
    osMed: median(pick.map((x) => x.osMed)) };
}
if (typeof module !== 'undefined') module.exports = { T0, NH, tzOf, windowStart, MODELS, sunParams, sunAlt, sunClass, moonAlt, moonPhase, moonEvents, modelHour, pointHour, tonight, cloudClass, median, DEG };
