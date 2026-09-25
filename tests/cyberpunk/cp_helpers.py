"""Test helpers for the cyberpunk chapter. Not named conftest.py: that name
would shadow tests/conftest.py (the Tau-7 one) on a shared sys.path."""

import random

from wilds.cyberpunk.hero import CyberHero
from wilds.cyberpunk.npc import spawn_npc
from wilds.cyberpunk.race import Race
from wilds.cyberpunk.sim import CitySim
from wilds.cyberpunk.tiles import CTile
from wilds.cyberpunk.world import CityLevel, CityWorld

GLYPHS = {
    ".": CTile.SIDEWALK, ",": CTile.ROAD, "#": CTile.WALL, "$": CTile.SHOP,
    "F": CTile.FIXER, "B": CTile.BAR, "=": CTile.CHECKPOINT,
}


def make_level(rows: list[str], level_id: str = "sprawl") -> tuple[CityLevel, dict]:
    marks: dict = {}
    tiles = []
    for y, row in enumerate(rows):
        line = []
        for x, ch in enumerate(row):
            if ch in GLYPHS:
                line.append(GLYPHS[ch])
            else:
                marks.setdefault(ch, []).append((x, y))
                line.append(CTile.SIDEWALK)
        tiles.append(line)
    return CityLevel(level_id, level_id, len(rows[0]), len(rows), tiles), marks


def make_world(rows: list[str], seed: int = 1, npcs: dict[str, str] | None = None,
               level_id: str = "sprawl", extra_levels: dict[str, CityLevel] | None = None) -> CityWorld:
    """npcs maps a mark char to a role, e.g. {'V': 'vendor'}."""
    level, marks = make_level(rows, level_id)
    rng = random.Random(seed)
    for mark, role in (npcs or {}).items():
        for i, pos in enumerate(marks.get(mark, [])):
            level.npcs.append(spawn_npc(f"{role}_{i + 1}", role, pos, rng))
    hero = CyberHero(pos=marks.get("@", [(0, 0)])[0], level_id=level_id, race=Race.HUMAN)
    levels = {level_id: level, **(extra_levels or {})}
    world = CityWorld(seed=seed, levels=levels, hero=hero, rng=rng)
    hero.observe(world)
    return world


def run_until_idle(sim: CitySim, limit: int = 3000) -> None:
    for _ in range(limit):
        if sim.action is None:
            return
        sim.tick()
    raise AssertionError("action never finished")
