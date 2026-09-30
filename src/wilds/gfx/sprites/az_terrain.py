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
_ramp("azt_shoal", "#1d4a5c", "#2b6772", "#428882", "#63a792", "#90c4a5", "#c8e3c2")  # shallows over sand


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


def _wrapped(c: Canvas, x: int, y: int) -> str:
    return c.px[y % c.h][x % c.w]


# --- grass ---------------------------------------------------------------------------------------


def _grass(seed: int) -> Canvas:
    """Short prairie grass: soft clumps lit from the top-left, little blade flecks and a few
    golden seed heads - the warm yellow-green of Mulgore."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    hump = _cushions(T, T, seed, 11, 2.2, 4.2, squash=1.35)
    fine = fbm(T, T, seed + 7, 2, 4)
    f = _mix((0.5, _emboss(hump)), (0.25, hump), (0.25, fine))
    _quantize(c, f, "1234", [9, 40, 41, 10], dither=0.08)
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
    _quantize(c, f, "0123", [8, 42, 40, 10], dither=0.1)
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
    """Dry grass: yellowed straw lying in swathes, with a green blade or bare earth here and there."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    warp = fbm(T, T, seed, 2, 2)
    # combed straw: diagonal strands warped by noise (periodic: 2 strands per tile per axis)
    comb = [[0.5 + 0.5 * math.sin(2 * math.pi * ((x + y) / T * 2 + 1.2 * warp[y][x])) for x in range(T)]
            for y in range(T)]
    f = _mix((0.35, _emboss(comb, 1, 1)), (0.35, fbm(T, T, seed + 3, 2, 4)), (0.3, fbm(T, T, seed + 5, 1, 8)))
    _quantize(c, f, "bcde", [10, 40, 40, 10], dither=0.1)
    for _ in range(4):  # straw blades
        x, y = rng.randrange(T), rng.randrange(T)
        c.set(x, y, "b")
        c.set(x, (y - 1) % T, "e")
    for _ in range(2):  # a green blade still alive
        x, y = rng.randrange(1, T - 1), rng.randrange(2, T - 1)
        c.set(x, y, "2")
        c.set(x, y - 1, "3")
    for _ in range(2):  # bare soil peeking through
        x, y = rng.randrange(1, T - 2), rng.randrange(1, T - 1)
        c.set(x, y, "C")
        c.set(x + 1, y, "B")
    return c


# --- earth -----------------------------------------------------------------------------------------


def _dirt(seed: int) -> Canvas:
    rng = random.Random(seed)
    c = Canvas(T, T)
    clods = _cushions(T, T, seed, 9, 2.5, 4.5, squash=1.2)
    f = _mix((0.45, _emboss(clods)), (0.2, clods), (0.35, fbm(T, T, seed + 3, 2, 8)))
    _quantize(c, f, "BCDE", [8, 40, 42, 10], dither=0.1)
    for _ in range(3):  # pebbles: a lit top over a shadow, away from the edges
        x, y = rng.randrange(2, T - 2), rng.randrange(2, T - 2)
        c.set(x, y, "F")
        c.set(x, y + 1, "B")
    for _ in range(2):  # dark grains
        c.set(rng.randrange(T), rng.randrange(T), "B")
    return c


def _road(seed: int) -> Canvas:
    """Packed pale dirt: the same earth as ``dirt`` one step lighter and smoother."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    f = _mix((0.3, _emboss(fbm(T, T, seed, 2, 4))), (0.4, fbm(T, T, seed + 1, 2, 4)),
             (0.3, fbm(T, T, seed + 2, 1, 8)))
    _quantize(c, f, "CDEF", [6, 34, 48, 12], dither=0.12)
    for _ in range(2):  # hoof-worn dimples and a pale grain
        x, y = rng.randrange(2, T - 2), rng.randrange(2, T - 2)
        c.set(x, y, "C")
        c.set(x + 1, y, "D")
    for _ in range(3):
        c.set(rng.randrange(T), rng.randrange(T), "G")
    return c


def _mesa(seed: int) -> Canvas:
    """Red-brown rock plateau: broad flat slabs, cracks between them, dust in the cracks."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    slabs = _cushions(T, T, seed, 6, 4.0, 6.5, squash=1.1)
    f = _mix((0.45, _emboss(slabs)), (0.35, slabs), (0.2, fbm(T, T, seed, 2, 4)))
    _quantize(c, f, "pqrs", [10, 38, 42, 10], dither=0.06)
    for _ in range(2):  # hairline cracks
        x, y = rng.randrange(T), rng.randrange(T)
        for _k in range(5):
            c.set(x % T, y % T, "o")
            x += rng.choice((1, 1, 0))
            y += rng.choice((-1, 0, 1, 1))
    for _ in range(3):  # dust
        c.set(rng.randrange(T), rng.randrange(T), "E")
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
    """Clear water over a rippled sand bottom; a net of caustic light drifts over it.
    Caustics are picked by rank, so every frame has the same amount of light."""
    base = Canvas(T, T)
    warp = fbm(T, T, seed, 2, 2)
    rip = [[0.5 + 0.5 * math.sin(2 * math.pi * (2 * y / T + 0.9 * warp[y][x] + 0.12 * math.sin(
        2 * math.pi * x / T))) for x in range(T)] for y in range(T)]
    f = _mix((0.5, _emboss(rip, 0, 1)), (0.25, fbm(T, T, seed + 1, 2, 4)), (0.25, rip))
    _quantize(base, f, "KUVW", [16, 34, 38, 12], dither=0.1)
    n1, n2 = fbm(T, T, seed + 2, 2, 2), fbm(T, T, seed + 3, 2, 2)
    frames = []
    for fr in range(4):
        ph = fr / 4
        caust = [[max(1 - abs(math.sin(2 * math.pi * (n1[y][x] * 1.5 + ph))),
                      1 - abs(math.sin(2 * math.pi * (n2[y][x] * 1.5 - ph)))) for x in range(T)] for y in range(T)]
        ranked = sorted(((caust[y][x], x, y) for y in range(T) for x in range(T)), reverse=True)
        c = base.copy()
        for i, (_v, x, y) in enumerate(ranked[:18]):
            c.set(x, y, "Z" if i < 4 else "Y")
        frames.append(c.grid())
    return frames


# --- walls: mountain and cliff ------------------------------------------------------------------------


def _lip(c: Canvas, seed: int) -> None:
    """The wall's broken top edge: a lit rim 1-2 px thick and a shadow line under it
    (thickness from periodic 1D noise, so the lip runs on seamlessly sideways)."""
    lip = fbm(T, 1, seed, 2, 4)[0]
    for x in range(T):
        thick = 2 if lip[x] > 0.45 else 1
        c.set(x, 0, "q" if lip[(x + 5) % T] < 0.6 else "r")
        if thick == 2:
            c.set(x, 1, "s" if lip[(x + 9) % T] > 0.7 else "r")
        c.set(x, thick, "n" if lip[(x + 3) % T] < 0.7 else "o")


def _facets(seed: int, n: int, stretch: float) -> tuple[list[list[int]], list[list[float]]]:
    """Periodic Voronoi cells: which rock facet owns each pixel, and its distance to the
    facet's border (0 on the border). ``stretch`` > 1 flattens facets into ledges."""
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


def _rock_facets(c: Canvas, seed: int, n: int, stretch: float, tones: str, foot: float) -> None:
    """Fill with angular facets: each facet one tone (by how it faces the light), lit along
    its top-left border, a dark crack along its bottom-right border, darker toward the foot."""
    rng = random.Random(seed)
    own, _edge_d = _facets(seed, n, stretch)
    # facet tones: the biggest facets first, each given the tone that keeps the running mean
    # closest to the middle of the ramp, so every variant has about the same brightness
    area = [sum(row.count(i) for row in own) for i in range(n)]
    mid = (len(tones) - 1) / 2
    base, tot, acc = [1] * n, 0, 0.0
    for i in sorted(range(n), key=lambda i: (-area[i], rng.random())):
        opts = list(range(1, len(tones) - 1))
        rng.shuffle(opts)
        base[i] = min(opts, key=lambda t: abs((acc + t * area[i]) / max(1, tot + area[i]) - mid))
        tot += area[i]
        acc += base[i] * area[i]
    fine = fbm(T, T, seed + 3, 2, 8)
    for y in range(T):
        for x in range(T):
            me = own[y][x]
            i = base[me]
            if own[(y + 1) % T][x] != me or own[y][(x + 1) % T] != me:
                i = 0  # crack
            elif own[(y - 1) % T][x] != me or own[y][(x - 1) % T] != me:
                i = min(len(tones) - 1, i + 1)  # lit rim
            elif fine[y][x] > 0.82:
                i = min(len(tones) - 1, i + 1)
            if y / (T - 1) > 1 - foot and bayer(x, y) < (y / (T - 1) - (1 - foot)) / foot * 1.2:
                i = max(0, i - 1)
            c.set(x, y, tones[i])


def _mountain_top(seed: int) -> Canvas:
    """The wall seen from above: jumbled red boulders, dark crevices, a tuft of grass clinging."""
    rng = random.Random(seed)
    c = Canvas(T, T)
    cob = _cushions(T, T, seed, 7, 3.0, 5.5)
    f = _mix((0.55, _emboss(cob)), (0.25, cob), (0.2, fbm(T, T, seed, 2, 4)))
    _quantize(c, f, "mnopqr", [5, 14, 32, 32, 14, 3], dither=0.05)
    if seed % 3 == 1:  # one variant has a tuft of grass clinging in a crevice
        low = sorted((f[y][x], x, y) for y in range(3, T - 3) for x in range(3, T - 3))
        x, y = low[rng.randrange(3)][1:]
        c.set(x, y, "2")
        c.set(x + 1, y, "1")
        c.set(x, y - 1, "3")
    return c


def _mountain_face(seed: int) -> Canvas:
    """South face: tall angular facets of dark red rock, a lit lip where the top breaks off,
    darker toward the foot and a contact shadow on the ground line."""
    c = Canvas(T, T)
    _rock_facets(c, seed, 5, 0.6, "mnopq", foot=0.4)
    _lip(c, seed + 11)
    for x in range(T):
        c.set(x, T - 1, "m")
    return c


def _cliff_face(seed: int) -> Canvas:
    """Mulgore's layered sandstone: flat ledges in alternating strata colours, each lit
    along its top and undercut along its bottom, a lit lip and a dark foot."""
    c = Canvas(T, T)
    _rock_facets(c, seed, 9, 2.6, "mnopqr", foot=0.35)
    warp = fbm(T, 1, seed + 5, 2, 4)[0]
    for y in range(T):  # strata: a paler sandy band and a deep red band tint the ledges
        for x in range(T):
            ch = c.px[y][x]
            s = (y + 3.0 * (warp[x] - 0.5)) % 8
            if ch in "opq" and 1.5 <= s < 3.5:
                c.px[y][x] = "E" if ch == "o" else "F"
    _lip(c, seed + 11)
    for x in range(T):
        c.set(x, T - 1, "m")
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


def _outline(c: Canvas, skip: str = ".zy") -> None:
    src = [row[:] for row in c.px]
    for y in range(c.h):
        for x in range(c.w):
            if src[y][x] not in ".zy":
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < c.w and 0 <= ny < c.h and src[ny][nx] not in skip:
                    c.px[y][x] = "k"
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

# fringe depth along an edge: period 16 (chains seamlessly), 3 px at both tile corners
DEPTH = {
    "water": [3, 3, 3, 4, 4, 3, 3, 2, 2, 3, 3, 4, 3, 3, 3, 3],
    "dirt": [3, 4, 4, 3, 2, 3, 4, 5, 4, 3, 2, 2, 3, 4, 3, 3],
    "cliff": [3, 3, 4, 3, 3, 2, 3, 3, 4, 4, 3, 2, 3, 3, 4, 3],
}
SIDE_SEED = {"n": 0, "s": 5, "e": 9, "w": 13}
CORNERS = ("ne", "nw", "se", "sw")


def _side_xy(side: str, k: int, j: int) -> tuple[int, int]:
    """Pixel at position ``k`` along the edge, ``j`` px in from the ``side`` border."""
    return {"n": (k, j), "s": (k, T - 1 - j), "w": (j, k), "e": (T - 1 - j, k)}[side]


def _mask(kind: str, where: str) -> set[tuple[int, int]]:
    if len(where) == 1:
        # each side reads the inner profile from another spot (still 3 px at the ends)
        inner = DEPTH[kind][1:15]
        off = SIDE_SEED[where] % len(inner)
        prof = [3] + inner[off:] + inner[:off] + [3]
        return {_side_xy(where, k, j) for k in range(T) for j in range(prof[k])}
    cx = T if "e" in where else 0
    cy = 0 if "n" in where else T
    return {(x, y) for y in range(T) for x in range(T) if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= 3.6 ** 2}


GRASS_TEX = _grass(100)


def _edge(kind: str, where: str, fr: int = 0) -> Canvas:
    g = _mask(kind, where)
    rng = random.Random(f"{kind}.{where}")
    c = Canvas(T, T)
    for x, y in g:
        c.set(x, y, GRASS_TEX.px[y][x])

    def grass(x, y):
        return (x, y) in g

    def inside(x, y):
        return 0 <= x < T and 0 <= y < T

    # the rim of the grass mat: lit where it faces up/left, in shade where it faces down/right
    for x, y in g:
        if inside(x, y + 1) and not grass(x, y + 1):
            c.set(x, y, "1" if bayer(x, y) < 0.6 else "2")
        elif inside(x + 1, y) and not grass(x + 1, y):
            c.set(x, y, "2")
        elif (inside(x, y - 1) and not grass(x, y - 1)) or (inside(x - 1, y) and not grass(x - 1, y)):
            c.set(x, y, "4" if bayer(x, y) < 0.5 else "3")
    # blades poking up out of the mat, into the open tile
    for x, y in sorted(g):
        if inside(x, y - 1) and not grass(x, y - 1) and rng.random() < 0.5:
            c.set(x, y - 1, "3")
            if rng.random() < 0.45 and inside(x, y - 2):
                c.set(x, y - 2, "4" if kind != "water" else "d")

    solid = {(x, y) for y in range(T) for x in range(T) if c.px[y][x] != "."}
    if kind == "water":
        # land is higher than the lake: an earth bank under every south-facing grass rim
        bank = set()
        for x, y in g:
            if inside(x, y + 1) and not grass(x, y + 1):
                run = sum(1 for j in range(3) if grass(x, y - j) or y - j < 0)
                for j in range(1, 1 + min(2, run - 1) + 1):
                    if inside(x, y + j) and not grass(x, y + j):
                        ch = "D" if j == 1 else "B"
                        c.set(x, y + j, ch)
                        bank.add((x, y + j))
        solid |= bank
        # the water's edge: a dark wet line, then foam that laps in and out (frame 0/1)
        land = g | bank
        for y in range(T):
            for x in range(T):
                if (x, y) in solid:
                    continue
                near = [(x + dx, y + dy) in land for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1))]
                near2 = [(x + dx, y + dy) in land for dx, dy in ((0, -2), (-2, 0), (2, 0), (0, 2))]
                t = bayer(x + fr * 2, y + fr)
                if any(near):  # frame 0: foam washed up on the shore; 1: wet, the wave pulls back
                    if fr == 0:
                        c.set(x, y, "M" if t < 0.15 else ("L" if t < 0.6 else "K"))
                    elif t < 0.7:
                        c.set(x, y, "K")
                elif any(near2):
                    if fr == 0 and t < 0.25:
                        c.set(x, y, "K")
                    elif fr == 1 and t < 0.5:
                        c.set(x, y, "M" if t < 0.12 else "L")
    elif kind == "cliff":
        # roots and turf hang over the cliff's lip below a grass rim
        for x, y in sorted(g):
            if inside(x, y + 1) and not grass(x, y + 1) and rng.random() < 0.4:
                for j in range(1, rng.randrange(2, 4)):
                    if inside(x, y + j) and (x, y + j) not in solid:
                        c.set(x, y + j, "B" if j > 1 else "1")
    else:  # dirt: a few loose blades strewn just beyond the fringe
        for x, y in sorted(g):
            if rng.random() < 0.1:
                dx, dy = rng.choice(((0, 3), (3, 0), (-3, 0), (0, -3), (2, 2), (-2, 2)))
                if inside(x + dx, y + dy) and not grass(x + dx, y + dy) and (x + dx, y + dy) not in solid:
                    c.set(x + dx, y + dy, "3")
                    if inside(x + dx, y + dy + 1) and c.get(x + dx, y + dy + 1) == ".":
                        c.set(x + dx, y + dy + 1, "1")

    # cast shadow: light from the top-left, so the grass shades what lies below and right of it
    if kind != "water":
        shade = "z" if kind == "cliff" else "y"
        occ = {(x, y) for y in range(T) for x in range(T) if c.px[y][x] != "."}
        for y in range(T):
            for x in range(T):
                if (x, y) in occ:
                    continue
                if (x, y - 1) in g or (x - 1, y) in g:
                    c.set(x, y, shade)
                elif (x - 1, y - 1) in g and bayer(x, y) < 0.5:
                    c.set(x, y, shade)
    return c


def _edges() -> None:
    notes = {"water": "lake shore", "dirt": "grass fringe on dirt", "cliff": "turf over the cliff"}
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
