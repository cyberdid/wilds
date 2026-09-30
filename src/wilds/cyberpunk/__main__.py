"""CLI entry for the cyberpunk chapter. Reached either directly
(`wilds --chapter cyberpunk`) or after a Tau-7 rescue writes a legacy file."""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

from ..eventlog import EventLog
from ..save import CITY_SUFFIX, SAVE_DIR, latest_save, load_game, save_game, save_path
from .brain import CyberClaudeBrain, CyberCodexBrain
from .legacy import import_legacy
from .scripted import CyberScriptedBrain
from .sim import CitySim
from .worldgen import generate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="wilds-cyberpunk", description="Насип: кіберпанк-глава Wilds.")
    p.add_argument("--chapter", choices=["tau7", "cyberpunk"], default="cyberpunk", help=argparse.SUPPRESS)
    p.add_argument("--brain", choices=["claude", "codex", "scripted"], default="claude")
    p.add_argument("--model", default=None)
    p.add_argument("--effort", default="low")
    p.add_argument("--lang", default="Ukrainian")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--speed", type=int, default=1)
    p.add_argument("--log-dir", default="logs")
    p.add_argument("--legacy-dir", default="legacy", help="тека зі спадком від Тау-7")
    p.add_argument("--legacy-file", default=None,
                   help="конкретний файл спадку; типово - найновіший у --legacy-dir")
    p.add_argument("--no-legacy", action="store_true", help="почати без спадку (випадкова раса, 200¥)")
    p.add_argument("--headless", type=int, metavar="TICKS", default=0)
    p.add_argument("--load", metavar="FILE", default=None, help="продовжити збережене місто (.csav)")
    p.add_argument("--continue", dest="resume", action="store_true",
                   help="продовжити останнє збереження міста з теки saves/")
    # `wilds --campaign --continue` lands here when the newest save is a city one
    p.add_argument("--campaign", action="store_true", help=argparse.SUPPRESS)
    from ..__main__ import add_gfx_args

    add_gfx_args(p)
    return p.parse_args(argv)


def make_brain(args: argparse.Namespace):
    if args.brain == "scripted":
        return CyberScriptedBrain()
    effort = None if args.effort == "none" else args.effort
    log_dir = Path(args.log_dir) if args.log_dir else None
    if not shutil.which(args.brain):
        sys.exit(f"Не знайдено `{args.brain}`. Встановіть і залогіньтесь, або --brain scripted.")
    if args.brain == "codex":
        return CyberCodexBrain(model=args.model or "gpt-5.6-luna", effort=effort, lang=args.lang, log_dir=log_dir)
    return CyberClaudeBrain(model=args.model or "haiku", effort=effort, lang=args.lang, log_dir=log_dir)


def _find_legacy(args: argparse.Namespace):
    if args.no_legacy:
        return None
    if args.legacy_file:
        path = Path(args.legacy_file)
    else:
        directory = Path(args.legacy_dir)
        files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime) if directory.exists() else []
        path = files[-1] if files else None
    if path is None or not path.exists():
        return None
    legacy = import_legacy(path)
    print(f"Спадок: {path} ({legacy.name}, з Тау-7 seed {legacy.source_seed})")
    return legacy


def headless(args: argparse.Namespace, brain, seed: int, legacy=None, eventlog: EventLog | None = None,
             loaded: CitySim | None = None) -> CitySim:
    """Run the city without a UI. A campaign passes the Tau-7 legacy and its journal."""
    if loaded is not None:
        sim, world = loaded, loaded.world
        seed = world.seed
    else:
        if legacy is None:
            legacy = _find_legacy(args)
        world = generate(seed, legacy)
        for ev in world.events:
            print(f"[{ev.tick // 60 % 24:02d}:{ev.tick % 60:02d}] {ev.text}")
        sim = CitySim(world)
        if args.log_dir:
            Path(args.log_dir).mkdir(parents=True, exist_ok=True)
            sim.diary_path = Path(args.log_dir) / f"diary-cyberpunk-{brain.name}-{seed}.md"
    world.listeners.append(lambda ev: print(f"[{ev.tick // 60 % 24:02d}:{ev.tick % 60:02d}] {ev.text}"))
    log = eventlog or EventLog.for_game(args.log_dir, brain.name, seed, "cyberpunk", sim=sim)
    if log:
        log.attach(sim, "Тінемісто", brain.label, resumed=loaded is not None)
    sim.run(brain, args.headless)
    if not sim.over:
        saved = save_game(sim, save_path(sim, brain.name, SAVE_DIR, CITY_SUFFIX))
        print(f"збережено: {saved}")
        if log:
            log.meta(f"збережено: {saved}")
    hero = world.hero
    ending = "вільний (борг погашено)" if hero.free else ("живий" if hero.alive else f"вибув: {hero.cause_of_death}")
    print(f"\n{world.clock()} | {ending} | рішень: {sim.decisions} | нуєни: {hero.nuyen}¥ | "
          f"борг: {hero.debt}¥ | раса: {hero.race.label} | мозок: {brain.label}")
    if sim.diary_path and hero.diary:
        print(f"щоденник: {sim.diary_path}")
    if log:
        log.check_end()
        if eventlog is None:
            log.close()
            print(f"журнал: {log.path}")
    return sim


def shot(args: argparse.Namespace, brain, seed: int) -> None:
    """Render one frame of the sprite front-end to a PNG, no window needed."""
    from ..__main__ import window_size
    from ..gfx.app import CityChapter, GfxApp

    legacy = _find_legacy(args)
    sim = CitySim(generate(seed, legacy))
    if args.headless:
        sim.run(brain, args.headless)
    app = GfxApp(CityChapter(lambda s: generate(s, legacy)), brain, seed, speed=args.speed,
                 sprites_dir=args.sprites, size=window_size(args), zoom=args.zoom, loaded=sim, headless=True,
                 view=args.view)
    app.god_view = args.god
    app.paused = True
    print(f"скріншот: {app.shot(args.shot)}")


def load_city(args: argparse.Namespace) -> CitySim | None:
    if not (args.load or args.resume):
        return None
    path = Path(args.load) if args.load else latest_save(SAVE_DIR, (CITY_SUFFIX,))
    if path is None or not path.exists():
        sys.exit("Збереження міста не знайдено (у saves/ немає *.csav або неправильний шлях).")
    sim, _ = load_game(path)
    if not isinstance(sim, CitySim):
        sys.exit(f"{path} - це збереження Тау-7, а не міста; запустіть без --chapter cyberpunk.")
    print(f"Завантажено {path}: {sim.world.clock()}")
    return sim


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    brain = make_brain(args)
    loaded = load_city(args)
    if args.shot:
        shot(args, brain, seed)
        return
    if args.headless:
        headless(args, brain, seed, loaded=loaded)
        return
    # a loaded city keeps its own world; the legacy only matters for "new city" after an ending
    legacy = _find_legacy(args)
    diary_dir = Path(args.log_dir) if args.log_dir else None
    if args.gfx:
        from ..__main__ import window_size
        from ..gfx.app import CityChapter, GfxApp

        GfxApp(CityChapter(lambda s: generate(s, legacy), diary_dir=diary_dir, save_dir=SAVE_DIR), brain, seed,
               speed=args.speed, sprites_dir=args.sprites, size=window_size(args), zoom=args.zoom,
               fullscreen=args.fullscreen, view=args.view, loaded=loaded).run()
        return
    if loaded is not None:
        sys.exit("Продовження міста поки що є лише у графічному (--gfx) та headless режимах.")
    from .ui import CyberApp

    app = CyberApp(lambda s: generate(s, legacy), brain, seed, speed=args.speed, diary_dir=diary_dir)
    app.run()
    if app.eventlog:
        app.eventlog.close()


if __name__ == "__main__":
    main()
