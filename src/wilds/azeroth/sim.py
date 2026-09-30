"""The Mulgore simulation: a hero living in a real-scale zone.

Same shape as the other chapters (decide -> run an action -> interrupt -> ask again), with
the pieces that make a zone feel alive at this size: creatures are only simulated near the
hero (the rest stand at home until he comes back), quests come from the content pack, and
travel takes as long as it would at a run.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ..metrics import Metrics
from ..sim import Conversation, Decision, HistoryEntry, Reflection, remember
from . import content, quests as q
from .actions import ACTION_HELP, ATTACK_TICKS, Action, Rest, Status, make_action
from .route import astar
from .scale import CHUNK, TICK_SECONDS
from .terrain import Terrain
from .world import Placement, ZoneWorld

Pos = tuple[int, int]
SIGHT = 9              # tiles (18 yards): how far a hostile notices the hero
LEASH = 40             # tiles a creature chases before giving up
ACTIVE_CHUNKS = 2      # creatures within this many chunks of the hero are simulated
RESPAWN_TICKS = 1800   # about 8.5 minutes
PACK_SIZE = 4
GOAL_LEVEL = 10
START_HOUR = 9
REFLECT_EVERY = 6000
LANDMARK_KINDS = ("subzone", "settlement", "gate", "lake", "plateau")
ZONE_WIDE = {"mulgore", "varies", "", "-"}


def cheb(a: Pos, b: Pos) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


@dataclass
class Creature:
    id: int
    title: str
    species: str
    level: int
    hp: int
    max_hp: int
    damage: int
    pos: Pos
    home: Pos
    hostile: bool
    target_hero: bool = False
    cooldown: int = 0
    respawn_at: int = 0

    @property
    def alive(self) -> bool:
        return self.hp > 0


@dataclass
class ActiveQuest:
    quest: q.Quest
    objectives: list[q.Objective]
    ready: bool = False


@dataclass
class Hero:
    pos: Pos
    name: str = "Мандрівник"
    level: int = 1
    xp: int = 0
    hp: float = 60.0
    max_hp: float = 60.0
    alive: bool = True
    deaths: int = 0
    hurt_this_tick: float = 0.0
    active: dict[str, ActiveQuest] = field(default_factory=dict)
    done: set[str] = field(default_factory=set)
    kills: Counter = field(default_factory=Counter)
    discovered: set[str] = field(default_factory=set)
    traits: list[str] = field(default_factory=list)
    goal: str = ""
    diary: list[tuple[int, str]] = field(default_factory=list)
    inventory: Counter = field(default_factory=Counter)
    rescued: bool = False

    @property
    def attack(self) -> int:
        return 3 + self.level * 2

    def xp_to_next(self) -> int:
        return 100 * self.level + 50


class ZoneSim:
    def __init__(self, world: ZoneWorld, seed: int = 0) -> None:
        self.world = world
        self.rng = random.Random(seed)
        self.action: Action | None = None
        self.history: list[HistoryEntry] = []
        self.wake_reason = "you have just started your life at Camp Narache"
        self.thought = ""
        self.decisions = 0
        self.pending_reflection: int | None = None
        self.pending_conversation = False
        self.diary_path = None
        self.metrics = Metrics()
        self._invalid_streak = 0
        self._next_reflection = REFLECT_EVERY
        self._alerted: set[int] = set()
        self.unreachable: set[str] = set()  # landmarks the hero found no way to
        self.legacy_path = None
        pack = world.pack
        self._mob_records = {q.clean(r["title"]): r for r in content.load(pack, "mob")}
        places = {}
        for p in world.placements:
            places.setdefault(q.clean(p.title), p)
        self.places: dict[str, Placement] = places
        self.npc_names = {q.clean(p.title) for p in world.placements if p.kind == "npc"}
        subzones = {q.clean(p.title) for p in world.placements if p.kind in LANDMARK_KINDS}
        self.quests = q.load_quests(pack, self.npc_names, set(self._mob_records), subzones)
        start = places.get("camp narache") or next(iter(places.values()))
        world.tick = world.tick or int(START_HOUR * 3600 / TICK_SECONDS)  # the day begins in the morning
        self._next_reflection = world.tick + REFLECT_EVERY
        self.hero = Hero(world.nearest_passable(start.pos, 40) or start.pos)
        self.hero.discovered.add("camp narache")
        world.hero = self.hero
        self.creatures: dict[int, Creature] = {}
        self._by_chunk: dict[tuple[int, int], set[int]] = {}
        self._next_id = 1
        self._dead: dict[int, int] = {}  # creature id -> tick it comes back, wherever the hero is
        self._spawn_all()
        # a quest whose kill targets are not in the world cannot be played: drop it, do not fake it
        alive = {q.clean(c.title) for c in self.creatures.values()}
        self.quests = [qu for qu in self.quests if all(o.target in alive for o in qu.kills)]
        world.log("Кемп Нараче. Твоє життя в Мулгорі починається.", "event")

    # --- places ----------------------------------------------------------------------------
    def find_place(self, name: str) -> tuple[Pos, str] | None:
        p = self.places.get(q.clean(name))
        return (p.pos, p.title) if p else None

    def is_npc(self, name: str) -> bool:
        return q.clean(name) in self.npc_names

    def landmarks(self) -> list[Placement]:
        return [p for p in self.world.placements if p.kind in LANDMARK_KINDS]

    # --- creatures ---------------------------------------------------------------------------
    def _spawn_all(self) -> None:
        w = self.world
        towns = [p.pos for p in w.placements if p.kind in ("settlement", "npc")]
        placed = {q.clean(p.title): p for p in w.placements if p.kind == "mob"}
        for title, rec in sorted(self._mob_records.items()):
            if rec["removed"] and title not in q.quest_refs(w.pack):
                continue
            base = placed.get(title)
            if base is not None:
                spots = [base.pos] * PACK_SIZE
                spread = 10
            elif self._zone_wide(rec):
                spots = [self._wild_spot(towns) for _ in range(5)]
                spread = 6
            else:
                continue
            for spot in spots:
                if spot is None:
                    continue
                self._add_creature(rec, w.nearest_passable((spot[0] + self.rng.randint(-spread, spread),
                                                            spot[1] + self.rng.randint(-spread, spread)), 20) or spot)

    @staticmethod
    def _zone_wide(rec: dict[str, Any]) -> bool:
        places = [s.strip().lower() for s in rec["info"].get("location", "").replace(";", ",").split(",")]
        return bool(places) and all(s in ZONE_WIDE or s == "mulgore" for s in places) or not rec["info"].get("location")

    def _wild_spot(self, towns: list[Pos]) -> Pos | None:
        w = self.world
        for _ in range(60):
            p = (self.rng.randrange(w.geo.width), self.rng.randrange(w.geo.height))
            if w.terrain.tile(*p) in (Terrain.GRASS, Terrain.TALL_GRASS, Terrain.DRY_GRASS) and \
                    all(cheb(p, t) > 60 for t in towns):
                return p
        return None

    def _add_creature(self, rec: dict[str, Any], pos: Pos) -> None:
        digits = "".join(ch if ch.isdigit() else " " for ch in rec["info"].get("level", "")).split()
        level = int(digits[0]) if digits else 1 + sum(map(ord, rec["id"])) % 6
        hp = 18 + 10 * level
        c = Creature(self._next_id, rec["title"], q.clean(rec["info"].get("race", "")) or "beast", level, hp, hp,
                     1 + level // 2 + 1, pos, pos, rec.get("aggro", {}).get("horde") == -1)
        self._next_id += 1
        self.creatures[c.id] = c
        self._by_chunk.setdefault((pos[0] // CHUNK, pos[1] // CHUNK), set()).add(c.id)

    def _move(self, c: Creature, pos: Pos) -> None:
        old = (c.pos[0] // CHUNK, c.pos[1] // CHUNK)
        new = (pos[0] // CHUNK, pos[1] // CHUNK)
        if old != new:
            self._by_chunk.get(old, set()).discard(c.id)
            self._by_chunk.setdefault(new, set()).add(c.id)
        c.pos = pos

    def respawning(self, kind: str) -> bool:
        """Some creature of this kind is dead and will come back."""
        return any(q.clean(self.creatures[i].title) == kind for i in self._dead)

    def living(self, kind: str) -> list[Creature]:
        return [c for c in self.creatures.values() if c.alive and q.clean(c.title) == kind]

    def near_creatures(self, radius_chunks: int = ACTIVE_CHUNKS) -> list[Creature]:
        cx, cy = self.hero.pos[0] // CHUNK, self.hero.pos[1] // CHUNK
        out = []
        for dx in range(-radius_chunks, radius_chunks + 1):
            for dy in range(-radius_chunks, radius_chunks + 1):
                out += [self.creatures[i] for i in self._by_chunk.get((cx + dx, cy + dy), ())]
        return out

    def attackers(self) -> list[Creature]:
        """Creatures that are fighting the hero right now."""
        return [c for c in self.near_creatures(1) if c.alive and c.target_hero and cheb(c.pos, self.hero.pos) <= 3]

    def visible_hostiles(self) -> list[Creature]:
        h = self.hero.pos
        return sorted((c for c in self.near_creatures() if c.alive and c.hostile and cheb(c.pos, h) <= SIGHT),
                      key=lambda c: cheb(c.pos, h))

    # --- combat and progress -------------------------------------------------------------------
    def hero_strikes(self, c: Creature) -> bool:
        hero, w = self.hero, self.world
        dmg = max(1, hero.attack + self.rng.randint(-1, 2))
        c.hp -= dmg
        c.target_hero = True
        if c.hp > 0:
            w.log(f"Б'єш {c.title}: -{dmg}, лишилось {c.hp}", "info")
            return False
        w.log(f"Вбив: {c.title} (рівень {c.level})", "good")
        c.respawn_at = w.tick + RESPAWN_TICKS
        self._dead[c.id] = c.respawn_at
        c.target_hero = False
        hero.kills[q.clean(c.title)] += 1
        self._gain_xp(max(5, 8 * c.level - 4 * max(0, hero.level - c.level)))
        for aq in hero.active.values():
            for o in aq.objectives:
                if o.kind == "kill" and o.target == q.clean(c.title) and not o.complete:
                    o.done += 1
                    w.log(f"Задання «{aq.quest.title}»: {c.title} {o.done}/{o.count}", "good")
            self._check_ready(aq)
        return True

    def _gain_xp(self, amount: int) -> None:
        hero = self.hero
        hero.xp += amount
        while hero.xp >= hero.xp_to_next():
            hero.xp -= hero.xp_to_next()
            hero.level += 1
            hero.max_hp += 12
            hero.hp = hero.max_hp
            self.world.log(f"Новий рівень: {hero.level}!", "victory" if hero.level >= GOAL_LEVEL else "good")
            self.pending_reflection = self.pending_reflection or self.world.tick

    def _check_ready(self, aq: ActiveQuest) -> None:
        if not aq.ready and aq.objectives and all(o.complete for o in aq.objectives):
            aq.ready = True
            self.world.log(f"Задання «{aq.quest.title}» виконано: поверніться до {aq.quest.turn_in.title()}", "good")

    def available_from(self, npc: str) -> list[q.Quest]:
        h = self.hero
        return [qu for qu in self.quests if qu.giver == npc and qu.title.lower() not in h.done
                and qu.id not in {a.quest.id for a in h.active.values()} and qu.req_level <= h.level
                and all(p in h.done or p not in {x.title.lower() for x in self.quests} for p in qu.previous)]

    def converse_with(self, npc: str, label: str) -> str:
        hero, w = self.hero, self.world
        said = []
        for aq in [a for a in hero.active.values() if a.ready and a.quest.turn_in == npc]:
            del hero.active[aq.quest.id]
            hero.done.add(aq.quest.title.lower())
            self._gain_xp(aq.quest.xp)
            said.append(f"здано «{aq.quest.title}» (+{aq.quest.xp} досвіду)")
            w.log(f"{label}: задання «{aq.quest.title}» здано. Нагорода: {aq.quest.rewards or '—'}", "good")
        for qu in self.available_from(npc)[:2]:
            aq = ActiveQuest(qu, [q.Objective(o.kind, o.target, o.count) for o in qu.objectives])
            hero.active[qu.id] = aq
            if qu.errand:  # nothing to count: report to the turn-in NPC, after visiting the area if it names one
                aq.ready = qu.turn_in != npc and not qu.area
            self._check_ready(aq)
            said.append(f"прийнято «{qu.title}»")
            w.log(f"{label}: «{qu.title}». {qu.brief or qu.text[:140]}", "event")
        if not said:
            w.log(f"{label} кивнув, але справ для тебе нема.", "info")
        return f"talked with {label}: " + ("; ".join(said) or "nothing to do")

    def collect_found(self, label: str) -> str:
        area, found = q.clean(label), []
        for aq in self.hero.active.values():
            if aq.quest.area in ("", area):
                for o in aq.objectives:
                    if o.kind == "collect" and not o.complete:
                        o.done = o.count
                        found.append(o.target)
                if aq.quest.errand and aq.quest.area == area:
                    aq.ready = True
                self._check_ready(aq)
        if found:
            self.world.log(f"Знайдено: {', '.join(found)}", "good")
        return f"searched {label}: " + (", ".join(found) or "found nothing")

    # --- what the front-end asks ------------------------------------------------------------------
    @property
    def over(self) -> bool:
        return self.hero.level >= GOAL_LEVEL

    @property
    def needs_decision(self) -> bool:
        return not self.over and self.action is None

    @property
    def pending(self) -> str | None:
        if self.over:
            return None
        if self.pending_reflection is not None:
            return "reflect"
        if self.action is None:
            return "decide"
        return None

    def consult(self, brain) -> None:
        kind = self.pending
        if kind == "reflect":
            self.apply_reflection(brain.reflect(self))
        elif kind == "decide":
            self.apply(brain.decide(self))

    def apply(self, decision: Decision) -> str | None:
        w = self.world
        self.decisions += 1
        self.thought = decision.thought
        entry = HistoryEntry(w.tick, decision.action, decision.target, decision.thought)
        self.history.append(entry)
        del self.history[:-30]
        self.metrics.on_decision(decision)
        if decision.thought:
            w.log(decision.thought, "brain")
        try:
            action = make_action(decision.action, decision.target)
            error = action.start(self)
        except KeyError:
            error = f"unknown action '{decision.action}'"
        if error:
            entry.outcome = f"rejected: {error}"
            self.wake_reason = f"your last choice was rejected: {error}"
            self.metrics.rejections += 1
            self._invalid_streak += 1
            if self._invalid_streak < 3:
                return error
            action = Rest("15")
            action.start(self)
            w.log("(розгубився і стоїть на місці)", "info")
        self._invalid_streak = 0
        self.action = action
        return error

    def apply_reflection(self, r: Reflection) -> None:
        w, hero = self.world, self.hero
        self.pending_reflection = None
        self._next_reflection = w.tick + REFLECT_EVERY
        text = r.diary.strip()
        if not text:
            return
        hero.diary.append((w.day, text))
        remember(hero.traits, r.trait, limit=5)
        if r.goal.strip():
            hero.goal = r.goal.strip()[:160]
        w.log(f"Щоденник, день {w.day}: {text}", "diary")
        if hero.goal:
            w.log(f"Мета: {hero.goal}", "diary")
        if self.diary_path:
            with open(self.diary_path, "a", encoding="utf-8") as f:
                f.write(f"## День {w.day}, {w.clock()}\n\n{text}\n\n*Мета:* {hero.goal}\n\n")

    def apply_conversation(self, c: Conversation) -> None:
        self.pending_conversation = False

    def run(self, brain, ticks: int) -> None:
        for _ in range(ticks):
            if self.over:
                return
            for _guard in range(5):
                if not self.pending:
                    break
                self.consult(brain)
            if self.action is not None:
                self.tick()

    # --- tick -------------------------------------------------------------------------------------------
    def tick(self) -> None:
        w, hero, action = self.world, self.hero, self.action
        if action is None or self.over:
            return
        hero.hurt_this_tick = 0.0
        status = action.step(self)
        action.ticks += 1
        w.tick += 1
        self._update_creatures()
        self._regen(action)
        self._discover()
        if w.tick >= self._next_reflection and self.pending_reflection is None:
            self.pending_reflection = w.tick
        if hero.hp <= 0:
            self._die()
            return
        if status is not Status.RUNNING:
            self._finish(f"{status.value}: {action.result}")
            return
        reason = self._interrupt_reason(action)
        if reason:
            action.cancel(self)
            action.result = f"interrupted: {reason}"
            self._finish(action.result)

    def _finish(self, outcome: str) -> None:
        if self.history and self.history[-1].outcome == "":
            self.history[-1].outcome = outcome
        self.wake_reason = outcome
        self.action = None

    def _regen(self, action: Action) -> None:
        hero = self.hero
        if action.effective_name != "hunt" and not any(c.target_hero and c.alive for c in self.near_creatures(1)):
            hero.hp = min(hero.max_hp, hero.hp + hero.max_hp * 0.0008)

    def _discover(self) -> None:
        hero = self.hero
        for p in self.landmarks():
            key = q.clean(p.title)
            if key not in hero.discovered and cheb(p.pos, hero.pos) <= 40:
                hero.discovered.add(key)
                self.world.log(f"Відкрито: {p.title}", "good")

    def _interrupt_reason(self, action: Action) -> str | None:
        reasons = []
        hostiles = [c for c in self.visible_hostiles() if c.id not in self._alerted]
        if hostiles and action.effective_name not in ("hunt",):
            c = hostiles[0]
            self._alerted.add(c.id)
            reasons.append(f"a hostile {c.title} (level {c.level}) is {cheb(c.pos, self.hero.pos)} tiles away")
        if self.hero.hurt_this_tick > 0 and action.effective_name != "hunt":
            reasons.append(f"you were hurt (-{self.hero.hurt_this_tick:.0f} hp)")
        if action.ticks >= action.max_ticks:
            reasons.append(f"'{action.name}' took too long")
        if not self.visible_hostiles():
            self._alerted &= {c.id for c in self.near_creatures()}
        return "; ".join(reasons) or None

    def _update_creatures(self) -> None:
        w, hero = self.world, self.hero
        if self._dead:
            for cid in [i for i, t in self._dead.items() if w.tick >= t]:
                c = self.creatures[cid]
                del self._dead[cid]
                c.hp, c.respawn_at, c.target_hero = c.max_hp, 0, False
                self._move(c, c.home)
        for c in self.near_creatures():
            if not c.alive:
                continue
            c.cooldown = max(0, c.cooldown - 1)
            d = cheb(c.pos, hero.pos)
            if c.hostile and d <= SIGHT and not c.target_hero:
                c.target_hero = True
            if c.target_hero:
                if d > LEASH:  # the hero is gone: it gives up, recovers and walks home
                    c.target_hero = False
                    c.hp = c.max_hp
                elif d > 1:
                    self._step_toward(c, hero.pos)
                elif c.cooldown == 0:
                    c.cooldown = ATTACK_TICKS
                    dmg = max(1, c.damage + self.rng.randint(-1, 1))
                    hero.hp -= dmg
                    hero.hurt_this_tick += dmg
                    w.log(f"{c.title} б'є тебе: -{dmg}", "danger")
                continue
            if cheb(c.pos, c.home) > 10:
                self._step_toward(c, c.home)
            elif w.tick % 6 == 0 and self.rng.random() < 0.5:
                self._wander(c)

    def step_hero_toward(self, dest: Pos) -> bool:
        """One step of the hero towards a nearby spot, round obstacles. False if stuck."""
        hero, w = self.hero, self.world
        here = hero.pos
        free = lambda p: w.passable(p) and not self._creature_at(p)  # noqa: E731
        best = min(((cheb((here[0] + dx, here[1] + dy), dest), (here[0] + dx, here[1] + dy))
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy) and free((here[0] + dx, here[1] + dy))),
                   default=None)
        if best and best[0] < cheb(here, dest):
            hero.pos = best[1]
            return True
        # boxed in by something: walk to a free tile next to the target, the long way round
        spots = [(dest[0] + dx, dest[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                 if (dx or dy) and free((dest[0] + dx, dest[1] + dy))]
        for spot in sorted(spots, key=lambda p: cheb(p, here)):
            path = astar(here, spot, free, max_nodes=600, bounds=lambda p: cheb(p, here) <= 30)
            if path:
                hero.pos = path[0]
                return True
        return False

    def _creature_at(self, p: Pos) -> bool:
        return any(c.alive and c.pos == p for c in self._by_chunk_creatures(p))

    def _by_chunk_creatures(self, p: Pos):
        return [self.creatures[i] for i in self._by_chunk.get((p[0] // CHUNK, p[1] // CHUNK), ())]

    def _step_toward(self, c: Creature, dest: Pos) -> None:
        best, best_d = None, cheb(c.pos, dest)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = (c.pos[0] + dx, c.pos[1] + dy)
                if (dx or dy) and self.world.passable(p) and p != self.hero.pos and cheb(p, dest) < best_d:
                    best, best_d = p, cheb(p, dest)
        if best:
            self._move(c, best)

    def _wander(self, c: Creature) -> None:
        p = (c.pos[0] + self.rng.randint(-1, 1), c.pos[1] + self.rng.randint(-1, 1))
        if self.world.passable(p) and cheb(p, c.home) <= 10 and p != self.hero.pos:
            self._move(c, p)

    def _die(self) -> None:
        w, hero = self.world, self.hero
        hero.deaths += 1
        w.log(f"{hero.name} загинув. Дух прокидається в Кемпі Нараче.", "death")
        start = self.places.get("camp narache")
        hero.pos = w.nearest_passable(start.pos, 40) or start.pos
        hero.hp = hero.max_hp
        for c in self.creatures.values():
            c.target_hero = False
        if self.action:
            self._finish("died")
        self.action = None

    def status(self) -> dict[str, Any]:
        h = self.hero
        return {"level": h.level, "xp": h.xp, "hp": round(h.hp), "quests_done": len(h.done),
                "active": len(h.active), "kills": sum(h.kills.values()), "deaths": h.deaths,
                "discovered": len(h.discovered), "clock": self.world.clock()}


__all__ = ["ZoneSim", "Hero", "Creature", "ACTION_HELP"]
