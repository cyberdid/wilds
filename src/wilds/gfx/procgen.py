"""Procedural drawing for sprites: a mutable character canvas with shapes,
seamless (periodic) value noise and ordered dithering.

Everything here still produces plain text grids - a generated texture goes
through the same Art/legend/palette pipeline as hand-drawn art, exports the
same way and can be overridden by a PNG the same way. All randomness is
seeded, so the art is identical on every run and machine.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Iterable

from .pixelart import TRANSPARENT, Grid, size_of

# 4x4 Bayer matrix, normalised to (0, 1): classic ordered dithering thresholds
_BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def bayer(x: int, y: int) -> float:
    return (_BAYER[y % 4][x % 4] + 0.5) / 16


def periodic_noise(w: int, h: int, cells: int, seed: int) -> list[list[float]]:
    """Smooth value noise in 0..1 that wraps around at the canvas edges, so a
    texture made from it tiles seamlessly with itself."""
    rng = random.Random(seed)
    lattice = [[rng.random() for _ in range(cells)] for _ in range(cells)]
    out = []
    for y in range(h):
        row = []
        fy = y / h * cells
        y0 = int(fy) % cells
        y1 = (y0 + 1) % cells
        ty = _smooth(fy - int(fy))
        for x in range(w):
            fx = x / w * cells
            x0 = int(fx) % cells
            x1 = (x0 + 1) % cells
            tx = _smooth(fx - int(fx))
            a = lattice[y0][x0] + (lattice[y0][x1] - lattice[y0][x0]) * tx
            b = lattice[y1][x0] + (lattice[y1][x1] - lattice[y1][x0]) * tx
            row.append(a + (b - a) * ty)
        out.append(row)
    return out


def fbm(w: int, h: int, seed: int, octaves: int = 3, cells: int = 2) -> list[list[float]]:
    """Fractal sum of periodic noise octaves, renormalised to 0..1 (still seamless)."""
    total = [[0.0] * w for _ in range(h)]
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        layer = periodic_noise(w, h, cells * (2 ** o), seed * 131 + o * 7)
        for y in range(h):
            for x in range(w):
                total[y][x] += layer[y][x] * amp
        norm += amp
        amp *= 0.5
    lo = min(min(r) for r in total)
    hi = max(max(r) for r in total)
    span = (hi - lo) or 1.0
    return [[(v - lo) / span for v in row] for row in total]


def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


class Canvas:
    """A mutable grid of characters with drawing helpers; ``.grid()`` freezes it."""

    def __init__(self, w: int, h: int, fill: str = TRANSPARENT) -> None:
        self.w, self.h = w, h
        self.px = [[fill] * w for _ in range(h)]

    @classmethod
    def of(cls, g: Grid) -> "Canvas":
        w, h = size_of(g)
        c = cls(w, h)
        c.px = [list(row) for row in g]
        return c

    def copy(self) -> "Canvas":
        c = Canvas(self.w, self.h)
        c.px = [row[:] for row in self.px]
        return c

    def grid(self) -> Grid:
        return tuple("".join(row) for row in self.px)

    # --- pixels -------------------------------------------------------------
    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def get(self, x: int, y: int, default: str = TRANSPARENT) -> str:
        return self.px[y][x] if self.inside(x, y) else default

    def set(self, x: int, y: int, ch: str) -> None:
        if self.inside(x, y):
            self.px[y][x] = ch

    def where(self, pred: Callable[[int, int, str], bool]) -> Iterable[tuple[int, int]]:
        for y in range(self.h):
            for x in range(self.w):
                if pred(x, y, self.px[y][x]):
                    yield x, y

    # --- shapes ---------------------------------------------------------------
    def rect(self, x: int, y: int, w: int, h: int, ch: str, fill: bool = True) -> "Canvas":
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                if fill or yy in (y, y + h - 1) or xx in (x, x + w - 1):
                    self.set(xx, yy, ch)
        return self

    def hline(self, x0: int, x1: int, y: int, ch: str) -> "Canvas":
        for x in range(min(x0, x1), max(x0, x1) + 1):
            self.set(x, y, ch)
        return self

    def vline(self, x: int, y0: int, y1: int, ch: str) -> "Canvas":
        for y in range(min(y0, y1), max(y0, y1) + 1):
            self.set(x, y, ch)
        return self

    def line(self, x0: int, y0: int, x1: int, y1: int, ch: str) -> "Canvas":
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.set(x0, y0, ch)
            if x0 == x1 and y0 == y1:
                return self
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, ch: str, fill: bool = True) -> "Canvas":
        """Pixel ellipse centred on (cx, cy); use .5 centres for even sizes."""
        for y in range(self.h):
            for x in range(self.w):
                nx = (x + 0.5 - cx) / max(rx, 0.01)
                ny = (y + 0.5 - cy) / max(ry, 0.01)
                d = nx * nx + ny * ny
                if d <= 1.0 and (fill or d > 1.0 - 2.2 / max(1.0, min(rx, ry) * 2)):
                    self.set(x, y, ch)
        return self

    def circle(self, cx: float, cy: float, r: float, ch: str, fill: bool = True) -> "Canvas":
        return self.ellipse(cx, cy, r, r, ch, fill)

    def blit(self, g: Grid, dx: int = 0, dy: int = 0) -> "Canvas":
        for y, row in enumerate(g):
            for x, ch in enumerate(row):
                if ch != TRANSPARENT:
                    self.set(x + dx, y + dy, ch)
        return self

    def replace(self, old: str, new: str) -> "Canvas":
        for row in self.px:
            for i, ch in enumerate(row):
                if ch == old:
                    row[i] = new
        return self

    # --- textures ---------------------------------------------------------------
    def noise_fill(self, chars: str, seed: int, cells: int = 4, octaves: int = 2,
                   dither: float = 0.0, only: str | None = None) -> "Canvas":
        """Fill with noise quantised into ``chars`` (dark -> light). ``dither``
        (0..1) blends band edges with a Bayer pattern instead of hard steps.
        ``only`` restricts painting to pixels currently holding one of those chars."""
        field = fbm(self.w, self.h, seed, octaves, cells)
        n = len(chars)
        for y in range(self.h):
            for x in range(self.w):
                if only is not None and self.px[y][x] not in only:
                    continue
                v = field[y][x] * n
                if dither:
                    v += (bayer(x, y) - 0.5) * dither
                self.px[y][x] = chars[max(0, min(n - 1, int(v)))]
        return self

    def speckle(self, ch: str, density: float, seed: int, only: str | None = None,
                cluster: int = 1) -> "Canvas":
        """Sprinkle ``ch`` pixels (clusters of up to ``cluster`` px) at the given density."""
        rng = random.Random(seed)
        count = int(self.w * self.h * density)
        for _ in range(count):
            x, y = rng.randrange(self.w), rng.randrange(self.h)
            for _k in range(rng.randint(1, cluster)):
                if only is None or self.get(x, y) in only:
                    self.set(x, y, ch)
                x = (x + rng.choice((-1, 0, 1))) % self.w
                y = (y + rng.choice((-1, 0, 1))) % self.h
        return self

    def gradient_v(self, chars: str, y0: int = 0, y1: int | None = None, dither: bool = True,
                   only: str | None = None) -> "Canvas":
        """Vertical ramp top -> bottom across ``chars``, Bayer-dithered between bands."""
        y1 = self.h - 1 if y1 is None else y1
        n = len(chars)
        span = max(1, y1 - y0)
        for y in range(max(0, y0), min(self.h, y1 + 1)):
            for x in range(self.w):
                if only is not None and self.px[y][x] not in only:
                    continue
                v = (y - y0) / span * (n - 1)
                if dither:
                    v += bayer(x, y) - 0.5
                self.px[y][x] = chars[max(0, min(n - 1, round(v)))]
        return self

    def shade_edges(self, light: str, dark: str, body: str) -> "Canvas":
        """Cheap 3D: body pixels with open space above/left get ``light``,
        below/right get ``dark`` (light comes from the top-left)."""
        src = [row[:] for row in self.px]
        for y in range(self.h):
            for x in range(self.w):
                if src[y][x] not in body:
                    continue
                up = src[y - 1][x] if y > 0 else TRANSPARENT
                left = src[y][x - 1] if x > 0 else TRANSPARENT
                down = src[y + 1][x] if y + 1 < self.h else TRANSPARENT
                right = src[y][x + 1] if x + 1 < self.w else TRANSPARENT
                if up not in body or left not in body:
                    self.px[y][x] = light
                elif down not in body or right not in body:
                    self.px[y][x] = dark
        return self


def rng_for(*parts) -> random.Random:
    """A deterministic RNG from arbitrary hashable parts (stable across runs)."""
    h = 2166136261
    for p in parts:
        for b in str(p).encode():
            h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return random.Random(h)


def wobble(t: float, period: float = 1.0) -> float:
    """-1..1 sine helper for animation frames generated in code."""
    return math.sin(2 * math.pi * t / period)
