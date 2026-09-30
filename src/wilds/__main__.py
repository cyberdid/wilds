"""Command line entry point: `wilds` or `python -m wilds`."""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

from .brain import ClaudeBrain, CodexBrain, ScriptedBrain
from .brain.codex import DEFAULT_MODEL as CODEX_DEFAULT_MODEL
from .actions import ACTION_HELP
from .campaign import CHAPTER2_TITLE, ready_for_chapter2
from .eventlog import EventLog
from .save import CITY_SUFFIX, SAVE_DIR, TAU7_SUFFIX, latest_save, load_game, save_game, save_path
from .sim import Simulation
from .worldgen import generate


def _chapter(argv: list[str] | None) -> str:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--chapter", choices=["tau7", "cyberpunk"], default="tau7")
    known, _ = pre.parse_known_args(argv)
    return known.chapter


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="wilds", description="Тау-7: ASCII-планета, на якій виживає ШІ.")
    p.add_argument("--brain", choices=["claude", "codex", "scripted"], default="claude",
                   help="хто керує героєм: Claude (`claude -p`), Codex (`codex exec`) або прості правила")
    p.add_argument("--model", default=None,
                   help=f"модель: для claude haiku|sonnet|opus (default haiku), "
                        f"для codex напр. gpt-5.6-luna (default {CODEX_DEFAULT_MODEL})")
    p.add_argument("--effort", default="low", help="рівень міркувань: low|medium|high, або 'none'")
    p.add_argument("--think", action="store_true",
                   help="Claude: увімкнути розширене мислення (розумніше, але 10-100 с на хід)")
    p.add_argument("--lang", default="Ukrainian", help="мова думок героя")
    p.add_argument("--seed", type=int, default=None, help="seed планети (default: випадковий)")
    p.add_argument("--speed", type=int, default=1, help="початкова швидкість 0-6")
    p.add_argument("--log-dir", default="logs", help="куди писати промпти/відповіді ШІ ('' — не писати)")
    p.add_argument("--load", metavar="FILE", default=None, help="продовжити збережену гру (.wsav)")
    p.add_argument("--continue", dest="resume", action="store_true",
                   help="продовжити останнє збереження з теки saves/")
    p.add_argument("--headless", type=int, metavar="TICKS", default=0,
                   help="без інтерфейсу: прогнати N тіків і вивести підсумок")
    p.add_argument("--chapter", choices=["tau7", "cyberpunk"], default="tau7",
                   help="tau7 (типово) - виживання; cyberpunk - друга глава після порятунку")
    p.add_argument("--legacy-dir", default="legacy", help="куди/звідки писати/читати спадок персонажа")
    p.add_argument("--no-legacy", action="store_true", help="не писати спадок при порятунку")
    p.add_argument("--campaign", action="store_true",
                   help="уся гра однією командою: Тау-7, а після порятунку - кіберпанк-глава зі спадком")
    add_gfx_args(p)
    return p.parse_args(argv)


def add_gfx_args(p: argparse.ArgumentParser) -> None:
    """Sprite front-end flags, shared by both chapters."""
    g = p.add_argument_group("графіка (спрайти, pygame)")
    g.add_argument("--gfx", action="store_true", help="графічний клієнт зі спрайтами замість терміналу")
    g.add_argument("--zoom", type=int, default=3, help="масштаб пікселів 1-6 (типово 3)")
    g.add_argument("--view", choices=["2d", "iso"], default="2d",
                   help="вид: 2d (3/4 зверху) або iso (ізометрія 2.5D); у грі перемикає клавіша i")
    g.add_argument("--window", default="1360x820", help="розмір вікна, напр. 1600x900")
    g.add_argument("--fullscreen", action="store_true", help="на весь екран")
    g.add_argument("--sprites", metavar="DIR", default=None,
                   help="тека з PNG, що підміняють вбудовані спрайти (формат: wilds-sprites --strips)")
    g.add_argument("--shot", metavar="FILE", default=None,
                   help="зберегти кадр гри в PNG без вікна (після --headless N тіків) і вийти")
    g.add_argument("--god", action="store_true", help="для --shot: показати всю мапу («око бога»)")


def window_size(args: argparse.Namespace) -> tuple[int, int]:
    try:
        w, h = (int(v) for v in args.window.lower().split("x"))
        return max(640, w), max(480, h)
    except ValueError:
        sys.exit(f"--window: очікую ШИРИНАxВИСОТА, отримав {args.window!r}")


def make_brain(args: argparse.Namespace):
    if args.brain == "scripted":
        return ScriptedBrain()
    effort = None if args.effort == "none" else args.effort
    log_dir = Path(args.log_dir) if args.log_dir else None
    if not shutil.which(args.brain):
        what = "Claude Code CLI" if args.brain == "claude" else "Codex CLI"
        sys.exit(f"Не знайдено `{args.brain}` ({what}). Встановіть його і залогіньтесь, "
                 "або запустіть з --brain scripted.")
    if args.brain == "codex":
        return CodexBrain(model=args.model or CODEX_DEFAULT_MODEL, effort=effort, lang=args.lang, log_dir=log_dir)
    return ClaudeBrain(model=args.model or "haiku", effort=effort, thinking=args.think,
                       lang=args.lang, log_dir=log_dir)


def headless(args: argparse.Namespace, brain, seed: int, loaded: Simulation | None = None) -> None:
    """Run Tau-7 without a UI; with --campaign a rescue continues into the city."""
    sim = loaded or Simulation(generate(seed))
    sim.brain_name = brain.name
    world = sim.world
    if loaded is None:
        for ev in world.events:
            print(f"[{ev.tick // 60 % 24:02d}:{ev.tick % 60:02d}] {ev.text}")
    world.listeners.append(lambda ev: print(f"[{ev.tick // 60 % 24:02d}:{ev.tick % 60:02d}] {ev.text}"))
    if args.log_dir and loaded is None:
        Path(args.log_dir).mkdir(parents=True, exist_ok=True)
        sim.diary_path = Path(args.log_dir) / f"diary-{brain.name}-{seed}.md"
    if not args.no_legacy:
        sim.legacy_dir = Path(args.legacy_dir)
    log = EventLog.for_game(args.log_dir, brain.name, world.seed, sim=sim)
    if log:
        log.attach(sim, "Тау-7", brain.label, resumed=loaded is not None)
    sim.run(brain, args.headless)
    if not sim.over:
        saved = save_game(sim, save_path(sim, brain.name))
        print(f"збережено: {saved}")
        if log:
            log.meta(f"збережено: {saved}")
    hero = world.hero
    ending = "врятований" if hero.rescued else ("живий" if hero.alive else f"загинув: {hero.cause_of_death}")
    print(f"\n{world.clock()} | {ending} | рішень: {sim.decisions} | артефактів: {hero.inventory['artifact']} | "
          f"вбито: {dict(hero.kills)} | мозок: {brain.label}")
    if world.pod:
        print(f"капсула: {world.pod.status_line()}")
    print("метрики:", sim.metrics.summary(len(ACTION_HELP)))
    if sim.diary_path and hero.diary:
        print(f"щоденник: {sim.diary_path}")
    if log:
        log.check_end()
    if args.campaign and ready_for_chapter2(sim):
        from .cyberpunk.__main__ import headless as city_headless, make_brain as make_city_brain
        from .cyberpunk.legacy import import_legacy

        print(f"\n===== Глава 2: {CHAPTER2_TITLE} (спадок {sim.legacy_path}) =====")
        if log:
            log.meta(f"кампанія: глава 2 «{CHAPTER2_TITLE}», спадок {sim.legacy_path}")
        city_headless(args, make_city_brain(args), world.seed, legacy=import_legacy(sim.legacy_path), eventlog=log)
    elif args.campaign:
        print("\nКампанія: порятунку не було, глава 2 не почалась.")
    if log:
        log.close()
        print(f"журнал: {log.path}")


def shot(args: argparse.Namespace, brain, seed: int, loaded: Simulation | None = None) -> None:
    """Render one frame of the sprite front-end to a PNG, no window needed."""
    from .gfx.app import GfxApp, Tau7Chapter

    sim = loaded or Simulation(generate(seed))
    sim.brain_name = brain.name
    if args.headless:
        sim.run(brain, args.headless)
    app = GfxApp(Tau7Chapter(generate), brain, seed, speed=args.speed, sprites_dir=args.sprites,
                 size=window_size(args), zoom=args.zoom, loaded=sim, headless=True, view=args.view)
    app.god_view = args.god
    app.paused = True  # only animations advance while the frame settles
    print(f"скріншот: {app.shot(args.shot)}")


def _city_save_requested(argv: list[str] | None) -> bool:
    """`--load x.csav`, or `--continue` when the newest save of either chapter is a city one."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--load", default=None)
    pre.add_argument("--continue", dest="resume", action="store_true")
    known, _ = pre.parse_known_args(argv)
    if known.load:
        return Path(known.load).suffix == CITY_SUFFIX
    if known.resume:
        newest = latest_save(SAVE_DIR, (TAU7_SUFFIX, CITY_SUFFIX))
        return newest is not None and newest.suffix == CITY_SUFFIX
    return False


def main(argv: list[str] | None = None) -> None:
    if _chapter(argv) == "cyberpunk" or _city_save_requested(argv):
        from .cyberpunk.__main__ import main as cyberpunk_main

        cyberpunk_main(argv)
        return
    args = parse_args(argv)
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    brain = make_brain(args)
    loaded = None
    if args.load or args.resume:
        path = Path(args.load) if args.load else latest_save()
        if path is None or not path.exists():
            sys.exit("Збереження не знайдено (тека saves/ порожня або неправильний шлях).")
        loaded, state = load_game(path)
        if hasattr(brain, "wrecks_done"):
            brain.wrecks_done = set(state.get("wrecks_done", []))
        print(f"Завантажено {path}: {loaded.world.clock()}")
    if args.campaign and args.no_legacy:
        sys.exit("--campaign переносить героя в главу 2 через спадок: приберіть --no-legacy.")
    if args.shot:
        shot(args, brain, seed, loaded)
        return
    if args.headless:
        headless(args, brain, seed, loaded)
        return
    diary_dir = Path(args.log_dir) if args.log_dir else None
    legacy_dir = None if args.no_legacy else Path(args.legacy_dir)
    if args.gfx:
        from .gfx.app import Campaign, CityChapter, GfxApp, Tau7Chapter

        chapter = Tau7Chapter(generate, diary_dir=diary_dir, save_dir=SAVE_DIR, legacy_dir=legacy_dir)
        campaign = None
        if args.campaign:
            from .cyberpunk.__main__ import make_brain as make_city_brain
            from .cyberpunk.worldgen import generate as city_generate

            campaign = Campaign(chapter, brain, make_city_brain(args),
                                lambda legacy: CityChapter(lambda s: city_generate(s, legacy), diary_dir=diary_dir,
                                                           save_dir=SAVE_DIR))
        GfxApp(chapter, brain, seed, speed=args.speed, sprites_dir=args.sprites, size=window_size(args),
               zoom=args.zoom, loaded=loaded, fullscreen=args.fullscreen, view=args.view, campaign=campaign).run()
        return
    from .ui import WildsApp

    app = WildsApp(generate, brain, seed, speed=args.speed, diary_dir=diary_dir, legacy_dir=legacy_dir,
                   loaded=loaded, campaign=args.campaign)
    result = app.run()
    if args.campaign and result == "campaign":
        from .cyberpunk.__main__ import make_brain as make_city_brain
        from .cyberpunk.legacy import import_legacy
        from .cyberpunk import worldgen as city_worldgen
        from .cyberpunk.ui import CyberApp

        legacy = import_legacy(app.sim.legacy_path)
        if app.eventlog:
            app.eventlog.meta(f"кампанія: глава 2 «{CHAPTER2_TITLE}», спадок {app.sim.legacy_path}")
        CyberApp(lambda s: city_worldgen.generate(s, legacy), make_city_brain(args), app.sim.world.seed,
                 speed=args.speed, diary_dir=diary_dir, eventlog=app.eventlog).run()
    if app.eventlog:
        app.eventlog.close()


if __name__ == "__main__":
    main()
