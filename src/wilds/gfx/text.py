"""Fonts and text for the pygame front-end.

Two bundled OFL fonts (see ``fonts/OFL-*.txt``): Tiny5, a pixel face for labels,
numbers and headings, and PT Sans, a clean face designed for Cyrillic, for
everything that is read at length (thoughts, the log, the diary, speech).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pygame

FONT_DIR = Path(__file__).with_name("fonts")
FACES = {
    "pixel": "Tiny5-Regular.ttf",
    "text": "PTSans-Regular.ttf",
    "bold": "PTSans-Bold.ttf",
}
# glyphs the bundled fonts lack, used in the game's own strings; the HUD draws
# real icons for the important ones, so plain-text stand-ins are enough here
_SUBST = str.maketrans({"☾": "", "☀": "", "⚡": "", "⚠": "!", "‼": "!!", "💭": "", "📔": "",
                        "🗨": "", "🚀": "", "🎉": "", "†": "+", "→": "»", "←": "«"})


def clean(text: str) -> str:
    return text.translate(_SUBST).strip()


@lru_cache(maxsize=64)
def font(face: str, size: int) -> pygame.font.Font:
    return pygame.font.Font(str(FONT_DIR / FACES[face]), size)


@lru_cache(maxsize=4096)
def render(text: str, face: str, size: int, color: tuple[int, int, int],
           shadow: tuple[int, int, int] | None = None) -> pygame.Surface:
    """Cached text surface; the pixel face is rendered without antialiasing."""
    f = font(face, size)
    aa = face != "pixel"
    surf = f.render(text, aa, color)
    if shadow is None:
        return surf
    out = pygame.Surface((surf.get_width() + 1, surf.get_height() + 1), pygame.SRCALPHA)
    out.blit(f.render(text, aa, shadow), (1, 1))
    out.blit(surf, (0, 0))
    return out


def wrap(text: str, face: str, size: int, width: int) -> list[str]:
    """Greedy word wrap to a pixel width (long words are split)."""
    f = font(face, size)
    lines: list[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        line = ""
        for word in words:
            candidate = f"{line} {word}" if line else word
            if f.size(candidate)[0] <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            while f.size(word)[0] > width and len(word) > 1:
                cut = len(word)
                while cut > 1 and f.size(word[:cut])[0] > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines


def line_height(face: str, size: int) -> int:
    return font(face, size).get_linesize()
