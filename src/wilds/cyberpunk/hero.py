"""The cyberpunk-chapter hero: a runner working off a debt to the corp that
"rescued" them, moving between districts of a nameless megacity."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..world import Pos
from .race import Race
from .tiles import CTile

if TYPE_CHECKING:
    from .world import CityWorld

MAX_ESSENCE = 10.0


@dataclass
class Place:
    id: str
    kind: str  # npc | landmark
    level_id: str
    pos: Pos
    label: str


@dataclass
class CyberHero:
    pos: Pos
    level_id: str = "sprawl"
    name: str = "Раннер"
    race: Race = Race.HUMAN
    sinless: bool = False
    hp: float = 100.0
    essence: float = MAX_ESSENCE
    nuyen: int = 200
    debt: int = 5000
    inventory: Counter[str] = field(default_factory=Counter)
    reputation: dict[str, float] = field(default_factory=dict)  # faction id -> -1..1 (stage 5)
    traits: list[str] = field(default_factory=list)
    goal: str = ""
    diary: list[tuple[int, str]] = field(default_factory=list)
    memory: dict[str, dict[Pos, CTile]] = field(default_factory=dict)  # level_id -> known tiles
    visible: set[Pos] = field(default_factory=set)  # current level only
    places: dict[str, Place] = field(default_factory=dict)  # global, across all districts
    alive: bool = True
    free: bool = False  # debt fully paid off - the chapter's "win" state
    cause_of_death: str = ""
    contracts_done: int = 0
    evicted: bool = False  # stage: upkeep - missed rent, the shortfall was added to debt

    @property
    def essence_state(self) -> str:
        if self.essence >= 8:
            return "practically unaugmented"
        if self.essence >= 5:
            return "moderately augmented"
        if self.essence >= 2.5:
            return "heavily augmented"
        return "barely holding together, essence critically low"

    def take_damage(self, amount: float, source: str) -> None:
        if not self.alive or amount <= 0:
            return
        self.hp = max(0.0, self.hp - amount)
        if self.hp <= 0:
            self.alive = False
            self.cause_of_death = source

    def sight_radius(self) -> int:
        return 9

    def known(self, level_id: str | None = None) -> dict[Pos, CTile]:
        return self.memory.setdefault(level_id or self.level_id, {})

    def observe(self, world: "CityWorld") -> list[Place]:
        level = world.level
        known = self.known(level.id)
        self.visible = level.visible_from(self.pos, self.sight_radius())
        new: list[Place] = []
        for p in self.visible:
            tile = level.tile(p)
            known[p] = tile
            npc = level.npc_at(p)
            if npc is not None:
                if npc.id not in self.places:
                    place = Place(npc.id, "npc", level.id, p, f"{npc.name} ({npc.role})")
                    self.places[npc.id] = place
                    new.append(place)
            elif tile in (CTile.FIXER, CTile.BAR, CTile.SHOP, CTile.CHECKPOINT):
                pid = f"landmark_{level.id}_{p[0]}_{p[1]}"
                if pid not in self.places:
                    place = Place(pid, "landmark", level.id, p, tile.label)
                    self.places[pid] = place
                    new.append(place)
        return new
