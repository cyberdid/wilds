"""The hero - a crash survivor: needs, inventory and memory of what they have seen."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .tiles import Tile
from .world import ITEMS, Level, Pos, chebyshev

if TYPE_CHECKING:
    from .world import World

NEEDS = ("satiety", "hydration", "warmth", "energy")
NEED_NAMES = {
    "hp": "здоров'я",
    "satiety": "ситість",
    "hydration": "вода",
    "warmth": "тепло",
    "energy": "енергія",
}
FIST_ATTACK = 2
FLARE_TICKS = 240


@dataclass
class Place:
    id: str
    kind: str  # water | spores | rocks | wreck | exit | camp | dome | pod | debris | crash_site
    level_id: str
    pos: Pos
    label: str


# minimum spacing between two remembered places of the same kind
_PLACE_SPACING = {"water": 10, "spores": 6, "rocks": 10}


@dataclass
class Hero:
    pos: Pos
    level_id: str = "surface"
    name: str = "Вцілілий"
    hp: float = 100.0
    satiety: float = 85.0
    hydration: float = 85.0
    warmth: float = 90.0
    energy: float = 90.0
    inventory: Counter[str] = field(default_factory=Counter)
    flare_ticks: int = 0
    memory: dict[str, dict[Pos, Tile]] = field(default_factory=dict)
    seen_items: dict[str, dict[Pos, list[str]]] = field(default_factory=dict)
    visible: set[Pos] = field(default_factory=set)
    places: dict[str, Place] = field(default_factory=dict)
    traits: list[str] = field(default_factory=list)  # formed by the nightly diary
    goal: str = ""  # the priority set in last night's diary
    diary: list[tuple[int, str]] = field(default_factory=list)  # (sol, entry)
    rescued: bool = False
    sleeping: bool = False
    alive: bool = True
    cause_of_death: str = ""
    kills: Counter[str] = field(default_factory=Counter)
    hurt_this_tick: float = 0.0
    _place_counts: Counter[str] = field(default_factory=Counter)

    # --- derived --------------------------------------------------------
    @property
    def attack_power(self) -> int:
        weapons = [ITEMS[i].attack for i in self.inventory if self.inventory[i] > 0]
        return max([FIST_ATTACK, *weapons])

    @property
    def weapon_name(self) -> str:
        best = max(
            (i for i in self.inventory if self.inventory[i] > 0 and ITEMS[i].attack),
            key=lambda i: ITEMS[i].attack,
            default=None,
        )
        return ITEMS[best].name if best else "кулаки"

    @property
    def has_light(self) -> bool:
        return self.inventory["headlamp"] > 0 or self.flare_ticks > 0 or self.inventory["flare"] > 0

    def sight_radius(self, world: "World") -> int:
        level = world.levels[self.level_id]
        near_heat = level.near_heat(self.pos, 3)
        if level.dark:
            return 5 if self.has_light else (3 if near_heat else 1)
        if world.director and world.director.storm_active:
            return 2
        if world.is_night:
            if self.has_light or near_heat:
                return 6
            return 3
        return 9

    def need(self, name: str) -> float:
        return float(getattr(self, name))

    def change(self, name: str, delta: float) -> None:
        value = max(0.0, min(100.0, getattr(self, name) + delta))
        setattr(self, name, value)

    # --- damage -----------------------------------------------------------
    def take_damage(self, amount: float, source: str) -> None:
        if not self.alive or amount <= 0:
            return
        self.hp = max(0.0, self.hp - amount)
        self.hurt_this_tick += amount
        self.sleeping = False
        if self.hp <= 0:
            self.alive = False
            self.cause_of_death = source

    # --- memory -----------------------------------------------------------
    def known(self, level_id: str) -> dict[Pos, Tile]:
        return self.memory.setdefault(level_id, {})

    def add_place(self, kind: str, level_id: str, pos: Pos, label: str) -> Place:
        for p in self.places.values():
            if p.kind == kind and p.level_id == level_id and p.pos == pos:
                return p
        self._place_counts[kind] += 1
        place = Place(f"{kind}_{self._place_counts[kind]}", kind, level_id, pos, label)
        self.places[place.id] = place
        return place

    def remove_place(self, kind: str, level_id: str, pos: Pos) -> None:
        for pid, p in list(self.places.items()):
            if p.kind == kind and p.level_id == level_id and p.pos == pos:
                del self.places[pid]

    def observe(self, world: "World") -> list[Place]:
        """Update what the hero sees; returns newly discovered places."""
        level = world.levels[self.level_id]
        self.visible = level.visible_from(self.pos, self.sight_radius(world))
        mem = self.known(level.id)
        items_mem = self.seen_items.setdefault(level.id, {})
        new: list[Place] = []
        for p in self.visible:
            tile = level.tile(p)
            mem[p] = tile
            if level.items.get(p):
                items_mem[p] = list(level.items[p])
            else:
                items_mem.pop(p, None)
            place = self._discover(level, p, tile)
            if place:
                new.append(place)
        return new

    def _discover(self, level: Level, p: Pos, tile: Tile) -> Place | None:
        kind = {
            Tile.WATER: "water",
            Tile.SPORE_BUSH: "spores",
            Tile.ROCK: "rocks",
            Tile.WRECK: "wreck",
            Tile.HATCH: "exit",
        }.get(tile)
        if kind is None:
            return None
        spacing = _PLACE_SPACING.get(kind, 0)
        for other in self.places.values():
            if other.kind != kind or other.level_id != level.id:
                continue
            if other.pos == p or (spacing and chebyshev(other.pos, p) <= spacing):
                return None
        label = {
            "water": "водойма",
            "spores": "спорові кущі",
            "rocks": "рудні скелі",
            "wreck": "вхід в уламки",
            "exit": "вихідний шлюз",
        }[kind]
        if kind == "wreck" and p in level.entrances:
            label = f"вхід в уламки: {level.entrances[p]}"
        return self.add_place(kind, level.id, p, label)
