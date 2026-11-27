// Loads the current product set and keeps it fresh (D52 item 3): `latest.json` is
// re-checked every 5 minutes with its ETag, the place view is redrawn when its
// `set_id` changes, and a "data not updating" banner shows once the newest data are
// more than an hour old.

import { clockLabel } from "./format.js";
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
 *  anything else is the map (the landing view, D44 item 9). */
function route() {
  const m = /^#place\/([a-z][a-z0-9_]*)$/.exec(location.hash);
  return m ? { view: "place", id: m[1] } : { view: "map" };
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
  state.place = files[0];
  await showView();
  document.body.dataset.setId = latest.set_id;
}

function renderMapHeader(home) {
  const p = home.place;
  document.title = "Tonight's sky";
  document.getElementById("place-name").textContent = "Tonight's sky";
  document.getElementById("place-meta").textContent =
    `The forecast area around ${p.name}. Pick ${p.name} for its full forecast, or any other spot ` +
    `for that spot's numbers. Times are ${p.name} time (${p.time_zone}).`;
}

/** Draw the view the address asks for from the set loaded. */
async function showView() {
  const latest = state.latest;
  if (!latest) return;
  const home = state.places[0];
  const r = route();
  const place = r.view === "place" ? state.places.find((p) => p.place.id === r.id) : null;
  const status = document.getElementById("status");
  if (r.view === "place" && !place) {
    status.hidden = false;
    status.textContent = `There is no saved place called “${r.id}”; showing the map.`;
  }
  const onMap = !place;
  document.getElementById("map-view").hidden = !onMap;
  document.getElementById("tonight").hidden = onMap;
  document.body.dataset.view = onMap ? "map" : "place";
  renderUpdated(latest, home.place.time_zone);
  renderAbout(latest, place ?? home, state.pageCommit);
  if (onMap) {
    renderMapHeader(home);
    await mapView.show(latest, state.places);
  } else {
    state.place = place;
    renderHeader(place);
    renderUpdated(latest, place.place.time_zone);
    renderVerdict(place);
    renderRuns(latest, place, Date.now());
    renderTerrain(place);
    renderTable(place);
    renderCredits(place);
    status.hidden = true;
  }
  document.body.dataset.state = "ready";
}

function showProblem(message) {
  const status = document.getElementById("status");
  status.hidden = false;
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
    if (state.latest) document.getElementById("status").hidden = true;
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
