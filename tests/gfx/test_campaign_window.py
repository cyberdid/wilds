"""The sprite window's campaign: a rescue continues into the city in the same
window and journal; a paid-off debt starts a new campaign on a new planet."""

from wilds.brain import ScriptedBrain
from wilds.cyberpunk.scripted import CyberScriptedBrain
from wilds.cyberpunk.sim import CitySim
from wilds.cyberpunk.worldgen import generate as city_generate
from wilds.gfx.app import Campaign, CityChapter, GfxApp, Tau7Chapter
from wilds.worldgen import generate


def test_rescue_switches_to_the_city_and_victory_starts_over(tmp_path):
    logs = tmp_path / "logs"
    tau7 = Tau7Chapter(generate, diary_dir=logs, legacy_dir=tmp_path / "legacy")
    campaign = Campaign(tau7, ScriptedBrain(), CyberScriptedBrain(),
                        lambda legacy: CityChapter(lambda s: city_generate(s, legacy), diary_dir=logs))
    app = GfxApp(tau7, ScriptedBrain(), 12, headless=True, size=(900, 600), campaign=campaign)
    app.speed_idx = 5
    world = app.sim.world
    world.pod.rescue_at = world.tick + 2
    for _ in range(10):
        app.update(0.1)
    assert app.sim.world.hero.rescued and app.next_hint().startswith("Глава 2")
    app.draw()
    journal = app.eventlog.path
    app.ended_at = app.now - 999  # skip the 20 s ending screen
    app.update(0.1)
    assert isinstance(app.sim, CitySim) and app.chapter is not tau7
    assert app.sim.world.hero.name == "Вцілілий"  # the legacy carried the hero over
    assert app.eventlog.path == journal and "Тінемісто" in journal.read_text(encoding="utf-8")
    app.draw()
    app.sim.world.hero.free = True
    app.update(0.1)
    app.ended_at = app.now - 999
    app.update(0.1)
    assert app.chapter is tau7 and app.sim.world.seed == 13
    assert app.eventlog.path != journal and "кампанію завершено" in journal.read_text(encoding="utf-8")
