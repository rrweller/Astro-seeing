// The landing view: the map of the forecast area (F1 spec Module 10; user stories 1-7
// and 28). MapLibre GL JS 5.24.1 (vendored, D56) draws the layers as sharp blocks, one
// per map cell, from tiles painted here in the browser (`addProtocol`) out of the binary
// layers. A click on a saved place opens its full view; a click anywhere else opens the
// cell card with that cell's values from the same layers. Nothing here derives a rule
// (D60 item 1): every number is a layer's stored value, formatted.
//
// No base map: the only geography is the vendored outline (Natural Earth coastlines and
// borders, web/vendor/natural-earth/); no request leaves the host.

import { clockLabel, dayLabel, fixed, metres } from "./format.js";
import { KINDS, cellAt, familiesOf, field, gridBounds, loadLayer, paintTile, patternSwatch, scaleGradient } from "./layers.js";
import { el } from "./render.js";
import { familyName } from "./verdict.js";

const TILE = 256;
const MAX_ZOOM = 12;
const DEFAULT_FAMILY = "gfs"; // the most levels (user story 3)
// coastlines and borders round the Kongsberg box (scripts/make_map_outline.py)
const OUTLINE_URL = new URL("../../vendor/natural-earth/outline-kongsberg-box.json", import.meta.url).href;

/** Tile key → field to paint; filled by `redraw`, read by the `cells` protocol. */
const fields = new Map();
let protocolAdded = false;

function addProtocol(maplibregl) {
  if (protocolAdded) return;
  protocolAdded = true;
  maplibregl.addProtocol("cells", async (params) => {
    const m = /^cells:\/\/([^/]+)\/(\d+)\/(\d+)\/(\d+)$/.exec(params.url);
    const f = m && fields.get(decodeURIComponent(m[1]));
    if (!f) throw new Error(`no map layer for ${params.url}`);
    const px = paintTile(f, +m[2], +m[3], +m[4], TILE);
    const canvas = new OffscreenCanvas(TILE, TILE);
    canvas.getContext("2d").putImageData(new ImageData(px, TILE, TILE), 0, 0);
    const blob = await canvas.convertToBlob({ type: "image/png" });
    return { data: await blob.arrayBuffer() };
  });
}

function edgeFeature(grid) {
  const [w, s, e, n] = gridBounds(grid);
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "LineString", coordinates: [[w, s], [e, s], [e, n], [w, n], [w, s]] },
  };
}

function cellFeature(grid, c) {
  if (!c) return { type: "FeatureCollection", features: [] };
  const n = grid.lat_north - (c.i - 0.5) * grid.dlat;
  const s = n - grid.dlat;
  const w = grid.lon_west + (c.j - 0.5) * grid.dlon;
  const e = w + grid.dlon;
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "LineString", coordinates: [[w, s], [e, s], [e, n], [w, n], [w, s]] },
  };
}

function hoursText(minutes) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
}

function latLonText(lat, lon) {
  return `${fixed(Math.abs(lat), 4)}° ${lat >= 0 ? "N" : "S"}, ${fixed(Math.abs(lon), 4)}° ${lon >= 0 ? "E" : "W"}`;
}

export class MapView {
  constructor(dataBase) {
    this.dataBase = dataBase;
    this.latest = null;
    this.home = null; // the default saved place's file: time zone and model names
    this.places = [];
    this.layers = new Map(); // layer name → typed array, for the set shown
    this.choice = "clear";
    this.family = DEFAULT_FAMILY;
    this.hour = null;
    this.picked = null;
    this.map = null;
    this.wire();
  }

  get grid() {
    return this.latest.grid;
  }

  // -- controls ------------------------------------------------------------------------

  wire() {
    for (const input of document.querySelectorAll('input[name="layer"]')) {
      input.addEventListener("change", () => {
        if (input.checked) this.choose({ choice: input.value });
      });
    }
    document.getElementById("model").addEventListener("change", (e) => this.choose({ family: e.target.value }));
    document.getElementById("hour").addEventListener("input", (e) => this.choose({ hour: Number(e.target.value) }));
  }

  async choose(change) {
    Object.assign(this, change);
    try {
      await this.redraw();
    } catch (err) {
      this.problem(err.message);
    }
  }

  problem(message) {
    const note = document.getElementById("map-note");
    note.textContent = `The map couldn't be drawn: ${message}.`;
    note.classList.add("caution");
  }

  syncControls() {
    const families = familiesOf(this.latest);
    if (!families.includes(this.family)) this.family = families.includes(DEFAULT_FAMILY) ? DEFAULT_FAMILY : families[0];
    const select = document.getElementById("model");
    select.replaceChildren(
      ...families.map((f) => el("option", { value: f, text: familyName(this.home, f), selected: f === this.family })),
    );
    const usesModel = this.choice === "seeing" || this.choice === "cloud";
    document.getElementById("model-pick").hidden = !usesModel || families.length === 0;
    document.getElementById("hour-pick").hidden = this.choice !== "cloud";
  }

  /** The slider's hours (UTC text) for the chosen family, and the hour shown. */
  sliderHours() {
    const entry = this.latest.layers[`total_cloud_${this.family}`];
    const hours = entry?.hours ?? [];
    if (this.hour === null || this.hour >= hours.length) {
      // start at the hour that holds "now", or the first hour
      const now = Date.now();
      const k = hours.findLastIndex((h) => Date.parse(h) <= now);
      this.hour = Math.max(0, k);
    }
    return hours;
  }

  // -- data ----------------------------------------------------------------------------

  async layer(name) {
    if (!this.layers.has(name)) {
      const entry = this.latest.layers[name];
      if (!entry) throw new Error(`latest.json has no layer ${name}`);
      const url = new URL(this.latest.set_path + entry.file, this.dataBase);
      this.layers.set(name, loadLayer(url, entry));
    }
    return this.layers.get(name);
  }

  // -- showing a set ----------------------------------------------------------------------

  /** Show product set `latest`, with the saved places' files (`places`, the default
   *  saved place first). */
  async show(latest, places) {
    const newSet = latest.set_id !== this.latest?.set_id;
    this.latest = latest;
    this.home = places[0];
    this.places = places;
    if (newSet) {
      this.layers = new Map();
      for (const key of fields.keys()) if (!key.startsWith(latest.set_id + "/")) fields.delete(key);
    }
    const base = ["clear_left", "counted_left", "incomplete_left", "dark_left_min"];
    for (const f of familiesOf(latest)) base.push(`seeing_fa_${f}`, `model_ground_${f}`);
    await Promise.all(base.map((name) => this.layer(name)));
    this.renderPlaces();
    if (!this.map) await this.createMap();
    else if (newSet) this.refreshMap();
    await this.redraw();
  }

  renderPlaces() {
    const list = document.getElementById("places-list");
    list.replaceChildren(
      ...this.places.map((p) => el("li", {}, el("a", { href: `#place/${p.place.id}`, text: p.place.name }))),
    );
  }

  placesOnMap() {
    const [w, s, e, n] = gridBounds(this.grid);
    return this.places.filter((p) => p.place.lon >= w && p.place.lon <= e && p.place.lat >= s && p.place.lat <= n);
  }

  async createMap() {
    const maplibregl = window.maplibregl;
    const container = document.getElementById("map");
    if (!maplibregl) throw new Error("the map library didn't load");
    addProtocol(maplibregl);
    const bounds = gridBounds(this.grid);
    const style = {
      version: 8,
      sources: {
        outline: { type: "geojson", data: OUTLINE_URL },
        edge: { type: "geojson", data: edgeFeature(this.grid) },
        pick: { type: "geojson", data: cellFeature(this.grid, null) },
      },
      layers: [
        { id: "background", type: "background", paint: { "background-color": "#0b1226" } },
        { id: "outline-casing", type: "line", source: "outline", paint: { "line-color": "rgba(4, 8, 22, 0.6)", "line-width": 2.6 } },
        {
          id: "coast",
          type: "line",
          source: "outline",
          filter: ["==", ["get", "kind"], "coast"],
          paint: { "line-color": "rgba(236, 241, 250, 0.85)", "line-width": 1 },
        },
        {
          id: "border",
          type: "line",
          source: "outline",
          filter: ["==", ["get", "kind"], "border"],
          paint: { "line-color": "rgba(236, 241, 250, 0.7)", "line-width": 1, "line-dasharray": [3, 2] },
        },
        { id: "edge", type: "line", source: "edge", paint: { "line-color": "#f0b860", "line-width": 1.2, "line-dasharray": [2, 2] } },
        { id: "pick", type: "line", source: "pick", paint: { "line-color": "#ffffff", "line-width": 2 } },
      ],
    };
    let map;
    try {
      map = new maplibregl.Map({
        container,
        style,
        bounds,
        fitBoundsOptions: { padding: 12 },
        maxZoom: MAX_ZOOM,
        renderWorldCopies: false,
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        attributionControl: false,
      });
    } catch (err) {
      container.replaceChildren(
        el("p", {
          class: "map-failed",
          text: "The map needs WebGL, which this browser doesn't offer. The saved places' full forecasts below still work.",
        }),
      );
      throw err;
    }
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(
      new maplibregl.AttributionControl({ compact: true, customAttribution: "Coastlines and borders: Natural Earth" }),
      "bottom-right",
    );
    this.map = map;
    window.forecastMap = this; // for the page's tests and for looking around in DevTools
    await new Promise((resolve) => map.once("load", resolve));
    // the area fills the map at first; zooming out goes only a little beyond it
    map.setMinZoom(Math.max(0, map.getZoom() - 1.5));
    // the credit starts folded behind its (i) button, so it covers no cells on a phone
    container.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
    map.on("click", (ev) => {
      if (ev.originalEvent.target.closest?.(".place-marker")) return;
      this.pick(cellAt(this.grid, ev.lngLat.lat, ev.lngLat.lng));
    });
    map.on("idle", () => {
      const source = map.getSource("cells");
      if (source) document.body.dataset.mapDrawn = decodeURIComponent(/^cells:\/\/([^/]+)\//.exec(source.tiles[0])[1]);
    });
    this.markers = [];
    this.refreshMap();
  }

  /** The grid's edge, the cells source and the place markers, for the set shown. */
  refreshMap() {
    const map = this.map;
    map.getSource("edge").setData(edgeFeature(this.grid));
    // the grid may differ between sets: the cells source is made again by `redraw`
    if (map.getLayer("cells")) map.removeLayer("cells");
    if (map.getSource("cells")) map.removeSource("cells");
    for (const m of this.markers) m.remove();
    this.markers = this.placesOnMap().map((p) => {
      const link = el(
        "a",
        { class: "place-marker", href: `#place/${p.place.id}`, title: `${p.place.name}: the full forecast` },
        el("span", { class: "dot" }),
        el("span", { class: "name", text: p.place.name }),
      );
      return new window.maplibregl.Marker({ element: link, anchor: "left", offset: [-7, 0] })
        .setLngLat([p.place.lon, p.place.lat])
        .addTo(map);
    });
  }

  // -- drawing ---------------------------------------------------------------------------

  layerName() {
    return { clear: "clear_left", seeing: `seeing_fa_${this.family}`, dark: "dark_left_min", cloud: `total_cloud_${this.family}` }[this.choice];
  }

  key() {
    const hour = this.choice === "cloud" ? this.hour : "";
    return `${this.latest.set_id}/${this.layerName()}/${hour}`;
  }

  async redraw() {
    this.syncControls();
    const hours = this.choice === "cloud" ? this.sliderHours() : [];
    const name = this.layerName();
    const entry = this.latest.layers[name];
    const key = this.key();
    document.body.dataset.mapKey = key; // what the map is about to show (the tests wait on it)
    const values = await this.layer(name);
    if (key !== this.key()) return; // the reader chose again while the layer loaded
    const cells = this.grid.nlat * this.grid.nlon;
    const offset = this.choice === "cloud" ? this.hour * cells : 0;
    fields.set(key, field(this.choice, this.grid, entry, values, offset));
    this.drawCells(key);
    this.renderHour(hours, values, offset, cells);
    this.renderLegend();
    this.renderNote();
    await this.renderCard();
  }

  /** Point the cells source at `key`'s tiles (each tile painted by the `cells`
   *  protocol), making the source the first time. */
  drawCells(key) {
    const map = this.map;
    const tiles = [`cells://${encodeURIComponent(key)}/{z}/{x}/{y}`];
    const source = map.getSource("cells");
    if (source) {
      source.setTiles(tiles);
      return;
    }
    map.addSource("cells", { type: "raster", tiles, tileSize: TILE, maxzoom: MAX_ZOOM, bounds: gridBounds(this.grid) });
    map.addLayer(
      { id: "cells", type: "raster", source: "cells", paint: { "raster-resampling": "nearest", "raster-fade-duration": 0 } },
      "outline-casing",
    );
  }

  renderHour(hours, values, offset, cells) {
    if (this.choice !== "cloud") return;
    const slider = document.getElementById("hour");
    slider.max = String(Math.max(0, hours.length - 1));
    slider.value = String(this.hour);
    const tz = this.home.place.time_zone;
    const t = hours[this.hour];
    const label = document.getElementById("hour-label");
    let none = true;
    for (let k = 0; k < cells; k++) if (values[offset + k] !== 255) none = false;
    const parts = [el("span", { class: "hour-time", text: `${dayLabel(t, tz)} ${clockLabel(t, tz)}` })];
    if (none) parts.push(el("span", { class: "caution", text: `No value from ${familyName(this.home, this.family)} at this hour` }));
    label.replaceChildren(...parts);
    label.dataset.time = t;
    label.dataset.none = String(none);
  }

  renderLegend() {
    const kind = KINDS[this.choice];
    const ticks = el("div", { class: "ticks" }, ...kind.ticks.map((v) => el("span", { text: kind.tickLabel(v) })));
    const codes = Object.values(kind.codes).map((c) =>
      el("li", { class: "code" }, patternSwatch(c.pattern), el("span", { text: c.label })),
    );
    const title = this.choice === "seeing" || this.choice === "cloud" ? `${kind.title}: ${familyName(this.home, this.family)}` : kind.title;
    const parts = [
      el("p", { class: "legend-title", text: title }),
      el("div", { class: "scale" }, el("div", { class: "bar", style: `background: ${scaleGradient(this.choice)}` }), ticks),
    ];
    if (codes.length) parts.push(el("ul", { class: "codes" }, ...codes));
    document.getElementById("legend").replaceChildren(...parts);
  }

  renderNote() {
    const name = this.home.place.name;
    const tz = this.home.place.time_zone;
    const common = `Each spot's numbers are worked out at each model's own ground. Times are ${name} time (${tz}).`;
    const notes = {
      clear:
        "Counted hours are tonight's dark hours from now on (on a night without dark time, the hours with the Sun " +
        "more than 12° down, then the hours with it down). An hour looks clear on most models when more than half " +
        "of the global models with a value for it put it in the clear class, with at least two such models.",
      seeing:
        "Seeing is how much the air blurs a star, in arcseconds (″); smaller is sharper. Every value is " +
        "uncalibrated: computed from the model's temperature and wind with the Osborn–Sarazin formula, above " +
        "1 km over the model's ground, not yet checked against measurements.",
      dark: "Dark time is when the Sun is more than 18° below the horizon.",
      cloud: "The slider steps through tonight's hours. Hours a model has no value for are drawn as “no value”, never filled.",
    };
    const coarse = "GFS and IFS show as larger blocks than ICON-EU: their grid is coarser (0.25° against 0.0625°).";
    const note = document.getElementById("map-note");
    note.classList.remove("caution");
    note.textContent = `${notes[this.choice]} ${coarse} ${common}`;
  }

  // -- the cell card -----------------------------------------------------------------------

  async pick(c) {
    this.picked = c;
    this.map.getSource("pick").setData(cellFeature(this.grid, c));
    await this.renderCard();
  }

  async renderCard() {
    const card = document.getElementById("cell-card");
    const c = this.picked;
    if (!c) {
      card.hidden = true;
      return;
    }
    const g = this.grid;
    const k = c.i * g.nlon + c.j;
    const v = async (name) => (await this.layer(name))[k];
    const [clear, counted, incomplete, dark] = await Promise.all(
      ["clear_left", "counted_left", "incomplete_left", "dark_left_min"].map(v),
    );
    let clearText;
    if (clear === 255) clearText = "No counted hours left tonight.";
    else if (clear === 254) {
      clearText = `Not known: all ${counted} counted hours left are incomplete (fewer than two models have a value).`;
    } else {
      clearText = `${clear} of ${counted} counted hours left look clear on most models`;
      clearText += incomplete > 0 ? ` (${incomplete} incomplete).` : ".";
    }
    const darkText = dark === 0 ? "No dark time left tonight." : `${hoursText(dark)} of dark time left.`;

    const rows = [];
    for (const f of familiesOf(this.latest)) {
      const seeing = await v(`seeing_fa_${f}`);
      const ground = await v(`model_ground_${f}`);
      const scale = this.latest.layers[`seeing_fa_${f}`].scale;
      const items = [
        el("dd", {
          dataset: { field: "seeing", family: f, value: seeing },
          text: seeing === 65535 ? "seeing: no value" : `seeing ${fixed(seeing * scale, 2)}″`,
        }),
        el("dd", {
          class: "ground",
          dataset: { field: "model_ground", family: f, value: ground },
          text: ground === -32768 ? "no run" : `model ground ${metres(ground)}`,
        }),
      ];
      if (this.choice === "cloud") {
        const cloud = (await this.layer(`total_cloud_${f}`))[this.hour * g.nlat * g.nlon + k];
        const at = clockLabel(this.sliderHours()[this.hour], this.home.place.time_zone);
        items.push(el("dd", { dataset: { field: "cloud", family: f, value: cloud }, text: cloud === 255 ? `cloud at ${at}: no value` : `cloud at ${at}: ${cloud} %` }));
      }
      // the model's level count, one of the seeing labels (D47), from the place file
      const model = Object.values(this.home.models).find((m) => m.family === f);
      const levels = model ? ` (${model.level_count} levels)` : "";
      rows.push(el("dt", { text: familyName(this.home, f) + levels }), ...items);
    }

    const lat = g.lat_north - c.i * g.dlat;
    const lon = g.lon_west + c.j * g.dlon;
    const close = el("button", { type: "button", class: "card-close", "aria-label": "Close the cell card", text: "×" });
    close.addEventListener("click", () => this.pick(null));
    card.replaceChildren(
      close,
      el("h3", { text: "This spot tonight" }),
      el("p", { class: "card-where", text: `Map cell at ${latLonText(lat, lon)}` }),
      el("p", { class: "card-label", text: "At the models' ground, not your terrain height." }),
      el("p", { class: "card-clear", dataset: { field: "clear_left", value: clear }, text: clearText }),
      el("p", { dataset: { field: "dark_left", value: dark }, text: darkText }),
      el("p", { class: "card-seeing-head" }, "Median free-atmosphere seeing over the counted hours, ", el("span", { class: "caution", text: "uncalibrated" }), " (Osborn–Sarazin):"),
      el("dl", { class: "card-models" }, ...rows),
    );
    card.dataset.row = String(c.i);
    card.dataset.col = String(c.j);
    card.hidden = false;
  }
}
