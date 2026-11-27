// Formatting only: turns the structured values of the product files into text.
// Nothing here decides a verdict, a class or a count (D60 item 1); a value that is
// missing stays blank, and a non-zero value is never shown as zero.

const formatters = new Map();

function formatter(timeZone, options) {
  const key = timeZone + JSON.stringify(options);
  if (!formatters.has(key)) {
    formatters.set(key, new Intl.DateTimeFormat("en-GB", { timeZone, ...options }));
  }
  return formatters.get(key);
}

function parts(date, timeZone, options) {
  const out = {};
  for (const p of formatter(timeZone, options).formatToParts(date)) out[p.type] = p.value;
  return out;
}

/** "13" for 12:00 UTC in Europe/Oslo in winter. */
export function hourLabel(utcText, timeZone) {
  return parts(new Date(utcText), timeZone, { hour: "2-digit", hourCycle: "h23" }).hour;
}

/** "11:00" in the given time zone. */
export function clockLabel(utcText, timeZone) {
  const p = parts(new Date(utcText), timeZone, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  return `${p.hour}:${p.minute}`;
}

/** "Thu 26 Nov" in the given time zone. */
export function dayLabel(utcText, timeZone) {
  const p = parts(new Date(utcText), timeZone, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  return `${p.weekday} ${p.day} ${p.month}`;
}

/** "Wed 25 Nov" for the Night "2026-11-25" (a Night is named by its evening's date). */
export function nightLabel(night) {
  return dayLabel(`${night}T12:00:00Z`, "UTC");
}

/** "06 UTC 26 Nov": how forecast runs are named. */
export function runLabel(utcText) {
  const p = parts(new Date(utcText), "UTC", {
    hour: "2-digit",
    day: "numeric",
    month: "short",
    hourCycle: "h23",
  });
  return `${p.hour} UTC ${p.day} ${p.month}`;
}

/** Whole minutes from `fromUtc` to `nowMs`, as "4 h 5 min" (never rounded up). */
export function ageText(fromUtc, nowMs) {
  const minutes = Math.floor((nowMs - Date.parse(fromUtc)) / 60000);
  if (minutes < 0) return "run time is ahead of this device's clock";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h} h ${m} min old` : `${m} min old`;
}

/** A number to `digits` decimals; blank for null; a non-zero value too small to show
 *  becomes "<0.01" rather than "0.00". */
export function fixed(value, digits) {
  if (value === null || value === undefined) return "";
  const step = 10 ** -digits;
  if (value !== 0 && Math.abs(value) < step / 2) return `<${step.toFixed(digits)}`;
  return value.toFixed(digits);
}

/** A cloud percentage to 0.1 %, without a trailing ".0": "0", "0.3", "91.2", "100".
 *  A trace of cloud is never shown as 0, and a nearly full sky never as 100. */
export function percent(value) {
  if (value === null || value === undefined) return "";
  if (value > 0 && value < 0.05) return "<0.1";
  if (value > 99.95 && value < 100) return ">99.9";
  const text = value.toFixed(1);
  return text.endsWith(".0") ? text.slice(0, -2) : text;
}

/** A percentage to whole numbers: "72". A trace is never shown as 0, and a nearly
 *  full value never as 100. */
export function wholePercent(value) {
  if (value > 0 && value < 0.5) return "<1";
  if (value > 99.5 && value < 100) return ">99";
  return String(Math.round(value));
}

/** Degrees to whole numbers with a true minus sign: "−12". */
export function degrees(value) {
  const rounded = Math.round(value);
  return rounded === 0 ? "0" : String(rounded).replace("-", "−");
}

/** Whole metres: "327 m". */
export function metres(value) {
  return `${Math.round(value)} m`;
}

/** A visibility in metres as kilometres: to 0.01 km below 1 km, so "0.35" (a short
 *  visibility keeps its detail); to 0.1 km from there, so "24.0". */
export function visibilityKm(valueM) {
  return fixed(valueM / 1000, valueM < 1000 ? 2 : 1);
}

/** Whole minutes as hours and minutes: "12 h 3 min", "45 min". */
export function duration(minutes) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
}

/** A point to 0.0001° (the map grid's 0.0625° needs four decimals): "59.7500° N, 9.5000° E". */
export function latLon(lat, lon) {
  return `${fixed(Math.abs(lat), 4)}° ${lat >= 0 ? "N" : "S"}, ${fixed(Math.abs(lon), 4)}° ${lon >= 0 ? "E" : "W"}`;
}

/** Metres as kilometres to 0.01 km: "0.14 km". */
export function km(valueM) {
  return `${fixed(valueM / 1000, 2)} km`;
}
