from pathlib import Path

import pytest

from wilds.azeroth import scale
from wilds.azeroth.route import astar, find_route
from wilds.azeroth.terrain import Terrain
from wilds.azeroth.world import ZoneWorld

PACK = Path(__file__).parents[2] / "data" / "azeroth" / "mulgore"


@pytest.fixture(scope="module")
def world():
    return ZoneWorld(PACK, seed=1, roads=False)


def test_zone_has_the_real_size():
    geo = scale.load_geometry(PACK)
    assert (geo.width, geo.height) == (2725, 1817)  # 5450 x 3633 yards at 2 yards a tile
    assert scale.TICK_SECONDS == pytest.approx(2 / 7)


def test_pct_and_tile_round_trip_and_submap_position():
    geo = scale.load_geometry(PACK)
    x, y = geo.pct_to_tile(48.6, 58.8)
    assert geo.tile_to_pct((x, y)) == pytest.approx((48.6, 58.8), abs=0.05)
    # the centre of Thunder Bluff's own map is the centre of Thunder Bluff in the zone
    assert geo.sub_to_tile("Thunder Bluff", 50, 50) == geo.pct_to_tile(40.54, 28.33)


def test_terrain_is_deterministic_and_chunks_agree_with_tiles(world):
    other = ZoneWorld(PACK, seed=1, roads=False)
    for p in [(1324, 1068), (1100, 500), (200, 200), (1427, 1499)]:
        assert world.tile(*p) == other.tile(*p) == world.terrain.tile(*p)
    assert world.tile(-1, 5) is Terrain.VOID and world.tile(10 ** 6, 5) is Terrain.VOID


def test_the_land_is_ringed_by_impassable_mountains(world):
    assert world.tile(5, 5) is Terrain.VOID
    assert world.passable(world.nearest_passable(world.geo.pct_to_tile(48.6, 58.8)))
    assert not world.terrain.macro_walkable(5, 5)


def test_placements_cover_the_content_and_sit_on_walkable_ground(world):
    kinds = {p.kind for p in world.placements}
    assert {"npc", "mob", "subzone", "settlement"} <= kinds
    assert len(world.placements) > 250
    exact = [p for p in world.placements if not p.approx]
    on_land = sum(1 for p in exact if world.nearest_passable(p.pos, 30))
    assert on_land / len(exact) > 0.9
    assert all(p.approx for p in world.placements if p.source_map == "text")


def test_route_from_camp_narache_to_bloodhoof_is_the_real_distance(world):
    a = world.nearest_passable(world.at("Camp Narache").pos, 40)
    b = world.nearest_passable(world.geo.pct_to_tile(48.6, 58.8), 40)
    path = find_route(world, a, b)
    assert path and path[-1] == b
    assert all(world.passable(p) for p in path)
    assert all(max(abs(p[0] - q[0]), abs(p[1] - q[1])) == 1 for p, q in zip(path, path[1:]))
    yards = len(path) * scale.TILE_YARDS
    assert 800 < yards < 1200  # about 860 yards as the crow flies; the road is a little longer


def test_no_route_out_through_the_mountains(world):
    a = world.nearest_passable(world.geo.pct_to_tile(48.6, 58.8), 40)
    assert find_route(world, a, (5, 5)) is None


def test_astar_respects_walls_and_corners():
    wall = {(2, y) for y in range(0, 5)}
    free = lambda p: 0 <= p[0] < 6 and 0 <= p[1] < 8 and p not in wall  # noqa: E731
    path = astar((0, 2), (4, 2), free)
    assert path[-1] == (4, 2) and all(free(p) for p in path) and (2, 5) in path
    assert astar((0, 0), (0, 0), free) == []


def test_roads_are_laid_between_settlements():
    w = ZoneWorld(PACK, seed=1, roads=True)
    assert len(w.terrain.roads) > 1500
    a = w.nearest_passable(w.at("Camp Narache").pos, 40)
    assert any(w.tile(a[0] + dx, a[1] + dy) is Terrain.ROAD for dx in range(-60, 60, 2) for dy in range(-60, 60, 2))


def test_the_great_gate_has_a_palisade_either_side():
    from wilds.azeroth import settlements

    world = ZoneWorld(PACK, seed=3)
    built = settlements.build_structures(world)
    gate = next(s for s in built if s.sprite == "az.obj.great_gate")
    wall = [s for s in built if s.sprite == "az.obj.palisade" and abs((s.pos[0] - gate.pos[0]) + (s.pos[1] - gate.pos[1])) == 0]
    left = [s for s in wall if s.pos[0] < gate.pos[0]]
    right = [s for s in wall if s.pos[0] > gate.pos[0]]
    assert len(left) >= 3 and len(right) >= 3


def test_the_explore_brain_keeps_the_hero_standing_and_alive():
    from wilds.azeroth.brain import ExploreBrain
    from wilds.azeroth.sim import ZoneSim

    sim = ZoneSim(ZoneWorld(PACK, seed=3), seed=3)
    start = sim.hero.pos
    sim.run(ExploreBrain(), 40)
    assert sim.hero.alive and sim.hero.pos == start
