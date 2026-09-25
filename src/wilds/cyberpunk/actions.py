"""The action menu for the cyberpunk chapter: deliberately smaller than Tau-7's -
this stage proves out dialogue, trade and travel, not combat or crafting."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Callable

from ..pathfinding import find_path, frontier
from ..world import DIRECTIONS, chebyshev
from .factions import adjust, faction_of, price_multiplier
from .hero import Place
from .items import ITEMS
from .npc import FIXER_COOLDOWN_MINUTES, JOBS_BEFORE_COOLDOWN
from .risk import (CONTRACT_HEAT_GAIN, CYBERWARE_HEAT_GAIN, add_heat, move_cost_for_district,
                   price_multiplier_for_district, roll_outcome, success_probability)
from .ship import FUEL_PRICE, LAUNCH_FUEL, LAUNCH_MINUTES, MAX_FUEL

if TYPE_CHECKING:
    from .world import CityWorld

TALK_COOLDOWN = 4 * 60
TRAVEL_MINUTES = 90
TRAVEL_FEE = 30


class Status(Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Action:
    name = ""
    max_ticks = 240

    def __init__(self, target: str = "") -> None:
        self.target = (target or "").strip()
        self.ticks = 0
        self.result = ""
        self._path: list[tuple[int, int]] = []

    def label(self) -> str:
        return f"{self.name} {self.target}".strip()

    def start(self, world: "CityWorld") -> str | None:
        return None

    def step(self, world: "CityWorld") -> Status:
        raise NotImplementedError

    def cancel(self, world: "CityWorld") -> None:
        pass

    def done(self, msg: str) -> Status:
        self.result = msg
        return Status.DONE

    def fail(self, msg: str) -> Status:
        self.result = msg
        return Status.FAILED

    def walk(self, world: "CityWorld", goal: Callable, replan: bool = False) -> str:
        hero = world.hero
        level = world.level
        if goal(hero.pos):
            self._path = []
            return "arrived"
        nxt = self._path[0] if self._path else None
        stale = (replan or nxt is None or chebyshev(nxt, hero.pos) != 1
                 or not level.passable(nxt) or level.npc_at(nxt) is not None or not goal(self._path[-1]))
        if stale:
            blocked = {n.pos for n in level.npcs}
            path = find_path(level, hero.known(), hero.pos, goal, blocked)  # optimistic; replans if blocked
            if path is None:
                return "blocked"
            self._path = path
            if not path:
                return "arrived"
        move_cost = move_cost_for_district(level.id)
        if move_cost > 1 and world.tick % move_cost != 0:
            return "moved"  # slow going here (stage: district modifiers) - this tick doesn't advance
        hero.pos = self._path.pop(0)
        return "arrived" if goal(hero.pos) else "moved"


def _other_district(place, hero) -> str | None:
    """None if the place is reachable on foot; else the error steering to `travel`/`launch`."""
    from .worldgen import OFFWORLD

    if place.level_id == hero.level_id:
        return None
    verb = "launch" if place.level_id in {d for d, _, _ in OFFWORLD} else "travel"
    return f"{place.id} is at '{place.level_id}', you are at '{hero.level_id}'; use `{verb} {place.level_id}` first"


class GoTo(Action):
    name = "go_to"

    def start(self, world: "CityWorld") -> str | None:
        hero = world.hero
        place = hero.places.get(self.target)
        if place is None:
            return f"unknown place '{self.target}'; use a place id from KNOWN PLACES"
        error = _other_district(place, hero)
        if error:
            return error
        self.dest = place.pos
        self.dest_name = place.label
        return None

    def label(self) -> str:
        return f"йде до: {self.dest_name}"

    def step(self, world: "CityWorld") -> Status:
        dest = self.dest
        state = self.walk(world, lambda p: chebyshev(p, dest) <= 1)
        if state == "arrived":
            return self.done(f"arrived at {self.dest_name}")
        if state == "blocked":
            return self.fail(f"no known path to {self.dest_name}")
        return Status.RUNNING


class Explore(Action):
    name = "explore"
    max_ticks = 90

    def start(self, world: "CityWorld") -> str | None:
        direction = self.target.upper() or "ANY"
        if direction != "ANY" and direction not in DIRECTIONS:
            return f"direction must be one of {', '.join(DIRECTIONS)} or 'any'"
        self.direction = direction
        self.known_before = len(world.hero.known())
        self.dest = None
        if not self._pick(world):
            return "everything reachable here is already explored"
        return None

    def _pick(self, world: "CityWorld") -> bool:
        hero = world.hero
        edges = frontier(world.level, hero.known(), hero.pos)
        edges.pop(hero.pos, None)
        if not edges:
            return False
        if self.direction == "ANY":
            self.dest = min(edges, key=lambda p: (edges[p], world.rng.random()))
        else:
            dx, dy = DIRECTIONS[self.direction]
            hx, hy = hero.pos
            self.dest = max(edges, key=lambda p: ((p[0] - hx) * dx + (p[1] - hy) * dy) * 3 - edges[p])
        self._path = []
        return True

    def label(self) -> str:
        return f"досліджує: {self.direction.lower()}"

    def step(self, world: "CityWorld") -> Status:
        hero = world.hero
        new = len(hero.known()) - self.known_before
        if self.ticks >= self.max_ticks - 1:
            return self.done(f"explored, saw {new} new tiles")
        dest = self.dest
        known = hero.known()
        reached = hero.pos == dest or all(q in known for q in world.level.neighbors(dest))
        if reached and not self._pick(world):
            return self.done(f"explored, saw {new} new tiles") if new else \
                self.fail("everything reachable here is already explored")
        dest = self.dest
        if self.walk(world, lambda p: p == dest) == "blocked" and not self._pick(world):
            return self.fail("everything reachable here is already explored")
        return Status.RUNNING


class Travel(Action):
    """Move to another district (stage 3): a flat time+fee trip, no on-foot path."""

    name = "travel"
    max_ticks = TRAVEL_MINUTES + 5

    def start(self, world: "CityWorld") -> str | None:
        from .worldgen import DISTRICTS

        district_id = self.target.strip().lower()
        valid = {d for d, _ in DISTRICTS}
        if district_id not in valid:
            return f"district must be one of {', '.join(sorted(valid))}"
        if district_id == world.hero.level_id:
            return f"you are already in '{district_id}'"
        if world.hero.nuyen < TRAVEL_FEE:
            return f"transit costs {TRAVEL_FEE}¥, you only have {world.hero.nuyen}¥"
        self.district_id = district_id
        self.name_shown = dict(DISTRICTS)[district_id]
        return None

    def label(self) -> str:
        return f"їде в район: {self.name_shown}"

    def step(self, world: "CityWorld") -> Status:
        if self.ticks < TRAVEL_MINUTES - 1:
            return Status.RUNNING
        hero = world.hero
        hero.nuyen -= TRAVEL_FEE
        hero.level_id = self.district_id
        hero.pos = world.levels[self.district_id].arrival
        world.log(f"Прибув до району «{self.name_shown}» (-{TRAVEL_FEE}¥ за проїзд)", "info")
        return self.done(f"traveled to {self.district_id}")


class Launch(Action):
    """Fly the ship to a place beyond the city: costs fuel, not nuyen, and takes longer."""

    name = "launch"
    max_ticks = 999

    def start(self, world: "CityWorld") -> str | None:
        from .worldgen import OFFWORLD

        self.max_ticks = LAUNCH_MINUTES + 5
        destination = self.target.strip().lower()
        valid = {d for d, _, _ in OFFWORLD}
        if destination not in valid:
            return f"destination must be one of {', '.join(sorted(valid))}"
        if destination == world.hero.level_id:
            return f"you are already at '{destination}'"
        ship = world.ship
        if ship is None:
            return "you have no ship"
        if ship.fuel < LAUNCH_FUEL:
            return f"not enough fuel: launch needs {LAUNCH_FUEL:.0f}, you have {ship.fuel:.0f}"
        if ship.hull <= 0:
            return "the ship's hull is wrecked; it cannot fly"
        self.destination = destination
        self.name_shown = dict((d, n) for d, n, _ in OFFWORLD)[destination]
        return None

    def label(self) -> str:
        return f"летить до: {self.name_shown}"

    def step(self, world: "CityWorld") -> Status:
        if self.ticks < LAUNCH_MINUTES - 1:
            return Status.RUNNING
        hero, ship = world.hero, world.ship
        ship.fuel = max(0.0, ship.fuel - LAUNCH_FUEL)
        # a rough, low-stakes flight: rare hull wear, occasionally a lucky salvage find
        if world.rng.random() < 0.12:
            damage = world.rng.uniform(5, 15)
            ship.hull = max(0.0, ship.hull - damage)
            world.log(f"Турбулентність / уламки на курсі: корпус -{damage:.0f}", "danger")
        elif world.rng.random() < 0.15:
            found = world.rng.randint(1, 2)
            hero.inventory["trinket"] += found
            world.log(f"Підібрав дрейфуючий контейнер по дорозі: сувенір x{found}", "good")
        hero.level_id = self.destination
        hero.pos = world.levels[self.destination].arrival
        world.log(f"Пришвартувався: {self.name_shown}", "info")
        return self.done(f"launched to {self.destination}")


class RefuelShip(Action):
    """Only available in the home city, where the corp's hangar is."""

    name = "refuel_ship"

    def start(self, world: "CityWorld") -> str | None:
        from .worldgen import HOME_DISTRICT

        if world.ship is None:
            return "you have no ship"
        if world.hero.level_id != HOME_DISTRICT:
            return f"the fuel hangar is only in '{HOME_DISTRICT}'"
        digits = "".join(ch for ch in self.target if ch.isdigit())
        wanted = int(digits) if digits else 999
        self.amount = min(wanted, MAX_FUEL - world.ship.fuel, world.hero.nuyen // FUEL_PRICE)
        if self.amount <= 0:
            return "no fuel needed, or not enough nuyen"
        return None

    def label(self) -> str:
        return f"заправляє корабель ({self.amount:.0f})"

    def step(self, world: "CityWorld") -> Status:
        cost = round(self.amount * FUEL_PRICE)
        world.hero.nuyen -= cost
        world.ship.fuel += self.amount
        world.log(f"Заправив корабель: +{self.amount:.0f} палива (-{cost}¥)", "good")
        return self.done(f"refueled {self.amount:.0f}")


class Talk(Action):
    name = "talk"

    def start(self, world: "CityWorld") -> str | None:
        place = world.hero.places.get(self.target)
        if place is None or place.kind != "npc":
            return f"unknown NPC '{self.target}'; use an npc place id from KNOWN PLACES"
        error = _other_district(place, world.hero)
        if error:
            return error
        self.npc_id = self.target
        return None

    def label(self) -> str:
        return f"розмовляє з: {self.target}"

    def step(self, world: "CityWorld") -> Status:
        npc = next((n for n in world.level.npcs if n.id == self.npc_id), None)
        if npc is None:
            return self.fail("that NPC is gone")
        if chebyshev(world.hero.pos, npc.pos) > 1:
            if self.walk(world, lambda p: chebyshev(p, npc.pos) <= 1, replan=True) == "blocked":
                return self.fail(f"cannot reach {npc.name}")
            return Status.RUNNING
        world.pending_talk = npc.id
        return self.done(f"talking with {npc.name}")


class Trade(Action):
    name = "trade"

    def start(self, world: "CityWorld") -> str | None:
        parts = self.target.lower().split()
        if len(parts) < 3 or parts[1] not in ("buy", "sell"):
            return "trade target format: '<npc_id> buy|sell <item> [qty]'"
        npc_id, mode, item = parts[0], parts[1], parts[2]
        qty = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
        place = world.hero.places.get(npc_id)
        if place is None or place.kind != "npc":
            return f"unknown NPC '{npc_id}'"
        error = _other_district(place, world.hero)
        if error:
            return error
        if item not in ITEMS:
            return f"unknown item '{item}'"
        self.npc_id, self.mode, self.item, self.qty = npc_id, mode, item, max(1, min(qty, 10))
        return None

    def label(self) -> str:
        return f"торгується з {self.npc_id}: {self.mode} {self.item}"

    def step(self, world: "CityWorld") -> Status:
        hero = world.hero
        npc = next((n for n in world.level.npcs if n.id == self.npc_id), None)
        if npc is None:
            return self.fail("that NPC is gone")
        if chebyshev(hero.pos, npc.pos) > 1:
            if self.walk(world, lambda p: chebyshev(p, npc.pos) <= 1, replan=True) == "blocked":
                return self.fail(f"cannot reach {npc.name}")
            return Status.RUNNING
        info = ITEMS[self.item]
        faction = faction_of(npc.role)
        rep_mult = price_multiplier(hero.reputation, faction)
        district_mult = price_multiplier_for_district(world.hero.level_id)
        if self.mode == "buy":
            if npc.stock[self.item] < self.qty:
                return self.fail(f"{npc.name} does not have {self.qty} {self.item} in stock")
            price = round(npc.price_for(self.item, selling=False) * self.qty * rep_mult * district_mult)
            if hero.nuyen < price:
                return self.fail(f"not enough nuyen ({hero.nuyen} < {price})")
            hero.nuyen -= price
            hero.inventory[self.item] += self.qty
            npc.stock[self.item] -= self.qty
            if info.cyberware:
                hero.essence = max(0.0, hero.essence - info.essence_cost * self.qty)
                add_heat(world.level, CYBERWARE_HEAT_GAIN)
            npc.adjust(affinity=0.03)
            adjust(hero.reputation, faction, 0.02)
            world.log(f"Купив у {npc.name}: {info.name} x{self.qty} за {price}¥", "good")
            return self.done(f"bought {self.qty} {self.item} for {price}")
        if hero.inventory[self.item] < self.qty:
            return self.fail(f"you don't have {self.qty} {self.item}")
        price = round(npc.price_for(self.item, selling=True) * self.qty * (2 - rep_mult))
        hero.nuyen += price
        hero.inventory[self.item] -= self.qty
        npc.stock[self.item] += self.qty if not info.cyberware else 0
        npc.adjust(affinity=0.02)
        adjust(hero.reputation, faction, 0.02)
        world.log(f"Продав {npc.name}: {info.name} x{self.qty} за {price}¥", "good")
        return self.done(f"sold {self.qty} {self.item} for {price}")


class RequestJob(Action):
    """A fixer hands out one courier job at a time - within their own district."""

    name = "request_job"

    def start(self, world: "CityWorld") -> str | None:
        place = world.hero.places.get(self.target)
        if place is None or place.kind != "npc":
            return f"unknown NPC '{self.target}'; use an npc place id from KNOWN PLACES"
        error = _other_district(place, world.hero)
        if error:
            return error
        npc = next((n for n in world.level.npcs if n.id == self.target), None)
        if npc is None or npc.role != "fixer":
            return "only a fixer hands out jobs"
        if world.contract is not None and world.contract.status != "done":
            return "you already have an active contract; finish it first"
        if npc.cooldown_until > world.tick:
            wait = npc.cooldown_until - world.tick
            return (f"{npc.name} has no work for you right now (too many jobs in a row drew attention); "
                    f"try again in ~{wait} min or work another fixer")
        self.fixer_id = self.target
        return None

    def label(self) -> str:
        return f"просить роботу у {self.fixer_id}"

    def step(self, world: "CityWorld") -> Status:
        from .contracts import generate_contract

        npc = next((n for n in world.level.npcs if n.id == self.fixer_id), None)
        if npc is None:
            return self.fail("that fixer is gone")
        if chebyshev(world.hero.pos, npc.pos) > 1:
            if self.walk(world, lambda p: chebyshev(p, npc.pos) <= 1, replan=True) == "blocked":
                return self.fail(f"cannot reach {npc.name}")
            return Status.RUNNING
        world.contract_seq += 1
        contract = generate_contract(world, npc, world.contract_seq)
        if contract is None:
            return self.fail("the fixer has no job for you right now")
        world.contract = contract
        hero = world.hero
        hero.places[f"drop_{contract.id}"] = Place(f"drop_{contract.id}", "landmark", world.hero.level_id,
                                                    contract.drop_pos, "місце передачі (дедроп)")
        world.log(f"{npc.name} дає роботу: {contract.brief}", "event")
        return self.done(f"got contract {contract.id}")


class CompleteJob(Action):
    name = "complete_job"

    def start(self, world: "CityWorld") -> str | None:
        contract = world.contract
        if contract is None or contract.status == "done":
            return "you have no active contract"
        if contract.status == "active":
            return "you have not picked up the package at the drop point yet"
        if contract.level_id != world.hero.level_id:
            return f"the fixer is in district '{contract.level_id}'; use `travel {contract.level_id}` first"
        return None

    def label(self) -> str:
        return "звітує про виконання роботи"

    def step(self, world: "CityWorld") -> Status:
        contract = world.contract
        npc = next((n for n in world.level.npcs if n.id == contract.giver), None)
        if npc is None:
            return self.fail("the fixer is gone")
        if chebyshev(world.hero.pos, npc.pos) > 1:
            if self.walk(world, lambda p: chebyshev(p, npc.pos) <= 1, replan=True) == "blocked":
                return self.fail("cannot reach the fixer")
            return Status.RUNNING
        hero = world.hero
        level = world.level
        faction = faction_of(npc.role)
        armored = any(ITEMS[k].cyberware for k, v in hero.inventory.items() if v > 0)
        rep_fixers = hero.reputation.get(faction or "", 0.0)
        p_success = success_probability(level.heat, rep_fixers, armored)
        outcome = roll_outcome(world.rng, p_success)
        heat_before = level.heat
        add_heat(level, CONTRACT_HEAT_GAIN)
        hero.contracts_done += 1
        contract.status = "done"
        hero.places.pop(f"drop_{contract.id}", None)

        if outcome == "success":
            hero.nuyen += contract.reward
            npc.adjust(trust=0.08, affinity=0.05)
            adjust(hero.reputation, faction, 0.06)
            world.log(f"Робота здана без проблем: +{contract.reward}¥ від {npc.name} "
                     f"(теплота району: {heat_before:.0f}).", "good")
        elif outcome == "partial":
            dmg = world.rng.uniform(12, 28)
            hero.nuyen += contract.reward
            hero.take_damage(dmg, "погоня після здачі роботи")
            npc.adjust(trust=0.04, affinity=0.02)
            adjust(hero.reputation, faction, 0.03)
            world.log(f"Здав роботу, але хтось помітив: втік із побоями (-{dmg:.0f} hp), все ж "
                     f"+{contract.reward}¥ від {npc.name}. Район розпечений (теплота {heat_before:.0f}).",
                     "danger")
        else:
            dmg = world.rng.uniform(35, 55)
            hero.take_damage(dmg, "провалена здача роботи")
            adjust(hero.reputation, faction, -0.05)
            world.log(f"Здачу перехопили! Без оплати, -{dmg:.0f} hp. Варто лягти на дно "
                     f"(теплота району {heat_before:.0f}).", "danger")

        npc.jobs_streak += 1
        if npc.jobs_streak >= JOBS_BEFORE_COOLDOWN:
            npc.jobs_streak = 0
            npc.cooldown_until = world.tick + FIXER_COOLDOWN_MINUTES
            world.log(f"{npc.name} лягає на дно на кілька годин - забагато твоїх робіт поспіль "
                     "привертає зайву увагу.", "info")
        return self.done(f"completed contract {contract.id}: {outcome}")


class PayDebt(Action):
    name = "pay_debt"

    def start(self, world: "CityWorld") -> str | None:
        digits = "".join(ch for ch in self.target if ch.isdigit())
        amount = int(digits) if digits else world.hero.nuyen
        amount = min(amount, world.hero.nuyen, world.hero.debt)
        if amount <= 0:
            return "nothing to pay: either no nuyen or debt is already zero"
        self.amount = amount
        return None

    def label(self) -> str:
        return f"погашає борг: {self.amount}¥"

    def step(self, world: "CityWorld") -> Status:
        hero = world.hero
        hero.nuyen -= self.amount
        hero.debt -= self.amount
        world.log(f"Погасив {self.amount}¥ боргу (лишилось {hero.debt}¥)", "good")
        if world.delinquent:
            world.delinquent = False
            for lv in world.levels.values():
                lv.npcs = [n for n in lv.npcs if n.role != "collector"]
            world.log("Колектор відступає - виплата зняла прострочення боргу.", "good")
        if hero.debt <= 0:
            hero.free = True
            world.log(f"{hero.name} розрахувався з корпорацією. Насип більше не в'язниця.", "victory")
        return self.done(f"paid {self.amount} toward debt")


class Use(Action):
    """Consume an item for its effect - currently only healing (stage: fail
    forward gives hp something to spend, so it needs a way to spend back)."""

    name = "use"

    def start(self, world: "CityWorld") -> str | None:
        item = self.target.strip().lower()
        if item not in ITEMS:
            return f"unknown item '{item}'"
        info = ITEMS[item]
        if info.heal <= 0:
            return f"'{item}' has no use effect"
        if world.hero.inventory[item] <= 0:
            return f"you have no {item}"
        self.item = item
        self.heal = info.heal
        return None

    def label(self) -> str:
        return f"використовує: {self.item}"

    def step(self, world: "CityWorld") -> Status:
        hero = world.hero
        hero.inventory[self.item] -= 1
        before = hero.hp
        hero.hp = min(100.0, hero.hp + self.heal)
        world.log(f"Використав {ITEMS[self.item].name}: +{hero.hp - before:.0f} hp.", "good")
        return self.done(f"used {self.item}, healed {hero.hp - before:.0f}")


class Rest(Action):
    name = "rest"

    def start(self, world: "CityWorld") -> str | None:
        digits = "".join(ch for ch in self.target if ch.isdigit())
        self.minutes = min(max(int(digits), 1), 240) if digits else 30
        return None

    def label(self) -> str:
        return f"відпочиває ({self.minutes} хв)"

    def step(self, world: "CityWorld") -> Status:
        if self.ticks >= self.minutes - 1:
            return self.done(f"rested {self.minutes} minutes")
        return Status.RUNNING


ACTIONS: dict[str, type[Action]] = {
    cls.name: cls for cls in (GoTo, Explore, Travel, Launch, RefuelShip, Talk, Trade,
                              RequestJob, CompleteJob, PayDebt, Use, Rest)
}

ACTION_HELP: dict[str, tuple[str, str]] = {
    "go_to": ("place id", "walk to a known NPC or landmark in your current district"),
    "explore": ("N|NE|E|SE|S|SW|W|NW|any", "walk toward unexplored ground, revealing the district"),
    "travel": ("district id (sprawl|docks|corp_row)",
              f"pay {TRAVEL_FEE}¥ and spend ~{TRAVEL_MINUTES} min to move to another district"),
    "launch": ("destination id (orbital_station|outpost)",
              f"fly the ship beyond the city: costs {LAUNCH_FUEL:.0f} fuel and ~{LAUNCH_MINUTES} min, "
              "small chance of hull wear or a lucky find"),
    "refuel_ship": ("amount, or empty to fill up",
                   f"buy fuel at {FUEL_PRICE}¥/unit; only possible back in the home district"),
    "talk": ("npc id", "walk to an NPC (same district/location) and start a conversation"),
    "trade": ("<npc id> buy|sell <item> [qty]",
              "buy from or sell to an NPC's stock; use the item id shown in their 'sells:' list"),
    "request_job": ("fixer npc id", "walk to a fixer and ask for a courier job (one at a time)"),
    "complete_job": ("", "walk to the fixer who gave you the active job and turn it in for payment"),
    "pay_debt": ("amount, or empty for all you can afford", "pay down the corp debt with nuyen"),
    "use": ("item id", "consume an item you're carrying for its effect (e.g. stim_patch heals hp)"),
    "rest": ("minutes", "stay in place"),
}


def make_action(name: str, target: str = "") -> Action:
    cls = ACTIONS.get(name)
    if cls is None:
        raise KeyError(name)
    return cls(target)
