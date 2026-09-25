"""Shared plumbing for brains that call an agent CLI (Claude Code, Codex).

Three kinds of calls share one mechanism (`ask`): the per-action decision,
the nightly diary reflection and conversations with the other survivor.
If a call fails, the free scripted brain answers instead so the survivor
never freezes (a "reflex" fallback).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from ..actions import ACTION_HELP
from .observe import (
    build_conversation_prompt,
    build_observation,
    build_reflection_prompt,
    conversation_system,
    reflection_system,
    system_prompt,
)
from .scripted import ScriptedBrain

if TYPE_CHECKING:
    from ..sim import Conversation, Decision, Reflection, Simulation

Runner = Callable[..., subprocess.CompletedProcess]


def _obj(props: dict[str, Any], strict: bool, optional: tuple[str, ...] = ()) -> dict[str, Any]:
    required = list(props) if strict else [k for k in props if k not in optional]
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def decision_schema(strict: bool) -> dict[str, Any]:
    """JSON schema of a decision. ``strict`` (OpenAI structured outputs) needs every field required."""
    return _obj({
        "thought": {"type": "string", "description": "1-2 short first-person sentences"},
        "action": {"type": "string", "enum": list(ACTION_HELP)},
        "target": {"type": "string", "description": "action target, or empty string"},
    }, strict)


def reflection_schema(strict: bool) -> dict[str, Any]:
    return _obj({
        "diary": {"type": "string", "description": "first-person diary entry, max 90 words"},
        "trait": {"type": "string", "description": "a new psychological trait formed today (max 6 words) or empty"},
        "goal": {"type": "string", "description": "concrete priority for tomorrow, max 15 words"},
    }, strict)


def conversation_schema(strict: bool) -> dict[str, Any]:
    line = _obj({
        "speaker": {"type": "string", "enum": ["hero", "companion"]},
        "text": {"type": "string"},
    }, True)
    return _obj({
        "lines": {"type": "array", "items": line, "description": "2-4 short alternating lines"},
        "trust_delta": {"type": "number", "description": "-0.15..0.15 change of her trust in the hero"},
        "affinity_delta": {"type": "number", "description": "-0.15..0.15 change of her warmth to the hero"},
        "request": {"type": "string", "description": "something she asks the hero to do, or empty"},
    }, strict)


class CLIBrain:
    """Subclasses implement ``run(system, prompt, schema) -> dict``."""

    name = "cli"
    strict_schemas = False

    def __init__(
        self,
        model: str,
        lang: str = "Ukrainian",
        timeout: float = 180,
        log_dir: Path | None = None,
        runner: Runner = subprocess.run,
    ) -> None:
        self.model = model
        self.lang = lang
        self.timeout = timeout
        self.runner = runner
        self.system = system_prompt(lang)
        self.fallback = ScriptedBrain()
        self.workdir = Path(tempfile.mkdtemp(prefix=f"wilds-{self.name}-"))  # keep project files out of context
        self.log_path: Path | None = None
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_path = log_dir / f"{self.name}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        self.calls = 0
        self.errors = 0
        self.last_error = ""
        self.last_latency = 0.0
        self.tokens_in = 0
        self.tokens_out = 0

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"

    # --- to implement -----------------------------------------------------
    def run(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """One CLI call; return the reply object or raise ValueError/OSError/TimeoutExpired."""
        raise NotImplementedError

    # --- the three kinds of calls -------------------------------------------
    def decide(self, sim: "Simulation") -> "Decision":
        from ..sim import Decision

        out = self.ask(sim, "decide", self.system, build_observation(sim), decision_schema(self.strict_schemas))
        if out is None or not isinstance(out.get("action"), str):
            return self._reflex(sim)
        return Decision(
            action=out["action"],
            target=str(out.get("target", "") or ""),
            thought=str(out.get("thought", "") or "").strip(),
        )

    def reflect(self, sim: "Simulation") -> "Reflection":
        from ..sim import Reflection

        out = self.ask(sim, "reflect", reflection_system(self.lang), build_reflection_prompt(sim),
                       reflection_schema(self.strict_schemas))
        if out is None or not str(out.get("diary", "")).strip():
            return self.fallback.reflect(sim)
        return Reflection(str(out["diary"]), str(out.get("trait", "") or ""), str(out.get("goal", "") or ""))

    def converse(self, sim: "Simulation") -> "Conversation":
        from ..sim import Conversation

        out = self.ask(sim, "converse", conversation_system(self.lang), build_conversation_prompt(sim),
                       conversation_schema(self.strict_schemas))
        lines = []
        for line in (out or {}).get("lines") or []:
            if isinstance(line, dict) and str(line.get("text", "")).strip():
                speaker = "companion" if line.get("speaker") == "companion" else "hero"
                lines.append((speaker, str(line["text"])))
        if not lines:
            return self.fallback.converse(sim)
        return Conversation(lines, _num(out.get("trust_delta")), _num(out.get("affinity_delta")),
                            str(out.get("request", "") or ""))

    # --- shared -----------------------------------------------------------
    def ask(self, sim: "Simulation", kind: str, system: str, prompt: str,
            schema: dict[str, Any]) -> dict[str, Any] | None:
        started = time.monotonic()
        self.calls += 1
        out: dict[str, Any] | None = None
        error = ""
        try:
            out = self.run(system, prompt, schema)
            if not isinstance(out, dict):
                raise ValueError("reply was not a JSON object")
        except subprocess.TimeoutExpired:
            error = f"timeout after {self.timeout:.0f}s"
        except (OSError, ValueError) as exc:
            error = str(exc) or type(exc).__name__
        self.last_latency = time.monotonic() - started
        if error:
            out = None
            self.errors += 1
            self.last_error = error[:200]
        self._log(sim, kind, prompt, out, error)
        return out

    def _reflex(self, sim: "Simulation") -> "Decision":
        """The model failed: act on instinct (scripted rules) instead of freezing."""
        decision = self.fallback.decide(sim)
        decision.thought = f"(інстинкт: {self.last_error[:60]}) {decision.thought}"
        return decision

    def _log(self, sim: "Simulation", kind: str, prompt: str, out: Any, error: str) -> None:
        if not self.log_path:
            return
        record = {
            "tick": sim.world.tick,
            "kind": kind,
            "model": self.model,
            "latency": round(self.last_latency, 2),
            "prompt": prompt,
            "reply": out,
            "error": error,
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def last_line(proc: subprocess.CompletedProcess) -> str:
    lines = (proc.stderr or proc.stdout or "").strip().splitlines()
    return lines[-1] if lines else "no output"
