"""World model: levels, items, time and the event log.

Nothing here knows about the LLM or the UI.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterator

from .tiles import Tile

if TYPE_CHECKING:
    from .companion import Companion
    from .creatures import Creature
    from .director import Director
    from .hero import Hero
    from .pod import Pod

Pos = tuple[int, int]

TICKS_PER_DAY = 24 * 60
NIGHT_START = 20  # hour
NIGHT_END = 6

DIRECTIONS: dict[str, Pos] = {
    "N": (0, -1), "NE": (1, -1), "E": (1, 0), "SE": (1, 1),
    "S": (0, 1), "SW": (-1, 1), "W": (-1, 0), "NW": (-1, -1),
}
NEIGHBORS: list[Pos] = list(DIRECTIONS.values())


@dataclass(frozen=True)
class ItemInfo:
    name: str  # Ukrainian display name
    glyph: str
    food: int = 0  # satiety restored when eaten
    heal: int = 0  # hp restored when eaten/used
    attack: int = 0  # melee damage when wielded
    light: bool = False
    note: str = ""  # short description for the LLM (English)


ITEMS: dict[str, ItemInfo] = {
    "fiber": ItemInfo("волокно", "=", note="building material from xeno-flora"),
    "ore": ItemInfo("руда", "o", note="building material from ore rocks"),
    "spores": ItemInfo("спорові капсули", "\"", food=12, note="food"),
    "raw_meat": ItemInfo("сире ксеном'ясо", "m", food=18, heal=-4, note="food, hurts a bit raw; cook it at a heater"),
    "cooked_meat": ItemInfo("смажене ксеном'ясо", "M", food=40, heal=3, note="good food"),
    "ration": ItemInfo("сухпайок", "c", food=45, note="good food"),
    "medkit": ItemInfo("аптечка", "+", heal=35, note="use to heal"),
    "flare": ItemInfo("фальшфеєр", "!", light=True, note="light source, burns out"),
    "headlamp": ItemInfo("налобний ліхтар", "¡", light=True, note="permanent light source"),
    "blade": ItemInfo("саморобне лезо", "/", attack=5, note="weapon"),
    "plasma_cutter": ItemInfo("плазморіз", "(", attack=7, note="weapon"),
    "artifact": ItemInfo("артефакт предтеч", "$", note="precursor artifact, the most valuable thing on this planet"),
    "alloy": ItemInfo("сплав обшивки", "&", note="hull alloy, beacon repair part (need 3)"),
    "circuit": ItemInfo("плата предтеч", "§", note="precursor circuit, beacon repair part (need 1)"),
    "power_cell": ItemInfo("енергоелемент", "¤", note="charge the pod with it (+25 power)"),
}


@dataclass
class Event:
    tick: int
    text: str
    kind: str = "info"  # info | danger | good | brain | death | event | diary | talk | victory


@dataclass
class Level:
    id: str
    name: str
    width: int
    height: int
    tiles: list[list[Tile]]
    dark: bool = False
    items: dict[Pos, list[str]] = field(default_factory=dict)
    creatures: list["Creature"] = field(default_factory=list)
    heaters: dict[Pos, int] = field(default_factory=dict)  # pos -> ticks left
    warm_spots: set[Pos] = field(default_factory=set)  # permanent heat sources (powered pod)
    regrow: dict[Pos, tuple[int, Tile]] = field(default_factory=dict)  # pos -> (tick, tile)
    entrances: dict[Pos, str] = field(default_factory=dict)  # surface pos -> wreck name
    exit_pos: Pos | None = None  # exit hatch inside a wreck
    parent: tuple[str, Pos] | None = None  # (level id, pos) to return to

    def in_bounds(self, p: Pos) -> bool:
        return 0 <= p[0] < self.width and 0 <= p[1] < self.height

    def tile(self, p: Pos) -> Tile:
        return self.tiles[p[1]][p[0]]

    def set_tile(self, p: Pos, t: Tile) -> None:
        self.tiles[p[1]][p[0]] = t

    def passable(self, p: Pos) -> bool:
        return self.in_bounds(p) and self.tile(p).passable

    def creature_at(self, p: Pos) -> "Creature | None":
        for c in self.creatures:
            if c.pos == p and c.hp > 0:
                return c
        return None

    def neighbors(self, p: Pos) -> Iterator[Pos]:
        for dx, dy in NEIGHBORS:
            q = (p[0] + dx, p[1] + dy)
            if self.in_bounds(q):
                yield q

    def positions(self) -> Iterator[Pos]:
        for y in range(self.height):
            for x in range(self.width):
                yield (x, y)

    def near_heat(self, p: Pos, radius: int = 2) -> bool:
        return any(chebyshev(p, f) <= radius for f in (*self.heaters, *self.warm_spots))

    def visible_from(self, origin: Pos, radius: int) -> set[Pos]:
        """Simple ray-cast field of view; opaque tiles are visible but block beyond."""
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


def chebyshev(a: Pos, b: Pos) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def direction_name(src: Pos, dst: Pos) -> str:
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    if dx == 0 and dy == 0:
        return "here"
    ns = "N" if dy < 0 else "S" if dy > 0 else ""
    ew = "E" if dx > 0 else "W" if dx < 0 else ""
    # drop the minor component when it is small relative to the major one
    if abs(dx) > 2 * abs(dy):
        ns = ""
    elif abs(dy) > 2 * abs(dx):
        ew = ""
    return ns + ew


def line(a: Pos, b: Pos) -> Iterator[Pos]:
    """Bresenham line from a to b inclusive."""
    x0, y0 = a
    x1, y1 = b
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        yield (x0, y0)
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


@dataclass
class World:
    seed: int
    levels: dict[str, Level]
    hero: "Hero"
    rng: random.Random
    tick: int = 8 * 60  # day 1, 08:00
    events: list[Event] = field(default_factory=list)
    listeners: list[Callable[[Event], None]] = field(default_factory=list)
    pod: "Pod | None" = None
    director: "Director | None" = None
    companion: "Companion | None" = None

    # --- time -----------------------------------------------------------
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
        return f"Сол {self.day}, {self.hour:02d}:{self.minute:02d}"

    # --- levels ---------------------------------------------------------
    @property
    def level(self) -> Level:
        return self.levels[self.hero.level_id]

    @property
    def surface(self) -> Level:
        return self.levels["surface"]

    # --- log ------------------------------------------------------------
    def log(self, text: str, kind: str = "info") -> None:
        ev = Event(self.tick, text, kind)
        self.events.append(ev)
        if len(self.events) > 500:
            del self.events[:100]
        for fn in self.listeners:
            fn(ev)
