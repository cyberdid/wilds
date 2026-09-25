"""Stage 3: multiple districts connected by `travel`."""

from cp_helpers import make_world, run_until_idle

from wilds.cyberpunk.actions import TRAVEL_FEE, TRAVEL_MINUTES
from wilds.cyberpunk.sim import CitySim, Decision
from wilds.cyberpunk.worldgen import DISTRICTS, HOME_DISTRICT, OFFWORLD, generate


def test_generate_builds_all_districts_with_unique_npcs():
    world = generate(4)
    expected = {d for d, _ in DISTRICTS} | {d for d, _, _ in OFFWORLD}
    assert set(world.levels) == expected
    assert world.hero.level_id == HOME_DISTRICT
    assert world.ship is not None
    all_ids = [n.id for lv in world.levels.values() for n in lv.npcs]
    assert len(all_ids) == len(set(all_ids)), "npc ids must be unique across all locations"
    for district_id, level in world.levels.items():
        assert level.id == district_id
        assert level.passable(level.arrival)


def test_same_seed_same_districts():
    a, b = generate(2), generate(2)
    for did in a.levels:
        assert [(n.id, n.pos) for n in a.levels[did].npcs] == [(n.id, n.pos) for n in b.levels[did].npcs]


def test_travel_moves_hero_costs_time_and_nuyen():
    world = make_world(["." * 20 for _ in range(10)])
    world.hero.nuyen = 200
    other = make_world(["." * 20 for _ in range(10)], level_id="docks").levels["docks"]
    world.levels["docks"] = other
    sim = CitySim(world)
    before_tick = world.tick
    assert sim.apply(Decision("travel", "docks")) is None
    run_until_idle(sim)
    assert world.hero.level_id == "docks"
    assert world.hero.pos == other.arrival
    assert world.hero.nuyen == 200 - TRAVEL_FEE
    assert world.tick - before_tick >= TRAVEL_MINUTES - 1


def test_travel_to_unknown_district_rejected(small_world):
    sim = CitySim(small_world)
    assert "district must be one of" in sim.apply(Decision("travel", "moon_base"))


def test_travel_to_current_district_rejected(small_world):
    sim = CitySim(small_world)
    assert "already in" in sim.apply(Decision("travel", small_world.hero.level_id))


def test_travel_without_enough_nuyen_rejected(small_world):
    small_world.hero.nuyen = 1
    sim = CitySim(small_world)
    assert "transit costs" in sim.apply(Decision("travel", "docks"))


def test_cannot_go_to_or_talk_to_a_place_in_another_district():
    world = generate(6)
    hero = world.hero
    other_id = next(d for d, _ in DISTRICTS if d != hero.level_id)
    other_level = world.levels[other_id]
    hero.observe(world)  # ensure current district is populated
    # manually "remember" a place in the other district, as if seen before traveling there once
    from wilds.cyberpunk.hero import Place

    npc = other_level.npcs[0]
    hero.places[npc.id] = Place(npc.id, "npc", other_id, npc.pos, npc.name)
    sim = CitySim(world)
    error = sim.apply(Decision("go_to", npc.id))
    assert error and f"travel {other_id}" in error
    error2 = sim.apply(Decision("talk", npc.id))
    assert error2 and f"travel {other_id}" in error2


def test_full_contract_cycle_stays_within_one_district_even_with_multiple_districts():
    from wilds.cyberpunk.scripted import CyberScriptedBrain

    world = generate(5)
    sim = CitySim(world)
    sim.run(CyberScriptedBrain(), 3 * 1440)
    assert world.hero.free  # the scripted brain never needs to travel to clear the debt
