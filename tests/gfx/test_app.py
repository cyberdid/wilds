"""The pygame front-end shell: it must drive the simulation exactly like the
headless loop (the renderer never changes rules), wire loaded saves like the
terminal UI, and handle its controls."""

import pygame

from wilds.brain import ScriptedBrain
from wilds.cyberpunk.scripted import CyberScriptedBrain
from wilds.cyberpunk.sim import CitySim
from wilds.cyberpunk.worldgen import generate as city_generate
from wilds.gfx.app import TPS, ZOOMS, CityChapter, GfxApp, Tau7Chapter, speed_index
from wilds.sim import Simulation
from wilds.worldgen import generate


def _key(app, key, uni=""):
    app.handle(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=uni, mod=0))


def _drive(app, ticks):
    app.paused = False
    guard = 0
    while app.sim.world.tick < ticks and not app.sim.over and guard < 20000:
        app.acc = 0.0
        app.update(0)  # dt=0: brain calls only; tick manually for exact control
        if app.sim.pending is None and app.thinking_since is None and app.sim.action is not None:
            app.sim.tick()
        guard += 1


def test_the_front_end_does_not_change_the_game():
    """Same seed + same brain: the app loop and Simulation.run end in the same state."""
    ref = Simulation(generate(21))
    ref.run(ScriptedBrain(), 700)
    app = GfxApp(Tau7Chapter(generate), ScriptedBrain(), 21, headless=True, size=(800, 600))
    _drive(app, ref.world.tick)
    a, b = ref.world.hero, app.sim.world.hero
    assert app.sim.world.tick == ref.world.tick
    assert (a.pos, a.level_id, round(a.hp, 6), dict(a.inventory)) == \
        (b.pos, b.level_id, round(b.hp, 6), dict(b.inventory))
    assert app.sim.decisions == ref.decisions


def test_loaded_sim_is_wired_like_the_terminal_ui(tmp_path):
    loaded = Simulation(generate(1))
    app = GfxApp(Tau7Chapter(generate, legacy_dir=tmp_path), ScriptedBrain(), 1, loaded=loaded, headless=True,
                 size=(800, 600))
    assert app.sim is loaded and loaded.legacy_dir == tmp_path and loaded.brain_name == "scripted"
    none = Simulation(generate(1))
    GfxApp(Tau7Chapter(generate, legacy_dir=None), ScriptedBrain(), 1, loaded=none, headless=True, size=(800, 600))
    assert none.legacy_dir is None


def test_controls():
    app = GfxApp(Tau7Chapter(generate), ScriptedBrain(), 3, headless=True, size=(800, 600))
    _key(app, pygame.K_SPACE)
    assert app.paused
    for _ in range(20):
        _key(app, pygame.K_EQUALS, "+")
    assert app.tps == TPS[-1]
    for _ in range(20):
        _key(app, pygame.K_MINUS, "-")
    assert app.tps == TPS[0]
    for _ in range(10):
        _key(app, pygame.K_RIGHTBRACKET, "]")
    assert app.zoom == ZOOMS[-1]
    _key(app, pygame.K_d)
    assert app.overlay == "diary"
    _key(app, pygame.K_ESCAPE)
    assert app.overlay is None
    _key(app, pygame.K_g)
    _key(app, pygame.K_m)
    assert app.god_view and not app.show_minimap
    seed = app.sim.world.seed
    _key(app, pygame.K_n)
    assert app.sim.world.seed == seed + 1
    app.draw()
    assert speed_index(1) == 2 and speed_index(99) == len(TPS) - 1


def test_save_on_quit(tmp_path):
    app = GfxApp(Tau7Chapter(generate, save_dir=tmp_path), ScriptedBrain(), 4, headless=True, size=(800, 600))
    app.quit()
    assert list(tmp_path.glob("*.wsav")) and not app.running


def test_city_front_end_runs_and_ends_cleanly():
    sim = CitySim(city_generate(7))
    app = GfxApp(CityChapter(city_generate), CyberScriptedBrain(), 7, loaded=sim, headless=True, size=(900, 600))
    app.speed_idx = 7
    for _ in range(40):
        app.update(1 / 20)
        app.draw()
    assert sim.decisions > 0 and sim.world.tick > 9 * 60
    sim.world.hero.free = True
    app.update(1 / 20)
    app.draw()
    assert app.ended_at is not None
