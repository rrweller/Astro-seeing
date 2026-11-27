// Draws a saved place's view from `latest.json` and its place file (schemas
// f1-latest/1 and f1-place/1). It formats what the files give and derives no rule
// (D60 item 1): shading comes from each hour's `sun_class`, greying from `past`, a
// model's missing hour or null value stays a blank cell. The verdict's wording is
// verdict.js's, from the file's `tonight` and `moon`.

import { ageText, clockLabel, dayLabel, degrees, fixed, hourLabel, km, metres, percent, runLabel } from "./format.js";
import { SOURCES } from "./sources.js";
import { MAJORITY_WORDS, basisNote, chips, headline, mepsLine, moonLine, seeingLine } from "./verdict.js";

/** Display names of the Cₙ² models by their keys in the place file. */
const CN2_NAMES = { osborn_sarazin: "Osborn–Sarazin", tatarskii: "Tatarskii + HMNSP99" };

const MISSING_REASONS = {
  off_step: "no value: the model has no forecast step at this hour",
  no_run: "no value: the model has no usable run",
  partial: "no value: the model's run lacks this step",
};

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c !== null && c !== undefined) node.append(c);
  return node;
}

function modelIds(place) {
  const ids = [];
  for (const hour of place.hours) for (const id of Object.keys(hour.models)) if (!ids.includes(id)) ids.push(id);
  return ids;
}

function modelName(place, id) {
  return place.models[id]?.name ?? id.toUpperCase();
}

// -- header -------------------------------------------------------------------------

export function renderHeader(place) {
  const p = place.place;
  document.title = `${p.name}: tonight's sky`;
  document.getElementById("place-name").textContent = p.name;
  const lat = `${Math.abs(p.lat)}° ${p.lat >= 0 ? "N" : "S"}`;
  const lon = `${Math.abs(p.lon)}° ${p.lon >= 0 ? "E" : "W"}`;
  const source = p.height_source === "glo30" ? "Copernicus GLO-30" : "entered by hand";
  document.getElementById("place-meta").textContent =
    `${lat}, ${lon}, ground ${metres(p.height_m)} above sea level (${source}). ` +
    `Times are ${p.name} time (${p.time_zone}).`;
  const first = place.hours[0].time;
  const last = place.hours[place.hours.length - 1].time;
  document.getElementById("night-title").textContent =
    `Tonight, ${dayLabel(first, p.time_zone)} to ${dayLabel(last, p.time_zone)}`;
}

export function renderUpdated(latest, timeZone) {
  document.getElementById("updated").textContent = `Updated ${clockLabel(latest.written_at, timeZone)}`;
}

// -- verdict ------------------------------------------------------------------------

function showLine(id, text) {
  const node = document.getElementById(id);
  node.hidden = text === null;
  node.textContent = text ?? "";
  return node;
}

export function renderVerdict(place) {
  const box = document.getElementById("verdict");
  const t = place.tonight;
  box.hidden = !t;
  if (!t) return;
  box.dataset.basis = t.basis;
  showLine("headline", headline(place));
  showLine("basis-note", basisNote(t));
  const where = `${place.place.name} time`;
  document.getElementById("strip").replaceChildren(
    ...chips(place).map((c) =>
      el(
        "li",
        {
          class: `chip chip-${c.cls}`,
          dataset: { class: c.cls, start: c.start, end: c.end },
          style: `flex-grow:${c.hours}`,
          title: `${c.label}: ${c.hours} ${c.hours === 1 ? "hour" : "hours"}, ${c.time.replace("–", " to ")} ${where}`,
        },
        el("span", { class: "chip-class", text: c.label }),
        el("span", { class: "chip-time", text: c.time }),
      ),
    ),
  );
  showLine("meps-line", mepsLine(t));
  const seeing = seeingLine(t);
  const line = showLine("seeing-line", seeing && seeing.text);
  if (seeing?.uncalibrated) {
    line.title = Object.entries(t.seeing.per_family).map(([f, v]) => `${f}: ${fixed(v, 2)}″`).join(", ");
    line.append(", ", el("strong", { class: "caution", text: "uncalibrated" }));
  }
  showLine("moon-line", place.moon ? moonLine(place) : null);
}

// -- runs ---------------------------------------------------------------------------

export function renderRuns(latest, place, nowMs) {
  const list = document.getElementById("runs");
  list.replaceChildren();
  // the place's own verdict says which runs are stale at this place (D48 item 5)
  const runs = place.tonight ? place.tonight.runs : latest.runs;
  for (const id of modelIds(place)) {
    const run = runs[id];
    const item = el("li", { dataset: { model: id } }, el("span", { class: "run-model", text: modelName(place, id) }));
    if (!run) {
      item.append(" no run yet");
    } else {
      item.append(
        ` run of ${runLabel(run.run_time)}, `,
        el("span", { class: "run-age", dataset: { runTime: run.run_time }, text: ageText(run.run_time, nowMs) }),
      );
      if (run.stale) item.append(" ", el("strong", { class: "stale", text: "stale, not counted" }));
    }
    list.append(item);
  }
}

/** Refreshes the run ages shown, as time passes. */
export function refreshAges(nowMs) {
  for (const span of document.querySelectorAll(".run-age")) span.textContent = ageText(span.dataset.runTime, nowMs);
}

// -- table --------------------------------------------------------------------------

function seeingCaption(place, id, cn2) {
  const info = place.models[id];
  const p = place.place;
  const name = modelName(place, id);
  let text = `Seeing, uncalibrated: ${CN2_NAMES[cn2] ?? cn2} Cₙ² model`;
  if (!info) return `${text}, from ${name}, which has no run.`;
  text += ` on the ${info.level_count} pressure levels of ${name}. `;
  if (info.raise_m > 0) {
    text +=
      `Observer at ${metres(info.observer_height_m)}: the place's ${metres(p.height_m)}, ` +
      `raised ${metres(info.raise_m)} to the model's ground.`;
  } else {
    text += `Observer at the place's height, ${metres(info.observer_height_m)}.`;
  }
  return text;
}

function totalNote(place, id) {
  const gap = place.models[id]?.gap_to_first_level_m;
  if (gap === null || gap === undefined) return "no ground layer; where the column starts above the model ground is not known";
  return `no ground layer; the column starts ${km(gap)} above the model ground`;
}

function rowsFor(place, id) {
  const cloud = (key) => (m) => m.cloud[key];
  const rows = [
    { group: "Cloud cover (%)", quantity: "total", label: "Total", value: cloud("total_pct"), format: percent, kind: "cloud" },
    { quantity: "low", label: "Low", value: cloud("low_pct"), format: percent, kind: "cloud" },
    { quantity: "mid", label: "Mid", value: cloud("mid_pct"), format: percent, kind: "cloud" },
    { quantity: "high", label: "High", value: cloud("high_pct"), format: percent, kind: "cloud" },
    {
      group: "Wind",
      quantity: "wind200",
      label: "200 hPa (m/s)",
      note: "the jet-stream level, about 12 km up",
      value: (m) => m.wind_200hpa_ms,
      format: (v) => fixed(v, 1),
    },
  ];
  for (const cn2 of ["osborn_sarazin", "tatarskii"]) {
    const caption = seeingCaption(place, id, cn2);
    const see = (key) => (m) => m.seeing[cn2][key];
    rows.push(
      {
        group: caption,
        groupClass: "seeing-head",
        quantity: `fa_${cn2}`,
        label: "Free atmosphere (″)",
        note: "above observer + 1 km",
        value: see("free_atmosphere_arcsec"),
        format: (v) => fixed(v, 2),
        seeing: true,
      },
      {
        quantity: `total_seeing_${cn2}`,
        label: "Total (″)",
        note: totalNote(place, id),
        value: see("total_arcsec"),
        format: (v) => fixed(v, 2),
        seeing: true,
      },
      {
        quantity: `hbar_${cn2}`,
        label: "H̄ (km)",
        note: "effective turbulence altitude above the observer",
        value: see("hbar_km"),
        format: (v) => fixed(v, 1),
        seeing: true,
      },
    );
  }
  return rows;
}

function hourClasses(hour) {
  return [`sun-${hour.sun_class}`, hour.past === true ? "past" : null].filter(Boolean).join(" ");
}

/** The rows over all global models: their agreement (D48 item 4) and the Moon. */
const VERDICT_ROWS = [
  {
    quantity: "agreement",
    label: "Models agree",
    note: "global models putting the hour in the clear class, of those with a value",
    value: (hour) => (hour.agreement && hour.agreement.of > 0 ? hour.agreement : null),
    content: (a) => [
      el("span", { class: "agree-count", text: `${a.clear}/${a.of} clear` }),
      el("span", { class: "agree-class", text: a.state === "incomplete" ? "incomplete" : MAJORITY_WORDS[a.majority] }),
    ],
    cellClass: (a) => `agree-${a.state} major-${a.majority}`,
    dataValue: (a) => `${a.clear}/${a.of}`,
    missingTitle: "no global model has a value this hour",
  },
  {
    quantity: "moon",
    label: "Moon altitude (°)",
    note: "below 0: under the horizon",
    value: (hour) => hour.moon_altitude_deg,
    content: (v) => [degrees(v)],
    cellClass: (v) => (v < 0 ? "below" : "above"),
    dataValue: (v) => String(v),
    missingTitle: "no value",
  },
];

function renderVerdictRows(place, body, span) {
  if (!place.tonight) return;
  body.append(
    el("tr", { class: "model-head" }, el("th", { colspan: span, scope: "colgroup" }, el("div", { class: "cap" }, el("span", { class: "model-name", text: "All global models" })))),
  );
  for (const row of VERDICT_ROWS) {
    const tr = el(
      "tr",
      { class: `verdict-row ${row.quantity}` },
      el("th", { scope: "row" }, el("span", { class: "label", text: row.label }), el("span", { class: "row-note", text: row.note })),
    );
    for (const hour of place.hours) {
      const value = row.value(hour);
      const missing = value === null || value === undefined;
      const attrs = {
        class: [hourClasses(hour), missing ? "missing" : row.cellClass(value)].filter(Boolean).join(" "),
        dataset: { model: "all", quantity: row.quantity, time: hour.time },
        title: missing ? row.missingTitle : null,
      };
      if (!missing) attrs.dataset.value = row.dataValue(value);
      tr.append(el("td", attrs, ...(missing ? [] : row.content(value))));
    }
    body.append(tr);
  }
}

export function renderTable(place) {
  const tz = place.place.time_zone;
  const table = document.getElementById("hours");
  const span = place.hours.length + 1;
  const head = el("tr", {}, el("th", { class: "corner", scope: "col", text: `${place.place.name} time` }));
  place.hours.forEach((hour, k) => {
    const label = hourLabel(hour.time, tz);
    const showDay = k === 0 || label === "00";
    head.append(
      el(
        "th",
        {
          scope: "col",
          class: [hourClasses(hour), hour.counted === true ? "counted" : null].filter(Boolean).join(" "),
          dataset: { time: hour.time, sun: hour.sun_class },
          title: hour.sun_class.replace(/_/g, " ") + (hour.counted === true ? ", counted in the verdict" : ""),
        },
        el("span", { class: "hour", text: label }),
        el("span", { class: "day", text: showDay ? dayLabel(hour.time, tz).split(" ")[0] : "" }),
      ),
    );
  });
  const body = el("tbody");
  renderVerdictRows(place, body, span);
  let uid = 0;
  for (const id of modelIds(place)) {
    const regional = place.models[id]?.regional ? el("span", { class: "not-counted", text: " (regional, not counted)" }) : null;
    const name = el("span", { class: "model-name", text: modelName(place, id) });
    body.append(
      el("tr", { class: "model-head", dataset: { model: id } }, el("th", { colspan: span, scope: "colgroup" }, el("div", { class: "cap" }, name, regional))),
    );
    let groupId = null;
    for (const row of rowsFor(place, id)) {
      if (row.group) {
        groupId = `g${++uid}`;
        body.append(el("tr", { class: `group-head ${row.groupClass ?? ""}` }, el("th", { colspan: span, scope: "colgroup" }, el("div", { class: "cap", id: groupId, text: row.group }))));
      }
      const labelId = `r${++uid}`;
      const tr = el(
        "tr",
        { class: row.kind ?? "" },
        el("th", { scope: "row", id: labelId }, el("span", { class: "label", text: row.label }), row.note ? el("span", { class: "row-note", text: row.note }) : null),
      );
      for (const hour of place.hours) {
        const m = hour.models[id];
        const value = !m || "missing" in m ? null : row.value(m);
        const attrs = {
          class: [hourClasses(hour), value === null ? "missing" : null].filter(Boolean).join(" "),
          dataset: { model: id, quantity: row.quantity, time: hour.time },
          "aria-describedby": row.seeing ? `${groupId} ${labelId}` : null,
        };
        if (value === null) {
          attrs.title = m && "missing" in m ? MISSING_REASONS[m.missing] ?? `no value: ${m.missing}` : "no value";
        } else {
          attrs.dataset.value = String(value);
          // the veil's thickness only: the text and data-value keep the file's value
          if (row.kind === "cloud") attrs.style = `--cover:${Math.min(Math.max(value, 0), 100) / 100}`;
        }
        tr.append(el("td", attrs, value === null ? "" : row.format(value)));
      }
      body.append(tr);
    }
  }
  table.replaceChildren(el("thead", {}, head), body);
}

// -- credits, about, sources --------------------------------------------------------

export function renderCredits(place) {
  const list = document.getElementById("credits");
  list.replaceChildren(...Object.entries(place.models).map(([id, m]) => el("li", { dataset: { model: id }, text: m.credit })));
}

export function renderAbout(latest, place, pageCommit) {
  const tz = place.place.time_zone;
  const items = [
    ["Data set", `${latest.set_id}, written ${clockLabel(latest.written_at, tz)} ${tz} (${latest.written_at})`],
    ["Back-end commit", latest.provenance.commit],
    ["Config hash", latest.provenance.config_hash],
    ["Software", Object.entries(latest.provenance.software).map(([k, v]) => `${k} ${v}`).join(", ")],
  ];
  if (place.provenance.commit !== latest.provenance.commit) items.push(["Place file commit", place.provenance.commit]);
  if (place.provenance.config_hash !== latest.provenance.config_hash) items.push(["Place file config hash", place.provenance.config_hash]);
  const runIds = Object.entries(place.provenance.run_ids);
  items.push(["Run IDs", runIds.length ? runIds.map(([id, n]) => `${modelName(place, id)}: ${n}`).join(", ") : "none"]);
  items.push(["This page's commit", pageCommit ?? "not recorded (this copy of the page wasn't installed by astro web deploy)"]);
  const list = document.getElementById("about-list");
  list.replaceChildren();
  for (const [k, v] of items) list.append(el("dt", { text: k }), el("dd", { text: v }));
}

export function renderSources() {
  const box = document.getElementById("sources-list");
  box.replaceChildren(
    ...SOURCES.map((s) =>
      el(
        "section",
        { class: "source", dataset: { source: s.id } },
        el("h3", { text: s.provider }),
        ...s.paragraphs.map((t) => el("p", { text: t })),
        s.link ? el("p", { class: "source-link" }, el("a", { href: s.link, rel: "noreferrer", text: s.link })) : null,
      ),
    ),
  );
}
