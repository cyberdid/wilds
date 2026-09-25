"""The city (multiple districts) and world state. Deliberately separate from
wilds.world.Level: a city block has no heaters, wrecks or pod - forcing a
shared base class would buy little and couple two unrelated domains."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterator

from ..world import Event, NEIGHBORS, Pos, TICKS_PER_DAY, line
from .tiles import CTile

if TYPE_CHECKING:
    from .contracts import Contract
    from .hero import CyberHero
    from .npc import NPC
    from .ship import Ship

NIGHT_START = 21
NIGHT_END = 6


@dataclass
class CityLevel:
    id: str
    name: str
    width: int
    height: int
    tiles: list[list[CTile]]
    arrival: Pos = (0, 0)  # where a traveler steps off arriving from elsewhere
    npcs: list["NPC"] = field(default_factory=list)
    heat: float = 0.0  # stage: district heat, 0-100 - how hot this district is for the hero right now

    def in_bounds(self, p: Pos) -> bool:
        return 0 <= p[0] < self.width and 0 <= p[1] < self.height

    def tile(self, p: Pos) -> CTile:
        return self.tiles[p[1]][p[0]]

    def set_tile(self, p: Pos, t: CTile) -> None:
        self.tiles[p[1]][p[0]] = t

    def passable(self, p: Pos) -> bool:
        return self.in_bounds(p) and self.tile(p).passable

    def npc_at(self, p: Pos) -> "NPC | None":
        return next((n for n in self.npcs if n.pos == p), None)

    def neighbors(self, p: Pos) -> Iterator[Pos]:
        for dx, dy in NEIGHBORS:
            q = (p[0] + dx, p[1] + dy)
            if self.in_bounds(q):
                yield q

    def positions(self) -> Iterator[Pos]:
        for y in range(self.height):
            for x in range(self.width):
                yield (x, y)

    def visible_from(self, origin: Pos, radius: int) -> set[Pos]:
        seen = {origin}
        ox, oy = origin
        for y in range(oy - radius, oy + radius + 1):
            for x in range(ox - radius, ox + radius + 1):
                if not self.in_bounds((x, y)):
                    continue
                if (x - ox) ** 2 + (y - oy) ** 2 > radius * radius + radius:
                    continue
                for p in line(origin, (x, y)):
                    seen.add(p)
                    if p != origin and self.tile(p).blocks_sight:
                        break
        return seen


@dataclass
class CityWorld:
    seed: int
    levels: dict[str, CityLevel]
    hero: "CyberHero"
    rng: random.Random
    tick: int = 9 * 60  # day 1, 09:00
    events: list[Event] = field(default_factory=list)
    listeners: list[Callable[[Event], None]] = field(default_factory=list)
    pending_talk: str = ""  # npc id the hero just walked up to, for CitySim to notice
    contract: "Contract | None" = None  # one active contract at a time (stage 2)
    contract_seq: int = 0
    ship: "Ship | None" = None  # None until stage 4 is wired up by worldgen
    delinquent: bool = False  # stage: debt installments - missed a required payment

    @property
    def level(self) -> CityLevel:
        return self.levels[self.hero.level_id]

    @property
    def day(self) -> int:
        return self.tick // TICKS_PER_DAY + 1

    @property
    def hour(self) -> int:
        return (self.tick % TICKS_PER_DAY) // 60

    @property
    def minute(self) -> int:
        return self.tick % 60

    @property
    def is_night(self) -> bool:
        return self.hour >= NIGHT_START or self.hour < NIGHT_END

    def clock(self) -> str:
        return f"День {self.day}, {self.hour:02d}:{self.minute:02d}"

    def log(self, text: str, kind: str = "info") -> None:
        ev = Event(self.tick, text, kind)
        self.events.append(ev)
        if len(self.events) > 500:
            del self.events[:100]
        for fn in self.listeners:
            fn(ev)
