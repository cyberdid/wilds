"""Stage 4: the ship - launch beyond the city, refuel back home."""

from cp_helpers import make_world, run_until_idle

from wilds.cyberpunk.ship import FUEL_PRICE, LAUNCH_FUEL, MAX_FUEL, Ship
from wilds.cyberpunk.sim import CitySim, Decision
from wilds.cyberpunk.worldgen import HOME_DISTRICT, OFFWORLD, generate


def _world_with_ship(fuel=100.0, hull=100.0):
    world = make_world(["." * 20 for _ in range(10)], level_id=HOME_DISTRICT)
    world.ship = Ship(fuel=fuel, hull=hull)
    return world


def test_launch_reaches_destination_and_spends_fuel():
    world = generate(9)
    world.ship.fuel = 100.0
    sim = CitySim(world)
    assert sim.apply(Decision("launch", "orbital_station")) is None
    run_until_idle(sim, 500)
    assert world.hero.level_id == "orbital_station"
    assert world.hero.pos == world.levels["orbital_station"].arrival
    assert world.ship.fuel <= 100.0 - LAUNCH_FUEL + 1e-9


def test_launch_without_enough_fuel_rejected():
    world = _world_with_ship(fuel=5.0)
    sim = CitySim(world)
    assert "not enough fuel" in sim.apply(Decision("launch", "outpost"))


def test_launch_unknown_destination_rejected():
    world = _world_with_ship()
    sim = CitySim(world)
    assert "destination must be one of" in sim.apply(Decision("launch", "andromeda"))


def test_launch_to_current_location_rejected():
    world = _world_with_ship()
    world.hero.level_id = "orbital_station"
    sim = CitySim(world)
    assert "already at" in sim.apply(Decision("launch", "orbital_station"))


def test_wrecked_hull_blocks_launch():
    world = _world_with_ship(hull=0.0)
    sim = CitySim(world)
    assert "hull is wrecked" in sim.apply(Decision("launch", "outpost"))


def test_refuel_only_works_in_home_district():
    world = _world_with_ship(fuel=20.0)
    world.hero.level_id = "docks"
    world.hero.nuyen = 1000
    sim = CitySim(world)
    assert f"only in '{HOME_DISTRICT}'" in sim.apply(Decision("refuel_ship"))


def test_refuel_fills_up_and_charges_nuyen():
    world = _world_with_ship(fuel=20.0)
    world.hero.nuyen = 1000
    sim = CitySim(world)
    assert sim.apply(Decision("refuel_ship")) is None
    run_until_idle(sim)
    assert world.ship.fuel == MAX_FUEL
    assert world.hero.nuyen == 1000 - round((MAX_FUEL - 20.0) * FUEL_PRICE)


def test_refuel_limited_by_nuyen():
    world = _world_with_ship(fuel=0.0)
    world.hero.nuyen = FUEL_PRICE * 10
    sim = CitySim(world)
    assert sim.apply(Decision("refuel_ship")) is None
    run_until_idle(sim)
    assert world.ship.fuel == 10.0
    assert world.hero.nuyen == 0


def test_all_offworld_destinations_are_reachable_and_have_npcs():
    world = generate(3)
    for place_id, _, landmarks in OFFWORLD:
        level = world.levels[place_id]
        assert len(level.npcs) == len(landmarks)
        assert level.passable(level.arrival)


def test_offworld_place_gets_a_launch_hint_not_a_travel_hint():
    """The steering message must name the right verb: `launch` for places beyond
    the city, `travel` for other city districts (regression: it used to always say
    `travel`, even for a ship-only destination)."""
    world = generate(3)
    hero = world.hero
    station = world.levels["orbital_station"]
    npc = station.npcs[0]
    from wilds.cyberpunk.hero import Place

    hero.places[npc.id] = Place(npc.id, "npc", "orbital_station", npc.pos, npc.name)
    sim = CitySim(world)
    error = sim.apply(Decision("go_to", npc.id))
    assert error and "launch orbital_station" in error and "travel orbital_station" not in error
