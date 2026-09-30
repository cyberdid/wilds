"""Azeroth / Mulgore art: terrain. Must satisfy
``wilds.azeroth.manifest.required()["terrain"]`` (see docs/azeroth/mulgore-art-manifest.md).

Ground is generated from seeded, periodic noise (seamless with itself and with its sibling
variants: every variant of a ground type is quantised to the same colour histogram, so the
same mean brightness). Walls and boulders are procedural too; the scattered decorations are
small hand-placed shapes, soft (no outline) with a translucent contact shadow.

Edge overlays follow the Tau-7 shore convention: ``az.edge.<kind>.<side>`` is drawn on a
tile of ``<kind>`` (water, dirt, cliff) whose neighbour on ``<side>`` is grass; it paints the
grass fringe creeping in from that side (plus a bank and foam for water, roots for a cliff)
and is transparent elsewhere. ``corner.<c>`` is for grass only on the diagonal ``<c>``.
Every fringe is 3 px deep where it meets the tile corners, so sides and corners chain up.
"""

from __future__ import annotations

import math
import random

from ..palette import _ramp
from ..pixelart import art
from ..procgen import Canvas, bayer, fbm
from ..registry import register

T = 16

# --- colours: Mulgore's warm daylight -------------------------------------------------------
_ramp("azt_grass", "#1e3321", "#2f4d27", "#4a6a2b", "#6a8932", "#8fa843", "#bcc463")  # golden-green prairie
_ramp("azt_straw", "#3a2f1b", "#5b4924", "#7f672e", "#a5893d", "#c8ac58", "#e5d18a")  # dry grass, straw
_ramp("azt_soil", "#2a1915", "#462a1d", "#654027", "#845735", "#a37447", "#c39562", "#dcb784")  # earth
_ramp("azt_rock", "#1e1219", "#361c1e", "#552a23", "#763d2b", "#975536", "#b67146", "#d4955f",
      "#ebbd85")  # red-brown mesa stone
_ramp("azt_lake", "#10263f", "#173a5a", "#1f5476", "#2b7090", "#4a93aa", "#86c2cc", "#d2eee8")
_ramp("azt_shoal", "#1f5a78", "#2d7189", "#448896", "#619d9f", "#86b5a8", "#b9d2bb")  # clear water over sand


def _chars(chars: str, ramp: str) -> dict[str, str]:
    return {ch: f"{ramp}{i}" for i, ch in enumerate(chars)}


# One legend for every ground tile and overlay, so textures can be copied between them.
GRASS_CH, STRAW_CH, SOIL_CH = "012345", "abcdef", "ABCDEFG"
ROCK_CH, LAKE_CH, SHOAL_CH = "mnopqrst", "HIJKLMN", "UVWXYZ"
TER = {**_chars(GRASS_CH, "azt_grass"), **_chars(STRAW_CH, "azt_straw"), **_chars(SOIL_CH, "azt_soil"),
       **_chars(ROCK_CH, "azt_rock"), **_chars(LAKE_CH, "azt_lake"), **_chars(SHOAL_CH, "azt_shoal"),
       "z": "ink:72", "y": "ink:40"}


# --- procedural helpers (periodic fields: everything wraps around the tile edges) -------------

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


def _cushions(w: int, h: int, seed: int, n: int, rmin: float, rmax: float, squash: float = 1.0) -> Field:
    """Periodic field of overlapping domes (clods, slabs, grass clumps)."""
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


def _quantize(c: Canvas, f: Field, chars: str, weights: list[float], dither: float = 0.0) -> Canvas:
    """Rank-based quantisation: ``chars[i]`` covers ``weights[i]`` of the pixels, so every
    variant built this way has the same histogram and the same mean brightness."""
    cells = [(x, y) for y in range(c.h) for x in range(c.w)]
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
            if wrap:
                c.set((x + i) % c.w, (y + j) % c.h, ch)
            else:
                c.set(x + i, y + j, ch)


# --- grass ---------------------------------------------------------------------------------------


def _window(i: int, margin: float = 2.5) -> float:
    """0 at the tile border, 1 from ``margin`` px inwards (smooth)."""
    d = min(i + 0.5, T - i - 0.5) / margin
    return 1.0 if d >= 1 else d * d * (3 - 2 * d)


def _varied(f: Field, seed: int, amp: float) -> Field:
    """Add large-scale variation (sunlit swathes, shaded hollows) that fades out toward the
    tile border: each variant gets its own big shapes, while every border stays at the
    common average, so any two siblings still meet without a seam."""
    low = fbm(T, T, seed, 2, 3)
    return [[f[y][x] + amp * (low[y][x] - 0.5) * _window(x) * _window(y) for x in range(T)] for y in range(T)]


# --- grass ---------------------------------------------------------------------------------------


def _grass(seed: int) -> Canvas:
    """Short prairie grass: soft clumps lit from the top-left, big sunlit and shaded swathes,
    little blade flecks and a few golden seed heads - the warm yellow-green of Mulgore."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    hump = _cushions(T, T, seed, 11, 2.2, 4.2, squash=1.35)
    f = _mix((0.5, _emboss(hump)), (0.2, hump), (0.3, fbm(T, T, seed + 7, 2, 4)))
    _quantize(c, _varied(f, seed + 50, 1.0), "12345", [8, 32, 38, 19, 3], dither=0.14)
    for _ in range(7):  # blades: a shaded root under a lit tip
        x, y = rng.randrange(T), rng.randrange(T)
        c.set(x, y, "2")
        c.set(x, (y - 1) % T, "4")
    for _ in range(3):  # seed heads catching the sun
        c.set(rng.randrange(1, T - 1), rng.randrange(1, T - 1), "d")
    return c


def _tall_grass(seed: int) -> Canvas:
    """Tall grass: a dark, dense sward full of long leaning blades with golden tips."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    f = _mix((0.5, fbm(T, T, seed, 2, 4)), (0.5, _emboss(_cushions(T, T, seed + 1, 9, 2.5, 4.5, 1.6), 1, 1)))
    _quantize(c, _varied(f, seed + 50, 1.0), "0123", [10, 38, 40, 12], dither=0.12)
    # blades, back to front, spread over a jittered 4x4 grid so none clump; they lean right
    # (the prairie wind): back row dim, front row with a lit shaft and a golden tip
    for layer, (lo, hi, shaft, tip) in enumerate(((3, 4, "2", "3"), (4, 6, "3", "4"))):
        for k in range(16):
            x = (k % 4) * 4 + rng.randrange(4) + layer * 2
            y = (k // 4) * 4 + rng.randrange(4) + layer * 2
            ln = rng.randrange(lo, hi)
            for j in range(ln):
                xx = x + (j * 2 // ln if k % 3 else 0)
                ch = "1" if j == 0 else (shaft if j < ln - 1 else tip)
                if layer and j == ln - 1 and k % 3 == 1:
                    ch = "e"
                c.set(xx % T, (y - j) % T, ch)
            if layer:
                c.set((x + 1) % T, y % T, "0")  # shadow right of the root
    return c


def _dry_grass(seed: int) -> Canvas:
    """Dry grass: yellowed straw in soft tussocks, loose strands blown every which way,
    a green blade or a bit of bare earth here and there."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    tus = _cushions(T, T, seed, 10, 2.5, 4.5, squash=1.4)
    f = _mix((0.45, _emboss(tus)), (0.2, tus), (0.35, fbm(T, T, seed + 3, 2, 4)))
    _quantize(c, _varied(f, seed + 50, 1.0), "bcde", [10, 36, 40, 14], dither=0.18)
    for _ in range(9):  # strands: a lit stroke over its own shadow, random directions
        x, y = rng.randrange(T), rng.randrange(T)
        dx, dy = rng.choice(((1, 0), (1, -1), (1, 1), (-1, -1)))
        for j in range(rng.randrange(2, 4)):
            c.set((x + dx * j) % T, (y + dy * j) % T, "e")
            c.set((x + dx * j) % T, (y + dy * j + 1) % T, "b")
    for _ in range(2):  # a green blade still alive
        x, y = rng.randrange(1, T - 1), rng.randrange(2, T - 1)
        c.set(x, y, "2")
        c.set(x, y - 1, "3")
    x, y = rng.randrange(2, T - 3), rng.randrange(2, T - 2)  # bare soil peeking through
    c.set(x, y, "C")
    c.set(x + 1, y, "B")
    return c


# --- earth -----------------------------------------------------------------------------------------


def _dirt(seed: int) -> Canvas:
    """Bare earth: flat and quiet - broad soft shading, a few pebbles and one dry crack."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    f = _mix((0.6, fbm(T, T, seed, 2, 3)), (0.3, _emboss(fbm(T, T, seed + 1, 2, 3))),
             (0.1, fbm(T, T, seed + 3, 1, 8)))
    _quantize(c, _varied(f, seed + 50, 0.5), "BCDE", [8, 40, 42, 10], dither=0.07)
    for _ in range(2):  # pebbles: a lit top over a shadow, away from the edges
        x, y = rng.randrange(2, T - 2), rng.randrange(2, T - 3)
        c.set(x, y, "E")
        c.set(x, y + 1, "B")
    x, y = rng.randrange(3, T - 7), rng.randrange(4, T - 4)  # a dry crack
    for _k in range(4):
        c.set(x, y, "B")
        x += 1
        y += rng.choice((-1, 0, 0, 1))
    return c


def _road(seed: int) -> Canvas:
    """Packed pale dirt: the same earth as ``dirt`` one step lighter and smoother."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    f = _mix((0.35, _emboss(fbm(T, T, seed, 2, 2))), (0.45, fbm(T, T, seed + 1, 2, 2)),
             (0.2, fbm(T, T, seed + 2, 1, 4)))
    _quantize(c, _varied(f, seed + 50, 0.5), "CDEF", [6, 34, 48, 12], dither=0.06)
    for _ in range(2):  # hoof-worn dimples and a pale grain
        x, y = rng.randrange(2, T - 2), rng.randrange(2, T - 2)
        c.set(x, y, "C")
        c.set(x + 1, y, "D")
    for _ in range(2):
        c.set(rng.randrange(2, T - 2), rng.randrange(2, T - 2), "G")
    return c


def _mesa(seed: int) -> Canvas:
    """Red-brown plateau: broad flat sandstone, wind-smoothed - soft shading only and a rare
    hairline crack, no grain."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    f = _mix((0.55, fbm(T, T, seed, 2, 3)), (0.3, _emboss(fbm(T, T, seed + 1, 2, 3))),
             (0.15, fbm(T, T, seed + 2, 1, 8)))
    _quantize(c, _varied(f, seed + 50, 0.6), "pqrs", [8, 38, 42, 12], dither=0.07)
    if seed % 3 == 0:  # a hairline crack on one variant, kept off the borders
        x, y = rng.randrange(3, T - 9), rng.randrange(4, T - 4)
        for _k in range(rng.randrange(4, 6)):
            c.set(x, y, "o")
            x += 1
            y = max(3, min(T - 4, y + rng.choice((-1, 0, 0, 1))))
    return c


# --- water -------------------------------------------------------------------------------------------


def _lake_frames(seed: int) -> list:
    """4 seamless frames: a still swell, and glints going through a life cycle
    (dot -> dash -> drifting dash -> gone) with staggered phases, so no frame pops."""
    rng = random.Random(seed)
    base = Canvas(T, T)
    swell = _mix((0.5, fbm(T, T, seed, 2, 4)), (0.5, _emboss(fbm(T, T, seed + 1, 2, 4), 0, 1)))
    _quantize(base, swell, "IJK", [22, 62, 16], dither=0.12)
    glints = [(rng.randrange(T), rng.randrange(T), k % 4) for k in range(8)]
    frames = []
    for fr in range(4):
        c = base.copy()
        for x0, y0, phase in glints:
            s = (fr + phase) % 4
            _stamp(c, x0, y0, (["L"], ["LML"], [".LMML"], ["..LL"])[s])
        frames.append(c.grid())
    return frames


def _shallows_frames(seed: int) -> list:
    """Calm, clear water over a sandy bottom: broad soft ripples in the sand and one slow
    band of light that drifts across (one step brighter, the same number of pixels in every
    frame, so nothing flickers)."""
    base = Canvas(T, T)
    warp = fbm(T, T, seed, 2, 2)
    rip = [[0.5 + 0.5 * math.sin(2 * math.pi * (2 * y / T + 0.6 * warp[y][x] + 0.1 * math.sin(
        2 * math.pi * x / T))) for x in range(T)] for y in range(T)]
    f = _mix((0.45, fbm(T, T, seed + 1, 2, 2)), (0.35, _emboss(rip, 0, 1)), (0.2, rip))
    tones = "UVWXY"
    _quantize(base, f, tones[0:3], [28, 52, 20], dither=0.0)
    wave = fbm(T, T, seed + 2, 2, 2)
    frames = []
    for fr in range(4):
        v = [[math.sin(2 * math.pi * (wave[y][x] * 2 + fr / 4)) for x in range(T)] for y in range(T)]
        ranked = sorted(((v[y][x], x, y) for y in range(T) for x in range(T)), reverse=True)
        c = base.copy()
        for _v, x, y in ranked[:16]:
            c.set(x, y, tones[tones.index(base.px[y][x]) + 1])
        frames.append(c.grid())
    return frames


# --- walls: the zone's rim -----------------------------------------------------------------------------


def _facets(seed: int, n: int, stretch: float) -> tuple[list[list[int]], list[list[float]]]:
    """Periodic Voronoi cells: which rock facet owns each pixel, and its distance to the
    facet's border (0 on the border). ``stretch`` < 1 makes tall columns, > 1 flat ledges."""
    rng = random.Random(seed)
    pts = [(rng.uniform(0, T), rng.uniform(0, T)) for _ in range(n)]
    own = [[0] * T for _ in range(T)]
    edge = [[0.0] * T for _ in range(T)]
    for y in range(T):
        for x in range(T):
            ds = []
            for i, (px, py) in enumerate(pts):
                dx = min(abs(x + 0.5 - px), T - abs(x + 0.5 - px))
                dy = min(abs(y + 0.5 - py), T - abs(y + 0.5 - py)) * stretch
                ds.append((dx * dx + dy * dy, i))
            ds.sort()
            own[y][x] = ds[0][1]
            edge[y][x] = math.sqrt(ds[1][0]) - math.sqrt(ds[0][0])
    return own, edge


def _rock_height(seed: int, n: int, stretch: float, cap: float) -> Field:
    """Blocks of rock as a height field: 0 in the cracks between them, rising to 1 inside."""
    _own, edge = _facets(seed, n, stretch)
    return [[min(edge[y][x], cap) / cap for x in range(T)] for y in range(T)]


def _mountain_top(seed: int) -> Canvas:
    """The rim's plateau seen from above (in 2.5D the top of an extruded block): broad,
    weathered red rock, softly undulating, with a few long cracks and a rare tuft of grass.
    Calm on purpose - on the diamond it is seen many times over."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    h = _rock_height(seed, 3, 1.0, 5.0)
    f = _mix((0.35, _emboss(h)), (0.3, h), (0.35, fbm(T, T, seed + 3, 2, 2)))
    _quantize(c, _varied(f, seed + 50, 0.5), "opqr", [12, 38, 38, 12], dither=0.1)
    for y in range(T):  # the cracks between slabs, broken up
        for x in range(T):
            if h[y][x] < 0.06 and bayer(x, y) < 0.75:
                c.px[y][x] = "n"
    if seed % 3 != 2:  # a tuft of grass in a crack, away from the borders
        low = sorted((h[y][x], x, y) for y in range(4, T - 4) for x in range(4, T - 4))
        x, y = low[rng.randrange(4)][1:]
        _stamp(c, x - 1, y - 1, [".e.", "34c", ".2."], wrap=False)
    return c


def _face_columns(seed: int, tones: str, weights: list[float], bands: float) -> Canvas:
    """A vertical rock wall, periodic sideways: fractured columns lit on their left flank,
    dark on the right, crossed by ``bands`` of strata, and darker toward the foot. The
    client stretches faces to the block's height, so the structure is mostly vertical."""
    c = Canvas(T, T)
    h = _rock_height(seed, 5, 0.35, 2.5)
    warp = fbm(T, 1, seed + 5, 2, 4)[0]
    lay = [[0.5 + 0.5 * math.sin(2 * math.pi * (bands * y / T + 0.35 * warp[x])) for x in range(T)]
           for y in range(T)]
    f = _mix((0.45, _emboss(h, 1, 0)), (0.2, h), (0.25, _emboss(lay, 0, 1)), (0.1, fbm(T, T, seed + 3, 1, 8)))
    f = [[v - 0.35 * (y / (T - 1)) ** 1.6 for v in row] for y, row in enumerate(f)]
    _quantize(c, f, tones, weights, dither=0.04)
    for y in range(T):
        for x in range(T):
            if h[y][x] < 0.14:
                c.px[y][x] = tones[0]  # the fissures between columns
    return c


def _lip(c: Canvas, seed: int, grass: bool) -> None:
    """Top edge of a wall: an earth-and-grass (or bare rock) lip, a sunlit rim of rock
    below it and a thin shadow line; periodic sideways. The foot is dark."""
    n = fbm(T, 1, seed, 2, 4)[0]
    for x in range(T):
        if grass:
            c.set(x, 0, FRINGE.px[0][x] if n[x] > 0.3 else "C")
            c.set(x, 1, "C" if n[(x + 4) % T] > 0.45 else "s")
            c.set(x, 2, "s" if n[(x + 7) % T] > 0.3 else "r")
        else:
            c.set(x, 0, "t" if n[x] > 0.55 else "s")
            c.set(x, 1, "s" if n[(x + 7) % T] > 0.35 else "r")
            c.set(x, 2, "r")
        c.set(x, 3, "n" if n[(x + 3) % T] > 0.5 else "o")
        c.set(x, T - 1, "m")
        if bayer(x, 0) < 0.5:
            c.set(x, T - 2, "m")


def _mountain_face(seed: int) -> Canvas:
    """The rim's wall: dark, deeply fissured red rock under a grassy lip - its lit crest
    against the plateau above reads as the ridge line."""
    c = _face_columns(seed, "mnopqr", [18, 24, 26, 19, 10, 3], 2.0)
    _lip(c, seed + 11, grass=True)
    return c


def _cliff_face(seed: int) -> Canvas:
    """Cliff at the land's edge: warmer sandstone columns with bolder strata, grass on top."""
    c = _face_columns(seed, "nopqrs", [16, 24, 26, 20, 11, 3], 3.0)
    _lip(c, seed + 11, grass=True)
    return c


def _mesa_face(seed: int) -> Canvas:
    """Mulgore's layered mesa wall: horizontal strata of uneven thickness in red, rust and
    pale sandstone (each ledge lit along its top, undercut below), a couple of long
    vertical joints, a bare-rock lip and a dark foot; periodic sideways."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    warp = fbm(T, 1, seed, 2, 4)[0]
    fine = fbm(T, T, seed + 1, 2, 8)
    bands = []
    y = 0.0
    tones = ["q", "p", "r", "o", "q", "p"]
    while y < T + 4:
        th = rng.choice((2, 3, 3, 4, 5))
        pale = rng.random() < 0.18
        bands.append((y, th, "E" if pale else rng.choice(tones)))
        y += th
    tone = {ch: i for i, ch in enumerate(ROCK_CH)}
    for y in range(T):
        for x in range(T):
            s_ = y + 1.4 * (warp[x] - 0.5)
            y0, th, ch = next(((b0, t_, ch_) for b0, t_, ch_ in bands if b0 <= s_ < b0 + t_), bands[-1])
            pos = s_ - y0
            if ch == "E":
                ch = "F" if pos < 0.9 else ("D" if pos >= th - 0.9 else "E")
            else:
                i = tone[ch]
                if pos < 0.9:
                    i += 1  # the ledge's lit top
                elif pos >= th - 0.9:
                    i -= 2  # undercut
                i += 1 if fine[y][x] > 0.82 else (-1 if fine[y][x] < 0.12 else 0)
                if y > 10 and bayer(x, y) < (y - 10) / 7:
                    i -= 1
                ch = ROCK_CH[max(0, min(7, i))]
            c.set(x, y, ch)
    for _k in range(2):  # long vertical joints, wobbling
        x = rng.randrange(T)
        y = rng.randrange(3, 7)
        for _j in range(rng.randrange(6, 11)):
            if y >= T - 1:
                break
            c.set(x % T, y, "m")
            if c.get((x - 1) % T, y) not in "m":
                c.set((x - 1) % T, y, "r" if bayer(x, y) < 0.5 else "q")
            y += 1
            x += rng.choice((0, 0, 0, 1, -1))
    _lip(c, seed + 11, grass=False)
    return c


# --- boulders ---------------------------------------------------------------------------------------


def _blob(c: Canvas, cx: float, cy: float, rx: float, ry: float, chars: str,
          light: tuple[float, float] = (-0.6, -0.8)) -> None:
    """A filled ellipse shaded as a rounded volume lit from the top-left."""
    n = len(chars)
    for y in range(c.h):
        for x in range(c.w):
            nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
            d = nx * nx + ny * ny
            if d > 1.0:
                continue
            v = 0.5 - 0.5 * (nx * light[0] + ny * light[1]) - 0.25 * d + (bayer(x, y) - 0.5) * 0.12
            c.set(x, y, chars[max(0, min(n - 1, int(v * n)))])


def _shadow(c: Canvas, cx: float, cy: float, rx: float, ry: float, ch: str = "z") -> None:
    for y in range(c.h):
        for x in range(c.w):
            nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
            if nx * nx + ny * ny <= 1.0 and c.px[y][x] == ".":
                c.px[y][x] = ch


def _outline(c: Canvas, skip: str = ".zy", ch: str = "k") -> None:
    """1px outline around every opaque pixel; shadow pixels (in ``skip``) may be outlined over."""
    src = [row[:] for row in c.px]
    for y in range(c.h):
        for x in range(c.w):
            if src[y][x] not in skip:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < c.w and 0 <= ny < c.h and src[ny][nx] not in skip:
                    c.px[y][x] = ch
                    break


def _boulders() -> None:
    specs = [
        [(7.8, 9.0, 6.2, 5.2)],
        [(9.3, 9.2, 5.6, 4.8), (3.8, 11.8, 2.8, 2.3)],
        [(8.0, 10.0, 6.6, 4.0)],
    ]
    for i, stones in enumerate(specs):
        rng = random.Random(900 + i)
        c = Canvas(T, T)
        _shadow(c, 8.5, 14.0, 7.0, 1.8)
        for cx, cy, rx, ry in stones:
            _blob(c, cx, cy, rx, ry, "nopqrst")
        if i == 2:  # a slab broken off a mesa: flat lit top, strata band on its face
            for x in range(T):
                for y in range(T):
                    if c.px[y][x] in ROCK_CH and y <= 7:
                        c.px[y][x] = "s" if y <= 6 else "r"
                    elif c.px[y][x] in ROCK_CH and y == 10:
                        c.px[y][x] = "o"
        # a crack across the stone
        cx, cy, rx, ry = stones[0]
        x, y = int(cx + rng.uniform(-1, 1)), int(cy - ry + 2)
        for _k in range(4):
            if c.get(x, y) in ROCK_CH:
                c.set(x, y, "n")
            x += rng.choice((0, 1))
            y += 1
        _outline(c)
        # grass tufts at the foot soften the contact with the ground
        for gx in (2, 13) if i != 1 else (13,):
            if c.get(gx, 13) in ".zy":
                c.set(gx, 13, "2")
                c.set(gx, 12, "4")
        register(f"az.boulder@{i}", art(c.grid(), legend=TER, note="red-brown boulder, blocks the way"))


# --- edge overlays ---------------------------------------------------------------------------------
# Each overlay paints the grass creeping in from ``side``. Its colours are an olive mix of
# green grass and straw, so it sits well against short, tall and dry grass alike.

CORNERS = ("ne", "nw", "se", "sw")
END = {"water": 4, "dirt": 3, "cliff": 3}      # fringe depth at the tile corners
SWING = {"water": 3.2, "dirt": 1.5, "cliff": 1.3}


def _side_xy(side: str, k: int, j: int) -> tuple[int, int]:
    """Pixel at position ``k`` along the edge, ``j`` px in from the ``side`` border."""
    return {"n": (k, j), "s": (k, T - 1 - j), "w": (j, k), "e": (T - 1 - j, k)}[side]


def _profile(kind: str, side: str) -> list[int]:
    """Fringe depth along one edge: a smooth periodic wobble (bays and points) that
    tapers to ``END`` at both corners, so sides and corners chain up."""
    wob = fbm(T, 1, 70 + "nsew".index(side) * 13 + len(kind), 2, 2)[0]
    out = []
    for k in range(T):
        taper = math.sin(math.pi * (k + 0.5) / T) ** 0.8
        out.append(max(1, round(END[kind] + SWING[kind] * 2 * (wob[k] - 0.5) * taper)))
    return out


def _mask(kind: str, where: str) -> set[tuple[int, int]]:
    if len(where) == 1:
        prof = _profile(kind, where)
        return {_side_xy(where, k, j) for k in range(T) for j in range(prof[k])}
    cx = T if "e" in where else 0
    cy = 0 if "n" in where else T
    r = END[kind] + 0.6
    return {(x, y) for y in range(T) for x in range(T) if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r}


def _fringe_tex() -> Canvas:
    """The grass mat of the overlays: green grass and straw mixed in soft clumps."""
    c = Canvas(T, T)
    f = _mix((0.5, fbm(T, T, 31, 2, 4)), (0.5, _emboss(_cushions(T, T, 31, 11, 2.2, 4.0, 1.35))))
    _quantize(c, f, "2c3d", [22, 28, 30, 20], dither=0.2)
    return c


FRINGE = _fringe_tex()


def _edge(kind: str, where: str, fr: int = 0) -> Canvas:
    g = _mask(kind, where)
    rng = random.Random(f"{kind}.{where}")
    c = Canvas(T, T)

    def grass(x, y):
        return (x, y) in g

    def inside(x, y):
        return 0 <= x < T and 0 <= y < T

    if kind == "dirt":
        return _dirt_edge(where, g, rng)
    for x, y in g:
        c.set(x, y, FRINGE.px[y][x])
    # the rim of the grass mat: lit where it faces up/left, in shade where it faces down/right
    for x, y in g:
        if inside(x, y + 1) and not grass(x, y + 1):
            c.set(x, y, "1" if bayer(x, y) < 0.6 else "b")
        elif inside(x + 1, y) and not grass(x + 1, y):
            c.set(x, y, "2")
        elif (inside(x, y - 1) and not grass(x, y - 1)) or (inside(x - 1, y) and not grass(x - 1, y)):
            c.set(x, y, "4" if bayer(x, y) < 0.5 else "e")
    # blades poking up out of the mat, into the open tile
    for x, y in sorted(g):
        if inside(x, y - 1) and not grass(x, y - 1) and rng.random() < 0.5:
            c.set(x, y - 1, "3" if rng.random() < 0.5 else "d")
            if rng.random() < 0.45 and inside(x, y - 2):
                c.set(x, y - 2, "4" if rng.random() < 0.5 else "e")

    solid = {(x, y) for y in range(T) for x in range(T) if c.px[y][x] != "."}
    if kind == "water":
        # land is higher than the lake: an earth bank under every south-facing grass rim
        bank = set()
        for x, y in g:
            if inside(x, y + 1) and not grass(x, y + 1):
                run = sum(1 for j in range(3) if grass(x, y - j) or y - j < 0)
                for j in range(1, 1 + min(2, run - 1) + 1):
                    if inside(x, y + j) and not grass(x, y + j):
                        c.set(x, y + j, "D" if j == 1 else "B")
                        bank.add((x, y + j))
        solid |= bank
        # the water's edge: foam washed up (frame 0), then wet and the wave pulling back (1)
        land = g | bank
        for y in range(T):
            for x in range(T):
                if (x, y) in solid:
                    continue
                near = any((x + dx, y + dy) in land for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)))
                near2 = any((x + dx, y + dy) in land for dx, dy in ((0, -2), (-2, 0), (2, 0), (0, 2)))
                t = bayer(x + fr * 2, y + fr)
                if near:
                    if fr == 0:
                        c.set(x, y, "M" if t < 0.15 else ("L" if t < 0.6 else "K"))
                    elif t < 0.7:
                        c.set(x, y, "K")
                elif near2:
                    if fr == 0 and t < 0.25:
                        c.set(x, y, "K")
                    elif fr == 1 and t < 0.5:
                        c.set(x, y, "M" if t < 0.12 else "L")
    else:  # cliff: roots and turf hang over the rock below a grass rim, and it casts a shadow
        for x, y in sorted(g):
            if inside(x, y + 1) and not grass(x, y + 1) and rng.random() < 0.4:
                for j in range(1, rng.randrange(2, 4)):
                    if inside(x, y + j) and (x, y + j) not in solid:
                        c.set(x, y + j, "B" if j > 1 else "1")
        occ = {(x, y) for y in range(T) for x in range(T) if c.px[y][x] != "."}
        for y in range(T):
            for x in range(T):
                if (x, y) in occ:
                    continue
                if (x, y - 1) in g or (x - 1, y) in g or ((x - 1, y - 1) in g and bayer(x, y) < 0.5):
                    c.set(x, y, "z")
    return c


def _dirt_edge(where: str, g: set[tuple[int, int]], rng: random.Random) -> Canvas:
    """Dirt and road already get the grass bled in softly by the client; this overlay only
    adds loose tussocks and blades straggling out along that edge (transparent between)."""
    c = Canvas(T, T)
    TUFTS = (["3.e", "232", "1.1"], [".4", "3d", "21"], ["e.3", "d2.", "1.."], ["4", "3", "1"])
    if len(where) == 1:
        spots = []
        for k in range(1, T - 1, 4):
            kk = k + rng.randrange(3)
            spots.append(_side_xy(where, kk, rng.randrange(3, 7)))
    else:
        cx = T - 3 if "e" in where else 1
        cy = 1 if "n" in where else T - 3
        spots = [(cx, cy), (cx + (-2 if "e" in where else 2), cy + (2 if "n" in where else -2))]
    for x, y in spots:
        tuft = rng.choice(TUFTS)
        x0 = max(0, min(T - len(tuft[0]), x - 1))
        y0 = max(0, min(T - len(tuft), y - 1))
        _stamp(c, x0, y0, tuft, wrap=False)
        for i in range(len(tuft[0])):  # a soft shadow at the foot, to the right
            if c.get(x0 + i + 1, y0 + len(tuft)) == "." and y0 + len(tuft) < T and x0 + i + 1 < T:
                c.set(x0 + i + 1, y0 + len(tuft), "y")
    # a sprinkle of single blades right at the border, where the bleed is thickest
    for x, y in sorted(g):
        if rng.random() < 0.08 and c.get(x, y) == "." and c.get(x, y - 1) == ".":
            c.set(x, y, "2")
            if y > 0:
                c.set(x, y - 1, "d" if rng.random() < 0.5 else "4")
    return c


def _edges() -> None:
    notes = {"water": "lake shore", "dirt": "grass straggling onto dirt", "cliff": "turf over the cliff"}
    for kind in ("water", "dirt", "cliff"):
        for where in (*"nsew", *CORNERS):
            name = f"az.edge.{kind}.{where}" if len(where) == 1 else f"az.edge.{kind}.corner.{where}"
            note = f"{notes[kind]}, grass to the {where}"
            if kind == "water":
                frames = [_edge(kind, where, fr).grid() for fr in range(2)]
                register(name, art(*frames, legend=TER, fps=1.5, note=note))
            else:
                register(name, art(_edge(kind, where).grid(), legend=TER, note=note))


# --- decorations: soft, no outline, a translucent contact shadow --------------------------------------

DECO = {
    "d": "azt_grass1", "g": "azt_grass2", "G": "azt_grass3", "h": "azt_grass4", "H": "azt_grass5",
    "r": "red1", "R": "red2", "p": "red3", "P": "red4",
    "y": "gold1", "Y": "gold2", "o": "gold3", "e": "tent1",
    "b": "water2", "B": "water3", "c": "water4", "C": "water5",
    "1": "azt_rock2", "2": "azt_rock3", "3": "azt_rock4", "4": "azt_rock5", "5": "azt_rock6", "6": "azt_rock7",
    "7": "bone1", "8": "bone2", "9": "bone3", "0": "bone4",
    "O": "azt_straw0", "a": "azt_straw1", "s": "azt_straw2", "S": "azt_straw3", "f": "azt_straw4",
    "F": "azt_straw5",
    "N": "azt_soil0", "A": "azt_soil1", "D": "azt_soil2", "E": "azt_soil3", "I": "azt_soil4",
    "t": "tent2", "T": "tent3", "u": "tent4",
    "z": "ink:60",
}

POPPY = [".pP.", "pRRr", ".Rr."]
DAISY = [".o.", "oeY", ".Y."]
LUPINE = [".C", "cB", "Bb", "cB", "Bb"]


def _g(*rows: str) -> tuple[str, ...]:
    """A 16x16 deco grid from its lowest rows: pads the top and the right with '.'."""
    body = [r.ljust(T, ".") for r in rows]
    assert all(len(r) == T for r in body), rows
    return tuple(["." * T] * (T - len(body)) + body)


def _leaves(c: Canvas, x: int, base: int) -> None:
    c.set(x - 1, base, "G")
    c.set(x + 1, base, "g")
    c.set(x - 1, base - 1, "h")


def _flowers(bloom: list[str], spots: list[tuple[int, int]], base: int = 13) -> Canvas:
    """A patch of flowers: each spot is a bloom's top-left; a stem runs down to the base row."""
    c = Canvas(T, T)
    xs = [x for x, _ in spots]
    _shadow(c, (min(xs) + max(xs)) / 2 + 2, base + 1.0, (max(xs) - min(xs)) / 2 + 3.5, 1.2)
    stem_dx = len(bloom[0]) // 2 - (1 if len(bloom[0]) % 2 == 0 else 0)
    for x, y in spots:
        sx = x + stem_dx
        for yy in range(y + len(bloom), base + 1):
            c.set(sx, yy, "g" if yy < base else "d")
        _leaves(c, sx, base)
    for x, y in spots:
        _stamp(c, x, y, bloom, wrap=False)
    return c


def _tuft(blades: list[tuple[int, int, int]], golden: bool) -> Canvas:
    """A clump of prairie grass: (base x, lean, height) blades, dark at the root, lit tips."""
    c = Canvas(T, T)
    xs = [b[0] for b in blades]
    _shadow(c, (min(xs) + max(xs)) / 2 + 1, 14.0, (max(xs) - min(xs)) / 2 + 2.5, 1.3)
    for x0, lean, h in blades:
        for j in range(h):
            x = x0 + round(lean * j / max(1, h - 1))
            y = 13 - j
            if j == 0:
                ch = "d"
            elif j < h - 2:
                ch = "g" if lean > 0 else "G"
            elif j < h - 1:
                ch = "G" if lean > 0 else "h"
            else:
                ch = ("f" if golden else "H") if lean <= 0 else ("S" if golden else "h")
            c.set(x, y, ch)
    return c


STONES = [
    _g("....455.........",   # three red pebbles
       "...45443........",
       "...4433221..54..",
       "...3332211.4432.",
       "....22111z.3321z",
       ".....zzzz..zzz..",
       "................"),
    _g("....45554.......",  # a flat slab and two chips
       "..454444333.....",
       ".43333322221....",
       ".z2211111111z.4.",
       "54.zzzzzzzzz.431",
       "321..........zz.",
       ".zz............."),
]
BONES = [
    _g("...........0....",   # a femur and a curve of ribs, bleached by the sun
       "..........0.8.0.",
       "..0.....0.9.8.9.",
       ".09000009.9.8.8.",
       ".98888888.8.7.7.",
       "..7.....7.......",
       "..zzzzzzz.zzzzz.",
       "................"),
    _g("...9........9...",   # a horned skull resting in the grass
       "...09......07...",
       "....098888907...",
       ".....099009.....",
       ".....907907.....",
       ".....09999......",
       "......8778......",
       "......0880.9....",
       "....zzzzzzz08...",
       "................",
       "................"),
]
DRY_BUSH = [
    _g("......f..F......",   # dead sagebrush: grey-gold twigs fanning from the root
       "...F..s.fS..f...",
       "....S.s.S..fS...",
       "..f.sSs.s.S.s.F.",
       "...SfsSsSsSsS.S.",
       "..FSsaSsasSaSs..",
       "...saSasasasas..",
       "....sa.aOa.as...",
       ".....a.OOa.a....",
       "......aOOOa.....",
       "....zzzzzzzz....",
       "................"),
    _g("......sSSf......",   # a tumbleweed caught in the grass
       "....sSf.FSSs....",
       "...sS.SfS.fSa...",
       "..sS.sa.SSs.Sa..",
       "..SfS.aSs.aS.s..",
       "..sa.SsaS.Ss.a..",
       "..as.a.sa.s.aO..",
       "...aOa.as.aOa...",
       "....aOaOaOa.....",
       "....zzzzzzzz....",
       "................"),
]
STUMPS = [
    _g("....DEEEED......",   # a sawn stump, rings on the cut face
       "...EuTTTTuE.....",
       "...ETtuutTD.....",
       "...DETTTTED.....",
       "...IEEDEDDA.....",
       "...IEEDEDNA.....",
       "..AIEEDDDNAA....",
       ".AD.IEDDA.DA....",
       "..zzzzzzzzzz....",
       "................",
       "................"),
    _g(".......u........",   # a trunk snapped off long ago, splintered top
       "......TI.u......",
       "....I.EIIT......",
       "....IEIEDE.I....",
       "....IEEDDNDE....",
       "....IEEDDNDN....",
       "....IEDEDDNN....",
       "....IEEDDDNN....",
       "...AIEDEDDNNA...",
       "..AIEEDDDNNNNA..",
       ".AN.zIEDDNzz.NA.",
       "..zzzzzzzzzzzz..",
       "................"),
]


def _decos() -> None:
    note = "scattered, walkable decoration"
    patches = {
        "flower_red": (POPPY, [[(2, 6), (7, 4), (10, 8)], [(4, 7), (9, 5)]]),
        "flower_yellow": (DAISY, [[(3, 7), (6, 4), (10, 6), (12, 9)], [(5, 8), (9, 6), (2, 9)]]),
        "flower_blue": (LUPINE, [[(4, 5), (7, 3), (10, 6)], [(6, 4), (10, 7)]]),
    }
    for name, (bloom, variants) in patches.items():
        for i, spots in enumerate(variants):
            register(f"az.deco.{name}@{i}", art(_flowers(bloom, spots).grid(), legend=DECO, note=note))
    tufts = [
        [(5, -1, 6), (6, 0, 8), (7, 1, 9), (8, 2, 7), (9, 3, 6), (10, 1, 5), (6, -2, 5)],
        [(4, -1, 5), (5, 0, 7), (6, 2, 6), (10, -1, 6), (11, 1, 8), (12, 2, 5)],
    ]
    for i, blades in enumerate(tufts):
        register(f"az.deco.tuft@{i}", art(_tuft(blades, golden=i == 1).grid(), legend=DECO, note=note))
    hand = {"stones": (STONES, "pebbles of red mesa stone"), "bones": (BONES, "bleached bones in the grass"),
            "dry_bush": (DRY_BUSH, "dead sagebrush, tumbleweed"), "stump": (STUMPS, "old tree stump")}
    for name, (grids, what) in hand.items():
        for i, g in enumerate(grids):
            register(f"az.deco.{name}@{i}", art(g, legend=DECO, note=what))


# --- plants and rocks: outlined objects that stand on the ground ------------------------------------

PL = {**TER,
      "u": "bone1", "v": "bone2", "x": "bone3", "Q": "bone4",          # bleached dead wood, thorns
      "g": "gold1", "h": "gold2", "j": "gold3",                        # yellow blooms
      "O": "red1", "R": "red2", "S": "red3", "T": "red4",              # red blooms, berries
      "i": "water3", "l": "water4", "P": "water5",                     # blue blooms
      "+": "spore4", "*": "flora4"}                                    # pink and violet


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


class _Sk:
    """A canvas that bends with the wind: ``bend(y)`` shifts every pixel drawn on row y."""

    def __init__(self, w: int, h: int, bend=None) -> None:
        self.c = Canvas(w, h)
        self.bend = bend or (lambda y: 0)

    def put(self, x: int, y: int, ch: str) -> None:
        self.c.set(int(x) + self.bend(int(y)), int(y), ch)

    def stroke(self, pts: list[tuple[int, int]], width: int = 1, ch: str = "@",
               thin_above: int | None = None) -> "_Sk":
        """Polyline ``width`` px wide (growing rightwards); above row ``thin_above`` 1 px."""
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            for x, y in _line(x0, y0, x1, y1):
                wd = 1 if thin_above is not None and y < thin_above else width
                for k in range(wd):
                    self.put(x + k, y, ch)
        return self

    def stamp(self, x: int, y: int, rows: list[str]) -> "_Sk":
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch != ".":
                    self.put(x + i, y + j, ch)
        return self

    def shade(self, light: str, mid: str, dark: str, marker: str = "@") -> "_Sk":
        """Stroke pixels: lit where open to the left, dark where open to the right."""
        src = [row[:] for row in self.c.px]
        for y in range(self.c.h):
            for x in range(self.c.w):
                if src[y][x] != marker:
                    continue
                left = src[y][x - 1] if x > 0 else "."
                right = src[y][x + 1] if x + 1 < self.c.w else "."
                self.c.px[y][x] = light if left != marker else (dark if right != marker else mid)
        return self

    def grid(self) -> tuple[str, ...]:
        return self.c.grid()


def _foliage(sk: _Sk, lobes: list[tuple[float, float, float, float]], seed: int, tones: str = "012345",
             hi: str = "d", clusters: float = 1.0) -> None:
    """A canopy of overlapping lobes (back to front). Each pixel is lit twice over: by the
    lobe it belongs to (a big rounded volume lit from the top-left) and by the leaf cluster
    it sits in (small domes, lit on their top-left too), so the crown reads as masses of
    leaves with dark gaps between them; the brightest tips catch the golden sun."""
    rng = random.Random(seed)
    c = sk.c
    x0 = min(cx - rx for cx, cy, rx, ry in lobes)
    x1 = max(cx + rx for cx, cy, rx, ry in lobes)
    y0 = min(cy - ry for cx, cy, rx, ry in lobes)
    y1 = max(cy + ry for cx, cy, rx, ry in lobes)
    n_cl = int((x1 - x0) * (y1 - y0) / 6 * clusters)
    cl = [(rng.uniform(x0, x1), rng.uniform(y0, y1), rng.uniform(1.6, 2.9)) for _ in range(n_cl)]
    n = len(tones)
    painted = set()
    for y in range(c.h):
        for x in range(c.w):
            hit = None
            for cx, cy, rx, ry in lobes:
                nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                if nx * nx + ny * ny <= 1.0:
                    hit = (nx, ny)
            if hit is None:
                continue
            nx, ny = hit
            d = nx * nx + ny * ny
            big = 0.58 - 0.42 * (nx * 0.6 + ny * 0.8) - 0.18 * d
            best = None
            for px, py, r in cl:
                dx, dy = (x + 0.5 - px) / r, (y + 0.5 - py) / r
                dd = dx * dx + dy * dy
                if dd < 1.0 and (best is None or dd < best[0]):
                    best = (dd, dx, dy)
            small = 0.2 if best is None else 0.55 - 0.45 * (best[1] * 0.6 + best[2] * 0.8) - 0.15 * best[0]
            v = 0.6 * big + 0.4 * small + (bayer(x, y) - 0.5) * 0.08
            ch = tones[max(0, min(n - 1, int(v * n)))]
            if hi and v > 0.9:
                ch = hi
            c.set(x + sk.bend(y), y, ch)
            painted.add((x + sk.bend(y), y))
    # a ragged rim: single leaves sticking out of the silhouette
    for x, y in sorted(painted):
        if rng.random() < 0.12:
            dx, dy = rng.choice(((0, -1), (-1, 0), (1, 0), (0, 1), (1, 1), (-1, 1)))
            if c.get(x + dx, y + dy) == ".":
                c.set(x + dx, y + dy, tones[3] if dy < 0 or dx < 0 else tones[1])


# --- trees ---

# (trunk and branch strokes [(points), width], canopy lobes back to front)
TREES = [
    # a flat-topped acacia, the classic lone tree of the plains
    ([([(15, 46), (15, 38), (14, 31)], 3), ([(14, 33), (10, 27), (6, 21)], 2), ([(16, 33), (20, 27), (24, 20)], 2),
      ([(15, 31), (16, 25), (16, 18)], 2), ([(10, 27), (5, 25)], 1), ([(20, 27), (26, 25)], 1)],
     [(7, 19, 6.5, 3.5), (25, 18, 6.5, 3.4), (11, 14, 6.5, 3.2), (21, 13, 7.5, 3.4), (16, 16, 8.5, 4.2),
      (15, 10, 6.5, 2.8)]),
    # a wide two-tiered acacia, leaning
    ([([(16, 46), (17, 39), (16, 31)], 3), ([(16, 34), (11, 29), (7, 25)], 2), ([(17, 32), (22, 27), (26, 23)], 2),
      ([(16, 31), (14, 22), (13, 15)], 2), ([(14, 24), (19, 17)], 1)],
     [(6, 25, 5.5, 2.8), (26, 23, 5, 2.7), (16, 23, 7, 3.2), (9, 16, 7, 3.4), (22, 14, 7.5, 3.6),
      (15, 11, 6.5, 3.2)]),
    # a broad round-crowned shade tree, dense
    ([([(14, 46), (14, 33)], 4), ([(15, 36), (9, 26)], 2), ([(16, 34), (22, 24)], 2), ([(15, 33), (16, 22)], 2)],
     [(8, 21, 6.5, 5.5), (24, 20, 6.5, 5.5), (16, 12, 9, 7), (9, 12, 5.5, 4.5), (22, 10, 6, 4.5),
      (16, 21, 9, 5.5), (12, 16, 6, 5), (21, 17, 6, 5)]),
    # a tall tree with two crowns, the trunk forking
    ([([(16, 46), (16, 38), (18, 30), (20, 23)], 3), ([(17, 35), (12, 27), (10, 19)], 2), ([(19, 28), (24, 25)], 1)],
     [(9, 20, 5.5, 4.2), (11, 14, 6.5, 5), (22, 22, 6.5, 4.5), (24, 16, 5.5, 4.2), (19, 10, 6.5, 5),
      (15, 17, 5, 4), (13, 8, 4.5, 3.2)]),
]


def _tree(i: int) -> _Sk:
    strokes, lobes = TREES[i]
    sk = _Sk(32, 48)
    sk.c.set(0, 0, ".")
    _shadow(sk.c, 16, 46.4, 9.5, 1.6, "y")
    for pts, w in strokes:
        sk.stroke(pts, w)
    x0, _ = strokes[0][0][0]
    sk.stroke([(x0 - 2, 46), (x0 - 1, 45)], 1).stroke([(x0 + strokes[0][1] + 1, 46), (x0 + strokes[0][1], 45)], 1)
    sk.shade("D", "C", "B")
    rng = random.Random(40 + i)
    for y in range(30, 47):  # bark: dark furrows running up the trunk
        for x in range(32):
            if sk.c.px[y][x] == "C" and rng.random() < 0.25:
                sk.c.px[y][x] = "B" if rng.random() < 0.7 else "E"
    _foliage(sk, lobes, 60 + i)
    # the canopy shades the trunk right below it
    for x in range(32):
        top = next((y for y in range(48) if sk.c.px[y][x] in GRASS_CH + "d"), None)
        if top is None:
            continue
        bottom = max(y for y in range(48) if sk.c.px[y][x] in GRASS_CH + "d")
        for y in range(bottom + 1, min(48, bottom + 3)):
            if sk.c.px[y][x] in "DCE":
                sk.c.px[y][x] = "B"
    _outline(sk.c)
    return sk


def _dead_tree(i: int) -> _Sk:
    """A gnarled dead tree: sun-bleached grey wood, twisted limbs, a dark knot hole."""
    sk = _Sk(24, 40)
    _shadow(sk.c, 12, 38.4, 7, 1.4, "y")
    shapes = [
        [([(11, 38), (11, 30), (10, 23), (11, 17)], 3), ([(11, 27), (7, 21), (5, 14), (3, 10)], 2),
         ([(12, 22), (16, 16), (18, 10), (20, 6)], 2), ([(11, 18), (11, 11), (9, 5)], 1), ([(5, 14), (8, 10)], 1),
         ([(18, 10), (15, 7)], 1), ([(7, 21), (3, 19)], 1)],
        [([(12, 38), (13, 31), (11, 25), (12, 20)], 3), ([(12, 26), (17, 22), (21, 15)], 2),
         ([(12, 21), (8, 15), (6, 8)], 2), ([(13, 21), (14, 12), (13, 6)], 1), ([(17, 22), (21, 22)], 1),
         ([(8, 15), (4, 13)], 1), ([(21, 15), (21, 11)], 1)],
        # a broken snag: one stub arm, the top snapped off
        [([(11, 38), (11, 24), (12, 16)], 4), ([(12, 26), (17, 21), (19, 17)], 2), ([(11, 22), (7, 18)], 1),
         ([(12, 16), (12, 13)], 2)],
    ]
    for pts, w in shapes[i]:
        sk.stroke(pts, w, thin_above=12 if w > 1 else None)
    sk.stroke([(8, 38), (10, 36)], 1).stroke([(15, 38), (14, 36)], 1)
    sk.shade("x", "v", "u")
    rng = random.Random(80 + i)
    for y in range(40):  # cracks along the grain
        for x in range(24):
            if sk.c.px[y][x] == "v" and rng.random() < 0.18:
                sk.c.px[y][x] = "u"
    kx, ky = (11, 28) if i != 2 else (12, 21)
    sk.stamp(kx, ky, ["A", "B"])  # knot hole
    if i == 2:  # splintered top
        sk.stamp(11, 11, ["Q.x", "xvx"])
    _outline(sk.c)
    return sk


# --- bushes ---

BUSHES = [
    [(5, 10, 4, 3.4), (11, 10, 4, 3.4), (8, 7, 4.5, 3.8), (8, 11, 5.5, 2.6)],
    [(4, 11, 3.5, 2.8), (12, 11, 3.5, 2.8), (6, 8, 3.8, 3.2), (11, 7, 3.5, 3.2), (8, 11, 5, 2.6)],
    [(5, 10, 4.2, 3.6), (11, 9, 4.2, 3.8), (8, 12, 5.5, 2.4)],
    [(4, 11, 3.2, 2.6), (8, 9, 4.2, 4), (12, 11, 3.4, 2.8), (8, 12, 5.2, 2.2)],
]


def _bush(i: int) -> _Sk:
    sk = _Sk(16, 16)
    _shadow(sk.c, 8.5, 14.2, 7, 1.5, "y")
    sk.stroke([(7, 14), (7, 11)], 1).stroke([(9, 14), (10, 11)], 1).shade("C", "C", "B")
    _foliage(sk, BUSHES[i], 120 + i, tones="012345" if i != 1 else "01234", clusters=1.4)
    rng = random.Random(130 + i)
    spots = [(x, y) for y in range(16) for x in range(16) if sk.c.px[y][x] in "234"]
    rng.shuffle(spots)
    if i == 2:  # red berries: a lit dot over a darker one
        for x, y in spots[:5]:
            sk.c.set(x, y, "S")
            if sk.c.get(x, y + 1) in GRASS_CH:
                sk.c.set(x, y + 1, "R")
    elif i == 3:  # small yellow blossoms
        for x, y in spots[:6]:
            sk.c.set(x, y, "j" if rng.random() < 0.5 else "h")
    _outline(sk.c)
    return sk


def _thornbush(i: int) -> _Sk:
    """A quilboar briar: a tangle of dark red-brown canes set with pale thorns, a few leaves."""
    rng = random.Random(150 + i)
    sk = _Sk(16, 16)
    _shadow(sk.c, 8.5, 14.2, 7, 1.5, "y")
    for _k in range(6 + i):  # canes arching out of the root: up to a crest, then drooping
        side = rng.choice((-1, 1))
        reach = rng.uniform(2.5, 7.0)
        crest = rng.uniform(5.0, 11.0) - reach * 0.3
        bx = 8 + rng.choice((-1, 0, 0, 1))
        pts = [(bx, 14), (int(round(bx + side * reach * 0.35)), int(round(14 - crest))),
               (int(round(bx + side * reach * 0.8)), int(round(14 - crest * 0.85))),
               (int(round(bx + side * reach)), int(round(14 - crest * 0.45)))]
        sk.stroke(pts, 1)
    sk.shade("E", "D", "B")
    cane = [(x, y) for y in range(16) for x in range(16) if sk.c.px[y][x] in "EDB"]
    rng.shuffle(cane)
    for x, y in cane[:12]:  # thorns: a pale point beside a cane
        dx, dy = rng.choice(((1, -1), (-1, -1), (1, 0), (-1, 0)))
        if sk.c.get(x + dx, y + dy) == ".":
            sk.c.set(x + dx, y + dy, "Q" if dy < 0 else "x")
    for x, y in cane[12:16]:
        sk.c.set(x, y, "1" if rng.random() < 0.5 else "2")
    if i == 1:
        for x, y in cane[16:19]:
            sk.c.set(x, y, "R")
    _outline(sk.c)
    return sk


# --- grasses, flowers, reeds (they sway: two frames) ---

CLUMPS = [
    [(4, 2, 9), (5, 4, 5), (6, 6, 2), (7, 7, 4), (8, 9, 3), (9, 11, 6), (10, 12, 9), (6, 3, 11), (8, 8, 1)],
    [(3, 1, 8), (5, 4, 4), (7, 6, 3), (8, 8, 6), (10, 12, 5), (11, 13, 9), (7, 5, 1), (9, 10, 2)],
    [(5, 3, 7), (6, 5, 3), (7, 7, 2), (8, 9, 4), (9, 11, 8), (7, 6, 0), (10, 13, 10)],
    [(3, 2, 9), (5, 3, 5), (6, 6, 3), (8, 8, 2), (9, 10, 5), (11, 13, 8), (7, 4, 1)],
]


def _grass_clump(i: int, fr: int) -> _Sk:
    """Tall prairie grass: long blades fanning from a dark base, seed heads on top; the
    fourth clump is sun-dried straw."""
    sk = _Sk(16, 16, (lambda y: 1 if y < 6 else 0) if fr else None)
    _shadow(sk.c, 8, 14.3, 5.5, 1.3, "y")
    dry = i == 3
    for k, (bx, tx, ty) in enumerate(CLUMPS[i]):
        pts = list(_line(bx + 2, 14, tx + 1, ty + 1))
        for j, (x, y) in enumerate(pts):
            t = j / max(1, len(pts) - 1)
            if dry:
                ch = "b" if t < 0.3 else ("c" if t < 0.75 else "d")
            else:
                ch = "1" if t < 0.25 else ("2" if t < 0.55 else ("3" if t < 0.85 else "4"))
            if tx + 1 < bx + 2 and t > 0.4:  # blades leaning left face the light
                ch = {"2": "3", "3": "4", "c": "d"}.get(ch, ch)
            sk.put(x, y, ch)
        if k % 3 == 0:  # a seed head
            sk.put(tx + 1, ty, "d" if not dry else "e")
            sk.put(tx + 1, ty - 1, "e" if not dry else "f")
    _outline(sk.c)
    return sk


FLOWER_SCHEMES = [  # light petal, mid, dark, centre
    ("T", "S", "R", "h"),   # red prairie poppies
    ("j", "h", "g", "E"),   # yellow
    ("P", "l", "i", "w"),   # blue
    ("w", "+", "*", "h"),   # white and pink
]
FLOWER_SPOTS = [(3, 5), (7, 3), (11, 6), (5, 8), (10, 9)]


def _wildflowers(i: int, fr: int) -> _Sk:
    lp, mp, dp, cp = FLOWER_SCHEMES[i]
    sk = _Sk(16, 16, (lambda y: 1 if y < 8 else 0) if fr else None)
    _shadow(sk.c, 8, 14.3, 6.5, 1.3, "y")
    for x, y in FLOWER_SPOTS:  # stems
        sk.stroke([(x + 1, 14), (x + 1, y + 2)], 1, ch="2")
    for x0, pts in ((3, [(3, 14), (1, 11)]), (8, [(8, 14), (6, 10)]), (12, [(12, 14), (14, 11)]), (9, [(9, 14), (11, 11)])):
        sk.stroke(pts, 1, ch="3")  # leaves
        sk.put(pts[-1][0], pts[-1][1], "4")
    sk.stamp(2, 12, ["1231321331"])  # a leafy base
    sk.stamp(5, 13, ["12211"])
    for x, y in FLOWER_SPOTS:
        sk.stamp(x, y, ["." + lp + ".", lp + cp + mp, "." + dp + "."])
    _outline(sk.c)
    return sk


def _reeds(i: int, fr: int) -> _Sk:
    """Cattails at the lake shore: straight stems, brown velvet heads, arching leaves."""
    rng = random.Random(170 + i)
    sk = _Sk(16, 24, (lambda y: 1 if y < 10 else 0) if fr else None)
    _shadow(sk.c, 8, 22.3, 6, 1.3, "y")
    stems = [(5, 4 + i), (8, 2), (11, 6 - i)][: 2 + (i != 1)] + ([(3, 9)] if i == 2 else [])
    for x, top in stems:
        sk.stroke([(x, 22), (x, top + 5)], 1, ch="2")
        sk.put(x, top, "3")  # the spike above the head
        sk.stamp(x - 1 + 1, top + 1, ["E", "D", "D", "C"])
        sk.stamp(x - 1, top + 1, ["D", "C", "C", "B"])
    for k in range(4):  # leaves arching out
        bx = 4 + k * 2 + rng.randrange(2)
        tx = bx + rng.choice((-4, -3, 3, 4))
        ty = rng.randrange(9, 14)
        pts = list(_line(bx, 22, tx, ty))
        for j, (x, y) in enumerate(pts):
            t = j / max(1, len(pts) - 1)
            sk.put(x, y, "1" if t < 0.3 else ("2" if t < 0.6 else ("3" if tx < bx else "2")))
        sk.put(tx, ty - 1, "4" if tx < bx else "3")
    _outline(sk.c)
    return sk


# --- rocks ---


def _layered(c: Canvas, mask: set[tuple[int, int]], seed: int, cx_of, hw_of, band: float = 3.4,
             pale: bool = True) -> None:
    """Shade a rock silhouette as Mulgore sandstone: lit on the left, dark on the right,
    stacked strata (lit ledge, undercut), some pale bands, vertical joints."""
    warp = fbm(64, 1, seed, 2, 4)[0]
    fine = fbm(64, 64, seed + 1, 1, 8)
    pal = random.Random(seed).sample(range(12), 2) if pale else []
    for x, y in mask:
        hw = max(1.0, hw_of(y))
        nx = (x + 0.5 - cx_of(y)) / hw
        v = 0.5 - 0.36 * nx
        s_ = y + 1.4 * (warp[x % 64] - 0.5)
        b = int(s_ // band)
        pos = s_ - b * band
        if pos < 0.9:
            v += 0.14
        elif pos > band - 1.0:
            v -= 0.22
        v += 0.08 if fine[y % 64][x % 64] > 0.75 else 0.0
        if b % 12 in pal:
            ch = "F" if v > 0.62 else ("E" if v > 0.36 else "D")
        else:
            ch = ROCK_CH[max(1, min(7, int(v * 7.2)))]
        c.set(x, y, ch)


def _spire(i: int) -> Canvas:
    """A tall red-rock spire: a hoodoo of stacked strata under a wider caprock."""
    specs = [  # height, cap half-width, neck, base half-width, lean, grass on top
        (46, 4.5, 3.2, 9.0, 1.0, True),
        (40, 3.5, 2.6, 8.0, -1.2, False),
        (44, 5.0, 3.6, 10.0, 0.0, True),
        (32, 5.5, 4.0, 9.5, 0.6, False),
    ]
    height, cap, neck, base, lean, grassy = specs[i]
    rng = random.Random(200 + i)
    W, H = 24, 48
    c = Canvas(W, H)
    y_top = H - 1 - height
    wob = fbm(H, 1, 210 + i, 2, 6)[0]

    def t_of(y):
        return (y - y_top) / height

    steps = [rng.uniform(-0.9, 0.9) for _ in range(20)]

    def hw_of(y):
        t = t_of(y)
        if t < 0.14:
            w = cap - (0.8 if t < 0.03 else 0)
        else:
            w = neck + (base - neck) * max(0.0, (t - 0.18) / 0.82) ** 1.7
            w += steps[int((y - y_top) // 4) % 20]  # ledges: each stratum juts or recedes
        return w + 2.0 * (wob[y] - 0.5)

    def cx_of(y):
        return 11.5 + lean * (1 - t_of(y)) * 2

    mask = {(x, y) for y in range(y_top, H - 1) for x in range(W) if abs(x + 0.5 - cx_of(y)) <= hw_of(y)}
    _shadow(c, 12, H - 1.6, base + 2, 1.6, "y")
    _layered(c, mask, 220 + i, cx_of, hw_of)
    for y in range(y_top, y_top + 2):  # the sunlit caprock top
        for x in range(W):
            if (x, y) in mask:
                c.set(x, y, "t" if y == y_top else "s")
    cap_bottom = y_top + int(height * 0.14)
    for x in range(W):  # the caprock's shadow on the neck
        if (x, cap_bottom + 1) in mask:
            c.set(x, cap_bottom + 1, "m" if bayer(x, 0) < 0.6 else "n")
    for _k in range(2):  # vertical joints
        y = rng.randrange(y_top + 8, H - 10)
        x = int(cx_of(y) + rng.uniform(-2, 2))
        for j in range(rng.randrange(4, 8)):
            if (x, y + j) in mask:
                c.set(x, y + j, "n")
    if grassy:
        cx = int(cx_of(y_top))
        c.set(cx - 1, y_top - 1, "3")
        c.set(cx, y_top - 1, "2")
        c.set(cx - 1, y_top - 2, "4")
        c.set(cx + 2, y_top - 1, "e")
    for bx, by, r in ((cx_of(H - 3) - base - 1, H - 3, 1.6), (cx_of(H - 3) + base + 0.5, H - 3, 1.8)):  # rubble
        _blob(c, bx, by, r * 1.2, r, "opqr")
    _outline(c)
    return c


def _chisel(c: Canvas, mask: set[tuple[int, int]], seed: int, n: int, tones: str = "nopqrst") -> None:
    """Shade a rock silhouette as broken planes: Voronoi facets, each a flat plane whose tone
    comes from where it faces (upper-left facets lit), a lit edge along its top-left
    border and a dark crack along its bottom-right one."""
    rng = random.Random(seed)
    xs = [x for x, _ in mask]
    ys = [y for _, y in mask]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = max(1, (x1 - x0) / 2), max(1, (y1 - y0) / 2)
    pts = [(rng.uniform(x0, x1), rng.uniform(y0, y1)) for _ in range(n)]
    tilt = [rng.uniform(-0.12, 0.12) for _ in range(n)]
    own = {}
    for x, y in mask:
        own[(x, y)] = min(range(n), key=lambda i: (x + 0.5 - pts[i][0]) ** 2 + (y + 0.5 - pts[i][1]) ** 2)
    k = len(tones)
    for (x, y), i in own.items():
        px, py = pts[i]
        fx, fy = (px - cx) / rx, (py - cy) / ry
        v = 0.55 - 0.3 * (fx * 0.6 + fy * 0.8) + tilt[i]
        v += -0.12 * ((x - px) * 0.6 + (y - py) * 0.8) / max(rx, ry)  # a gentle roll across the plane
        right, below = own.get((x + 1, y)), own.get((x, y + 1))
        left, above = own.get((x - 1, y)), own.get((x, y - 1))
        if (right is not None and right != i) or (below is not None and below != i):
            v -= 0.3
        elif (left is not None and left != i) or (above is not None and above != i):
            v += 0.16
        if (x, y + 1) not in mask or (x + 1, y) not in mask:
            v -= 0.12  # the silhouette's shadow side
        if (x, y - 1) not in mask:
            v += 0.12  # its sunlit top rim
        c.set(x, y, tones[max(0, min(k - 1, int(v * k)))])


def _boulder_big(i: int) -> Canvas:
    specs = [
        (32, 26, [(15.5, 14.5, 11.5, 9.5), (8, 18, 6, 5)], 9),
        (30, 24, [(12, 14, 9, 8.5), (21, 16, 7.5, 6.5)], 8),
        (32, 22, [(16, 12.5, 13, 8)], 7),
    ]
    w, h, lobes, facets = specs[i]
    rng = random.Random(300 + i)
    c = Canvas(w, h)
    _shadow(c, w / 2 + 1, h - 1.8, w / 2 - 1, 1.8, "y")
    rock = set()
    for cx, cy, rx, ry in lobes:
        rock |= {(x, y) for y in range(h) for x in range(w) if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1}
    if i == 2:  # a squared-off mesa block
        rock = {(x, y) for x, y in rock if y >= 5}
    _chisel(c, rock, 310 + i, facets)
    if i == 2:  # flat lit top and strata on its face
        for x, y in rock:
            if y < 9:
                c.set(x, y, "s" if y < 7 else "r")
            elif (y - 10) % 4 == 0 and c.px[y][x] not in "mn":
                c.set(x, y, "o")
    for _k in range(4):  # pale lichen on the lit side
        x, y = rng.choice(sorted(p for p in rock if c.px[p[1]][p[0]] in "rs"))
        c.set(x, y, "c")
    _outline(c)
    for gx in (3, w - 5):  # grass at the foot
        c.set(gx, h - 3, "2")
        c.set(gx, h - 4, "4")
        c.set(gx + 1, h - 3, "3")
    return c


def _slab(i: int) -> Canvas:
    """A low rock outcrop: a flat sunlit top surface and a short layered front face."""
    rx, ry, face = [(10.5, 3.6, 4), (9.0, 3.0, 5), (10.8, 2.6, 3)][i]
    c = Canvas(24, 16)
    cx, cy = 12, 8.5 - face / 2
    _shadow(c, 12.5, 14.5, 11, 1.4, "y")
    top = {(x, y) for y in range(16) for x in range(24) if ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2 <= 1}
    front = set()
    for x in range(24):
        ys = [y for (xx, y) in top if xx == x]
        if ys:
            for y in range(max(ys) + 1, max(ys) + 1 + face):
                front.add((x, y))
    fine = fbm(24, 16, 330 + i, 1, 4)
    for x, y in front:
        nx = (x + 0.5 - cx) / rx
        v = 0.5 - 0.3 * nx - 0.05 * (y - cy - ry)
        ch = ROCK_CH[max(0, min(6, int(v * 6)))]
        if (y - int(cy + ry)) % 3 == 0:
            ch = ROCK_CH[max(0, ROCK_CH.index(ch) - 1)]
        c.set(x, y, ch)
    for x, y in top:
        nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
        v = 0.6 - 0.25 * nx - 0.25 * ny + (fine[y][x] - 0.5) * 0.3
        c.set(x, y, "qrrs"[max(0, min(3, int(v * 4)))])
    for x in range(24):  # the rim where top meets face catches the light
        ys = [y for (xx, y) in top if xx == x]
        if ys and x < cx + rx * 0.4:
            c.set(x, max(ys), "t")
    rng = random.Random(340 + i)
    x, y = rng.randrange(6, 16), int(cy)
    for _k in range(4):  # a crack across the top
        if (x, y) in top:
            c.set(x, y, "p")
        x += 1
        y += rng.choice((-1, 0, 1))
    _outline(c)
    return c


def _arch() -> Canvas:
    """A small natural arch of layered sandstone, lit on the left, dark inside the opening."""
    W, H = 32, 32
    c = Canvas(W, H)
    _shadow(c, 16, H - 1.8, 14, 1.8, "y")
    mask = set()
    for y in range(H - 2):
        for x in range(W):
            dx = (x + 0.5 - 16) / 14.5
            outer = y >= 5 + 7 * dx * dx and abs(dx) <= 1.0 - 0.02 * max(0, 26 - y)
            hole = ((x + 0.5 - 16.5) / 7.5) ** 2 + ((y + 0.5 - 30) / 16) ** 2 <= 1
            if outer and not hole:
                mask.add((x, y))
    _layered(c, mask, 350, lambda y: 16.0, lambda y: 14.5, band=3.2)
    for x, y in mask:  # inside the opening the rock turns away from the light
        hole_d = ((x + 0.5 - 16.5) / 8.5) ** 2 + ((y + 0.5 - 30) / 17) ** 2
        if hole_d <= 1.15:
            c.set(x, y, "n" if x < 17 else "o")
        elif hole_d <= 1.35 and x >= 16:
            c.set(x, y, "m")
    for x in range(W):  # sunlit top of the span
        ys = [y for (xx, y) in mask if xx == x]
        if ys and x < 22:
            c.set(x, min(ys), "t")
    _outline(c)
    for gx in (5, 26):
        c.set(gx, H - 3, "2")
        c.set(gx, H - 4, "4")
    return c


def _plants_rocks() -> None:
    for i in range(4):
        register(f"az.mesa.face@{i}", art(_mesa_face(850 + i).grid(), legend=TER, note="layered red mesa wall"))
    notes = ["flat-topped acacia", "wide two-tiered acacia", "broad shade tree", "tall forked tree"]
    for i in range(4):
        register(f"az.plant.tree@{i}", art(_tree(i).grid(), legend=PL, note=notes[i]))
    for i in range(3):
        register(f"az.plant.dead_tree@{i}", art(_dead_tree(i).grid(), legend=PL, note="gnarled dead tree"))
    for i in range(4):
        register(f"az.plant.bush@{i}", art(_bush(i).grid(), legend=PL, note="green scrub bush"))
    for i in range(3):
        register(f"az.plant.thornbush@{i}", art(_thornbush(i).grid(), legend=PL, note="quilboar briar"))
    for i in range(4):
        register(f"az.plant.grass_clump@{i}", art(*[_grass_clump(i, f).grid() for f in range(2)], legend=PL,
                                                  fps=1.5, note="tall grass clump, sways"))
        register(f"az.plant.wildflowers@{i}", art(*[_wildflowers(i, f).grid() for f in range(2)], legend=PL,
                                                  fps=1.2, note="wildflowers, sway"))
    for i in range(3):
        register(f"az.plant.reeds@{i}", art(*[_reeds(i, f).grid() for f in range(2)], legend=PL, fps=1.3,
                                            note="cattails at the shore, sway"))
    for i in range(4):
        register(f"az.rock.spire@{i}", art(_spire(i).grid(), legend=PL, note="red-rock spire"))
    for i in range(3):
        register(f"az.rock.boulder_big@{i}", art(_boulder_big(i).grid(), legend=PL, note="big boulder"))
        register(f"az.rock.slab@{i}", art(_slab(i).grid(), legend=PL, note="flat rock outcrop"))
    register("az.rock.arch_small", art(_arch().grid(), legend=PL, note="small natural rock arch"))


# --- register ---------------------------------------------------------------------------------------


def _ground() -> None:
    for i in range(4):
        register(f"az.ground.grass@{i}", art(_grass(100 + i).grid(), legend=TER, note="short prairie grass"))
        register(f"az.ground.tall_grass@{i}", art(_tall_grass(200 + i).grid(), legend=TER,
                                                  note="tall golden-green grass"))
        register(f"az.ground.dry_grass@{i}", art(_dry_grass(300 + i).grid(), legend=TER, note="yellowed dry grass"))
    for i in range(3):
        register(f"az.ground.dirt@{i}", art(_dirt(400 + i).grid(), legend=TER, note="bare earth"))
        register(f"az.ground.road@{i}", art(_road(450 + i).grid(), legend=TER, note="packed dirt road"))
        register(f"az.ground.mesa@{i}", art(_mesa(500 + i).grid(), legend=TER, note="red rock plateau"))
    for i in range(2):
        register(f"az.ground.water@{i}", art(*_lake_frames(600 + i * 17), legend=TER, fps=3,
                                             note="Stonebull Lake water"))
        register(f"az.ground.shallows@{i}", art(*_shallows_frames(650 + i * 17), legend=TER, fps=3,
                                                note="clear shallows over sand"))
    for i in range(3):
        register(f"az.mountain.top@{i}", art(_mountain_top(700 + i).grid(), legend=TER, note="mountain wall, top"))
        register(f"az.mountain.face@{i}", art(_mountain_face(750 + i).grid(), legend=TER,
                                              note="mountain wall, south face"))
        register(f"az.cliff.face@{i}", art(_cliff_face(800 + i).grid(), legend=TER, note="layered sandstone cliff"))


_ground()
_boulders()
_edges()
_decos()
_plants_rocks()
