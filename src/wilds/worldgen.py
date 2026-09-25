"""Procedural generation of the alien surface and the derelict wrecks on it."""

from __future__ import annotations

import random
from collections import deque

from .creatures import spawn
from .director import Director
from .hero import Hero
from .pod import Pod
from .noise import ValueNoise
from .tiles import Tile
from .world import Level, Pos, World, chebyshev

SURFACE_W, SURFACE_H = 80, 40
WRECK_W, WRECK_H = 44, 22
WRECK_NAMES = ["Уламки «Геліоса»", "Станція «Кеплер-9»", "Вулик предтеч"]


def generate(seed: int) -> World:
    """Build a world; retries internal layouts until the map is playable."""
    for attempt in range(100):
        rng = random.Random(seed * 7919 + attempt)
        surface = _surface_tiles(rng)
        layout = _plan_surface(surface, rng)
        if layout is not None:
            break
    else:  # pragma: no cover - statistically unreachable
        raise RuntimeError(f"could not generate a playable world for seed {seed}")

    spawn_pos, wreck_positions, region = layout
    levels = {"surface": surface}
    # nearest wreck is the easiest
    wreck_positions.sort(key=lambda p: chebyshev(p, spawn_pos))
    for i, pos in enumerate(wreck_positions):
        wreck = _wreck_level(f"wreck_{i + 1}", WRECK_NAMES[i], i + 1, rng)
        wreck.parent = ("surface", pos)
        surface.set_tile(pos, Tile.WRECK)
        surface.entrances[pos] = wreck.name
        levels[wreck.id] = wreck

    _populate_surface(surface, region, spawn_pos, rng)

    pod_pos = next(q for q in surface.neighbors(spawn_pos) if surface.tile(q) is Tile.MOSS
                   and not surface.creature_at(q))
    surface.set_tile(pod_pos, Tile.POD)

    hero = Hero(pos=spawn_pos)
    world = World(seed=seed, levels=levels, hero=hero, rng=rng)
    world.pod = Pod(pod_pos)
    world.director = Director()
    hero.add_place("pod", "surface", pod_pos, "рятувальна капсула (база)")
    hero.observe(world)
    world.log("Рятувальна капсула розбилася на Тау-7. Зв'язку з кораблем немає.", "danger")
    world.log("Аварійний маяк пошкоджено: потрібні 3 сплави обшивки і плата предтеч.", "event")
    return world


# --- surface -----------------------------------------------------------------


def _surface_tiles(rng: random.Random) -> Level:
    elevation = ValueNoise(rng.randrange(1 << 30))
    moisture = ValueNoise(rng.randrange(1 << 30))
    tiles: list[list[Tile]] = []
    for y in range(SURFACE_H):
        row = []
        for x in range(SURFACE_W):
            e = elevation.fractal(x / 14, y / 14)
            m = moisture.fractal(x / 9 + 50, y / 9 + 50)
            if e < 0.36:
                t = Tile.WATER
            elif e < 0.40:
                t = Tile.DUST
            elif e > 0.66:
                t = Tile.ROCK
            elif m > 0.52 and rng.random() < 0.8:
                t = Tile.FLORA
            elif m > 0.42 and rng.random() < 0.035:
                t = Tile.SPORE_BUSH
            else:
                t = Tile.MOSS
            row.append(t)
        tiles.append(row)
    return Level("surface", "Поверхня Тау-7", SURFACE_W, SURFACE_H, tiles)


def largest_region(level: Level) -> set[Pos]:
    seen: set[Pos] = set()
    best: set[Pos] = set()
    for start in level.positions():
        if start in seen or not level.passable(start):
            continue
        region = {start}
        queue = deque([start])
        seen.add(start)
        while queue:
            p = queue.popleft()
            for q in level.neighbors(p):
                if q not in seen and level.passable(q):
                    seen.add(q)
                    region.add(q)
                    queue.append(q)
        if len(region) > len(best):
            best = region
    return best


def _touches(level: Level, p: Pos, tile: Tile) -> bool:
    return any(level.tile(q) is tile for q in level.neighbors(p))


def _plan_surface(level: Level, rng: random.Random) -> tuple[Pos, list[Pos], set[Pos]] | None:
    region = largest_region(level)
    if len(region) < 0.45 * level.width * level.height:
        return None
    shore = [p for p in region if _touches(level, p, Tile.WATER)]
    cliffs = [p for p in region if _touches(level, p, Tile.ROCK)]
    forest = [p for p in region if level.tile(p) is Tile.FLORA]
    if len(shore) < 10 or len(cliffs) < 5 or len(forest) < 60:
        return None

    candidates = [
        p for p in region
        if level.tile(p) is Tile.MOSS
        and 3 <= p[0] < level.width - 3 and 3 <= p[1] < level.height - 3
        and min(chebyshev(p, s) for s in shore) <= 12
        and sum(1 for f in forest if chebyshev(p, f) <= 10) >= 8
        and sum(1 for q in level.neighbors(p) if level.tile(q) is Tile.MOSS) >= 2  # room for the pod
    ]
    if not candidates:
        return None
    spawn_pos = rng.choice(sorted(candidates))

    wreck_spots = [
        p for p in sorted(region)
        if level.tile(p) in (Tile.MOSS, Tile.DUST, Tile.FLORA)
        and chebyshev(p, spawn_pos) >= 14
        and 1 <= p[0] < level.width - 1 and 1 <= p[1] < level.height - 1
    ]
    rng.shuffle(wreck_spots)
    wrecks: list[Pos] = []
    for p in wreck_spots:
        if all(chebyshev(p, r) >= 14 for r in wrecks):
            wrecks.append(p)
        if len(wrecks) == len(WRECK_NAMES):
            return spawn_pos, wrecks, region
    return None


def _populate_surface(level: Level, region: set[Pos], spawn_pos: Pos, rng: random.Random) -> None:
    cells = sorted(region)

    def pick(tile_types: tuple[Tile, ...], min_dist: int) -> Pos | None:
        options = [p for p in cells if level.tile(p) in tile_types
                   and chebyshev(p, spawn_pos) >= min_dist and not level.creature_at(p)]
        return rng.choice(options) if options else None

    plan = [("hopper", (Tile.MOSS,), 4, 9), ("hound", (Tile.FLORA, Tile.MOSS), 20, 3),
            ("brute", (Tile.FLORA,), 16, 1)]
    for kind, tile_types, min_dist, n in plan:
        for _ in range(n):
            p = pick(tile_types, min_dist)
            if p:
                level.creatures.append(spawn(kind, p))


# --- wrecks -------------------------------------------------------------------


Rect = tuple[int, int, int, int]  # x, y, w, h


def _center(r: Rect) -> Pos:
    return (r[0] + r[2] // 2, r[1] + r[3] // 2)


def _wreck_level(level_id: str, name: str, difficulty: int, rng: random.Random) -> Level:
    tiles = [[Tile.WALL] * WRECK_W for _ in range(WRECK_H)]
    level = Level(level_id, name, WRECK_W, WRECK_H, tiles, dark=True)

    rooms: list[Rect] = []
    for _ in range(200):
        w, h = rng.randint(4, 9), rng.randint(3, 6)
        x, y = rng.randint(1, WRECK_W - w - 2), rng.randint(1, WRECK_H - h - 2)
        if any(x - 1 < rx + rw and rx - 1 < x + w and y - 1 < ry + rh and ry - 1 < y + h
               for rx, ry, rw, rh in rooms):
            continue
        rooms.append((x, y, w, h))
        if len(rooms) >= 7:
            break

    for x, y, w, h in rooms:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                level.set_tile((xx, yy), Tile.FLOOR)
    for a, b in zip(rooms, rooms[1:]):
        (x1, y1), (x2, y2) = _center(a), _center(b)
        corner = (x2, y1) if rng.random() < 0.5 else (x1, y2)
        for (ax, ay), (bx, by) in (((x1, y1), corner), (corner, (x2, y2))):
            for xx in range(min(ax, bx), max(ax, bx) + 1):
                for yy in range(min(ay, by), max(ay, by) + 1):
                    level.set_tile((xx, yy), Tile.FLOOR)

    entry = _center(rooms[0])
    level.set_tile(entry, Tile.HATCH)
    level.exit_pos = entry

    def room_cell(room: Rect) -> Pos:
        for _ in range(50):
            p = (rng.randint(room[0], room[0] + room[2] - 1), rng.randint(room[1], room[1] + room[3] - 1))
            if level.tile(p) is Tile.FLOOR and p not in level.items and not level.creature_at(p):
                return p
        return _center(room)

    far = sorted(rooms[1:], key=lambda r: chebyshev(_center(r), entry))
    loot = ["artifact", "ration", "medkit", "flare", "ration", "alloy", "power_cell"]
    loot += {1: ["plasma_cutter"], 2: ["headlamp", "medkit", "circuit"],
             3: ["ration", "medkit", "artifact", "circuit", "power_cell"]}[difficulty]
    for i, item in enumerate(loot):
        room = far[-1] if item == "artifact" else far[i % len(far)]
        level.items.setdefault(room_cell(room), []).append(item)

    monsters = ["drone"] * (3 - difficulty // 2) + ["android"] * difficulty
    for i, kind in enumerate(monsters):
        room = far[-1] if i == 0 else rng.choice(far)
        level.creatures.append(spawn(kind, room_cell(room)))
    return level
