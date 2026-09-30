"""Street scale: buildings used to be about one person tall (a 16x16 facade tile
stretched over 18-32 px), so the city read as a doll's house. Facades are now
stacked from storey modules drawn to the runner's scale."""

import pygame
import pytest

from wilds.gfx.bank import SpriteBank, _to_wall
from wilds.gfx.city_scene import CAP_H, GROUND_H, STOREY_H, STOREYS, CityScene, storeys, tallest
from wilds.gfx.render import PROJECTIONS, Renderer


@pytest.fixture(scope="module")
def bank(sprites):
    return SpriteBank(sprites)


def _person_height(bank) -> int:
    img = bank.base("cp.hero.human.idle")[0]
    rows = [y for y in range(img.get_height()) if any(img.get_at((x, y)).a for x in range(img.get_width()))]
    return max(rows) - min(rows) + 1


def test_facade_modules_are_at_street_scale(bank):
    person = _person_height(bank)
    for theme in dict.fromkeys(("sprawl", "docks", "corp", "station", "outpost")):
        for name, h in (("cap", CAP_H), ("storey", STOREY_H), ("ground", GROUND_H)):
            for v in bank.registry.variants(f"cp.{theme}.facade.{name}"):
                assert bank.base(v)[0].get_size() == (16, h), v
    assert STOREY_H > person and GROUND_H >= person + 10  # a door you walk through, a storey over your head
    assert tallest("sprawl") >= 5 * person and tallest("corp") >= 12 * person
    assert tallest("docks") < tallest("sprawl") < tallest("corp")


def test_storeys_stay_in_each_themes_range_and_are_one_per_city_block():
    for theme, (lo, hi) in STOREYS.items():
        seen = {storeys(theme, tx, ty) for tx in range(0, 46) for ty in range(0, 24)}
        assert seen <= set(range(lo, hi + 1))
        assert storeys(theme, 2, 2) == storeys(theme, 7, 4)  # same block (tx // 8, ty // 5)


def test_facade_strip_stacks_to_the_building_height(bank):
    names = ("cp.sprawl.facade.cap@0", "cp.sprawl.facade.storey@0", "cp.sprawl.facade.storey@1",
             "cp.sprawl.facade.ground@0")
    strip, glow = bank.facade(names)
    assert strip.get_size() == (16, CAP_H + 2 * STOREY_H + GROUND_H)
    assert glow is not None  # lit windows keep glowing at night
    cube, _ = bank.iso_tower("cp.sprawl.wall.top@0", names, 0.0, True, True)
    assert cube.get_size() == (32, 16 + strip.get_height())


def test_unstretched_wall_mapping_matches_the_per_pixel_one():
    src = pygame.Surface((16, 40), pygame.SRCALPHA)
    for y in range(40):
        for x in range(16):
            src.set_at((x, y), ((x * 13) % 256, (y * 7) % 256, (x * y) % 256, 255))
    for left in (True, False):
        fast = _to_wall(src, 40, left, 236)
        slow = pygame.Surface((16, 48), pygame.SRCALPHA)
        for dy in range(48):
            for dx in range(16):
                v = dy - (dx / 2 if left else 8 - dx / 2)
                if 0 <= v < 40:
                    slow.set_at((dx, dy), src.get_at((dx, int(v))))
        slow.fill((236, 236, 250, 255), special_flags=pygame.BLEND_RGBA_MULT)
        assert pygame.image.tobytes(fast, "RGBA") == pygame.image.tobytes(slow, "RGBA")


def test_blocks_between_camera_and_runner_are_cut_down(bank):
    from wilds.cyberpunk.worldgen import generate

    world = generate(157479)
    level = world.levels["sprawl"]
    scene = CityScene(Renderer(bank))
    scene._hero = (9, 6)  # a sidewalk column between two city blocks (x % 8 in (0, 1))
    frame = Renderer(bank).frame(0, 0, pygame.Rect(0, 0, 800, 600), 3, 0.0, PROJECTIONS["iso"])
    scene._cuts = {}
    assert scene._cut(frame, level, 11, 8)  # the block right in front (deeper, same screen column)
    assert not scene._cut(frame, level, 3, 2)  # a block behind the runner stays tall
    frame2d = Renderer(bank).frame(0, 0, pygame.Rect(0, 0, 800, 600), 3, 0.0, PROJECTIONS["2d"])
    scene._cuts = {}
    assert scene._cut(frame2d, level, 11, 8)  # south of him: its lifted roof would cover his street
    assert not scene._cut(frame2d, level, 11, 2)  # north of him: its facade rises up behind him
