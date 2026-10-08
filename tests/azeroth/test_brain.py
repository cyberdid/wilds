"""The Claude/Codex brain of Mulgore: the right schema and prompt, a Decision from a
model reply, and the scripted fallback whenever the model fails. A live model is never
called here - the CLI runner is faked."""

import json
import subprocess
from pathlib import Path

import pytest

from wilds.azeroth.actions import ACTION_HELP
from wilds.azeroth.brain import decision_schema, make_claude_brain, make_codex_brain
from wilds.azeroth.observe import build_observation, system_prompt
from wilds.azeroth.sim import ZoneSim
from wilds.azeroth.world import ZoneWorld

PACK = Path(__file__).parents[2] / "data" / "azeroth" / "mulgore"


@pytest.fixture(scope="module")
def sim():
    return ZoneSim(ZoneWorld(PACK, seed=1, roads=False), seed=1)


def _claude_reply(out: dict) -> str:
    return json.dumps({"type": "result", "is_error": False, "structured_output": out,
                       "usage": {"input_tokens": 50, "output_tokens": 10}})


class FakeClaudeRunner:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


def test_observation_lists_the_six_actions_and_key_sections(sim):
    sys = system_prompt("Ukrainian")
    for name in ACTION_HELP:
        assert f"- {name}" in sys
    obs = build_observation(sim)
    assert "STATUS: level 1" in obs
    assert "What do you do now?" in obs


def test_decision_schema_enumerates_exactly_the_action_menu():
    schema = decision_schema(strict=False)
    assert schema["properties"]["action"]["enum"] == list(ACTION_HELP)
    assert set(schema["required"]) == {"thought", "action", "target"}


def test_claude_decide_uses_azeroth_schema_and_returns_a_decision(sim):
    runner = FakeClaudeRunner(_claude_reply({"thought": "Візьму завдання.", "action": "talk",
                                             "target": "Grull Hawkwind"}))
    brain = make_claude_brain(runner=runner)
    d = brain.decide(sim)
    assert (d.action, d.target) == ("talk", "Grull Hawkwind")
    assert d.thought == "Візьму завдання."
    cmd, _ = runner.calls[0]
    assert cmd[cmd.index("--model") + 1] == "haiku"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == decision_schema(strict=False)


def test_a_failed_model_call_falls_back_to_the_scripted_brain(sim):
    runner = FakeClaudeRunner(stdout="not json", returncode=1)
    brain = make_claude_brain(runner=runner)
    d = brain.decide(sim)
    assert d.action in ACTION_HELP          # a real, playable action from the rules
    assert "інстинкт" in d.thought           # marked as a reflex, not a model choice


def test_model_choice_is_configurable(sim):
    runner = FakeClaudeRunner(_claude_reply({"thought": "x", "action": "explore", "target": ""}))
    brain = make_claude_brain(model="sonnet", runner=runner)
    brain.decide(sim)
    cmd, _ = runner.calls[0]
    assert cmd[cmd.index("--model") + 1] == "sonnet"


def test_codex_brain_builds_with_the_mixin():
    brain = make_codex_brain()
    assert brain.name == "codex"
    assert hasattr(brain, "decide") and hasattr(brain, "fallback")
