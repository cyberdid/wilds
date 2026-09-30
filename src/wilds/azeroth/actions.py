"""The hero's action menu in Mulgore. An action runs for many ticks until done or interrupted;
the brain is asked again only then (same idea as the other chapters)."""

from __future__ import annotations

import random
from enum import Enum
from typing import TYPE_CHECKING

from . import quests as q
from .route import find_route, reachable

if TYPE_CHECKING:
    from .sim import Creature, ZoneSim

ACTION_HELP: dict[str, tuple[str, str]] = {
    "go_to": ("place", "run to a known NPC, settlement or landmark by name"),
    "talk": ("npc", "speak to an NPC close by: accept the quests they offer, hand in finished ones"),
    "hunt": ("creature", "find the nearest living creature of that kind and fight it to the death"),
    "search": ("area", "go to an area and search it for what a quest asks you to collect"),
    "explore": ("", "walk to the nearest landmark you have not discovered yet"),
    "rest": ("ticks", "sit down and recover health"),
}
ATTACK_TICKS = 7     # about two seconds between blows
TALK_RANGE = 3
SEARCH_TICKS = 60


class Status(Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Action:
    name = ""
    max_ticks = 4000

    def __init__(self, target: str = "") -> None:
        self.target = (target or "").strip()
        self.ticks = 0
        self.result = ""
        self._path: list[tuple[int, int]] = []

    @property
    def effective_name(self) -> str:
        return self.name

    def start(self, sim: "ZoneSim") -> str | None:
        return None

    def step(self, sim: "ZoneSim") -> Status:
        raise NotImplementedError

    def cancel(self, sim: "ZoneSim") -> None:
        pass

    def done(self, msg: str) -> Status:
        self.result = msg
        return Status.DONE

    def fail(self, msg: str) -> Status:
        self.result = msg
        return Status.FAILED

    def walk_to(self, sim: "ZoneSim", dest: tuple[int, int], within: int = 1) -> str:
        """One step towards ``dest``: 'moved' | 'arrived' | 'blocked'."""
        hero = sim.hero
        if max(abs(hero.pos[0] - dest[0]), abs(hero.pos[1] - dest[1])) <= within:
            return "arrived"
        if not self._path or max(abs(self._path[0][0] - hero.pos[0]), abs(self._path[0][1] - hero.pos[1])) != 1:
            path = find_route(sim.world, hero.pos, dest)
            if path is None:
                return "blocked"
            self._path = path
        if not self._path:
            return "arrived"
        hero.pos = self._path.pop(0)
        return "moved"


class GoTo(Action):
    name = "go_to"

    def start(self, sim: "ZoneSim") -> str | None:
        spot = sim.find_place(self.target)
        if spot is None:
            return f"unknown place '{self.target}'; use a name from KNOWN PLACES"
        self.dest, self.label = spot
        self.within = 3 if sim.is_npc(self.target) else 12
        if not reachable(sim.world, sim.hero.pos, self.dest):
            return f"{self.label} cannot be reached on foot from here"
        return None

    def step(self, sim: "ZoneSim") -> Status:
        state = self.walk_to(sim, self.dest, self.within)
        if state == "arrived":
            return self.done(f"arrived at {self.label}")
        if state == "blocked":
            return self.fail(f"no way to {self.label}")
        return Status.RUNNING


class Explore(Action):
    name = "explore"

    def start(self, sim: "ZoneSim") -> str | None:
        here = sim.hero.pos
        options = [(max(abs(p.pos[0] - here[0]), abs(p.pos[1] - here[1])), p) for p in sim.landmarks()
                   if q.clean(p.title) not in sim.hero.discovered and q.clean(p.title) not in sim.unreachable
                   and reachable(sim.world, here, p.pos)]
        if not options:
            return "every landmark of this zone is already discovered"
        _, self.place = min(options, key=lambda t: t[0])
        return None

    def step(self, sim: "ZoneSim") -> Status:
        state = self.walk_to(sim, self.place.pos, 14)
        if state == "arrived":
            return self.done(f"reached {self.place.title}")
        if state == "blocked":
            sim.unreachable.add(q.clean(self.place.title))
            return self.fail(f"cannot reach {self.place.title}")
        return Status.RUNNING


class Rest(Action):
    name = "rest"

    def start(self, sim: "ZoneSim") -> str | None:
        digits = "".join(ch for ch in self.target if ch.isdigit())
        self.limit = max(10, min(int(digits) if digits else 120, 1200))
        return None

    def step(self, sim: "ZoneSim") -> Status:
        hero = sim.hero
        hero.hp = min(hero.max_hp, hero.hp + hero.max_hp * 0.004)
        if hero.hp >= hero.max_hp or self.ticks + 1 >= self.limit:
            return self.done("rested")
        return Status.RUNNING


class Talk(Action):
    name = "talk"

    def start(self, sim: "ZoneSim") -> str | None:
        spot = sim.find_place(self.target)
        if spot is None or not sim.is_npc(self.target):
            return f"unknown NPC '{self.target}'"
        self.dest, self.label = spot
        self.npc = q.clean(self.target)
        return None

    def step(self, sim: "ZoneSim") -> Status:
        state = self.walk_to(sim, self.dest, TALK_RANGE)
        if state == "blocked":
            return self.fail(f"cannot reach {self.label}")
        if state == "moved":
            return Status.RUNNING
        return self.done(sim.converse_with(self.npc, self.label))


class Hunt(Action):
    name = "hunt"

    def start(self, sim: "ZoneSim") -> str | None:
        self.kind = q.clean(self.target)
        if not sim.living(self.kind):
            return f"no living '{self.target}' anywhere in the zone"
        self.victim: "Creature | None" = None
        self.cooldown = 0
        return None

    def _pick(self, sim: "ZoneSim") -> "Creature | None":
        hero = sim.hero
        live = sim.living(self.kind)
        return min(live, key=lambda c: max(abs(c.pos[0] - hero.pos[0]), abs(c.pos[1] - hero.pos[1])), default=None)

    def step(self, sim: "ZoneSim") -> Status:
        hero = sim.hero
        if self.victim is None or self.victim.hp <= 0:
            self.victim = self._pick(sim)
            if self.victim is None:
                return self.fail(f"all '{self.target}' are dead")
        c = self.victim
        dist = max(abs(c.pos[0] - hero.pos[0]), abs(c.pos[1] - hero.pos[1]))
        if dist > 1:
            if dist > 30:  # far: a planned route, kept until the quarry has moved a lot
                state = self.walk_to(sim, c.pos, 1)
            else:          # close: just close in on it, the quarry keeps moving
                state = "moved" if sim.step_hero_toward(c.pos) else "blocked"
                self._path = []
            return Status.RUNNING if state == "moved" else self.fail(f"cannot reach {c.title}")
        self.cooldown -= 1
        if self.cooldown <= 0:
            self.cooldown = ATTACK_TICKS
            if sim.hero_strikes(c):
                return self.done(f"killed {c.title}")
        return Status.RUNNING


class Search(Action):
    name = "search"

    def start(self, sim: "ZoneSim") -> str | None:
        spot = sim.find_place(self.target)
        if spot is None:
            return f"unknown area '{self.target}'"
        self.dest, self.label = spot
        self.searched = 0
        return None

    def step(self, sim: "ZoneSim") -> Status:
        if self.searched == 0:
            state = self.walk_to(sim, self.dest, 14)
            if state == "blocked":
                return self.fail(f"cannot reach {self.label}")
            if state == "moved":
                return Status.RUNNING
        self.searched += 1
        if self.searched >= SEARCH_TICKS:
            return self.done(sim.collect_found(self.label))
        return Status.RUNNING


ACTIONS = {cls.name: cls for cls in (GoTo, Talk, Hunt, Search, Explore, Rest)}


def make_action(name: str, target: str = "") -> Action:
    return ACTIONS[name](target)


def jitter(rng: random.Random, pos: tuple[int, int], spread: int) -> tuple[int, int]:
    return pos[0] + rng.randint(-spread, spread), pos[1] + rng.randint(-spread, spread)
