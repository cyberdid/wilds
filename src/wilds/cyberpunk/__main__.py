"""CLI entry for the cyberpunk chapter. Reached either directly
(`wilds --chapter cyberpunk`) or after a Tau-7 rescue writes a legacy file."""

from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

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


def headless(args: argparse.Namespace, brain, seed: int) -> None:
    legacy = _find_legacy(args)
    world = generate(seed, legacy)
    for ev in world.events:
        print(f"[{ev.tick // 60 % 24:02d}:{ev.tick % 60:02d}] {ev.text}")
    world.listeners.append(lambda ev: print(f"[{ev.tick // 60 % 24:02d}:{ev.tick % 60:02d}] {ev.text}"))
    sim = CitySim(world)
    if args.log_dir:
        Path(args.log_dir).mkdir(parents=True, exist_ok=True)
        sim.diary_path = Path(args.log_dir) / f"diary-cyberpunk-{brain.name}-{seed}.md"
    sim.run(brain, args.headless)
    hero = world.hero
    ending = "вільний (борг погашено)" if hero.free else ("живий" if hero.alive else f"вибув: {hero.cause_of_death}")
    print(f"\n{world.clock()} | {ending} | рішень: {sim.decisions} | нуєни: {hero.nuyen}¥ | "
          f"борг: {hero.debt}¥ | раса: {hero.race.label} | мозок: {brain.label}")
    if sim.diary_path and hero.diary:
        print(f"щоденник: {sim.diary_path}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    brain = make_brain(args)
    if args.headless:
        headless(args, brain, seed)
        return
    from .ui import CyberApp

    legacy = _find_legacy(args)
    diary_dir = Path(args.log_dir) if args.log_dir else None
    CyberApp(lambda s: generate(s, legacy), brain, seed, speed=args.speed, diary_dir=diary_dir).run()


if __name__ == "__main__":
    main()
