from conftest import make_world

from wilds.brain import ScriptedBrain
from wilds.creatures import spawn
from wilds.sim import Decision, Simulation
from wilds.tiles import Tile
from wilds.worldgen import generate


def test_scripted_brain_survives_several_days():
    for seed in (0, 1, 2):
        world = generate(seed)
        sim = Simulation(world)
        sim.run(ScriptedBrain(), 2 * 24 * 60)
        assert world.day >= 2 or not world.hero.alive
        # the brain should not be consulted every few ticks
        assert sim.decisions < 2 * 24 * 60 / 5


def test_hound_interrupts_long_action():
    world = make_world([
        "..............................",
        ".@............................",
        "..............................",
        "..............................",
    ])
    sim = Simulation(world)
    sim.apply(Decision("rest", "120"))
    sim.tick()
    world.level.creatures.append(spawn("hound", (9, 3)))
    for _ in range(120):
        if sim.action is None:
            break
        sim.tick()
    assert sim.action is None
    assert "hound appeared" in sim.history[-1].outcome


def test_same_hound_does_not_interrupt_again_right_away():
    world = make_world([
        "..........",
        ".@......w.",
    ])
    sim = Simulation(world)
    sim.apply(Decision("fight"))
    sim.tick()  # sees the hound while fighting: remembered, no interrupt
    sim.action = None
    sim.apply(Decision("rest", "5"))
    sim.tick()
    assert sim.action is None or "hound appeared" not in (sim.history[-1].outcome or "")


def test_low_need_interrupts_once():
    world = make_world(["......", ".@...."])
    world.hero.hydration = 25.2
    sim = Simulation(world)
    sim.apply(Decision("rest", "60"))
    for _ in range(5):
        sim.tick()
    assert sim.action is None
    assert "hydration is low" in sim.history[-1].outcome
    sim.apply(Decision("rest", "5"))
    for _ in range(5):
        sim.tick()
    assert sim.history[-1].outcome.startswith("done")


def test_nightfall_interrupts():
    world = make_world(["......", ".@...."], tick=19 * 60 + 50)
    sim = Simulation(world)
    sim.apply(Decision("rest", "60"))
    for _ in range(60):
        if sim.action is None:
            break
        sim.tick()
    assert "night is falling" in sim.history[-1].outcome


def test_death_leaves_a_grave():
    world = make_world(["......", ".@...."])
    hero = world.hero
    hero.hp = 0.1
    hero.hydration = 0
    sim = Simulation(world)
    sim.apply(Decision("rest", "10"))
    sim.tick()
    assert not hero.alive
    assert hero.cause_of_death == "спрага"
    assert world.level.tile(hero.pos) is Tile.GRAVE
    assert not sim.needs_decision
    assert world.events[-1].kind == "death"


def test_heater_keeps_hounds_away():
    world = make_world([
        "............",
        ".@..........",
        "............",
    ])
    hero = world.hero
    hero.inventory.update({"fiber": 3, "ore": 2})
    sim = Simulation(world)
    sim.apply(Decision("build", "heater"))
    for _ in range(20):
        if sim.action is None:
            break
        sim.tick()
    assert world.level.heaters
    world.level.creatures.append(spawn("hound", (9, 1)))
    hp_after_build = hero.hp
    sim.apply(Decision("rest", "60"))
    for _ in range(60):
        if sim.action is None:
            sim.apply(Decision("rest", "60"))
        sim.tick()
    assert hero.hp >= hp_after_build


def test_similar_traits_replace_each_other():
    from wilds.sim import remember

    notes: list[str] = []
    remember(notes, "Фальшфеєр потребує одного волокна для уламків")
    remember(notes, "Фальшфеєр потребує волокна, треба для уламків більше")
    remember(notes, "Громило живе біля північної флори")
    assert len(notes) == 2
    assert notes[0].startswith("Фальшфеєр потребує волокна")
    for i in range(10):
        remember(notes, f"унікальний факт номер{i} слово{i}")
    assert len(notes) == 6
