"""The Azeroth client draws real frames headlessly and its pieces behave."""

from pathlib import Path

import pygame
import pytest

from wilds.azeroth import settlements
from wilds.azeroth.brain import ScriptedZoneBrain
from wilds.azeroth.sim import ZoneSim
from wilds.azeroth.terrain import Terrain
from wilds.azeroth.world import ZoneWorld
from wilds.gfx import az_app

PACK = Path(__file__).parents[2] / "data" / "azeroth" / "mulgore"


@pytest.fixture(scope="module")
def app():
    world = ZoneWorld(PACK, seed=3)
    sim = ZoneSim(world, seed=3)
    sim.hero.pos = world.nearest_passable(sim.find_place("Bloodhoof Village")[0], 40)
    a = az_app.AzApp(sim, ScriptedZoneBrain(), 3, headless=True, size=(1000, 640), zoom=3)
    a.paused = True
    yield a
    pygame.display.quit()


def test_a_frame_shows_the_village_and_the_panel(app, tmp_path):
    out = app.shot(tmp_path / "frame.png", frames=3)
    assert out.exists() and out.stat().st_size > 20_000
    w, h = app.screen.get_size()
    colours = {tuple(app.screen.get_at((x, y)))[:3] for x in range(0, w, 7) for y in range(0, h, 7)}
    assert len(colours) > 60  # not a blank or single-colour frame


def test_people_and_creatures_get_name_plates_around_the_village(app):
    app.draw()
    titles = {p[3] for p in app.plates}
    assert app.plates and any("[" in t for t in titles) or len(titles) > 3
    assert any(p[4] == az_app.hud.CYAN for p in app.plates)  # the hero's own plate


def test_structures_are_indexed_by_chunk(app):
    kinds = {kind for objs in app.by_chunk.values() for kind, _ in objs}
    assert {"structure", "npc"} <= kinds


def test_ground_blends_and_caches_composites(app):
    grid = [[Terrain.GRASS] * 3 for _ in range(3)]
    grid[1][2] = Terrain.TALL_GRASS  # the higher-ranked neighbour bleeds into the centre tile
    a, key = app.painter.composite(grid, 1, 1, 10, 10, 0.0)
    n = len(app.painter._composite)
    b, key2 = app.painter.composite(grid, 1, 1, 10, 10, 0.0)
    assert a is b and key == key2 and len(app.painter._composite) == n
    plain = [[Terrain.GRASS] * 3 for _ in range(3)]
    assert app.painter.composite(plain, 1, 1, 10, 10, 0.0)[0] is not a
    assert app.painter.diamond(a, key) is app.painter.diamond(a, key)


def test_thunder_bluff_is_platforms_joined_by_bridges(app):
    world = app.world
    plats = settlements.platforms(world)
    assert {p.name for p in plats} == {"High Rise", "Spirit Rise", "Elder Rise", "Hunter Rise"}
    hub = plats[0]
    assert settlements.on_platform(world, hub.center, plats) is hub
    assert settlements.on_platform(world, (hub.center[0] + 300, hub.center[1]), plats) is None
    assert len(app.relief.bridges) > 200


def test_relief_stands_the_platforms_above_the_mesa(app):
    rel = app.relief
    hub = rel.platforms[0]
    kind = rel.kind(*hub.center, Terrain.MESA)
    assert kind == "platform"
    assert rel.height(*hub.center, kind) > rel.height(hub.center[0], hub.center[1], "mesa") > 0
    ground = rel.height(hub.center[0] + 90, hub.center[1], "ground")
    assert 0 <= ground <= 48 and ground % 8 == 0 and ground < rel.height(*hub.center, kind)
    assert rel.height(0, 0, "water") == 0


def test_the_view_switches_between_25d_and_three_quarter(app):
    app.view = "iso"
    app.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i, unicode="i"))
    assert app.view == "2d"
    app.draw()
    app.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_i, unicode="i"))
    assert app.view == "iso"


def test_zoom_and_keys_do_not_crash(app):
    for key in (pygame.K_RIGHTBRACKET, pygame.K_LEFTBRACKET, pygame.K_m, pygame.K_n, pygame.K_TAB, pygame.K_h):
        app.handle(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=""))
    app.draw()
    app.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode=""))
    app.show_panel = True
