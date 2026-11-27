// Loads the current product set and keeps it fresh (D52 item 3): `latest.json` is
// re-checked every 5 minutes with its ETag, the place view is redrawn when its
// `set_id` changes, and a "data not updating" banner shows once the newest data are
// more than an hour old. The map can also show one of the last 7 nights' sunset maps
// (`#night/<date>`, ticket #67); the re-check keeps the night chosen.

import { clockLabel, nightLabel } from "./format.js";
import { MapView } from "./mapview.js";
import { refreshAges, renderAbout, renderCredits, renderHeader, renderRuns, renderSources, renderTable, renderTerrain, renderUpdated, renderVerdict } from "./render.js";

const CHECK_EVERY_MS = 5 * 60 * 1000;
const NOT_UPDATING_AFTER_MS = 60 * 60 * 1000;
const CLOCK_EVERY_MS = 60 * 1000;

const dataBase = new URL(document.querySelector('meta[name="forecast-data"]').content, location.href);
const versionUrl = new URL(document.querySelector('meta[name="page-version"]').content, location.href);

const state = { etag: null, latest: null, places: [], place: null, pageCommit: null };
const mapView = new MapView(dataBase);

async function getJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url.pathname}: HTTP ${response.status}`);
  return response.json();
}

/** The new latest.json and its ETag, or null when the server says it hasn't changed
 *  since the last one shown (304). */
async function fetchLatest() {
  const headers = state.etag ? { "If-None-Match": state.etag } : {};
  const response = await fetch(new URL("latest.json", dataBase), { cache: "no-store", headers });
  if (response.status === 304) return null;
  if (!response.ok) throw new Error(`latest.json: HTTP ${response.status}`);
  return { latest: await response.json(), etag: response.headers.get("ETag") };
}

async function loadPageCommit() {
  try {
    const version = await getJson(versionUrl);
    return typeof version.commit === "string" ? version.commit : null;
  } catch {
    return null;
  }
}

/** Which view the address asks for: `#place/<id>` is a saved place's full view;
 *  `#night/<date>` is the map as forecast at sunset that night (a sunset map);
 *  anything else is the map of Tonight (the landing view, D44 item 9). */
function route() {
  const m = /^#place\/([a-z][a-z0-9_]*)$/.exec(location.hash);
  if (m) return { view: "place", id: m[1] };
  const n = /^#night\/(\d{4}-\d{2}-\d{2})$/.exec(location.hash);
  return { view: "map", night: n ? n[1] : null };
}

/** Load set `latest`: every saved place's file, the default place's first. */
async function show(latest) {
  if (!latest.places.some((p) => p.id === latest.default_place)) {
    throw new Error(`latest.json names no file for ${latest.default_place}`);
  }
  const entries = [...latest.places].sort((a, b) => (b.id === latest.default_place) - (a.id === latest.default_place));
  const files = await Promise.all(entries.map((e) => getJson(new URL(latest.set_path + e.file, dataBase))));
  state.latest = latest;
  state.places = files;
  await showView();
  document.body.dataset.setId = latest.set_id;
}

function renderMapHeader(home, night) {
  const p = home.place;
  const title = night ? `Sunset map: ${nightLabel(night)}` : "Tonight's sky";
  document.title = title;
  document.getElementById("place-name").textContent = title;
  document.getElementById("place-meta").textContent = night
    ? `The map of the forecast area around ${p.name} as it was forecast at sunset there on ` +
      `${nightLabel(night)}, kept for looking back. Times are ${p.name} time (${p.time_zone}).`
    : `The forecast area around ${p.name}. Pick ${p.name} for its full forecast, or any other spot ` +
      `for that spot's numbers. Times are ${p.name} time (${p.time_zone}).`;
}

/** Draw the view the address asks for from the set loaded. */
async function showView() {
  const latest = state.latest;
  if (!latest) return;
  const home = state.places[0];
  const r = route();
  const place = r.view === "place" ? state.places.find((p) => p.place.id === r.id) : null;
  let night = r.night ?? null;
  let message = null; // what the address asked for that isn't there
  if (r.view === "place" && !place) {
    message = `There is no saved place called “${r.id}”; showing the map.`;
  } else if (night && !latest.sunset_maps.some((m) => m.night === night)) {
    message = `There is no sunset map for the night of ${night} (only the last 7 nights' are kept); showing Tonight.`;
    night = null;
  }
  const status = document.getElementById("status");
  status.hidden = message === null;
  status.textContent = message ?? "";
  status.dataset.kind = "view";
  const onMap = !place;
  // the place whose time zone the page's times use: the map uses the default place's
  state.place = place ?? home;
  document.getElementById("map-view").hidden = !onMap;
  document.getElementById("tonight").hidden = onMap;
  document.body.dataset.view = onMap ? "map" : "place";
  renderUpdated(latest, state.place.place.time_zone);
  renderAbout(latest, state.place, state.pageCommit);
  if (onMap) {
    renderMapHeader(home, night);
    const shown = await mapView.show(latest, state.places, night);
    if (night) renderAbout(latest, state.place, state.pageCommit, { night, latest: shown });
  } else {
    renderHeader(place);
    renderVerdict(place);
    renderRuns(latest, place, Date.now());
    renderTerrain(place);
    renderTable(place);
    renderCredits(place);
  }
  document.body.dataset.state = "ready";
}

function showProblem(message) {
  const status = document.getElementById("status");
  status.hidden = false;
  status.dataset.kind = "problem";
  status.textContent = state.latest
    ? `The last check for new data failed (${message}). Showing the data from ${clockLabel(state.latest.written_at, state.place.place.time_zone)}.`
    : `The forecast couldn't be loaded: ${message}.`;
  if (!state.latest) document.body.dataset.state = "error";
}

function updateBanner() {
  const banner = document.getElementById("banner");
  if (!state.latest) return;
  const old = Date.now() - Date.parse(state.latest.written_at) > NOT_UPDATING_AFTER_MS;
  if (old) {
    const at = clockLabel(state.latest.written_at, state.place.place.time_zone);
    banner.textContent = `Data not updating: the newest forecast data were written at ${at}, more than an hour ago.`;
  }
  banner.hidden = !old;
}

async function check() {
  try {
    const fetched = await fetchLatest();
    if (fetched && fetched.latest.set_id !== state.latest?.set_id) await show(fetched.latest);
    // kept only once its set is shown, so a set that failed to load is fetched again
    if (fetched) state.etag = fetched.etag;
    // a failed check's message goes once a check succeeds; the view's own message stays
    const status = document.getElementById("status");
    if (state.latest && status.dataset.kind === "problem") status.hidden = true;
  } catch (err) {
    showProblem(err.message);
  }
  updateBanner();
}

async function start() {
  renderSources();
  window.addEventListener("hashchange", async () => {
    try {
      await showView();
      window.scrollTo(0, 0);
    } catch (err) {
      showProblem(err.message);
    }
  });
  state.pageCommit = await loadPageCommit();
  await check();
  setInterval(check, CHECK_EVERY_MS);
  setInterval(() => {
    refreshAges(Date.now());
    updateBanner();
  }, CLOCK_EVERY_MS);
}

start();
