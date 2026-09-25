"""The second survivor (arrives with the distress-signal event).

Routine life is a cheap utility AI (no LLM): drink, eat, sleep at the pod,
gather fiber into the pod storage. The LLM is only used for conversations
with the hero, which the simulation triggers now and then.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .pathfinding import find_path
from .tiles import Tile
from .world import ITEMS, Pos, chebyshev

if TYPE_CHECKING:
    from .world import Level, World

TALK_COOLDOWN = 8 * 60
FOOD = ("cooked_meat", "ration", "spores", "raw_meat")


class _FullMap:
    """Companions know the surface; quacks like the hero's memory dict."""

    def __init__(self, level: "Level") -> None:
        self.level = level

    def get(self, p: Pos, default=None):
        return self.level.tile(p) if self.level.in_bounds(p) else default


@dataclass
class Companion:
    pos: Pos
    name: str = "Ліра"
    personality: str = ("бортова інженерка-кібернетик: іронічна, прагматична, боїться темряви, "
                        "мріє повернутися до доньки на станції Церера")
    state: str = "stranded"  # stranded | working | dead
    hp: float = 40.0
    satiety: float = 45.0
    hydration: float = 35.0
    energy: float = 60.0
    trust: float = 0.4
    affinity: float = 0.5
    carrying: int = 0
    activity: str = "чекає на допомогу біля своєї капсули"
    last_talk: int = -10_000
    last_line: str = ""
    request: str = ""
    cause_of_death: str = ""
    talk_requested: bool = False
    _path: list[Pos] = field(default_factory=list)
    _goal: Pos | None = None
    _task: str = "work"
    _reach: int = 0

    @property
    def alive(self) -> bool:
        return self.state != "dead"

    @property
    def joined(self) -> bool:
        return self.state == "working"

    def wants_to_talk(self, world: "World") -> bool:
        hero = world.hero
        return (self.joined and hero.level_id == "surface" and chebyshev(self.pos, hero.pos) <= 2
                and world.tick - self.last_talk >= TALK_COOLDOWN and not hero.sleeping)

    def status_line(self) -> str:
        if not self.alive:
            return f"{self.name} is dead ({self.cause_of_death})"
        mood = "grateful" if self.affinity > 0.7 else "wary" if self.trust < 0.3 else "cooperative"
        text = (f"{self.name} ({self.state}, {self.activity}); hp {self.hp:.0f}, satiety {self.satiety:.0f}, "
                f"hydration {self.hydration:.0f}; trust {self.trust:.2f}, affinity {self.affinity:.2f} ({mood})")
        if self.request:
            text += f"; she asked you: \"{self.request}\""
        return text

    # --- relations ------------------------------------------------------------
    def adjust(self, trust: float = 0.0, affinity: float = 0.0) -> None:
        self.trust = min(1.0, max(0.0, self.trust + trust))
        self.affinity = min(1.0, max(0.0, self.affinity + affinity))

    def receive(self, world: "World", item: str) -> str:
        info = ITEMS[item]
        if info.food:
            self.satiety = min(100.0, self.satiety + info.food)
            self.adjust(0.05, 0.12)
            if "food" in self.request or "їж" in self.request:
                self.request = ""
            return f"{self.name} з вдячністю з'їла: {info.name}"
        if item == "medkit":
            self.hp = min(100.0, self.hp + info.heal)
            self.adjust(0.08, 0.1)
            return f"{self.name} перев'язала рани (аптечка)"
        if world.pod:
            world.pod.storage[item] += 1
        self.adjust(0.03, 0.04)
        return f"{self.name} поклала в капсулу: {info.name}"

    # --- tick -------------------------------------------------------------------
    def update(self, world: "World") -> None:
        if not self.alive:
            return
        hero = world.hero
        level = world.surface
        slow = 0.5 if self.activity == "спить" else 1.0
        self.satiety = max(0.0, self.satiety - 0.045 * slow)
        self.hydration = max(0.0, self.hydration - 0.065 * slow)
        self.energy = max(0.0, min(100.0, self.energy + (0.35 if self.activity == "спить" else -0.04)))
        starving = [n for n in ("satiety", "hydration") if getattr(self, n) <= 0]
        if starving:
            self.hp -= 0.15 * len(starving)
        elif self.satiety > 40 and self.hydration > 40:
            self.hp = min(100.0, self.hp + 0.02)
        if self.hp <= 0:
            self._die(world, "голод" if "satiety" in starving else "спрага")
            return

        if self.state == "stranded":
            if hero.level_id == "surface" and chebyshev(hero.pos, self.pos) <= 1:
                self.state = "working"
                self.adjust(0.2, 0.15)
                self.activity = "йде до капсули"
                world.log(f"{self.name} вибралася з уламків капсули і приєдналася до табору!", "good")
            return

        if world.tick % 20 == 0 or self._goal is None:
            self._choose(world, level)
        self._act(world, level)

    def _die(self, world: "World", cause: str) -> None:
        self.state = "dead"
        self.cause_of_death = cause
        self.activity = "мертва"
        if world.surface.tile(self.pos) in (Tile.MOSS, Tile.DUST):
            world.surface.set_tile(self.pos, Tile.GRAVE)
        world.log(f"{self.name} загинула ({cause}).", "death")

    # utility AI: score each activity, pick the best
    def _choose(self, world: "World", level: "Level") -> None:
        pod = world.pod
        night = world.is_night
        scores = {
            "drink": (1 - self.hydration / 100) ** 2 * 1.3,
            "eat": (1 - self.satiety / 100) ** 2 * 1.2,
            "sleep": (0.9 if night else 0.0) + (1 - self.energy / 100) ** 2,
            "work": 0.35 if not night else 0.05,
        }
        best = max(scores, key=scores.get)
        home = pod.pos if pod else self.pos
        if best == "drink":
            self._goal = self._nearest(level, lambda p: any(level.tile(q) is Tile.WATER for q in level.neighbors(p)))
            self.activity = "йде пити"
        elif best == "eat":
            if pod and any(pod.storage[f] for f in FOOD):
                self._goal, self.activity = home, "йде їсти з запасів капсули"
            else:
                self._goal = self._nearest(level, lambda p: level.tile(p) is Tile.SPORE_BUSH)
                self.activity = "шукає спори"
        elif best == "sleep":
            self._goal, self.activity = home, "йде спати до капсули"
        else:
            if self.carrying >= 3:
                self._goal, self.activity = home, "несе волокно в капсулу"
            else:
                self._goal = self._nearest(level, lambda p: level.tile(p) is Tile.FLORA, near=home)
                self.activity = "збирає волокно"
        self._path = []
        self._task = best
        # pod-bound goals are reached when adjacent; resource tiles must be stood on
        self._reach = 1 if self._goal == home and best in ("eat", "sleep", "work") else 0

    def _nearest(self, level: "Level", goal, near: Pos | None = None) -> Pos | None:
        start = near or self.pos
        path = find_path(level, _FullMap(level), start, goal, allow_unknown=False, max_nodes=4000)
        if path is None:
            return None
        return path[-1] if path else start

    def _act(self, world: "World", level: "Level") -> None:
        task = self._task
        pod = world.pod
        if self._goal is None:
            return
        if chebyshev(self.pos, self._goal) > self._reach:
            if world.tick % 2 == 0:  # she walks at half the hero's speed
                self._step(level)
            return
        if task == "drink":
            self.hydration = min(100.0, self.hydration + 6)
            if self.hydration >= 95:
                self._goal = None
        elif task == "eat":
            if pod and chebyshev(self.pos, pod.pos) <= 1:
                food = next((f for f in FOOD if pod.storage[f] > 0), None)
                if food:
                    pod.storage[food] -= 1
                    self.satiety = min(100.0, self.satiety + ITEMS[food].food)
            elif level.tile(self.pos) is Tile.SPORE_BUSH:
                level.set_tile(self.pos, Tile.SPORE_BUSH_EMPTY)
                level.regrow[self.pos] = (world.tick + 24 * 60, Tile.SPORE_BUSH)
                self.satiety = min(100.0, self.satiety + 30)
            self._goal = None
        elif task == "sleep":
            self.activity = "спить"
            if self.energy >= 98 and not world.is_night:
                self._goal = None
        else:
            if level.tile(self.pos) is Tile.FLORA and self.carrying < 3:
                if world.tick % 6 == 0:
                    self.carrying += 1
                if self.carrying >= 3:
                    self._goal = None
            elif pod and chebyshev(self.pos, pod.pos) <= 1 and self.carrying:
                pod.storage["fiber"] += self.carrying
                self.carrying = 0
                self._goal = None
            else:
                self._goal = None

    def _step(self, level: "Level") -> None:
        goal = self._goal
        if not self._path or chebyshev(self._path[-1], goal) > self._reach:
            reach = self._reach
            path = find_path(level, _FullMap(level), self.pos,
                             lambda p: chebyshev(p, goal) <= reach, allow_unknown=False, max_nodes=4000)
            if not path:
                self._goal = None
                return
            self._path = path
        nxt = self._path.pop(0)
        if level.passable(nxt) and not level.creature_at(nxt):
            self.pos = nxt
        else:
            self._path = []
