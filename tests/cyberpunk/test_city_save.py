"""The city chapter can be saved and resumed, like Tau-7 (it could not be at
first: closing the window during a live Codex campaign lost the city run)."""

import copy

from wilds.cyberpunk.scripted import CyberScriptedBrain
from wilds.cyberpunk.sim import CitySim
from wilds.cyberpunk.worldgen import generate
from wilds.save import CITY_SUFFIX, TAU7_SUFFIX, latest_save, load_game, save_game, save_path


def test_city_save_roundtrip_keeps_the_stakes_state(tmp_path):
    sim = CitySim(generate(5))
    sim.run(CyberScriptedBrain(), 600)
    world = sim.world
    world.level.heat = 42.0
    world.delinquent = True
    events = []
    world.listeners.append(events.append)
    path = save_game(sim, save_path(sim, "cyber-codex", tmp_path, CITY_SUFFIX))
    assert path.suffix == ".csav"
    assert world.listeners, "listeners are restored after saving"

    loaded, _ = load_game(path)
    w2 = loaded.world
    assert isinstance(loaded, CitySim)
    assert w2.tick == world.tick and w2.hero.pos == world.hero.pos
    assert (w2.hero.nuyen, w2.hero.debt, w2.hero.hp) == (world.hero.nuyen, world.hero.debt, world.hero.hp)
    assert w2.level.heat == 42.0 and w2.delinquent
    assert w2.listeners == []
    assert loaded.decisions == sim.decisions


def test_loaded_city_continues_exactly_like_the_original(tmp_path):
    sim = CitySim(generate(4))
    brain = CyberScriptedBrain()
    sim.run(brain, 300)
    path = save_game(sim, tmp_path / "a.csav")
    brain_copy = copy.deepcopy(brain)
    sim.run(brain, 900)
    loaded, _ = load_game(path)
    loaded.run(brain_copy, 900)
    assert loaded.world.tick == sim.world.tick
    assert loaded.world.hero.debt == sim.world.hero.debt
    assert [e.text for e in loaded.world.events] == [e.text for e in sim.world.events]


def test_tau7_continue_never_picks_a_city_save(tmp_path):
    (tmp_path / "codex-1.wsav").write_bytes(b"x")
    (tmp_path / "cyber-codex-1.csav").write_bytes(b"x")
    assert latest_save(tmp_path).suffix == TAU7_SUFFIX
    assert latest_save(tmp_path, (CITY_SUFFIX,)).suffix == CITY_SUFFIX


def test_gfx_city_chapter_saves_on_s_and_on_quit(tmp_path):
    from wilds.gfx.app import CityChapter, GfxApp

    sim = CitySim(generate(7))
    app = GfxApp(CityChapter(generate, save_dir=tmp_path), CyberScriptedBrain(), 7, loaded=sim,
                 headless=True, size=(900, 600))
    path = app.chapter.save(app)
    assert path is not None and path.exists() and path.suffix == ".csav"
    loaded, _ = load_game(path)
    assert loaded.world.tick == sim.world.tick


def test_continue_routes_to_the_chapter_of_the_newest_save(tmp_path, monkeypatch):
    import os

    import wilds.__main__ as root

    monkeypatch.setattr(root, "SAVE_DIR", tmp_path)
    tau7, city = tmp_path / "codex-1.wsav", tmp_path / "cyber-codex-1.csav"
    tau7.write_bytes(b"x")
    city.write_bytes(b"x")
    os.utime(tau7, (1, 1))
    os.utime(city, (2, 2))
    assert root._city_save_requested(["--continue"])
    os.utime(tau7, (3, 3))
    assert not root._city_save_requested(["--continue"])
    assert root._city_save_requested(["--load", "saves/x.csav"])
    assert not root._city_save_requested(["--load", "saves/x.wsav"])
    assert not root._city_save_requested([])


def test_a_resumed_save_keeps_writing_the_journal_it_started_in(tmp_path, monkeypatch):
    """A campaign's city save, continued standalone, must append to the campaign's
    one journal - not open a new events-cyberpunk-<brain>-<seed>.log beside it."""
    from wilds.cyberpunk import __main__ as city_cli

    monkeypatch.chdir(tmp_path)
    journal = tmp_path / "logs" / "events-codex-9.log"
    sim = CitySim(generate(9))
    sim.journal_path = str(journal)
    path = save_game(sim, tmp_path / "saves" / "cyber-codex-9.csav")
    city_cli.main(["--load", str(path), "--brain", "scripted", "--headless", "30", "--log-dir", "logs"])
    assert journal.exists() and "продовження збереження" in journal.read_text(encoding="utf-8")
    assert not list((tmp_path / "logs").glob("events-cyberpunk-*.log"))
