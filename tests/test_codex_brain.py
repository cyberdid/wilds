import json
import subprocess

from wilds.brain.cli import reflection_schema
from wilds.brain.codex import SCHEMA, CodexBrain
from wilds.sim import Simulation
from wilds.worldgen import generate


class FakeCodex:
    """Imitates `codex exec`: writes the final message to the -o file."""

    def __init__(self, reply: str | None, returncode: int = 0, stderr: str = "tokens used\n12,345\n"):
        self.reply, self.returncode, self.stderr = reply, returncode, stderr
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        out = cmd[cmd.index("--output-last-message") + 1]
        if self.reply is not None:
            with open(out, "w") as f:
                f.write(self.reply)
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


def _reply(**kw) -> str:
    return json.dumps({"thought": "Треба води.", "action": "drink", "target": "", **kw})


def test_decide_reads_last_message_file(tmp_path):
    runner = FakeCodex(_reply())
    brain = CodexBrain(runner=runner, log_dir=tmp_path)
    d = brain.decide(Simulation(generate(1)))
    assert (d.action, d.thought) == ("drink", "Треба води.")
    assert brain.tokens_in == 12345
    assert brain.label == "codex:gpt-5.6-luna"
    assert len(list(tmp_path.glob("codex-*.jsonl"))) == 1


def test_command_uses_model_schema_and_stdin():
    runner = FakeCodex(_reply())
    brain = CodexBrain(model="gpt-5.6-luna", effort="low", runner=runner)
    brain.decide(Simulation(generate(1)))
    cmd, kw = runner.calls[0]
    assert cmd[:2] == ["codex", "exec"]
    assert cmd[cmd.index("--model") + 1] == "gpt-5.6-luna"
    assert "model_reasoning_effort=low" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[-1] == "-"
    schema = json.loads(open(cmd[cmd.index("--output-schema") + 1]).read())
    assert schema == SCHEMA
    assert "Do not run any commands" in kw["input"]
    assert "Tau-7" in kw["input"] and "WHY YOU ARE DECIDING NOW" in kw["input"]


def test_each_schema_gets_its_own_file():
    runner = FakeCodex(json.dumps({"diary": "Тихий день.", "trait": "", "goal": "Спати"}))
    brain = CodexBrain(runner=runner)
    sim = Simulation(generate(1))
    sim.pending_reflection = 1
    assert brain.reflect(sim).diary == "Тихий день."
    cmd, _ = runner.calls[0]
    assert json.loads(open(cmd[cmd.index("--output-schema") + 1]).read()) == reflection_schema(strict=True)


def test_strict_schemas_require_every_field():
    from wilds.brain.cli import conversation_schema

    for schema in (SCHEMA, reflection_schema(True), conversation_schema(True)):
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["additionalProperties"] is False
    line = conversation_schema(True)["properties"]["lines"]["items"]
    assert set(line["required"]) == set(line["properties"])


def test_stale_reply_is_not_reused():
    runner = FakeCodex(_reply())
    brain = CodexBrain(runner=runner)
    sim = Simulation(generate(1))
    assert brain.decide(sim).action == "drink"
    runner.reply = None  # codex crashed before writing anything
    d = brain.decide(sim)
    assert brain.errors == 1 and d.thought.startswith("(інстинкт")


def test_prose_around_json_is_tolerated():
    brain = CodexBrain(runner=FakeCodex("Ось моя відповідь:\n" + _reply(action="sleep")))
    assert brain.decide(Simulation(generate(1))).action == "sleep"


def test_failures_use_reflex():
    sim = Simulation(generate(1))
    for runner in (FakeCodex(None, returncode=1, stderr="Not logged in"), FakeCodex("not json at all")):
        brain = CodexBrain(runner=runner)
        brain.decide(sim)
        assert brain.errors == 1
