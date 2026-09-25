"""The narrative bridge: Tau-7 rescue -> legacy JSON -> cyberpunk chapter."""

from wilds.cyberpunk.legacy import import_legacy
from wilds.legacy_export import BASE_NUYEN, write_legacy
from wilds.sim import Simulation
from wilds.worldgen import generate as generate_tau7


def test_write_legacy_captures_name_traits_nuyen(tmp_path):
    world = generate_tau7(2)
    hero = world.hero
    hero.name = "Тестовий Герой"
    hero.traits = ["впертий", "обережний"]
    hero.diary = [(1, "Перший день."), (2, "Другий день, важкий.")]
    hero.inventory["artifact"] = 3

    path = write_legacy(world, "claude", tmp_path)
    legacy = import_legacy(path)

    assert legacy.name == "Тестовий Герой"
    assert legacy.traits == ["впертий", "обережний"]
    assert "Другий день, важкий." in legacy.summary
    assert legacy.starting_nuyen == BASE_NUYEN + 3 * 500
    assert legacy.source_seed == 2


def test_write_legacy_without_diary_or_artifacts(tmp_path):
    world = generate_tau7(3)
    path = write_legacy(world, "codex", tmp_path)
    legacy = import_legacy(path)
    assert legacy.summary == ""
    assert legacy.starting_nuyen == BASE_NUYEN
    assert legacy.race == ""  # Tau-7 has no races; the cyberpunk chapter rolls one


def test_legacy_written_only_on_rescue(tmp_path):
    from wilds.brain import ScriptedBrain

    world = generate_tau7(4)
    sim = Simulation(world)
    sim.legacy_dir = tmp_path
    sim.brain_name = "claude"
    sim.run(ScriptedBrain(), 200)  # short run, nowhere near the beacon/rescue
    assert not world.hero.rescued
    assert sim.legacy_path is None
    assert list(tmp_path.glob("*.json")) == []
