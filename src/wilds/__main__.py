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
from .save import latest_save, load_game, save_game, save_path
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
    return p.parse_args(argv)


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
    sim.run(brain, args.headless)
    if not sim.over:
        print(f"збережено: {save_game(sim, save_path(sim, brain.name))}")
    hero = world.hero
    ending = "врятований" if hero.rescued else ("живий" if hero.alive else f"загинув: {hero.cause_of_death}")
    print(f"\n{world.clock()} | {ending} | рішень: {sim.decisions} | артефактів: {hero.inventory['artifact']} | "
          f"вбито: {dict(hero.kills)} | мозок: {brain.label}")
    if world.pod:
        print(f"капсула: {world.pod.status_line()}")
    print("метрики:", sim.metrics.summary(len(ACTION_HELP)))
    if sim.diary_path and hero.diary:
        print(f"щоденник: {sim.diary_path}")


def main(argv: list[str] | None = None) -> None:
    if _chapter(argv) == "cyberpunk":
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
    if args.headless:
        headless(args, brain, seed, loaded)
        return
    from .ui import WildsApp

    diary_dir = Path(args.log_dir) if args.log_dir else None
    legacy_dir = None if args.no_legacy else Path(args.legacy_dir)
    WildsApp(generate, brain, seed, speed=args.speed, diary_dir=diary_dir, legacy_dir=legacy_dir,
             loaded=loaded).run()


if __name__ == "__main__":
    main()
