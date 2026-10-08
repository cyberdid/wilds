"""Render a zone to PNG without sprites: an overview, or a crop at tile resolution.

    python tools/preview_zone.py data/azeroth/mulgore out.png                  # whole zone
    python tools/preview_zone.py data/azeroth/mulgore out.png 1324 1068 160    # 160x160 tiles around a tile
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw  # noqa: E402

from wilds.azeroth.terrain import Terrain  # noqa: E402
from wilds.azeroth.world import ZoneWorld  # noqa: E402

COLORS = {Terrain.GRASS: (98, 160, 72), Terrain.TALL_GRASS: (70, 130, 58), Terrain.DRY_GRASS: (186, 176, 92),
          Terrain.DIRT: (150, 112, 70), Terrain.ROAD: (204, 178, 120), Terrain.MESA: (158, 130, 108),
          Terrain.BOULDER: (110, 104, 112), Terrain.MOUNTAIN: (92, 66, 44), Terrain.CLIFF: (122, 86, 54),
          Terrain.WATER: (54, 96, 168), Terrain.SHALLOWS: (104, 150, 200), Terrain.VOID: (22, 22, 30)}
KIND = {"npc": (255, 90, 90), "mob": (90, 210, 255), "object": (255, 255, 120), "subzone": (255, 255, 255),
        "settlement": (255, 160, 40), "gate": (255, 160, 40), "lake": (255, 255, 255), "plateau": (255, 255, 255)}


def render(world: ZoneWorld, out: str, cx: int | None, cy: int | None, span: int) -> None:
    if cx is None:
        scale = 8
        w, h = world.geo.width // scale, world.geo.height // scale
        im = Image.new("RGB", (w, h))
        for y in range(h):
            for x in range(w):
                im.putpixel((x, y), COLORS[world.tile(x * scale + scale // 2, y * scale + scale // 2)])
        x0 = y0 = 0
        px = 1 / scale
    else:
        px = max(2, 960 // span)
        x0, y0 = cx - span // 2, cy - span // 2
        im = Image.new("RGB", (span * px, span * px))
        d = ImageDraw.Draw(im)
        for y in range(span):
            for x in range(span):
                d.rectangle((x * px, y * px, x * px + px - 1, y * px + px - 1), fill=COLORS[world.tile(x0 + x, y0 + y)])
    d = ImageDraw.Draw(im)
    for p in world.placements:
        x, y = (p.pos[0] - x0) * px, (p.pos[1] - y0) * px
        if 0 <= x < im.width and 0 <= y < im.height:
            r = 2 if cx is None else max(2, px)
            d.ellipse((x - r, y - r, x + r, y + r), outline=KIND.get(p.kind, (255, 255, 255)))
    im.save(out)


if __name__ == "__main__":
    if len(sys.argv) not in (3, 6):
        sys.exit(__doc__)
    t0 = time.time()
    world = ZoneWorld(sys.argv[1], seed=1)
    cx, cy, span = (int(a) for a in sys.argv[3:6]) if len(sys.argv) == 6 else (None, None, 0)
    render(world, sys.argv[2], cx, cy, span)
    print(f"{sys.argv[2]} in {time.time() - t0:.1f}s")
