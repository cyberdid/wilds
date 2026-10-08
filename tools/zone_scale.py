"""Real-world size of a zone, in yards, from the game client's own map tables.

    python tools/zone_scale.py data/azeroth/mulgore/zone.json mulgore 7 88 462 8 9

The wiki does not store zone sizes. The client does: ``UiMapAssignment`` holds the
world-coordinate rectangle of every map (x runs north-south, y east-west), published
as CSV by wago.tools. The first UiMap id is the zone, the rest are sub-maps; each
sub-map is placed inside the zone as a percentage of the zone map, the same system
the wiki's ``{{co|x|y|map}}`` coordinates use (x% from the west edge, y% from the north).
"""

import csv
import io
import json
import sys
import time
import urllib.request

BASE = "https://wago.tools/db2"


def fetch(table: str) -> list[dict]:
    req = urllib.request.Request(f"{BASE}/{table}/csv", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return list(csv.DictReader(io.StringIO(resp.read().decode("utf-8"))))


def rect(assignments: list[dict], ui_map: int) -> dict:
    rows = [r for r in assignments if int(r["UiMapID"]) == ui_map]
    if not rows:
        raise SystemExit(f"UiMap {ui_map} has no assignment")
    r = rows[0]
    x0, y0, x1, y1 = (float(r[k]) for k in ("Region_0", "Region_1", "Region_3", "Region_4"))
    return {"map_id": int(r["MapID"]), "area_id": int(r["AreaID"]), "x_min": x0, "x_max": x1, "y_min": y0,
            "y_max": y1, "east_west": round(abs(y1 - y0), 1), "north_south": round(abs(x1 - x0), 1)}


def place(child: dict, parent: dict) -> dict:
    """Centre and extent of ``child`` inside ``parent`` as fractions of the parent map."""
    cx, cy = (child["x_min"] + child["x_max"]) / 2, (child["y_min"] + child["y_max"]) / 2
    return {"center_x_pct": round((parent["y_max"] - cy) / parent["east_west"] * 100, 2),
            "center_y_pct": round((parent["x_max"] - cx) / parent["north_south"] * 100, 2),
            "width_pct": round(child["east_west"] / parent["east_west"] * 100, 2),
            "height_pct": round(child["north_south"] / parent["north_south"] * 100, 2)}


def main(argv: list[str]) -> None:
    if len(argv) < 3:
        sys.exit(__doc__)
    out, zone_id, zone_ui = argv[0], argv[1], int(argv[2])
    subs = [int(a) for a in argv[3:]]
    names = {int(r["ID"]): r["Name_lang"] for r in fetch("UiMap")}
    assignments = fetch("UiMapAssignment")
    zone = rect(assignments, zone_ui)
    data = {"id": zone_id, "name": names[zone_ui], "ui_map_id": zone_ui, "yards": zone,
            "source": {"tables": ["UiMap", "UiMapAssignment"], "site": "wago.tools",
                       "fetched": time.strftime("%Y-%m-%d"),
                       "note": "world-coordinate rectangle of the zone map; 1 yard = 1 world unit"},
            "submaps": []}
    for ui in subs:
        r = rect(assignments, ui)
        data["submaps"].append({"name": names[ui], "ui_map_id": ui, "yards": r, "in_zone": place(r, zone)})
    json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{data['name']}: {zone['east_west']} x {zone['north_south']} yards (E-W x N-S)")
    for s in data["submaps"]:
        print(f"  {s['name']}: {s['yards']['east_west']} x {s['yards']['north_south']} yd at "
              f"{s['in_zone']['center_x_pct']}%, {s['in_zone']['center_y_pct']}%")


if __name__ == "__main__":
    main(sys.argv[1:])
