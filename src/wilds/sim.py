"""The simulation loop: advances the world one tick at a time and decides
when the hero's brain needs to be consulted again (a decision, the nightly
diary, or a conversation with the other survivor)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from .actions import ACTION_HELP, Action, Rest, Status, make_action, visible_creatures
from .creatures import creature_turn, spawn
from .hero import FLARE_TICKS, NEEDS
from .metrics import Metrics
from .tiles import Tile
from .world import TICKS_PER_DAY, World, chebyshev, direction_name

if TYPE_CHECKING:
    from .hero import Place

LOW = 25.0
LOW_HP = 40.0
MAX_HOUNDS = 6
ALERT_COOLDOWN = 120  # ticks before the same creature can interrupt again
COMBAT = ("fight", "hunt", "flee")
SHELTERS = (Tile.DOME, Tile.POD)
DEATH_CAUSES = {
    "satiety": "голод",
    "hydration": "спрага",
    "warmth": "холод",
    "energy": "виснаження",
}


@dataclass
class Decision:
    action: str
    target: str = ""
    thought: str = ""
    note: str = ""  # legacy, ignored: long-term memory now comes from the nightly diary


@dataclass
class Reflection:
    diary: str
    trait: str = ""
    goal: str = ""


@dataclass
class Conversation:
    lines: list[tuple[str, str]] = field(default_factory=list)  # (speaker, text), speaker: hero|companion
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

    def decide(self, sim: "Simulation") -> Decision: ...

    def reflect(self, sim: "Simulation") -> Reflection: ...

    def converse(self, sim: "Simulation") -> Conversation: ...


class Simulation:
    def __init__(self, world: World) -> None:
        self.world = world
        self.action: Action | None = None
        self.history: list[HistoryEntry] = []
        self.wake_reason = "your escape pod just crash-landed on an unknown planet"
        self.thought = ""
        self.decisions = 0
        self.pending_reflection: int | None = None  # sol to write the diary about
        self.pending_conversation = False
        self.diary_path = None  # set by the front-end to also append entries to a file
        self.legacy_dir = None  # set by the front-end to export a cyberpunk-chapter legacy on rescue
        self.brain_name = "hero"
        self.legacy_path = None  # filled in once written
        self.metrics = Metrics()
        self._invalid_streak = 0
        self._alerted: dict[int, int] = {}  # creature id -> last tick it was seen close
        self._low_flags: set[str] = set()
        self._was_night = world.is_night
        self._day = world.day

    def __setstate__(self, state: dict) -> None:
        """Loading a save from an older code version: backfill attributes that
        did not exist yet when it was written, instead of crashing on first use."""
        self.__dict__.update(state)
        self.__dict__.setdefault("legacy_dir", None)
        self.__dict__.setdefault("brain_name", "hero")
        self.__dict__.setdefault("legacy_path", None)

    # --- what the front-end should do next ----------------------------------
    @property
    def over(self) -> bool:
        hero = self.world.hero
        return not hero.alive or hero.rescued

    @property
    def needs_decision(self) -> bool:
        return not self.over and self.action is None

    @property
    def pending(self) -> str | None:
        """'reflect' | 'converse' | 'decide' | None - the next brain call needed."""
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
        """Run whichever brain call is pending (blocking)."""
        kind = self.pending
        if kind == "reflect":
            self.apply_reflection(brain.reflect(self))
        elif kind == "converse":
            self.apply_conversation(brain.converse(self))
        elif kind == "decide":
            self.apply(brain.decide(self))

    # --- decisions --------------------------------------------------------
    def apply(self, decision: Decision) -> str | None:
        """Start the decided action. Returns an error message if rejected."""
        world = self.world
        hero = world.hero
        self.decisions += 1
        self.thought = decision.thought
        # the brain has just seen these; only new drops should interrupt later
        self._low_flags = {n for n in (*NEEDS, "hp") if hero.need(n) < (LOW_HP if n == "hp" else LOW)}
        entry = HistoryEntry(world.tick, decision.action, decision.target, decision.thought)
        self.history.append(entry)
        del self.history[:-30]
        self.metrics.on_decision(decision)
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
            self.metrics.rejections += 1
            self._invalid_streak += 1
            if self._invalid_streak < 3:
                return error
            action = Rest("15")
            action.start(world)
            world.log("(розгубився і стоїть на місці)", "info")
        self._invalid_streak = 0
        self.action = action
        return error

    def apply_reflection(self, r: Reflection) -> None:
        world = self.world
        hero = world.hero
        sol = self.pending_reflection or world.day - 1
        self.pending_reflection = None
        text = r.diary.strip()
        if not text:
            return
        hero.diary.append((sol, text))
        remember(hero.traits, r.trait, limit=5)
        if r.goal.strip():
            hero.goal = r.goal.strip()[:160]
        world.log(f"Щоденник, сол {sol}: {text}", "diary")
        if r.trait.strip():
            world.log(f"Нова риса: {r.trait.strip()}", "diary")
        if hero.goal:
            world.log(f"Мета на завтра: {hero.goal}", "diary")
        if self.diary_path:
            with open(self.diary_path, "a", encoding="utf-8") as f:
                f.write(f"## Сол {sol}\n\n{text}\n\n")
                if r.trait.strip():
                    f.write(f"*Риса:* {r.trait.strip()}  \n")
                f.write(f"*Мета:* {hero.goal}\n\n")

    def apply_conversation(self, c: Conversation) -> None:
        world = self.world
        comp = world.companion
        self.pending_conversation = False
        if comp is None:
            return
        comp.last_talk = world.tick
        comp.talk_requested = False
        for speaker, text in c.lines[:6]:
            who = comp.name if speaker == "companion" else world.hero.name
            world.log(f"{who}: «{text.strip()}»", "talk")
            if speaker == "companion":
                comp.last_line = text.strip()
        comp.adjust(max(-0.15, min(0.15, c.trust_delta)), max(-0.15, min(0.15, c.affinity_delta)))
        comp.request = c.request.strip()[:160]
        self.metrics.conversations += 1

    def run(self, brain: Brain, ticks: int) -> None:
        """Headless loop (tests, benchmarks)."""
        for _ in range(ticks):
            if self.over:
                return
            for _guard in range(6):  # diary + talk + up to 3 rejected decisions + fallback
                if not self.pending:
                    break
                self.consult(brain)
            if self.action is not None:
                self.tick()

    # --- tick -------------------------------------------------------------
    def tick(self) -> None:
        world = self.world
        hero = world.hero
        action = self.action
        if action is None or self.over:
            return
        hero.hurt_this_tick = 0.0
        status = action.step(world)
        action.ticks += 1
        self._update_world()
        world.tick += 1
        new_places = hero.observe(world)
        self.metrics.on_tick(world)
        if world.day != self._day:
            self._day = world.day
            self.pending_reflection = world.day - 1
        comp = world.companion
        if comp and comp.alive and (comp.talk_requested or comp.wants_to_talk(world)):
            self.pending_conversation = True

        if not hero.alive:
            self._die()
            return
        if self._check_rescue():
            return
        if status is not Status.RUNNING:
            self._finish(f"{status.value}: {action.result}")
            self._scan_hostiles()
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

    def _scan_hostiles(self) -> set[int]:
        """Hostiles close enough to matter that we have not warned about lately."""
        world = self.world
        hero = world.hero
        new: set[int] = set()
        for c in visible_creatures(world):
            if not c.kind.hostile:
                continue
            danger_range = c.kind.sight + (5 if world.is_night and not world.level.dark else 2)
            if chebyshev(c.pos, hero.pos) > danger_range:
                continue
            if world.tick - self._alerted.get(c.id, -10_000) > ALERT_COOLDOWN:
                new.add(c.id)
            self._alerted[c.id] = world.tick
        return new

    def _interrupt_reason(self, action: Action, new_places: list["Place"]) -> str | None:
        world = self.world
        hero = world.hero
        name = action.effective_name
        reasons: list[str] = []

        new_hostiles = self._scan_hostiles()
        if new_hostiles and name not in COMBAT:
            c = next(c for c in world.level.creatures if c.id in new_hostiles)
            reasons.append(f"a {c.kind.key} appeared {chebyshev(c.pos, hero.pos)} tiles "
                           f"{direction_name(hero.pos, c.pos)}")
        if hero.hurt_this_tick > 0 and name not in COMBAT:
            reasons.append(f"you were hurt (-{hero.hurt_this_tick:.0f} hp)")

        for need in (*NEEDS, "hp"):
            value = hero.need(need)
            limit = LOW_HP if need == "hp" else LOW
            if value < limit and need not in self._low_flags:
                self._low_flags.add(need)
                if not (name == "sleep" and need == "energy"):
                    reasons.append(f"{need} is low ({value:.0f})")
            elif value > limit + 10:
                self._low_flags.discard(need)

        if world.is_night != self._was_night:
            self._was_night = world.is_night
            if name != "sleep" and action.name != "routine" and not world.level.dark:
                reasons.append("night is falling" if world.is_night else "dawn has come")

        if name in ("explore", "go_to"):
            for p in new_places:
                if p.kind == "wreck":
                    reasons.append(f"discovered {p.id}: {p.label}")

        if world.director:
            reasons.extend(world.director.alerts)

        if action.ticks >= action.max_ticks:
            reasons.append(f"'{action.name}' took too long")
        return "; ".join(reasons) or None

    # --- world update -----------------------------------------------------
    def _update_world(self) -> None:
        world = self.world
        hero = world.hero
        level = world.level
        director = world.director
        storm = bool(director and director.storm_active)
        sheltered = level.tile(hero.pos) in SHELTERS

        # needs
        slow = 0.5 if hero.sleeping else 1.0
        hero.change("satiety", -0.055 * slow)
        hero.change("hydration", -0.08 * slow)
        if hero.sleeping:
            hero.change("energy", 0.4 if sheltered else 0.3)
        else:
            hero.change("energy", -0.045)
        if level.near_heat(hero.pos, 2):
            warmth = 0.6
        elif level.dark:
            warmth = -0.03
        elif world.is_night:
            warmth = -0.02 if sheltered else -0.13
        else:
            warmth = 0.15
        if storm and not level.dark and not sheltered and not level.near_heat(hero.pos, 2):
            warmth -= 0.2
        hero.change("warmth", warmth)
        starving = [n for n in NEEDS if hero.need(n) <= 0]
        for n in starving:
            hero.take_damage(0.15, DEATH_CAUSES[n])
            hero.hurt_this_tick -= 0.15  # needs are not an "attack"
        if not starving and all(hero.need(n) > 40 for n in NEEDS):
            hero.change("hp", 0.08 if hero.sleeping else 0.03)

        # light
        needs_light = level.dark or world.is_night
        if needs_light and hero.inventory["headlamp"] <= 0:
            if hero.flare_ticks > 0:
                hero.flare_ticks -= 1
                if hero.flare_ticks == 0:
                    world.log("Фальшфеєр догорів", "info")
            if hero.flare_ticks == 0 and hero.inventory["flare"] > 0:
                hero.inventory["flare"] -= 1
                hero.flare_ticks = FLARE_TICKS
                world.log("Запалив фальшфеєр", "info")

        # heaters and regrowth (all levels)
        for lv in world.levels.values():
            for pos in list(lv.heaters):
                lv.heaters[pos] -= 1
                if lv.heaters[pos] <= 0:
                    del lv.heaters[pos]
                    lv.set_tile(pos, Tile.HEATER_OFF)
                    for p in hero.places.values():
                        if p.kind == "camp" and p.pos == pos and p.level_id == lv.id:
                            p.label = "розряджений обігрівач"
                    if lv is level:
                        world.log("Обігрівач розрядився", "info")
            for pos, (when, tile) in list(lv.regrow.items()):
                if world.tick >= when:
                    del lv.regrow[pos]
                    if lv.tile(pos) in (Tile.STALK, Tile.SPORE_BUSH_EMPTY):
                        lv.set_tile(pos, tile)

        # base, storyteller, the other survivor
        if world.pod:
            world.pod.update(world, storm)
        if director:
            director.update(world, self.metrics.action_diversity(len(ACTION_HELP)))
        if world.companion:
            world.companion.update(world)

        # creatures
        for c in list(level.creatures):
            creature_turn(world, level, c)
        if world.tick % 30 == 0:
            self._population()

    def _population(self) -> None:
        world = self.world
        surface = world.surface
        hero = world.hero
        on_surface = hero.level_id == "surface"
        hidden = (lambda p: p not in hero.visible) if on_surface else (lambda p: True)
        calm = world.director is not None and world.director.relaxing(world.tick)
        if world.is_night and not calm:
            hounds = [c for c in surface.creatures if c.kind.key == "hound"]
            if len(hounds) < MAX_HOUNDS and world.rng.random() < 0.5:
                spot = self._far_spot((Tile.FLORA, Tile.MOSS), 15)
                if spot:
                    surface.creatures.append(spawn("hound", spot, extra=True))
        elif not world.is_night:
            surface.creatures = [c for c in surface.creatures if not (c.extra and hidden(c.pos))]
        hoppers = sum(1 for c in surface.creatures if c.kind.key == "hopper")
        if hoppers < 5 and world.rng.random() < 0.1:
            spot = self._far_spot((Tile.MOSS,), 12)
            if spot:
                surface.creatures.append(spawn("hopper", spot))

    def _far_spot(self, tiles: tuple[Tile, ...], min_dist: int):
        world = self.world
        surface = world.surface
        hero = world.hero
        for _ in range(40):
            p = (world.rng.randrange(surface.width), world.rng.randrange(surface.height))
            if surface.tile(p) not in tiles or surface.creature_at(p):
                continue
            if hero.level_id == "surface" and (chebyshev(p, hero.pos) < min_dist or p in hero.visible):
                continue
            return p
        return None

    # --- endings ------------------------------------------------------------
    def _check_rescue(self) -> bool:
        world = self.world
        pod = world.pod
        if not pod or pod.rescue_at is None or world.tick < pod.rescue_at:
            return False
        hero = world.hero
        hero.rescued = True
        hero.sleeping = False
        comp = world.companion
        with_her = f" разом із {comp.name}" if comp and comp.joined else ""
        world.log(f"Рятувальний шатл сів біля капсули! {hero.name} покидає Тау-7{with_her}. "
                  f"Прожито до: {world.clock()}", "victory")
        if self.legacy_dir is not None:
            from .legacy_export import write_legacy

            self.legacy_path = write_legacy(world, self.brain_name, self.legacy_dir)
            world.log(f"Записано спадок для наступної глави: {self.legacy_path}", "event")
        if self.action:
            self._finish("rescued")
        self.action = None
        return True

    def _die(self) -> None:
        world = self.world
        hero = world.hero
        level = world.level
        cause = hero.cause_of_death or "невідомо"
        if level.tile(hero.pos) not in (Tile.WRECK, Tile.HATCH, Tile.POD, Tile.CRASH):
            level.set_tile(hero.pos, Tile.GRAVE)
        world.log(f"{hero.name} загинув. Причина: {cause}. Прожив до: {world.clock()}", "death")
        if self.action:
            self._finish(f"died: {cause}")
        self.action = None


def sol_events(world: World, sol: int) -> list[str]:
    """Log lines (without the hero's own thoughts) that happened during a sol."""
    start, end = (sol - 1) * TICKS_PER_DAY, sol * TICKS_PER_DAY
    return [f"[{e.tick // 60 % 24:02d}:{e.tick % 60:02d}] {e.text}" for e in world.events
            if start <= e.tick < end and e.kind not in ("brain", "diary")]


def _words(text: str) -> set[str]:
    return {w.strip(".,!?-—:;()«»").lower() for w in text.split() if len(w) > 3}


def remember(notes: list[str], note: str, limit: int = 6) -> None:
    """Keep a short list of distinct notes; a similar new note replaces the old one."""
    note = note.strip()[:160]
    if not note:
        return
    words = _words(note)
    for i, old in enumerate(notes):
        other = _words(old)
        if words and other and len(words & other) / min(len(words), len(other)) > 0.5:
            del notes[i]
            break
    notes.append(note)
    del notes[:-limit]
