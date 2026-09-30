"""`--campaign` plays both chapters in one run, and every mode writes the full
journal logs/events-<brain>-<seed>.log (events, decisions with reasons, hero
state, action outcomes, endings, campaign steps)."""

import asyncio

import pytest

from wilds import __main__ as cli
from wilds import ui
from wilds.brain import ScriptedBrain
from wilds.eventlog import EventLog
from wilds.save import save_game
from wilds.sim import Simulation
from wilds.ui.app import WildsApp
from wilds.worldgen import generate


def test_headless_campaign_plays_both_chapters_into_one_journal(tmp_path, capsys):
    cli.main(["--campaign", "--brain", "scripted", "--seed", "42", "--headless", "40000",
              "--log-dir", str(tmp_path / "logs"), "--legacy-dir", str(tmp_path / "legacy")])
    out = capsys.readouterr().out
    assert "врятований" in out and "Глава 2: Тінемісто" in out and "вільний (борг погашено)" in out
    assert (tmp_path / "legacy" / "scripted-42.json").exists()
    log = (tmp_path / "logs" / "events-scripted-42.log").read_text(encoding="utf-8")
    assert "===== Тау-7 · seed 42" in log and "===== Тінемісто · seed 42" in log
    assert "кампанія: глава 2 «Тінемісто»" in log
    assert log.count("] КІНЕЦЬ") >= 2 and "Рятувальна капсула розбилася" in log
    decisions = log.count("] рішення ")
    assert decisions > 100 and log.count("] підсумок ") >= decisions - 2
    assert "] стан " in log and "причина:" in log


def test_standalone_city_journal_and_disabled_logging(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # an unfinished headless city run now saves into ./saves
    cli.main(["--chapter", "cyberpunk", "--brain", "scripted", "--seed", "3", "--headless", "150",
              "--no-legacy", "--log-dir", str(tmp_path)])
    log = (tmp_path / "events-cyberpunk-scripted-3.log").read_text(encoding="utf-8")
    assert "===== Тінемісто · seed 3" in log and "] рішення " in log
    assert (tmp_path / "saves" / "scripted-3.csav").exists()
    monkeypatch.chdir(tmp_path / "..")
    before = set(tmp_path.parent.rglob("events-*.log"))
    cli.main(["--brain", "scripted", "--seed", "4", "--headless", "50", "--no-legacy", "--log-dir", ""])
    assert set(tmp_path.parent.rglob("events-*.log")) == before


def test_campaign_needs_a_legacy():
    with pytest.raises(SystemExit):
        cli.main(["--campaign", "--no-legacy", "--brain", "scripted", "--headless", "10"])


def test_journal_survives_saving(tmp_path):
    sim = Simulation(generate(2))
    log = EventLog(tmp_path / "events.log")
    log.attach(sim, "Тау-7", "scripted")
    sim.run(ScriptedBrain(), 60)
    save_game(sim, tmp_path / "s.wsav")  # listeners are stripped while pickling
    sim.world.log("після збереження", "info")
    log.close()
    text = (tmp_path / "events.log").read_text(encoding="utf-8")
    assert "після збереження" in text and "] рішення " in text


def test_terminal_campaign_exits_into_chapter_two(tmp_path, monkeypatch):
    monkeypatch.setattr(ui.app, "RESTART_AFTER", 0.0)
    app = WildsApp(generate, ScriptedBrain(), 8, diary_dir=tmp_path / "logs", legacy_dir=tmp_path / "legacy",
                   campaign=True)
    world = app.sim.world
    world.pod.rescue_at = world.tick + 1

    async def drive():
        async with app.run_test() as pilot:
            for _ in range(60):
                await pilot.pause(0.05)
                if app.return_value is not None:
                    break

    asyncio.run(drive())
    assert app.sim.world.hero.rescued and app.return_value == "campaign"
    assert app.eventlog and "врятований" in app.eventlog.path.read_text(encoding="utf-8")
