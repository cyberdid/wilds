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


def test_structures_and_people_are_found_around_the_village(app):
    sprites = []
    x0, y0 = app.sim.hero.pos[0] - 20, app.sim.hero.pos[1] - 15
    app.plates = []
    app._collect(sprites, x0, y0, 40, 30)
    names = {s[1] for s in sprites}
    assert any(n.startswith("az.obj.") for n in names) and any(n.startswith("az.person.") for n in names)
    assert "az.person.hero.idle" in names or "az.person.hero.walk" in names


def test_ground_blends_and_caches_composites(app):
    grid = [[Terrain.GRASS] * 3 for _ in range(3)]
    grid[1][2] = Terrain.TALL_GRASS  # the higher-ranked neighbour bleeds into the centre tile
    a = app.painter.tile(grid, 1, 1, 10, 10, 2, 0.0)
    before = len(app.painter._scaled)
    b = app.painter.tile(grid, 1, 1, 10, 10, 2, 0.0)
    assert a is b and len(app.painter._scaled) == before
    plain = [[Terrain.GRASS] * 3 for _ in range(3)]
    assert app.painter.tile(plain, 1, 1, 10, 10, 2, 0.0) is not a


def test_thunder_bluff_is_platforms_joined_by_bridges(app):
    world = app.world
    plats = settlements.platforms(world)
    assert {p.name for p in plats} == {"High Rise", "Spirit Rise", "Elder Rise", "Hunter Rise"}
    hub = plats[0]
    assert settlements.on_platform(world, hub.center, plats) is hub
    assert settlements.on_platform(world, (hub.center[0] + 300, hub.center[1]), plats) is None
    assert len(app.bridge_tiles) > 200


def test_zoom_and_keys_do_not_crash(app):
    for key in (pygame.K_RIGHTBRACKET, pygame.K_LEFTBRACKET, pygame.K_m, pygame.K_n, pygame.K_TAB, pygame.K_h):
        app.handle(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=""))
    app.draw()
    app.handle(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode=""))
    app.show_panel = True
