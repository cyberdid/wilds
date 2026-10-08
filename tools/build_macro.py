"""Macro terrain of a zone from its classic world-map art.

    python tools/build_macro.py data/azeroth/mulgore/maps/WorldMap-Mulgore.jpg data/azeroth/mulgore/macro.json

The map is classified cell by cell (2x2 map pixels) by colour into:
  g grassland, d dry/yellow ground, r interior that is neither (plateaus, lakes, towns),
  m mountain wall (a band around the land), v void beyond the mountains.
The land footprint is the closed shape of the grass; the wall is a band around it.
Only this derived grid is stored in the repository; the map image itself is not.
"""

import colorsys
import json
import sys

from PIL import Image

CELL = 2          # map pixels per macro cell
CLOSE = 7         # cells: gap closed when joining grass patches into one landmass
WALL = 22         # cells of mountain wall around the land


def classify(r: float, g: float, b: float) -> str:
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    h *= 360
    if h >= 52 and s > 0.35:
        return "g"
    if h >= 43 and s > 0.35:
        return "d"
    return "o"  # parchment, relief lines, water and plateaus are told apart below


def dilate(mask: list[list[bool]], n: int) -> list[list[bool]]:
    h, w = len(mask), len(mask[0])
    # separable box dilation with running counts
    horiz = [[False] * w for _ in range(h)]
    for y in range(h):
        row = mask[y]
        last = -10 ** 9
        nxt = [10 ** 9] * (w + 1)
        for x in range(w - 1, -1, -1):
            nxt[x] = x if row[x] else nxt[x + 1]
        for x in range(w):
            if row[x]:
                last = x
            horiz[y][x] = x - last <= n or nxt[x] - x <= n
    out = [[False] * w for _ in range(h)]
    for x in range(w):
        last = -10 ** 9
        nxt = [10 ** 9] * (h + 1)
        for y in range(h - 1, -1, -1):
            nxt[y] = y if horiz[y][x] else nxt[y + 1]
        for y in range(h):
            if horiz[y][x]:
                last = y
            out[y][x] = y - last <= n or nxt[y] - y <= n
    return out


def erode(mask: list[list[bool]], n: int) -> list[list[bool]]:
    inv = [[not v for v in row] for row in mask]
    return [[not v for v in row] for row in dilate(inv, n)]


def fill_holes(mask: list[list[bool]]) -> list[list[bool]]:
    h, w = len(mask), len(mask[0])
    outside = [[False] * w for _ in range(h)]
    stack = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
    while stack:
        x, y = stack.pop()
        if 0 <= x < w and 0 <= y < h and not outside[y][x] and not mask[y][x]:
            outside[y][x] = True
            stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return [[not outside[y][x] for x in range(w)] for y in range(h)]


def largest_component(mask: list[list[bool]]) -> list[list[bool]]:
    """Keep only the biggest 4-connected blob (drops the map's corner ornaments)."""
    h, w = len(mask), len(mask[0])
    seen = [[False] * w for _ in range(h)]
    best: list[tuple[int, int]] = []
    for y0 in range(h):
        for x0 in range(w):
            if mask[y0][x0] and not seen[y0][x0]:
                blob, stack = [], [(x0, y0)]
                seen[y0][x0] = True
                while stack:
                    x, y = stack.pop()
                    blob.append((x, y))
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
                if len(blob) > len(best):
                    best = blob
    out = [[False] * w for _ in range(h)]
    for x, y in best:
        out[y][x] = True
    return out


def main(src: str, dst: str) -> None:
    im = Image.open(src).convert("RGB")
    W, H = im.size[0] // CELL, im.size[1] // CELL
    small = im.resize((W, H), Image.BOX)
    raw = [[classify(*small.getpixel((x, y))) for x in range(W)] for y in range(H)]
    green = [[c in "gd" for c in row] for row in raw]
    land = largest_component(fill_holes(erode(dilate(green, CLOSE), CLOSE - 2)))
    wall = dilate(land, WALL)
    rows = []
    for y in range(H):
        row = []
        for x in range(W):
            if land[y][x]:
                row.append(raw[y][x] if raw[y][x] in "gd" else "r")
            else:
                row.append("m" if wall[y][x] else "v")
        rows.append("".join(row))
    json.dump({"cell_px": CELL, "map_px": list(im.size), "width": W, "height": H,
               "legend": {"g": "grassland", "d": "dry ground", "r": "plateau/lake/town interior",
                          "m": "mountain wall", "v": "beyond the mountains"},
               "source": "classic zone map art (warcraft.wiki.gg File:WorldMap-Mulgore.jpg), classified by colour",
               "rows": rows}, open(dst, "w"), indent=0)
    land_cells = sum(r.count("g") + r.count("d") + r.count("r") for r in rows)
    print(f"{W}x{H} cells; land {land_cells / (W * H):.1%} of the map frame")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
