"""Every game object has art: the manifest is satisfied, every enum member of
both chapters resolves to existing sprites through the renderer's mapping,
and every sprite name written literally in the gfx code exists."""

import ast
import re
from pathlib import Path

import pytest

from wilds.creatures import KINDS
from wilds.cyberpunk.items import ITEMS as CITY_ITEMS
from wilds.cyberpunk.npc import ROLES
from wilds.cyberpunk.tiles import CTile
from wilds.gfx import manifest
from wilds.gfx.mapping import (cp_block, cp_ground_base, cp_hero, cp_npc, cp_object, t7_actor, t7_block,
                               t7_ground_base, t7_item, t7_object)
from wilds.tiles import Tile
from wilds.world import ITEMS as TAU7_ITEMS

GFX = Path(__file__).resolve().parents[2] / "src" / "wilds" / "gfx"


def _exists(reg, name):
    assert name in reg, f"no sprite for {name!r}"
    for v in reg.variants(name):
        assert v in reg


def test_manifest_is_fully_covered(sprites):
    problems = manifest.check(sprites)
    assert not problems, "sprite gaps:\n" + "\n".join(problems)


@pytest.mark.parametrize("level_id", ["surface", *manifest.WRECK_THEMES])
@pytest.mark.parametrize("tile", list(Tile), ids=lambda t: t.name)
def test_every_tau7_tile_has_art_on_every_level(sprites, tile, level_id):
    for underlay in (Tile.MOSS, Tile.DUST):
        base = t7_ground_base(tile, level_id, underlay)
        if base is not None:
            _exists(sprites, base)
    block = t7_block(tile, level_id)
    if block:
        for name in block:
            _exists(sprites, name)
    for wreck in manifest.WRECK_THEMES:
        obj = t7_object(tile, wreck)
        if obj:
            _exists(sprites, obj)
    assert base is not None or block, f"{tile} is neither ground nor block"


@pytest.mark.parametrize("level_id", list(manifest.CITY_THEMES))
@pytest.mark.parametrize("tile", list(CTile), ids=lambda t: t.name)
def test_every_city_tile_has_art_in_every_location(sprites, tile, level_id):
    for underlay in (CTile.SIDEWALK, CTile.ROAD):
        base = cp_ground_base(sprites, tile, level_id, underlay)
        if base is not None:
            _exists(sprites, base)
    block = cp_block(tile, level_id)
    if block:
        for name in block:
            _exists(sprites, name)
    obj = cp_object(sprites, tile, level_id)
    if obj:
        _exists(sprites, obj)


@pytest.mark.parametrize("kind", list(KINDS))
def test_every_creature_animates(sprites, kind):
    for anim in ("idle", "move", "attack"):
        name = t7_actor(sprites, kind, anim)
        _exists(sprites, name)
        if anim != "attack" or KINDS[kind].hostile:
            assert name.endswith(anim), f"{kind} has no own '{anim}' animation"


def test_heroes_and_lira_have_every_animation_the_scene_uses(sprites):
    for anim in ("idle", "walk", "work", "drink", "attack", "sleep", "hurt"):
        assert t7_actor(sprites, "hero", anim) == f"t7.hero.{anim}"
    for anim in ("idle", "walk", "carry", "work", "sleep", "wave"):
        assert t7_actor(sprites, "lira", anim) == f"t7.lira.{anim}"
    for race in manifest.RACES:
        for aug in (False, True):
            for anim in ("idle", "walk", "hurt"):
                _exists(sprites, cp_hero(sprites, race, anim, aug))


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("race", manifest.RACES)
def test_every_npc_role_and_race(sprites, role, race):
    assert cp_npc(sprites, role, race, "idle") == f"cp.npc.{role}.{race}.idle"
    assert cp_npc(sprites, role, race, "talk") == f"cp.npc.{role}.{race}.talk"


def test_every_item_of_both_chapters(sprites):
    for key in TAU7_ITEMS:
        _exists(sprites, t7_item(key))
    for key in CITY_ITEMS:
        _exists(sprites, f"cp.item.{key}")


LITERAL = re.compile(r"^(ui|fx|t7|cp)\.[a-z0-9_]+(\.[a-z0-9_]+)*(@\d+)?$")


def test_every_sprite_name_written_in_the_gfx_code_exists(sprites):
    """Catches typos like 'ui.hydraton' in HUD/scene code (prefix lookups excluded)."""
    missing = []
    for path in GFX.glob("*.py"):
        if path.name == "export.py":  # its dotted strings are sheet-grouping keys, not sprites
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and LITERAL.match(node.value):
                name = node.value
                if name.endswith(".") or name in sprites:
                    continue
                missing.append(f"{path.name}: {name}")
    assert not missing, "\n".join(missing)
