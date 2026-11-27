"""Write the map page's light outline (coastlines and country borders) for one box.

The map draws no base map from an outside server (ticket #66); this outline is the only
geography under the layers. It comes from Natural Earth 1:10m (public domain), as
redistributed in TopoJSON by the npm package world-atlas 2.0.2 (ISC). Fetch and check
the package first (see web/vendor/README.md), then run, for example:

    pixi run python -I scripts/make_map_outline.py <unpacked>/package/countries-10m.json \
        --box 4.65 54.67 14.65 64.67 --out web/vendor/natural-earth/outline-kongsberg-box.json

Each TopoJSON arc used by one country is coastline, one shared by two countries is a
border. Lines are cut to the box widened by ``--margin`` degrees (a line that leaves it
keeps its first point outside, so it reaches the box's edge), and coordinates are
rounded to 4 decimals (about 10 m), far below the 1:10m data's own detail.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    """The topology's arcs as lon/lat lists (quantized, delta-encoded arcs undone)."""
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    out = []
    for arc in topo["arcs"]:
        x = y = 0
        points = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            points.append((x * sx + tx, y * sy + ty))
        out.append(points)
    return out


def arc_uses(geometries: list[dict]) -> Counter:
    """How many geometries use each arc (an arc index ``~i`` is arc ``i`` reversed)."""
    uses: Counter = Counter()
    for g in geometries:
        rings = g["arcs"] if g["type"] == "Polygon" else [r for p in g["arcs"] for r in p]
        used = {i if i >= 0 else ~i for ring in rings for i in ring}
        uses.update(used)
    return uses


def cut(points, west, south, east, north) -> list[list[tuple[float, float]]]:
    """``points`` cut to the box: the runs of points inside, each with its neighbour
    outside on either side, so no drawn line stops short of the box's edge."""
    inside = [west <= x <= east and south <= y <= north for x, y in points]
    lines, current = [], []
    for k, p in enumerate(points):
        near = inside[k] or (k > 0 and inside[k - 1]) or (k + 1 < len(points) and inside[k + 1])
        if near:
            current.append(p)
        elif current:
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return [line for line in lines if len(line) > 1]


def outline(topo: dict, box: tuple[float, float, float, float], margin: float) -> dict:
    west, south, east, north = box
    wide = (west - margin, south - margin, east + margin, north + margin)
    arcs = decode_arcs(topo)
    uses = arc_uses(topo["objects"]["countries"]["geometries"])
    kinds: dict[str, list] = {"coast": [], "border": []}
    for i, count in sorted(uses.items()):
        kind = "coast" if count == 1 else "border"
        for line in cut(arcs[i], *wide):
            kinds[kind].append([[round(x, 4), round(y, 4)] for x, y in line])
    features = [
        {
            "type": "Feature",
            "properties": {"kind": kind},
            "geometry": {"type": "MultiLineString", "coordinates": lines},
        }
        for kind, lines in kinds.items()
    ]
    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("topojson", type=Path, help="world-atlas countries-10m.json")
    ap.add_argument("--box", type=float, nargs=4, metavar=("W", "S", "E", "N"), required=True)
    ap.add_argument("--margin", type=float, default=1.0)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    doc = outline(json.loads(args.topojson.read_text()), tuple(args.box), args.margin)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":")) + "\n")
    tmp.replace(args.out)
    n = {f["properties"]["kind"]: len(f["geometry"]["coordinates"]) for f in doc["features"]}
    print(f"{args.out}: {n['coast']} coast lines, {n['border']} border lines")


if __name__ == "__main__":
    main()
