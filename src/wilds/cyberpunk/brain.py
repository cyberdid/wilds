"""Claude/Codex brains for the cyberpunk chapter.

These are thin subclasses of the Tau-7 CLI brains: they reuse the low-level
CLI plumbing (command building, reply parsing, logging - see
wilds.brain.cli.CLIBrain) but override decide/reflect/converse to use
cyberpunk prompts, schemas and dataclasses instead of Tau-7's. Some structure
duplication versus wilds/brain/claude.py|codex.py is intentional: forcing one
shared abstraction across two unrelated domains (planet survival vs a city
block) would trade a little repetition for a worse, more tangled interface.
If a third chapter ever needs this, that is the point to generalize CLIBrain.
"""

from __future__ import annotations

from typing import Any

from ..brain.claude import ClaudeBrain
from ..brain.cli import _num
from ..brain.codex import CodexBrain
from .actions import ACTION_HELP
from .observe import (
    build_conversation_prompt,
    build_observation,
    build_reflection_prompt,
    conversation_system,
    reflection_system,
    system_prompt,
)
from .scripted import CyberScriptedBrain


def _obj(props: dict[str, Any], strict: bool) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def decision_schema(strict: bool) -> dict[str, Any]:
    return _obj({
        "thought": {"type": "string", "description": "1-2 short first-person sentences"},
        "action": {"type": "string", "enum": list(ACTION_HELP)},
        "target": {"type": "string", "description": "action target, or empty string"},
    }, strict)


def reflection_schema(strict: bool) -> dict[str, Any]:
    return _obj({
        "diary": {"type": "string", "description": "first-person diary entry, max 90 words"},
        "trait": {"type": "string", "description": "a new trait formed today (max 6 words) or empty"},
        "goal": {"type": "string", "description": "concrete priority for tomorrow, max 15 words"},
    }, strict)


def conversation_schema(strict: bool) -> dict[str, Any]:
    line = _obj({"speaker": {"type": "string", "enum": ["hero", "npc"]}, "text": {"type": "string"}}, True)
    return _obj({
        "lines": {"type": "array", "items": line, "description": "2-4 short alternating lines"},
        "trust_delta": {"type": "number", "description": "-0.15..0.15 change of trust in the hero"},
        "affinity_delta": {"type": "number", "description": "-0.15..0.15 change of warmth to the hero"},
        "request": {"type": "string", "description": "something the NPC asks the hero to do, or empty"},
    }, strict)


class _CyberBrainMixin:
    """Shared decide/reflect/converse logic; mixed into the Claude/Codex subclasses."""

    def _setup(self) -> None:
        self.system = system_prompt(self.lang)
        self.fallback = CyberScriptedBrain()

    def decide(self, sim):
        from .sim import Decision

        out = self.ask(sim, "decide", self.system, build_observation(sim), decision_schema(self.strict_schemas))
        if out is None or not isinstance(out.get("action"), str):
            return self._reflex(sim)
        return Decision(action=out["action"], target=str(out.get("target", "") or ""),
                        thought=str(out.get("thought", "") or "").strip())

    def reflect(self, sim):
        from .sim import Reflection

        out = self.ask(sim, "reflect", reflection_system(self.lang), build_reflection_prompt(sim),
                       reflection_schema(self.strict_schemas))
        if out is None or not str(out.get("diary", "")).strip():
            return self.fallback.reflect(sim)
        return Reflection(str(out["diary"]), str(out.get("trait", "") or ""), str(out.get("goal", "") or ""))

    def converse(self, sim):
        npc = next((n for n in sim.world.level.npcs if n.id == sim.pending_conversation), None)
        if npc is None:
            return self.fallback.converse(sim)
        out = self.ask(sim, "converse", conversation_system(self.lang), build_conversation_prompt(sim, npc),
                       conversation_schema(self.strict_schemas))
        lines = []
        for line in (out or {}).get("lines") or []:
            if isinstance(line, dict) and str(line.get("text", "")).strip():
                speaker = "npc" if line.get("speaker") == "npc" else "hero"
                lines.append((speaker, str(line["text"])))
        if not lines:
            return self.fallback.converse(sim)
        from .sim import Conversation

        return Conversation(lines, _num(out.get("trust_delta")), _num(out.get("affinity_delta")),
                            str(out.get("request", "") or ""))

    def _reflex(self, sim):
        decision = self.fallback.decide(sim)
        decision.thought = f"(інстинкт: {self.last_error[:60]}) {decision.thought}"
        return decision


class CyberClaudeBrain(_CyberBrainMixin, ClaudeBrain):
    name = "cyber-claude"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._setup()


class CyberCodexBrain(_CyberBrainMixin, CodexBrain):
    name = "cyber-codex"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._setup()
