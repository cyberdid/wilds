"""A free, rule-based brain: good enough to survive for a while, and the
reference opponent for tests. No LLM involved."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..actions import FOOD_PREFERENCE, visible_creatures
from ..pathfinding import frontier
from ..pod import TRANSMIT_POWER
from ..tiles import Tile
from ..world import chebyshev

if TYPE_CHECKING:
    from ..sim import Conversation, Decision, Reflection, Simulation


class ScriptedBrain:
    name = "scripted"
    label = "scripted (правила)"

    def __init__(self) -> None:
        self.wrecks_done: set[str] = set()

    def decide(self, sim: "Simulation") -> "Decision":
        from ..sim import Decision

        action, target, thought = self._choose(sim)
        last = sim.history[-1] if sim.history else None
        if last and last.outcome.startswith("rejected") and last.action == action:
            if action == "explore":
                action, target, thought = "rest", "60", "Усе довкола вже знайоме. Перепочину."
            else:
                action, target, thought = "explore", "any", "Не вийшло. Пошукаю щось інше."
        return Decision(action, target, thought)

    def _choose(self, sim: "Simulation") -> tuple[str, str, str]:
        world = sim.world
        hero = world.hero
        level = world.level
        inv = hero.inventory
        known = hero.known(level.id)
        tiles = set(known.values())

        hostiles = sorted((c for c in visible_creatures(world) if c.kind.hostile),
                          key=lambda c: chebyshev(c.pos, hero.pos))
        if hostiles:
            c = hostiles[0]
            d = chebyshev(c.pos, hero.pos)
            strong = c.kind.hp > hero.attack_power * 5
            if (hero.hp < 35 or strong) and not (d <= 1 and c.kind.chase_every == 1):
                return "flee", "", f"{c.name.capitalize()} надто небезпечний. Тікаю!"
            if d <= 4 or c.kind.chase_every == 1:
                return "fight", "", f"{c.name.capitalize()} поруч. Доведеться битися."

        if hero.hp < 50 and inv["medkit"] > 0:
            return "use", "medkit", "Треба скористатися аптечкою."

        food = next((f for f in FOOD_PREFERENCE if inv[f] > 0), None)

        if level.dark:
            seen = hero.seen_items.get(level.id)
            low = hero.hydration < 35 or (hero.satiety < 30 and not food) or not hero.has_light
            if low or hero.hp < 45:
                self.wrecks_done.add(level.id)
                return "leave", "", "Досить на сьогодні, вибираюся з уламків."
            if hero.satiety < 40 and food:
                return "eat", food, "Перекушу, поки тихо."
            if seen:
                return "loot", "", "Сканер бачить щось цінне."
            if sim.history and "already explored" in sim.history[-1].outcome:
                self.wrecks_done.add(level.id)
                return "leave", "", "Тут більше нічого. Виходжу."
            return "explore", "any", "Обережно досліджую темні відсіки."

        pod = world.pod
        comp = world.companion
        if pod and pod.fault and inv["ore"] >= 2:
            return "pod", "repair", "Капсула іскрить. Полагоджу проводку."
        if pod and inv["power_cell"]:
            return "pod", "charge", "Енергоелемент - у батарею капсули."
        if pod and not pod.beacon_repaired and not pod.missing_parts(inv):
            return "pod", "beacon", "Усі деталі є. Лагоджу маяк!"
        if pod and pod.beacon_repaired and pod.rescue_at is None and pod.power >= TRANSMIT_POWER:
            return "pod", "transmit", "Маяк готовий. Кличу на допомогу!"
        if pod and pod.heater_on and not world.is_night and chebyshev(hero.pos, pod.pos) <= 2:
            return "pod", "heater_off", "Ранок. Вимкну обігрів, щоб берегти батарею."
        if comp and comp.state == "stranded":
            return "go_to", "crash_site_1", "Там хтось живий. Треба допомогти."
        if comp and comp.joined and comp.satiety < 30 and food and food != "raw_meat":
            return "give", food, f"{comp.name} голодна. Поділюся."
        if hero.seen_items.get(level.id) and not world.is_night:
            return "loot", "", "Там щось лежить - може, сплав для маяка."

        if hero.hydration < 50 and Tile.WATER in tiles:
            return "drink", "", "Хочеться пити."
        if hero.satiety < 55:
            if food and not (food == "raw_meat" and level.heaters):
                return "eat", food, "Час поїсти."
            if inv["raw_meat"] and level.heaters:
                return "cook", "", "Засмажу м'ясо на обігрівачі."
            if Tile.SPORE_BUSH in tiles:
                return "gather", "spores", "Назбираю спор."
            hoppers = [c for c in visible_creatures(world) if c.kind.key == "hopper"]
            if hoppers:
                return "hunt", "hopper", "Стрибунець! Буде вечеря."
            if Tile.WATER in tiles and hero.satiety < 35:
                return "gather", "eel", "Спробую вполювати вугрів в озері."
        if inv["raw_meat"] and level.heaters:
            return "cook", "", "Засмажу м'ясо, поки працює обігрівач."

        near_heat = level.near_heat(hero.pos, 2)
        if (world.is_night or hero.energy < 25) and pod and not pod.fault and hero.energy < 85:
            return "routine", "night", "Ніч. Повертаюся до капсули."
        if world.is_night or hero.energy < 25:
            if not near_heat and inv["fiber"] >= 3 and inv["ore"] >= 2:
                return "build", "heater", "Темно і холодно. Зберу обігрівач."
            if hero.energy < 85 and (near_heat or hero.warmth > 50 or hero.energy < 25):
                return "sleep", "", "Посплю біля обігрівача."
            if inv["fiber"] < 3 and Tile.FLORA in tiles:
                return "gather", "fiber 3", "Потрібне волокно для обігрівача."
            if inv["ore"] < 2 and Tile.ROCK in tiles:
                return "gather", "ore 2", "Потрібна руда для обігрівача."
            return "rest", "30", "Чекаю світанку над Тау-7."

        if not inv["blade"] and not inv["plasma_cutter"]:
            if inv["fiber"] < 2 and Tile.FLORA in tiles:
                return "gather", "fiber 4", "Без зброї тут не вижити. Потрібне волокно."
            if inv["ore"] < 1 and Tile.ROCK in tiles:
                return "gather", "ore 2", "Шукаю руду для леза."
            if inv["fiber"] >= 2 and inv["ore"] >= 1:
                return "craft", "blade", "Виготовлю саморобне лезо."
        if inv["fiber"] < 5 and Tile.FLORA in tiles:
            return "gather", "fiber 5", "Запасуся волокном."
        if inv["ore"] < 2 and Tile.ROCK in tiles:
            return "gather", "ore 2", "Запасуся рудою."
        if inv["flare"] < 2 and inv["fiber"] >= 4:
            return "craft", "flare", "Фальшфеєр знадобиться в темряві."
        inside = {lv.parent[1]: lid for lid, lv in world.levels.items() if lv.parent}
        wrecks = [p for p in hero.places.values() if p.kind == "wreck"
                  and inside.get(p.pos) not in self.wrecks_done]
        ready = hero.attack_power >= 5 and hero.has_light and hero.hp > 70 and hero.satiety > 50
        if wrecks and ready:
            wreck = min(wrecks, key=lambda p: chebyshev(p.pos, hero.pos))
            return "enter", wreck.id, "Я готовий. Спробую пробратися в уламки."
        if frontier(level, known, hero.pos):
            return "explore", "any", "Подивлюся, що там за пагорбом."
        if pod and chebyshev(hero.pos, pod.pos) > 1:
            return "go_to", "pod_1", "Усе довкола знайоме. Повернуся до капсули."
        return "rest", "60", "Чекаю, поки капсула набере заряд."

    # --- diary and conversation without an LLM -----------------------------------
    def reflect(self, sim: "Simulation") -> "Reflection":
        from ..sim import Reflection

        world = sim.world
        hero = world.hero
        sol = sim.pending_reflection or max(1, world.day - 1)
        events = [e for e in world.events
                  if (e.tick // 1440) + 1 == sol and e.kind in ("danger", "good", "event")]
        hurt = sum(1 for e in events if e.kind == "danger")
        highlights = "; ".join(e.text.rstrip(".!") for e in events[-3:]) or "день минув тихо"
        mood = "Руки досі тремтять." if hurt >= 3 else "Здається, я звикаю до цього світу."
        trait = "насторожений після ран" if hurt >= 3 and "насторожений після ран" not in hero.traits else ""
        pod = world.pod
        if pod and not pod.beacon_repaired:
            missing = pod.missing_parts(hero.inventory)
            goal = "Знайти для маяка: " + ", ".join(f"{n} {k}" for k, n in missing.items())
        elif pod and pod.rescue_at is None:
            goal = "Накопичити енергію капсули і передати сигнал лиха"
        else:
            goal = "Дожити до прильоту шатла"
        return Reflection(f"Сол {sol}. {highlights}. {mood}", trait, goal)

    def converse(self, sim: "Simulation") -> "Conversation":
        from ..sim import Conversation

        comp = sim.world.companion
        request = ""
        if comp.satiety < 40:
            line, request = "Я вмираю з голоду. Є щось поїсти?", "Принеси мені щось поїсти"
        elif comp.hydration < 40:
            line = "Вода... Далеко до озера?"
        else:
            line = "Сховище поповнюю. Скоро маяк, так?"
        return Conversation([("companion", line), ("hero", "Тримайся. Ми виберемося з Тау-7.")],
                            0.02, 0.02, request)
