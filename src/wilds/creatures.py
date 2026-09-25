"""Alien fauna and hostile machines: kinds, simple behaviour and combat."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import TYPE_CHECKING

from .tiles import Tile
from .world import Level, Pos, chebyshev

if TYPE_CHECKING:
    from .world import World


@dataclass(frozen=True)
class Kind:
    key: str
    name: str  # Ukrainian
    glyph: str
    color: str
    hp: int
    damage: int
    sight: int
    behavior: str  # timid | hunter | territorial
    chase_every: int  # moves once per N ticks while chasing/fleeing
    wander_every: int
    meat: int = 0
    fears_heat: bool = False
    acc: str = ""  # accusative form for log messages

    @property
    def hostile(self) -> bool:
        return self.behavior != "timid"


KINDS: dict[str, Kind] = {
    "hopper": Kind("hopper", "стрибунець", "h", "bright_white", 3, 0, 5, "timid", 2, 3, meat=1, acc="стрибунця"),
    "hound": Kind("hound", "ксенопес", "x", "green_yellow", 14, 4, 7, "hunter", 1, 3, meat=2, fears_heat=True, acc="ксенопса"),
    "brute": Kind("brute", "громило", "B", "dark_orange3", 35, 9, 4, "territorial", 2, 5, meat=4, fears_heat=True, acc="громила"),
    "drone": Kind("drone", "дрон-охоронець", "d", "red", 9, 3, 5, "hunter", 1, 3, acc="дрона-охоронця"),
    "android": Kind("android", "андроїд", "A", "bright_white", 16, 5, 6, "hunter", 2, 4, acc="андроїда"),
}

_ids = count(1)


@dataclass
class Creature:
    kind: Kind
    pos: Pos
    home: Pos
    hp: int = 0
    id: int = field(default_factory=lambda: next(_ids))
    cooldown: int = 0
    extra: bool = False  # spawned at night, despawns in daylight

    def __post_init__(self) -> None:
        if self.hp <= 0:
            self.hp = self.kind.hp

    @property
    def name(self) -> str:
        return self.kind.name

    @property
    def acc(self) -> str:
        return self.kind.acc or self.kind.name


def spawn(kind: str, pos: Pos, extra: bool = False) -> Creature:
    return Creature(KINDS[kind], pos, pos, extra=extra)


def _free(level: Level, world: "World", p: Pos) -> bool:
    hero = world.hero
    if not level.passable(p) or level.creature_at(p):
        return False
    return not (hero.level_id == level.id and hero.pos == p)


def _step(level: Level, world: "World", c: Creature, target: Pos, away: bool = False) -> None:
    best, best_score = None, None
    for q in level.neighbors(c.pos):
        if not _free(level, world, q):
            continue
        if c.kind.fears_heat and level.near_heat(q, 1):
            continue
        d = chebyshev(q, target)
        score = -d if away else d
        if best_score is None or score < best_score:
            best, best_score = q, score
    if best is not None:
        c.pos = best


def _wander(level: Level, world: "World", c: Creature, radius: int = 8) -> None:
    options = [q for q in level.neighbors(c.pos) if _free(level, world, q)
               and chebyshev(q, c.home) <= radius]
    if options:
        c.pos = world.rng.choice(options)


def creature_turn(world: "World", level: Level, c: Creature) -> None:
    if c.hp <= 0:
        return
    hero = world.hero
    c.cooldown = max(0, c.cooldown - 1)
    hero_here = hero.alive and hero.level_id == level.id
    dist = chebyshev(c.pos, hero.pos) if hero_here else 999
    sight = c.kind.sight
    if not level.dark and world.is_night and c.kind.behavior == "hunter":
        sight += 3
    if hero_here and hero.sleeping and level.tile(hero.pos) in (Tile.DOME, Tile.POD):
        sight = max(1, sight // 2)

    k = c.kind
    if k.behavior == "timid":
        if dist <= sight and world.tick % k.chase_every == 0:
            _step(level, world, c, hero.pos, away=True)
        elif world.tick % k.wander_every == 0:
            _wander(level, world, c)
        return

    engaged = dist <= sight
    if k.behavior == "territorial":
        engaged = engaged and chebyshev(hero.pos, c.home) <= 7
    scared = k.fears_heat and hero_here and level.near_heat(hero.pos, 2)

    if engaged and not scared:
        if dist <= 1:
            if c.cooldown == 0:
                attack_hero(world, c)
                c.cooldown = 2
        elif world.tick % k.chase_every == 0:
            _step(level, world, c, hero.pos)
    elif engaged and scared and dist <= 3:
        _step(level, world, c, hero.pos, away=True)
    elif world.tick % k.wander_every == 0:
        if chebyshev(c.pos, c.home) > 8:
            _step(level, world, c, c.home)
        else:
            _wander(level, world, c)


def attack_hero(world: "World", c: Creature) -> None:
    hero = world.hero
    dmg = max(1, c.kind.damage + world.rng.randint(-1, 1))
    was_sleeping = hero.sleeping
    hero.take_damage(dmg, f"{c.name}")
    suffix = " (розбудив!)" if was_sleeping else ""
    world.log(f"{c.name.capitalize()} атакує: -{dmg} HP{suffix}", "danger")


def hero_attack(world: "World", c: Creature) -> bool:
    """Hero strikes creature; returns True if it died."""
    hero = world.hero
    dmg = max(1, hero.attack_power + world.rng.randint(-1, 1))
    c.hp -= dmg
    if c.hp > 0:
        world.log(f"Б'ю {c.acc} ({hero.weapon_name}): -{dmg}, лишилось {c.hp}", "info")
        return False
    level = world.levels[hero.level_id]
    level.creatures = [x for x in level.creatures if x is not c]
    hero.kills[c.kind.key] += 1
    if c.kind.meat:
        hero.inventory["raw_meat"] += c.kind.meat
        world.log(f"Вбив {c.acc}! +{c.kind.meat} сирого ксеном'яса", "good")
    else:
        world.log(f"Знищив {c.acc}", "good")
    return True
