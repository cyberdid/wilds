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
    "Bloodhoof Village": (34, [  # a few big airy tents on the grass, tall totems between them (see reference-notes.md)
        ("az.obj.big_teepee", 1, 0, 4, 8), ("az.obj.hut_large", 3, 12, 26, 12), ("az.obj.inn", 1, 14, 24, 10),
        ("az.obj.hide_longhouse", 1, 12, 24, 10), ("az.obj.tent", 2, 12, 28, 8), ("az.obj.totem_pole", 5, 8, 30, 3),
        ("az.obj.eagle_totem", 3, 10, 28, 4), ("az.obj.stilt_lodge", 1, 22, 33, 8), ("az.obj.bonfire", 2, 3, 14, 2),
        ("az.obj.forge", 1, 18, 28, 4), ("az.obj.anvil", 1, 18, 28, 2), ("az.obj.drying_rack", 2, 10, 30, 3),
        ("az.obj.hide_stretcher", 2, 10, 30, 3), ("az.obj.stable", 1, 26, 40, 6), ("az.obj.kodo_pen", 1, 28, 44, 4),
        ("az.obj.barrel@0", 2, 12, 30, 1), ("az.obj.crate@1", 1, 12, 30, 1), ("az.obj.cooking_pot", 1, 3, 8, 1)]),
    "Camp Narache": (24, [
        ("az.obj.bonfire", 1, 0, 3, 2), ("az.obj.hut_large", 3, 8, 18, 12), ("az.obj.hide_longhouse", 1, 10, 20, 10),
        ("az.obj.tent", 1, 10, 20, 8), ("az.obj.totem_pole", 7, 12, 24, 3), ("az.obj.eagle_totem", 1, 8, 18, 4),
        ("az.obj.windbreak", 3, 16, 24, 4), ("az.obj.training_dummy", 2, 6, 14, 2), ("az.obj.drying_rack", 1, 10, 20, 3),
        ("az.obj.hide_stretcher", 1, 10, 20, 3)]),
    "Camp Sungraze": (10, [
        ("az.obj.bonfire", 1, 0, 1, 2), ("az.obj.tent", 3, 4, 8, 6), ("az.obj.totem_pole", 1, 6, 9, 3),
        ("az.obj.hide_stretcher", 1, 5, 9, 3), ("az.obj.kodo_bones", 1, 9, 10, 4)]),
    "Venture Co. Mine": (26, [
        ("az.obj.mine_entrance", 1, 0, 6, 6), ("az.obj.goblin_shack", 3, 8, 26, 4), ("az.obj.ore_cart", 3, 6, 24, 3),
        ("az.obj.crate@0", 5, 6, 26, 1), ("az.obj.barrel@0", 4, 6, 26, 1), ("az.obj.scaffold", 1, 12, 24, 4),
        ("az.obj.torch", 4, 4, 24, 1), ("az.obj.signpost", 1, 18, 24, 1)]),
    "Bael'dun Digsite": (26, [
        ("az.obj.dig_tent", 3, 4, 22, 4), ("az.obj.scaffold", 2, 8, 26, 4), ("az.obj.crate@0", 4, 6, 24, 1),
        ("az.obj.barrel@1", 2, 6, 24, 1), ("az.obj.ore_cart", 1, 10, 24, 3), ("az.obj.torch", 3, 4, 22, 1)]),
    "Palemane Rock": (26, [
        ("az.obj.cave_mouth", 1, 0, 4, 8), ("az.obj.bonfire", 1, 8, 16, 2)]),
    "Kodo Rock": (16, [("az.obj.standing_stone", 1, 0, 2, 2)]),
    "Red Rocks": (22, [("az.rock.dome", 5, 2, 20, 4), ("az.rock.hoodoo", 4, 4, 20, 3), ("az.tb.pine", 3, 8, 22, 2)]),
    "Ravaged Caravan": (14, [("az.obj.wagon", 2, 0, 8, 5), ("az.obj.crate@0", 3, 3, 10, 1),
                              ("az.obj.barrel@1", 2, 3, 10, 1)]),
    "Great Gate": (8, [("az.obj.great_gate", 1, 0, 0, 8)]),
    "Stonetalon Pass (Mulgore)": (8, [("az.obj.stonetalon_pass", 1, 0, 1, 6)]),
    "Thunderhorn Water Well": (8, [("az.obj.water_well", 1, 0, 1, 4)]),
    "Wildmane Water Well": (8, [("az.obj.water_well", 1, 0, 1, 4)]),
    "Winterhoof Water Well": (8, [("az.obj.water_well", 1, 0, 1, 4)]),
}

# Thunder Bluff rises: (name, x%, y% on Thunder Bluff's own map, platform radius in tiles)
RISES = (("High Rise", 46.5, 50.0, 46), ("Spirit Rise", 25.7, 21.0, 30), ("Elder Rise", 76.8, 29.0, 32),
         ("Hunter Rise", 57.0, 84.6, 32))
PLAZA_RADIUS = 9  # tiles around a rise's centre paved with the painted inlay
RISE_BUILDINGS = {
    "High Rise": [("az.tb.tower_totem", 0, -8, 6), ("az.tb.longhouse@0", -14, 4, 12), ("az.tb.longhouse@1", 14, 6, 12),
                  ("az.tb.longhouse@2", 0, 16, 12), ("az.tb.lift_tower", -34, 16, 4), ("az.tb.lift_tower", 6, -34, 4),
                  ("az.tb.totem_tall", -9, 2, 4), ("az.tb.totem_tall", 9, 2, 4), ("az.obj.bonfire", 0, 4, 2),
                  ("az.tb.brazier", -6, 8, 2), ("az.tb.brazier", 6, 8, 2), ("az.tb.drum", -4, 10, 2),
                  ("az.tb.drum", 5, 10, 2), ("az.tb.banner_pole", -18, -6, 2), ("az.tb.banner_pole", 18, -6, 2)],
    "Spirit Rise": [("az.tb.spirit_pool", 0, 2, 7), ("az.tb.totem_tall", -10, -6, 4), ("az.tb.totem_tall", 12, -4, 4),
                    ("az.obj.bonfire", 0, 14, 2), ("az.tb.brazier", -8, 10, 2), ("az.tb.brazier", 9, 10, 2),
                    ("az.tb.windmill_totem", -14, 4, 2), ("az.tb.windmill_totem", 14, 6, 2), ("az.obj.stone_circle", 0, -14, 6)],
    "Elder Rise": [("az.tb.round_tent", 0, -2, 14), ("az.tb.totem_tall", -16, 6, 4), ("az.tb.totem_tall", 16, 6, 4),
                   ("az.tb.windmill_totem", -12, -8, 2), ("az.tb.windmill_totem", 12, -8, 2),
                   ("az.tb.brazier", -8, 10, 2), ("az.tb.brazier", 8, 10, 2), ("az.tb.drum", 0, 12, 2),
                   ("az.tb.banner_pole", -20, 0, 2), ("az.tb.banner_pole", 20, 0, 2)],
    "Hunter Rise": [("az.tb.warrior_hall", 0, -4, 12), ("az.tb.totem_tall", 14, 6, 4), ("az.tb.totem_tall", -14, 6, 4),
                    ("az.tb.windmill_totem", -18, -4, 2), ("az.tb.windmill_totem", 18, -4, 2),
                    ("az.obj.training_dummy", 6, 14, 2), ("az.obj.training_dummy", -4, 16, 2), ("az.obj.training_dummy", 0, 18, 2),
                    ("az.tb.brazier", -8, 8, 2), ("az.tb.brazier", 10, 8, 2), ("az.tb.drum", 4, 10, 2),
                    ("az.tb.banner_pole", -22, 2, 2), ("az.tb.banner_pole", 22, 2, 2)],
}

# Street life of a rise, per 46 tiles of radius (scaled down for smaller rises): sprite, count, min/max radius
# as a share of the platform radius, footprint in tiles. Tall hide tents, teal-roofed longhouses, wind totems.
STREET: list[tuple[str, int, float, float, int]] = [
    ("az.tb.tent_tall", 46, 0.22, 0.86, 3), ("az.tb.longhouse", 8, 0.30, 0.80, 12), ("az.tb.windmill_totem", 14, 0.20, 0.90, 2),
    ("az.tb.totem_tall", 6, 0.20, 0.85, 4), ("az.obj.totem_pole", 6, 0.20, 0.90, 3),
    ("az.tb.brazier", 10, 0.10, 0.92, 2), ("az.obj.torch", 26, 0.10, 0.95, 1), ("az.obj.bonfire", 4, 0.15, 0.80, 2),
    ("az.tb.pot", 22, 0.10, 0.95, 1), ("az.obj.barrel", 14, 0.10, 0.95, 1), ("az.obj.crate", 10, 0.10, 0.95, 1),
    ("az.obj.drying_rack", 9, 0.25, 0.90, 2), ("az.obj.hide_stretcher", 7, 0.25, 0.90, 2),
    ("az.tb.hanging_hides", 8, 0.20, 0.92, 3), ("az.tb.drum", 6, 0.10, 0.85, 2), ("az.obj.banner", 8, 0.15, 0.95, 1),
    ("az.tb.banner_pole", 8, 0.20, 0.95, 2), ("az.tb.prayer_flags", 6, 0.20, 0.90, 4), ("az.obj.signpost", 4, 0.15, 0.80, 1),
    ("az.obj.anvil", 2, 0.30, 0.80, 1), ("az.obj.forge", 2, 0.30, 0.80, 2),
    ("az.obj.kodo_saddle_rack", 3, 0.30, 0.85, 2), ("az.obj.haystack", 4, 0.30, 0.85, 2),
    ("az.obj.cooking_pot", 6, 0.15, 0.80, 1),
]


STREET_DENSITY = 0.3  # Thunder Bluff is airy tents on grass between pines, not a crowded town


def _street(plat: Platform) -> Recipe:
    k = plat.radius / 46
    return [(sprite, max(1, round(count * k * k * STREET_DENSITY)), max(2, int(lo * plat.radius)), int(hi * plat.radius), size)
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
    rise_radius = {p.center: p.radius for p in platforms(world)}
    for a, b in bridges(world):  # a wooden gatehouse where each bridge meets a rise
        for here, there in ((a, b), (b, a)):
            d = math.hypot(there[0] - here[0], there[1] - here[1]) or 1.0
            k = rise_radius[here] * 0.9 / d
            out.append(Structure("az.tb.gatehouse", (round(here[0] + (there[0] - here[0]) * k),
                                                     round(here[1] + (there[1] - here[1]) * k)), 4))
    for plat in platforms(world):
        for sprite, dx, dy, size in RISE_BUILDINGS.get(plat.name, []):
            out.append(Structure(sprite, (plat.center[0] + dx, plat.center[1] + dy), size))
        rng_plat = random.Random(rng.random())
        for s in _scatter(world, rng_plat, plat.center, plat.radius, _street(plat), out):
            if not any((s.pos[0] + dx, s.pos[1] + dy) in bridge for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                out.append(s)
    out += _gate_wall(world, out)
    return out


GATE_WALL = 12  # tiles of log wall on each side of the Great Gate (the wall runs screen-horizontally)


def gate_line(world: "ZoneWorld") -> tuple[Pos, list[Pos]] | None:
    """The Great Gate's position and the tiles of its wall (both sides, nearest first), stopping at obstacles."""
    place = next((p for p in world.placements if p.title == "Great Gate"), None)
    if place is None:
        return None
    gate = world.nearest_passable(place.pos, 30) or place.pos
    tiles: list[Pos] = []
    for sign in (1, -1):
        for k in range(3, GATE_WALL + 3):  # the gate itself spans about 4 tiles; the wall starts beside it
            p = (gate[0] + sign * k, gate[1] - sign * k)
            if not _free(world, p):
                break
            tiles.append(p)
    return gate, tiles


def _gate_wall(world: "ZoneWorld", built: list[Structure]) -> list[Structure]:
    """A continuous log wall either side of the Great Gate, closed by a tall post at each end."""
    line = gate_line(world)
    if line is None:
        return []
    gate, tiles = line
    out = [Structure("az.obj.log_wall", p, 1) for p in tiles]
    for sign in (1, -1):
        side = [p for p in tiles if (p[0] - gate[0]) * sign > 0]
        if side:
            far = max(side, key=lambda p: abs(p[0] - gate[0]))
            out.append(Structure("az.obj.log_wall_post", (far[0] + sign, far[1] - sign), 1))
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
