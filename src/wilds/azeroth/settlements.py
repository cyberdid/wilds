"""What stands in Mulgore's settlements, at real scale, and Thunder Bluff's rises.

A village is not one hut: Bloodhoof Village spans a few hundred yards. Each settlement gets a
recipe (how many huts, tents, pens, totems ...) that is scattered deterministically around
its centre on walkable ground, never on top of each other. Thunder Bluff is a city on mesas:
its rises become round platforms joined by rope bridges.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .terrain import Terrain

if TYPE_CHECKING:
    from .world import ZoneWorld

Pos = tuple[int, int]


@dataclass(frozen=True)
class Structure:
    sprite: str   # az.* sprite name (variants as "name@N")
    pos: Pos      # ground point of the sprite's anchor, in tiles
    size: int     # footprint in tiles, for spacing


@dataclass(frozen=True)
class Platform:
    name: str
    center: Pos
    radius: int


# sprite, count, min radius, max radius, footprint in tiles
Recipe = list[tuple[str, int, int, int, int]]

RECIPES: dict[str, tuple[int, Recipe]] = {
    "Bloodhoof Village": (34, [
        ("az.obj.totem_pole@0", 1, 0, 4, 3), ("az.obj.bonfire", 3, 3, 12, 2), ("az.obj.well", 2, 6, 18, 2),
        ("az.obj.hut_large", 3, 10, 26, 6), ("az.obj.hut_small@0", 5, 8, 32, 4), ("az.obj.hut_small@1", 5, 8, 32, 4),
        ("az.obj.tent@0", 3, 10, 34, 4), ("az.obj.tent@1", 3, 10, 34, 4), ("az.obj.tent@2", 3, 10, 34, 4),
        ("az.obj.totem_pole@1", 2, 12, 30, 3), ("az.obj.banner", 4, 6, 26, 2), ("az.obj.drying_rack", 4, 8, 30, 3),
        ("az.obj.inn", 1, 14, 24, 6), ("az.obj.forge", 1, 16, 28, 3), ("az.obj.anvil", 1, 16, 28, 2),
        ("az.obj.stable", 1, 26, 40, 5), ("az.obj.kodo_pen", 6, 28, 46, 4), ("az.obj.barrel@0", 4, 8, 34, 1),
        ("az.obj.crate@1", 4, 8, 34, 1), ("az.node.prairie_flower", 3, 10, 44, 1),
        ("az.obj.haystack", 4, 24, 40, 3), ("az.obj.cooking_pot", 3, 2, 10, 1), ("az.obj.torch", 7, 6, 32, 1),
        ("az.obj.signpost", 3, 30, 40, 1), ("az.obj.prayer_flags", 2, 10, 26, 4),
        ("az.obj.stone_circle", 1, 20, 30, 6), ("az.obj.hide_stretcher", 3, 10, 30, 3),
        ("az.obj.kodo_saddle_rack", 2, 24, 36, 3), ("az.obj.grave_cairn", 4, 30, 40, 1)]),
    "Camp Narache": (28, [
        ("az.obj.bonfire", 2, 0, 8, 2), ("az.obj.totem_pole@1", 2, 6, 20, 3), ("az.obj.tent@0", 3, 8, 30, 4),
        ("az.obj.tent@2", 3, 8, 30, 4), ("az.obj.hut_small@0", 2, 12, 32, 4), ("az.obj.training_dummy", 5, 8, 26, 2),
        ("az.obj.banner", 2, 4, 20, 2), ("az.obj.drying_rack", 2, 10, 28, 3), ("az.obj.barrel@1", 3, 6, 26, 1),
        ("az.obj.torch", 4, 6, 24, 1), ("az.obj.signpost", 2, 22, 28, 1), ("az.obj.haystack", 1, 14, 24, 3),
        ("az.obj.cooking_pot", 2, 2, 8, 1), ("az.obj.hide_stretcher", 2, 10, 24, 3)]),
    "Camp Sungraze": (24, [
        ("az.obj.bonfire", 2, 0, 8, 2), ("az.obj.totem_pole@2", 1, 4, 14, 3), ("az.obj.tent@1", 3, 8, 26, 4),
        ("az.obj.tent@2", 2, 8, 26, 4), ("az.obj.hut_small@1", 2, 10, 28, 4), ("az.obj.drying_rack", 2, 8, 24, 3),
        ("az.obj.torch", 3, 6, 20, 1), ("az.obj.cooking_pot", 1, 2, 8, 1), ("az.obj.haystack", 1, 12, 20, 3)]),
    "Venture Co. Mine": (26, [
        ("az.obj.mine_entrance", 1, 0, 6, 6), ("az.obj.goblin_shack", 3, 8, 26, 4), ("az.obj.ore_cart", 3, 6, 24, 3),
        ("az.obj.crate@0", 5, 6, 26, 1), ("az.obj.barrel@0", 4, 6, 26, 1), ("az.obj.scaffold", 1, 12, 24, 4),
        ("az.obj.torch", 4, 4, 24, 1), ("az.obj.signpost", 1, 18, 24, 1)]),
    "Bael'dun Digsite": (26, [
        ("az.obj.dig_tent", 3, 4, 22, 4), ("az.obj.scaffold", 2, 8, 26, 4), ("az.obj.crate@0", 4, 6, 24, 1),
        ("az.obj.barrel@1", 2, 6, 24, 1), ("az.obj.ore_cart", 1, 10, 24, 3), ("az.obj.torch", 3, 4, 22, 1)]),
    "Palemane Rock": (26, [
        ("az.obj.rock_arch", 1, 0, 4, 6), ("az.obj.bonfire", 2, 6, 16, 2), ("az.obj.kodo_bones", 1, 10, 20, 4)]),
    "Kodo Rock": (16, [("az.obj.kodo_bones", 2, 0, 10, 4)]),
    "Red Rocks": (22, [("az.obj.stone_circle", 1, 0, 6, 6), ("az.obj.grave_cairn", 5, 6, 20, 1)]),
    "Ravaged Caravan": (14, [("az.obj.wagon", 2, 0, 8, 5), ("az.obj.crate@0", 3, 3, 10, 1),
                              ("az.obj.barrel@1", 2, 3, 10, 1)]),
    "Great Gate": (8, [("az.obj.great_gate", 1, 0, 1, 8)]),
    "Stonetalon Pass (Mulgore)": (8, [("az.obj.stonetalon_pass", 1, 0, 1, 6)]),
    "Thunderhorn Water Well": (8, [("az.obj.well", 1, 0, 1, 2), ("az.obj.barrel@0", 1, 3, 6, 1)]),
    "Wildmane Water Well": (8, [("az.obj.well", 1, 0, 1, 2), ("az.obj.barrel@1", 1, 3, 6, 1)]),
    "Winterhoof Water Well": (8, [("az.obj.well", 1, 0, 1, 2), ("az.obj.crate@0", 1, 3, 6, 1)]),
}

# Thunder Bluff rises: (name, x%, y% on Thunder Bluff's own map, platform radius in tiles)
RISES = (("High Rise", 46.5, 50.0, 46), ("Spirit Rise", 25.7, 21.0, 30), ("Elder Rise", 76.8, 29.0, 32),
         ("Hunter Rise", 57.0, 84.6, 32))
PLAZA_RADIUS = 9  # tiles around a rise's centre paved with the painted inlay
RISE_BUILDINGS = {
    "High Rise": [("az.tb.lodge@1", 0, -6, 12), ("az.tb.totem_tall", -16, 4, 4), ("az.tb.totem_tall", 18, 6, 4),
                  ("az.tb.tent_row@0", -24, -14, 10), ("az.tb.tent_row@1", 22, -16, 10), ("az.tb.lift", 0, 24, 6),
                  ("az.obj.banner", -8, 14, 2), ("az.obj.banner", 8, 14, 2), ("az.obj.bonfire", 0, 14, 2),
                  ("az.tb.brazier", -8, 0, 2), ("az.tb.brazier", 8, 0, 2), ("az.tb.brazier", -30, 6, 2),
                  ("az.tb.brazier", 30, 8, 2), ("az.tb.drum", -4, 6, 2), ("az.tb.drum", 5, 7, 2),
                  ("az.tb.hanging_hides", -30, -4, 4), ("az.tb.hanging_hides", 28, -2, 4),
                  ("az.tb.pot", -12, 10, 1), ("az.tb.pot", 13, 11, 1), ("az.tb.banner_pole", -18, -10, 2),
                  ("az.tb.banner_pole", 18, -12, 2), ("az.tb.prayer_flags", 0, 30, 4), ("az.tb.stairs", -38, 10, 1)],
    "Spirit Rise": [("az.tb.spirit_pool", 0, 2, 7), ("az.tb.totem_tall", -10, -6, 4), ("az.tb.totem_tall", 12, -4, 4),
                    ("az.obj.bonfire", 0, 14, 2), ("az.tb.brazier", -8, 10, 2), ("az.tb.brazier", 9, 10, 2),
                    ("az.tb.prayer_flags", -4, -14, 4), ("az.tb.pot", 6, -8, 1), ("az.obj.stone_circle", 0, -16, 6)],
    "Elder Rise": [("az.tb.lodge@0", 0, -4, 12), ("az.tb.totem_tall", -14, 6, 4), ("az.obj.banner", 10, 10, 2),
                   ("az.obj.bonfire", -4, 12, 2), ("az.tb.brazier", -8, 8, 2), ("az.tb.brazier", 8, 8, 2),
                   ("az.tb.drum", 0, 10, 2), ("az.tb.hanging_hides", 16, -2, 4), ("az.tb.banner_pole", -16, -6, 2),
                   ("az.tb.prayer_flags", 0, 20, 4), ("az.tb.pot", 12, 12, 1)],
    "Hunter Rise": [("az.tb.warrior_hall", 0, -4, 12), ("az.tb.totem_tall", 14, 6, 4),
                    ("az.tb.tent_row@1", -16, 8, 10), ("az.obj.training_dummy", 6, 14, 2),
                    ("az.obj.training_dummy", -4, 16, 2), ("az.tb.brazier", -8, 6, 2), ("az.tb.brazier", 10, 4, 2),
                    ("az.tb.hanging_hides", 20, 10, 4), ("az.tb.banner_pole", -20, 0, 2), ("az.obj.training_dummy", 0, 18, 2),
                    ("az.tb.drum", 4, 8, 2), ("az.tb.pot", -10, 14, 1)],
}


# Street life of a rise, per 46 tiles of radius (scaled down for smaller rises): sprite, count, min/max radius
# as a share of the platform radius, footprint in tiles.
STREET: list[tuple[str, int, float, float, int]] = [
    ("az.obj.hut_large", 10, 0.30, 0.86, 6), ("az.obj.hut_small", 26, 0.22, 0.90, 4), ("az.obj.tent", 18, 0.25, 0.90, 3),
    ("az.tb.tent_row", 6, 0.35, 0.85, 10), ("az.tb.totem_tall", 6, 0.20, 0.85, 4), ("az.obj.totem_pole", 6, 0.20, 0.90, 3),
    ("az.tb.brazier", 14, 0.10, 0.92, 2), ("az.obj.torch", 34, 0.10, 0.95, 1), ("az.obj.bonfire", 5, 0.15, 0.80, 2),
    ("az.tb.pot", 26, 0.10, 0.95, 1), ("az.obj.barrel", 16, 0.10, 0.95, 1), ("az.obj.crate", 12, 0.10, 0.95, 1),
    ("az.obj.drying_rack", 9, 0.25, 0.90, 2), ("az.obj.hide_stretcher", 7, 0.25, 0.90, 2),
    ("az.tb.hanging_hides", 12, 0.20, 0.92, 3), ("az.tb.drum", 8, 0.10, 0.85, 2), ("az.obj.banner", 10, 0.15, 0.95, 1),
    ("az.tb.banner_pole", 8, 0.20, 0.95, 2), ("az.tb.prayer_flags", 8, 0.20, 0.90, 4), ("az.obj.signpost", 4, 0.15, 0.80, 1),
    ("az.obj.well", 3, 0.25, 0.75, 2), ("az.obj.anvil", 2, 0.30, 0.80, 1), ("az.obj.forge", 2, 0.30, 0.80, 2),
    ("az.obj.kodo_saddle_rack", 3, 0.30, 0.85, 2), ("az.obj.haystack", 4, 0.30, 0.85, 2), ("az.obj.cooking_pot", 6, 0.15, 0.80, 1),
    ("az.obj.wagon", 2, 0.35, 0.85, 3),
]


def _street(plat: Platform) -> Recipe:
    k = plat.radius / 46
    return [(sprite, max(1, round(count * k * k)), max(2, int(lo * plat.radius)), int(hi * plat.radius), size)
            for sprite, count, lo, hi, size in STREET]


def _free(world: "ZoneWorld", p: Pos) -> bool:
    return world.terrain.tile(*p) not in (Terrain.WATER, Terrain.SHALLOWS, Terrain.VOID, Terrain.MOUNTAIN,
                                          Terrain.CLIFF, Terrain.BOULDER)


def _scatter(world: "ZoneWorld", rng: random.Random, center: Pos, radius: int, recipe: Recipe,
             taken: list[Structure]) -> list[Structure]:
    out: list[Structure] = []
    for sprite, count, rmin, rmax, size in recipe:
        for _ in range(count):
            for _try in range(40):
                a, r = rng.uniform(0, 2 * math.pi), rng.uniform(rmin, max(rmin, min(rmax, radius)))
                p = (int(center[0] + math.cos(a) * r), int(center[1] + math.sin(a) * r * 0.75))
                if not _free(world, p):
                    continue
                if any(max(abs(p[0] - s.pos[0]), abs(p[1] - s.pos[1])) < (size + s.size) // 2 + 1
                       for s in taken + out):
                    continue
                out.append(Structure(sprite, p, size))
                break
    return out


def platforms(world: "ZoneWorld") -> list[Platform]:
    return [Platform(name, world.geo.sub_to_tile("Thunder Bluff", x, y), r) for name, x, y, r in RISES]


def build_structures(world: "ZoneWorld") -> list[Structure]:
    """Every structure of the zone, deterministic for the world's seed."""
    rng = random.Random(world.seed * 97 + 5)
    out: list[Structure] = []
    for p in world.placements:
        if p.kind not in ("subzone", "settlement", "gate") or p.title not in RECIPES:
            continue
        radius, recipe = RECIPES[p.title]
        center = world.nearest_passable(p.pos, 30) or p.pos
        out += _scatter(world, random.Random(rng.random()), center, radius, recipe, out)
    bridge = bridge_tiles(world)
    for plat in platforms(world):
        for sprite, dx, dy, size in RISE_BUILDINGS.get(plat.name, []):
            out.append(Structure(sprite, (plat.center[0] + dx, plat.center[1] + dy), size))
        rng_plat = random.Random(rng.random())
        for s in _scatter(world, rng_plat, plat.center, plat.radius, _street(plat), out):
            if not any((s.pos[0] + dx, s.pos[1] + dy) in bridge for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                out.append(s)
    return out


def bridges(world: "ZoneWorld") -> list[tuple[Pos, Pos]]:
    """Rope bridges from the High Rise to the other rises (as centre-to-centre lines)."""
    plats = {p.name: p for p in platforms(world)}
    hub = plats["High Rise"]
    return [(hub.center, plats[n].center) for n in ("Spirit Rise", "Elder Rise", "Hunter Rise")]


def bridge_tiles(world: "ZoneWorld") -> set[Pos]:
    """Tiles of the rope bridges (three wide), from each rise's edge to the High Rise."""
    out: set[Pos] = set()
    for (x0, y0), (x1, y1) in bridges(world):
        steps = max(abs(x1 - x0), abs(y1 - y0))
        for k in range(steps + 1):
            x, y = round(x0 + (x1 - x0) * k / steps), round(y0 + (y1 - y0) * k / steps)
            out.update((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    return out


def on_platform(world: "ZoneWorld", p: Pos, plats: list[Platform] | None = None) -> Platform | None:
    for plat in plats or platforms(world):
        d = math.hypot((p[0] - plat.center[0]) / 1.0, (p[1] - plat.center[1]) / 0.75)
        if d <= plat.radius:
            return plat
    return None
