"""A free, rule-based brain for the cyberpunk chapter: makes reasonable progress
without any LLM, and doubles as the reflex fallback when a real model call fails."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..pathfinding import frontier
from ..world import chebyshev
from .actions import TALK_COOLDOWN

if TYPE_CHECKING:
    from .sim import CitySim, Conversation, Decision, Reflection

STIM_RESERVE = 60  # enough for one stim_patch even at Corp Row's price markup


class CyberScriptedBrain:
    name = "scripted"
    label = "scripted (правила)"

    def decide(self, sim: "CitySim") -> "Decision":
        from .sim import Decision

        action, target, thought = self._choose(sim)
        last = sim.history[-1] if sim.history else None
        if last and last.outcome.startswith("rejected") and last.action == action:
            action, target, thought = "explore", "any", "Не вийшло. Пошукаю щось інше."
        return Decision(action, target, thought)

    def _choose(self, sim: "CitySim") -> tuple[str, str, str]:
        world = sim.world
        hero = world.hero
        level = world.level
        contract = world.contract

        if contract is not None and contract.status == "delivered":
            return "complete_job", "", "Пакунок у мене. Здам роботу і заберу оплату."
        if contract is not None and contract.status == "active":
            drop_id = f"drop_{contract.id}"
            return "go_to", drop_id, "Іду на дедроп по пакунок."

        # stage: risky jobs can now actually hurt - a reflex fallback that never
        # heals would slowly bleed out, so it keeps a small cash reserve for
        # this instead of dumping every nuyen into debt (mirrors Tau-7's
        # ScriptedBrain checking `hp < 50 and inv["medkit"]` before healing)
        if hero.hp < 50 and hero.inventory["stim_patch"] > 0:
            return "use", "stim_patch", "Треба підлікуватися, поки не пізно."
        healer = next((n for n in level.npcs if n.role in ("vendor", "doc")
                      and n.stock.get("stim_patch", 0) > 0), None)
        if (hero.hp < 50 and healer is not None and healer.id in hero.places
                and hero.nuyen >= healer.price_for("stim_patch", False)):
            return "trade", f"{healer.id} buy stim_patch", f"Куплю ліки в {healer.name}, поки цілий."

        if hero.nuyen > STIM_RESERVE and hero.debt > 0:
            amount = min(hero.nuyen - STIM_RESERVE, hero.debt)
            return "pay_debt", str(amount), "Заплачу борг, але лишу трохи на ліки."

        fixer = next((n for n in level.npcs if n.role == "fixer"), None)
        no_active_job = contract is None or contract.status == "done"
        if hero.debt > 0 and no_active_job and fixer is not None and fixer.id in hero.places:
            return "request_job", fixer.id, f"Попрошу роботу в {fixer.name} - гроші на дорозі не валяються."

        for npc in sorted(level.npcs, key=lambda n: chebyshev(n.pos, hero.pos)):
            known = npc.id in hero.places
            reachable = chebyshev(npc.pos, hero.pos) <= 20
            if known and reachable and world.tick - npc.last_talk >= TALK_COOLDOWN:
                return "talk", npc.id, f"Варто познайомитися з {npc.name} ({npc.role})."

        if frontier(level, hero.known(), hero.pos):
            return "explore", "any", "Подивлюся, що є далі по кварталу."
        return "rest", "60", "Насип вивчено. Перепочину."

    def reflect(self, sim: "CitySim") -> "Reflection":
        from .sim import Reflection

        world = sim.world
        hero = world.hero
        day = sim.pending_reflection or max(1, world.day - 1)
        events = [e for e in world.events if (e.tick // 1440) + 1 == day and e.kind in ("good", "talk", "event")]
        highlights = "; ".join(e.text.rstrip(".!") for e in events[-3:]) or "день минув тихо"
        diary = f"День {day} у Насипі. {highlights}. Борг ще висить наді мною."
        goal = f"Погасити ще частину боргу ({hero.debt}¥ лишилось)" if hero.debt > 0 else "Роздивитися Насип уважніше"
        return Reflection(diary, "", goal)

    def converse(self, sim: "CitySim") -> "Conversation":
        from .sim import Conversation

        npc = next((n for n in sim.world.level.npcs if n.id == sim.pending_conversation), None)
        name = npc.name if npc else "незнайомець"
        line = f"{name} коротко кидає кілька слів про життя в Насипу."
        return Conversation([("npc", line), ("hero", "Зрозуміло. Побачимось.")], 0.02, 0.01, "")
