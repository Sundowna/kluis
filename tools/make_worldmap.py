#!/usr/bin/env python3
"""Build kluis/data/worldmap.json (the Home dot map) from Natural Earth 110m land (public domain).

Dev-only: python3 tools/make_worldmap.py ne_110m_land.geojson
Source: https://www.naturalearthdata.com/ (ne_110m_land), via github.com/nvkelso/natural-earth-vector
The app never touches the network for the map; it only reads the JSON this script writes.
"""
import json
import os
import sys

STEP = 2.5                 # degrees per dot
LAT_TOP, LAT_BOTTOM = 82.5, -57.5   # no Antarctica, like the prototype


def inside(x, y, ring):
    c = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def main(src):
    feats = json.load(open(src))["features"]
    polys = []
    for f in feats:
        g = f["geometry"]
        rings = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for p in rings:
            outer = p[0]
            xs = [pt[0] for pt in outer]
            ys = [pt[1] for pt in outer]
            polys.append((min(xs), max(xs), min(ys), max(ys), p))
    cols = int(360 / STEP)
    rows = int((LAT_TOP - LAT_BOTTOM) / STEP) + 1
    runs = []
    for r in range(rows):
        lat = LAT_TOP - r * STEP
        row = []
        for c in range(cols):
            lon = -180 + (c + 0.5) * STEP
            land = False
            for x0, x1, y0, y1, p in polys:
                if x0 <= lon <= x1 and y0 <= lat <= y1 and inside(lon, lat, p[0]) \
                        and not any(inside(lon, lat, h) for h in p[1:]):
                    land = True
                    break
            row.append(land)
        spans, c = [], 0
        while c < cols:
            if row[c]:
                a = c
                while c < cols and row[c]:
                    c += 1
                spans.append([a, c - 1])
            else:
                c += 1
        runs.append(spans)
    out = {"source": "Natural Earth 110m land (public domain), dot grid", "step": STEP, "lat_top": LAT_TOP,
           "lon_left": -180, "cols": cols, "rows": rows, "runs": runs}
    dest = os.path.join(os.path.dirname(__file__), "..", "kluis", "data", "worldmap.json")
    with open(dest, "w") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(sum(b - a + 1 for row in runs for a, b in row), "dots", rows, "rows")


if __name__ == "__main__":
    main(sys.argv[1])
