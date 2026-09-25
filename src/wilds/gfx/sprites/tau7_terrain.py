"""Tau-7 terrain: ground, water, rock, flora and every structure on the surface,
plus the three themed wreck interiors. Ground is generated (seamless noise,
seeded), objects are hand-drawn grids."""

from __future__ import annotations

import math
import random

from ..pixelart import art
from ..procgen import Canvas, bayer, fbm
from ..registry import register

T = 16


def _ramp_legend(ramp: str, n: int) -> dict[str, str]:
    return {str(i): f"{ramp}{i}" for i in range(n)}


# --- procedural helpers --------------------------------------------------------------
# Fields are lists of rows of floats. Everything wraps around the tile edges, so a
# texture built from them tiles seamlessly with itself and with its sibling variants.

Field = list[list[float]]


def _norm(f: Field) -> Field:
    lo = min(min(r) for r in f)
    hi = max(max(r) for r in f)
    span = (hi - lo) or 1.0
    return [[(v - lo) / span for v in row] for row in f]


def _emboss(f: Field, dx: int = 1, dy: int = 1) -> Field:
    """Slope toward the light (top-left): >0.5 where a surface faces the light."""
    h, w = len(f), len(f[0])
    return _norm([[f[(y + dy) % h][(x + dx) % w] - f[y][x] for x in range(w)] for y in range(h)])


def _mix(*parts: tuple[float, Field]) -> Field:
    h, w = len(parts[0][1]), len(parts[0][1][0])
    return _norm([[sum(k * f[y][x] for k, f in parts) for x in range(w)] for y in range(h)])


def _cushions(w: int, h: int, seed: int, n: int, rmin: float, rmax: float,
              squash: float = 1.0) -> Field:
    """Periodic field of overlapping domes (moss cushions, cobbles, blisters)."""
    rng = random.Random(seed)
    pts = [(rng.uniform(0, w), rng.uniform(0, h), rng.uniform(rmin, rmax)) for _ in range(n)]
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            best = 0.0
            for px, py, r in pts:
                ddx = min(abs(x + 0.5 - px), w - abs(x + 0.5 - px))
                ddy = min(abs(y + 0.5 - py), h - abs(y + 0.5 - py)) * squash
                d = (ddx * ddx + ddy * ddy) / (r * r)
                if d < 1.0:
                    best = max(best, 1.0 - d)
            row.append(best)
        out.append(row)
    return out


def _quantize(c: Canvas, f: Field, chars: str, weights: list[float], dither: float = 0.0,
              only: str | None = None) -> Canvas:
    """Rank-based quantisation: ``chars[i]`` (dark -> light) covers ``weights[i]`` of the
    pixels, so every variant built this way has the same histogram - and so the same
    mean brightness. ``dither`` blends the band edges with a Bayer pattern."""
    cells = [(x, y) for y in range(c.h) for x in range(c.w) if only is None or c.px[y][x] in only]
    vals = sorted(f[y][x] for x, y in cells)
    total = sum(weights)
    cuts, acc = [], 0.0
    for wgt in weights[:-1]:
        acc += wgt
        cuts.append(vals[min(len(vals) - 1, int(acc / total * len(vals)))])
    for x, y in cells:
        v = f[y][x] + (bayer(x, y) - 0.5) * dither
        i = 0
        while i < len(cuts) and v >= cuts[i]:
            i += 1
        c.px[y][x] = chars[i]
    return c


def _stamp(c: Canvas, x: int, y: int, rows: list[str], wrap: bool = True) -> None:
    """Paint a tiny pattern (``.`` = keep) at (x, y), wrapping around the tile edges."""
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == ".":
                continue
            xx, yy = x + i, y + j
            if wrap:
                c.set(xx % c.w, yy % c.h, ch)
            else:
                c.set(xx, yy, ch)


# --- ground -----------------------------------------------------------------------

MOSS = {**_ramp_legend("moss", 6), "g": "glowcyan", "p": "spore3", "r": "rock2", "R": "rock3"}
FOREST = {**_ramp_legend("moss", 6), "a": "flora1", "b": "flora2", "c": "flora3", "d": "dust1"}
DUST = {**_ramp_legend("dust", 6), "r": "rock2", "R": "rock3", "b": "bone3"}
SCORCH = {"0": "ink2", "2": "rock1", "3": "dust0", "4": "dust1", "5": "grey1",
          "6": "grey2", "e": "fire3", "E": "fire1"}


def _moss(seed: int) -> Canvas:
    rng = random.Random(seed)
    c = Canvas(T, T)
    hump = _cushions(T, T, seed, 12, 2.0, 4.0, squash=1.25)
    fine = fbm(T, T, seed + 7, 2, 4)
    f = _mix((0.55, _emboss(hump)), (0.25, hump), (0.2, fine))
    _quantize(c, f, "1234", [10, 50, 34, 6], dither=0.06)
    # a few tufts: a bright blade over a dark root, never on the tile border
    for _ in range(2):
        x, y = rng.randrange(1, T - 1), rng.randrange(2, T - 1)
        c.set(x, y, "2")
        c.set(x, y - 1, "4")
    return c


def _ground_moss() -> None:
    for i in range(4):
        c = _moss(100 + i)
        register(f"t7.ground.moss@{i}", art(c.grid(), legend=MOSS, note="moss ground"))


def _ground_forest() -> None:
    """Darker, shaded moss under the xeno-flora canopy, with a little violet leaf litter."""
    for i in range(4):
        seed = 150 + i
        rng = random.Random(seed)
        c = Canvas(T, T)
        hump = _cushions(T, T, seed, 11, 2.0, 4.0, squash=1.2)
        fine = fbm(T, T, seed + 3, 2, 4)
        f = _mix((0.5, _emboss(hump)), (0.2, hump), (0.3, fine))
        _quantize(c, f, "0123", [10, 46, 38, 6], dither=0.06)
        # fallen leaves: two small violet slivers, lit on the upper-left tip
        for _ in range(2):
            x, y = rng.randrange(T), rng.randrange(T)
            leaf = rng.choice((["ba", ".a"], ["b.", "aa"], ["bba"], ["b", "a"]))
            _stamp(c, x, y, leaf)
        register(f"t7.ground.forest@{i}", art(c.grid(), legend=FOREST, note="moss under the flora canopy"))


def _dust(seed: int) -> Canvas:
    rng = random.Random(seed)
    c = Canvas(T, T)
    warp = fbm(T, T, seed, 2, 2)
    # wind ripples: a vertical sine warped by noise (periodic: 3 waves per tile)
    rip = [[0.5 + 0.5 * math.sin(2 * math.pi * (3 * y / T + 1.3 * warp[y][x] + 0.15 * math.sin(
        2 * math.pi * x / T))) for x in range(T)] for y in range(T)]
    fine = fbm(T, T, seed + 5, 2, 8)
    base = fbm(T, T, seed + 9, 2, 4)
    f = _mix((0.3, _emboss(rip, 0, 1)), (0.35, base), (0.35, fine))
    _quantize(c, f, "1234", [6, 64, 26, 4], dither=0.1)
    # grains: a few dark pits
    for _ in range(3):
        c.set(rng.randrange(T), rng.randrange(T), "1")
    return c


def _ground_dust() -> None:
    for i in range(4):
        register(f"t7.ground.dust@{i}", art(_dust(300 + i).grid(), legend=DUST, note="red dust ground"))


def _ground_scorch() -> None:
    for i in range(2):
        seed = 400 + i
        rng = random.Random(seed)
        c = Canvas(T, T)
        hump = _cushions(T, T, seed, 10, 2.0, 4.5)
        f = _mix((0.45, _emboss(hump)), (0.3, fbm(T, T, seed, 2, 4)), (0.25, fbm(T, T, seed + 1, 2, 8)))
        # soot and char in the hollows, grey ash on the lit bumps
        _quantize(c, f, "034256", [10, 22, 26, 20, 17, 5], dither=0.1)
        # glassy heat cracks
        x, y = rng.randrange(T), rng.randrange(T)
        for _ in range(7):
            c.set(x % T, y % T, "0")
            x += rng.choice((1, 1, 0))
            y += rng.choice((-1, 0, 1))
        # one ember still glowing in the ash
        x, y = rng.randrange(3, T - 3), rng.randrange(3, T - 3)
        c.set(x, y, "e")
        c.set(x + 1, y, "E")
        register(f"t7.ground.scorch@{i}", art(c.grid(), legend=SCORCH, note="scorched ground"))


# --- water -------------------------------------------------------------------------

WATER = {**_ramp_legend("water", 6), "f": "white", "b": "dust1", "B": "dust2", "d": "dust0",
         "D": "dust3", "k": "ink", "K": "ink2", "m": "moss2"}


def _water_frames(seed: int) -> list:
    """4 seamless frames. The surface itself is still; glints go through a life cycle
    (dot -> dash -> drifting dash -> gone) with staggered phases, so every frame has
    the same amount of sparkle and nothing pops."""
    rng = random.Random(seed)
    base = Canvas(T, T)
    swell = _mix((0.5, fbm(T, T, seed, 2, 4)), (0.5, _emboss(fbm(T, T, seed + 1, 2, 4), 0, 1)))
    _quantize(base, swell, "123", [22, 66, 12], dither=0.1)
    glints = []
    for k in range(8):
        glints.append((rng.randrange(T), rng.randrange(T), k % 4))
    frames = []
    for fr in range(4):
        c = base.copy()
        for x0, y0, phase in glints:
            s = (fr + phase) % 4
            pattern = (["3"], ["343"], [".3443"], ["..33"])[s]
            _stamp(c, x0, y0, pattern)
        frames.append(c.grid())
    return frames


def _water() -> None:
    for i in range(2):
        register(f"t7.ground.water@{i}", art(*_water_frames(500 + i * 17), legend=WATER, fps=3,
                                             note="water surface"))
    _shore()


# The earth bank's height per column (seamless: the ends match). The north-shore foam
# follows the same profile so it always hugs the foot of the bank.
BANK_DEPTH = [5, 5, 6, 6, 5, 5, 5, 6, 7, 6, 5, 5, 6, 6, 5, 5]


# foam clusters along a shore (period 16, so shore tiles chain up seamlessly)
FOAM = "..55.5..f5...55."


def _foam(k: int, fr: int) -> tuple[str, str, str]:
    """Shore profile at position ``k`` along the edge in frame ``fr``: (outer, middle,
    inner) pixels from the land side inwards. Frame 0: the wave has pulled back, a
    line of foam floats 1 px off the shore; frame 1: it washes up against the land."""
    f = FOAM[k % 16]
    g = FOAM[(k + 5) % 16]
    if fr == 0:
        outer = "4" if bayer(k, 0) < 0.8 else "3"
        middle = f if f != "." else "3"
        inner = "3" if bayer(k, 2) < 0.4 else "."
    else:
        outer = g if g != "." else "4"
        middle = "4" if bayer(k, 1) < 0.5 else "3"
        inner = "3" if bayer(k, 2) < 0.25 else "."
    return outer, middle, inner


def _shore() -> None:
    """Overlays on a water tile touching land: foam along the side (laps in and out),
    inner-corner curls, and the earth bank under land to the north (land is higher)."""
    for side in "nsew":
        frames = []
        for fr in range(2):
            c = Canvas(T, T)
            for k in range(T):
                rows = _foam(k, fr)
                for j, ch in enumerate(rows):
                    if ch == ".":
                        continue
                    if side == "n":
                        # the bank covers the top rows; the water meets it at its foot
                        c.set(k, BANK_DEPTH[k] + j, ch)
                    elif side == "s":
                        c.set(k, T - 1 - j, ch)
                    elif side == "w":
                        c.set(j, k, ch)
                    else:
                        c.set(T - 1 - j, k, ch)
                if side == "n":  # the bank's shadow darkens the water right below it
                    y = BANK_DEPTH[k] + 3
                    if bayer(k, y) < 0.5:
                        c.set(k, y, "1")
            frames.append(c.grid())
        register(f"t7.water.edge.{side}", art(*frames, legend=WATER, fps=2, note=f"shore, land {side}"))
    # inner corners: land only diagonally. South corners: a small foam knot in the corner
    # joining the neighbours' foam lines. North corners: the foam runs down the side of
    # the land and turns along the foot of the neighbour's bank.
    knot = (["..3", ".45", "35f"], ["..4", ".35", "45f"])
    for corner in ("ne", "nw", "se", "sw"):
        frames = []
        for fr in range(2):
            c = Canvas(T, T)
            if "s" in corner:
                rows = list(knot[fr])
                if "w" in corner:
                    rows = [r[::-1] for r in rows]
                _stamp(c, T - 3 if "e" in corner else 0, T - 3, rows, wrap=False)
            else:
                foot = BANK_DEPTH[0] if "e" in corner else BANK_DEPTH[-1]
                for y in range(foot + 1):
                    outer, middle, _inner = _foam(y, fr)
                    x_out, x_mid = (T - 1, T - 2) if "e" in corner else (0, 1)
                    c.set(x_out, y, outer)
                    c.set(x_mid, y, middle if middle != "." else "4")
                turn = ["3445", ".335"] if fr == 0 else ["4455", ".345"]
                if "w" in corner:
                    turn = [r[::-1] for r in turn]
                _stamp(c, T - 4 if "e" in corner else 0, foot, turn, wrap=False)
            frames.append(c.grid())
        register(f"t7.water.corner.{corner}", art(*frames, legend=WATER, fps=2, note="inner shore corner"))
    # the earth bank: lit lip, soil strata, a wet dark foot at the waterline
    c = Canvas(T, T)
    rng = random.Random(77)
    for x in range(T):
        d = BANK_DEPTH[x]
        for y in range(d):
            if y == 0:
                ch = "D" if bayer(x, 0) > 0.35 else "B"
            elif y < d - 2:
                ch = "B" if (y == 1 and bayer(x, y) > 0.5) else "b"
            elif y == d - 2:
                ch = "d"
            else:
                ch = "K"
            c.set(x, y, ch)
        if d > 5 and rng.random() < 0.5:  # a pebble or a root in the soil
            c.set(x, rng.randrange(2, d - 2), "d")
    register("t7.water.bank", art(c.grid(), legend=WATER, note="earth bank above the water"))


# --- rock ----------------------------------------------------------------------------

ROCK = {**_ramp_legend("rock", 6), "o": "ore0", "O": "ore1", "Q": "ore2", "c": "cryst0", "C": "cryst1",
        "x": "cryst2", "m": "moss2", "M": "moss3", "n": "moss1"}


def _rock_top(seed: int) -> Canvas:
    c = Canvas(T, T)
    cob = _cushions(T, T, seed, 7, 3.0, 5.5)
    f = _mix((0.55, _emboss(cob)), (0.25, cob), (0.2, fbm(T, T, seed, 2, 4)))
    _quantize(c, f, "12345", [9, 32, 42, 16, 1], dither=0.05)
    return c


def _rock_face(seed: int, veins: list[list[str]]) -> Canvas:
    """South cliff face: stacked angular blocks lit from the top-left, a lit lip at the
    top where the plateau breaks off, and a dark contact shadow at the foot."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    blocks = _cushions(T, T, seed, 9, 3.0, 5.0, squash=0.8)
    f = _mix((0.6, _emboss(blocks)), (0.2, blocks), (0.2, fbm(T, T, seed, 2, 4)))
    # darken toward the foot: the face turns away from the sky
    f = [[v - 0.28 * (y / (T - 1)) ** 1.5 for v in row] for y, row in enumerate(f)]
    _quantize(c, f, "01234", [7, 20, 38, 29, 6], dither=0.06)
    # the plateau's lip: a sliver of top surface, a bright broken edge 1-2 px thick,
    # and a shadow under it; thickness follows a periodic 1D noise (seamless sideways)
    lip = fbm(T, 1, seed + 11, 2, 4)[0]
    for x in range(T):
        thick = 2 if lip[x] > 0.5 else 1
        c.set(x, 0, "3" if lip[(x + 5) % T] < 0.7 else "4")
        for y in range(1, 1 + thick):
            c.set(x, y, "5" if (y == 1 and lip[(x + 9) % T] > 0.8) else "4")
        c.set(x, 1 + thick, "1" if lip[(x + 3) % T] < 0.75 else "2")
    # contact shadow on the ground line
    for x in range(T):
        c.set(x, T - 1, "0")
        if bayer(x, T - 2) < 0.5:
            c.set(x, T - 2, "0" if c.get(x, T - 2) in "01" else "1")
    for pat in veins:
        _stamp(c, rng.randrange(2, T - 5), rng.randrange(4, 9), pat, wrap=False)
    return c


def _rock() -> None:
    for i in range(3):
        c = _rock_top(600 + i)
        register(f"t7.rock.top@{i}", art(c.grid(), legend=ROCK, note="rock plateau"))
    veins = [
        [["..Q", ".QO", "Oo.", "o.."]],
        [["QO..", ".OOo", "...o"]],
        [[".x.", "xCc", "Cc."]],  # a cyan crystal seam instead of ore
    ]
    for i in range(3):
        c = _rock_face(700 + i, veins[i])
        register(f"t7.rock.face@{i}", art(c.grid(), legend=ROCK, note="cliff face with ore"))


# --- sketching objects -------------------------------------------------------------------
# Plants and props are composed from strokes and small pre-shaded stamps, then shaded
# and outlined in one pass, so every frame of an animation gets a clean outline.


def _line(x0: int, y0: int, x1: int, y1: int):
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


class _Sketch:
    """A canvas that bends with the wind: ``bend(y)`` offsets every pixel drawn on row y."""

    def __init__(self, w: int, h: int, bend=None) -> None:
        self.c = Canvas(w, h)
        self.bend = bend or (lambda y: 0)

    def stem(self, pts: list[tuple[int, int]], width: int = 2, ch: str = "S",
             taper: int | None = None) -> "_Sketch":
        """Polyline of ``width`` px (growing rightwards); above row ``taper`` it thins to 1 px."""
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            for x, y in _line(x0, y0, x1, y1):
                wd = 1 if taper is not None and y < taper else width
                for k in range(wd):
                    self.c.set(x + k + self.bend(y), y, ch)
        return self

    def stamp(self, x: int, y: int, rows: list[str]) -> "_Sketch":
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch != ".":
                    self.c.set(x + i + self.bend(y + j), y + j, ch)
        return self

    def shade(self, marker: str = "S", light: str = "3", mid: str = "2", dark: str = "1") -> "_Sketch":
        """Stroke pixels: lit where open to the left, dark where open to the right."""
        src = [row[:] for row in self.c.px]
        for y in range(self.c.h):
            for x in range(self.c.w):
                if src[y][x] != marker:
                    continue
                left = src[y][x - 1] if x > 0 else "."
                right = src[y][x + 1] if x + 1 < self.c.w else "."
                if left == ".":
                    self.c.px[y][x] = light
                elif right == ".":
                    self.c.px[y][x] = dark
                else:
                    self.c.px[y][x] = mid
        return self

    def outline(self, ch: str = "k") -> "_Sketch":
        src = [row[:] for row in self.c.px]
        for y in range(self.c.h):
            for x in range(self.c.w):
                if src[y][x] != ".":
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.c.w and 0 <= ny < self.c.h and src[ny][nx] not in ".z":
                        self.c.px[y][x] = ch
                        break
        return self

    def blob(self, cx: float, cy: float, rx: float, ry: float, chars: str = "12345",
             light: tuple[float, float] = (-0.6, -0.8)) -> "_Sketch":
        """A filled ellipse shaded as a rounded volume lit from the top-left."""
        n = len(chars)
        for y in range(self.c.h):
            for x in range(self.c.w):
                nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                d = nx * nx + ny * ny
                if d > 1.0:
                    continue
                v = 0.5 - 0.5 * (nx * light[0] + ny * light[1]) - 0.25 * d
                v += (bayer(x, y) - 0.5) * 0.1
                self.c.set(x + self.bend(y), y, chars[max(0, min(n - 1, int(v * n)))])
        return self

    def shadow(self, cx: float, cy: float, rx: float, ry: float, ch: str = "z") -> "_Sketch":
        """Soft contact shadow on the ground, only where nothing else is drawn."""
        for y in range(self.c.h):
            for x in range(self.c.w):
                nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                if nx * nx + ny * ny <= 1.0 and self.c.px[y][x] == ".":
                    self.c.px[y][x] = ch
        return self

    def grid(self):
        return self.c.grid()


# --- flora -------------------------------------------------------------------------------

FLORA = {**_ramp_legend("flora", 6), "z": "ink:96", "g": "glowviolet", "m": "moss1", "M": "moss2"}

# pre-shaded stamps (light from the top-left)
BUD_L = [".54.", "5443", "4432", "4322", "3322", ".21.", ".21."]
BUD_S = [".5.", "543", "432", "322", ".2."]
BULB = [".54.", "5443", "4432", "3321", "4432", "3321", ".21."]
BULB_S = [".4.", "443", "332", "432", ".1."]
ROOTS = ["..SS..", ".S21S.", "S2112S"]


def _flora_trident(bend) -> _Sketch:
    """The classic Psi: a stalk splitting into three prongs, each ending in a fibre bud."""
    s = _Sketch(16, 28, bend)
    s.stem([(7, 25), (7, 20), (8, 14), (8, 11)], 2)
    s.stem([(7, 21), (5, 20), (3, 18), (2, 16), (2, 13)], 2)
    s.stem([(8, 19), (10, 18), (12, 16), (13, 13), (13, 11)], 2)
    s.stem([(6, 24), (4, 23), (3, 21)], 1)  # little side leaves
    s.stem([(9, 23), (11, 22)], 1)
    s.shade()
    s.stamp(7, 4, BUD_L)
    s.stamp(1, 9, BUD_S)
    s.stamp(12, 7, BUD_S)
    s.stamp(5, 24, ROOTS)
    s.shade()
    return s.outline().shadow(8, 26.5, 6, 1.6)


def _flora_umbrella(bend) -> _Sketch:
    """A weeping umbrella: a canopy of fronds on a stout stalk, tips drooping."""
    s = _Sketch(16, 28, bend)
    s.stem([(7, 25), (7, 17), (7, 11)], 2)
    s.shade()
    s.blob(7.5, 8.5, 6.2, 4.4, "12345")
    # drooping frond tips below the canopy rim, with gaps between them
    for x, ln in ((2, 4), (4, 3), (6, 2), (9, 2), (11, 3), (13, 4)):
        s.stem([(x, 10), (x, 10 + ln)], 1, ch="T")
    s.shade("T", "3", "2", "2")
    s.stamp(5, 24, ROOTS)
    s.shade()
    return s.outline().shadow(8, 26.5, 5.5, 1.6)


def _flora_bulbs(bend) -> _Sketch:
    s = _Sketch(16, 28, bend)
    s.stem([(6, 25), (5, 18), (4, 11)], 1)
    s.stem([(8, 25), (9, 15), (9, 7)], 1)
    s.stem([(9, 25), (11, 20), (12, 16)], 1)
    s.stem([(7, 25), (4, 23)], 1)
    s.stem([(9, 25), (12, 24)], 1)
    s.shade()
    s.stamp(3, 5, BULB)
    s.stamp(8, 1, BULB)
    s.stamp(11, 11, BULB_S)
    s.stamp(5, 24, ROOTS)
    s.shade()
    return s.outline().shadow(8, 26.5, 6, 1.6)


def _flora() -> None:
    def still(y):
        return 0

    def sway(y):
        return 1 if y < 13 else 0

    for i, build in enumerate((_flora_trident, _flora_umbrella, _flora_bulbs)):
        frames = [build(still).grid(), build(sway).grid()]
        register(f"t7.flora@{i}", art(*frames, legend=FLORA, fps=1.5, note="tall xeno-flora, sways"))


def _stalk() -> None:
    """What is left after cutting a flora: stubs with pale fresh cuts, a sprout regrowing."""
    s = _Sketch(16, 16)
    s.stem([(6, 13), (6, 6)], 2)
    s.stem([(9, 13), (10, 9)], 2)
    s.stem([(4, 13), (3, 10)], 1)
    s.shade()
    s.stamp(5, 5, ["4554", ".32."])   # fresh cut faces, seen from above
    s.stamp(9, 8, ["4554", ".21."])
    s.stamp(2, 9, ["45"])
    s.stamp(11, 10, ["4.4", ".3.", ".2."])  # a sprout already regrowing
    s.stamp(4, 12, ["S2112S".replace("S", "2")])
    s.shade()
    s.outline().shadow(8, 14.5, 5.5, 1.4)
    register("t7.stalk", art(s.grid(), legend=FLORA, note="cut flora stalk, regrowing"))


# --- spore bushes -------------------------------------------------------------------------

SPORE = {"f": "flora1", "0": "spore0", "1": "spore1", "2": "spore2", "3": "spore3", "4": "spore4",
         "5": "spore5", "p": "glowpink", "q": "glowpink:120", "z": "ink:96"}
# the harvested bush: the same leaves drained of colour, pods torn open
SPORE_EMPTY = {"f": "grey0", "0": "grey1", "1": "grey2", "2": "grey3", "3": "grey2", "4": "grey3",
               "5": "grey3", "p": "grey3", "q": "grey1", "z": "ink:96", "h": "ink2", "H": "grey1"}

# leaf clusters (cx, cy, rx, ry), back to front; each is shaded as its own lobe
LOBES = [(7.5, 4.6, 2.8, 2.4), (4.2, 5.8, 2.7, 2.3), (10.9, 5.6, 2.8, 2.4), (2.6, 8.6, 2.6, 2.3),
         (12.4, 8.4, 2.5, 2.3), (6.0, 8.4, 3.0, 2.5), (9.4, 8.8, 3.0, 2.4), (7.6, 10.4, 4.6, 1.9)]
# pod positions (x, y, size, phase): big 4x4 and small 3x3 bulbs
PODS = [(6, 2, 4, 0), (2, 5, 3, 1), (10, 4, 3, 2), (8, 7, 3, 1), (3, 8, 3, 2), (11, 8, 3, 0)]
# pod pixels by pulse stage: (body, highlight, shade); stage 2 glows ('p', '5' are emissive)
POD_STAGES = (("3", "4", "2"), ("4", "5", "3"), ("p", "5", "4"))
POD_BIG = [".hb.", "hbbs", "bbss", ".ss."]
POD_SMALL = [".h.", "hbs", ".s."]


def _bush_body() -> _Sketch:
    s = _Sketch(15, 13)
    for cx, cy, rx, ry in LOBES:
        s.blob(cx, cy, rx, ry, "f012")
    s.stamp(3, 11, ["f0ffff0f"])  # woody base in shadow
    return s


def _spore_pod(stage: int, big: bool) -> list[str]:
    body, hl, shade = POD_STAGES[stage]
    pat = POD_BIG if big else POD_SMALL
    return [r.replace("b", body).replace("h", hl).replace("s", shade) for r in pat]


def _spore_bush() -> None:
    frames = []
    for fr in range(3):
        s = _bush_body()
        for x, y, size, phase in PODS:
            s.stamp(x, y, _spore_pod((fr + phase) % 3, size == 4))
        s.outline()
        # a spore drifting up out of the bush
        s.c.set(*((9, 1), (9, 0), (3, 2))[fr], "q")
        s.shadow(7.5, 12.3, 6.8, 1.3)
        frames.append(s.grid())
    register("t7.spore_bush", art(*frames, legend=SPORE, fps=3, note="spore bush, glowing pods pulse"))
    s = _bush_body()
    for x, y, size, _phase in PODS:
        s.stamp(x, y, [".H..", "HhH.", ".H..", "...."][:size] if size == 4 else [".H.", "Hh.", "..."])
    s.outline().shadow(7.5, 12.3, 6.8, 1.3)
    register("t7.spore_bush_empty", art(s.grid(), legend=SPORE_EMPTY, note="harvested spore bush"))


# --- heater ---------------------------------------------------------------------------------

HEATER = {"q": "rock1", "r": "rock2", "R": "rock3", "t": "rock4", "o": "ore1", "O": "ore2",
          "s": "steel1", "S": "steel2", "m": "steel3", "M": "steel4", "h": "steel5",
          "f": "fire1", "F": "fire2", "e": "fire3", "E": "fire4", "W": "fire5",
          "v": "flora2", "V": "flora3", "a": "grey2", "A": "grey3", "c": "rock1", "z": "ink:96"}

# brazier: a steel bowl bound with flora fibre on a cairn of ore stones
HEATER_BASE = """
..............
..............
..............
..............
..............
..............
..............
..............
..............
..kkkkkkkkkk..
.kMhhhhMMmmmk.
kMfeEEeeeFFfmk
kMFeEWWEeeFfSk
kmhhhMMmmmSSsk
.kmMmmmSSSSsk.
..kVvVVvvVvk..
..kqRtRkRRtk..
.kRRtRqkRoOqk.
.kRqqqkqRRqqk.
..kkkkkkkkkk..
"""

HEATER_ASH = """
..............
..............
..............
..............
..............
..............
..............
..............
..............
..kkkkkkkkkk..
.kMhhhhMMmmmk.
kMcaAAaacaccmk
kMcaaAacacccSk
kmhhhMMmmmSSsk
.kmMmmmSSSSsk.
..kVvVVvvVvk..
..kqRtRkRRtk..
.kRRtRqkRqqqk.
.kRqqqkqRRqqk.
..kkkkkkkkkk..
"""

FLAMES = [
    """
    ..............
    .......F......
    ......Fe....E.
    ......eE.F....
    .....FeEFe....
    ....FeEEeE....
    ....eEWEEe.F..
    ...FeEWWEeFe..
    ...eEWWWWEe...
    ..FeEWWWWEeF..
    ..eEEWWWEEEe..
    """,
    """
    ....E...F.....
    ........e.....
    .......Fe.....
    ....F..eE.....
    ....eF.eEF....
    ....eEFEWe....
    ...FeEEWWe....
    ...eEWWWEeF...
    ..FeEWWWWEe...
    ..eEWWWWWEeF..
    ..eEEWWWEEEe..
    """,
    """
    ...........E..
    ......e.......
    .....Fe...F...
    .....eE...e...
    .....eEF.Fe...
    ....FeWEFeE...
    ....eEWWEEe...
    ...FeEWWWEeF..
    ...eEWWWWWe...
    ..FeEWWWWEeF..
    ..eEEWWWWEEe..
    """,
]


def _heater() -> None:
    from ..pixelart import grid, overlay

    base = grid(HEATER_BASE)
    frames = [overlay(base, grid(f)) for f in FLAMES]
    register("t7.heater", art(*frames, legend=HEATER, fps=6, note="working heater: fibre-bound brazier"))
    register("t7.heater_off", art(grid(HEATER_ASH), legend=HEATER, note="dead heater, cold ash"))


# --- dome -------------------------------------------------------------------------------------

DOME = {**_ramp_legend("tent", 5), "g": "glass2", "G": "glass3", "l": "grey2", "L": "grey3",
        "c": "glowcyan", "s": "steel2", "S": "steel3", "z": "ink:96"}

# the zipped entrance flap at the front of the dome
DOME_DOOR = [
    "...kkkk...",
    "..k1221k..",
    ".k112211k.",
    ".k113211k.",
    "k1113211Kk",
    "k1112211Kk",
    "k1113211Kk",
    "k1112211Kk",
    "kssSSSSssk",
]


def _dome() -> None:
    """Inflatable habitat: an orange shell with inflated tube ribs, a zipped door with a
    status light, a porthole and guy lines staked into the ground."""
    W, H = 24, 22
    c = Canvas(W, H)
    cx, base, rx, ry = 12.0, 19.0, 10.7, 15.5
    lx, ly, lz = -0.5, -0.6, 0.62
    ln = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / ln, ly / ln, lz / ln
    ribs = (-0.66, 0.0, 0.66)
    for y in range(H):
        for x in range(W):
            nx = (x + 0.5 - cx) / rx
            ny = (y + 0.5 - base) / ry
            if ny > 0 or nx * nx + ny * ny > 1:
                continue
            nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
            v = nx * lx + ny * ly + nz * lz
            # panels bulge between the ribs: brighter mid-panel, darker next to a rib
            hw = math.sqrt(max(1e-6, 1 - ny * ny))
            u = nx / hw
            near = min(abs(u - r) for r in ribs)
            v = (v + 0.3) / 1.3 - 0.12 * max(0.0, 0.18 - near) / 0.18 + (bayer(x, y) - 0.5) * 0.08
            ch = "0123"[max(0, min(3, int(v * 4)))]
            # the ribs themselves: inflated tubes, lit left edge, shadowed right edge
            for r in ribs:
                d = (u - r) * hw * rx
                if -1.0 <= d < 0.0:
                    ch = str(min(4, int(ch) + 1))
                elif 0.0 <= d < 1.0:
                    ch = str(max(0, int(ch) - 1))
            c.set(x, y, ch)
    # a skirt seam near the ground, and the dark hem where the shell meets it
    hem = int(base)
    for x in range(W):
        if c.get(x, hem - 3) in "1234":
            c.set(x, hem - 3, str(int(c.get(x, hem - 3)) - 1))
        if c.get(x, hem - 1) in "01234":
            c.set(x, hem - 1, "0")
    for j, row in enumerate(DOME_DOOR):
        for i, ch in enumerate(row):
            if ch != ".":
                c.set(7 + i, 10 + j, ch)
    c.set(12, 9, "c")  # door status light
    for j, row in enumerate([".kk.", "kGwk", "kggk", ".kk."]):  # porthole
        for i, ch in enumerate(row):
            if ch != ".":
                c.set(3 + i, 9 + j, ch)
    g = Canvas.of(c.grid())
    src = [row[:] for row in g.px]
    for y in range(H):
        for x in range(W):
            if src[y][x] != ".":
                continue
            if any(0 <= x + dx < W and 0 <= y + dy < H and src[y + dy][x + dx] != "."
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                g.px[y][x] = "k"
    # guy lines and stakes
    for (x0, y0), (x1, y1) in (((2, 12), (0, 20)), ((21, 12), (23, 20))):
        for x, y in _line(x0, y0, x1, y1):
            if g.get(x, y) == ".":
                g.set(x, y, "l")
    g.set(0, 21, "L")
    g.set(23, 21, "L")
    for y in range(H):
        for x in range(W):
            nx, ny = (x + 0.5 - cx) / (rx + 1.2), (y + 0.5 - 20.4) / 1.5
            if nx * nx + ny * ny <= 1 and g.px[y][x] == ".":
                g.px[y][x] = "z"
    register("t7.dome", art(g.grid(), legend=DOME, note="inflatable habitat dome"))


# --- grave ------------------------------------------------------------------------------------

GRAVE = {"d": "dust1", "D": "dust2", "e": "dust3", "E": "dust4", "s": "steel2", "S": "steel4",
         "r": "rust2", "R": "rust3", "h": "grey4", "H": "grey3", "v": "water4", "V": "water3",
         "f": "flora3", "q": "rock2", "Q": "rock3", "p": "spore4", "P": "spore3", "m": "moss3",
         "z": "ink:96"}

GRAVE_ART = """
.....kkkk.....
....kwhhhk....
...kwhhhvvk...
...khhhHvVk...
....kHHHkk....
..kkkkSskkkk..
.kRRRfSsfRrrk.
..kkkkSskkkk..
.....kSsk.....
...kkkSskkk...
..kEEeSsDpDk..
.kEeeDDDmPDdk.
kQeDDDDDDDddkk
kqkdddddddkQqk
.kzkkkkkkkzkk.
"""


def _grave() -> None:
    register("t7.grave", art(GRAVE_ART, legend=GRAVE, note="a grave: scrap cross, the helmet on top"))


# --- escape pods ------------------------------------------------------------------------------

POD = {
    "w": "white", "h": "grey4", "H": "grey3", "g": "grey2", "G": "grey1",   # hull
    "o": "podorange", "O": "suit1", "u": "suit3",                            # livery stripe
    "r": "rust1", "R": "rust2", "q": "rock1", "Q": "rock0", "t": "ore0",    # charred heat shield
    "s": "steel1", "S": "steel2", "m": "steel3", "M": "steel4", "n": "steel5",  # metal parts
    "c": "cryst1", "C": "cryst0", "x": "glowcyan", "v": "water5",           # window
    "b": "glass1", "B": "glass2", "j": "glass3",                            # solar cells
    "e": "dust0", "E": "dust1", "d": "dust2", "D": "dust3",                 # pushed-up earth
    "L": "neon_red", "l": "red1",                                           # status light
    "f": "fire4", "F": "fire5", "y": "fire3", "Y": "fire1",                 # sparks, embers
    "a": "grey3:130", "A": "grey2:100",                                     # smoke
    "z": "ink:96", "Z": "ink:150",
}
HULL = "GgHhw"  # hull tones, dark -> light


class _Bell:
    """A re-entry capsule (a bell with a rounded heat-shield base), possibly tilted.

    ``top`` is the centre of the narrow end, ``angle`` tilts the axis (radians, 0 =
    upright). ``at(x, y)`` gives (s, u) for pixels inside: s = 0 at the top .. 1 at the
    rim of the heat shield (>1 on the shield), u = -1 left edge .. 1 right edge."""

    def __init__(self, top: tuple[float, float], length: float, w_top: float, w_bot: float,
                 cap: float, angle: float = 0.0) -> None:
        self.tx, self.ty = top
        self.length, self.w_top, self.w_bot, self.cap = length, w_top, w_bot, cap
        self.ax, self.ay = math.sin(angle), math.cos(angle)   # axis, top -> bottom
        self.px_, self.py_ = math.cos(angle), -math.sin(angle)  # across, left -> right

    def at(self, x: int, y: int):
        dx, dy = x + 0.5 - self.tx, y + 0.5 - self.ty
        s_len = dx * self.ax + dy * self.ay
        r_len = dx * self.px_ + dy * self.py_
        if s_len < 0:
            return None
        if s_len <= self.length:
            k = s_len / self.length
            w = self.w_top + (self.w_bot - self.w_top) * k ** 0.75
        elif s_len <= self.length + self.cap:
            k2 = (s_len - self.length) / self.cap
            w = self.w_bot * math.sqrt(max(0.0, 1 - k2 * k2))
        else:
            return None
        if w <= 0 or abs(r_len) > w:
            return None
        return s_len / self.length, r_len / w

    def screen(self, s: float, u: float) -> tuple[int, int]:
        """Pixel at axis position s (0..1) and across position u (-1..1)."""
        s_len = s * self.length
        w = self.w_top + (self.w_bot - self.w_top) * max(0.0, min(1.0, s)) ** 0.75
        x = self.tx + s_len * self.ax + u * w * self.px_
        y = self.ty + s_len * self.ay + u * w * self.py_
        return int(x), int(y)

    def paint(self, c: Canvas, stripe: tuple[float, float] = (0.5, 0.62)) -> None:
        lx, ly, lz = -0.45, -0.6, 0.66
        ln = math.sqrt(lx * lx + ly * ly + lz * lz)
        lx, ly, lz = lx / ln, ly / ln, lz / ln
        slope = (self.w_bot - self.w_top) / self.length
        for y in range(c.h):
            for x in range(c.w):
                hit = self.at(x, y)
                if hit is None:
                    continue
                s, u = hit
                nz = math.sqrt(max(0.0, 1 - u * u))
                # outward normal: across the hull, toward the viewer, tilted up the cone
                up = slope if s <= 1 else -(s - 1) * self.length / self.cap
                nxs = u * self.px_ - up * self.ax * 0.8
                nys = u * self.py_ - up * self.ay * 0.8
                n = math.sqrt(nxs * nxs + nys * nys + nz * nz) or 1
                v = (nxs * lx + nys * ly + nz * lz) / n
                v += (bayer(x, y) - 0.5) * 0.12
                if s > 1.0:  # the charred heat shield
                    ch = "QQqt"[max(0, min(3, int((v + 0.3) * 3)))]
                else:
                    ch = HULL[max(0, min(4, int((v + 0.25) / 1.2 * 5)))]
                    # the livery stripe: a ring, so its front arc sags toward the viewer
                    ring = s - 0.07 * nz
                    if stripe[0] <= ring < stripe[1]:
                        ch = "o" if v > 0.25 else "O"
                c.set(x, y, ch)


def _outline_canvas(c: Canvas, skip: str = ".zZaAeEdD") -> None:
    """Ink outline around every pixel not in ``skip`` (ground and smoke stay unoutlined)."""
    src = [row[:] for row in c.px]
    for y in range(c.h):
        for x in range(c.w):
            if src[y][x] != ".":
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < c.w and 0 <= ny < c.h and src[ny][nx] not in skip:
                    c.px[y][x] = "k"
                    break


def _crater(c: Canvas, cx: float, cy: float, rx: float, ry: float, seed: int) -> None:
    """Pushed-up earth around an impact: an irregular lit rim of clods, a charred hollow."""
    rng = random.Random(seed)
    wob = fbm(32, 1, seed, 2, 4)[0]
    for y in range(c.h):
        for x in range(c.w):
            nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
            ang = (math.atan2(ny, nx) / (2 * math.pi)) % 1.0
            d = (nx * nx + ny * ny) / (0.8 + 0.35 * wob[int(ang * 31)])
            if d > 1.0 or c.px[y][x] != ".":
                continue
            if d > 0.55:  # the rim: lit on its far (north) side, in shadow on the near side
                ch = "d" if ny < -0.1 else ("E" if bayer(x, y) < 0.6 else "e")
                if ny < -0.5 and bayer(x, y) > 0.55:
                    ch = "D"
            else:  # the charred hollow
                ch = "e" if bayer(x, y) < 0.35 else "Z"
            c.px[y][x] = ch
    for _ in range(6):  # clods thrown out onto the rim
        a = rng.uniform(0, 2 * math.pi)
        x = int(cx + math.cos(a) * rx * rng.uniform(0.95, 1.1))
        y = int(cy + math.sin(a) * ry * rng.uniform(0.95, 1.1))
        if 0 <= x < c.w - 1 and 0 <= y < c.h - 1 and c.px[y][x] == ".":
            c.set(x, y, "d")
            c.set(x + 1, y, "e")


def _shadow_canvas(c: Canvas, cx: float, cy: float, rx: float, ry: float, ch: str = "z") -> None:
    for y in range(c.h):
        for x in range(c.w):
            nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
            if nx * nx + ny * ny <= 1 and c.px[y][x] == ".":
                c.px[y][x] = ch


# solar wings (drawn before the hull, outlined together with it): a steel frame holding
# dark cells, lit far edge; the right wing's hinge broke - it hangs with a smashed cell
WING_L = [
    ".nmnmnmn",
    "jbBjbBjS",
    "bBjbBjbS",
    "jbBjbBjS",
    "SSSSSSSs",
]
WING_R_BROKEN = [
    "nm......",
    "jbnm....",
    "bBjbm...",
    ".bBgbS..",
    "..jGgjS.",
    "...SbBjS",
    "....SSSs",
]
POD_WINDOW = [".kkk.", "kvxck", "kccCk", ".kkk."]
POD_HATCH = [".kkkk.", "kgHHgk", "kHhhHk", "kHoOHk", "kHhhHk", "kgHHgk", ".kkkk."]
POD_RING = ["MnnmS", "mSssS"]
# the repaired beacon: a mast with a dish, covering every pixel of the snapped one
POD_BEACON = [
    "kxkkkkk.",
    "kMknMMmk",
    "kMkmSSsk",
    "kMkkSskk",
    "kmkk.kk.",
    "kmk.....",
]


def _pod_base(fr: int) -> Canvas:
    c = Canvas(32, 24)
    _crater(c, 16.0, 21.0, 12.0, 2.6, 91)
    _stamp(c, 1, 10, WING_L, wrap=False)
    _stamp(c, 23, 11, WING_R_BROKEN, wrap=False)
    bell = _Bell((16.5, 7.0), 11.5, 3.8, 8.4, 2.4, angle=-0.08)
    bell.paint(c)
    _stamp(c, 14, 5, POD_RING, wrap=False)       # docking ring on the narrow top
    _stamp(c, 11, 10, POD_HATCH, wrap=False)
    _stamp(c, 18, 9, POD_WINDOW, wrap=False)
    c.set(22, 14, "L" if fr == 0 else "l")      # status light blinks
    # the snapped beacon mast: a stub bent over at the break, a torn cable hanging
    _stamp(c, 16, 1, ["..mm", ".M..", "M...", "M..."], wrap=False)
    _outline_canvas(c)
    c.set(20, 2, "l")
    c.set(20, 3, "l")
    if fr == 1:  # the torn end sparks
        c.set(20, 0, "f")
        c.set(21, 1, "F")
        c.set(19, 0, "y")
    _shadow_canvas(c, 16.0, 23.0, 13.5, 1.3)
    return c


def _pod() -> None:
    frames = [_pod_base(fr).grid() for fr in range(2)]
    register("t7.pod", art(*frames, legend=POD, fps=2, note="the hero's crashed escape pod, beacon broken"))
    # overlay: the repaired beacon mast (covering the broken one), a dish, a blinking light
    frames = []
    for fr in range(2):
        c = Canvas(32, 24)
        rows = [r.replace("x", "x" if fr == 0 else "C") for r in POD_BEACON]
        _stamp(c, 14, 0, rows, wrap=False)
        frames.append(c.grid())
    register("t7.pod.antenna", art(*frames, legend=POD, fps=2,
                                   note="overlay on t7.pod: repaired beacon mast, beacon blinking"))
    # overlay: heater on - porthole and hatch seams glow warm, light spills on the ground
    warm = {**POD, "1": "fire4", "2": "fire3", "3": "win_warm", "4": "fire3:110", "5": "fire4:70"}
    frames = []
    for fr in range(2):
        c = Canvas(32, 24)
        _stamp(c, 19, 10, ["331" if fr == 0 else "313", "122"], wrap=False)
        for y in range(11, 16):
            c.set(11, y, "4" if (y + fr) % 2 else "2")
            c.set(16, y, "4")
        _stamp(c, 12, 22, ["5454" if fr == 0 else "4545"], wrap=False)
        frames.append(c.grid())
    register("t7.pod.glow", art(*frames, legend=warm, fps=3, note="overlay on t7.pod: heater on, warm glow"))


def _crash() -> None:
    """The second pod: the same capsule, slammed in at an angle and half buried, hatch
    blown off (a dark doorway), a wing torn away, the hull split open and smoking."""
    frames = []
    for fr in range(2):
        c = Canvas(32, 24)
        _crater(c, 16.0, 20.6, 14.0, 3.0, 17)
        _stamp(c, 22, 13, ["nmnmn.", "jbBjbS", "bBGgbS", "SSSSSs"], wrap=False)  # bent wing
        bell = _Bell((12.5, 5.5), 12.0, 3.6, 8.2, 2.4, angle=0.5)
        bell.paint(c)
        # earth thrown up over the buried side
        for y in range(15, 24):
            for x in range(15, 30):
                nx, ny = (x + 0.5 - 22.5) / 7.5, (y + 0.5 - 20.5) / 3.2
                if nx * nx + ny * ny <= 1 and c.get(x, y) != ".":
                    c.set(x, y, "d" if ny < -0.45 else ("E" if bayer(x, y) < 0.6 else "e"))
        # soot streaks and dents
        rng = random.Random(23)
        for _ in range(8):
            x, y = rng.randrange(8, 22), rng.randrange(6, 19)
            for k in range(rng.randint(2, 3)):
                if c.get(x + k, y + k // 2) in "GgHhwoO":
                    c.set(x + k, y + k // 2, "G" if k else "q")
        # the hatch is gone: a dark doorway (someone is still inside)
        _stamp(c, 11, 10, [".kkk.", "kQQQk", "kQQqk", "kQqQk", "kQQQk", "kqQQk", ".kkk."], wrap=False)
        # a split near the top of the hull: torn bright edges, embers glowing inside
        _stamp(c, 15, 6, [".hh.h", "hQQhQ", "hQyQh", ".hQh."], wrap=False)
        if fr == 1:
            c.set(17, 8, "f")
            c.set(16, 7, "y")
        _outline_canvas(c)
        # the blown-off hatch lying in the dust, the other wing torn away beside it
        _stamp(c, 0, 18, [".kkkk.", "kgHHgk", "kHoOHk", "kgHHgk", ".kkkk."], wrap=False)
        _stamp(c, 25, 19, ["kkkkkkk", "kjbBjbk", "kkkkkkk"], wrap=False)
        puffs = [[(16, 4, ["aa", "aa"]), (17, 2, [".a", "aA"]), (16, 0, ["A.", "AA"])],
                 [(17, 4, ["aa", ".a"]), (16, 2, ["aA", "a."]), (17, 0, [".A", "AA"])]][fr]
        for x, y, pat in puffs:
            for j, row in enumerate(pat):
                for i, ch in enumerate(row):
                    if ch != "." and c.get(x + i, y + j) == ".":
                        c.set(x + i, y + j, ch)
        _shadow_canvas(c, 16.0, 23.0, 15.0, 1.3)
        frames.append(c.grid())
    register("t7.crash", art(*frames, legend=POD, fps=2,
                             note="the second pod's crash site: half buried, hatch blown off, smoking"))


_ground_moss()
_ground_forest()
_ground_dust()
_ground_scorch()
_water()
_rock()
_flora()
_stalk()
_spore_bush()
_heater()
_dome()
_grave()
_pod()
_crash()
