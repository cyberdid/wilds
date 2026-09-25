import json
import subprocess

from cp_helpers import make_world

from wilds.cyberpunk.brain import CyberClaudeBrain, CyberCodexBrain, decision_schema
from wilds.cyberpunk.observe import build_observation, system_prompt
from wilds.cyberpunk.sim import CitySim


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


class FakeCodexRunner:
    def __init__(self, reply: str | None, returncode: int = 0, stderr: str = "tokens used\n1,000\n"):
        self.reply, self.returncode, self.stderr = reply, returncode, stderr
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        out = cmd[cmd.index("--output-last-message") + 1]
        if self.reply is not None:
            with open(out, "w") as f:
                f.write(self.reply)
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


def _sim() -> CitySim:
    return CitySim(make_world(["." * 30 for _ in range(15)], npcs={}))


def test_claude_decide_uses_cyberpunk_schema_and_prompt():
    runner = FakeClaudeRunner(_claude_reply({"thought": "Час роздивитися Насип.", "action": "explore", "target": "any"}))
    brain = CyberClaudeBrain(runner=runner)
    d = brain.decide(_sim())
    assert (d.action, d.target) == ("explore", "any")
    cmd, kw = runner.calls[0]
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == decision_schema(strict=False)
    assert "Sprawl" in kw["input"] and "WHY YOU ARE DECIDING NOW" in kw["input"]


def test_claude_decide_falls_back_on_error():
    brain = CyberClaudeBrain(runner=FakeClaudeRunner("boom", returncode=1, stderr="not logged in"))
    sim = _sim()
    d = brain.decide(sim)
    assert d.thought.startswith("(інстинкт")
    assert sim.apply(d) is None  # the scripted fallback always picks a valid action


def test_codex_decide_reads_last_message():
    reply = json.dumps({"thought": "Погашу борг.", "action": "pay_debt", "target": ""})
    brain = CyberCodexBrain(runner=FakeCodexRunner(reply))
    d = brain.decide(_sim())
    assert d.action == "pay_debt"
    assert brain.tokens_in == 1000
    assert brain.label == "cyber-codex:gpt-5.6-luna"


def test_codex_failure_triggers_reflex():
    brain = CyberCodexBrain(runner=FakeCodexRunner(None, returncode=1, stderr="rate limited"))
    sim = _sim()
    d = brain.decide(sim)
    assert brain.errors == 1
    assert sim.apply(d) is None


def test_reflection_and_conversation_calls():
    from wilds.cyberpunk.npc import spawn_npc
    import random

    world = make_world(["." * 20 for _ in range(10)])
    world.level.npcs.append(spawn_npc("fixer_1", "fixer", (5, 5), random.Random(1)))
    sim = CitySim(world)
    sim.pending_reflection = 1

    r_reply = _claude_reply({"diary": "Перший день у Насипу минув спокійно.", "trait": "обачний", "goal": "Знайти роботу"})
    brain = CyberClaudeBrain(runner=FakeClaudeRunner(r_reply))
    r = brain.reflect(sim)
    assert r.diary.startswith("Перший день")
    sim.apply_reflection(r)
    assert world.hero.diary == [(1, r.diary)]
    assert world.hero.goal == "Знайти роботу"

    sim.pending_conversation = "fixer_1"
    c_reply = _claude_reply({"lines": [{"speaker": "npc", "text": "Чув про тебе."},
                                       {"speaker": "hero", "text": "Радий знайомству."}],
                             "trust_delta": 0.05, "affinity_delta": 0.02, "request": ""})
    brain2 = CyberClaudeBrain(runner=FakeClaudeRunner(c_reply))
    c = brain2.converse(sim)
    assert c.lines[0] == ("npc", "Чув про тебе.")
    sim.apply_conversation(c)
    assert world.level.npcs[0].last_line == "Чув про тебе."


def test_system_prompt_and_observation_mention_key_facts():
    prompt = system_prompt("Ukrainian")
    assert "Sprawl" in prompt and "Tau-7" in prompt and "- pay_debt" in prompt
    assert "- request_job" in prompt and "- complete_job" in prompt
    text = build_observation(_sim())
    for section in ("TIME:", "STATUS:", "INVENTORY:", "MAP", "LEGEND:", "@"):
        assert section in text


def test_observation_shows_active_contract():
    from wilds.cyberpunk.contracts import Contract

    sim = _sim()
    sim.world.contract = Contract("job_fixer_1_1", "fixer_1", "sprawl", (3, 3), 300, brief="Забери пакунок.")
    text = build_observation(sim)
    assert "ACTIVE CONTRACT" in text and "Забери пакунок." in text
