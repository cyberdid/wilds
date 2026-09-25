from wilds.pathfinding import find_path
from wilds.tiles import Tile
from wilds.worldgen import generate, largest_region


def _tiles(level):
    return [[t.name for t in row] for row in level.tiles]


def test_same_seed_same_world():
    a, b = generate(42), generate(42)
    assert _tiles(a.surface) == _tiles(b.surface)
    assert a.hero.pos == b.hero.pos
    assert _tiles(a.levels["wreck_2"]) == _tiles(b.levels["wreck_2"])


def test_different_seeds_differ():
    assert _tiles(generate(1).surface) != _tiles(generate(2).surface)


def test_world_is_playable():
    for seed in range(5):
        world = generate(seed)
        surface = world.surface
        region = largest_region(surface)
        assert world.hero.pos in region
        assert surface.tile(world.hero.pos) is Tile.MOSS
        # three wrecks, each reachable and leading to a level with an exit hatch and an artifact
        assert len(surface.entrances) == 3
        for pos in surface.entrances:
            assert pos in region
        for lid in ("wreck_1", "wreck_2", "wreck_3"):
            wreck = world.levels[lid]
            assert wreck.dark
            assert wreck.tile(wreck.exit_pos) is Tile.HATCH
            assert any("artifact" in items for items in wreck.items.values())
            full = {p: wreck.tile(p) for p in wreck.positions()}
            for item_pos in wreck.items:
                assert find_path(wreck, full, wreck.exit_pos, lambda p, t=item_pos: p == t,
                                 allow_unknown=False) is not None


def test_hero_starts_seeing_surroundings():
    world = generate(3)
    assert world.hero.pos in world.hero.visible
    assert len(world.hero.known("surface")) > 50
