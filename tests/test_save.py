import copy

from wilds.brain import ScriptedBrain
from wilds.save import latest_save, load_game, save_game, save_path
from wilds.sim import Simulation
from wilds.worldgen import generate


def test_save_and_load_roundtrip(tmp_path):
    world = generate(3)
    events = []
    world.listeners.append(events.append)
    sim = Simulation(world)
    sim.run(ScriptedBrain(), 2 * 24 * 60)
    path = save_game(sim, save_path(sim, "scripted", tmp_path), {"wrecks_done": ["wreck_1"]})
    assert world.listeners, "listeners are restored after saving"
    assert latest_save(tmp_path) == path

    loaded, state = load_game(path)
    assert state == {"wrecks_done": ["wreck_1"]}
    w2 = loaded.world
    assert w2.tick == world.tick and w2.hero.pos == world.hero.pos
    assert w2.hero.inventory == world.hero.inventory
    assert w2.hero.diary == world.hero.diary
    assert w2.pod.power == world.pod.power
    assert w2.listeners == []
    assert loaded.decisions == sim.decisions


def test_loaded_game_continues_exactly_like_the_original(tmp_path):
    sim = Simulation(generate(4))
    brain = ScriptedBrain()
    sim.run(brain, 30 * 60)
    path = save_game(sim, tmp_path / "a.wsav")
    brain_copy = copy.deepcopy(brain)

    sim.run(brain, 24 * 60)
    loaded, _ = load_game(path)
    loaded.run(brain_copy, 24 * 60)
    assert loaded.world.tick == sim.world.tick
    assert loaded.world.hero.pos == sim.world.hero.pos
    assert loaded.world.hero.inventory == sim.world.hero.inventory
    assert [e.text for e in loaded.world.events] == [e.text for e in sim.world.events]


def test_new_creatures_after_load_get_fresh_ids(tmp_path):
    from wilds.creatures import spawn

    sim = Simulation(generate(1))
    loaded, _ = load_game(save_game(sim, tmp_path / "b.wsav"))
    ids = {c.id for lv in loaded.world.levels.values() for c in lv.creatures}
    assert spawn("hopper", (0, 0)).id not in ids


def test_load_backfills_attributes_added_after_the_save_was_written(tmp_path):
    """A pickled Simulation calls __new__, not __init__, on load - attributes
    added to __init__ in a later code version must not raise AttributeError
    on an older save (regression: this crashed exactly at the rescue moment,
    since _check_rescue reads self.legacy_dir)."""
    sim = Simulation(generate(1))
    del sim.__dict__["legacy_dir"]
    del sim.__dict__["brain_name"]
    del sim.__dict__["legacy_path"]
    path = save_game(sim, tmp_path / "old.wsav")

    loaded, _ = load_game(path)
    assert loaded.legacy_dir is None
    assert loaded.brain_name == "hero"
    assert loaded.legacy_path is None
