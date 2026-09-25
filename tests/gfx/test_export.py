"""`wilds-sprites` exports sheets/strips/GIFs, and exported strips round-trip as
art overrides (the path for hand-painted or AI-generated replacements)."""

import pygame

from wilds.gfx.bank import SpriteBank
from wilds.gfx.export import main as export_main


def test_export_sheets_strips_and_gifs(tmp_path, sprites):
    export_main(["--out", str(tmp_path), "--prefix", "t7.hero", "--strips", "--gif", "--scale", "2"])
    assert (tmp_path / "sheet-t7.hero.png").exists()
    strip = tmp_path / "png" / "t7.hero.walk.png"
    img = pygame.image.load(str(strip))
    a = sprites.get("t7.hero.walk")
    assert img.get_size() == (a.size[0] * len(a.frames), a.size[1])
    assert (tmp_path / "gif" / "t7.hero.walk.gif").exists()


def test_png_override_replaces_the_built_in_art(tmp_path, sprites):
    a = sprites.get("t7.hero.idle")
    w, h = a.size
    strip = pygame.Surface((w * 2, h), pygame.SRCALPHA)
    strip.fill((255, 0, 0, 255))
    pygame.image.save(strip, str(tmp_path / "t7.hero.idle.png"))
    bank = SpriteBank(sprites, overrides=tmp_path)
    frames = bank.base("t7.hero.idle")
    assert len(frames) == 2 and frames[0].get_at((0, 0))[:3] == (255, 0, 0)
    assert "t7.hero.idle" in bank.overridden
    assert bank.glow("t7.hero.idle") is None  # overridden art carries no emissive layer
    untouched = SpriteBank(sprites)
    assert untouched.base("t7.hero.idle")[0].get_at((0, 0))[:3] != (255, 0, 0)
