"""Text-grid pixel art: the single source of truth for every sprite in the game.

A frame is a block of text, one character per pixel. A legend maps characters
to palette colour names (see ``palette.py``); ``.`` is always transparent.
Keeping the art as code makes it diffable and reviewable, lets a recolour
(race skin, role outfit, district theme) be a one-line name mapping, and lets
the tests prove that every game object has a sprite.

    HOPPER = art('''
        ..kk..
        .kwwk.
        kwwwwk
        ''', legend={"w": "bone4"}, note="tiny example")

A legend value may carry an alpha after a colon: ``"glowcyan:96"``.
Rendering to pygame surfaces lives in ``bank.py``; this module is pure Python
so sprite definitions can be validated without a display.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Mapping, Sequence

from .palette import EMISSIVE, PALETTE

Grid = tuple[str, ...]
RGBA = tuple[int, int, int, int]

TRANSPARENT = "."
# Characters every sprite may use without declaring them in its legend.
DEFAULT_LEGEND: dict[str, str] = {"k": "ink", "K": "ink2", "w": "white"}


def color_spec(spec: str) -> RGBA:
    """'name' or 'name:alpha' -> (r, g, b, a)."""
    name, _, alpha = spec.partition(":")
    if name not in PALETTE:
        raise KeyError(f"unknown palette colour '{name}'")
    a = int(alpha) if alpha else 255
    if not 0 <= a <= 255:
        raise ValueError(f"alpha out of range in '{spec}'")
    r, g, b = PALETTE[name]
    return r, g, b, a


# --- grids ----------------------------------------------------------------------


def grid(text: str | Sequence[str]) -> Grid:
    """Parse a text block (or a list of rows) into a rectangular grid.

    Each line is stripped of surrounding whitespace, so art can be indented
    freely inside triple-quoted strings; blank lines at the start/end are
    dropped. Transparent pixels must be written as '.', never as spaces.
    """
    lines = text.splitlines() if isinstance(text, str) else list(text)
    rows = [line.strip() for line in lines]
    while rows and not rows[0]:
        rows.pop(0)
    while rows and not rows[-1]:
        rows.pop()
    if not rows:
        raise ValueError("empty grid")
    width = len(rows[0])
    for i, row in enumerate(rows):
        if len(row) != width:
            raise ValueError(f"grid row {i} is {len(row)} wide, expected {width}: {row!r}")
        if " " in row:
            raise ValueError(f"grid row {i} contains a space; use '.' for transparency: {row!r}")
    return tuple(rows)


def blank(w: int, h: int) -> Grid:
    return tuple(TRANSPARENT * w for _ in range(h))


def size_of(g: Grid) -> tuple[int, int]:
    return len(g[0]), len(g)


def mirror(g: Grid) -> Grid:
    """Flip left-right."""
    return tuple(row[::-1] for row in g)


def flip_v(g: Grid) -> Grid:
    return tuple(reversed(g))


def symmetric(half: str | Grid, center: bool = False) -> Grid:
    """Author the left half, get the whole: left + mirrored left.

    With ``center=True`` the last column of the half is the centre column and is
    not duplicated (odd widths)."""
    g = grid(half) if isinstance(half, str) else half
    return tuple(row + (row[:-1] if center else row)[::-1] for row in g)


def shift(g: Grid, dx: int = 0, dy: int = 0) -> Grid:
    """Move every pixel by (dx, dy) inside the same canvas; what falls off is lost."""
    w, h = size_of(g)
    out = [[TRANSPARENT] * w for _ in range(h)]
    for y, row in enumerate(g):
        for x, ch in enumerate(row):
            nx, ny = x + dx, y + dy
            if ch != TRANSPARENT and 0 <= nx < w and 0 <= ny < h:
                out[ny][nx] = ch
    return tuple("".join(r) for r in out)


def pad(g: Grid, left: int = 0, top: int = 0, right: int = 0, bottom: int = 0) -> Grid:
    w, _ = size_of(g)
    width = w + left + right
    rows = [TRANSPARENT * width] * top
    rows += [TRANSPARENT * left + row + TRANSPARENT * right for row in g]
    rows += [TRANSPARENT * width] * bottom
    return tuple(rows)


def crop(g: Grid, x: int, y: int, w: int, h: int) -> Grid:
    return tuple(row[x:x + w] for row in g[y:y + h])


def overlay(base: Grid, top: Grid, dx: int = 0, dy: int = 0) -> Grid:
    """Paint the non-transparent pixels of ``top`` over ``base`` at (dx, dy)."""
    w, h = size_of(base)
    out = [list(row) for row in base]
    for y, row in enumerate(top):
        for x, ch in enumerate(row):
            nx, ny = x + dx, y + dy
            if ch != TRANSPARENT and 0 <= nx < w and 0 <= ny < h:
                out[ny][nx] = ch
    return tuple("".join(r) for r in out)


def erase(base: Grid, mask: Grid, dx: int = 0, dy: int = 0) -> Grid:
    """Make transparent every pixel of ``base`` covered by a non-'.' pixel of ``mask``."""
    w, h = size_of(base)
    out = [list(row) for row in base]
    for y, row in enumerate(mask):
        for x, ch in enumerate(row):
            nx, ny = x + dx, y + dy
            if ch != TRANSPARENT and 0 <= nx < w and 0 <= ny < h:
                out[ny][nx] = TRANSPARENT
    return tuple("".join(r) for r in out)


def swap(g: Grid, mapping: Mapping[str, str]) -> Grid:
    """Replace characters (not colours): {'a': 'b'} turns every 'a' pixel into 'b'."""
    return tuple("".join(mapping.get(ch, ch) for ch in row) for row in g)


def outline_grid(g: Grid, char: str = "k", diagonal: bool = False) -> Grid:
    """Add a 1px outline of ``char`` around every opaque pixel (inside the canvas)."""
    w, h = size_of(g)
    steps = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if diagonal:
        steps += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    out = [list(row) for row in g]
    for y in range(h):
        for x in range(w):
            if g[y][x] != TRANSPARENT:
                continue
            for dx, dy in steps:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and g[ny][nx] not in (TRANSPARENT, char):
                    out[y][x] = char
                    break
    return tuple("".join(r) for r in out)


# --- art ------------------------------------------------------------------------


@dataclass(frozen=True)
class Art:
    """One sprite: animation frames of equal size plus how to colour and place them."""

    frames: tuple[Grid, ...]
    legend: Mapping[str, str] = field(default_factory=dict)
    fps: float = 0.0
    # pixel (x, y) inside the frame that stands on the tile's ground point;
    # None -> bottom centre (w // 2, h - 1)
    anchor: tuple[int, int] | None = None
    outline: str | None = None  # palette name: auto 1px outline around opaque pixels
    loop: bool = True
    note: str = ""

    def __post_init__(self) -> None:
        if not self.frames:
            raise ValueError("a sprite needs at least one frame")
        size = size_of(self.frames[0])
        for i, f in enumerate(self.frames):
            if size_of(f) != size:
                raise ValueError(f"frame {i} is {size_of(f)}, frame 0 is {size}")
        for ch, spec in self.legend.items():
            if len(ch) != 1:
                raise ValueError(f"legend key {ch!r} must be a single character")
            color_spec(spec)
        used = {ch for f in self.frames for row in f for ch in row} - {TRANSPARENT}
        missing = used - set(self.legend)
        if missing:
            raise ValueError(f"characters without a legend entry: {''.join(sorted(missing))}")
        if self.outline is not None:
            color_spec(self.outline)
        if self.anchor is not None:
            w, h = size
            ax, ay = self.anchor
            if not (0 <= ax < w and 0 <= ay < h):
                raise ValueError(f"anchor {self.anchor} outside the {w}x{h} frame")
        if self.fps < 0:
            raise ValueError("fps must be >= 0")

    @property
    def size(self) -> tuple[int, int]:
        return size_of(self.frames[0])

    @property
    def ground_anchor(self) -> tuple[int, int]:
        if self.anchor is not None:
            return self.anchor
        w, h = self.size
        return w // 2, h - 1

    @property
    def animated(self) -> bool:
        return len(self.frames) > 1 and self.fps > 0

    def frame_index(self, t: float) -> int:
        """Frame to show ``t`` seconds into the animation."""
        n = len(self.frames)
        if n == 1 or self.fps <= 0:
            return 0
        i = int(t * self.fps)
        return i % n if self.loop else min(i, n - 1)

    def rgba(self, index: int = 0) -> bytes:
        """Frame pixels as tightly packed RGBA bytes (row-major), outline applied."""
        g = self.frames[index]
        w, h = size_of(g)
        lut = {ch: color_spec(spec) for ch, spec in self.legend.items()}
        buf = bytearray(w * h * 4)
        solid = [[False] * w for _ in range(h)]
        for y, row in enumerate(g):
            for x, ch in enumerate(row):
                if ch == TRANSPARENT:
                    continue
                r, gg, b, a = lut[ch]
                i = (y * w + x) * 4
                buf[i:i + 4] = bytes((r, gg, b, a))
                solid[y][x] = a == 255
        if self.outline:
            r, gg, b, a = color_spec(self.outline)
            for y in range(h):
                for x in range(w):
                    if g[y][x] != TRANSPARENT:
                        continue
                    if any(0 <= x + dx < w and 0 <= y + dy < h and solid[y + dy][x + dx]
                           for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                        i = (y * w + x) * 4
                        buf[i:i + 4] = bytes((r, gg, b, a))
        return bytes(buf)


def emissive_chars(a: "Art") -> set[str]:
    return {ch for ch, spec in a.legend.items() if spec.partition(":")[0] in EMISSIVE}


def emissive_rgba(a: "Art", index: int = 0) -> bytes | None:
    """Only the light-emitting pixels of a frame (None if it has none)."""
    chars = emissive_chars(a)
    if not chars:
        return None
    g = a.frames[index]
    if not any(ch in chars for row in g for ch in row):
        return None
    w, h = size_of(g)
    buf = bytearray(w * h * 4)
    for y, row in enumerate(g):
        for x, ch in enumerate(row):
            if ch in chars:
                i = (y * w + x) * 4
                buf[i:i + 4] = bytes(color_spec(a.legend[ch]))
    return bytes(buf)


def art(*frames: str | Grid, legend: Mapping[str, str] | None = None, fps: float = 0.0,
        anchor: tuple[int, int] | None = None, outline: str | None = None, loop: bool = True,
        note: str = "") -> Art:
    """Build an Art from text frames; the default legend (k/K/w) is always available."""
    grids = tuple(grid(f) if isinstance(f, str) else tuple(f) for f in frames)
    merged = {**DEFAULT_LEGEND, **(legend or {})}
    return Art(grids, merged, fps, anchor, outline, loop, note)


def recolor(a: Art, mapping: Mapping[str, str], note: str | None = None) -> Art:
    """Same pixels, different colours: maps palette names (not characters).

    Keys may be bare names ('suit2') and match legend values with or without alpha."""
    legend = {}
    for ch, spec in a.legend.items():
        name, sep, alpha = spec.partition(":")
        new = mapping.get(spec) or mapping.get(name)
        legend[ch] = (new + (sep + alpha if sep and ":" not in new else "")) if new else spec
    return replace(a, legend=legend, note=a.note if note is None else note)


def with_legend(a: Art, **entries: str) -> Art:
    """Override single legend entries by character: with_legend(a, s='skin3')."""
    return replace(a, legend={**a.legend, **entries})


def map_frames(a: Art, fn, **changes) -> Art:
    """New Art whose frames are fn(frame) for each frame."""
    return replace(a, frames=tuple(fn(f) for f in a.frames), **changes)


def sequence(*arts: Art, fps: float | None = None, **changes) -> Art:
    """Concatenate frames of several same-size arts (legends merged, later wins)."""
    legend: dict[str, str] = {}
    for a in arts:
        legend.update(a.legend)
    frames = tuple(f for a in arts for f in a.frames)
    return replace(arts[0], frames=frames, legend=legend,
                   fps=arts[0].fps if fps is None else fps, **changes)


def frames_of(texts: Iterable[str]) -> tuple[Grid, ...]:
    return tuple(grid(t) for t in texts)
