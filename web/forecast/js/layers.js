// The map layers: reading the binary arrays latest.json describes, and painting them
// as sharp blocks, one per map cell, never blended (F1 spec Modules 4 and 7, D86).
// Nothing here decides a class or a count (D60 item 1): a cell's colour comes from its
// stored value, and a reserved code (254, 255, 65535, …) gets its own pattern.

const TYPES = { uint8: Uint8Array, uint16: Uint16Array, int16: Int16Array };

/** A layer's values as a typed array, read as its latest.json entry describes it.
 *  The arrays are little-endian; a file of the wrong length is refused. */
export async function loadLayer(url, entry) {
  const Type = TYPES[entry.dtype];
  if (!Type) throw new Error(`${entry.file}: unknown dtype ${entry.dtype}`);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${entry.file}: HTTP ${response.status}`);
  const buffer = await response.arrayBuffer();
  const count = entry.shape.reduce((a, b) => a * b, 1);
  if (buffer.byteLength !== count * Type.BYTES_PER_ELEMENT) {
    throw new Error(`${entry.file}: ${buffer.byteLength} bytes, expected ${count * Type.BYTES_PER_ELEMENT}`);
  }
  if (Type.BYTES_PER_ELEMENT === 1) return new Type(buffer);
  const view = new DataView(buffer);
  const out = new Type(count);
  const get = entry.dtype === "int16" ? "getInt16" : "getUint16";
  for (let k = 0; k < count; k++) out[k] = view[get](k * 2, true);
  return out;
}

/** The global families on the map, from the layer names (`seeing_fa_<family>`). */
export function familiesOf(latest) {
  return Object.keys(latest.layers)
    .filter((name) => name.startsWith("seeing_fa_"))
    .map((name) => name.slice("seeing_fa_".length));
}

/** The map cell (row, column) holding a point, or null outside the grid. The grid's
 *  numbers are cell centres; each cell reaches half a spacing either way. */
export function cellAt(grid, lat, lon) {
  const i = Math.floor((grid.lat_north + grid.dlat / 2 - lat) / grid.dlat);
  const j = Math.floor((lon - grid.lon_west + grid.dlon / 2) / grid.dlon);
  if (i < 0 || i >= grid.nlat || j < 0 || j >= grid.nlon) return null;
  return { i, j };
}

/** The grid's outer edge as [west, south, east, north]. */
export function gridBounds(grid) {
  return [
    grid.lon_west - grid.dlon / 2,
    grid.lat_north - (grid.nlat - 0.5) * grid.dlat,
    grid.lon_west + (grid.nlon - 0.5) * grid.dlon,
    grid.lat_north + grid.dlat / 2,
  ];
}

// -- colours ----------------------------------------------------------------------------

function ramp(stops) {
  return (v) => {
    if (v <= stops[0][0]) return stops[0][1];
    for (let k = 1; k < stops.length; k++) {
      if (v <= stops[k][0]) {
        const [a, ca] = stops[k - 1];
        const [b, cb] = stops[k];
        const f = (v - a) / (b - a);
        return [0, 1, 2].map((n) => Math.round(ca[n] + (cb[n] - ca[n]) * f));
      }
    }
    return stops[stops.length - 1][1];
  };
}

/** The patterns for values that aren't a quantity. Each is two colours, so it never
 *  reads as a flat colour of the scale: diagonal lines for "nothing to show", dots
 *  for "every counted hour incomplete". */
export const PATTERNS = {
  hatch: { base: [20, 29, 54], ink: [118, 132, 160], at: (x, y) => (x + y) % 8 < 2 },
  dots: { base: [44, 51, 80], ink: [176, 186, 210], at: (x, y) => x % 5 < 2 && y % 5 < 2 },
};

// Clear hours: none clear is a flat slate; more clear hours run from deep blue to a
// pale sea-green, so the best spots are the brightest.
const CLEAR_STOPS = [[0, [58, 66, 86]], [1, [31, 60, 112]], [4, [40, 112, 170]], [8, [86, 182, 186]], [12, [168, 226, 196]], [16, [226, 246, 214]]];
// Seeing, arcsec: green (sharp) through amber to rose (blurred).
const SEEING_STOPS = [[0.4, [47, 176, 138]], [0.8, [156, 198, 90]], [1.2, [232, 191, 76]], [1.8, [224, 123, 79]], [2.5, [184, 64, 106]]];
// Dark time left, hours: pale where there's none, deepening to the night sky.
const DARK_STOPS = [[0, [201, 211, 230]], [4, [110, 136, 184]], [8, [52, 76, 136]], [12, [22, 38, 88]], [16, [8, 16, 46]]];
// Total cloud, %: the clear night sky up to a white veil.
const CLOUD_STOPS = [[0, [12, 26, 64]], [30, [40, 64, 112]], [60, [122, 140, 168]], [100, [234, 239, 245]]];

/** How each layer kind is shown: its scale, its reserved codes and their patterns, and
 *  the legend's words. `value(stored)` turns a stored number into the quantity shown. */
export const KINDS = {
  clear: {
    title: "Mostly clear counted hours left",
    unit: "hours",
    colour: ramp(CLEAR_STOPS),
    value: (v) => v,
    ticks: [0, 4, 8, 12, 16],
    tickLabel: (v) => (v === 16 ? "16+" : String(v)),
    codes: {
      255: { pattern: "hatch", label: "No counted hours left tonight" },
      254: { pattern: "dots", label: "Not known: every counted hour left is incomplete (fewer than two models have a value)" },
    },
  },
  seeing: {
    title: "Median free-atmosphere seeing over the counted hours (uncalibrated)",
    unit: "″",
    colour: ramp(SEEING_STOPS),
    value: (v, entry) => v * entry.scale,
    ticks: [0.4, 0.8, 1.2, 1.8, 2.5],
    // the scale's ends hold every value beyond them, so they say so
    tickLabel: (v) => (v === 0.4 ? "≤0.4″" : v === 2.5 ? "≥2.5″" : `${v.toFixed(1)}″`),
    codes: { 65535: { pattern: "hatch", label: "No value: the model has no seeing over the counted hours" } },
  },
  dark: {
    title: "Dark time left tonight",
    unit: "hours",
    colour: ramp(DARK_STOPS),
    value: (v) => v / 60,
    ticks: [0, 4, 8, 12, 16],
    tickLabel: (v) => (v === 16 ? "16+ h" : `${v} h`),
    codes: {},
  },
  cloud: {
    title: "Total cloud at the chosen hour",
    unit: "%",
    colour: ramp(CLOUD_STOPS),
    value: (v) => v,
    ticks: [0, 25, 50, 75, 100],
    tickLabel: (v) => `${v} %`,
    codes: { 255: { pattern: "hatch", label: "No value at this hour" } },
  },
};

// -- painting -------------------------------------------------------------------------

/** One field to paint: a kind, the grid, and `values` (typed array) from `offset`. */
export function field(kind, grid, entry, values, offset = 0) {
  return { kind: KINDS[kind], grid, entry, values, offset };
}

function cellColour(f, stored) {
  const code = f.kind.codes[stored];
  if (code) return code.pattern;
  return f.kind.colour(f.kind.value(stored, f.entry));
}

/** RGBA pixels of an N × N Web Mercator tile z/x/y: each pixel takes the colour of the
 *  map cell under its centre (nearest, never blended); outside the grid it is left
 *  transparent. Patterns are laid on whole-map pixel coordinates, so they run on
 *  across tile edges. */
export function paintTile(f, z, x, y, N) {
  const g = f.grid;
  const n = 2 ** z;
  const out = new Uint8ClampedArray(N * N * 4);
  const cols = new Int32Array(N);
  for (let c = 0; c < N; c++) {
    const lon = ((x + (c + 0.5) / N) / n) * 360 - 180;
    const j = Math.floor((lon - g.lon_west + g.dlon / 2) / g.dlon);
    cols[c] = j >= 0 && j < g.nlon ? j : -1;
  }
  const cache = new Map();
  for (let r = 0; r < N; r++) {
    const t = Math.PI - (2 * Math.PI * (y + (r + 0.5) / N)) / n;
    const lat = (Math.atan(Math.sinh(t)) * 180) / Math.PI;
    const i = Math.floor((g.lat_north + g.dlat / 2 - lat) / g.dlat);
    if (i < 0 || i >= g.nlat) continue;
    for (let c = 0; c < N; c++) {
      const j = cols[c];
      if (j < 0) continue;
      const stored = f.values[f.offset + i * g.nlon + j];
      let colour = cache.get(stored);
      if (colour === undefined) cache.set(stored, (colour = cellColour(f, stored)));
      if (typeof colour === "string") {
        const p = PATTERNS[colour];
        colour = p.at(x * N + c, y * N + r) ? p.ink : p.base;
      }
      const o = (r * N + c) * 4;
      out[o] = colour[0];
      out[o + 1] = colour[1];
      out[o + 2] = colour[2];
      out[o + 3] = 255;
    }
  }
  return out;
}

/** A small canvas filled with a pattern, for the legend: the same painter as the map. */
export function patternSwatch(name, width = 22, height = 14) {
  const p = PATTERNS[name];
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const px = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const colour = p.at(x, y) ? p.ink : p.base;
      px.set([...colour, 255], (y * width + x) * 4);
    }
  }
  canvas.getContext("2d").putImageData(new ImageData(px, width, height), 0, 0);
  return canvas;
}

/** The CSS gradient of a kind's scale, for the legend bar. */
export function scaleGradient(kind) {
  const k = KINDS[kind];
  const lo = k.ticks[0];
  const hi = k.ticks[k.ticks.length - 1];
  const stops = [];
  for (let s = 0; s <= 20; s++) {
    const v = lo + ((hi - lo) * s) / 20;
    const [r, g, b] = k.colour(v);
    stops.push(`rgb(${r} ${g} ${b}) ${s * 5}%`);
  }
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}
