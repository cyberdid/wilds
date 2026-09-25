"""Procedural generation of the city: several independent districts (stage 3)
connected only by the `travel` action - each is its own small street-grid
block, generated the same way "The Sprawl" was in stage 1."""

from __future__ import annotations

import random
from collections import deque

from ..world import Pos
from .hero import CyberHero
from .legacy import Legacy
from .npc import spawn_npc
from .race import Race, random_race
from .ship import Ship
from .tiles import CTile
from .world import CityLevel, CityWorld

WIDTH, HEIGHT = 46, 24
LANDMARKS = [
    ("fixer", "fixer", CTile.FIXER),
    ("vendor", "vendor", CTile.SHOP),
    ("doc", "doc", CTile.SHOP),
    ("bar", "civilian", CTile.BAR),
    ("checkpoint", "civilian", CTile.CHECKPOINT),
    ("ganger", "ganger", CTile.ALLEY),
]
# id, display name, home district for a hero/legacy without a district preference
DISTRICTS = [
    ("sprawl", "Насип"),
    ("docks", "Доки"),
    ("corp_row", "Корпоративний ряд"),
]
HOME_DISTRICT = DISTRICTS[0][0]

# stage: district modifiers - light per-district flavor on the same mechanics,
# so the 3 districts stop being reskins of each other. Docks: quieter and
# cheaper to lie low in, but a slog to cross on foot. Corp Row: heavily
# surveilled (heat spikes AND clears fast - a hot minute, not a hot life)
# and taxes every purchase. Sprawl (home turf) stays the baseline.
DISTRICT_MODIFIERS: dict[str, dict] = {
    "sprawl": {},
    "docks": {"heat_gain_mult": 0.7, "heat_decay_mult": 0.8, "move_cost": 2},
    "corp_row": {"heat_gain_mult": 1.4, "heat_decay_mult": 1.3, "price_mult": 1.25},
}

# stage 4: places reached by `launch` (the ship), not `travel` (in-city transit) -
# smaller, sparser, and each with its own flavour of NPC
OFFWORLD_SIZE = (26, 16)
OFFWORLD = [
    ("orbital_station", "Станція «Кассандра»", [("trader", "vendor", CTile.SHOP), ("smuggler", "fixer", CTile.FIXER)]),
    ("outpost", "Форпост «Вертиго»", [("scav", "ganger", CTile.ALLEY), ("medic", "doc", CTile.SHOP)]),
]


def generate(seed: int, legacy: Legacy | None = None) -> CityWorld:
    rng = random.Random(seed)
    levels: dict[str, CityLevel] = {}
    for district_id, name in DISTRICTS:
        levels[district_id] = _district(district_id, name, WIDTH, HEIGHT, LANDMARKS, seed, rng.randrange(1 << 30))
    for place_id, name, landmarks in OFFWORLD:
        w, h = OFFWORLD_SIZE
        levels[place_id] = _district(place_id, name, w, h, landmarks, seed, rng.randrange(1 << 30))

    hero = _make_hero(levels[HOME_DISTRICT].arrival, legacy, rng)
    world = CityWorld(seed=seed, levels=levels, hero=hero, rng=rng, ship=Ship())
    hero.observe(world)
    intro = "Шатл корпорації сів у Насипу. Тепер це твій район - і твій борг." if legacy is None else (
        f"{legacy.name} прокидається в Насипу, з боргом перед корпорацією за 'порятунок' з Тау-7.")
    world.log(intro, "danger" if legacy is None else "event")
    return world


def _district(district_id: str, name: str, width: int, height: int, landmarks: list, seed: int,
              salt: int) -> CityLevel:
    for attempt in range(50):
        rng = random.Random(seed * 104729 + salt + attempt)
        tiles = _blocks(rng, width, height)
        level = CityLevel(district_id, name, width, height, tiles)
        spawn_pos = _reachable_center(level, rng)
        if spawn_pos is None:
            continue
        landmark_spots = _place_landmarks(level, rng, len(landmarks))
        if landmark_spots is None:
            continue
        break
    else:  # pragma: no cover - statistically unreachable
        raise RuntimeError(f"could not generate a playable location '{district_id}' for seed {seed}")

    level.arrival = spawn_pos
    for (kind, role, ctile), pos in zip(landmarks, landmark_spots):
        level.set_tile(pos, ctile)
        level.npcs.append(spawn_npc(f"{kind}_{district_id}", role, pos, rng))
    return level


def _make_hero(pos: Pos, legacy: Legacy | None, rng: random.Random) -> CyberHero:
    if legacy is None:
        return CyberHero(pos=pos, level_id=HOME_DISTRICT, race=random_race(rng))
    race = Race[legacy.race] if legacy.race else random_race(rng)
    hero = CyberHero(pos=pos, level_id=HOME_DISTRICT, name=legacy.name, race=race,
                     nuyen=legacy.starting_nuyen, traits=list(legacy.traits))
    hero.sinless = race.roll_sinless(rng)
    if legacy.summary:
        hero.diary.append((0, legacy.summary))
    return hero


def _blocks(rng: random.Random, width: int = WIDTH, height: int = HEIGHT) -> list[list[CTile]]:
    """A street grid: sidewalks/roads between rectangular building blocks."""
    tiles = [[CTile.WALL for _ in range(width)] for _ in range(height)]
    for y in range(0, height):
        if y % 5 in (0, 1):
            for x in range(width):
                tiles[y][x] = CTile.ROAD if y % 5 == 0 else CTile.SIDEWALK
    for x in range(0, width):
        if x % 8 in (0, 1):
            for y in range(height):
                if tiles[y][x] is CTile.WALL:
                    tiles[y][x] = CTile.SIDEWALK
    for y in range(height):
        for x in range(width):
            if tiles[y][x] is CTile.SIDEWALK and rng.random() < 0.03:
                tiles[y][x] = rng.choice([CTile.TRASH, CTile.NEON])
    return tiles


def _reachable_center(level: CityLevel, rng: random.Random) -> Pos | None:
    region = _largest_region(level)
    if len(region) < 0.3 * level.width * level.height:
        return None
    candidates = [p for p in region if 5 <= p[0] < level.width - 5 and 5 <= p[1] < level.height - 5]
    return rng.choice(sorted(candidates)) if candidates else None


def _largest_region(level: CityLevel) -> set[Pos]:
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


def _place_landmarks(level: CityLevel, rng: random.Random, count: int) -> list[Pos] | None:
    region = _largest_region(level)
    candidates = sorted(p for p in region if level.tile(p) in (CTile.SIDEWALK, CTile.ROAD)
                        and 3 <= p[0] < level.width - 3 and 3 <= p[1] < level.height - 3)
    rng.shuffle(candidates)
    chosen: list[Pos] = []
    for p in candidates:
        if all(max(abs(p[0] - q[0]), abs(p[1] - q[1])) >= 4 for q in chosen):
            chosen.append(p)
        if len(chosen) == count:
            return chosen
    return None
