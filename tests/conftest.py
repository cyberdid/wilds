import random

import pytest

from wilds.creatures import spawn
from wilds.hero import Hero
from wilds.sim import Simulation
from wilds.tiles import Tile
from wilds.world import Level, World

GLYPHS = {
    ".": Tile.MOSS, "~": Tile.WATER, "^": Tile.ROCK, "T": Tile.FLORA,
    "%": Tile.SPORE_BUSH, "#": Tile.WALL, "_": Tile.FLOOR, "<": Tile.HATCH, "R": Tile.WRECK,
}


def make_level(rows: list[str], level_id: str = "surface", dark: bool = False) -> tuple[Level, dict]:
    """Build a level from ASCII; '@' marks the hero, lowercase letters mark creatures."""
    marks: dict = {}
    tiles = []
    for y, row in enumerate(rows):
        line = []
        for x, ch in enumerate(row):
            if ch in GLYPHS:
                line.append(GLYPHS[ch])
            else:
                marks.setdefault(ch, []).append((x, y))
                line.append(Tile.FLOOR if dark else Tile.MOSS)
        tiles.append(line)
    level = Level(level_id, level_id, len(rows[0]), len(rows), tiles, dark=dark)
    return level, marks


CREATURE_MARKS = {"r": "hopper", "w": "hound", "b": "brute", "s": "drone", "z": "android"}


def make_world(rows: list[str], tick: int = 10 * 60, seed: int = 1) -> World:
    level, marks = make_level(rows)
    for mark, kind in CREATURE_MARKS.items():
        for p in marks.get(mark, []):
            level.creatures.append(spawn(kind, p))
    hero = Hero(pos=marks["@"][0])
    world = World(seed=seed, levels={"surface": level}, hero=hero, rng=random.Random(seed), tick=tick)
    hero.observe(world)
    return world


@pytest.fixture
def small_world():
    return make_world([
        "~~~~~~~~~~~~~~~~~~~~",
        "~..................~",
        "~..TTT.........%...~",
        "~..TTT.............~",
        "~.........@........~",
        "~..................~",
        "~^^^...............~",
        "~^^^...............~",
        "~~~~~~~~~~~~~~~~~~~~",
    ])


def run_until_idle(sim: Simulation, limit: int = 2000) -> None:
    for _ in range(limit):
        if sim.action is None:
            return
        sim.tick()
    raise AssertionError("action never finished")
