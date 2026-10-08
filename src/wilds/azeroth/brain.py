"""A free, rule-based brain for Mulgore: takes quests, fights what they ask for, hands them in.
The reference opponent for tests and the reflex fallback when a model call fails."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..sim import Conversation, Decision, Reflection
from . import quests as q
from .actions import ACTION_HELP

if TYPE_CHECKING:
    from .sim import ZoneSim

Pos = tuple[int, int]


def _dist(a: Pos, b: Pos) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


class ScriptedZoneBrain:
    name = "scripted"
    label = "scripted (правила)"

    def decide(self, sim: "ZoneSim") -> Decision:
        action, target, thought = self._choose(sim)
        last = sim.history[-1] if sim.history else None
        if last and last.outcome.startswith(("rejected", "failed")) and (last.action, last.target) == (action, target):
            return Decision("explore", "", "Так не вийшло. Огляну околиці.") if sim.hero.hp > 30 \
                else Decision("rest", "120", "Треба перепочити.")
        return Decision(action, target, thought)

    def _choose(self, sim: "ZoneSim") -> tuple[str, str, str]:
        hero = sim.hero
        here = hero.pos
        attackers = sim.attackers()
        if attackers:
            c = min(attackers, key=lambda a: _dist(here, a.pos))
            if hero.hp < hero.max_hp * 0.35 or c.level > hero.level + 3:
                return "go_to", "Camp Narache", f"{c.title} сильніший за мене. Відступаю до табору!"
            return "hunt", c.title, f"{c.title} напав. Захищаюся!"
        hostiles = [c for c in sim.visible_hostiles() if c.level <= hero.level + 2]
        if hostiles and hero.hp > hero.max_hp * 0.6:
            c = hostiles[0]
            return "hunt", c.title, f"{c.title} поруч. Доведеться битися."
        if hero.hp < hero.max_hp * 0.5:
            return "rest", "300", "Сили на межі. Перепочину."

        # hand in finished quests
        for aq in hero.active.values():
            if aq.ready:
                npc = aq.quest.turn_in
                return "talk", npc, f"Задання «{aq.quest.title}» готове. Піду до {npc.title()}."
        # work on active quests
        for aq in hero.active.values():
            for o in aq.objectives:
                if o.complete:
                    continue
                if o.kind == "kill":
                    if not sim.living(o.target):
                        if sim.respawning(o.target):
                            return "rest", "300", f"Усі {o.target} побиті. Зачекаю, поки з'являться нові."
                        continue  # nothing of that kind left in the zone: work on something else
                    return "hunt", o.target, f"Для «{aq.quest.title}» треба вбити: {o.target} ({o.done}/{o.count})."
                return "search", aq.quest.area or aq.quest.giver, f"Шукаю {o.target} для «{aq.quest.title}»."
            if aq.quest.errand and aq.quest.area:
                return "search", aq.quest.area, f"Маю оглянути {aq.quest.area.title()} для «{aq.quest.title}»."
        # take a new quest from the nearest giver that has one for us
        givers = sorted({qu.giver for qu in sim.quests if sim.available_from(qu.giver)},
                        key=lambda g: _dist(here, sim.places[g].pos) if g in sim.places else 10 ** 9)
        if givers:
            g = givers[0]
            return "talk", g, f"{g.title()} може мати для мене справу."
        # nothing to do: grind something my level can take, else look around
        prey = sorted((c for c in sim.creatures.values() if c.alive and c.hostile and c.level <= hero.level + 1
                       and c.level >= hero.level - 3),
                      key=lambda c: _dist(here, c.pos))
        if prey:
            return "hunt", prey[0].title, f"Тренуватимусь на {prey[0].title}."
        return "explore", "", "Ще не все бачив у цих степах."

    # --- diary and conversation without an LLM -----------------------------------------------------------
    def reflect(self, sim: "ZoneSim") -> Reflection:
        h = sim.hero
        goal = "Виконати ще задання і дорости до 10 рівня" if h.level < 10 else "Залишити Мулгор"
        return Reflection(f"Рівень {h.level}. Виконано завдань: {len(h.done)}, вбито: {sum(h.kills.values())}. "
                          f"Рівнини Мулгору стають рідними.", "", goal)

    def converse(self, sim: "ZoneSim") -> Conversation:
        return Conversation([], 0.0, 0.0, "")


__all__ = ["ScriptedZoneBrain", "q"]


class ExploreBrain(ScriptedZoneBrain):
    """A sightseeing hero: stands still so the world lives around the free camera (``--explore``)."""

    name = "explore"
    label = "огляд (герой стоїть)"

    def decide(self, sim: "ZoneSim") -> Decision:
        sim.hero.hp = sim.hero.max_hp = 10**6  # nothing can hurt a tourist
        return Decision("rest", "300", "Оглядаю Мулгор.")


# --- Claude / Codex brains --------------------------------------------------------------------------


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def decision_schema(strict: bool) -> dict[str, Any]:
    return _obj({
        "thought": {"type": "string", "description": "1-2 short first-person sentences"},
        "action": {"type": "string", "enum": list(ACTION_HELP)},
        "target": {"type": "string", "description": "action target name, or empty string"},
    })


def reflection_schema(strict: bool) -> dict[str, Any]:
    return _obj({
        "diary": {"type": "string", "description": "first-person diary entry, max 90 words"},
        "trait": {"type": "string", "description": "a new trait formed (max 6 words) or empty"},
        "goal": {"type": "string", "description": "concrete next priority, max 15 words"},
    })


class _AzBrainMixin:
    """decide/reflect through a model; falls back to the scripted brain on any failure.
    Mulgore never asks the brain to converse (quests are resolved inside the Talk action)."""

    def _setup(self) -> None:
        from .observe import system_prompt

        self.system = system_prompt(self.lang)
        self.fallback = ScriptedZoneBrain()

    def decide(self, sim: "ZoneSim") -> Decision:
        from .observe import build_observation

        out = self.ask(sim, "decide", self.system, build_observation(sim), decision_schema(self.strict_schemas))
        if out is None or not isinstance(out.get("action"), str):
            return self._reflex(sim)
        return Decision(out["action"], str(out.get("target", "") or ""), str(out.get("thought", "") or "").strip())

    def reflect(self, sim: "ZoneSim") -> Reflection:
        from .observe import build_reflection_prompt, reflection_system

        out = self.ask(sim, "reflect", reflection_system(self.lang), build_reflection_prompt(sim),
                       reflection_schema(self.strict_schemas))
        if out is None or not str(out.get("diary", "")).strip():
            return self.fallback.reflect(sim)
        return Reflection(str(out["diary"]), str(out.get("trait", "") or ""), str(out.get("goal", "") or ""))

    def converse(self, sim: "ZoneSim") -> Conversation:
        return self.fallback.converse(sim)

    def _reflex(self, sim: "ZoneSim") -> Decision:
        decision = self.fallback.decide(sim)
        decision.thought = f"(інстинкт: {self.last_error[:60]}) {decision.thought}"
        return decision


def make_claude_brain(**kwargs):
    from ..brain.claude import ClaudeBrain

    class AzClaudeBrain(_AzBrainMixin, ClaudeBrain):
        name = "claude"

    brain = AzClaudeBrain(**kwargs)
    brain._setup()
    return brain


def make_codex_brain(**kwargs):
    from ..brain.codex import CodexBrain

    class AzCodexBrain(_AzBrainMixin, CodexBrain):
        name = "codex"

    brain = AzCodexBrain(**kwargs)
    brain._setup()
    return brain
