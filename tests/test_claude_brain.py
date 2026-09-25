import json
import subprocess

from wilds.brain.claude import SCHEMA, ClaudeBrain
from wilds.brain.cli import conversation_schema, reflection_schema
from wilds.brain.observe import build_observation, system_prompt
from wilds.sim import Simulation
from wilds.worldgen import generate


def _reply(out: dict, **extra) -> str:
    return json.dumps({"type": "result", "is_error": False, "structured_output": out,
                       "usage": {"input_tokens": 100, "output_tokens": 20}, **extra})


class FakeRunner:
    def __init__(self, stdout="", returncode=0, stderr="", exc=None):
        self.stdout, self.returncode, self.stderr, self.exc = stdout, returncode, stderr, exc
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, self.stderr)


def test_decide_uses_structured_output(tmp_path):
    runner = FakeRunner(_reply({"thought": "Хочу пити.", "action": "drink", "target": ""}))
    brain = ClaudeBrain(runner=runner, log_dir=tmp_path)
    d = brain.decide(Simulation(generate(1)))
    assert (d.action, d.thought) == ("drink", "Хочу пити.")
    cmd, kw = runner.calls[0]
    assert cmd[:2] == ["claude", "-p"]
    assert "--json-schema" in cmd and "--strict-mcp-config" in cmd
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == SCHEMA
    assert "WHY YOU ARE DECIDING NOW" in kw["input"]
    assert brain.tokens_in == 100
    assert len(list(tmp_path.glob("claude-*.jsonl"))) == 1


def test_decision_schema_has_no_note_field():
    assert set(SCHEMA["properties"]) == {"thought", "action", "target"}


def test_thinking_disabled_by_default():
    assert any("alwaysThinkingEnabled" in part for part in ClaudeBrain().command())
    assert not any("alwaysThinkingEnabled" in part for part in ClaudeBrain(thinking=True).command())


def test_falls_back_to_result_text():
    stdout = json.dumps({"is_error": False, "result": json.dumps({"action": "sleep", "target": "", "thought": "zz"})})
    brain = ClaudeBrain(runner=FakeRunner(stdout))
    assert brain.decide(Simulation(generate(1))).action == "sleep"


def test_failures_trigger_reflex_brain():
    sim = Simulation(generate(1))
    for runner in (
        FakeRunner("not json", returncode=1, stderr="Not logged in"),
        FakeRunner(json.dumps({"is_error": True, "result": "rate limited"})),
        FakeRunner(exc=subprocess.TimeoutExpired("claude", 1)),
        FakeRunner(exc=FileNotFoundError("claude")),
    ):
        brain = ClaudeBrain(runner=runner)
        d = brain.decide(sim)
        assert brain.errors == 1
        assert d.thought.startswith("(інстинкт")
        assert sim.apply(d) is None  # the scripted fallback picks a valid action
        sim.action = None


def test_reflection_call():
    out = {"diary": "Сьогодні я вперше побачив ксенопса.", "trait": "боїться темряви", "goal": "Знайти сплав"}
    runner = FakeRunner(_reply(out))
    brain = ClaudeBrain(runner=runner)
    world = generate(1)
    sim = Simulation(world)
    sim.pending_reflection = 1
    r = brain.reflect(sim)
    assert r.diary.startswith("Сьогодні") and r.trait == "боїться темряви"
    cmd, kw = runner.calls[0]
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == reflection_schema(strict=False)
    assert "diary" in cmd[cmd.index("--system-prompt") + 1]
    assert "WHAT HAPPENED TODAY" in kw["input"]
    sim.apply_reflection(r)
    assert world.hero.goal == "Знайти сплав"
    assert world.hero.traits == ["боїться темряви"]
    assert world.hero.diary == [(1, r.diary)]
    assert sim.pending_reflection is None


def test_failed_reflection_uses_template():
    brain = ClaudeBrain(runner=FakeRunner("garbage", returncode=1))
    sim = Simulation(generate(1))
    sim.pending_reflection = 1
    r = brain.reflect(sim)
    assert r.diary.startswith("Сол 1")
    assert r.goal


def test_conversation_call():
    from wilds.companion import Companion

    world = generate(1)
    world.companion = Companion(pos=world.hero.pos, state="working")
    out = {"lines": [{"speaker": "companion", "text": "Привіт"}, {"speaker": "hero", "text": "Тримайся"}],
           "trust_delta": 0.9, "affinity_delta": -0.05, "request": "Принеси води"}
    runner = FakeRunner(_reply(out))
    brain = ClaudeBrain(runner=runner)
    sim = Simulation(world)
    c = brain.converse(sim)
    assert c.lines == [("companion", "Привіт"), ("hero", "Тримайся")]
    cmd, _ = runner.calls[0]
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == conversation_schema(strict=False)
    sim.apply_conversation(c)
    assert abs(world.companion.trust - 0.55) < 1e-9  # +0.9 is clamped to +0.15
    assert world.companion.request == "Принеси води"
    assert world.companion.last_line == "Привіт"


def test_observation_contains_key_sections():
    world = generate(2)
    text = build_observation(Simulation(world))
    for section in ("TIME:", "STATUS:", "INVENTORY:", "POD (pod_1", "MAP", "LEGEND:", "@", "dx="):
        assert section in text


def test_system_prompt_mentions_goal_language_and_actions():
    prompt = system_prompt("Ukrainian")
    assert "Ukrainian" in prompt and "beacon" in prompt
    for action in ("- craft <blade|flare [count]>", "- pod <", "- routine <night|supplies>", "- talk", "- give"):
        assert action in prompt
