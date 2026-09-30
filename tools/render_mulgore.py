"""Render a patch of Mulgore with the real sprites, without a window.

    python tools/render_mulgore.py out.png <tile x> <tile y> [tiles wide] [tiles high] [scale]
    python tools/render_mulgore.py out.png village        # Bloodhoof Village
    python tools/render_mulgore.py out.png narache        # Camp Narache

A preview, not the game renderer: ground tiles by terrain, the placed people, creatures and
landmarks of the content pack, y-sorted. The real chunked scene builds on the same pieces.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame  # noqa: E402

from wilds.azeroth import content, quests  # noqa: E402
from wilds.azeroth.terrain import Terrain  # noqa: E402
from wilds.azeroth.world import ZoneWorld  # noqa: E402
from wilds.gfx.bank import SpriteBank  # noqa: E402
from wilds.gfx.sprites import load_azeroth  # noqa: E402

PACK = Path(__file__).resolve().parents[1] / "data" / "azeroth" / "mulgore"
TILE = 16
GROUND = {Terrain.GRASS: "az.ground.grass", Terrain.TALL_GRASS: "az.ground.tall_grass",
          Terrain.DRY_GRASS: "az.ground.dry_grass", Terrain.DIRT: "az.ground.dirt", Terrain.ROAD: "az.ground.road",
          Terrain.MESA: "az.ground.mesa", Terrain.WATER: "az.ground.water", Terrain.SHALLOWS: "az.ground.shallows",
          Terrain.BOULDER: "az.ground.grass", Terrain.MOUNTAIN: "az.mountain.top", Terrain.CLIFF: "az.cliff.face"}
OUTFITS = {"warrior": "guard", "hunter": "hunter", "shaman": "shaman", "druid": "druid", "priest": "priest",
           "trainer": "trainer", "merchant": "merchant", "elder": "elder", "innkeeper": "merchant"}
DECO = ("az.deco.flower_red", "az.deco.flower_yellow", "az.deco.flower_blue", "az.deco.tuft", "az.deco.stones")


def pick(bank, base: str, x: int, y: int) -> str:
    vs = bank.registry.variants(base)
    return vs[(x * 7 + y * 13) % len(vs)]


def outfit_of(rec: dict) -> str:
    text = (rec["info"].get("profession", "") + " " + rec["title"]).lower()
    return next((v for k, v in OUTFITS.items() if k in text), "civilian")


def render(world: ZoneWorld, bank: SpriteBank, cx: int, cy: int, w: int, h: int, scale: int) -> pygame.Surface:
    x0, y0 = cx - w // 2, cy - h // 2
    surf = pygame.Surface((w * TILE * scale, h * TILE * scale))
    surf.fill((20, 20, 28))
    things = []
    for ty in range(h):
        for tx in range(w):
            x, y = x0 + tx, y0 + ty
            t = world.tile(x, y)
            if t is Terrain.VOID:
                continue
            base = GROUND[t]
            surf.blit(bank.frame(pick(bank, base, x, y), 0.0, scale), (tx * TILE * scale, ty * TILE * scale))
            if t is Terrain.BOULDER:
                things.append((y, x, pick(bank, "az.boulder", x, y)))
            elif t in (Terrain.GRASS, Terrain.TALL_GRASS, Terrain.DRY_GRASS) and (x * 31 + y * 17) % 23 == 0:
                things.append((y - 0.5, x, pick(bank, DECO[(x + y) % len(DECO)], x, y)))
    recs = {quests.clean(r["title"]): r for k in ("npc", "mob") for r in content.load(PACK, k)}
    for p in world.placements:
        tx, ty = p.pos[0] - x0, p.pos[1] - y0
        if not (0 <= tx < w and 0 <= ty < h):
            continue
        rec = recs.get(quests.clean(p.title))
        if p.kind == "npc" and rec:
            race = quests.clean(rec["info"].get("race", ""))
            body = "tauren_f" if (rec["info"].get("gender", "").lower() == "female") else "tauren_m"
            if race and race not in ("tauren", "highmountain tauren", "") and f"az.person.{race.replace(' ', '_')}.civilian.idle" in bank:
                name = f"az.person.{race.replace(' ', '_')}.civilian.idle"
            else:
                name = f"az.person.{body}.{outfit_of(rec)}.idle"
            if name in bank:
                things.append((p.pos[1], p.pos[0], name))
        elif p.kind == "mob" and rec:
            species = "_".join(quests.clean(rec["info"].get("race", "")).replace("'", "").split())
            name = f"az.creature.{species}.idle"
            if name in bank:
                things.append((p.pos[1], p.pos[0], name))
    things += SETTLEMENTS(world, x0, y0, w, h)
    for y, x, name in sorted(things, key=lambda t: (t[0], t[1])):
        fr = bank.frame(name, 0.0, scale)
        ax, ay = bank.anchor(name, scale)
        gx, gy = ((x - x0) * TILE + TILE // 2) * scale, ((y - y0) * TILE + TILE - 1) * scale
        surf.blit(fr, (gx - ax, gy - ay))
    return surf


def SETTLEMENTS(world, x0, y0, w, h):
    """A few buildings around the settlements so the place reads as a place."""
    out = []
    layouts = {"Bloodhoof Village": [("az.obj.hut_large", -6, -4), ("az.obj.hut_small@0", 5, -5),
                                     ("az.obj.hut_small@1", -8, 3), ("az.obj.tent@0", 7, 2), ("az.obj.tent@1", -3, 6),
                                     ("az.obj.totem_pole@0", 1, -3), ("az.obj.bonfire", 0, 1), ("az.obj.well", 3, 4),
                                     ("az.obj.banner", -2, -1), ("az.obj.inn", 10, -3), ("az.obj.forge", -10, -1),
                                     ("az.obj.kodo_pen", 9, 7), ("az.obj.drying_rack", 4, -1)],
               "Camp Narache": [("az.obj.tent@0", -4, -2), ("az.obj.tent@2", 4, -3), ("az.obj.bonfire", 0, 0),
                                ("az.obj.training_dummy", 6, 3), ("az.obj.totem_pole@1", -1, -4),
                                ("az.obj.hut_small@0", -6, 4)]}
    for p in world.placements:
        for dx, dy, pos_name in [(d[1], d[2], d[0]) for d in layouts.get(p.title, [])]:
            x, y = p.pos[0] + dx, p.pos[1] + dy
            if x0 <= x < x0 + w and y0 <= y < y0 + h and world.passable((x, y)):
                out.append((y, x, pos_name))
    return out


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        sys.exit(__doc__)
    pygame.display.init()
    pygame.display.set_mode((1, 1))
    world = ZoneWorld(PACK, seed=1)
    bank = SpriteBank(load_azeroth())
    if argv[1] in ("village", "narache"):
        spot = world.at("Bloodhoof Village" if argv[1] == "village" else "Camp Narache").pos
        cx, cy, rest = spot[0], spot[1], argv[2:]
    else:
        cx, cy, rest = int(argv[1]), int(argv[2]), argv[3:]
    w, h, scale = (int(rest[i]) if len(rest) > i else d for i, d in enumerate((44, 26, 3)))
    pygame.image.save(render(world, bank, cx, cy, w, h, scale), argv[0])
    print(f"{argv[0]}: {w}x{h} tiles = {w * 2}x{h * 2} yards around tile ({cx}, {cy})")


if __name__ == "__main__":
    main(sys.argv[1:])
