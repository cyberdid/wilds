"""Director-7: a deterministic storyteller (no LLM calls).

It measures the survivor's tension each tick and paces events the way
RimWorld's storytellers and Left 4 Dead's AI Director do: quiet build-up,
a telegraphed peak, then a guaranteed breather. Every event is announced
ahead of time so a death feels earned, not random.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .tiles import Tile
from .world import Pos, TICKS_PER_DAY, chebyshev, direction_name

if TYPE_CHECKING:
    from .world import World

GRACE_TICKS = TICKS_PER_DAY + 8 * 60  # nothing happens before sol 2, 08:00
MAX_CALM = 3 * TICKS_PER_DAY  # a peak is forced after this much calm
RELAX_AFTER_DAMAGE = 40  # hp lost within the window that triggers a breather
DAMAGE_WINDOW = 90
UNSAFE_FOR_IMPACT = (Tile.POD, Tile.WRECK, Tile.CRASH, Tile.WATER, Tile.ROCK)
# stage: multi-axis tension - a behavioural loop (the same action over and over) reads as
# low threat/hazard/need-deficit, so a purely-survival tension score would never notice it;
# folding 1-entropy in as its own "novelty" term lets a boring-but-safe stretch still raise
# tension enough to eventually force a peak, closing the loop on metrics.Metrics that were
# computed every tick but never fed back into anything
CRITICAL_HP = 25.0  # never force a scheduled peak while this fragile - avoid a death spiral
CRITICAL_NEED = 20.0


@dataclass
class Event:
    kind: str  # dust_storm | orbital_debris | hound_pack | pod_fault | distress_signal
    warn_at: int
    starts_at: int
    ends_at: int
    stage: str = "warning"  # warning | active | done
    data: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return EVENT_NAMES[self.kind]


EVENT_NAMES = {
    "dust_storm": "пилова буря",
    "orbital_debris": "падіння орбітальних уламків",
    "hound_pack": "зграя ксенопсів",
    "pod_fault": "збій систем капсули",
    "distress_signal": "сигнал SOS",
}


class Director:
    def __init__(self) -> None:
        self.tension = 0.0
        self.calm_ticks = 0
        self.relax_until = 0
        self.events: list[Event] = []
        self._hp: deque[tuple[int, float]] = deque()
        self.alerts: list[str] = []  # new this tick; the sim turns them into interrupts
        self.history: list[str] = []

    # --- queries ----------------------------------------------------------
    @property
    def current(self) -> Event | None:
        return next((e for e in self.events if e.stage != "done"), None)

    def active(self, kind: str) -> bool:
        return any(e.kind == kind and e.stage == "active" for e in self.events)

    @property
    def storm_active(self) -> bool:
        return self.active("dust_storm")

    def relaxing(self, tick: int) -> bool:
        return tick < self.relax_until

    def phase(self, tick: int) -> str:
        ev = self.current
        if ev and ev.stage == "active":
            return "пік"
        if ev:
            return "наростання"
        if self.relaxing(tick):
            return "перепочинок"
        return "затишшя"

    def warnings(self, world: "World") -> list[str]:
        """Human-readable lines about upcoming/active events for the LLM."""
        out = []
        for e in self.events:
            if e.stage == "done":
                continue
            left = e.starts_at - world.tick
            if e.stage == "warning":
                out.append(f"WARNING: {EVENT_HINTS[e.kind]} Expected in ~{max(left, 0)} min.{_where(world, e)}")
            else:
                out.append(f"ACTIVE: {EVENT_ACTIVE[e.kind]}{_where(world, e)}")
        return out

    def banner(self, world: "World") -> str:
        """Short Ukrainian status for the viewer."""
        e = self.current
        if e is None:
            return ""
        if e.stage == "warning":
            return f"⚠ {e.name}: за ~{max(0, e.starts_at - world.tick)} хв"
        return f"‼ {e.name}!"

    # --- tick ---------------------------------------------------------------
    def update(self, world: "World", entropy: float = 1.0) -> None:
        self.alerts = []
        hero = world.hero
        self._measure(world, entropy)
        self._hp.append((world.tick, hero.hp))
        while self._hp and self._hp[0][0] < world.tick - DAMAGE_WINDOW:
            self._hp.popleft()
        if max(h for _, h in self._hp) - hero.hp >= RELAX_AFTER_DAMAGE and not self.relaxing(world.tick):
            self._relax(world, 300, "Після важкого бою Тау-7 ніби затихає.")

        for e in self.events:
            if e.stage == "warning" and world.tick >= e.starts_at:
                self._start(world, e)
            elif e.stage == "active" and world.tick >= e.ends_at:
                self._end(world, e)

        if self.current or self.relaxing(world.tick) or world.tick < GRACE_TICKS:
            return
        critical = (hero.hp < CRITICAL_HP
                   or min(hero.satiety, hero.hydration, hero.warmth, hero.energy) < CRITICAL_NEED)
        self.calm_ticks += 1 if self.tension < 0.3 else 0
        chance = min(1.0, self.calm_ticks / 720) / 600
        if not critical and (self.calm_ticks >= MAX_CALM or world.rng.random() < chance):
            self._schedule(world)

    def _measure(self, world: "World", entropy: float = 1.0) -> None:
        hero = world.hero
        worst_need = min(hero.satiety, hero.hydration, hero.warmth, hero.energy)
        threat = 0.0
        for c in world.level.creatures:
            if c.kind.hostile and c.pos in hero.visible:
                threat = max(threat, 1 - chebyshev(c.pos, hero.pos) / 10)
        hazard = 1.0 if self.current and self.current.stage == "active" else 0.0
        novelty = 1 - entropy  # a long behavioural loop reads as its own kind of danger
        self.tension = (0.30 * (1 - hero.hp / 100) + 0.25 * (1 - worst_need / 100)
                        + 0.15 * threat + 0.15 * hazard + 0.15 * novelty)

    def _relax(self, world: "World", ticks: int, text: str) -> None:
        self.relax_until = world.tick + ticks
        self.calm_ticks = 0
        world.log(text, "event")

    # --- scheduling -----------------------------------------------------------
    def _schedule(self, world: "World") -> None:
        options: list[tuple[str, float]] = [("dust_storm", 1.0), ("orbital_debris", 1.0)]
        if 14 <= world.hour <= 21:
            options.append(("hound_pack", 1.2))
        pod = world.pod
        if pod and not pod.fault and pod.power > 5:
            options.append(("pod_fault", 0.6))
        if world.companion is None and world.day >= 3:
            options.append(("distress_signal", 3.0))
        recent = self.history[-2:]
        options = [(k, w * (0.3 if k in recent else 1.0)) for k, w in options]
        kind = _weighted(world, options)
        tick = world.tick
        warn, dur = {
            "dust_storm": (180, world.rng.randint(180, 300)),
            "orbital_debris": (60, 1),
            "hound_pack": (max(120, (20 - world.hour) * 60), 1),
            "pod_fault": (90, 1),
            "distress_signal": (45, 1),
        }[kind]
        event = Event(kind, tick, tick + warn, tick + warn + dur)
        if kind == "orbital_debris":
            spot = _impact_spot(world)
            if spot is None:
                return
            event.data["pos"] = spot
        if kind == "distress_signal":
            spot = _crash_spot(world)
            if spot is None:
                return
            event.data["pos"] = spot
        self.events.append(event)
        self.history.append(kind)
        self.calm_ticks = 0
        text = EVENT_TELEGRAPH[kind]
        world.log(text + _where(world, event), "event")
        self.alerts.append("WARNING: " + EVENT_HINTS[kind] + _where(world, event))

    def _start(self, world: "World", e: Event) -> None:
        from .companion import Companion
        from .creatures import spawn

        e.stage = "active"
        hero = world.hero
        surface = world.surface
        if e.kind == "dust_storm":
            world.log("Пилова буря накрила долину! Видимість - кілька метрів, холоднішає.", "danger")
        elif e.kind == "orbital_debris":
            pos = e.data["pos"]
            hit = hero.level_id == "surface" and chebyshev(hero.pos, pos) <= 1
            for p in [(pos[0] + dx, pos[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]:
                if surface.in_bounds(p) and surface.tile(p) not in UNSAFE_FOR_IMPACT:
                    surface.set_tile(p, Tile.DUST)
                    surface.heaters.pop(p, None)
            surface.creatures = [c for c in surface.creatures if chebyshev(c.pos, pos) > 1]
            loot = ["alloy", "alloy"] + (["power_cell"] if world.rng.random() < 0.4 else [])
            surface.items.setdefault(pos, []).extend(loot)
            hero.add_place("debris", "surface", pos, "місце падіння уламків")
            if hit:
                hero.take_damage(35, "орбітальний уламок")
                world.log("Уламок впав прямо поруч! -35 HP", "danger")
            else:
                world.log("Гуркіт! Уламки корабля врізались у поверхню. Там може бути сплав.", "event")
        elif e.kind == "hound_pack":
            placed = 0
            for _ in range(80):
                if placed >= 3:
                    break
                p = (world.rng.randrange(surface.width), world.rng.randrange(surface.height))
                d = chebyshev(p, hero.pos)
                if surface.passable(p) and not surface.creature_at(p) and 10 <= d <= 16:
                    wolf = spawn("hound", p, extra=True)
                    if hero.level_id == "surface":
                        wolf.home = hero.pos
                    surface.creatures.append(wolf)
                    placed += 1
            world.log("Зграя ксенопсів вийшла на полювання!", "danger")
        elif e.kind == "pod_fault" and world.pod:
            world.pod.fault = True
            world.pod.heater_on = False
            world.log("Коротке замикання! Обігрів і сонячні панелі капсули не працюють (потрібна руда для ремонту).",
                      "danger")
        elif e.kind == "distress_signal":
            pos = e.data["pos"]
            surface.set_tile(pos, Tile.CRASH)
            world.companion = Companion(pos=pos)
            hero.add_place("crash_site", "surface", pos, "друга капсула (там хтось живий!)")
            world.log("Друга капсула впала неподалік! Хтось усередині подає сигнали.", "event")
        self.alerts.append(f"EVENT STARTED: {EVENT_ACTIVE[e.kind]}{_where(world, e)}")
        if e.ends_at <= e.starts_at + 1:
            self._end(world, e, quiet=True)

    def _end(self, world: "World", e: Event, quiet: bool = False) -> None:
        e.stage = "done"
        if e.kind == "dust_storm":
            world.log("Буря вщухла.", "event")
        self.relax_until = world.tick + world.rng.randint(180, 300)
        self.calm_ticks = 0
        if not quiet:
            world.log("Настає затишшя.", "event")


EVENT_TELEGRAPH = {
    "dust_storm": "Барометр падає, на обрії здіймається руда стіна пилу.",
    "orbital_debris": "Спалахи в небі: уламки корабля входять в атмосферу.",
    "hound_pack": "Далеко в темряві лунає виття - багато голосів.",
    "pod_fault": "У капсулі клацає реле і пахне паленою ізоляцією.",
    "distress_signal": "Приймач капсули ловить слабкий сигнал SOS!",
}
EVENT_HINTS = {
    "dust_storm": "a dust storm is coming (sight 2 tiles, strong cold; shelter in the pod, a dome or by a heater).",
    "orbital_debris": "orbital debris will crash (3x3 impact, 35 damage if you stand there; alloy will lie there after).",
    "hound_pack": "a pack of xeno-hounds is gathering to hunt you tonight (stay near a heater or be armed).",
    "pod_fault": "the pod electronics are about to short-circuit (heater and solar will stop until `pod repair`).",
    "distress_signal": "a second escape pod is falling nearby - someone may be alive inside.",
}
EVENT_ACTIVE = {
    "dust_storm": "dust storm - you can barely see, it is freezing",
    "orbital_debris": "debris has fallen",
    "hound_pack": "a hound pack is hunting",
    "pod_fault": "pod fault: heater and solar are dead until `pod repair`",
    "distress_signal": "a second pod crashed; go to crash_site to rescue the survivor",
}


def _where(world: "World", e: Event) -> str:
    pos = e.data.get("pos")
    if not pos:
        return ""
    hero = world.hero
    if hero.level_id != "surface":
        return f" Location: ({pos[0]},{pos[1]})."
    return f" Location: ({pos[0]},{pos[1]}), {chebyshev(pos, hero.pos)} tiles {direction_name(hero.pos, pos)}."


def _weighted(world: "World", options: list[tuple[str, float]]) -> str:
    total = sum(w for _, w in options)
    r = world.rng.random() * total
    for k, w in options:
        r -= w
        if r <= 0:
            return k
    return options[-1][0]


def _impact_spot(world: "World") -> Pos | None:
    surface = world.surface
    center = world.hero.pos if world.hero.level_id == "surface" else (world.pod.pos if world.pod else None)
    if center is None:
        return None
    for _ in range(60):
        p = (center[0] + world.rng.randint(-15, 15), center[1] + world.rng.randint(-15, 15))
        if (surface.in_bounds(p) and surface.passable(p) and surface.tile(p) not in UNSAFE_FOR_IMPACT
                and chebyshev(p, center) >= 4
                and all(surface.tile(q) is not Tile.POD for q in surface.neighbors(p))):
            return p
    return None


def _crash_spot(world: "World") -> Pos | None:
    from .worldgen import largest_region

    surface = world.surface
    anchor = world.pod.pos if world.pod else world.hero.pos
    region = largest_region(surface)
    options = sorted(p for p in region if surface.tile(p) is Tile.MOSS
                     and 12 <= chebyshev(p, anchor) <= 25 and not surface.creature_at(p))
    return world.rng.choice(options) if options else None
