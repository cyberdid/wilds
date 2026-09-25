"""The action menu the brain chooses from.

Each action validates itself in ``start`` and then advances one tick per
``step`` call until it reports DONE or FAILED. Actions never talk to the LLM.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Callable

from .creatures import Creature, hero_attack
from .pathfinding import find_path, frontier
from .pod import BEACON_PARTS, CELL_POWER, RESCUE_DELAY, TRANSMIT_POWER, TRANSMIT_TICKS
from .tiles import Tile
from .world import DIRECTIONS, ITEMS, Pos, chebyshev

if TYPE_CHECKING:
    from .world import World


class Status(Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


RECIPES: dict[str, tuple[dict[str, int], int]] = {
    "blade": ({"fiber": 2, "ore": 1}, 15),
    "flare": ({"fiber": 1}, 5),
}
STRUCTURES: dict[str, tuple[dict[str, int], int]] = {
    "heater": ({"fiber": 3, "ore": 2}, 10),
    "dome": ({"fiber": 6}, 40),
}
HEATER_TICKS = 8 * 60
BUILDABLE = (Tile.MOSS, Tile.DUST, Tile.STALK, Tile.SPORE_BUSH_EMPTY, Tile.HEATER_OFF)
FOOD_PREFERENCE = ["cooked_meat", "ration", "spores", "raw_meat"]


# --- world helpers used by actions ---------------------------------------------


def move_hero(world: "World", p: Pos) -> None:
    hero = world.hero
    hero.pos = p
    pickup(world)


def pickup(world: "World") -> None:
    hero = world.hero
    level = world.level
    items = level.items.pop(hero.pos, None)
    if not items:
        return
    for item in items:
        hero.inventory[item] += 1
        kind = "good"
        text = f"Підібрав: {ITEMS[item].name}"
        if item == "artifact":
            text = f"Знайшов АРТЕФАКТ ПРЕДТЕЧ! ({level.name})"
        world.log(text, kind)
    hero.seen_items.get(level.id, {}).pop(hero.pos, None)


def change_level(world: "World", level_id: str, pos: Pos) -> None:
    hero = world.hero
    hero.level_id = level_id
    hero.pos = pos
    hero.observe(world)


def touching(known: dict[Pos, Tile], p: Pos, tiles: tuple[Tile, ...], include_self: bool = True) -> Pos | None:
    """Return a remembered tile of the given types adjacent to (or at) p."""
    candidates = [p] if include_self else []
    candidates += [(p[0] + dx, p[1] + dy) for dx, dy in DIRECTIONS.values()]
    for q in candidates:
        if known.get(q) in tiles:
            return q
    return None


def visible_creatures(world: "World") -> list[Creature]:
    hero = world.hero
    return [c for c in world.level.creatures if c.hp > 0 and c.pos in hero.visible]


# --- base ----------------------------------------------------------------------


class Action:
    name = ""
    max_ticks = 300

    def __init__(self, target: str = "") -> None:
        self.target = (target or "").strip()
        self.ticks = 0
        self.result = ""
        self._path: list[Pos] = []

    def label(self) -> str:
        return f"{self.name} {self.target}".strip()

    @property
    def effective_name(self) -> str:
        """The action actually running (a routine reports its current step)."""
        return self.name

    def start(self, world: "World") -> str | None:
        """Validate; return an error message to reject the action."""
        return None

    def step(self, world: "World") -> Status:
        raise NotImplementedError

    def cancel(self, world: "World") -> None:
        world.hero.sleeping = False

    # helpers
    def done(self, msg: str) -> Status:
        self.result = msg
        return Status.DONE

    def fail(self, msg: str) -> Status:
        self.result = msg
        return Status.FAILED

    def walk(self, world: "World", goal: Callable[[Pos], bool], replan: bool = False) -> str:
        """Advance one step toward the nearest goal tile: arrived | moved | blocked."""
        hero = world.hero
        level = world.level
        if goal(hero.pos):
            self._path = []
            return "arrived"
        nxt = self._path[0] if self._path else None
        stale = (
            replan
            or nxt is None
            or chebyshev(nxt, hero.pos) != 1
            or not level.passable(nxt)
            or level.creature_at(nxt) is not None
            or not goal(self._path[-1])
        )
        if stale:
            blocked = {c.pos for c in level.creatures if c.hp > 0}
            path = find_path(level, hero.known(level.id), hero.pos, goal, blocked)
            if path is None:
                return "blocked"
            self._path = path
            if not path:
                return "arrived"
        move_hero(world, self._path.pop(0))
        return "arrived" if goal(hero.pos) else "moved"


# --- movement ------------------------------------------------------------------


class GoTo(Action):
    name = "go_to"

    def start(self, world: "World") -> str | None:
        hero = world.hero
        place = hero.places.get(self.target)
        if place:
            if place.level_id != hero.level_id:
                return f"{self.target} is on another level ({place.level_id}); use enter/leave first"
            self.dest = place.pos
            self.dest_name = place.label
            return None
        try:
            x, y = (int(v) for v in self.target.replace(" ", "").split(","))
        except ValueError:
            return f"unknown place '{self.target}'; use a place id from the list or 'x,y'"
        if not world.level.in_bounds((x, y)):
            return f"({x},{y}) is outside the map"
        self.dest = (x, y)
        self.dest_name = f"({x},{y})"
        return None

    def label(self) -> str:
        return f"йде до: {self.dest_name}"

    def _goal(self, world: "World") -> Callable[[Pos], bool]:
        dest = self.dest
        if world.level.passable(dest):
            return lambda p: p == dest
        return lambda p: chebyshev(p, dest) <= 1

    def step(self, world: "World") -> Status:
        state = self.walk(world, self._goal(world))
        if state == "arrived":
            return self.done(f"arrived at {self.dest_name}")
        if state == "blocked":
            return self.fail(f"no known path to {self.dest_name}")
        return Status.RUNNING


class Explore(Action):
    """Walk toward the edge of the known map, preferring a direction."""

    name = "explore"
    max_ticks = 90

    def start(self, world: "World") -> str | None:
        direction = self.target.upper() or "ANY"
        if direction != "ANY" and direction not in DIRECTIONS:
            return f"direction must be one of {', '.join(DIRECTIONS)} or 'any'"
        self.direction = direction
        self.known_before = len(world.hero.known(world.level.id))
        self.dest: Pos | None = None
        if not self._pick(world):
            return "everything reachable here is already explored"
        return None

    def _pick(self, world: "World") -> bool:
        hero = world.hero
        edges = frontier(world.level, hero.known(world.level.id), hero.pos)
        edges.pop(hero.pos, None)
        if not edges:
            return False
        if self.direction == "ANY":
            if self.dest is not None:  # keep heading roughly the same way
                hx, hy = hero.pos
                vx, vy = self.dest[0] - hx, self.dest[1] - hy
                self.dest = max(edges, key=lambda p: (p[0] - hx) * vx + (p[1] - hy) * vy - edges[p] * 2)
            else:
                self.dest = min(edges, key=lambda p: (edges[p], world.rng.random()))
        else:
            dx, dy = DIRECTIONS[self.direction]
            hx, hy = hero.pos
            self.dest = max(edges, key=lambda p: ((p[0] - hx) * dx + (p[1] - hy) * dy) * 3 - edges[p])
        self._path = []
        return True

    def label(self) -> str:
        where = "навмання" if self.direction == "ANY" else self.direction
        return f"досліджує: {where}"

    def step(self, world: "World") -> Status:
        hero = world.hero
        dest = self.dest
        known = hero.known(world.level.id)
        new = len(known) - self.known_before
        if self.ticks >= self.max_ticks - 1:
            return self.done(f"explored {self.direction.lower()}, saw {new} new tiles")
        # the chosen edge is no longer an edge once its surroundings are seen
        reached = hero.pos == dest or all(q in known for q in world.level.neighbors(dest))
        if reached and not self._pick(world):
            if new:
                return self.done(f"explored {self.direction.lower()}, saw {new} new tiles")
            return self.fail("everything reachable here is already explored")
        dest = self.dest
        state = self.walk(world, lambda p: p == dest)
        if state == "blocked":
            if not self._pick(world):
                return self.fail("everything reachable here is already explored")
        return Status.RUNNING


# --- gathering -----------------------------------------------------------------


class Gather(Action):
    name = "gather"
    SOURCES = {
        "fiber": (Tile.FLORA,),
        "ore": (Tile.ROCK,),
        "spores": (Tile.SPORE_BUSH,),
        "eel": (Tile.WATER,),
    }
    AMOUNT = {"fiber": 3, "ore": 2, "spores": 3, "eel": 1}
    WORK = {"fiber": 4, "ore": 6, "spores": 2}
    NAMES = {"fiber": "волокно", "ore": "руду", "spores": "спори", "eel": "вугрів"}

    def start(self, world: "World") -> str | None:
        parts = self.target.lower().split()
        if not parts or parts[0] not in self.SOURCES:
            if parts and parts[0] in ITEMS:
                return f"{parts[0]} is an item, not a resource: use loot to pick it up"
            return f"gather target must be one of {', '.join(self.SOURCES)}"
        self.resource = parts[0]
        self.amount = self.AMOUNT[self.resource]
        if len(parts) > 1 and parts[1].isdigit():
            self.amount = max(1, min(int(parts[1]), 10))
        known = world.hero.known(world.level.id)
        if not any(t in self.SOURCES[self.resource] for t in known.values()):
            return f"you don't know where to find {self.resource}; explore first"
        self.got = 0
        self.work = 0
        self.eel_hunting = 0
        return None

    def label(self) -> str:
        return f"збирає: {self.NAMES[self.resource]} ({self.got}/{self.amount})"

    def step(self, world: "World") -> Status:
        hero = world.hero
        level = world.level
        known = hero.known(level.id)
        sources = self.SOURCES[self.resource]
        include_self = self.resource in ("fiber", "spores")
        spot = touching(known, hero.pos, sources, include_self)
        if spot is None or level.tile(spot) not in sources:
            state = self.walk(world, lambda p: touching(known, p, sources, include_self) is not None)
            if state == "blocked":
                return self._finish(f"no reachable {self.resource}")
            return Status.RUNNING
        if self.resource == "eel":
            return self._eel(world)
        self.work += 1
        if self.work < self.WORK[self.resource]:
            return Status.RUNNING
        self.work = 0
        if self.resource == "fiber":
            hero.inventory["fiber"] += 1
            self.got += 1
            if world.rng.random() < 0.35:
                level.set_tile(spot, Tile.STALK)
                level.regrow[spot] = (world.tick + 3 * 24 * 60, Tile.FLORA)
        elif self.resource == "ore":
            hero.inventory["ore"] += 1
            self.got += 1
        elif self.resource == "spores":
            hero.inventory["spores"] += 3
            self.got += 3
            level.set_tile(spot, Tile.SPORE_BUSH_EMPTY)
            level.regrow[spot] = (world.tick + 24 * 60, Tile.SPORE_BUSH)
        known[spot] = level.tile(spot)
        if self.got >= self.amount:
            return self._finish()
        return Status.RUNNING

    def _eel(self, world: "World") -> Status:
        self.eel_hunting += 1
        if world.rng.random() < 0.035:
            world.hero.inventory["raw_meat"] += 1
            self.got += 1
            world.log("Спіймав озерного вугра! +1 сире ксеном'ясо", "good")
            if self.got >= self.amount:
                return self._finish()
        if self.eel_hunting > 120:
            return self._finish("eel are not biting")
        return Status.RUNNING

    def _finish(self, reason: str = "") -> Status:
        msg = f"gathered {self.got} {self.resource}"
        if reason:
            msg += f" ({reason})"
        if self.got:
            return self.done(msg)
        return self.fail(msg)


class Drink(Action):
    name = "drink"

    def label(self) -> str:
        return "п'є воду"

    def start(self, world: "World") -> str | None:
        known = world.hero.known(world.level.id)
        if Tile.WATER not in known.values():
            return "you don't know where water is; explore first"
        return None

    def step(self, world: "World") -> Status:
        hero = world.hero
        known = hero.known(world.level.id)
        if touching(known, hero.pos, (Tile.WATER,), include_self=False) is None:
            state = self.walk(world, lambda p: touching(known, p, (Tile.WATER,), False) is not None)
            if state == "blocked":
                return self.fail("no reachable water")
            return Status.RUNNING
        hero.change("hydration", 8)
        if hero.hydration >= 98:
            return self.done("drank until full")
        return Status.RUNNING


# --- items ---------------------------------------------------------------------


class Eat(Action):
    name = "eat"

    def start(self, world: "World") -> str | None:
        inv = world.hero.inventory
        item = self.target.lower() or next((f for f in FOOD_PREFERENCE if inv[f] > 0), "")
        if not item:
            return "you have no food"
        if item not in ITEMS or not ITEMS[item].food:
            return f"{item} is not food"
        if inv[item] <= 0:
            return f"you have no {item}"
        self.item = item
        return None

    def label(self) -> str:
        return f"їсть: {ITEMS[self.item].name}"

    def step(self, world: "World") -> Status:
        hero = world.hero
        info = ITEMS[self.item]
        hero.inventory[self.item] -= 1
        hero.change("satiety", info.food)
        if info.heal > 0:
            hero.change("hp", info.heal)
        elif info.heal < 0:
            hero.take_damage(-info.heal, "отруєння сирим ксеном'ясом")
            hero.hurt_this_tick = max(0.0, hero.hurt_this_tick + info.heal)  # self-inflicted
        world.log(f"З'їв: {info.name} (+{info.food} ситості)", "good" if info.heal >= 0 else "info")
        return self.done(f"ate {self.item}")


class Use(Action):
    name = "use"

    def start(self, world: "World") -> str | None:
        item = self.target.lower() or "medkit"
        if item != "medkit":
            return "only 'medkit' can be used (food: eat, flare/headlamp work automatically)"
        if world.hero.inventory[item] <= 0:
            return "you have no medkit"
        self.item = item
        return None

    def label(self) -> str:
        return "користується аптечкою"

    def step(self, world: "World") -> Status:
        hero = world.hero
        if self.ticks < 5:
            return Status.RUNNING
        hero.inventory[self.item] -= 1
        hero.change("hp", ITEMS[self.item].heal)
        world.log(f"Вколов стимулятор з аптечки (+{ITEMS[self.item].heal} HP)", "good")
        return self.done("used medkit")


def _missing(inv, cost: dict[str, int]) -> str:
    lack = [f"{n - inv[k]} {k}" for k, n in cost.items() if inv[k] < n]
    return ", ".join(lack)


class Craft(Action):
    name = "craft"

    def start(self, world: "World") -> str | None:
        parts = self.target.lower().split()
        item = parts[0] if parts else ""
        if item not in RECIPES:
            return f"can craft only: {', '.join(RECIPES)}"
        self.count = min(max(int(parts[1]), 1), 10) if len(parts) > 1 and parts[1].isdigit() else 1
        cost, self.work = RECIPES[item]
        lack = _missing(world.hero.inventory, cost)
        if lack:
            return f"not enough materials for {item}: need {lack} more"
        self.item = item
        self.made = 0
        self.progress = 0
        return None

    def label(self) -> str:
        return f"майструє: {ITEMS[self.item].name} ({self.made}/{self.count})"

    def step(self, world: "World") -> Status:
        self.progress += 1
        if self.progress < self.work:
            return Status.RUNNING
        self.progress = 0
        hero = world.hero
        cost, _ = RECIPES[self.item]
        if _missing(hero.inventory, cost):
            if self.made:
                return self.done(f"crafted {self.made} {self.item} (out of materials)")
            return self.fail("materials were lost")
        for k, n in cost.items():
            hero.inventory[k] -= n
        hero.inventory[self.item] += 1
        self.made += 1
        world.log(f"Змайстрував: {ITEMS[self.item].name}", "good")
        if self.made >= self.count:
            return self.done(f"crafted {self.made} {self.item}")
        return Status.RUNNING


class Build(Action):
    name = "build"
    NAMES = {"heater": "обігрівач", "dome": "купол"}

    def start(self, world: "World") -> str | None:
        what = self.target.lower()
        if what not in STRUCTURES:
            return f"can build only: {', '.join(STRUCTURES)}"
        level = world.level
        if level.dark:
            return "cannot build inside wrecks"
        cost, self.work = STRUCTURES[what]
        lack = _missing(world.hero.inventory, cost)
        if lack:
            return f"not enough materials for {what}: need {lack} more"
        pos = world.hero.pos
        spots = [pos] if what == "dome" else [q for q in level.neighbors(pos)] + [pos]
        spots = [q for q in spots if level.tile(q) in BUILDABLE and not level.creature_at(q)]
        if not spots:
            return f"no free moss/dust here to build a {what}; move to open ground"
        self.what = what
        self.spot = spots[0]
        return None

    def label(self) -> str:
        return f"будує: {self.NAMES[self.what]}"

    def step(self, world: "World") -> Status:
        if self.ticks < self.work:
            return Status.RUNNING
        hero = world.hero
        level = world.level
        cost, _ = STRUCTURES[self.what]
        if _missing(hero.inventory, cost):
            return self.fail("materials were lost")
        for k, n in cost.items():
            hero.inventory[k] -= n
        if self.what == "heater":
            level.set_tile(self.spot, Tile.HEATER)
            level.heaters[self.spot] = HEATER_TICKS
            hero.remove_place("camp", level.id, self.spot)
            hero.add_place("camp", level.id, self.spot, "обігрівач")
            world.log("Зібрав і увімкнув обігрівач", "good")
        else:
            level.set_tile(self.spot, Tile.DOME)
            hero.add_place("dome", level.id, self.spot, "купол")
            world.log("Надув житловий купол", "good")
        hero.known(level.id)[self.spot] = level.tile(self.spot)
        return self.done(f"built {self.what} at {self.spot[0]},{self.spot[1]}")


class Cook(Action):
    name = "cook"

    def label(self) -> str:
        return "готує м'ясо"

    def start(self, world: "World") -> str | None:
        if world.hero.inventory["raw_meat"] <= 0:
            return "you have no raw_meat"
        if not world.level.heaters:
            return "there is no working heater on this level; build one"
        self.work = 0
        self.cooked = 0
        return None

    def step(self, world: "World") -> Status:
        hero = world.hero
        level = world.level
        if not level.heaters:
            return self.fail("the heater ran out of power")
        if not level.near_heat(hero.pos, 1):
            heaters = set(level.heaters)
            state = self.walk(world, lambda p: any(chebyshev(p, f) <= 1 for f in heaters))
            if state == "blocked":
                return self.fail("cannot reach the heater")
            return Status.RUNNING
        self.work += 1
        if self.work >= 5:
            self.work = 0
            hero.inventory["raw_meat"] -= 1
            hero.inventory["cooked_meat"] += 1
            self.cooked += 1
            if hero.inventory["raw_meat"] <= 0:
                world.log(f"Засмажив м'ясо ({self.cooked} шт.)", "good")
                return self.done(f"cooked {self.cooked} meat")
        return Status.RUNNING


class Loot(Action):
    """Pick up remembered items; with none in sight, search the level for some."""

    name = "loot"
    max_ticks = 240

    def label(self) -> str:
        return "обшукує місцевість" if self.searching else "підбирає речі"

    def start(self, world: "World") -> str | None:
        self.searching = False
        self.picked = 0
        self._edge: Pos | None = None
        if world.hero.seen_items.get(world.level.id):
            return None
        if not frontier(world.level, world.hero.known(world.level.id), world.hero.pos):
            return "no items are known here and everything reachable is already searched"
        self.searching = True
        return None

    def step(self, world: "World") -> Status:
        hero = world.hero
        before = sum(hero.inventory.values())
        seen = hero.seen_items.get(world.level.id, {})
        if seen:
            self.searching = False
            targets = set(seen)
            state = self.walk(world, lambda p: p in targets)
            self.picked += sum(hero.inventory.values()) - before
            if state == "blocked":
                return self.fail("cannot reach the items")
            if not hero.seen_items.get(world.level.id):
                return self.done(f"picked up everything known ({self.picked} items)")
            return Status.RUNNING
        if self.picked:
            return self.done(f"picked up everything known ({self.picked} items)")
        # searching: walk toward the nearest unexplored edge until something shows up
        known = hero.known(world.level.id)
        if self._edge is None or hero.pos == self._edge or all(q in known for q in world.level.neighbors(self._edge)):
            edges = frontier(world.level, known, hero.pos)
            edges.pop(hero.pos, None)
            if not edges:
                return self.fail("searched everywhere reachable, found nothing")
            self._edge = min(edges, key=edges.get)
            self._path = []
        edge = self._edge
        if self.walk(world, lambda p: p == edge) == "blocked":
            self._edge = None
        return Status.RUNNING


# --- combat --------------------------------------------------------------------


class Hunt(Action):
    """Chase and attack a creature. ``fight`` is the same with any hostile."""

    name = "hunt"
    max_ticks = 200

    def start(self, world: "World") -> str | None:
        self.kind = self.target.lower()
        self.lost = 0
        self.prey = self._choose(world)
        if self.prey is None:
            what = self.kind or "hostile creature"
            return f"no visible {what} to attack"
        return None

    def _choose(self, world: "World") -> Creature | None:
        hero = world.hero
        options = [c for c in visible_creatures(world)
                   if (c.kind.key == self.kind if self.kind else c.kind.hostile)]
        return min(options, key=lambda c: chebyshev(c.pos, hero.pos), default=None)

    def label(self) -> str:
        return f"полює на: {self.prey.name}" if self.name == "hunt" else f"б'ється з: {self.prey.name}"

    def step(self, world: "World") -> Status:
        hero = world.hero
        prey = self.prey
        if prey.hp <= 0 or prey not in world.level.creatures:
            return self.done(f"killed {prey.kind.key}")
        if prey.pos not in hero.visible:
            self.lost += 1
            if self.lost > 8:
                return self.fail(f"lost sight of {prey.kind.key}")
        else:
            self.lost = 0
        if chebyshev(prey.pos, hero.pos) <= 1:
            if hero_attack(world, prey):
                return self.done(f"killed {prey.kind.key}")
            return Status.RUNNING
        target = prey.pos
        state = self.walk(world, lambda p: chebyshev(p, target) <= 1, replan=True)
        if state == "blocked":
            return self.fail(f"cannot reach {prey.kind.key}")
        return Status.RUNNING


class Fight(Hunt):
    name = "fight"


class Flee(Action):
    name = "flee"
    max_ticks = 20

    def label(self) -> str:
        return "тікає!"

    def step(self, world: "World") -> Status:
        hero = world.hero
        level = world.level
        threats = [c for c in visible_creatures(world) if c.kind.hostile]
        if not threats:
            return self.done("escaped, no threats visible")
        best, best_score = None, None
        for q in level.neighbors(hero.pos):
            if not level.passable(q) or level.creature_at(q):
                continue
            score = min(chebyshev(q, c.pos) for c in threats) * 10
            score += 15 if level.near_heat(q, 1) else 0
            score += sum(1 for n in level.neighbors(q) if level.passable(n))  # avoid dead ends
            if best_score is None or score > best_score:
                best, best_score = q, score
        if best is None:
            return self.fail("cornered, nowhere to run")
        move_hero(world, best)
        if self.ticks >= self.max_ticks - 1:
            return self.done("ran for a while")
        return Status.RUNNING


# --- rest ----------------------------------------------------------------------


class Sleep(Action):
    """Sleep until rested; at night, sleep through until dawn (saves brain calls)."""

    name = "sleep"
    max_ticks = 12 * 60

    def label(self) -> str:
        return "спить"

    def start(self, world: "World") -> str | None:
        if world.hero.energy >= 90 and not world.is_night:
            return "you are not tired (energy >= 90); at night you can always sleep until dawn"
        self.night = world.is_night
        return None

    def step(self, world: "World") -> Status:
        hero = world.hero
        if self.ticks == 0:
            hero.sleeping = True
            where = {Tile.DOME: "під куполом", Tile.POD: "у капсулі"}.get(world.level.tile(hero.pos), "просто неба")
            world.log(f"Лягає спати {where}", "info")
        if not hero.sleeping:
            return self.done("woke up abruptly")
        rested = hero.energy >= 99
        if rested and not world.is_night:
            hero.sleeping = False
            if self.night:
                world.log("Прокинувся на світанку", "good")
                return self.done("slept through the night, woke at dawn")
            world.log("Прокинувся відпочилим", "good")
            return self.done("slept well, energy restored")
        return Status.RUNNING


class Rest(Action):
    name = "rest"

    def start(self, world: "World") -> str | None:
        digits = "".join(ch for ch in self.target if ch.isdigit())
        self.minutes = min(max(int(digits), 1), 240) if digits else 30
        return None

    def label(self) -> str:
        return f"відпочиває ({self.minutes} хв)"

    def step(self, world: "World") -> Status:
        if self.ticks >= self.minutes - 1:
            return self.done(f"rested {self.minutes} minutes")
        return Status.RUNNING


class Wait(Rest):
    name = "wait"


# --- wrecks --------------------------------------------------------------------


class Enter(Action):
    name = "enter"

    def label(self) -> str:
        return "йде в уламки"

    def start(self, world: "World") -> str | None:
        hero = world.hero
        if world.level.dark:
            return "you are already inside a wreck"
        wrecks = [p for p in hero.places.values() if p.kind == "wreck"]
        if self.target:
            wrecks = [p for p in wrecks if p.id == self.target]
        if not wrecks:
            return "no known wreck entrance" + (f" '{self.target}'" if self.target else "; explore first")
        self.wreck = min(wrecks, key=lambda p: chebyshev(p.pos, hero.pos))
        return None

    def step(self, world: "World") -> Status:
        dest = self.wreck.pos
        state = self.walk(world, lambda p: p == dest)
        if state == "blocked":
            return self.fail("cannot reach the wreck entrance")
        if state != "arrived":
            return Status.RUNNING
        level_id = next(lid for lid, lv in world.levels.items() if lv.parent == ("surface", dest))
        wreck = world.levels[level_id]
        change_level(world, level_id, wreck.exit_pos)
        world.log(f"Пробрався всередину: {wreck.name}. Енергії немає, темно...", "danger")
        return self.done(f"entered {wreck.name}")


class Leave(Action):
    name = "leave"

    def label(self) -> str:
        return "виходить з уламків"

    def start(self, world: "World") -> str | None:
        if not world.level.dark:
            return "you are not inside a wreck"
        return None

    def step(self, world: "World") -> Status:
        level = world.level
        exit_pos = level.exit_pos
        state = self.walk(world, lambda p: p == exit_pos)
        if state == "blocked":
            return self.fail("cannot find the way to the exit")
        if state != "arrived":
            return Status.RUNNING
        parent_id, pos = level.parent
        change_level(world, parent_id, pos)
        world.log(f"Вибрався з уламків ({level.name}) на поверхню", "good")
        return self.done("left the wreck")


# --- the pod --------------------------------------------------------------------


class PodAction(Action):
    """Everything done at the escape pod: power, repairs, beacon, storage."""

    name = "pod"
    COMMANDS = ("heater_on", "heater_off", "charge", "repair", "beacon", "transmit", "take")
    WORK = {"repair": 20, "beacon": 60, "transmit": TRANSMIT_TICKS}
    LABELS = {
        "heater_on": "вмикає обігрів капсули", "heater_off": "вимикає обігрів капсули",
        "charge": "заряджає капсулу", "repair": "ремонтує проводку капсули",
        "beacon": "лагодить аварійний маяк", "transmit": "передає сигнал лиха", "take": "бере речі зі сховища",
    }

    def start(self, world: "World") -> str | None:
        pod = world.pod
        if pod is None:
            return "there is no pod"
        if world.hero.level_id != pod.level_id:
            return "the pod is on the surface; leave the wreck first"
        parts = self.target.lower().split()
        cmd = parts[0] if parts else ""
        if cmd not in self.COMMANDS:
            return f"pod command must be one of: {', '.join(self.COMMANDS)}"
        inv = world.hero.inventory
        if cmd == "heater_on" and (pod.fault or pod.power <= 0):
            return "the pod heater cannot run: " + ("fault, use `pod repair`" if pod.fault else "no power")
        if cmd == "charge" and inv["power_cell"] <= 0:
            return "you have no power_cell"
        if cmd == "repair":
            if not pod.fault:
                return "the pod has no fault to repair"
            if inv["ore"] < 2:
                return "repairing the wiring needs 2 ore"
        if cmd == "beacon":
            if pod.beacon_repaired:
                return "the beacon is already repaired"
            missing = pod.missing_parts(inv)
            if missing:
                return "beacon parts missing: " + ", ".join(f"{n} {k}" for k, n in missing.items())
        if cmd == "transmit":
            if not pod.beacon_repaired:
                return "repair the beacon first (`pod beacon`)"
            if pod.rescue_at is not None:
                return "the distress call was already sent; survive until rescue"
            if pod.power < TRANSMIT_POWER:
                return f"transmitting needs {TRANSMIT_POWER} power, the pod has {pod.power:.0f}"
        if cmd == "take":
            item = parts[1] if len(parts) > 1 else ""
            if pod.storage[item] <= 0:
                stored = ", ".join(f"{k} x{v}" for k, v in pod.storage.items() if v) or "nothing"
                return f"the pod storage has no '{item}' (it has: {stored})"
            self.item = item
        self.cmd = cmd
        self.work = 0
        return None

    def label(self) -> str:
        return self.LABELS[self.cmd]

    def step(self, world: "World") -> Status:
        pod = world.pod
        hero = world.hero
        if chebyshev(hero.pos, pod.pos) > 1:
            target = pod.pos
            if self.walk(world, lambda p: chebyshev(p, target) <= 1) == "blocked":
                return self.fail("cannot reach the pod")
            return Status.RUNNING
        self.work += 1
        if self.work < self.WORK.get(self.cmd, 1):
            if self.cmd == "transmit":
                pod.power = max(0.0, pod.power - TRANSMIT_POWER / TRANSMIT_TICKS)
            return Status.RUNNING
        inv = hero.inventory
        if self.cmd == "heater_on":
            pod.heater_on = True
            world.log("Увімкнув обігрів капсули", "good")
        elif self.cmd == "heater_off":
            pod.heater_on = False
            world.log("Вимкнув обігрів капсули, щоб берегти батарею", "info")
        elif self.cmd == "charge":
            n = inv["power_cell"]
            inv["power_cell"] = 0
            pod.power = min(100.0, pod.power + n * CELL_POWER)
            world.log(f"Вставив енергоелементи ({n}) - батарея капсули {pod.power:.0f}%", "good")
        elif self.cmd == "repair":
            inv["ore"] -= 2
            pod.fault = False
            world.log("Проводку капсули відремонтовано", "good")
        elif self.cmd == "beacon":
            for k, n in BEACON_PARTS.items():
                inv[k] -= n
            pod.beacon_repaired = True
            world.log("АВАРІЙНИЙ МАЯК ВІДРЕМОНТОВАНО! Лишилось накопичити енергію і передати сигнал.", "victory")
        elif self.cmd == "transmit":
            pod.transmitted = True
            pod.rescue_at = world.tick + RESCUE_DELAY
            world.log("Сигнал лиха передано! Рятувальний шатл прибуде через 3 соли. Треба вижити.", "victory")
        elif self.cmd == "take":
            n = pod.storage[self.item]
            pod.storage[self.item] = 0
            inv[self.item] += n
            world.log(f"Взяв зі сховища капсули: {ITEMS[self.item].name} x{n}", "info")
        return self.done(f"pod {self.cmd} done")


# --- routines ------------------------------------------------------------------------


def _plan_night(world: "World") -> tuple[str, str] | None:
    hero = world.hero
    level = world.level
    inv = hero.inventory
    if level.dark:
        return ("leave", "")
    pod = world.pod
    if pod and not pod.fault and pod.power > 15:
        if chebyshev(hero.pos, pod.pos) > 0:
            return ("go_to", "pod_1")
        saving = pod.beacon_repaired and pod.rescue_at is None and pod.power < TRANSMIT_POWER + 10
        if not pod.heater_on and not saving:  # once the beacon works, save power for the call
            return ("pod", "heater_on")
        return ("sleep", "") if hero.energy < 90 or world.is_night else None
    if level.near_heat(hero.pos, 2):
        return ("sleep", "") if hero.energy < 90 or world.is_night else None
    if inv["fiber"] < 3:
        return ("gather", "fiber 3")
    if inv["ore"] < 2:
        return ("gather", "ore 2")
    return ("build", "heater")


def _plan_supplies(world: "World") -> tuple[str, str] | None:
    hero = world.hero
    inv = hero.inventory
    known = set(hero.known(world.level.id).values())
    if world.level.dark:
        return None
    if hero.hydration < 85 and Tile.WATER in known:
        return ("drink", "")
    food = next((f for f in FOOD_PREFERENCE if inv[f] > 0 and f != "raw_meat"), None)
    if hero.satiety < 60 and food:
        return ("eat", food)
    if sum(inv[f] for f in FOOD_PREFERENCE) < 4 and Tile.SPORE_BUSH in known:
        return ("gather", "spores")
    if inv["fiber"] < 4 and Tile.FLORA in known:
        return ("gather", "fiber 4")
    if inv["ore"] < 2 and Tile.ROCK in known:
        return ("gather", "ore 2")
    return None


class Routine(Action):
    """A macro action: a deterministic planner picks sub-actions until done.

    Saves LLM calls for predictable chores; interrupts still reach the brain.
    """

    name = "routine"
    max_ticks = 900
    PLANNERS = {"night": _plan_night, "supplies": _plan_supplies}
    LABELS = {"night": "готується до ночі", "supplies": "поповнює запаси"}

    def start(self, world: "World") -> str | None:
        self.kind = self.target.lower().strip()
        if self.kind not in self.PLANNERS:
            return f"routine must be one of: {', '.join(self.PLANNERS)}"
        self.sub: Action | None = None
        self.steps = 0
        self.done_steps: list[str] = []
        if self._next(world) is None and not self.sub:
            return f"nothing to do for routine {self.kind}"
        return None

    @property
    def effective_name(self) -> str:
        return self.sub.name if self.sub else self.name

    def label(self) -> str:
        now = f": {self.sub.label()}" if self.sub else ""
        return f"{self.LABELS[self.kind]}{now}"

    def cancel(self, world: "World") -> None:
        if self.sub:
            self.sub.cancel(world)

    def _next(self, world: "World") -> Action | None:
        plan = self.PLANNERS[self.kind](world)
        self.sub = None
        while plan is not None and self.steps < 10:
            self.steps += 1
            action = make_action(*plan)
            error = action.start(world)
            if error is None:
                self.sub = action
                return action
            self.done_steps.append(f"{plan[0]} skipped ({error})")
            return None
        return None

    def step(self, world: "World") -> Status:
        if self.sub is None and self._next(world) is None:
            summary = "; ".join(self.done_steps[-4:]) or "nothing needed"
            return self.done(f"routine {self.kind} finished ({summary})")
        status = self.sub.step(world)
        self.sub.ticks += 1
        if status is Status.RUNNING:
            return Status.RUNNING
        self.done_steps.append(f"{self.sub.name} {self.sub.target}: {status.value}".strip())
        if status is Status.FAILED:
            return self.fail(f"routine {self.kind} stopped: {self.sub.result}")
        self.sub = None
        return Status.RUNNING


# --- the other survivor ----------------------------------------------------------------


class Talk(Action):
    name = "talk"

    def label(self) -> str:
        return "йде поговорити"

    def start(self, world: "World") -> str | None:
        comp = world.companion
        if comp is None or not comp.alive:
            return "there is nobody to talk to"
        if not comp.joined:
            return "she is still trapped at her crash site; go there (go_to crash_site_1) to free her"
        if world.hero.level_id != "surface":
            return "she is on the surface"
        return None

    def step(self, world: "World") -> Status:
        comp = world.companion
        target = comp.pos
        if chebyshev(world.hero.pos, target) > 1:
            if self.walk(world, lambda p: chebyshev(p, target) <= 1, replan=True) == "blocked":
                return self.fail("cannot reach her")
            return Status.RUNNING
        comp.talk_requested = True
        return self.done(f"talking with {comp.name}")


class Give(Action):
    name = "give"

    def label(self) -> str:
        return f"віддає: {ITEMS[self.item].name}"

    def start(self, world: "World") -> str | None:
        comp = world.companion
        if comp is None or not comp.alive or not comp.joined:
            return "there is nobody here to give things to"
        item = self.target.lower().split()[0] if self.target else ""
        if world.hero.inventory[item] <= 0:
            return f"you have no '{item}'"
        self.item = item
        return None

    def step(self, world: "World") -> Status:
        comp = world.companion
        target = comp.pos
        if chebyshev(world.hero.pos, target) > 1:
            if self.walk(world, lambda p: chebyshev(p, target) <= 1, replan=True) == "blocked":
                return self.fail("cannot reach her")
            return Status.RUNNING
        world.hero.inventory[self.item] -= 1
        world.log(comp.receive(world, self.item), "good")
        return self.done(f"gave {self.item} to {comp.name}")


# --- registry ------------------------------------------------------------------


ACTIONS: dict[str, type[Action]] = {
    cls.name: cls
    for cls in (GoTo, Explore, Gather, Drink, Eat, Use, Craft, Build, Cook, Loot,
                Hunt, Fight, Flee, Sleep, Rest, Wait, Enter, Leave, PodAction, Routine, Talk, Give)
}

# What the LLM sees about each action: (target format, description)
ACTION_HELP: dict[str, tuple[str, str]] = {
    "go_to": ("place id or 'x,y'", "walk to a known place or map coordinate"),
    "explore": ("N|NE|E|SE|S|SW|W|NW|any", "walk toward unexplored ground (in a direction) revealing the map"),
    "gather": ("fiber|ore|spores|eel [amount]", "walk to the nearest known source and collect"),
    "drink": ("", "walk to known water and drink until full"),
    "eat": ("food item or empty for best", "eat one food item from inventory"),
    "use": ("medkit", "heal with a medkit"),
    "craft": ("blade|flare [count]", "blade: 2 fiber+1 ore (weapon); flare: 1 fiber (light at night/in wrecks)"),
    "build": ("heater|dome", "heater: 3 fiber+2 ore, runs 8h, warmth, scares hounds/brutes away, cook at it; "
              "dome: 6 fiber, safer and warmer sleep"),
    "cook": ("", "cook all raw_meat at a working heater"),
    "loot": ("", "pick up items seen on this level; if none are known, search the level until some turn up"),
    "hunt": ("hopper|hound|brute|drone|android", "chase and kill a visible creature (meat from alien animals)"),
    "fight": ("", "attack the nearest visible hostile creature"),
    "flee": ("", "run away from visible hostile creatures"),
    "sleep": ("", "sleep until rested; at night sleep until dawn (by day only when energy < 90); danger wakes you"),
    "rest": ("minutes", "stay in place"),
    "enter": ("wreck place id or empty", "walk to a wreck entrance and go inside"),
    "leave": ("", "walk to the exit hatch of the wreck and return to the surface"),
    "pod": ("heater_on|heater_off|charge|repair|beacon|transmit|take <item>",
            "walk to your escape pod and use it: pod heater (warmth, drains power), charge with power_cells, "
            "repair a fault (2 ore), repair the beacon (3 alloy+1 circuit), transmit the distress call "
            "(needs 60 power) or take stored items"),
    "routine": ("night|supplies", "automatic chores: night = get to warmth and sleep; "
                "supplies = drink, eat, stock food/fiber/ore"),
    "talk": ("", "walk to the other survivor and talk with her"),
    "give": ("item", "give one item to the other survivor (food helps her, builds trust)"),
}


def make_action(name: str, target: str = "") -> Action:
    cls = ACTIONS.get(name)
    if cls is None:
        raise KeyError(name)
    return cls(target)
