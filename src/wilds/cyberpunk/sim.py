"""The cyberpunk chapter's simulation loop - the same shape as wilds.sim.Simulation
(decide -> execute -> interrupt -> nightly diary -> occasional conversation),
kept as a separate lightweight class since the world/hero types differ."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from ..metrics import Metrics
from ..world import TICKS_PER_DAY, chebyshev
from .actions import ACTION_HELP, Action, Rest, Status, make_action
from .director import CyberDirector
from .factions import adjust, faction_of
from .npc import NPC
from .race import random_race
from .risk import decay_heat
from .worldgen import HOME_DISTRICT

if TYPE_CHECKING:
    from .hero import Place
    from .world import CityWorld

TALK_COOLDOWN = 4 * 60

# stage: upkeep - a modest, escalating diegetic cost of living, charged at
# the end of each day; deliberately NOT an exponential reward-decay formula
# on contracts, since that would be unexplainable to a spectator
UPKEEP_BASE = 90
UPKEEP_PER_DAY = 10
UPKEEP_CAP = 300

# stage: debt installments - a required minimum paydown every few days, or
# the corp sends a collector
INSTALLMENT_TICKS = 3 * TICKS_PER_DAY
INSTALLMENT_MIN = 400

# stage: ambient hazards (collector, hostile-reputation ganger ambush) share
# one cooldown field on NPC (last_hit) so neither can spam damage every tick
AMBUSH_COOLDOWN = 180
COLLECTOR_DAMAGE = (10.0, 22.0)
GANGER_AMBUSH_DAMAGE = (8.0, 20.0)
HOSTILE_REP_THRESHOLD = -0.5


@dataclass
class Decision:
    action: str
    target: str = ""
    thought: str = ""


@dataclass
class Reflection:
    diary: str
    trait: str = ""
    goal: str = ""


@dataclass
class Conversation:
    lines: list[tuple[str, str]] = field(default_factory=list)  # (hero|npc, text)
    trust_delta: float = 0.0
    affinity_delta: float = 0.0
    request: str = ""


@dataclass
class HistoryEntry:
    tick: int
    action: str
    target: str
    thought: str
    outcome: str = ""


class Brain(Protocol):
    name: str
    label: str

    def decide(self, sim: "CitySim") -> Decision: ...

    def reflect(self, sim: "CitySim") -> Reflection: ...

    def converse(self, sim: "CitySim") -> Conversation: ...


class CitySim:
    def __init__(self, world: "CityWorld") -> None:
        self.world = world
        self.action: Action | None = None
        self.history: list[HistoryEntry] = []
        self.wake_reason = "you just arrived in the Sprawl, owing the corp that pulled you out of Tau-7"
        self.thought = ""
        self.decisions = 0
        self.pending_reflection: int | None = None
        self.pending_conversation: str = ""  # npc id, or ""
        self.diary_path = None
        self._invalid_streak = 0
        self._day = world.day
        self.metrics = Metrics()
        self.director = CyberDirector()
        self._debt_baseline = world.hero.debt
        self._next_installment = world.tick + INSTALLMENT_TICKS

    @property
    def over(self) -> bool:
        hero = self.world.hero
        return hero.free or not hero.alive

    @property
    def pending(self) -> str | None:
        if self.over:
            return None
        if self.pending_reflection is not None:
            return "reflect"
        if self.pending_conversation:
            return "converse"
        if self.action is None:
            return "decide"
        return None

    def consult(self, brain: Brain) -> None:
        kind = self.pending
        if kind == "reflect":
            self.apply_reflection(brain.reflect(self))
        elif kind == "converse":
            self.apply_conversation(brain.converse(self))
        elif kind == "decide":
            self.apply(brain.decide(self))

    def apply(self, decision: Decision) -> str | None:
        world = self.world
        self.decisions += 1
        self.metrics.on_decision(decision)
        self.thought = decision.thought
        entry = HistoryEntry(world.tick, decision.action, decision.target, decision.thought)
        self.history.append(entry)
        del self.history[:-30]
        if decision.thought:
            world.log(decision.thought, "brain")
        try:
            action = make_action(decision.action, decision.target)
            error = action.start(world)
        except KeyError:
            error = f"unknown action '{decision.action}'"
        if error:
            entry.outcome = f"rejected: {error}"
            self.wake_reason = f"your last choice was rejected: {error}"
            self._invalid_streak += 1
            if self._invalid_streak < 3:
                return error
            action = Rest("15")
            action.start(world)
        self._invalid_streak = 0
        self.action = action
        return error

    def apply_reflection(self, r: Reflection) -> None:
        from ..sim import remember  # shared dedup-by-similarity helper

        world = self.world
        hero = world.hero
        day = self.pending_reflection or world.day - 1
        self.pending_reflection = None
        text = r.diary.strip()
        if not text:
            return
        hero.diary.append((day, text))
        remember(hero.traits, r.trait, limit=5)
        if r.goal.strip():
            hero.goal = r.goal.strip()[:160]
        world.log(f"Щоденник, день {day}: {text}", "diary")
        if hero.goal:
            world.log(f"Мета на завтра: {hero.goal}", "diary")
        if self.diary_path:
            with open(self.diary_path, "a", encoding="utf-8") as f:
                f.write(f"## День {day}\n\n{text}\n\n*Мета:* {hero.goal}\n\n")

    def apply_conversation(self, c: Conversation) -> None:
        world = self.world
        hero = world.hero
        npc_id = self.pending_conversation
        self.pending_conversation = ""
        npc = next((n for n in world.level.npcs if n.id == npc_id), None)
        if npc is None:
            return
        npc.last_talk = world.tick
        for speaker, text in c.lines[:6]:
            who = npc.name if speaker == "npc" else world.hero.name
            world.log(f"{who}: «{text.strip()}»", "talk")
            if speaker == "npc":
                npc.last_line = text.strip()
        trust_delta = max(-0.15, min(0.15, c.trust_delta))
        npc.adjust(trust_delta, max(-0.15, min(0.15, c.affinity_delta)))
        npc.request = c.request.strip()[:160]
        adjust(hero.reputation, faction_of(npc.role), trust_delta * 0.5)

    def run(self, brain: Brain, ticks: int) -> None:
        for _ in range(ticks):
            if self.over:
                return
            for _guard in range(6):
                if not self.pending:
                    break
                self.consult(brain)
            if self.action is not None:
                self.tick()

    def tick(self) -> None:
        world = self.world
        hero = world.hero
        action = self.action
        if action is None or self.over:
            return
        status = action.step(world)
        action.ticks += 1
        world.tick += 1
        for lv in world.levels.values():
            decay_heat(lv)
        new_places = hero.observe(world)
        if world.contract is not None and world.contract.status == "active":
            if hero.level_id == world.contract.level_id and chebyshev(hero.pos, world.contract.drop_pos) <= 1:
                world.contract.status = "delivered"
                world.log("Пакунок забрано з дедропу.", "good")

        self._ambient_hazards(world)

        if world.day != self._day:
            self._day = world.day
            self.pending_reflection = world.day - 1
            self._charge_upkeep(world)
        if world.tick >= self._next_installment and hero.debt > 0:
            self._check_installment(world)
        self.director.update(world, self.metrics.action_diversity(len(ACTION_HELP)))
        if world.pending_talk:
            npc = next((n for n in world.level.npcs if n.id == world.pending_talk), None)
            if npc and world.tick - npc.last_talk >= TALK_COOLDOWN:
                self.pending_conversation = world.pending_talk
            world.pending_talk = ""

        if not hero.alive:
            self._finish(f"died: {hero.cause_of_death}")
            return
        if status is not Status.RUNNING:
            self._finish(f"{status.value}: {action.result}")
            return
        reason = self._interrupt_reason(action, new_places)
        if reason:
            action.cancel(world)
            action.result = f"interrupted: {reason}"
            self._finish(action.result)

    def _finish(self, outcome: str) -> None:
        if self.history and self.history[-1].outcome == "":
            self.history[-1].outcome = outcome
        self.wake_reason = outcome
        self.action = None

    def _interrupt_reason(self, action: Action, new_places: list["Place"]) -> str | None:
        reasons: list[str] = []
        for p in new_places:
            if p.kind == "npc":
                reasons.append(f"met someone new: {p.id} ({p.label})")
        reasons.extend(self.director.alerts)
        if action.ticks >= action.max_ticks:
            reasons.append(f"'{action.name}' took too long")
        return "; ".join(reasons) or None

    def _charge_upkeep(self, world: "CityWorld") -> None:
        hero = world.hero
        if hero.debt <= 0:
            return
        upkeep = min(UPKEEP_CAP, UPKEEP_BASE + UPKEEP_PER_DAY * world.day)
        if hero.nuyen >= upkeep:
            hero.nuyen -= upkeep
            hero.evicted = False
            world.log(f"Оренда й рахунки Насипу: -{upkeep}¥.", "info")
            return
        shortfall = upkeep - hero.nuyen
        hero.nuyen = 0
        hero.debt += shortfall
        hero.evicted = True
        world.log(f"Не вистачило на оренду: {shortfall}¥ додано до боргу. Хазяїн погрожує виселенням.",
                  "danger")

    def _check_installment(self, world: "CityWorld") -> None:
        hero = world.hero
        paid = self._debt_baseline - hero.debt
        self._debt_baseline = hero.debt
        self._next_installment = world.tick + INSTALLMENT_TICKS
        if paid >= INSTALLMENT_MIN:
            world.delinquent = False
            return
        world.delinquent = True
        self._spawn_collector(world)
        world.log(f"Термін внеску минув, а погашено лише {max(0, paid)}¥ з потрібних "
                 f"{INSTALLMENT_MIN}¥ - корпорація шле колектора.", "danger")

    def _spawn_collector(self, world: "CityWorld") -> None:
        level = world.levels[HOME_DISTRICT]
        if any(n.role == "collector" for n in level.npcs):
            return
        npc = NPC(f"collector_{HOME_DISTRICT}", "Колектор", random_race(world.rng), "collector",
                  level.arrival, "холоднокровний вибивач боргів корпорації", hostile=True)
        level.npcs.append(npc)

    def _ambient_hazards(self, world: "CityWorld") -> None:
        hero = world.hero
        if not hero.alive:
            return
        for npc in world.level.npcs:
            if npc.role == "collector" and npc.hostile:
                if (chebyshev(hero.pos, npc.pos) <= 1
                        and world.tick - npc.last_hit >= AMBUSH_COOLDOWN):
                    dmg = world.rng.uniform(*COLLECTOR_DAMAGE)
                    hero.take_damage(dmg, "напад колектора боргів")
                    npc.last_hit = world.tick
                    world.log(f"Колектор наздогнав: -{dmg:.0f} hp. Заплати борг, щоб він відчепився.",
                             "danger")
            elif npc.role == "ganger" and hero.reputation.get("gangs", 0.0) <= HOSTILE_REP_THRESHOLD:
                if (chebyshev(hero.pos, npc.pos) <= 1
                        and world.tick - npc.last_hit >= AMBUSH_COOLDOWN):
                    dmg = world.rng.uniform(*GANGER_AMBUSH_DAMAGE)
                    hero.take_damage(dmg, f"засідка банди ({npc.name})")
                    npc.last_hit = world.tick
                    world.log(f"Банда {npc.name} тебе не забула: -{dmg:.0f} hp. Твоя репутація серед "
                             "банд надто низька.", "danger")
