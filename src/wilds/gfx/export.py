"""`wilds-sprites`: export every sprite for viewing, editing and overriding.

    uv run wilds-sprites                      # contact sheets in sprites_export/
    uv run wilds-sprites --strips --gif       # + 1x PNG strips (override format) + GIFs
    uv run wilds-sprites --module tau7_life   # preview one sprite module in isolation
    uv run wilds-sprites --check              # list sprites the manifest still misses

A 1x strip ``png/<name>.png`` dropped into a directory passed as ``--sprites DIR``
to the game replaces that sprite (see ``bank.SpriteBank``).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

from . import manifest  # noqa: E402
from .bank import SpriteBank  # noqa: E402
from .registry import SPRITES, Registry  # noqa: E402
from .sprites import AZEROTH_MODULES, MODULES, load, load_all, load_azeroth  # noqa: E402

BG = (22, 21, 30)
CELL_BG = (34, 32, 46)
CHECK = (44, 42, 58)
LABEL = (200, 198, 214)
DIM = (130, 128, 150)
HEAD = (255, 214, 120)
MAX_W = 1500
PAD = 10
TILE = 16


def init_headless() -> None:
    if not pygame.get_init():
        pygame.display.init()
        pygame.font.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((1, 1))


def family(name: str) -> str:
    """Grouping key for sheets: the first two dotted parts (t7.hero, cp.sprawl); all HUD
    icons share one sheet and the event-log markers another."""
    parts = name.split("@")[0].split(".")
    if parts[0] == "ui":
        return "ui.log" if parts[1] == "log" else "ui"
    return ".".join(parts[:2])


def _checker(surf: pygame.Surface, rect: pygame.Rect, size: int) -> None:
    surf.fill(CELL_BG, rect)
    for y in range(rect.top, rect.bottom, size):
        for x in range(rect.left + ((y - rect.top) // size % 2) * size, rect.right, size * 2):
            surf.fill(CHECK, pygame.Rect(x, y, size, size).clip(rect))


def render_sheet(bank: SpriteBank, names: list[str], scale: int, title: str) -> pygame.Surface:
    font = pygame.font.Font(None, 18)
    small = pygame.font.Font(None, 15)
    cells = []
    for name in names:
        a = bank.art(name)
        frames = bank.frames(name, scale)
        fw, fh = frames[0].get_size()
        label = name.split(".", 2)[-1] if name.count(".") >= 2 else name
        info = f"{a.size[0]}x{a.size[1]}" + (f"  {len(frames)}f @{a.fps:g}" if len(frames) > 1 else "")
        if name in bank.overridden:
            info += "  [override]"
        text_w = max(font.size(label)[0], small.size(info)[0])
        w = max(len(frames) * (fw + 2) - 2, text_w) + 2 * PAD
        h = fh + 2 * PAD + 34
        cells.append((name, label, info, frames, w, h))
    # shelf layout
    x, y, row_h = PAD, 40, 0
    placed = []
    for cell in cells:
        w, h = cell[4], cell[5]
        if x + w > MAX_W and x > PAD:
            x, y, row_h = PAD, y + row_h + PAD, 0
        placed.append((cell, x, y))
        x += w + PAD
        row_h = max(row_h, h)
    width = max([px + c[4] for c, px, _ in placed] + [400]) + PAD
    height = y + row_h + PAD
    sheet = pygame.Surface((width, height))
    sheet.fill(BG)
    sheet.blit(pygame.font.Font(None, 30).render(title, True, HEAD), (PAD, 10))
    for (name, label, info, frames, w, h), px, py in placed:
        fw, fh = frames[0].get_size()
        for i, fr in enumerate(frames):
            r = pygame.Rect(px + PAD + i * (fw + 2), py + PAD, fw, fh)
            _checker(sheet, r, max(4, scale * 2))
            sheet.blit(fr, r)
        sheet.blit(font.render(label, True, LABEL), (px + PAD, py + PAD + fh + 4))
        sheet.blit(small.render(info, True, DIM), (px + PAD, py + PAD + fh + 20))
    return sheet


def mock_scene(bank: SpriteBank, rows: list[str], layers: dict[str, list[str]], scale: int = 3,
               t: float = 0.0) -> pygame.Surface:
    """Render a tiny map for eyeballing seams and composition.

    ``rows`` is a text map; ``layers[ch]`` lists sprite names drawn on that
    tile in order. Each sprite's anchor lands on the tile's ground point
    (bottom centre), so 16x16 tiles fill their cell and taller objects rise
    above it. Objects are drawn row by row, so southern ones overlap northern
    ones like in the game. A name ending in ``@*`` picks a variant by position.
    """
    h, w = len(rows), len(rows[0])
    surf = pygame.Surface((w * TILE * scale, h * TILE * scale), pygame.SRCALPHA)
    surf.fill((*BG, 255))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            for name in layers.get(ch, []):
                if name.endswith("@*"):
                    vs = bank.registry.variants(name[:-2])
                    name = vs[(x * 7 + y * 13) % len(vs)]
                fr = bank.frame(name, t + (x * 0.37 + y * 0.61), scale)
                ax, ay = bank.anchor(name, scale)
                gx, gy = (x * TILE + TILE // 2) * scale, (y * TILE + TILE - 1) * scale
                surf.blit(fr, (gx - ax, gy - ay))
    return surf


def save_gif(bank: SpriteBank, name: str, scale: int, path: Path) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    a = bank.art(name)
    frames = bank.frames(name, scale)
    images = []
    for fr in frames:
        bg = pygame.Surface(fr.get_size())
        bg.fill(CELL_BG)
        bg.blit(fr, (0, 0))
        images.append(Image.frombytes("RGB", bg.get_size(), pygame.image.tobytes(bg, "RGB")))
    duration = int(1000 / a.fps) if a.fps else 200
    images[0].save(path, save_all=True, append_images=images[1:], duration=duration,
                   loop=0 if a.loop else 1, disposal=2)
    return True


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="wilds-sprites", description="Export all Wilds sprites as PNG.")
    p.add_argument("--out", default="sprites_export", help="output directory")
    p.add_argument("--scale", type=int, default=4, help="preview scale for sheets and GIFs")
    p.add_argument("--prefix", default="", help="only sprites whose name starts with this")
    p.add_argument("--module", action="append", choices=(*MODULES, *AZEROTH_MODULES),
                   help="import only this sprite module (repeatable); default: all")
    p.add_argument("--azeroth", action="store_true", help="the Azeroth chapter's art (az_* modules) instead of Wilds")
    p.add_argument("--strips", action="store_true", help="write 1x PNG strips (the override format)")
    p.add_argument("--gif", action="store_true", help="write animated GIFs for animated sprites (Pillow)")
    p.add_argument("--sprites", default=None, help="override directory to preview replaced art")
    p.add_argument("--check", action="store_true", help="only report what the manifest still misses")
    args = p.parse_args(argv)

    init_headless()
    if args.module:
        for m in args.module:
            load(m)
        registry: Registry = SPRITES
    elif args.azeroth:
        registry = load_azeroth()
    else:
        registry = load_all()
    if args.check:
        from ..azeroth import manifest as az_manifest

        chosen = args.module or []
        az = [m[3:] for m in chosen if m in AZEROTH_MODULES]
        wild = [m for m in chosen if m not in AZEROTH_MODULES]
        problems = []
        if wild or not (chosen or args.azeroth):
            problems += manifest.check(registry, wild or None)
        if az or args.azeroth:
            problems += az_manifest.check(registry, az or None)
        for line in problems:
            print(line)
        print(f"{len(registry)} sprites registered, {len(problems)} problems")
        sys.exit(1 if problems else 0)

    bank = SpriteBank(registry, overrides=args.sprites)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = registry.names(args.prefix)
    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(family(n), []).append(n)
    for fam, members in groups.items():
        sheet = render_sheet(bank, members, args.scale, f"{fam}  ({len(members)})")
        pygame.image.save(sheet, str(out / f"sheet-{fam}.png"))
    if args.strips:
        (out / "png").mkdir(exist_ok=True)
        for n in names:
            frames = bank.frames(n, 1)
            w, h = frames[0].get_size()
            strip = pygame.Surface((w * len(frames), h), pygame.SRCALPHA)
            for i, fr in enumerate(frames):
                strip.blit(fr, (i * w, 0))
            pygame.image.save(strip, str(out / "png" / f"{n}.png"))
    gifs = 0
    if args.gif:
        (out / "gif").mkdir(exist_ok=True)
        for n in names:
            if len(bank.frames(n, 1)) > 1:
                gifs += save_gif(bank, n, args.scale, out / "gif" / f"{n}.gif")
    print(f"{len(names)} sprites in {len(groups)} sheets -> {out}" + (f", {gifs} gifs" if args.gif else ""))


if __name__ == "__main__":
    main()
