// Writes the verdict's wording from the place file's `tonight` and `moon` sections
// (D48 items 7-10, D44 item 9). Every count, class, basis and state comes from the file,
// worked out by forecast.tonight in Python; this module only picks the words for them
// and never derives a rule (D60 item 1).

import { clockLabel, fixed, hourLabel, wholePercent } from "./format.js";

/** The words for each basis of the counted hours (D48 item 2): the hours in the
 *  headline (one, many), what ended, and the note under the headline (null for dark). */
const BASES = {
  dark: {
    hours: ["dark hour", "dark hours"],
    ended: "Dark time",
    note: null,
  },
  sun_below_12: {
    hours: ["night hour (Sun below −12°)", "night hours (Sun below −12°)"],
    ended: "Night hours (Sun below −12°)",
    note:
      "No dark time tonight: the Sun never gets 18° below the horizon, so the count uses " +
      "the hours with the Sun more than 12° down.",
  },
  sun_down: {
    hours: ["night hour (Sun down)", "night hours (Sun down)"],
    ended: "Night hours (Sun down)",
    note:
      "No dark time tonight: the Sun never gets 18° below the horizon, nor 12°, so the " +
      "count uses the hours with the Sun down.",
  },
};

export const CHIP_LABELS = {
  clear: "Clear",
  some_cloud: "Some cloud",
  cloudy: "Cloudy",
  split: "Split",
  incomplete: "Incomplete",
};

/** Words for each cloud class or "split" in the per-hour agreement. */
export const MAJORITY_WORDS = { clear: "clear", some_cloud: "some cloud", cloudy: "cloudy", split: "split" };

/** Names of the forecast-model families, for a family with no run at this place. */
const FAMILY_NAMES = { gfs: "GFS", icon: "ICON", ifs: "IFS", meps: "MEPS" };

const FAMILY_STATES = {
  ok: "has values",
  stale: "has a stale run (not counted)",
  missing: "has no run for these hours",
  partial: "has a run that lacks these hours",
  off_step: "has no forecast step at these hours",
};

const HOUR_MS = 60 * 60 * 1000;

function plural(n, one, many) {
  return n === 1 ? one : many;
}

export function familyName(place, family) {
  const model = Object.values(place.models).find((m) => m.family === family);
  return model?.name ?? FAMILY_NAMES[family] ?? family.toUpperCase();
}

/** True once the counted hours are over (D48 item 10): the verdict shows only when. */
export function darkTimeEnded(tonight) {
  return tonight.nothing_to_count?.reason === "dark_time_ended";
}

/** "x of n dark hours (left) look clear on most models (k hours incomplete)", or the
 *  nothing-to-count sentence. */
export function headline(place) {
  const t = place.tonight;
  const tz = place.place.time_zone;
  const nothing = t.nothing_to_count;
  if (nothing?.reason === "dark_time_ended") {
    return `${BASES[t.basis].ended} ended at ${clockLabel(nothing.dark_time_ended_at, tz)}`;
  }
  if (nothing?.reason === "not_enough_models") {
    const states = Object.entries(nothing.families).map(
      ([family, state]) => `${familyName(place, family)} ${FAMILY_STATES[state] ?? state}`,
    );
    return `Not enough models for a verdict: ${states.join("; ")}`;
  }
  const [one, many] = BASES[t.basis].hours;
  const hours = plural(t.counted_hours, one, many);
  const left = t.started ? " left" : "";
  const look = plural(t.clear_hours, "looks", "look");
  let text = `${t.clear_hours} of ${t.counted_hours} ${hours}${left} ${look} clear on most models`;
  const k = t.incomplete_hours;
  if (k > 0) text += ` (${k} ${plural(k, "hour", "hours")} incomplete)`;
  return text;
}

/** Why the count isn't over dark hours, or null when it is. */
export function basisNote(tonight) {
  return BASES[tonight.basis].note;
}

/** The strip's chips: class, label, local hours ("22–02", or "22" for one hour) and
 *  how many hours each covers. */
export function chips(place) {
  const tz = place.place.time_zone;
  return place.tonight.chips.map((c) => {
    const first = hourLabel(c.start, tz);
    const last = hourLabel(c.end, tz);
    return {
      cls: c.class,
      label: CHIP_LABELS[c.class] ?? c.class,
      time: c.start === c.end ? first : `${first}–${last}`,
      hours: Math.round((Date.parse(c.end) - Date.parse(c.start)) / HOUR_MS) + 1,
      start: c.start,
      end: c.end,
    };
  });
}

/** "MEPS (regional, not counted): x of n clear (k hours missing)", or null when no
 *  regional-only model covers the place or the counted hours are over. */
export function mepsLine(tonight) {
  const m = tonight.meps;
  if (!m || darkTimeEnded(tonight)) return null;
  let text = `MEPS (regional, not counted): ${m.clear_hours} of ${m.counted_hours} clear`;
  if (m.missing_hours > 0) {
    text += ` (${m.missing_hours} ${plural(m.missing_hours, "hour", "hours")} missing`;
    text += m.stale ? ": its run is more than 24 h old)" : ")";
  }
  return text;
}

/** The seeing range over the counting families (D48 item 7), or null when the counted
 *  hours are over. */
export function seeingLine(tonight) {
  if (darkTimeEnded(tonight)) return null;
  const s = tonight.seeing;
  if (!s) return { text: "Seeing: no model has it tonight", uncalibrated: false };
  const k = Object.keys(s.per_family).length;
  const lo = fixed(s.min_arcsec, 2);
  const hi = fixed(s.max_arcsec, 2);
  const range = lo === hi ? lo : `${lo}–${hi}`;
  return {
    text: `Seeing ${range}″ (free atmosphere, Osborn–Sarazin, ${k} ${plural(k, "model", "models")})`,
    uncalibrated: true,
  };
}

/** "Moon: rises 14:02, sets 03:15, 72 % lit, waxing". */
export function moonLine(place) {
  const m = place.moon;
  const tz = place.place.time_zone;
  const rise = m.rise ? `rises ${clockLabel(m.rise, tz)}` : "does not rise tonight";
  const set = m.set ? `sets ${clockLabel(m.set, tz)}` : "does not set tonight";
  const trend = m.phase_deg < 180 ? "waxing" : "waning";
  return `Moon: ${rise}, ${set}, ${wholePercent(m.illuminated_fraction * 100)} % lit, ${trend}`;
}
