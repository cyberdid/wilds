from wilds.cyberpunk.legacy import Legacy
from wilds.cyberpunk.worldgen import LANDMARKS, generate
from wilds.pathfinding import find_path


def _tiles(level):
    return [[t.name for t in row] for row in level.tiles]


def test_same_seed_same_world():
    a, b = generate(1), generate(1)
    assert _tiles(a.level) == _tiles(b.level)
    assert a.hero.pos == b.hero.pos
    assert [(n.id, n.name, n.pos) for n in a.level.npcs] == [(n.id, n.name, n.pos) for n in b.level.npcs]


def test_different_seeds_differ():
    assert _tiles(generate(1).level) != _tiles(generate(2).level)


def test_all_landmarks_placed_and_reachable():
    for seed in range(5):
        world = generate(seed)
        level = world.level
        assert len(level.npcs) == len(LANDMARKS)
        full_map = {p: level.tile(p) for p in level.positions()}
        for npc in level.npcs:
            assert level.tile(npc.pos).passable
            path = find_path(level, full_map, world.hero.pos, lambda p, t=npc.pos: p == t, allow_unknown=False)
            assert path is not None, f"{npc.id} unreachable on seed {seed}"


def test_hero_starts_seeing_surroundings():
    world = generate(3)
    assert world.hero.pos in world.hero.visible
    assert len(world.hero.known()) > 30


def test_no_legacy_gives_random_race_and_base_nuyen():
    world = generate(7)
    assert world.hero.nuyen == 200
    assert world.hero.debt == 5000


def test_legacy_seeds_name_race_traits_and_nuyen():
    legacy = Legacy(name="Мандрівниця", race="TROLL", traits=["впертий"], summary="Пережила Тау-7.",
                    starting_nuyen=2300, source_seed=9)
    world = generate(9, legacy)
    hero = world.hero
    assert hero.name == "Мандрівниця"
    assert hero.race.name == "TROLL"
    assert hero.nuyen == 2300
    assert hero.traits == ["впертий"]
    assert hero.diary == [(0, "Пережила Тау-7.")]


def test_legacy_without_race_still_rolls_one():
    legacy = Legacy(name="Хтось", race="", starting_nuyen=500)
    world = generate(2, legacy)
    assert world.hero.race is not None


def test_no_duplicate_landmark_place_for_an_npc_standing_on_one():
    """A checkpoint/shop/bar/fixer tile with an NPC on it should surface once,
    as the npc place - not also as a separate landmark place (regression)."""
    from wilds.cyberpunk.sim import CitySim
    from wilds.cyberpunk.scripted import CyberScriptedBrain

    world = generate(11)
    sim = CitySim(world)
    sim.run(CyberScriptedBrain(), 3000)
    positions = [p.pos for p in world.hero.places.values()]
    assert len(positions) == len(set(positions)), world.hero.places
