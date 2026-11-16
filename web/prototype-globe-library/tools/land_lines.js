// Splits the land polygons (world-atlas 110m, Natural Earth) into open LineStrings so that no drawn segment
// runs along the antimeridian or along the -90° closing edge of Antarctica. Run: node tools/land_lines.js
const fs = require('fs');
const g = JSON.parse(fs.readFileSync(__dirname + '/../shared/land.geojson', 'utf8'));
const lines = []; let dropped = 0;
const flush = (cur) => { if (cur.length > 1) lines.push(cur); };
for (const f of g.features) for (const poly of f.geometry.coordinates) for (const ring of poly) {
  let cur = [];
  for (const p of ring) {
    if (p[1] < -89.9) { dropped++; flush(cur); cur = []; continue; }               // Antarctica's closing edge along -90°
    if (cur.length && Math.abs(p[0] - cur[cur.length - 1][0]) > 180) { dropped++; flush(cur); cur = []; } // antimeridian jump
    cur.push(p);
  }
  flush(cur);
}
fs.writeFileSync(__dirname + '/../shared/land-lines.geojson', JSON.stringify({ type: 'Feature', properties: {}, geometry: { type: 'MultiLineString', coordinates: lines } }));
console.log(lines.length, 'lines;', dropped, 'segments dropped');
