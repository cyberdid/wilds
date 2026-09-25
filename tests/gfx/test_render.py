"""Headless rendering of every situation the sprite front-end must draw, in
both chapters: no crash, and no placeholder (missing sprite) anywhere."""

import pytest

from wilds.brain import ScriptedBrain
from wilds.companion import Companion
from wilds.cyberpunk.actions import Launch, Travel
from wilds.cyberpunk.contracts import Contract
from wilds.cyberpunk.npc import NPC
from wilds.cyberpunk.race import Race
from wilds.cyberpunk.scripted import CyberScriptedBrain
from wilds.cyberpunk.sim import CitySim
from wilds.cyberpunk.worldgen import generate as city_generate
from wilds.director import Event
from wilds.gfx.app import CityChapter, GfxApp, Tau7Chapter
from wilds.gfx.manifest import CITY_THEMES
from wilds.actions import change_level
from wilds.sim import Simulation
from wilds.worldgen import generate


def tau7_app(seed=5, **kw):
    sim = Simulation(generate(seed))
    return GfxApp(Tau7Chapter(generate), ScriptedBrain(), seed, loaded=sim, headless=True,
                  size=(1000, 700), **kw), sim


def city_app(seed=5, **kw):
    sim = CitySim(city_generate(seed))
    return GfxApp(CityChapter(city_generate), CyberScriptedBrain(), seed, loaded=sim, headless=True,
                  size=(1000, 700), **kw), sim


def shoot(app, tmp_path, name="shot.png", frames=4):
    app.paused = True
    path = app.shot(tmp_path / name, frames=frames)
    assert path.exists() and path.stat().st_size > 1000
    assert not app.renderer.missing, f"placeholders drawn for: {sorted(app.renderer.missing)}"


def test_tau7_day_surface(tmp_path):
    app, _ = tau7_app()
    shoot(app, tmp_path)


def test_tau7_night_storm_and_debris_warning(tmp_path):
    app, sim = tau7_app()
    world = sim.world
    world.tick = 23 * 60
    hero = world.hero
    d = world.director
    d.events.append(Event("dust_storm", world.tick - 10, world.tick - 5, world.tick + 200, stage="active"))
    spot = (hero.pos[0] + 3, hero.pos[1])
    d.events.append(Event("orbital_debris", world.tick, world.tick + 60, world.tick + 61, data={"pos": spot}))
    hero.observe(world)
    shoot(app, tmp_path)
    assert app.scene.weather(sim)


def test_tau7_camp_life_and_companion(tmp_path):
    app, sim = tau7_app()
    world = sim.world
    hero = world.hero
    world.pod.heater_on = True
    world.pod.beacon_repaired = True
    world.pod.fault = True
    world.companion = Companion(pos=(hero.pos[0] + 1, hero.pos[1] + 1), state="working", carrying=2)
    hero.inventory.update({"fiber": 3, "blade": 1, "artifact": 1, "headlamp": 1})
    hero.sleeping = True
    hero.warmth = 20
    world.levels["surface"].items[(hero.pos[0] - 1, hero.pos[1])] = ["artifact"]
    hero.observe(world)
    shoot(app, tmp_path)


@pytest.mark.parametrize("wreck", ["wreck_1", "wreck_2", "wreck_3"])
def test_tau7_inside_every_wreck(tmp_path, wreck):
    app, sim = tau7_app()
    level = sim.world.levels[wreck]
    change_level(sim.world, wreck, level.exit_pos)
    app.god_view = True
    shoot(app, tmp_path)


def test_tau7_endings(tmp_path):
    app, sim = tau7_app()
    sim.world.hero.rescued = True
    shoot(app, tmp_path, "rescued.png", frames=10)
    app2, sim2 = tau7_app(seed=6)
    sim2.world.hero.alive = False
    sim2.world.hero.cause_of_death = "холод"
    shoot(app2, tmp_path, "dead.png")


def test_tau7_simulation_runs_under_the_renderer(tmp_path):
    app, sim = tau7_app(seed=9)
    app.paused = False
    app.speed_idx = 6
    for _ in range(60):
        app.update(1 / 30)
        app.draw()
    assert sim.world.tick > 8 * 60 and sim.decisions > 0
    assert not app.renderer.missing, sorted(app.renderer.missing)


@pytest.mark.parametrize("level_id", list(CITY_THEMES))
def test_city_every_location_day_and_night(tmp_path, level_id):
    app, sim = city_app()
    world = sim.world
    hero = world.hero
    hero.level_id = level_id
    hero.pos = world.levels[level_id].arrival
    hero.observe(world)
    shoot(app, tmp_path, "day.png")
    world.tick = 23 * 60
    app.god_view = True
    shoot(app, tmp_path, "night.png")


def test_city_heat_contract_collector_and_augmented_runner(tmp_path):
    app, sim = city_app()
    world = sim.world
    hero = world.hero
    level = world.level
    level.heat = 90
    world.contract = Contract("job_x", level.npcs[0].id, level.id, (hero.pos[0] + 2, hero.pos[1]), 300)
    level.npcs.append(NPC("collector_sprawl", "Колектор", Race.TROLL, "collector",
                          (hero.pos[0] + 1, hero.pos[1]), "x", hostile=True))
    hero.inventory["cyber_arm"] = 1
    hero.observe(world)
    shoot(app, tmp_path)


@pytest.mark.parametrize("action", [Travel("docks"), Launch("orbital_station")], ids=["travel", "launch"])
def test_city_cutscenes(tmp_path, action):
    app, sim = city_app()
    assert action.start(sim.world) is None
    sim.action = action
    action.ticks = 30
    shoot(app, tmp_path)


@pytest.mark.parametrize("zoom", [1, 2, 4, 6])
def test_every_zoom_level(tmp_path, zoom):
    app, _ = tau7_app(zoom=zoom)
    shoot(app, tmp_path)
