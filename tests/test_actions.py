from conftest import make_world, run_until_idle

from wilds.sim import Decision, Simulation
from wilds.tiles import Tile


def test_drink_walks_to_water_and_fills_up(small_world):
    small_world.hero.hydration = 20
    sim = Simulation(small_world)
    assert sim.apply(Decision("drink")) is None
    run_until_idle(sim)
    assert small_world.hero.hydration >= 98
    assert sim.history[-1].outcome.startswith("done")


def test_gather_fiber_and_craft_blade(small_world):
    hero = small_world.hero
    sim = Simulation(small_world)
    sim.apply(Decision("gather", "fiber 2"))
    run_until_idle(sim)
    assert hero.inventory["fiber"] == 2
    sim.apply(Decision("gather", "ore"))
    run_until_idle(sim)
    assert hero.inventory["ore"] >= 1
    assert sim.apply(Decision("craft", "blade")) is None
    run_until_idle(sim)
    assert hero.inventory["blade"] == 1
    assert hero.inventory["fiber"] == 0
    assert hero.attack_power == 5


def test_craft_several_flares(small_world):
    hero = small_world.hero
    hero.inventory["fiber"] = 5
    sim = Simulation(small_world)
    sim.apply(Decision("craft", "flare 3"))
    run_until_idle(sim)
    assert hero.inventory["flare"] == 3
    assert hero.inventory["fiber"] == 2


def test_craft_without_materials_is_rejected(small_world):
    sim = Simulation(small_world)
    error = sim.apply(Decision("craft", "blade"))
    assert error and "not enough" in error
    assert sim.action is None
    assert sim.history[-1].outcome.startswith("rejected")


def test_unknown_action_is_rejected(small_world):
    sim = Simulation(small_world)
    assert "unknown action" in sim.apply(Decision("teleport"))


def test_three_rejections_fall_back_to_rest(small_world):
    sim = Simulation(small_world)
    sim.apply(Decision("teleport"))
    sim.apply(Decision("teleport"))
    sim.apply(Decision("teleport"))
    assert sim.action is not None and sim.action.name == "rest"


def test_build_heater_warms_and_cooks(small_world):
    hero = small_world.hero
    hero.inventory.update({"fiber": 3, "ore": 2, "raw_meat": 2})
    hero.warmth = 30
    sim = Simulation(small_world)
    assert sim.apply(Decision("build", "heater")) is None
    run_until_idle(sim)
    assert small_world.level.heaters
    assert any(p.kind == "camp" for p in hero.places.values())
    sim.apply(Decision("cook"))
    run_until_idle(sim)
    assert hero.inventory["cooked_meat"] == 2
    assert hero.warmth > 30


def test_eat_picks_best_food(small_world):
    hero = small_world.hero
    hero.satiety = 20
    hero.inventory.update({"spores": 3, "cooked_meat": 1})
    sim = Simulation(small_world)
    sim.apply(Decision("eat"))
    run_until_idle(sim)
    assert hero.inventory["cooked_meat"] == 0
    assert hero.satiety >= 59


def test_eat_raw_meat_hurts_but_is_not_an_attack(small_world):
    hero = small_world.hero
    hero.inventory["raw_meat"] = 1
    sim = Simulation(small_world)
    sim.apply(Decision("eat", "raw_meat"))
    sim.tick()
    assert hero.hp < 100
    assert "hurt" not in sim.history[-1].outcome


def test_hunt_hopper_gives_meat():
    world = make_world([
        "..........",
        ".@....r...",
        "..........",
    ])
    world.hero.inventory["blade"] = 1
    sim = Simulation(world)
    assert sim.apply(Decision("hunt", "hopper")) is None
    run_until_idle(sim)
    assert world.hero.kills["hopper"] == 1
    assert world.hero.inventory["raw_meat"] == 1


def test_explore_reveals_new_tiles():
    rows = ["." * 60 for _ in range(20)]
    rows[10] = "." * 5 + "@" + "." * 54
    world = make_world(rows)
    before = len(world.hero.known("surface"))
    sim = Simulation(world)
    assert sim.apply(Decision("explore", "E")) is None
    run_until_idle(sim)
    assert len(world.hero.known("surface")) > before
    assert world.hero.pos[0] > 5


def test_sleep_restores_energy(small_world):
    hero = small_world.hero
    hero.energy = 40
    sim = Simulation(small_world)
    sim.apply(Decision("sleep"))
    run_until_idle(sim)
    assert hero.energy >= 99
    assert not hero.sleeping


def test_enter_and_leave_wreck():
    from wilds.worldgen import generate

    world = generate(5)
    hero = world.hero
    wreck_pos, wreck_name = next(iter(world.surface.entrances.items()))
    hero.pos = wreck_pos
    hero.observe(world)
    sim = Simulation(world)
    assert sim.apply(Decision("enter")) is None
    run_until_idle(sim)
    assert world.level.dark and world.level.name == wreck_name
    assert hero.pos == world.level.exit_pos
    sim.apply(Decision("leave"))
    run_until_idle(sim)
    assert hero.level_id == "surface" and hero.pos == wreck_pos


def test_heater_needs_open_ground():
    world = make_world([
        "TTT",
        "T@T",
        "TTT",
    ])
    world.hero.inventory.update({"fiber": 3, "ore": 2})
    world.levels["surface"].set_tile(world.hero.pos, Tile.FLORA)
    sim = Simulation(world)
    assert "no free" in sim.apply(Decision("build", "heater"))


def test_night_sleep_lasts_until_dawn_even_when_rested(small_world):
    small_world.tick = 22 * 60
    small_world.hero.energy = 95
    sim = Simulation(small_world)
    assert sim.apply(Decision("sleep")) is None
    run_until_idle(sim, 1000)
    assert 6 <= small_world.hour < 7
    assert "dawn" in sim.history[-1].outcome


def test_daytime_sleep_needs_tiredness(small_world):
    small_world.hero.energy = 95
    assert "not tired" in Simulation(small_world).apply(Decision("sleep"))
