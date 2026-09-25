"""Pod & beacon, Director-7, the second survivor, routines, diary and metrics."""

from conftest import run_until_idle

from wilds.actions import ACTION_HELP
from wilds.brain import ScriptedBrain
from wilds.companion import Companion
from wilds.director import GRACE_TICKS, Event
from wilds.pod import CELL_POWER, RESCUE_DELAY, TRANSMIT_POWER
from wilds.sim import Decision, Reflection, Simulation
from wilds.tiles import Tile
from wilds.worldgen import generate


def _at_pod(seed: int = 3):
    world = generate(seed)
    world.hero.pos = next(q for q in world.surface.neighbors(world.pod.pos) if world.surface.passable(q))
    world.hero.observe(world)
    return world, Simulation(world)


# --- pod ---------------------------------------------------------------------------


def test_world_starts_with_pod_next_to_hero():
    world = generate(1)
    assert world.surface.tile(world.pod.pos) is Tile.POD
    assert max(abs(a - b) for a, b in zip(world.pod.pos, world.hero.pos)) == 1
    assert "pod_1" in world.hero.places
    assert world.director is not None


def test_every_world_has_enough_beacon_parts():
    for seed in range(4):
        world = generate(seed)
        items = [i for lv in world.levels.values() for stack in lv.items.values() for i in stack]
        assert items.count("alloy") >= 3 and items.count("circuit") >= 1


def test_pod_heater_warms_and_drains_power():
    world, sim = _at_pod()
    world.tick = 22 * 60  # night
    world.hero.warmth = 40
    power = world.pod.power
    sim.apply(Decision("pod", "heater_on"))
    run_until_idle(sim)
    assert world.pod.heating
    sim.apply(Decision("rest", "60"))
    run_until_idle(sim)
    assert world.pod.power < power
    assert world.hero.warmth > 40


def test_charge_repair_beacon_transmit_rescue():
    world, sim = _at_pod()
    hero, pod = world.hero, world.pod
    hero.inventory.update({"power_cell": 2, "alloy": 3, "circuit": 1, "ore": 2})
    before = pod.power
    sim.apply(Decision("pod", "charge"))
    run_until_idle(sim)
    assert abs(pod.power - min(100, before + 2 * CELL_POWER)) < 1  # plus a little solar trickle

    assert "beacon first" in sim.apply(Decision("pod", "transmit"))
    sim.apply(Decision("pod", "beacon"))
    run_until_idle(sim)
    assert pod.beacon_repaired and hero.inventory["alloy"] == 0

    pod.power = TRANSMIT_POWER + 5
    sim.apply(Decision("pod", "transmit"))
    run_until_idle(sim)
    assert pod.rescue_at is not None and pod.rescue_at - world.tick <= RESCUE_DELAY
    world.tick = pod.rescue_at
    sim.apply(Decision("rest", "5"))
    sim.tick()
    assert hero.rescued and sim.over and sim.pending is None
    assert world.events[-1].kind == "victory"


def test_transmit_needs_power():
    world, sim = _at_pod()
    world.pod.beacon_repaired = True
    world.pod.power = 10
    assert "needs" in sim.apply(Decision("pod", "transmit"))


def test_pod_fault_blocks_heater_until_repaired():
    world, sim = _at_pod()
    world.pod.fault = True
    assert "fault" in sim.apply(Decision("pod", "heater_on"))
    sim.action = None
    world.hero.inventory["ore"] = 2
    sim.apply(Decision("pod", "repair"))
    run_until_idle(sim)
    assert not world.pod.fault


def test_take_from_storage():
    world, sim = _at_pod()
    world.pod.storage["fiber"] = 4
    sim.apply(Decision("pod", "take fiber"))
    run_until_idle(sim)
    assert world.hero.inventory["fiber"] == 4 and world.pod.storage["fiber"] == 0


# --- director ----------------------------------------------------------------------


def test_director_is_quiet_during_grace_then_schedules_events():
    world = generate(2)
    sim = Simulation(world)
    sim.run(ScriptedBrain(), GRACE_TICKS - world.tick - 5)
    assert not world.director.events
    sim.run(ScriptedBrain(), 4 * 24 * 60)
    assert world.director.events, "a peak must happen within a few calm sols"


def test_every_event_is_telegraphed_before_it_hits():
    world = generate(4)
    sim = Simulation(world)
    sim.run(ScriptedBrain(), 6 * 24 * 60)
    for e in world.director.events:
        assert e.starts_at - e.warn_at >= 45


def test_debris_impact_damages_and_leaves_alloy():
    world = generate(1)
    hero = world.hero
    target = hero.pos
    event = Event("orbital_debris", world.tick, world.tick, world.tick + 1, data={"pos": target})
    world.director.events.append(event)
    world.director._start(world, event)
    assert hero.hp <= 65
    assert world.surface.items[target].count("alloy") == 2
    assert any(p.kind == "debris" for p in hero.places.values())


def test_storm_limits_sight_and_chills():
    world = generate(1)
    event = Event("dust_storm", world.tick, world.tick, world.tick + 200)
    world.director.events.append(event)
    world.director._start(world, event)
    assert world.hero.sight_radius(world) == 2
    sim = Simulation(world)
    world.hero.warmth = 50
    sim.apply(Decision("rest", "30"))
    run_until_idle(sim)
    assert world.hero.warmth < 50


def test_heavy_damage_triggers_a_breather():
    world = generate(1)
    director = world.director
    director.update(world)
    world.hero.hp = 50
    world.tick += 1
    director.update(world)
    assert director.relaxing(world.tick)


# --- the second survivor -------------------------------------------------------------


def test_distress_signal_brings_a_companion_who_joins():
    world = generate(2)
    event = Event("distress_signal", world.tick, world.tick, world.tick + 1)
    from wilds.director import _crash_spot

    event.data["pos"] = _crash_spot(world)
    world.director._start(world, event)
    comp = world.companion
    assert comp is not None and comp.state == "stranded"
    assert "crash_site_1" in world.hero.places
    sim = Simulation(world)
    sim.apply(Decision("go_to", "crash_site_1"))
    run_until_idle(sim, 3000)
    sim.tick() if sim.action else None
    comp.update(world)
    assert comp.joined


def test_companion_lives_on_her_own():
    world = generate(2)
    world.companion = Companion(pos=world.pod.pos, state="working", hydration=30, satiety=80)
    for _ in range(600):
        world.companion.update(world)
        world.tick += 1
    assert world.companion.alive
    assert world.companion.hydration > 30


def test_give_food_and_talk():
    world, sim = _at_pod()
    world.companion = Companion(pos=world.hero.pos, state="working", satiety=20)
    world.hero.inventory["ration"] = 1
    sim.apply(Decision("give", "ration"))
    run_until_idle(sim)
    assert world.companion.satiety > 20 and world.companion.affinity > 0.5
    sim.apply(Decision("talk"))
    run_until_idle(sim)
    assert sim.pending == "converse"
    sim.consult(ScriptedBrain())
    assert world.companion.last_line and sim.pending == "decide"


# --- routines -------------------------------------------------------------------------


def test_night_routine_goes_home_and_sleeps():
    world = generate(3)
    world.tick = 21 * 60
    world.hero.energy = 50
    sim = Simulation(world)
    assert sim.apply(Decision("routine", "night")) is None
    for _ in range(1500):
        if sim.action is None:
            break
        sim.tick()
    assert world.hero.pos == world.pod.pos
    assert world.hero.energy > 85


def test_supplies_routine_drinks_and_stocks():
    world = generate(3)
    world.hero.hydration = 30
    sim = Simulation(world)
    assert sim.apply(Decision("routine", "supplies")) is None
    run_until_idle(sim, 3000)
    assert world.hero.hydration > 80


def test_unknown_routine_rejected():
    world = generate(3)
    assert "routine must be" in Simulation(world).apply(Decision("routine", "party"))


# --- diary and metrics ------------------------------------------------------------------


def test_midnight_asks_for_a_diary_entry(tmp_path):
    world = generate(1)
    sim = Simulation(world)
    sim.diary_path = tmp_path / "diary.md"
    world.tick = 24 * 60 - 1
    sim.apply(Decision("rest", "10"))
    sim.tick()
    assert sim.pending == "reflect" and sim.pending_reflection == 1
    sim.apply_reflection(Reflection("Перший сол позаду.", "впертий", "Знайти воду"))
    assert world.hero.diary[-1] == (1, "Перший сол позаду.")
    assert "Перший сол" in sim.diary_path.read_text()
    assert sim.pending != "reflect"


def test_metrics_summary():
    world = generate(0)
    sim = Simulation(world)
    sim.run(ScriptedBrain(), 24 * 60)
    m = sim.metrics.summary(len(ACTION_HELP))
    assert 0 < m["action_diversity"] <= 1
    assert m["explored_tiles_per_sol"] > 0
    assert 0 < m["thought_novelty"] <= 1


def test_full_scripted_story_reaches_an_ending():
    endings = []
    for seed in (0, 1):
        world = generate(seed)
        sim = Simulation(world)
        sim.run(ScriptedBrain(), 14 * 24 * 60)
        endings.append(world.hero.rescued or not world.hero.alive)
        assert world.hero.diary, "at least one diary entry"
    assert all(endings)


def test_loot_searches_a_wreck_when_nothing_is_known():
    world = generate(5)
    hero = world.hero
    wreck = world.levels["wreck_1"]
    hero.level_id, hero.pos = "wreck_1", wreck.exit_pos
    hero.inventory["headlamp"] = 1
    wreck.creatures.clear()
    hero.observe(world)
    hero.seen_items["wreck_1"] = {}
    sim = Simulation(world)
    assert sim.apply(Decision("loot")) is None
    assert sim.action.searching
    run_until_idle(sim, 1000)
    assert sum(hero.inventory.values()) > 1, sim.history[-1].outcome


def test_gather_an_item_suggests_loot():
    world = generate(5)
    assert "use loot" in Simulation(world).apply(Decision("gather", "power_cell"))
