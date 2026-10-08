"""``wilds --chapter azeroth``: a hero living in Mulgore at real scale."""

from __future__ import annotations

import random
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[3] / "data" / "azeroth" / "mulgore"


def main(argv: list[str] | None = None) -> None:
    import argparse

    import shutil

    from ..__main__ import add_gfx_args, window_size
    from .brain import ExploreBrain, ScriptedZoneBrain, make_claude_brain, make_codex_brain
    from .sim import ZoneSim
    from .world import ZoneWorld

    p = argparse.ArgumentParser(prog="wilds --chapter azeroth", description="Мулгор у справжньому масштабі.")
    p.add_argument("--chapter", default="azeroth")
    p.add_argument("--brain", choices=["scripted", "claude", "codex"], default="scripted",
                   help="хто керує героєм: scripted (правила), claude (`claude -p`) або codex (`codex exec`)")
    p.add_argument("--model", default=None)
    p.add_argument("--effort", default="low")
    p.add_argument("--think", action="store_true")
    p.add_argument("--lang", default="Ukrainian")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--speed", type=int, default=1, help="початкова швидкість 0-9")
    p.add_argument("--log-dir", default="logs")
    p.add_argument("--explore", action="store_true",
                   help="огляд: герой стоїть і його не вбити, камера вільна, світ живе (WASD, мінікарта, цифри)")
    p.add_argument("--headless", type=int, metavar="TICKS", default=0, help="без вікна: прогнати N тіків")
    p.add_argument("--start", default=None, help="почати біля місця, напр. 'Bloodhoof Village' (для скріншотів)")
    p.add_argument("--pack", default=str(PACK), help="тека з контент-пакетом зони")
    add_gfx_args(p)
    p.set_defaults(zoom=2, view="iso")  # Мулгор — 2.5D за замовчуванням
    args, _unknown = p.parse_known_args(argv)
    seed = args.seed if args.seed is not None else random.randrange(1_000_000)
    world = ZoneWorld(args.pack, seed=seed)
    sim = ZoneSim(world, seed=seed)
    if args.explore:
        brain = ExploreBrain()
    elif args.brain in ("claude", "codex"):
        if not shutil.which(args.brain):
            sys.exit(f"Не знайдено `{args.brain}`. Встановіть і залогіньтесь, або --brain scripted.")
        effort = None if args.effort == "none" else args.effort
        log_dir = Path(args.log_dir) if args.log_dir else None
        if args.brain == "claude":
            brain = make_claude_brain(model=args.model or "haiku", effort=effort, thinking=args.think,
                                      lang=args.lang, log_dir=log_dir)
        else:
            brain = make_codex_brain(model=args.model or "gpt-5.6-luna", effort=effort, lang=args.lang,
                                     log_dir=log_dir)
    else:
        brain = ScriptedZoneBrain()
    if args.explore and not args.start:
        args.start = "Bloodhoof Village"
    if args.start:
        spot = sim.find_place(args.start)
        if spot is None:
            sys.exit(f"--start: невідоме місце {args.start!r}")
        sim.hero.pos = world.nearest_passable(spot[0], 40) or spot[0]
    if args.headless:
        sim.run(brain, args.headless)
    if args.shot:
        from ..gfx.az_app import AzApp

        app = AzApp(sim, brain, seed, speed=args.speed, sprites_dir=args.sprites, size=window_size(args),
                    zoom=args.zoom, view=args.view, headless=True)
        app.paused = True
        print(f"скріншот: {app.shot(args.shot)}")
        return
    if args.headless:
        print(f"{world.clock()} | {sim.status()}")
        return
    from ..gfx.az_app import AzApp
    from .route import coarse_map

    coarse_map(world)  # build the routing map now (a few seconds) instead of on the first go_to in-window

    diary_dir = Path(args.log_dir) if args.log_dir else None
    AzApp(sim, brain, seed, speed=args.speed, sprites_dir=args.sprites, size=window_size(args), zoom=args.zoom, view=args.view,
          fullscreen=args.fullscreen, diary_dir=diary_dir).run()


if __name__ == "__main__":
    main()
