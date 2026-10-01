"""Azeroth / Mulgore art: structures. Must satisfy
``wilds.azeroth.manifest.required()["structures"]`` (see docs/azeroth/mulgore-art-manifest.md).

Camps, villages, mines, nests, gates and gathering nodes at the world's real scale
(16 px = 2 yards): a tauren (16x24) walks through a longhouse door, a kodo fits the corral.
Every piece stands on its tile's ground point (bottom-centre anchor) and rises above it.

Big pieces are drawn procedurally on a ``Pic``: a small canvas that holds *palette names*
per pixel, shaded with light from the top-left, then frozen into an ordinary text grid and
legend (``_art``). Small pieces are hand-drawn grids stamped onto the same canvas.

Tauren building: hide stretched over timber frames, poles crossed above the roof, bone and
horn trim, red / blue / white painted bands. Venture Co.: rusty riveted sheet metal. Quilboar:
thorny briar domes patched with hide. Everything is seeded; output is identical on every run.
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

from ..palette import RAMPS, _ramp
from ..pixelart import Art, art
from ..procgen import bayer, fbm, rng_for
from ..registry import register

# --- colours -----------------------------------------------------------------------------------
# earthy Mulgore materials the shared palette lacks (Tau-7's rock is violet, its moss teal)
_ramp("azs_wood", "#2a1812", "#472a1b", "#6a4126", "#8f5e34", "#b5824c", "#d6aa70")   # timber
_ramp("azs_hide", "#3b2517", "#65402a", "#8f6440", "#b98c5c", "#dab584", "#f1dbb0")   # tanned hide
_ramp("azs_stone", "#231e1d", "#3b3330", "#5a4f49", "#7d7068", "#a3958a", "#c9bcae")  # warm grey stone
_ramp("azs_leaf", "#18260f", "#2b4416", "#46661f", "#6a8d2b", "#98b647", "#cbd97e")   # prairie green
_ramp("azs_brier", "#1c150f", "#35281a", "#534027", "#735c37", "#977c4f")             # quilboar bramble
# the tauren camps of the reference pictures: off-white stitched canvas, teal and crimson paint,
# weathered grey-brown totem wood, the grey-teal roof of the lakeside lodge
_ramp("azs_canvas", "#4d4238", "#7b6d5e", "#a6998a", "#cbc0b0", "#e6dece", "#f8f4ea")  # tent canvas
_ramp("azs_teal", "#123a3c", "#1f6265", "#2f8f8c", "#57bdb0", "#9fe3d2")               # teal paint
_ramp("azs_crim", "#2e0c10", "#5e1519", "#8f2220", "#bb3a2c", "#de6e55")               # crimson paint
_ramp("azs_drift", "#221c19", "#3d332c", "#5d5045", "#7f6f60", "#a3927f", "#c6b7a2")   # weathered wood
_ramp("azs_roof", "#1e2a2b", "#334544", "#4d6662", "#6d8a83", "#97b0a6")               # grey-teal roof
# Mulgore's mountains are pale beige-grey; the boulders at Palemane and Kodo Rock blue-grey
_ramp("azs_pale", "#3b3431", "#5f5650", "#867b70", "#ab9f8f", "#cdc1ad", "#ebe0cb")   # pale cliff
_ramp("azs_slate", "#1b1f2a", "#2c3342", "#434d60", "#627083", "#8996a6", "#b3bdc8")  # blue-grey stone
_ramp("azs_vine", "#1d180c", "#352d15", "#544823", "#766832", "#9c8d4a", "#c2b674")   # thorn vine

WOOD = RAMPS["azs_wood"]
HIDE = RAMPS["azs_hide"]
STONE = RAMPS["azs_stone"]
LEAF = RAMPS["azs_leaf"]
BRIER = RAMPS["azs_brier"]
MESA = RAMPS["dust"]
BONE = RAMPS["bone"]
RED = RAMPS["red"]
RUST = RAMPS["rust"]
STEEL = RAMPS["steel"]
FIRE = RAMPS["fire"]
TENT = RAMPS["tent"]
SAND = RAMPS["sand"]
WATER = RAMPS["water"]
GREY = RAMPS["grey"]
BLUE = ["water1", "water2", "water3", "water4"]
GOLD = ["gold0", "gold1", "gold2", "gold3"]
CANVAS = RAMPS["azs_canvas"]
TEAL = RAMPS["azs_teal"]
PAINT_RED = RAMPS["azs_crim"]
DRIFT = RAMPS["azs_drift"]
ROOF = RAMPS["azs_roof"]
PALE = RAMPS["azs_pale"]
SLATE = RAMPS["azs_slate"]
VINE = RAMPS["azs_vine"]
STRAW = SAND[1:]
_MATERIALS = [WOOD, HIDE, STONE, LEAF, BRIER, CANVAS, TEAL, PAINT_RED, DRIFT, ROOF, BONE, SAND, TENT, PALE, SLATE,
              VINE, RUST, STEEL]
SHADOW = "ink:90"          # soft contact shadow on the ground (never outlined)
SHADOW_CORE = "ink:140"    # its denser core right under the object
DEEP = "ink2"

# --- canvas of palette names ----------------------------------------------------------------------


class Pic:
    """A canvas whose pixels are palette names (None = transparent)."""

    def __init__(self, w: int, h: int) -> None:
        self.w, self.h = w, h
        self.px: list[list[str | None]] = [[None] * w for _ in range(h)]

    def copy(self) -> "Pic":
        p = Pic(self.w, self.h)
        p.px = [row[:] for row in self.px]
        return p

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h

    def get(self, x: int, y: int) -> str | None:
        return self.px[y][x] if self.inside(x, y) else None

    def set(self, x: int, y: int, c) -> None:
        x, y = int(x), int(y)
        if not self.inside(x, y):
            return
        if callable(c):
            c = c(x, y)
        if c:
            self.px[y][x] = c

    def clear(self, x: int, y: int) -> None:
        if self.inside(x, y):
            self.px[y][x] = None

    def rect(self, x: int, y: int, w: int, h: int, c) -> "Pic":
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, c)
        return self

    def hline(self, x0: int, x1: int, y: int, c) -> "Pic":
        for x in range(min(x0, x1), max(x0, x1) + 1):
            self.set(x, y, c)
        return self

    def vline(self, x: int, y0: int, y1: int, c) -> "Pic":
        for y in range(min(y0, y1), max(y0, y1) + 1):
            self.set(x, y, c)
        return self

    def line(self, x0: int, y0: int, x1: int, y1: int, c) -> "Pic":
        for x, y in _line(x0, y0, x1, y1):
            self.set(x, y, c)
        return self

    def region(self, test: Callable[[float, float], bool], c) -> "Pic":
        for y in range(self.h):
            for x in range(self.w):
                if test(x + 0.5, y + 0.5):
                    self.set(x, y, c)
        return self

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, c) -> "Pic":
        return self.region(lambda x, y: ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0, c)

    def poly(self, pts: Sequence[tuple[float, float]], c) -> "Pic":
        return self.region(lambda x, y: _in_poly(x, y, pts), c)

    def stamp(self, rows: Sequence[str] | str, legend: dict[str, str], dx: int = 0, dy: int = 0) -> "Pic":
        """Paint a hand-drawn grid; '.' leaves the pixel alone, 'k'/'K'/'w' are ink/ink2/white."""
        if isinstance(rows, str):
            rows = [r.strip() for r in rows.strip().splitlines()]
        lg = {"k": "ink", "K": "ink2", "w": "white", **legend}
        for j, row in enumerate(rows):
            for i, ch in enumerate(row):
                if ch != ".":
                    self.set(dx + i, dy + j, lg[ch])
        return self

    def outline(self, skip: Iterable[str] = (), c: str = "ink") -> "Pic":
        """1px ink around every opaque pixel (shadows / smoke / glow halos in ``skip`` stay open)."""
        skip = set(skip) | {SHADOW, SHADOW_CORE}
        src = [row[:] for row in self.px]
        for y in range(self.h):
            for x in range(self.w):
                if src[y][x] is not None:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    n = src[y + dy][x + dx] if self.inside(x + dx, y + dy) else None
                    if n is not None and n not in skip and ":" not in n:
                        self.px[y][x] = c
                        break
        return self

    def shadow(self, cx: float, cy: float, rx: float, ry: float, c: str = SHADOW) -> "Pic":
        """Contact shadow on the ground, only where nothing is drawn. The light comes from the
        top-left, so it falls a little to the right, with a denser core near the object."""
        cx += max(0.5, rx * 0.08)
        for y in range(self.h):
            for x in range(self.w):
                d = ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2
                if self.px[y][x] is None and d <= 1:
                    self.px[y][x] = SHADOW_CORE if d < 0.45 and c == SHADOW else c
        return self


_POOL = ("abcdefghijlmnopqrstuvxyzABCDEFGHIJLMNOPQRSTUVWXYZ0123456789"
         "!#$%&()*+,-/:;<=>?@[]^_{|}~'\"`\\")


def _art(pics: Sequence[Pic] | Pic, **kw) -> Art:
    """Freeze one or more same-size Pics into an Art (one shared legend)."""
    if isinstance(pics, Pic):
        pics = [pics]
    fixed = {"ink": "k", "ink2": "K", "white": "w"}
    chars: dict[str, str] = {}
    pool = iter(_POOL)
    for p in pics:
        for row in p.px:
            for n in row:
                if n is not None and n not in chars:
                    chars[n] = fixed.get(n) or next(pool)
    frames = [tuple("".join("." if n is None else chars[n] for n in row) for row in p.px) for p in pics]
    legend = {ch: n for n, ch in chars.items()}
    return art(*frames, legend=legend, **kw)


def _line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
    pts = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return pts
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _in_poly(x: float, y: float, pts: Sequence[tuple[float, float]]) -> bool:
    inside = False
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


# --- shading ------------------------------------------------------------------------------------

_L = (-0.5, -0.62, 0.6)
_LN = math.sqrt(sum(v * v for v in _L))
LIGHT = tuple(v / _LN for v in _L)


def lambert(nx: float, ny: float, nz: float) -> float:
    n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return (nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]) / n


def tone(ramp: Sequence[str], v: float, x: int = 0, y: int = 0, d: float = 0.12) -> str:
    """Pick a ramp step for brightness v (0..1), Bayer-dithered by ``d`` between steps."""
    v = v + (bayer(x, y) - 0.5) * d
    return ramp[max(0, min(len(ramp) - 1, int(v * len(ramp))))]


def step(ramp: Sequence[str], name: str | None, d: int) -> str | None:
    """The same material ``d`` steps lighter (+) or darker (-); other colours unchanged."""
    if name in ramp:
        return ramp[max(0, min(len(ramp) - 1, ramp.index(name) + d))]
    return name


def cyl(ramp: Sequence[str], x: int, x0: int, x1: int, y: int = 0, lo: float = 0.15, hi: float = 0.9) -> str:
    """Round pole / barrel shading across its width: lit left, dark right."""
    u = (x + 0.5 - x0) / max(1, x1 - x0 + 1)
    v = hi - (hi - lo) * (u * 1.1) ** 1.2 if u > 0.18 else hi - 0.25 + u
    return tone(ramp, v, x, y, 0.1)


def pole(p: Pic, x0: int, y0: int, x1: int, y1: int, ramp: Sequence[str] = WOOD, lit: int = 3) -> None:
    """A 2px timber: lit on its left/upper side, shadowed on the other."""
    for x, y in _line(x0, y0, x1, y1):
        p.set(x, y, ramp[lit])
        p.set(x + 1, y, ramp[lit - 2])


# --- hide buildings ---------------------------------------------------------------------------------


def dome_shade(p: Pic, cx: float, base: float, rx: float, ry: float, ramp: Sequence[str],
               ribs: Sequence[float] = (), flat: float = 1.0, lo: int = 0,
               band: tuple[float, float] | None = None, paint: Callable | None = None,
               seams: Sequence[float] = ()) -> dict[tuple[int, int], tuple[float, float, float]]:
    """A hide dome over a timber frame. ``flat`` > 1 squares the shoulders (a longhouse).
    ``ribs`` are frame poles under the hide at horizontal positions u (-1..1): a lit ridge
    and a shadowed hollow. ``band`` (ny range) is handed to ``paint(x, y, u, t, v)`` for
    painted patterns. Returns {pixel: (u, ny, v)} for later decoration."""
    info = {}
    e = 2.0 * flat
    for y in range(p.h):
        for x in range(p.w):
            nx = (x + 0.5 - cx) / rx
            ny = (y + 0.5 - base) / ry
            if ny > 0:
                continue
            f = abs(nx) ** e + ny * ny
            if f > 1:
                continue
            nz = math.sqrt(max(0.0, 1 - f))
            gx = flat * abs(nx) ** (e - 1) * (1 if nx >= 0 else -1)
            v = lambert(gx, ny, nz + 0.15)
            v = (v + 0.2) / 1.2
            hw = max(1e-6, (1 - ny * ny)) ** (1 / e)
            u = nx / hw
            lvl = v * (len(ramp) - lo) + lo - 0.7 + (bayer(x, y) - 0.5) * 0.6
            for r in ribs:
                d = (u - r) * hw * rx
                if -1.0 <= d < 0.0:
                    lvl += 1
                elif 0.0 <= d < 1.0:
                    lvl -= 1.2
            for s in seams:  # horizontal lacing seams
                if abs(ny - s) * ry < 0.5:
                    lvl -= 1
            idx = max(0, min(len(ramp) - 1, int(round(lvl))))
            c = ramp[idx]
            if band and band[0] <= ny < band[1] and paint:
                t = (ny - band[0]) / (band[1] - band[0])
                c = paint(x, y, u, t, v) or c
            p.px[y][x] = c
            info[(x, y)] = (u, ny, v)
    return info


def door_arch(p: Pic, x0: int, x1: int, top: int, bottom: int, glow: str | None = None) -> None:
    """A dark rounded doorway, lighter toward the floor if a fire burns inside."""
    w = x1 - x0 + 1
    cx = x0 + w / 2
    for y in range(top, bottom + 1):
        for x in range(x0, x1 + 1):
            dy = y + 0.5 - (top + w / 2)
            dx = x + 0.5 - cx
            if dy < 0 and dx * dx + dy * dy > (w / 2) ** 2:
                continue
            c = DEEP
            if glow and y >= bottom - 2 and 1 < x - x0 < w - 2:
                k = y - (bottom - 2)  # embers on the floor, fading upward
                c = glow if bayer(x, y) < 0.18 + k * 0.2 else ("fire1" if bayer(x, y) < 0.35 + k * 0.3 else DEEP)
            elif x == x0 or y == top:
                c = "ink"
            p.set(x, y, c)


def skull(p: Pic, cx: int, y: int, horns: bool = True) -> None:
    """A kodo skull with sweeping horns, facing out: tauren door trophy (13 wide)."""
    p.stamp([
        "tt.........tt",
        ".tt.......tt.",
        "..tTT...TTs..",
        "...sBBBBBs...",
        "...BBkBkBs...",
        "....BBBBs....",
        ".....BBs.....",
        ".....kBk.....",
    ] if horns else [
        "...sBBBBBs...",
        "...BBkBkBs...",
        "....BBBBs....",
        ".....BBs.....",
        ".....kBk.....",
    ], {"t": BONE[3], "T": BONE[2], "s": BONE[2], "B": BONE[4]}, cx - 6, y)


def tusk_pair(p: Pic, x0: int, x1: int, base: int, height: int) -> None:
    """Two curved bone tusks framing a doorway (left one mirrored)."""
    for i in range(height):
        t = i / max(1, height - 1)
        off = int(round(math.sin(t * math.pi * 0.9) * 2.2))
        y = base - i
        for x, dirn in ((x0 - off, -1), (x1 + off, 1)):
            p.set(x, y, BONE[4] if dirn < 0 else BONE[3])
            if i < height * 0.6:
                p.set(x - dirn, y, BONE[2])


# --- 2.5D scene: a tiny z-buffered renderer for the big tauren pieces -------------------------------
#
# World units are pixels: x to the right, y toward the viewer, z up. The camera looks down from a high
# angle, so a ground circle of radius r becomes a 2:1 ellipse (r by r/2) like the diamond tiles, and
# heights stay upright. Surfaces are sampled densely, z-buffered, lit from the top-left, quantised to
# ramps with an ordered dither, then frozen into an ordinary palette-name Pic.

_L3 = (-0.55, 0.35, 0.76)
_L3N = math.sqrt(sum(v * v for v in _L3))
LIGHT3 = tuple(v / _L3N for v in _L3)
FRONT = math.pi / 2           # the angle around a round tent that faces the viewer


def shade3(nx: float, ny: float, nz: float) -> float:
    """Brightness 0..1 of a surface with normal n under the top-left sun (a little ambient)."""
    n = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    d = (nx * LIGHT3[0] + ny * LIGHT3[1] + nz * LIGHT3[2]) / n
    return max(0.0, min(1.0, 0.16 + 0.86 * max(0.0, d) ** 1.25))


class Scene:
    """Painter with a depth buffer. ``ox, oy`` is the screen pixel under the world origin."""

    def __init__(self, w: int, h: int, ox: float, oy: float) -> None:
        self.w, self.h, self.ox, self.oy = w, h, ox, oy
        self.col: list[list[str | None]] = [[None] * w for _ in range(h)]
        self.dep = [[-1e9] * w for _ in range(h)]
        self.oid = [[0] * w for _ in range(h)]
        self._ids = 0

    def new_id(self) -> int:
        self._ids += 1
        return self._ids

    def screen(self, x: float, y: float, z: float) -> tuple[int, int]:
        return int(math.floor(self.ox + x)), int(math.floor(self.oy + y * 0.5 - z))

    def put(self, x: float, y: float, z: float, c, oid: int, bias: float = 0.0) -> None:
        ix, iy = self.screen(x, y, z)
        self.put_px(ix, iy, 2 * y + z + bias, c, oid)

    def put_px(self, ix: int, iy: int, d: float, c, oid: int) -> None:
        if 0 <= ix < self.w and 0 <= iy < self.h and d > self.dep[iy][ix]:
            if callable(c):
                c = c(ix, iy)
            if c:
                self.col[iy][ix], self.dep[iy][ix], self.oid[iy][ix] = c, d, oid

    def lathe(self, cx: float, cy: float, prof: Sequence[tuple[float, float]], mat: Callable,
              ds: float = 0.25, squash: float = 1.0, lift: float = 0.0) -> None:
        """Surface of revolution through profile points (z, r), listed from the bottom outward/up.
        ``mat(th, z, r, v, ix, iy)`` returns a palette name (``th`` = angle, FRONT faces the viewer).
        Rasterised column by column, so the angle is exact for each pixel column and seams and
        patterns come out as clean lines. ``squash`` flattens the depth (oval plan), ``lift`` raises it."""
        oid = self.new_id()
        samples = []
        for (z0, r0), (z1, r1) in zip(prof, prof[1:]):
            seg = math.hypot(z1 - z0, r1 - r0)
            if seg == 0:
                continue
            nr, nz = (z1 - z0) / seg, -(r1 - r0) / seg       # outward normal in the (r, z) plane
            for k in range(int(seg / ds) + 1):
                t = k * ds / seg
                samples.append((z0 + (z1 - z0) * t, r0 + (r1 - r0) * t, nr, nz))
        rmax = max(r for _, r in prof)
        for ix in range(int(math.floor(self.ox + cx - rmax)) - 1, int(math.ceil(self.ox + cx + rmax)) + 2):
            dx = ix + 0.5 - self.ox - cx
            for sgn in (1, -1):
                prev = None
                for z, r, nr, nz in samples:
                    if abs(dx) > r:
                        prev = None
                        continue
                    y = sgn * math.sqrt(r * r - dx * dx)
                    th = math.atan2(y, dx) % math.tau
                    c, s = dx / r if r else 0.0, y / r if r else 0.0
                    v = shade3(nr * c, nr * s / squash, nz)
                    y *= squash
                    zz = z + lift
                    iy = int(math.floor(self.oy + (cy + y) * 0.5 - zz))
                    d = 2 * (cy + y) + zz
                    rows = [iy]
                    if prev is not None and abs(iy - prev) > 1:   # close gaps on flat parts
                        rows = range(min(iy, prev) + 1, max(iy, prev)) if iy != prev else [iy]
                        rows = list(rows) + [iy]
                    for yy in rows:
                        self.put_px(ix, yy, d, lambda px, py, th=th, z=z, r=r, v=v: mat(th, z, r, v, px, py), oid)
                    prev = iy

    def quad(self, p0, a, b, mat: Callable, ds: float = 0.4, oid: int | None = None, tri: bool = False) -> None:
        """Flat patch p0 + u*a + v*b (u, v in 0..1; a triangle u + v <= 1 if ``tri``);
        ``mat(u, v, light, ix, iy)``."""
        oid = oid or self.new_id()
        n = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
        if 2 * n[1] + n[2] < 0:   # face the camera
            n = (-n[0], -n[1], -n[2])
        lv = shade3(*n)
        nu = int(math.sqrt(sum(c * c for c in a)) / ds) + 1
        nv = int(math.sqrt(sum(c * c for c in b)) / ds) + 1
        for i in range(nu + 1):
            u = i / nu
            for j in range(nv + 1):
                w = j / nv
                if tri and u + w > 1.0001:
                    break
                self.put(p0[0] + u * a[0] + w * b[0], p0[1] + u * a[1] + w * b[1], p0[2] + u * a[2] + w * b[2],
                         lambda ix, iy, u=u, w=w: mat(u, w, lv, ix, iy), oid)

    def rod(self, p0, p1, rad: float, ramp: Sequence[str], hi: float = 0.9, lo: float = 0.2,
            oid: int | None = None) -> None:
        """A round timber from p0 to p1, ``rad`` px thick each side, lit on its upper-left flank."""
        oid = oid or self.new_id()
        sx0, sy0 = p0[0], p0[1] * 0.5 - p0[2]
        sx1, sy1 = p1[0], p1[1] * 0.5 - p1[2]
        ln = math.hypot(sx1 - sx0, sy1 - sy0) or 1.0
        px, py = -(sy1 - sy0) / ln, (sx1 - sx0) / ln     # screen perpendicular
        if px + py > 0:                                  # make +side point to the upper-left (lit)
            px, py = -px, -py
        steps = int(max(ln, math.dist(p0, p1)) / 0.35) + 1
        for i in range(steps + 1):
            t = i / steps
            x, y, z = (p0[k] + (p1[k] - p0[k]) * t for k in range(3))
            k = -rad
            while k <= rad + 1e-6:
                f = (k + rad) / (2 * rad) if rad else 0.5   # 0 = shadow flank, 1 = lit flank
                c = ramp[max(0, min(len(ramp) - 1, int((lo + (hi - lo) * f) * len(ramp))))]
                # move in screen space: x directly, y through z (keeps depth of the axis)
                self.put(x + px * k, y, z - py * k, c, oid, bias=(rad - abs(k)) * 0.5)
                k += 0.5

    def surface(self, fn: Callable, nu: int, nv: int, mat: Callable, oid: int | None = None) -> None:
        """Parametric patch: ``fn(u, v)`` -> ((x, y, z), (nx, ny, nz)) for u, v in 0..1;
        ``mat(u, v, light, ix, iy)``."""
        oid = oid or self.new_id()
        for i in range(nu + 1):
            u = i / nu
            for j in range(nv + 1):
                w = j / nv
                (x, y, z), n = fn(u, w)
                lv = shade3(*n)
                self.put(x, y, z, lambda ix, iy, u=u, w=w, lv=lv: mat(u, w, lv, ix, iy), oid)

    def ball(self, x: float, y: float, z: float, r: float, mat: Callable, oid: int) -> None:
        """A lit sphere seen from the camera (the building block of thick vines);
        ``mat(light, ix, iy)``."""
        sx, sy = self.ox + x, self.oy + y * 0.5 - z
        d0 = 2 * y + z
        for iy in range(int(math.floor(sy - r)), int(math.ceil(sy + r)) + 1):
            for ix in range(int(math.floor(sx - r)), int(math.ceil(sx + r)) + 1):
                a, b = (ix + 0.5 - sx) / r, (iy + 0.5 - sy) / r
                q = a * a + b * b
                if q > 1:
                    continue
                f = math.sqrt(1 - q)
                # screen right = world x; screen up = (0, -1, 2)/sqrt5; toward camera = (0, 2, 1)/sqrt5
                n = (a, (b + 2 * f) / 2.236, (-2 * b + f) / 2.236)
                lv = shade3(*n)
                self.put_px(ix, iy, d0 + f * r * 2.2, lambda px, py, lv=lv: mat(lv, px, py), oid)

    def tube(self, pts: Sequence[tuple[float, float, float]], r0: float, r1: float, mat: Callable,
             step: float = 0.5) -> list[tuple[float, float, float, float, float]]:
        """A thick tapering tube along a Catmull-Rom spline through ``pts`` (radius r0 -> r1).
        ``mat(light, s, ix, iy)`` gets the arc length s. Returns the samples (x, y, z, r, s)."""
        oid = self.new_id()
        dense = []
        ext = [pts[0]] + list(pts) + [pts[-1]]
        for i in range(1, len(ext) - 2):
            p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
            n = max(2, int(math.dist(p1, p2) / 0.25))
            for k in range(n):
                t = k / n
                dense.append(tuple(0.5 * (2 * p1[c] + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t * t
                                          + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t ** 3) for c in range(3)))
        dense.append(tuple(pts[-1]))
        total = sum(math.dist(a, b) for a, b in zip(dense, dense[1:])) or 1.0
        out, s, last = [], 0.0, -1e9
        for i, q in enumerate(dense):
            if i:
                s += math.dist(dense[i - 1], q)
            if s - last < step and i != len(dense) - 1:
                continue
            last = s
            r = r0 + (r1 - r0) * (s / total)
            self.ball(q[0], q[1], q[2], r, lambda lv, ix, iy, s=s: mat(lv, s, ix, iy), oid)
            out.append((q[0], q[1], q[2], r, s))
        return out

    def disc(self, cx: float, cy: float, z: float, r: float, mat: Callable) -> None:
        """A flat horizontal disc (a platform top); ``mat(rr, th, ix, iy)``."""
        oid = self.new_id()
        lv = shade3(0, 0, 1)
        rr = 0.0
        while rr <= r:
            n = max(6, int(math.tau * rr / 0.5))
            for i in range(n):
                th = i * math.tau / n
                self.put(cx + rr * math.cos(th), cy + rr * math.sin(th), z,
                         lambda ix, iy, rr=rr, th=th: mat(rr, th, lv, ix, iy), oid)
            rr += 0.4

    def pic(self, edge: float = 7.0) -> Pic:
        """Freeze into a Pic. Where a nearer part overlaps a farther one, the farther pixel along
        the boundary turns dark: the inner contour lines of pixel art."""
        p = Pic(self.w, self.h)
        for y in range(self.h):
            for x in range(self.w):
                c = self.col[y][x]
                if c is None:
                    continue
                d, o = self.dep[y][x], self.oid[y][x]
                dark = False
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < self.w and 0 <= yy < self.h and self.col[yy][xx] is not None:
                        dd = self.dep[yy][xx] - d
                        if dd > edge or (self.oid[yy][xx] != o and dd > 1.5):
                            dark = True
                            break
                p.px[y][x] = darker(c, 2) if dark else c
        return p


def darker(name: str, d: int) -> str:
    """The same material ``d`` steps darker, for contour lines (ink if it has no ramp)."""
    for ramp in _MATERIALS:
        if name in ramp:
            i = ramp.index(name)
            return ramp[i - d] if i - d >= 0 else "ink"
    return "ink" if name not in ("ink", "ink2") else name


def wrap(a: float) -> float:
    """Angle difference folded into -pi..pi."""
    return (a + math.pi) % math.tau - math.pi


def decal(rows: Sequence[str], legend: dict[str, str], fallback: Callable | None = None) -> Callable:
    """Quad material that maps a hand-drawn grid over the patch (u -> columns, w -> rows upward)."""
    def mat(u, w, lv, ix, iy):
        r = rows[min(len(rows) - 1, int((1 - w) * len(rows)))]
        ch = r[min(len(r) - 1, int(u * len(r)))]
        if ch == ".":
            return fallback(u, w, lv, ix, iy) if fallback else None
        return {"k": "ink", "K": "ink2", "w": "white", **legend}[ch]
    return mat


def hexcell(u: float, v: float, s: float) -> tuple[int, int, float]:
    """Pointy-top hexagon grid of size ``s``: (column, row, distance to the cell's border)."""
    hw, hh = s * math.sqrt(3), s * 1.5
    j0 = int(math.floor(v / hh))
    best = []
    for j in (j0 - 1, j0, j0 + 1, j0 + 2):
        off = hw / 2 if j % 2 else 0.0
        i0 = int(math.floor((u - off) / hw))
        for i in (i0 - 1, i0, i0 + 1, i0 + 2):
            best.append((math.hypot(u - (i * hw + off), v - j * hh), i, j))
    best.sort()
    (d1, i, j), (d2, _, _) = best[0], best[1]
    return i, j, (d2 - d1) / 2


# --- materials of a tauren camp ---------------------------------------------------------------------


def cord(v: float) -> str:
    return WOOD[1] if v > 0.45 else WOOD[0]


def canvas(seams: int = 10, off: float = 0.0, ramp: Sequence[str] = (), rings: Sequence[float] = (),
           bands: Sequence[tuple[float, float, Callable]] = (), door: Callable | None = None,
           tick: int = 3, gain: float = 1.0) -> Callable:
    """Off-white stitched canvas: vertical seams laced with dark cord (a seam line with short
    cross ticks every ``tick`` px), optional laced rings at heights ``rings``, painted ``bands``
    (z0, z1, painter) and a ``door(th, z, r, v, ix, iy)`` cut-out."""
    ramp = ramp or CANVAS

    def mat(th, z, r, v, ix, iy):
        if door:
            c = door(th, z, r, v, ix, iy)
            if c:
                return c
        for z0, z1, paint in bands:
            if z0 <= z < z1:
                c = paint(th, z - z0, r, v, ix, iy)
                if c:
                    return c
        a = (th / math.tau * seams + off) % 1.0
        gap = math.tau * r / seams                           # px between two seams here
        dist = min(a, 1 - a) * gap                           # arc px to the nearest seam
        if gap > 5 and dist < 1.5 and int(z) % tick == 0:
            return cord(v)
        if gap > 3 and dist < 0.6:
            return ramp[1] if v < 0.45 else ramp[2]
        for rz in rings:
            if abs(z - rz) < 0.5:
                return cord(v) if int(th * r) % 3 else step(ramp, tone(ramp, v * gain, ix, iy), -1)
        return tone(ramp, v * gain, ix, iy, 0.1)
    return mat


def paint_band(kind: str, height: float) -> Callable:
    """Painted bands on canvas: 'tri' red lines around a row of teal triangles, 'hex' teal and
    cream hexagons netted in red, 'step' teal stepped diamonds between red lines."""
    def paint(th, t, r, v, ix, iy):
        u = wrap(th - FRONT) * r
        red = PAINT_RED[3] if v > 0.5 else PAINT_RED[2] if v > 0.28 else PAINT_RED[1]
        teal = TEAL[3] if v > 0.5 else TEAL[2] if v > 0.28 else TEAL[1]
        if kind == "hex":
            i, j, e = hexcell(u, t + 1.0, 2.0)
            if e < 0.45 or t < 0.6 or t > height - 0.6:
                return red
            return teal if (i + 2 * j) % 3 else tone(CANVAS, v + 0.1, ix, iy)
        if t < 1 or t >= height - 1:
            return red
        tt = (t - 1) / max(1.0, height - 2)
        if kind == "tri":
            ph = (u / 4.0) % 1.0
            return teal if abs(ph - 0.5) * 2 < 1 - tt else None
        ph = (u / 6.0) % 1.0
        dd = abs(ph - 0.5) * 2 + abs(tt - 0.5) * 2
        return teal if dd < 0.75 else (red if dd < 0.95 else None)
    return paint


def arch_door(width: float, height: float, glow: bool = True, cone: bool = False) -> Callable:
    """A doorway centred on the front of a round wall (rounded) or a cone (triangular flap)."""
    def door(th, z, r, v, ix, iy):
        u = wrap(th - FRONT) * r
        if cone:
            half = width / 2 * max(0.0, 1 - z / height)
        else:
            top = height - width / 2
            half = width / 2 if z < top else math.sqrt(max(0.0, (width / 2) ** 2 - (z - top) ** 2))
        if abs(u) >= half or z >= height:
            return None
        if abs(u) >= half - 0.9:
            return CANVAS[1] if u < 0 else WOOD[0]
        if glow and z < 2.5:
            return FIRE[3] if bayer(ix, iy) < 0.5 - z * 0.15 else FIRE[2]
        if glow and z < 4.5 and bayer(ix, iy) < 0.3:
            return FIRE[1]
        return DEEP
    return door


def planks(ramp: Sequence[str], width: float = 2.6, gain: float = 1.0) -> Callable:
    """Vertical timber planks around a round base (lathe material)."""
    def mat(th, z, r, v, ix, iy):
        u = th * r / width
        if u % 1.0 < 1 / width:
            return ramp[max(0, int(v * gain * len(ramp)) - 2)]
        return tone(ramp, v * gain + ((int(u) * 37) % 5 - 2) * 0.03, ix, iy, 0.1)
    return mat


def ring_posts(sc: Scene, cx: float, cy: float, r: float, n: int, top: float, off: float = 0.0,
               rad: float = 1.0, base: float = 0.0, skip_front: float = 0.0) -> None:
    """A ring of upright posts, lighter carved caps on top."""
    for i in range(n):
        th = off + i * math.tau / n
        if skip_front and abs(wrap(th - FRONT)) < skip_front:
            continue
        x, y = cx + r * math.cos(th), cy + r * math.sin(th)
        sc.rod((x, y, base), (x, y, top), rad, WOOD[1:])
        sc.put(x - 0.5, y, top + 0.6, WOOD[5], sc.new_id(), bias=2)


def apex_poles(sc: Scene, cx: float, cy: float, z0: float, z1: float, spread: float,
               angles: Sequence[float], rad: float = 0.75) -> None:
    """Timber poles crossing at a cone's smoke hole and fanning out above it."""
    for a in angles:
        sc.rod((cx - math.cos(a) * 1.0, cy - math.sin(a) * 1.0, z0),
               (cx + math.cos(a) * spread, cy + math.sin(a) * spread, z1), rad, WOOD[1:])


HORNS = [
    "t.........t",
    "Tt.......tT",
    ".Tt.....tT.",
    "..TtwhwtT..",
    "...hHHHd...",
    "....hHd....",
]
HORN_LG = {"t": "bone4", "T": "bone3", "h": "azs_wood4", "H": "azs_wood3", "d": "azs_wood1"}


def finial(p: Pic, cx: int, top: int) -> None:
    """Crossed horns lashed to the tip of a tent: the tauren roof ornament."""
    p.stamp(HORNS, HORN_LG, cx - 5, top)


def finish(p: Pic, cx: float, gy: float, rx: float, ry: float) -> Pic:
    p.outline()
    p.shadow(cx, gy, rx, ry)
    return p


# --- great round tents ------------------------------------------------------------------------------


def _hut_large() -> None:
    """Camp Narache's great tent: a timber drum, a wide flared canvas eave with posts standing
    through its rim, a stitched canvas bell above, a painted band and crossed horns on top."""
    W, H = 64, 56
    cx, cy = 32.0, 0.0
    sc = Scene(W, H, 0, 44)
    door = arch_door(9, 11)
    drum = planks(WOOD[1:], 3.0)
    eave = canvas(12, 0.5, rings=(16.5,), tick=3)
    prof = [(0, 17.0), (12.5, 17.0), (13.0, 28.5), (13.7, 28.7), (17.5, 25.3), (20, 21.0), (21.5, 14.5)]
    sc.lathe(cx, cy, prof,
             lambda th, z, r, v, ix, iy: ((door(th, z, r, v, ix, iy) or drum(th, z, r, v, ix, iy)) if z < 12.7
                                          else eave(th, z, r, v, ix, iy)))
    sc.lathe(cx, cy, [(21, 15.0), (23, 14.4), (37.3, 1.0), (37.4, 0)],
             canvas(10, 0.0, bands=((22, 26, paint_band("hex", 4.0)),), tick=3))
    # posts lashed through the eave's rim, standing out above it
    for i in range(12):
        th = 0.26 + i * math.tau / 12
        r = 26.0
        z0 = 13.7 + (28.7 - r) / (28.7 - 25.3) * (17.5 - 13.7)
        x, y = cx + r * math.cos(th), cy + r * math.sin(th)
        sc.rod((x, y, z0 - 1.5), (x, y, z0 + 5.5), 0.9, WOOD[1:])
        sc.put(x - 0.5, y, z0 + 6.1, WOOD[5], sc.new_id(), bias=2)
    p = sc.pic()
    finial(p, 32, 0)
    register("az.obj.hut_large", _art(finish(p, 32, 53.5, 22, 3.2),
             note="Camp Narache's great tent: timber drum, flared canvas eave, posts through its rim, stitched bell"))


def _big_teepee() -> None:
    """Bloodhoof's great teepee: a tall white stitched cone on a round timber platform with
    steps, carved posts on the rim and a bundle of long crossed poles fanning out of the top."""
    W, H = 64, 80
    cx, cy = 32.0, 0.0
    sc = Scene(W, H, 0, 62)
    # the round timber platform and its rim posts
    sc.lathe(cx, cy, [(0, 28.5), (5, 28.5), (5, 0)],
             lambda th, z, r, v, ix, iy: planks(WOOD[1:], 2.4)(th, z, r, v, ix, iy) if z < 4.9
             else tone(WOOD[2:], 0.35 + v * 0.5 + (0.12 if int(r) % 3 == 0 else 0), ix, iy, 0.15))
    # steps up to the door
    for k in range(3):
        y0 = 28.5 + (3 - k) * 2.5
        sc.quad((cx - 6, y0, 0), (12, 0, 0), (0, 0, 1.7 * (k + 1)),
                lambda u, w, lv, ix, iy: WOOD[2] if w > 0.85 else tone(WOOD[1:4], lv, ix, iy))
        sc.quad((cx - 6, y0 - 2.5, 1.7 * (k + 1)), (12, 0, 0), (0, 2.5, 0),
                lambda u, w, lv, ix, iy: WOOD[4] if u > 0.04 else WOOD[3])
    # the cone: dark hide wrap at the foot, a laced band, white stitched canvas up to the smoke hole
    door = arch_door(11, 15, cone=True)
    wrap_mat = planks(HIDE[0:4], 4.0)
    band = paint_band("tri", 4.0)
    cone_mat = canvas(14, 0.5, bands=((12, 16, band), (33, 35, paint_band("tri", 2.0))), door=door, tick=3)
    sc.lathe(cx, cy, [(5, 23.0), (8, 22.0), (48, 2.4), (49, 0)],
             lambda th, z, r, v, ix, iy: (door(th, z, r, v, ix, iy) or wrap_mat(th, z, r, v, ix, iy))
             if z < 8.5 else cone_mat(th, z, r, v, ix, iy))
    ring_posts(sc, cx, cy, 26.5, 10, 13, off=0.35, rad=1.2, base=5, skip_front=0.45)
    # the pole bundle: long poles through the smoke hole, fanned out and leaning
    angles = [0.3, 0.9, 1.5, 2.1, 2.7, 3.4, 4.0, 4.7, 5.3, 5.9]
    for i, a in enumerate(angles):
        ln = 21 + (i * 7) % 6
        sc.rod((cx - math.cos(a) * 2, cy - math.sin(a) * 2, 40),
               (cx + math.cos(a) * (8 + (i % 3) * 2), cy + math.sin(a) * (8 + (i % 3)), 40 + ln), 1.0, WOOD[1:])
    p = sc.pic()
    register("az.obj.big_teepee", _art(finish(p, 32, 76, 31, 4.5),
             note="Bloodhoof's great teepee: white stitched cone, timber platform, steps, pole bundle"))


# --- medium tents -----------------------------------------------------------------------------------


def _hut_small(v: int) -> None:
    W, H = 48, 44
    cx, cy = 24.0, 0.0
    sc = Scene(W, H, 0, 33)
    if v == 0:   # Sungraze: painted hide wall, flared eave, tall canvas cone
        door = arch_door(7, 8)
        wall = hide_wall()
        sc.lathe(cx, cy, [(0, 14.5), (8.5, 14.5), (9.5, 20.5), (10.2, 20.6), (13, 15)],
                 lambda th, z, r, vv, ix, iy: (door(th, z, r, vv, ix, iy) or wall(th, z, r, vv, ix, iy))
                 if z < 8.6 else canvas(10, 0.5, bands=((10.2, 12.8, paint_band("step", 2.6)),))(th, z, r, vv, ix, iy))
        sc.lathe(cx, cy, [(12.5, 15.4), (16, 13), (30, 2.2), (31, 0)], canvas(9, 0.0))
        apex_poles(sc, cx, cy, 27, 37, 4, (0.5, 2.6, 1.6))
        p = sc.pic()
        finial(p, 24, 0)
    elif v == 1:  # round hide lodge: a tan bell, red-and-teal band, ring of short posts
        door = arch_door(7, 9)
        sc.lathe(cx, cy, [(0, 19.0), (4, 19.4), (9, 18.4), (15, 15.6), (21, 11.0), (25, 6.0), (27.5, 2.2), (28, 0)],
                 canvas(8, 0.5, ramp=HIDE[1:], bands=((9, 13, paint_band("tri", 4.0)),), door=door, gain=1.05))
        ring_posts(sc, cx, cy, 20.5, 10, 6, off=0.3, rad=0.8, skip_front=0.4)
        apex_poles(sc, cx, cy, 24, 34, 4.5, (0.6, 2.5, 1.55, 4.2))
        p = sc.pic()
        finial(p, 24, 3)
    else:         # two-tier canvas cone with a hex band and crossed poles
        door = arch_door(7, 10, cone=False)
        sc.lathe(cx, cy, [(0, 19.5), (2, 19.0), (12, 12.5), (13, 12.2)],
                 canvas(12, 0.5, bands=((5.5, 9.5, paint_band("hex", 4.0)),), door=door))
        sc.lathe(cx, cy, [(12.6, 12.6), (14, 11.4), (31, 2.0), (32, 0)], canvas(9, 0.0, rings=(20,)))
        apex_poles(sc, cx, cy, 28, 38, 4, (0.5, 2.6, 1.6, 4.4))
        p = sc.pic()
        finial(p, 24, 0)
    register(f"az.obj.hut_small@{v}", _art(finish(p, 24, 40.5, 23, 3.4),
             note=["tent with a painted hide wall, flared eave and a canvas cone",
                   "round tan hide lodge with a red-and-teal band and posts",
                   "two-tier canvas tent with a hex band"][v]))


def hide_wall() -> Callable:
    """Tan hide wall painted with teal diamonds in red outline (Camp Sungraze)."""
    def mat(th, z, r, v, ix, iy):
        u = wrap(th - FRONT) * r
        ph = ((u + 5) / 10.0) % 1.0
        dd = abs(ph - 0.5) * 2 * 5 + abs(z - 4.5)
        if 4 < abs(u) < 14 or abs(u) > 17:
            if dd < 2.6:
                return TEAL[3] if v > 0.45 else TEAL[2]
            if dd < 3.6:
                return PAINT_RED[2]
        return tone(HIDE[1:5], v + (0.1 if int(z) % 4 == 0 else 0), ix, iy, 0.12)
    return mat


def _tent(v: int) -> None:
    """Tall conical tents with laced seams and crossed horns (three patterns)."""
    W, H = 40, 48
    cx, cy = 20.0, 0.0
    sc = Scene(W, H, 0, 39)
    if v == 0:
        door = arch_door(8, 13, cone=True)
        sc.lathe(cx, cy, [(0, 15.0), (1, 14.6), (33, 2.0), (34, 0)],
                 canvas(9, 0.5, bands=((14, 18, paint_band("tri", 4.0)), (3, 5, paint_band("tri", 2.0))), door=door))
        apex_poles(sc, cx, cy, 30, 41, 4, (0.5, 2.6, 1.6, 4.3))
    elif v == 1:
        door = arch_door(8, 12, cone=True)
        sc.lathe(cx, cy, [(0, 14.5), (1, 14.2), (34, 1.8), (35, 0)],
                 canvas(8, 0.5, ramp=HIDE[1:], bands=((22, 25, paint_band("step", 3.0)),
                                                       (4, 8, paint_band("hex", 4.0))), door=door, gain=1.05))
        apex_poles(sc, cx, cy, 31, 42, 3.5, (0.7, 2.4, 1.55))
    else:          # flared skirt halfway up, painted hide wall below (Camp Sungraze)
        door = arch_door(6, 7)
        wall = hide_wall()
        sc.lathe(cx, cy, [(0, 11.0), (8, 11.0), (9, 16.5), (9.8, 16.6), (12.5, 11.4)],
                 lambda th, z, r, vv, ix, iy: (door(th, z, r, vv, ix, iy) or wall(th, z, r, vv, ix, iy))
                 if z < 8.1 else canvas(10, 0.5, bands=((9.8, 12.4, paint_band("step", 2.6)),))(th, z, r, vv, ix, iy))
        sc.lathe(cx, cy, [(12, 11.8), (14, 10.4), (35, 1.6), (36, 0)], canvas(8, 0.0))
        apex_poles(sc, cx, cy, 32, 42, 3.5, (0.5, 2.6, 1.6))
    p = sc.pic()
    finial(p, 20, 0)
    register(f"az.obj.tent@{v}", _art(finish(p, 20, 45, 18, 3),
             note=["white laced cone tent, teal-and-red bands", "tan hide cone tent, stepped and hex bands",
                   "Sungraze tent: canvas cone over a flared eave and a painted hide wall"][v]))


# --- inn, stable, stilt lodge -----------------------------------------------------------------------


def _inn() -> None:
    """A round canvas lodge with a hide awning over a warm doorway and an ale sign."""
    W, H = 48, 40
    cx, cy = 22.0, 0.0
    sc = Scene(W, H, 0, 31)
    door = arch_door(8, 8.5, glow=True)
    wall = hide_wall()
    sc.lathe(cx, cy, [(0, 15.0), (8.5, 15.0), (9.5, 19.5), (10.2, 19.6), (12.5, 15)],
             lambda th, z, r, v, ix, iy: (door(th, z, r, v, ix, iy) or wall(th, z, r, v, ix, iy))
             if z < 8.6 else canvas(12, 0.5)(th, z, r, v, ix, iy))
    sc.lathe(cx, cy, [(12, 15.4), (14, 14), (25, 4.5), (27, 1.5), (27.5, 0)],
             canvas(10, 0.0, bands=((14.5, 18.5, paint_band("hex", 4.0)),)))
    apex_poles(sc, cx, cy, 23, 33, 3.5, (0.5, 2.6, 1.6))
    # sign on a post at the right: a mug of ale
    sc.rod((41, 8, 0), (41, 8, 22), 0.7, WOOD[1:])
    sc.rod((35, 8, 21.5), (44, 8, 21.5), 0.5, WOOD[1:])
    p = sc.pic()
    p.stamp(["kkkkkkk", "kpppppk", "kpyyGpk", "kpyYGyk", "kpyYGpk", "kpppppk", "kkkkkkk"],
            {"p": WOOD[4], "y": "gold2", "Y": "gold1", "G": BONE[4]}, 35, 13)
    p.set(36, 12, "ink")
    p.set(40, 12, "ink")
    finial(p, 22, 0)
    register("az.obj.inn", _art(finish(p, 23, 37.5, 22, 2.6),
             note="tauren inn: round canvas lodge, painted hide wall, awning, warm door, ale sign"))


def box_frame(phi: float) -> Callable:
    """World point of a building's local (a along its length, b across, z) rotated by phi."""
    c, s = math.cos(phi), math.sin(phi)
    return lambda cx, cy, a, b, z: (cx + a * c - b * s, cy + a * s + b * c, z)


def _stable() -> None:
    """An open stable: canvas lean-to roof on six posts over hay and a water trough."""
    W, H = 40, 32
    sc = Scene(W, H, 0, 24)
    P = box_frame(-0.32)
    cx, cy, A, B = 20.0, -1.0, 15.0, 6.5

    def v3(a, b, z):
        return P(0, 0, a, b, z)

    def at(a, b, z):
        return P(cx, cy, a, b, z)
    # hay heap and trough under the roof
    sc.lathe(at(-7, 0, 0)[0], at(-7, 0, 0)[1], [(0, 6), (2, 5.5), (4, 3.5), (5, 0)],
             lambda th, z, r, v, ix, iy: tone(STRAW, v + 0.1 + (0.15 if bayer(ix * 3, iy) > 0.8 else 0), ix, iy, 0.3))
    sc.quad(at(3, 3, 0), v3(9, 0, 0), (0, 0, 3), lambda u, w, lv, ix, iy: WOOD[3] if w > 0.7 else tone(WOOD[1:4], lv, ix, iy))
    sc.quad(at(3, 3, 3), v3(9, 0, 0), v3(0, -3, 0), lambda u, w, lv, ix, iy: WATER[4] if 0.1 < u < 0.9 and 0.2 < w < 0.9 else WOOD[4])
    # posts
    for a in (-A, 0, A):
        sc.rod(at(a, B, 0), at(a, B, 11), 0.8, WOOD[1:])
        sc.rod(at(a, -B, 0), at(a, -B, 16), 0.8, WOOD[1:])
    # roof: canvas sloping toward the viewer, laced edges and a red-teal hem
    sc.quad(at(-A - 2, -B - 1, 17), v3(2 * A + 4, 0, 0), (v3(0, 2 * B + 4, 0)[0], v3(0, 2 * B + 4, 0)[1], -7),
            lambda u, w, lv, ix, iy: (PAINT_RED[2] if w > 0.93 else TEAL[2] if w > 0.86 else
                                      cord(lv) if (u * 8) % 1.0 < 0.07 and int(w * 30) % 3 == 0 else
                                      CANVAS[2] if (u * 8) % 1.0 < 0.07 or u < 0.02 or u > 0.98 else
                                      tone(CANVAS, lv, ix, iy, 0.1)))
    p = sc.pic()
    register("az.obj.stable", _art(finish(p, 20, 29, 19, 2.5), note="open stable: canvas lean-to on posts, hay, trough"))


def _stilt_lodge() -> None:
    """Bloodhoof's lodge by the lake: a log house up on stilts with a deck, a sloped grey-teal
    roof with crossed poles at the ridge ends, and a ladder down to the grass."""
    W, H = 56, 48
    sc = Scene(W, H, 0, 38)
    P = box_frame(0.22)
    cx, cy = 27.0, -4.0
    A, B, S, WH, R, O = 18.0, 6.5, 7.0, 10.0, 6.5, 1.6   # half length/depth, stilts, wall, ridge, overhang

    def at(a, b, z):
        return P(cx, cy, a, b, z)

    def vec(a, b, z):
        return P(0, 0, a, b, z)

    def slope(db, dz):
        d = vec(0, db, 0)
        return (d[0], d[1], dz)
    # stilts with cross braces
    for a in (-A + 1, -A / 3, A / 3, A - 1):
        for b in (-B + 1, B + 3):
            sc.rod(at(a, b, 0), at(a, b, S), 0.9, WOOD[1:])
    # deck: planks running across, a thick front beam
    sc.quad(at(-A, -B, S), vec(2 * A, 0, 0), vec(0, 2 * B + 4, 0),
            lambda u, w, lv, ix, iy: WOOD[2] if (u * 2 * A) % 3.5 < 1.0 else WOOD[4])
    sc.quad(at(-A, B + 4, S - 1.5), vec(2 * A, 0, 0), (0, 0, 1.5),
            lambda u, w, lv, ix, iy: WOOD[2] if w > 0.5 else WOOD[1])
    # log walls; the door on the long front wall
    def logs(u, w, lv, ix, iy):
        return WOOD[1] if (w * WH) % 2.5 < 1.0 else (WOOD[4] if lv > 0.5 else WOOD[3] if lv > 0.3 else WOOD[2])
    sc.quad(at(-A, B, S), vec(2 * A, 0, 0), (0, 0, WH - 1), lambda u, w, lv, ix, iy:
            (DEEP if abs(u - 0.4) < 0.06 and w < 0.72 else WOOD[5] if abs(u - 0.4) < 0.085 and w < 0.78
             else logs(u, w, lv, ix, iy)))
    sc.quad(at(A, B, S), vec(0, -2 * B, 0), (0, 0, WH - 1), logs)
    sc.quad(at(A, B, S + WH - 1), vec(0, -2 * B, 0), slope(-B, R),
            lambda u, w, lv, ix, iy: tone(WOOD[1:4], lv, ix, iy, 0.1), tri=True)
    # roof: two slopes of grey-teal shingles, darker rows, a lit ridge
    def roof(u, w, lv, ix, iy):
        if w > 0.95:
            return ROOF[4]
        return ROOF[1] if (w * 5) % 1.0 < 0.22 else tone(ROOF[2:], lv, ix, iy, 0.08)
    for side in (1, -1):
        sc.quad(at(-A - O, side * (B + O), S + WH - O * R / B), vec(2 * A + 2 * O, 0, 0),
                slope(-side * (B + O), R + O * R / B), roof)
    for a, sg in ((-A - O, -1), (A + O, 1)):
        top = S + WH + R
        sc.rod(at(a, 0, top - 1), at(a + sg * 2.5, -3, top + 4), 0.6, WOOD[1:])
        sc.rod(at(a, 0, top - 1), at(a + sg * 2.5, 3, top + 4), 0.6, WOOD[1:])
    # a ladder down to the grass
    for side in (-2.0, 2.0):
        sc.rod(at(-A * 0.25 + side, B + 4.6, S), at(-A * 0.25 + side, B + 9.5, 0), 0.5, WOOD[2:])
    for k in range(1, 4):
        t = k / 4
        sc.rod(at(-A * 0.25 - 2, B + 4.6 + 4.9 * t, S * (1 - t)), at(-A * 0.25 + 2, B + 4.6 + 4.9 * t, S * (1 - t)),
               0.4, WOOD[4:])
    p = sc.pic()
    register("az.obj.stilt_lodge", _art(finish(p, 28, 45, 25, 2.8),
             note="timber lodge on stilts by the lake: log walls, deck, grey-teal roof, ladder"))


def _buildings() -> None:
    _hut_large()
    _big_teepee()
    for v in range(3):
        _hut_small(v)
    for v in range(3):
        _tent(v)
    _inn()
    _stilt_lodge()
    _eagle_totem()


# --- totems ---------------------------------------------------------------------------------------

_FACE_LG = {"h": DRIFT[4], "H": DRIFT[5], "m": DRIFT[3], "d": DRIFT[1], "D": DRIFT[0], "o": CANVAS[5],
            "t": TEAL[3], "T": TEAL[1], "r": PAINT_RED[2], "R": PAINT_RED[1], "y": BONE[4], "Y": BONE[3]}
FACE_BEAR = [
    ".thhmmmdT.",
    "thmmmmmmdT",
    "hmookmookd",
    "hmmmhhmmmd",
    ".mmhHhmmd.",
    ".mrrrrrRd.",
    ".mrokokRd.",
    "..mmmmmd..",
    "...dddd...",
]
FACE_EAGLE = [
    "tthmmmmdTT",
    ".thmmmmdT.",
    "hmookmookd",
    "hmmmyymmmd",
    ".mmmyYmmd.",
    "..mmyYmd..",
    ".tthmYdTT.",
    "..hmmmmd..",
    "...dddd...",
]
FACE_WOLF = [
    "h........d",
    "hh......dd",
    "hmhhmmmmdd",
    "hmookookdd",
    ".mmmhmmmd.",
    "..mmhmmd..",
    "..mkkkkd..",
    "..mowowd..",
    "...dddd...",
]
TOTEM_TOPS = [
    [   # curved bull horns over a cap
        "y..............y",
        "Yy............yY",
        ".Yy..........yY.",
        "..YyyhhmmmmdyY..",
        "....hmmmmmmdd...",
        "....rrrrrrRR....",
    ],
    [   # eagle head on spread arms with teal tips
        "......hmmd......",
        ".....hokmmd.....",
        ".....hmmmyYY....",
        "......mmmd......",
        "......hmmd......",
        "tTthhmmmmmmddtTT",
        ".tthmmmmmmmmdTT.",
        "....rrrrrrRR....",
    ],
    [   # carved kodo head with sweeping horns and feather tufts
        "Yy............yY",
        ".Yy..........yY.",
        "..Yyy.hmmd.yyY..",
        "o...yhmmmmdy...o",
        "r...hookmokd...R",
        "r...hmmmmmmd...R",
        ".....mmhhmd.....",
        "......mmmd......",
    ],
]


def totem_mat(zones: Sequence[tuple[float, float, str]]) -> Callable:
    """Weathered pole: hexagon bands (teal and cream cells netted in red), painted rings, wood."""
    def mat(th, z, r, v, ix, iy):
        u = wrap(th - FRONT) * r
        for z0, z1, kind in zones:
            if z0 <= z < z1:
                red = PAINT_RED[2] if v > 0.4 else PAINT_RED[1]
                if kind == "hex":
                    i, j, e = hexcell(u + 1.0, z - z0 + 0.5, 2.3)
                    if e < 0.42 or z - z0 < 0.8 or z1 - z < 0.8:
                        return red
                    if (i + 2 * j) % 3 == 0:
                        return tone(CANVAS, v + 0.1, ix, iy, 0.1)
                    return TEAL[3] if v > 0.55 else TEAL[2] if v > 0.3 else TEAL[1]
                if kind == "red":
                    return red
                if kind == "teal":
                    return TEAL[3] if v > 0.5 else TEAL[1]
        grain = 0.06 if int(u * 1.5 + z * 0.15) % 3 == 0 else 0.0
        return tone(DRIFT[1:], v + grain, ix, iy, 0.12)
    return mat


def _totem(v: int) -> None:
    """VERY tall carved totems (about four tauren high): stacked faces between bands of hexagons."""
    W, H = 16, 72
    sc = Scene(W, H, 0, 68)
    zones = [
        [(3, 16, "hex"), (27, 38, "hex"), (49, 50.5, "red"), (51, 52, "teal")],
        [(3, 12, "hex"), (23, 24, "red"), (24.5, 25.5, "teal"), (35, 46, "hex")],
        [(3, 20, "hex"), (31, 44, "hex"), (55, 56, "red")],
    ][v]
    top = [55, 49, 57][v]
    sc.lathe(8.0, 0.0, [(0, 4.3), (3, 4.0), (top, 3.5), (top, 0)], totem_mat(zones))
    p = sc.pic()
    faces = [[(17, FACE_BEAR), (39, FACE_EAGLE)], [(13, FACE_WOLF), (26, FACE_BEAR)],
             [(21, FACE_EAGLE), (45, FACE_WOLF)]][v]
    for z, face in faces:
        p.stamp(face, _FACE_LG, 3, 68 - z - len(face))
    crest = TOTEM_TOPS[v]
    p.stamp(crest, _FACE_LG, 0, 68 - top - len(crest) + 2)
    # stones heaped around the foot
    p.stamp(["..abb.ab.abb..", ".abbcabbcabbc.", "abbccbbccbbccc"],
            {"a": STONE[4], "b": STONE[3], "c": STONE[1]}, 1, 67)
    register(f"az.obj.totem_pole@{v}", _art(finish(p, 8, 70.2, 7.5, 1.6),
             note=["very tall totem: bear and eagle faces, hexagon bands, bull horns",
                   "very tall totem: wolf and bear faces, eagle head on spread arms",
                   "very tall totem: eagle and wolf faces, kodo head with sweeping horns"][v]))


def eagle_wing(p: Pic, cx: int, side: int, tip_y: float, lit: bool, dy: int = 0) -> None:
    """One spread wing in screen space: carved coverts along the leading edge, a cream band,
    teal-striped flight feathers with dark tips, separate finger feathers at the end."""
    s0, span, d = cx + side * 4, 12, (0 if lit else -1)
    for i in range(span + 1):
        x = s0 + side * i
        t = i / span
        lead = 11 + (tip_y - 11) * t - math.sin(t * math.pi) * 3.0
        trail = 22 + (tip_y + 3 - 22) * t ** 0.7 - (1 if (i % 3 == 0 and 0.1 < t) else 0)
        if t > 0.7 and i % 2:
            lead += 2   # gaps between the finger feathers
        top = int(round(lead))
        for y in range(top, int(round(trail)) + 1):
            fy = (y - lead) / max(1.0, trail - lead)
            if y == top:
                c = DRIFT[5 + d]
            elif fy < 0.3 and t < 0.75:
                c = DRIFT[3 + d]
            elif fy < 0.5 and t < 0.75:
                c = CANVAS[4 + d]
            elif fy > 0.84:
                c = DRIFT[1] if t > 0.4 else PAINT_RED[2 + d]
            else:
                c = TEAL[3 + d] if i % 3 != 1 else CANVAS[3 + d]
            p.set(x, y + dy, c)


EAGLE = [
    "...cccC...",
    "..ccccCC..",
    "..ckcCkC..",
    "..cccbCC..",
    "...cbBC...",
    "..hmmBmd..",
    ".hmmmmmmd.",
    ".hmttTTmd.",
    ".hmrrRRmd.",
    ".hmttTTmd.",
    "..hmmmmd..",
    "..hmmmmd..",
    "...hmmd...",
    "..hmhmdd..",
    ".hmhmdmdd.",
    ".hh.mm.dd.",
    "..bb..BB..",
]


def _eagle_totem() -> None:
    """A carved pole on a round stone plinth, an eagle with spread wings on top (wings flap)."""
    W, H = 32, 56
    lg = {**_FACE_LG, "c": CANVAS[5], "C": CANVAS[3], "b": "gold2", "B": "gold1"}
    frames = []
    for fr in range(2):
        sc = Scene(W, H, 0, 51)
        sc.lathe(16.0, 0.0, [(0, 7.0), (2.6, 6.6), (2.6, 0)],
                 lambda th, z, r, v, ix, iy: STONE[1] if z < 2.5 and int(th * r / 3) % 4 == 0 else
                 tone(STONE[1:], v + (0.08 if r < 4 else 0), ix, iy, 0.15))
        sc.lathe(16.0, 0.0, [(2.5, 2.4), (30, 2.0), (30, 0)],
                 totem_mat([(7, 8, "red"), (8.5, 9.5, "teal"), (16, 24, "hex"), (28, 29, "red")]))
        p = sc.pic()
        tip = 2.0 if fr == 0 else 8.0
        eagle_wing(p, 15, -1, tip, True)
        eagle_wing(p, 16, 1, tip + 0.5, False)
        p.stamp(EAGLE, lg, 11, 5)
        frames.append(finish(p, 16, 52, 8, 2))
    register("az.obj.eagle_totem", _art(frames, fps=2, note="eagle totem: carved pole on a stone plinth, eagle with spread wings"))


# --- fire -----------------------------------------------------------------------------------------


def flames(p: Pic, cx: float, base: int, half: float, height: float, frame: int, frames: int,
           seed: int, sparks: int = 2) -> None:
    """Licking flames: a tapered profile eaten by noise that scrolls upward and loops over
    ``frames`` frames; dark red rim, orange body, yellow-white core."""
    nh = 24
    field = fbm(16, nh, seed, 2, 2)
    for y in range(max(0, int(base - height - 2)), base + 1):
        t = (base + 0.5 - y) / height
        for x in range(p.w):
            u = (x + 0.5 - cx) / half
            if abs(u) > 1.25:
                continue
            prof = (1 - min(1.0, abs(u)) ** 1.6) * max(0.0, 1 - t) ** 0.8
            n = field[(y + frame * nh // frames) % nh][int(x * 16 / p.w) % 16]
            f = prof * 1.35 - 0.1 + (n - 0.5) * 0.7 * (0.4 + t)
            if f > 0.72:
                c = FIRE[5] if t < 0.45 else FIRE[4]
            elif f > 0.5:
                c = FIRE[4]
            elif f > 0.3:
                c = FIRE[3]
            elif f > 0.12:
                c = FIRE[2]
            else:
                continue
            p.set(x, y, c)
    r = rng_for("sparks", seed, frame)
    for _ in range(sparks):
        x = int(cx + r.uniform(-half, half))
        y = int(base - height - r.uniform(0, 3))
        if p.get(x, y) is None:
            p.set(x, y, FIRE[4] if r.random() < 0.5 else FIRE[3])


def _bonfire() -> None:
    frames = []
    for fr in range(3):
        p = Pic(16, 16)
        # logs crossed under the fire, a ring of stones in front
        pole(p, 3, 13, 11, 10, WOOD, 3)
        pole(p, 4, 10, 12, 13, WOOD, 2)
        flames(p, 7.8, 12, 4.4, 9, fr, 3, 77)
        p.stamp([".ab..ab..ab..ab.", "abbcabbcabbcabbc", ".cc..cc..cc..cc."],
                {"a": STONE[4], "b": STONE[3], "c": STONE[1]}, 0, 12)
        p.set(7, 12, FIRE[3])
        p.set(9, 12, FIRE[2])
        p.outline(skip=FIRE[2:])
        p.shadow(8, 15, 8, 1.2)
        frames.append(p)
    register("az.obj.bonfire", _art(frames, fps=6, note="camp bonfire: crossed logs in a stone ring"))


# --- camp props -------------------------------------------------------------------------------------


def _drying_rack() -> None:
    p = Pic(24, 16)
    for x in (2, 20):  # A-frame legs
        pole(p, x, 15, x + 1, 2, WOOD, 3)
        pole(p, x + 2, 15, x + 1, 2, WOOD, 3)
    p.hline(1, 22, 3, WOOD[4])
    p.hline(1, 22, 4, WOOD[1])
    # a stretched hide on a hoop, and strips of meat
    p.rect(5, 5, 7, 8, lambda x, y: tone(HIDE[2:], 0.95 - (x - 5) * 0.09 - (y - 5) * 0.05, x, y, 0.3))
    p.stamp(["m.m.m.m", "......."], {"m": WOOD[2]}, 5, 5)
    for x in (14, 16, 18):
        h = 7 if x != 16 else 9
        p.vline(x, 5, 5 + h, RED[1])
        p.vline(x, 5, 5 + h // 2, RED[2])
        p.set(x, 5, BONE[3])
    p.outline()
    p.shadow(12, 15, 11, 1)
    register("az.obj.drying_rack", _art(p, note="rack with a stretched hide and drying meat strips"))


def _kodo_pen() -> None:
    p = Pic(32, 24)
    for ry in (8, 13, 18):  # three log rails
        for x in range(1, 31):
            p.set(x, ry, WOOD[4] if bayer(x, ry) < 0.8 else WOOD[3])
            p.set(x, ry + 1, WOOD[2])
            p.set(x, ry + 2, WOOD[1] if (x * 7) % 5 else WOOD[2])
    for px_ in (2, 15, 28):  # sharpened posts lashed with rope
        for y in range(3, 23):
            p.set(px_, y, WOOD[3])
            p.set(px_ + 1, y, WOOD[1])
        p.set(px_, 2, WOOD[4])
        for ry in (8, 13, 18):
            p.set(px_ - 1, ry + 1, SAND[3])
            p.set(px_, ry + 1, SAND[4])
            p.set(px_ + 1, ry + 1, SAND[2])
            p.set(px_ + 2, ry + 1, SAND[2])
    # horns lashed to the middle post
    p.stamp(["t.....t", "tT...Tt", ".TBBBT.", "..BkB..", "...B..."],
            {"t": BONE[4], "T": BONE[3], "B": BONE[3]}, 13, 0)
    for x in (5, 9, 21, 25):  # tufts of grass at the base
        p.stamp([".g.", "gGg"], {"g": LEAF[4], "G": LEAF[3]}, x, 21)
    p.outline()
    p.shadow(16, 23, 16, 1)
    register("az.obj.kodo_pen", _art(p, note="kodo corral fence: log rails lashed to posts, horn trophy"))


def _well() -> None:
    p = Pic(16, 24)
    # posts and a little hide roof
    for x in (2, 13):
        p.vline(x, 3, 15, WOOD[3] if x == 2 else WOOD[2])
        p.vline(x + (1 if x == 2 else -1), 4, 15, WOOD[1])
    p.poly([(7.5, -0.2), (0.5, 5), (15.5, 5)], lambda x, y: tone(HIDE[1:5], 0.95 - x * 0.05, x, y, 0.2))
    p.hline(1, 14, 5, HIDE[1])
    p.hline(3, 12, 7, WOOD[4])  # windlass
    p.hline(3, 12, 8, WOOD[2])
    p.vline(8, 9, 10, SAND[3])
    p.stamp(["kaak", "abbc", "abbc"], {"a": WOOD[4], "b": WOOD[3], "c": WOOD[1]}, 6, 10)
    # stone ring
    for y in range(14, 23):
        for x in range(1, 15):
            c = cyl(STONE[1:], x, 1, 14, y)
            if (y - 14) % 3 == 0 or (x + (y - 14) // 3 * 2) % 5 == 0:
                c = step(STONE, c, -1)
            p.set(x, y, c)
    p.ellipse(8, 14.5, 7, 2.5, lambda x, y: STONE[4] if y < 14 else STONE[3])
    p.ellipse(8, 14.5, 5, 1.5, lambda x, y: WATER[1] if x > 5 else WATER[2])
    p.set(5, 14, WATER[4])
    p.outline()
    p.shadow(8, 23, 8, 1)
    register("az.obj.well", _art(p, note="stone well with a hide roof, windlass and bucket"))


HORDE = [
    "K.KK.K",
    "KKKKKK",
    ".KKKK.",
    "..KK..",
    ".KKKK.",
    "K.KK.K",
]


def _banner() -> None:
    frames = []
    for fr in range(2):
        p = Pic(16, 32)
        cloth = Pic(10, 22)
        for y in range(22):
            for x in range(10):
                notch = y - 17 > (4 - abs(x - 4.5)) if y >= 17 else False
                if notch:
                    continue
                cloth.set(x, y, RED[2] if x < 7 else RED[1])
                if x == 0 or y == 0:
                    cloth.set(x, y, RED[3])
        cloth.hline(0, 9, 2, "gold1")
        cloth.stamp(HORDE, {}, 2, 7)
        for y in range(22):  # the cloth waves: rows swing more toward the free end
            ph = y * 0.45 + fr * math.pi
            dx = round(math.sin(ph) * y / 14)
            fold = math.cos(ph)
            for x in range(10):
                c = cloth.get(x, y)
                if c in RED:
                    c = step(RED, c, 1 if fold > 0.6 else (-1 if fold < -0.6 else 0))
                p.set(4 + x + dx, 5 + y, c)
        p.vline(2, 2, 31, WOOD[3])
        p.vline(3, 2, 31, WOOD[1])
        p.hline(2, 14, 4, WOOD[4])
        p.hline(3, 14, 5, WOOD[2])
        p.stamp([".t.", "tTt", ".T."], {"t": BONE[4], "T": BONE[3]}, 1, 0)
        p.outline()
        p.shadow(3, 31, 3, 1)
        frames.append(p)
    register("az.obj.banner", _art(frames, fps=2, note="Horde war banner on a crossbar pole, waving"))


def _anvil() -> None:
    p = Pic(16, 16)
    p.stamp([
        "..............",
        ".aaaaaaaaaaa..",
        "abbbbbbbbbbbc.",
        ".cccbbbbbcccc.",
        "....cbbbbc....",
        "....cbbbc.....",
        "...abbbbbcc...",
        "..cccccccccc..",
        "...dffffffe...",
        "...dffgfffe...",
        "...dfffffge...",
        "...ddfffeee...",
    ], {"a": STEEL[4], "b": STEEL[3], "c": STEEL[1], "d": WOOD[4], "f": WOOD[3], "g": WOOD[2],
        "e": WOOD[1]}, 1, 3)
    p.set(2, 4, STEEL[5])
    p.outline()
    p.shadow(8, 15, 6, 1)
    register("az.obj.anvil", _art(p, note="blacksmith anvil on a stump"))


def _stone_blocks(p: Pic, x0: int, y0: int, x1: int, y1: int, lit: float = 0.9) -> None:
    for y in range(y0, y1 + 1):
        row = (y - y0) // 3
        for x in range(x0, x1 + 1):
            joint = (y - y0) % 3 == 2 or (x - x0 + row * 3) % 6 == 5
            v = lit - (x - x0) / max(1, x1 - x0) * 0.5 - (0.12 if joint else 0)
            p.set(x, y, tone(STONE[1:], v, x, y, 0.15) if not joint else STONE[1])


def _forge() -> None:
    frames = []
    for fr in range(3):
        p = Pic(24, 24)
        flames(p, 10.5, 10, 5.5, 8, fr, 3, 31, sparks=3)
        _stone_blocks(p, 2, 10, 19, 22)
        p.hline(1, 20, 10, STONE[4])
        p.hline(3, 18, 11, FIRE[1])  # the coal bed
        for x in range(4, 18):
            p.set(x, 11, FIRE[3] if (x + fr) % 3 == 0 else FIRE[2])
        # stoke hole with glowing coals
        door_arch(p, 7, 14, 15, 21)
        for x in range(8, 14):
            p.set(x, 20, FIRE[4] if (x + fr) % 2 else FIRE[3])
            p.set(x, 21, FIRE[2])
            if (x * 3 + fr) % 4 == 0:
                p.set(x, 19, FIRE[3])
        # hide bellows on the right
        p.poly([(19, 13), (23, 15), (23, 19), (19, 18)], lambda x, y: tone(HIDE[1:5], 0.7 - (y - 13) * 0.08, x, y))
        p.hline(19, 23, 16 + (fr % 2), HIDE[1])
        p.line(22, 14, 23, 11, WOOD[3])
        p.outline(skip=FIRE[2:3])
        p.shadow(12, 23, 12, 1)
        frames.append(p)
    register("az.obj.forge", _art(frames, fps=6, note="stone forge, glowing coals, hide bellows"))


def _training_dummy() -> None:
    p = Pic(16, 24)
    p.vline(7, 14, 23, WOOD[3])
    p.vline(8, 14, 23, WOOD[1])
    p.hline(1, 14, 9, WOOD[4])
    p.hline(1, 14, 10, WOOD[2])
    p.ellipse(7.8, 13, 4.2, 5.5, lambda x, y: tone(SAND[1:], 0.95 - (x - 4) * 0.08 - (y - 8) * 0.03, x, y, 0.3))
    p.ellipse(7.8, 4.5, 3, 3.2, lambda x, y: tone(HIDE[1:5], 0.95 - (x - 5) * 0.12 - (y - 2) * 0.05, x, y, 0.2))
    p.hline(5, 10, 7, SAND[1])  # neck rope
    p.hline(4, 11, 16, SAND[1])  # waist rope
    # painted target on the chest
    p.ellipse(8, 12.5, 2.5, 2.5, RED[2])
    p.ellipse(8, 12.5, 1.5, 1.5, BONE[4])
    p.set(7, 12, RED[3])
    # a stuck arrow
    p.line(9, 13, 13, 11, WOOD[4])
    p.stamp(["rw", "r."], {"r": RED[2]}, 13, 10)
    p.set(4, 4, "ink")
    p.set(6, 4, "ink")
    p.outline()
    p.shadow(8, 23, 5, 1)
    register("az.obj.training_dummy", _art(p, note="straw training dummy with a painted target"))


def _barrel(v: int) -> None:
    p = Pic(16, 16)
    x0, x1 = 3, 12
    for y in range(3, 15):
        bulge = 1 if 5 <= y <= 12 else 0
        for x in range(x0 - bulge, x1 + 1 + bulge):
            c = cyl(WOOD[1:], x, x0 - 1, x1 + 1, y)
            if (x - x0) % 3 == 2:
                c = step(WOOD, c, -1)
            p.set(x, y, c)
    for hy in (4, 8, 13):
        for x in range(x0 - 1, x1 + 2):
            if p.get(x, hy):
                p.set(x, hy, STEEL[3] if x < 8 else STEEL[1])
    p.ellipse(8, 3, 5, 1.8, WOOD[4] if v == 0 else WOOD[3])
    if v == 0:
        p.hline(5, 10, 3, WOOD[3])
    else:  # open water barrel with a gourd dipper
        p.ellipse(8, 3, 3.8, 1.2, lambda x, y: WATER[3] if x > 5 else WATER[4])
        p.set(6, 2, WATER[5])
        p.line(10, 3, 13, 0, SAND[3])
        p.stamp(["gG", "GG"], {"g": SAND[4], "G": SAND[2]}, 12, 0)
    p.outline()
    p.shadow(8, 15, 6.5, 1)
    register(f"az.obj.barrel@{v}", _art(p, note=["hooped barrel", "water barrel with a gourd dipper"][v]))


def _crate(v: int) -> None:
    p = Pic(16, 16)
    # 3/4 view: lit top face, front face of planks
    p.rect(2, 3, 12, 3, lambda x, y: WOOD[5] if y == 3 else WOOD[4])
    for y in range(6, 15):
        for x in range(2, 14):
            c = WOOD[3] if x < 11 else WOOD[2]
            if (y - 6) % 3 == 2:
                c = WOOD[1]
            p.set(x, y, c)
    p.vline(2, 6, 14, WOOD[4])
    p.vline(13, 3, 14, WOOD[1])
    if v == 0:
        p.line(3, 7, 12, 13, WOOD[4])
        p.line(3, 8, 12, 14, WOOD[2])
    else:  # open crate of corn and melons, rope-lashed
        p.rect(3, 3, 10, 3, WOOD[0])
        p.stamp(["yYy.gGg.", "yYyggGGg", ".yYgGGg."], {"y": "gold2", "Y": "gold1", "g": LEAF[4], "G": LEAF[3]}, 4, 2)
        p.vline(8, 6, 14, SAND[3])
        p.hline(2, 13, 10, SAND[3])
        p.set(8, 10, SAND[4])
    p.outline()
    p.shadow(8, 15, 7, 1)
    register(f"az.obj.crate@{v}", _art(p, note=["plank crate", "open crate of corn and melons"][v]))


def _camp() -> None:
    _bonfire()
    for v in range(3):
        _totem(v)
    _drying_rack()
    _kodo_pen()
    _well()
    _banner()
    _anvil()
    _forge()
    _stable()
    _training_dummy()
    for v in range(2):
        _barrel(v)
        _crate(v)



# --- rock ----------------------------------------------------------------------------------------


def rock(p: Pic, test: Callable[[float, float], bool], ramp: Sequence[str], seed: int, strata: int = 0,
         cells: int = 3, lit: float = 0.55, skew: float = 0.3) -> set[tuple[int, int]]:
    """Fill a mask with rock: embossed noise lit from the top-left, lit upper/left rims,
    shadowed lower/right rims, optional wavy sedimentary strata (Mulgore's mesas)."""
    n = fbm(p.w, p.h, seed, 3, cells)
    pts = {(x, y) for y in range(p.h) for x in range(p.w) if test(x + 0.5, y + 0.5)}
    for x, y in pts:
        x2, y2 = min(p.w - 1, x + 1), min(p.h - 1, y + 1)
        v = lit + (n[y][x] - n[y2][x2]) * 3.0 - (x / p.w - 0.5) * skew
        if (x, y - 1) not in pts or (x - 1, y) not in pts:
            v += 0.3
        elif (x + 1, y) not in pts or (x, y + 1) not in pts:
            v -= 0.2
        if strata and (y + int(n[y][x] * 3)) % strata == 0:
            v -= 0.28
        elif strata and (y + int(n[y][x] * 3)) % strata == 1:
            v += 0.1
        p.px[y][x] = tone(ramp, v, x, y, 0.12)
    return pts


def tufts(p: Pic, pts: Iterable[tuple[int, int]], seed: int, density: float = 0.35) -> None:
    """Grass growing on the upper rims of a mass."""
    r = rng_for("tufts", seed)
    pts = set(pts)
    for x, y in sorted(pts):
        if (x, y - 1) not in pts and r.random() < density:
            p.set(x, y, LEAF[3])
            if r.random() < 0.6:
                p.set(x, y - 1, LEAF[4])


def _rock_arch() -> None:
    W, H = 48, 40
    p = Pic(W, H)
    wob = fbm(48, 1, 91, 2, 4)[0]

    def mass(x, y):
        top = 5 + abs(x - 22) ** 1.6 * 0.045 + wob[int(x) % 48] * 4
        if x < 2 or x > 45.5:
            return False
        if x < 6:
            top = max(top, 16 + (6 - x) * 3)
        if x > 42:
            top = max(top, 14 + (x - 42) * 4)
        return y >= top

    def opening(x, y):
        return ((x - 24.5) / 8.5) ** 2 + ((y - 39.5) / 21) ** 2 <= 1

    pts = rock(p, lambda x, y: mass(x, y) and not opening(x, y), MESA[1:], 92, strata=5)
    # the cave mouth: deep shadow, the far wall faintly lit
    for y in range(H):
        for x in range(W):
            if mass(x + 0.5, y + 0.5) and opening(x + 0.5, y + 0.5):
                d = ((x + 0.5 - 24.5) / 8.5) ** 2 + ((y + 0.5 - 39.5) / 21) ** 2
                c = DEEP if d < 0.75 or y > 35 else "ink"
                if y > 34 and d < 0.5:
                    c = MESA[0] if bayer(x, y) < (y - 34) / 6 else DEEP
                p.set(x, y, c)
    tufts(p, pts, 93)
    # gnoll bones by the mouth: the Palemane mark
    p.stamp(["t.T", ".t.", "T.t"], {"t": BONE[4], "T": BONE[2]}, 12, 35)
    p.outline()
    p.shadow(24, 39, 24, 1.3)
    register("az.obj.rock_arch", _art(p, note="Palemane Rock: red mesa arch over the gnolls' cave"))


def distance_field(mask: set[tuple[int, int]], w: int, h: int) -> list[list[float]]:
    """Chamfer distance from every masked pixel to the nearest unmasked one."""
    inf = 1e9
    d = [[inf if (x, y) in mask else 0.0 for x in range(w)] for y in range(h)]
    for y in range(h):
        for x in range(w):
            if d[y][x]:
                for dx, dy, c in ((-1, 0, 1), (0, -1, 1), (-1, -1, 1.41), (1, -1, 1.41)):
                    nx, ny = x + dx, y + dy
                    d[y][x] = min(d[y][x], (d[ny][nx] if 0 <= nx < w and 0 <= ny < h else 0.0) + c)
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            if d[y][x]:
                for dx, dy, c in ((1, 0, 1), (0, 1, 1), (1, 1, 1.41), (-1, 1, 1.41)):
                    nx, ny = x + dx, y + dy
                    d[y][x] = min(d[y][x], (d[ny][nx] if 0 <= nx < w and 0 <= ny < h else 0.0) + c)
    return d


def crag(p: Pic, pts: Sequence[tuple[float, float]], ramp: Sequence[str], seed: int, lit: float = 0.5,
         strata: int = 0, relief: float = 1.0, open_bottom: bool = True) -> set[tuple[int, int]]:
    """A faceted mountain mass: the inside distance to the silhouette is a ridge height map,
    so every crag gets lit left/upper faces, shadowed right faces and a crisp ridge line,
    with the same values whichever side of the picture it stands on."""
    mask = {(x, y) for y in range(p.h) for x in range(p.w) if _in_poly(x + 0.5, y + 0.5, pts)}
    if open_bottom:  # the mass continues below the picture: no edge along the bottom row
        mask_ext = mask | {(x, p.h + k) for x in range(p.w) for k in range(8) if (x, p.h - 1) in mask}
        d = distance_field(mask_ext, p.w, p.h + 8)
    else:
        d = distance_field(mask, p.w, p.h)
    n = fbm(p.w, p.h + 8, seed, 3, 3)
    hgt = [[(d[y][x] ** 0.75) * 0.7 * relief + n[y][x] * 2 for x in range(p.w)] for y in range(len(d))]
    for x, y in mask:
        gx = hgt[y][min(p.w - 1, x + 1)] - hgt[y][max(0, x - 1)]
        gy = hgt[y + 1][x] - hgt[max(0, y - 1)][x]
        v = lambert(-gx, -gy, 2.0)
        v = lit + (v - 0.6) * 1.3 - (y / p.h) * 0.1
        if strata and (y + int(n[y][x] * 4)) % strata == 0:
            v -= 0.2
        p.px[y][x] = tone(ramp, v, x, y, 0.14)
    return mask


def _stonetalon_pass() -> None:
    W, H = 48, 32
    p = Pic(W, H)
    far = [(15, 32), (19, 11), (23, 7), (27, 9), (31, 13), (34, 32)]
    left = [(0.5, 32), (0.5, 14), (4, 7), (9, 2), (13, 4), (17, 10), (21, 17), (23, 24), (22, 32)]
    right = [(26, 32), (26, 23), (29, 15), (33, 8), (38, 4), (42, 6), (47.5, 14), (47.5, 32)]
    crag(p, far, STONE[0:4], 17, lit=0.35, relief=0.6)
    lpts = crag(p, left, STONE[0:5], 18, lit=0.55, strata=5)
    rpts = crag(p, right, STONE[0:5], 19, lit=0.55, strata=5)
    # the trail: a worn dirt band winding up into the notch, darker as it recedes
    for y in range(12, H):
        t = (y - 12) / (H - 13)
        cx = 24.5 + math.sin(t * math.pi * 1.3) * 2.5
        half = 0.8 + t * 4.2
        for x in range(W):
            e = abs(x + 0.5 - cx) / half
            if e > 1:
                continue
            v = 0.25 + t * 0.45 + (0.12 if x + 0.5 < cx else 0) - (0.3 if e > 0.75 else 0)
            p.set(x, y, tone(MESA[1:5], v, x, y, 0.1))
    for x, y in ((22, 28), (26, 25), (21, 22), (27, 30), (24, 18)):
        p.set(x, y, STONE[3])
        p.set(x + 1, y, STONE[2])
    # scree and grass at the feet of the crags
    for (x, y) in sorted(lpts | rpts):
        if y >= 27 and (x * 7 + y * 3) % 17 == 0:
            p.set(x, y, LEAF[3])
            p.set(x, y - 1, LEAF[4])
    tufts(p, {xy for xy in lpts | rpts if xy[1] < 26}, 20, 0.2)
    # the painted rock where the path tops out: a red Grimtotem hand
    p.stamp(["r.r.r", "rrrrr", ".rrr.", ".rr.."], {"r": RED[2]}, 7, 17)
    p.outline()
    p.shadow(24, 31.5, 24, 1)
    register("az.obj.stonetalon_pass", _art(p, note="the trail into the Stonetalon mountains, painted rock"))


def _harpy_nest() -> None:
    W, H = 24, 24
    p = Pic(W, H)
    pillar = [(4, 23.9), (6, 14), (8, 11), (17, 11), (19, 15), (21, 23.9)]
    rock(p, lambda x, y: _in_poly(x, y, pillar), MESA[1:], 44, strata=4)
    r = rng_for("nest")
    p.ellipse(12, 10, 10, 3.6, lambda x, y: tone(WOOD[1:], 0.7 - (y - 7) * 0.12, x, y, 0.3))
    for _ in range(26):  # woven twigs
        x = r.randint(3, 20)
        y = r.randint(8, 12)
        ln = r.randint(2, 4)
        c = r.choice([WOOD[4], WOOD[3], SAND[3], SAND[4], WOOD[2]])
        p.line(x, y, x + ln, y + r.choice((-1, 0, 1)), c)
    p.ellipse(12, 8.3, 6, 1.4, WOOD[0])
    p.stamp(["ab.ab", "bc.bc"], {"a": BONE[4], "b": BONE[3], "c": BONE[2]}, 9, 6)
    # bright feathers stuck in the rim (Windfury plumes are prized)
    for fx, fy, c in ((3, 6, RED[2]), (5, 5, BLUE[3]), (19, 5, RED[3]), (21, 7, BLUE[2]), (15, 4, "gold2")):
        p.vline(fx, fy, fy + 2, c)
        p.set(fx, fy + 3, BONE[3])
    p.outline()
    p.shadow(12, 23.5, 10, 1)
    register("az.obj.harpy_nest", _art(p, note="Windfury harpy nest on a rock spire, eggs and plumes"))


def _kodo_bones() -> None:
    W, H = 32, 16
    p = Pic(W, H)
    p.ellipse(17, 15.5, 15, 3, lambda x, y: tone(MESA[2:5], 0.7 - (y - 13) * 0.2, x, y, 0.2))
    # ribs arching up from the buried spine
    for i, rx_ in enumerate(range(13, 30, 4)):
        top = 4 + abs(i - 1.5)
        for y in range(int(top), 15):
            t = (y - top) / (15 - top)
            x = rx_ + round(math.sin(t * math.pi * 0.9) * 2.4)
            p.set(x, y, BONE[4] if t < 0.4 else BONE[3])
            p.set(x + 1, y, BONE[2])
    p.hline(12, 29, 5, BONE[3])
    for x in range(12, 30, 2):
        p.set(x, 4, BONE[4])
    # the great skull, horn curling up, half sunk in the earth
    p.stamp([
        "..tt.........",
        ".t...........",
        "t....ABBBB...",
        "t...ABBBBBBc.",
        ".tAABBKKBBBBc",
        "..ABBBKKBBBBc",
        "..ABBBBBBBBc.",
        "...ABBBBBBc..",
        "...ABBBBBc...",
        "....ABBcKc...",
        "....AccKK....",
    ], {"t": BONE[4], "A": BONE[4], "B": BONE[3], "c": BONE[2]}, 0, 3)
    p.outline()
    register("az.obj.kodo_bones", _art(p, note="Kodo Rock: bleached giant skull and ribs half buried"))


# --- the Great Gate --------------------------------------------------------------------------------


def _log_wall(p: Pic, x0: int, y0: int, x1: int, y1: int, vertical: bool, dark: float = 0.0) -> None:
    """Stacked logs: each 3px, lit edge / body / shadow, with end-grain notches."""
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            k = (x - x0) % 3 if vertical else (y - y0) % 3
            c = [WOOD[4], WOOD[3], WOOD[1]][k]
            if dark:
                c = step(WOOD, c, -1) if (x - x0) / max(1, x1 - x0) > 1 - dark else c
            p.set(x, y, c)


# --- Venture Co. ------------------------------------------------------------------------------------


def _hazard(p: Pic, x0: int, y0: int, w: int, h: int) -> None:
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            p.set(x, y, "hazard" if (x + y) % 4 < 2 else "hazard_dark")


def _mine_entrance() -> None:
    W, H = 48, 40
    p = Pic(W, H)
    wob = fbm(48, 1, 55, 2, 4)[0]

    def hill(x, y):
        top = 4 + abs(x - 24) ** 2 * 0.028 + wob[int(x) % 48] * 3
        return 0.5 < x < 47.5 and y >= top

    pts = rock(p, hill, MESA[1:], 56, strata=5)
    tufts(p, pts, 57)
    # tunnel mouth
    for y in range(14, 40):
        for x in range(16, 32):
            p.set(x, y, DEEP if y < 34 or abs(x - 23.5) > 5 else ("ink" if (x + y) % 2 else DEEP))
    # rails running out of the dark
    for y in range(30, 40):
        k = (y - 30) / 9
        lx, rx_ = round(21 - k * 2), round(26 + k * 2)
        if y % 2 == 0:
            p.hline(lx - 1, rx_ + 1, y, WOOD[2])
        p.set(lx, y, STEEL[4])
        p.set(rx_, y, STEEL[4])
    # timber frame: posts, lintel, knee braces
    for x in (14, 32):
        p.vline(x, 13, 39, WOOD[4])
        p.vline(x + 1, 13, 39, WOOD[2])
    p.rect(12, 11, 24, 3, lambda x, y: [WOOD[4], WOOD[3], WOOD[1]][y - 11])
    p.line(16, 14, 18, 16, WOOD[3])
    p.line(31, 14, 29, 16, WOOD[2])
    # the Venture Co. sign: a riveted rust plate with hazard stripes
    p.rect(17, 5, 14, 6, lambda x, y: RUST[3] if x < 28 else RUST[2])
    p.hline(17, 30, 5, RUST[4])
    _hazard(p, 18, 8, 12, 2)
    for x in (18, 29):
        p.set(x, 6, STEEL[5])
    p.hline(20, 27, 6, RUST[1])  # stencilled lettering, worn
    for x in range(20, 28, 2):
        p.set(x, 7, RUST[1])
    # a lantern on the left post
    p.stamp(["s.", "ly", "ss"], {"s": STEEL[2], "l": "fire4", "y": "fire3"}, 12, 17)
    p.outline()
    p.shadow(24, 39.5, 24, 1)
    register("az.obj.mine_entrance", _art(p, note="Venture Co. mine: timber-framed shaft in the mesa, rails"))


def _metal_panels(p: Pic, x0: int, y0: int, x1: int, y1: int, seed: int) -> None:
    r = rng_for("panels", seed)
    x = x0
    while x <= x1:
        w = r.randint(4, 7)
        ramp = r.choice([RUST[1:], RUST[1:], STEEL[1:5]])
        for xx in range(x, min(x1, x + w - 1) + 1):
            for y in range(y0, y1 + 1):
                k = (xx - x0) % 2
                v = 0.75 - (xx - x0) / max(1, x1 - x0) * 0.35 - k * 0.15
                p.set(xx, y, tone(ramp, v, xx, y, 0.2))
        p.vline(min(x1, x + w - 1), y0, y1, "ink2")
        for y in range(y0 + 1, y1, 5):
            p.set(x + 1, y, STEEL[5])
        x += w


def _goblin_shack() -> None:
    W, H = 32, 28
    p = Pic(W, H)
    # stove pipe with a puff of smoke
    p.vline(23, 1, 9, STEEL[4])
    p.vline(24, 1, 9, STEEL[2])
    p.hline(22, 25, 1, STEEL[3])
    p.stamp([".aa.", "aAAa"], {"a": "grey3:120", "A": "grey4:140"}, 21, 0)
    _metal_panels(p, 3, 11, 26, 26, 7)
    # corrugated roof sloping right
    for x in range(1, 31):
        top = 5 + (x - 1) * 5 // 29
        for y in range(top, top + 4):
            c = RUST[4] if y == top else (RUST[3] if x % 2 else RUST[2])
            if y == top + 3:
                c = RUST[1]
            p.set(x, y, c)
    # plank door and a lit window
    p.rect(7, 16, 6, 11, lambda x, y: WOOD[3] if (x - 7) % 2 == 0 else WOOD[2])
    p.hline(7, 12, 19, WOOD[1])
    p.hline(7, 12, 24, WOOD[1])
    p.set(11, 21, "gold2")
    p.rect(17, 15, 6, 4, "win_warm")
    p.vline(19, 15, 18, STEEL[1])
    p.hline(17, 22, 16, STEEL[1])
    p.rect(16, 14, 8, 1, STEEL[3])
    p.rect(16, 19, 8, 1, STEEL[1])
    # an oil barrel by the wall
    for y in range(20, 27):
        for x in range(26, 31):
            p.set(x, y, cyl(RUST[1:], x, 26, 30, y) if y not in (22, 25) else STEEL[2])
    p.hline(26, 30, 20, RUST[4])
    p.outline(skip=("grey3:120", "grey4:140"))
    p.shadow(16, 27, 16, 1)
    register("az.obj.goblin_shack", _art(p, note="goblin worker shack: patched rusty sheet metal, stove pipe"))


def _ore_cart() -> None:
    W, H = 24, 16
    p = Pic(W, H)
    p.hline(0, 23, 14, STEEL[4])
    p.hline(0, 23, 15, STEEL[1])
    for x in range(1, 24, 4):
        p.set(x, 15, WOOD[2])
    r = rng_for("ore")
    for _ in range(40):  # heaped ore
        x = r.randint(5, 18)
        y = r.randint(2, 5)
        if y >= 5 - (2 - abs(x - 11.5) / 5):
            p.set(x, y, r.choice([STONE[3], STONE[2], "ore1", "ore2", STONE[4]]))
    p.poly([(3, 5), (21, 5), (19, 12.5), (5, 12.5)],
           lambda x, y: tone(RUST[1:], 0.85 - (x - 3) * 0.03 - (y - 5) * 0.04, x, y, 0.15))
    p.hline(3, 20, 5, RUST[4])
    p.hline(4, 19, 8, STEEL[3])
    for x in (5, 11, 18):
        p.set(x, 7, STEEL[5])
    for wx in (7, 16):
        p.ellipse(wx + 0.5, 12.5, 2, 2, lambda x, y, wx=wx: STEEL[3] if x + y < wx + 13 else STEEL[1])
        p.set(wx, 12, STEEL[5])
    p.outline()
    register("az.obj.ore_cart", _art(p, note="Venture Co. mine cart heaped with ore, on rails"))


# --- quilboar -------------------------------------------------------------------------------------


def brambles(p: Pic, test: Callable[[int, int], bool], seed: int, n: int, shade: Callable[[int, int], float],
             thorn_rate: float = 0.25) -> None:
    """Tangled briar vines over a mask, lit per pixel by ``shade``; thorns stick out."""
    r = rng_for("briar", seed)
    for _ in range(n):
        x, y = r.uniform(0, p.w), r.uniform(0, p.h)
        a = r.uniform(0, math.tau)
        for _i in range(r.randint(5, 11)):
            xi, yi = int(x), int(y)
            if test(xi, yi):
                v = shade(xi, yi)
                p.set(xi, yi, tone(BRIER[1:], v + 0.2, xi, yi, 0.1))
                if r.random() < thorn_rate:
                    tx, ty = xi + r.choice((-1, 1)), yi - 1
                    p.set(tx, ty, BONE[3] if v > 0.45 else BONE[2])
            a += r.uniform(-0.6, 0.6)
            x += math.cos(a)
            y += math.sin(a)


def _thorn_hut(v: int) -> None:
    """A quilboar hut: courses of thick bramble woven over bent stakes like a basket, long pale
    thorns along the courses and the rim, stretched hides lashed over the top."""
    W, H = 32, 32
    p = Pic(W, H)
    cx, base, rx, ry = 16.0, 30.0, 13.5, 19.0 if v == 0 else 16.5
    stakes = (-0.66, -0.33, 0.0, 0.33, 0.66)
    info = {}
    for y in range(H):
        for x in range(W):
            nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - base) / ry
            if ny > 0 or nx * nx + ny * ny > 1:
                continue
            nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
            lv = (lambert(nx, ny, nz + 0.1) + 0.25) / 1.25
            hw = math.sqrt(max(1e-6, 1 - ny * ny))
            u = nx / hw
            course = (int(base) - y) // 3
            r = (int(base) - y) % 3              # 2 = lit top of a course, 0 = its shadowed underside
            seg = sum(1 for s_ in stakes if u > s_)
            over = (course + seg) % 2 == 0      # the bramble passes over / under each stake
            lvl = lv * 3.2 + (0.9 if r == 2 else (-1.0 if r == 0 else 0)) + (0.5 if over else -0.6)
            near = min(abs(u - s_) * hw * rx for s_ in stakes)
            if near < 0.6:                      # a stake shows where the bramble dips under it
                lvl = lv * 3.2 + (0.3 if u * hw * rx < 0 else -0.4)
                c = WOOD[max(1, min(4, int(round(lvl))))]
            else:
                c = BRIER[max(0, min(4, int(round(lvl))))]
            p.px[y][x] = c
            info[(x, y)] = (u, ny, lv, course, r, over)
    # thorns: regular pale spikes on the lit crest of the "over" runs
    for (x, y), (u, ny, lv, course, r, over) in sorted(info.items()):
        if r == 2 and over and (x * 5 + course * 3) % 7 == 0 and (x, y - 1) in info:
            p.set(x - (1 if u < 0 else -1), y - 1, BONE[3] if lv > 0.5 else BONE[2])
    # the rim bristles with long thorns pointing outward
    rim = [xy for xy in sorted(info) if (xy[0], xy[1] - 1) not in info]
    for i, (x, y) in enumerate(rim):
        if i % 3 == 1 and y < base - 3:
            dx = -1 if x < cx - 2 else (1 if x > cx + 2 else 0)
            p.set(x + dx, y - 1, BRIER[3])
            p.set(x + 2 * dx, y - 2, BONE[3])
    # stretched hides lashed on: a cap over the top (v0) or a big flank panel (v1)
    def hide_panel(test, ramp):
        for (x, y), (u, ny, lv, *_rest) in info.items():
            if test(u, ny):
                p.set(x, y, tone(ramp, lv + 0.05, x, y, 0.1))
        for (x, y), (u, ny, lv, *_rest) in info.items():
            if test(u, ny) and not test(*info.get((x, y + 1), (9, 9))[:2]) and x % 2 == 0:
                p.set(x, y, "ink2")  # lacing along the lower edge
    if v == 0:
        hide_panel(lambda u, ny: ny < -0.72 + 0.12 * math.cos(u * 6), HIDE[1:5])
        hide_panel(lambda u, ny: 0.35 < u < 0.8 and -0.55 < ny < -0.3, SAND[1:4])
    else:
        hide_panel(lambda u, ny: -0.85 < u < -0.3 and -0.75 < ny < -0.3, HIDE[1:5])
        hide_panel(lambda u, ny: ny < -0.85, SAND[1:4])
    door_arch(p, 12, 19, 20 if v == 0 else 21, 29)
    tusk_pair(p, 11, 20, 29, 8)
    if v == 1:  # a boar skull over the doorway
        p.stamp([".abbba.", "abkbkba", ".abbba.", "t.bbb.t", "t..c..t"],
                {"a": BONE[3], "b": BONE[4], "c": BONE[2], "t": BONE[4]}, 12, 14)
    for x in range(3, 29):  # trodden earth at the hem
        if p.get(x, 29) is not None:
            p.set(x, 30, MESA[2] if x < 16 else MESA[1])
    p.outline(skip=())
    p.shadow(16, 30.8, 15, 1.4)
    register(f"az.obj.thorn_hut@{v}", _art(p, note=["quilboar hut: woven bramble dome, hide cap, tusked door",
                                                    "quilboar hut: hide flank, boar skull over the door"][v]))


def _barricade() -> None:
    W, H = 24, 16
    p = Pic(W, H)
    for x0 in (3, 13):  # crossed sharpened stakes
        pole(p, x0, 14, x0 + 8, 2, WOOD, 4)
        pole(p, x0 + 8, 14, x0, 2, WOOD, 4)
        p.set(x0 + 8, 1, WOOD[5])
        p.set(x0, 1, WOOD[5])
    p.hline(1, 22, 9, WOOD[3])
    p.hline(1, 22, 10, WOOD[1])
    brambles(p, lambda x, y: 1 <= x <= 22 and 6 <= y <= 13, 60, 15, lambda x, y: 0.55 - y * 0.02 - x * 0.01, 0.5)
    for x0 in (3, 13):  # the stake points stay on top of the tangle
        p.set(x0 + 8, 1, WOOD[5])
        p.set(x0, 1, WOOD[5])
        p.set(x0 + 7, 2, WOOD[4])
        p.set(x0 + 1, 2, WOOD[4])
    p.outline()
    p.shadow(12, 15, 11, 1)
    register("az.obj.barricade", _art(p, note="quilboar barricade: stakes wound with thorny briar"))


# --- dwarven dig ---------------------------------------------------------------------------------------


def _dig_tent() -> None:
    W, H = 32, 28
    p = Pic(W, H)
    canvas = [BONE[0], BONE[1], BONE[2], BONE[3]]
    # blue Explorers' pennant on a pole behind
    p.vline(27, 1, 12, WOOD[3])
    p.stamp(["bbbB", "bBB.", "B..."], {"b": BLUE[3], "B": BLUE[2]}, 28, 1)
    # side roof running back, then the front gable
    p.poly([(10, 6), (27, 9), (30.5, 25.5), (17, 25.5)],
           lambda x, y: tone(canvas, 0.55 - (x - 10) * 0.012 - (y - 6) * 0.008, x, y, 0.04))
    p.line(10, 6, 27, 9, BONE[4])
    p.poly([(10, 5), (1.5, 25.5), (18.5, 25.5)], lambda x, y: tone(canvas, 0.78 - abs(x - 10) * 0.02, x, y, 0.1))
    p.poly([(10, 12), (6, 25.5), (14, 25.5)], DEEP)
    p.poly([(10, 12), (5.5, 25.5), (8, 25.5)], BONE[3])
    p.poly([(10, 12), (14.5, 25.5), (12.5, 25.5)], BONE[2])
    p.line(10, 12, 10, 5, BONE[2])
    p.set(10, 4, WOOD[4])
    # guy ropes and stakes
    p.line(3, 20, 0, 25, SAND[3])
    p.line(29, 17, 31, 25, SAND[3])
    # lantern at the door and a crate with a pick
    p.stamp(["s", "l", "s"], {"s": STEEL[2], "l": "fire4"}, 16, 13)
    p.rect(20, 21, 6, 5, lambda x, y: WOOD[4] if y == 21 else (WOOD[3] if x < 24 else WOOD[2]))
    p.line(26, 25, 28, 17, WOOD[3])
    p.stamp(["aaa..", "...a.", "....a"], {"a": STEEL[4]}, 26, 16)
    p.outline()
    p.shadow(16, 26.5, 16, 1.2)
    register("az.obj.dig_tent", _art(p, note="dwarven expedition tent: canvas ridge tent, lantern, pick"))


def _scaffold() -> None:
    W, H = 32, 32
    p = Pic(W, H)
    posts = (3, 15, 26)
    for i in range(2):  # X braces between the posts on each level
        for a, b in ((posts[0], posts[1]), (posts[1], posts[2])):
            y0, y1 = (4, 12) if i == 0 else (14, 22)
            p.line(a + 2, y0 + 1, b - 1, y1 - 1, WOOD[2])
            p.line(b - 1, y0 + 1, a + 2, y1 - 1, WOOD[2])
    for x in posts:
        p.vline(x, 2, 31, WOOD[4])
        p.vline(x + 1, 2, 31, WOOD[2])
    for y in (12, 22):  # plank decks
        p.hline(1, 29, y, WOOD[5])
        p.hline(1, 29, y + 1, WOOD[3])
        for x in range(4, 30, 5):
            p.set(x, y + 1, WOOD[1])
    # ladder up to the first deck
    for x in (19, 22):
        p.vline(x, 13, 31, WOOD[3])
    for y in range(15, 31, 3):
        p.hline(20, 21, y, WOOD[4])
    # hoist arm with rope and bucket
    p.hline(26, 31, 2, WOOD[4])
    p.hline(26, 31, 3, WOOD[2])
    p.vline(30, 4, 14, SAND[3])
    p.stamp(["abc", "abc"], {"a": WOOD[4], "b": WOOD[3], "c": WOOD[1]}, 29, 15)
    # tools on the deck
    p.stamp(["ss.", "..w", "..w"], {"s": STEEL[4], "w": WOOD[4]}, 6, 9)
    p.outline()
    p.shadow(15, 31.5, 15, 1)
    register("az.obj.scaffold", _art(p, note="wooden excavation scaffold with ladder and hoist"))


# --- gathering nodes ------------------------------------------------------------------------------

_SPARK = {"s": "white", "S": "gold3"}


def _node(name: str, rows: Sequence[str], legend: dict[str, str], sway: bool = True,
          spark: tuple[int, int] = (11, 3), note: str = "") -> None:
    base = Pic(16, 16).stamp(list(rows), legend)
    frames = []
    for fr in range(2):
        p = Pic(16, 16)
        if sway and fr == 1:  # the upper half leans one pixel with the wind
            for y in range(16):
                for x in range(16):
                    src = base.get(x - 1, y) if y < 8 else base.get(x, y)
                    p.set(x, y, src)
        else:
            p = base.copy()
        sx, sy = spark
        if fr == 1:
            p.stamp([".S.", "SsS", ".S."], _SPARK, sx - 1, sy - 1)
        else:
            p.set(sx, sy, "gold3")
        p.outline(skip=("white", "gold3"))
        p.shadow(8, 15, 5, 1)
        frames.append(p)
    register(name, _art(frames, fps=2, note=note))


def _nodes() -> None:
    leaf = {"L": LEAF[2], "l": LEAF[4], "g": LEAF[3], "G": LEAF[1]}
    _node("az.node.peacebloom", [
        "................",
        "................",
        "....aa..........",
        "...aooa...aa....",
        "....ab...aooa...",
        ".....g....ab....",
        "..aa.g.....g....",
        ".aoob.g...g.....",
        "..ab..g..g......",
        "....g.g.g.......",
        "..lLg.gLgl......",
        ".lLlLlgLlLl.....",
        "..LlLLLlLLGl....",
        "...GLLGLLG......",
        "................",
        "................",
    ], {**leaf, "a": BONE[4], "b": BONE[3], "o": "gold2"}, spark=(12, 2), note="peacebloom: white blossoms")
    _node("az.node.silverleaf", [
        "................",
        "................",
        "......e.........",
        "......ee...e....",
        "..e...eE..eE....",
        "..ee..eE.eE.....",
        "...eE.eEeE......",
        "....eEeEE..e....",
        ".e...eeE..eE....",
        ".eeE.eEE.eE.....",
        "..eeEeEEeE......",
        "...eeeEEE.......",
        "....GgGgG.......",
        "................",
        "................",
        "................",
    ], {**leaf, "e": "stat3", "E": "stat2"}, spark=(12, 3), note="silverleaf: silvery spears")
    _node("az.node.earthroot", [
        "................",
        "................",
        "................",
        ".....g..........",
        "....lg..g.......",
        ".....g.lg.......",
        ".....g..g.......",
        "....aaabb.......",
        "...abbbbcb......",
        "..abbcbbbcb.....",
        "..abbbbcbbc.a...",
        ".abcbbbbbcc.b...",
        "..mmbbcbcmmbc...",
        ".mMMmmmmmMMmm...",
        "................",
        "................",
    ], {**leaf, "a": WOOD[5], "b": WOOD[4], "c": WOOD[2], "m": MESA[3], "M": MESA[2]}, sway=False,
        spark=(11, 6), note="earthroot: a gnarled root pushing out of the soil")
    _node("az.node.prairie_flower", [
        "................",
        "...p.....p......",
        "..pop...pop.....",
        "...pg....pg.....",
        "....g..p..g.....",
        "....g.pop.g.....",
        "....g..pg.g.....",
        ".....g..gg......",
        ".....g..g.......",
        "..l..g.gg.l.....",
        "..Ll.gggg.L.....",
        "...LlLgLLlL.....",
        "....LLGLLG......",
        "................",
        "................",
        "................",
    ], {**leaf, "p": "flora4", "o": "gold2"}, spark=(12, 4), note="prairie flower: violet heads on tall stems")
    _node("az.node.shiny_stone", [
        "................",
        "................",
        "................",
        "................",
        "................",
        "................",
        "................",
        "................",
        "......aab.......",
        ".....abbbc......",
        "....abbbbcc.....",
        "....bbbbccc.....",
        ".....cccCC......",
        "................",
        "................",
        "................",
    ], {"a": "stat4", "b": "stat3", "c": "stat2", "C": "stat1"}, sway=False, spark=(7, 8),
        note="shiny stone: a polished pebble glinting in the grass")
    p = Pic(16, 16)
    rock(p, lambda x, y: ((x - 8) / 7) ** 2 + ((y - 11.5) / 4.5) ** 2 <= 1 and y < 15, STONE[1:], 71)
    p.stamp([
        "..............",
        "....ab........",
        "...abbc...ab..",
        "....cc...abc..",
        "......v...c...",
        ".ab..vv.......",
        "abbc......ab..",
        ".cc......abbc.",
    ], {"a": "gold2", "b": "ore2", "c": "ore1", "v": "cryst0"}, 1, 6)
    p.outline()
    p.shadow(8, 15, 7, 1)
    register("az.node.copper_vein", _art(p, note="copper vein: ore chunks and green patina in a boulder"))


# --- chests and the spirit portal ----------------------------------------------------------------


def _chest_body(p: Pic, locked: bool) -> None:
    band = [STEEL[4], STEEL[2]] if locked else [WOOD[1], WOOD[0]]
    for y in range(8, 15):
        for x in range(2, 14):
            p.set(x, y, WOOD[3] if x < 11 else WOOD[2])
            if y == 11:
                p.set(x, y, WOOD[1])
    for bx in (4, 11):
        p.vline(bx, 8, 14, band[0])
    p.hline(2, 13, 14, WOOD[1])


def _chests() -> None:
    frames = []
    for fr in range(2):
        p = Pic(16, 16)
        if fr == 0:
            p.rect(2, 5, 12, 3, lambda x, y: [WOOD[5], WOOD[4], WOOD[3]][y - 5] if x < 11 else WOOD[3])
            p.hline(3, 12, 4, WOOD[4])
        else:  # lid thrown back, gold heaped inside
            p.rect(3, 2, 10, 4, lambda x, y: WOOD[2] if y < 5 else WOOD[1])
            p.hline(3, 12, 2, WOOD[3])
            p.rect(2, 6, 12, 2, WOOD[0])
            p.stamp([".aba.bab..", "abbbabbbba"], {"a": "gold3", "b": "gold2"}, 3, 6)
        _chest_body(p, False)
        for bx in (4, 11):
            p.vline(bx, 5 if fr == 0 else 2, 7 if fr == 0 else 5, WOOD[1])
        p.stamp(["y", "Y"], {"y": "gold2", "Y": "gold1"}, 8, 8)
        p.outline()
        p.shadow(8, 15, 7, 1)
        frames.append(p)
    register("az.obj.chest", _art(frames, fps=1, loop=False,
                                  note="treasure chest; frame 0 closed, frame 1 opened (pick by frame)"))
    p = Pic(16, 16)
    p.rect(2, 5, 12, 3, lambda x, y: [WOOD[5], WOOD[4], WOOD[3]][y - 5] if x < 11 else WOOD[3])
    p.hline(3, 12, 4, WOOD[4])
    _chest_body(p, True)
    for bx in (4, 11):
        p.vline(bx, 4, 7, STEEL[4])
    p.hline(2, 13, 8, STEEL[3])
    p.stamp([".yy.", "y..y", "YYYY", "YkYY", "YYYY"], {"y": STEEL[4], "Y": "gold2"}, 6, 7)
    p.outline()
    p.shadow(8, 15, 7, 1)
    register("az.obj.chest_locked", _art(p, note="locked chest: iron bands and a padlock"))


def _spirit_portal() -> None:
    W, H = 24, 32
    cx, cy, R = 12.0, 16.0, 8.5
    frames = []
    for fr in range(4):
        p = Pic(W, H)
        for y in range(H):  # the spirit swirl inside the hoop
            for x in range(W):
                dx, dy = x + 0.5 - cx, y + 0.5 - cy
                rr = math.hypot(dx, dy)
                if rr > R - 1.2:
                    continue
                a = math.atan2(dy, dx)
                s = math.sin(2 * a + rr * 0.8 - fr * math.pi / 2)
                if s > 0.7:
                    c = "glowcyan"
                elif s > 0.2:
                    c = "water4:220"
                elif rr < 2.2:
                    c = "cryst2"
                else:
                    c = "water2:170"
                p.set(x, y, c)
        for y in range(H):  # the hoop: hide-wrapped bent sapling
            for x in range(W):
                rr = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                if R - 1.2 < rr <= R + 0.6:
                    lit = (x + 0.5 - cx) + (y + 0.5 - cy) < 0
                    wrap = (round(math.atan2(y + 0.5 - cy, x + 0.5 - cx) * 5) % 3) == 0
                    p.set(x, y, (HIDE[4] if lit else HIDE[2]) if wrap else (WOOD[4] if lit else WOOD[2]))
        for x in (2, 20):  # carved posts holding it
            p.vline(x, 10, 31, WOOD[4])
            p.vline(x + 1, 10, 31, WOOD[2])
            p.stamp(["ab", "cc", "ab"], {"a": RED[2], "b": RED[1], "c": BLUE[2]}, x, 12)
        p.hline(1, 22, 9, WOOD[4])
        p.hline(1, 22, 10, WOOD[2])
        for fx in (6, 12, 18):  # feathers hanging from the crossbar and hoop
            p.vline(fx, 26, 28, BONE[4] if fx < 12 else BONE[3])
            p.set(fx, 29, RED[2])
        p.stamp(["..a..", ".aba.", "abbba"], {"a": STONE[3], "b": STONE[2]}, 10, 29)
        p.outline(skip=("glowcyan", "cryst2"))
        p.shadow(12, 31.5, 11, 1)
        frames.append(p)
    register("az.obj.spirit_portal", _art(frames, fps=6, note="spirit portal: swirling blue spirit in a hide hoop"))


def _wilds() -> None:
    _rock_arch()
    _stonetalon_pass()
    _harpy_nest()
    _kodo_bones()
    _great_gate()
    _mine_entrance()
    _goblin_shack()
    _ore_cart()
    for v in range(2):
        _thorn_hut(v)
    _barricade()
    _dig_tent()
    _scaffold()
    _wagon()
    _nodes()
    _chests()
    _spirit_portal()



# --- settlement dressing ------------------------------------------------------------------------


def _fence(v: int) -> None:
    """16x16, tiles sideways: rails run edge to edge on the same rows in every variant and
    the one post sits in the middle, so any variants can be strung together."""
    p = Pic(16, 16)
    rails = (7, 11)
    for i, ry in enumerate(rails):
        if v == 1 and i == 0:  # a rope instead of the top rail, sagging between posts
            for x in range(16):
                p.set(x, ry + (1 if 3 <= x <= 5 or 10 <= x <= 12 else 0), SAND[3] if x % 2 else SAND[2])
            continue
        for x in range(16):
            p.set(x, ry, WOOD[4] if (x + i) % 5 else WOOD[3])
            p.set(x, ry + 1, WOOD[2] if x % 4 else WOOD[1])
    p.vline(7, 4, 15, WOOD[4])
    p.vline(8, 4, 15, WOOD[2])
    p.set(7, 3, WOOD[5])
    for ry in rails:  # rope lashing where rails meet the post
        p.set(6, ry + 1, SAND[3])
        p.set(9, ry + 1, SAND[2])
    if v == 2:  # a feather charm hung on the post
        p.vline(9, 5, 6, SAND[3])
        p.stamp(["a", "a", "r"], {"a": BONE[4], "r": RED[2]}, 10, 6)
    p.outline()
    for x in range(16):  # shadow strip along the whole run
        if p.get(x, 15) is None:
            p.set(x, 15, SHADOW)
    register(f"az.obj.fence@{v}", _art(p, note=["low log-rail fence", "rope-and-rail fence",
                                                "rail fence with a feather charm"][v]))


def _haystack(v: int) -> None:
    W, H = 24, 24
    p = Pic(W, H)
    if v == 0:  # a domed stack, a hide cap tied down with rope and stones
        info = dome_shade(p, 12, 22.5, 10.5, 17, SAND, ribs=())
        r = rng_for("hay", v)
        for (x, y), (u, ny, lv) in sorted(info.items()):
            if r.random() < 0.18:  # loose straws
                p.set(x, y, SAND[4] if lv > 0.45 else SAND[1])
        for (x, y), (u, ny, lv) in info.items():
            if ny < -0.62 + 0.08 * math.cos(u * 7):
                p.set(x, y, tone(HIDE[1:5], lv, x, y, 0.1))
        for y in (7, 8):
            p.set(6, y + 3, SAND[1])
        p.line(4, 12, 11, 7, SAND[1])
        p.line(20, 12, 13, 7, SAND[1])
        p.stamp(["ab", "bc"], {"a": STONE[4], "b": STONE[3], "c": STONE[1]}, 3, 12)
        p.stamp(["ab", "bc"], {"a": STONE[4], "b": STONE[3], "c": STONE[1]}, 19, 12)
    else:  # a long loaf-shaped rick, combed straw, roped in two bands
        info = dome_shade(p, 12, 22.5, 11, 14, SAND, flat=2.0)
        for (x, y), (u, ny, lv) in info.items():
            if (x * 3 + y) % 5 == 0:
                p.set(x, y, step(SAND, p.get(x, y), 1 if lv > 0.5 else -1))
        for bx in (7, 16):
            for (x, y), (u, ny, lv) in info.items():
                if x == bx:
                    p.set(x, y, SAND[1] if lv < 0.6 else SAND[2])
        p.stamp(["ab", "bc"], {"a": STONE[4], "b": STONE[3], "c": STONE[1]}, 6, 21)
        p.stamp(["ab", "bc"], {"a": STONE[4], "b": STONE[3], "c": STONE[1]}, 15, 21)
    p.outline()
    p.shadow(12, 23, 11, 1.2)
    register(f"az.obj.haystack@{v}", _art(p, note=["hay stack with a hide cap roped down",
                                                   "hay rick roped in two bands"][v]))


def _cooking_pot() -> None:
    frames = []
    for fr in range(2):
        p = Pic(16, 16)
        # steam wisps drifting up, alternating
        wisp = ["..a..", ".a.A.", "..aA.", ".aA..", "..A.."] if fr == 0 else [".a...", "..aA.", ".Aa..", "..aA.", "..A.."]
        p.stamp(wisp, {"a": "grey4:150", "A": "white:170"}, 6, 0)
        p.line(2, 14, 7, 3, WOOD[3])   # tripod
        p.line(13, 14, 8, 3, WOOD[2])
        p.vline(8, 4, 5, STEEL[2])
        p.ellipse(8, 9.5, 4.5, 3.5, lambda x, y: tone(GREY[0:4], 0.85 - (x - 4) * 0.08 - (y - 7) * 0.04, x, y, 0.1))
        p.hline(4, 12, 6, GREY[3])
        p.hline(5, 11, 7, "azs_leaf2" if fr == 0 else "azs_leaf3")  # stew
        p.set(7, 7, "tent3")
        for x in range(5, 12):  # coals
            p.set(x, 13, FIRE[3] if (x + fr) % 2 else FIRE[1])
            p.set(x, 14, STONE[1] if x % 3 else FIRE[2])
        p.stamp(["ab", ".."], {"a": STONE[4], "b": STONE[2]}, 3, 13)
        p.stamp(["ab", ".."], {"a": STONE[3], "b": STONE[1]}, 11, 13)
        p.outline(skip=FIRE[1:4])
        p.shadow(8, 15, 6, 1)
        frames.append(p)
    register("az.obj.cooking_pot", _art(frames, fps=2, note="iron stew pot on a tripod over coals, steaming"))


TORCH_FLAMES = [
    ["...a..", "..ab..", "..bb.a", ".abcb.", ".bcdb.", ".bcdcb", "abcdcb", ".bccb."],
    ["......", "..a...", ".ab...", ".bbca.", "abcdb.", ".bcdb.", "bcddcb", ".bccb."],
    [".a....", "....a.", "...ba.", "..bcb.", ".bcdb.", "abcdcb", ".bcdcb", ".bccb."],
]


def _torch() -> None:
    frames = []
    for fr in range(3):
        p = Pic(16, 24)
        p.stamp(TORCH_FLAMES[fr], {"a": FIRE[2], "b": FIRE[3], "c": FIRE[4], "d": FIRE[5]}, 5, 0)
        p.vline(7, 8, 23, WOOD[4])
        p.vline(8, 8, 23, WOOD[2])
        p.stamp(["abba", "acca", "abba"], {"a": HIDE[1], "b": HIDE[3], "c": HIDE[2]}, 6, 7)  # wrapped head
        p.set(7, 9, FIRE[3])
        p.stamp(["t..t", ".tt."], {"t": BONE[3]}, 6, 12)  # horn collar
        p.stamp([".ab.", "abbc"], {"a": STONE[4], "b": STONE[3], "c": STONE[1]}, 6, 22)
        p.outline(skip=FIRE[2:])
        p.shadow(8, 23.3, 3, 0.8)
        frames.append(p)
    register("az.obj.torch", _art(frames, fps=6, note="standing torch: hide-wrapped head on a pole"))


def _signpost(v: int) -> None:
    p = Pic(16, 24)
    p.vline(7, 3, 23, WOOD[4])
    p.vline(8, 3, 23, WOOD[2])
    arrow_r = ["aaaaab.", "cccccdb", "eeeeed."]
    arrow_l = [".baaaaa", "bdccccc", ".deeeee"]
    lg = {"a": WOOD[5], "b": WOOD[3], "c": WOOD[4], "d": WOOD[2], "e": WOOD[1]}
    if v == 0:
        p.stamp(arrow_r, lg, 8, 5)
        p.stamp(arrow_l, lg, 1, 10)
        p.hline(10, 12, 6, WOOD[2])  # carved marks
        p.hline(3, 5, 11, WOOD[2])
        p.set(7, 2, WOOD[5])
    else:
        p.stamp(arrow_r, lg, 8, 8)
        p.set(11, 9, RED[2])
        p.set(13, 9, RED[2])
        skull(p, 8, -2)
    p.stamp([".ab.", "abbc"], {"a": STONE[4], "b": STONE[3], "c": STONE[1]}, 6, 22)
    p.outline()
    p.shadow(8, 23.3, 4, 0.8)
    register(f"az.obj.signpost@{v}", _art(p, note=["signpost: two carved arrow boards",
                                                   "signpost with a kodo skull and one board"][v]))


def _prayer_flags() -> None:
    frames = []
    cols = [(RED[2], RED[1]), ("gold2", "gold1"), (BLUE[3], BLUE[2]), (BONE[4], BONE[3]), (LEAF[4], LEAF[3])]
    for fr in range(2):
        p = Pic(32, 24)
        for x in (1, 29):
            p.vline(x, 3, 23, WOOD[4])
            p.vline(x + 1, 3, 23, WOOD[2])
            p.set(x, 2, BONE[4])
        pts = []
        for x in range(3, 29):  # the cord sags between the poles
            t = (x - 2) / 27
            y = round(4 + math.sin(t * math.pi) * 4)
            p.set(x, y, SAND[3])
            pts.append((x, y))
        for i, x in enumerate(range(4, 28, 4)):
            y = dict(pts)[x] + 1
            lit, dark = cols[i % len(cols)]
            sway = (1 if (i + fr) % 2 else 0)
            for j in range(5):  # a flag, its tail swinging with the wind
                dx = sway if j >= 3 else 0
                p.hline(x + dx, x + 2 + dx, y + j, lit if j < 3 else dark)
                p.set(x + 2 + dx, y + j, dark)
        p.outline()
        p.shadow(2, 23.3, 2, 0.8)
        p.shadow(30, 23.3, 2, 0.8)
        frames.append(p)
    register("az.obj.prayer_flags", _art(frames, fps=2, note="string of prayer flags between two poles, fluttering"))


def _stone_circle() -> None:
    W, H = 48, 32
    p = Pic(W, H)
    cx, cy, rx, ry = 24.0, 21.0, 20.0, 7.5
    # the ring of worn earth the stones stand on, and a painted hearth stone in the middle
    for y in range(H):
        for x in range(W):
            d = ((x + 0.5 - cx) / rx) ** 2 + ((y + 0.5 - cy) / ry) ** 2
            if 0.75 < d <= 1.08:
                p.set(x, y, "dust3:120")
    stones = []
    for k in range(9):
        a = -math.pi / 2 + k * math.tau / 9
        sx, sy = cx + math.cos(a) * rx, cy + math.sin(a) * ry
        stones.append((sy, sx, k))
    hearth = [".abbbb.", "abrrbbc", ".cccccc"]
    for sy, sx, k in sorted(stones + [(cy, cx, -1)]):  # back to front, the hearth stone mid-way
        if k < 0:
            q = Pic(W, H).stamp(hearth, {"a": STONE[4], "b": STONE[3], "c": STONE[1], "r": RED[2]}, 21, 19)
            q.outline()
            for y in range(H):
                for x in range(W):
                    if q.px[y][x] is not None:
                        p.px[y][x] = q.px[y][x]
            continue
        near = (sy - (cy - ry)) / (2 * ry)
        hgt = round(7 + near * 6 + (k % 3))
        wid = 2.2 + near * 1.3
        base = round(sy)
        pts = [(sx - wid, base + 0.9), (sx - wid * 0.9, base - hgt * 0.8), (sx - wid * 0.3, base - hgt),
               (sx + wid * 0.6, base - hgt * 0.9), (sx + wid, base - hgt * 0.5), (sx + wid, base + 0.9)]
        q = Pic(W, H)
        q.poly(pts, lambda x, y, sx=sx, base=base, hgt=hgt: tone(
            STONE[1:], 0.9 - (x + 0.5 - sx + 2.5) * 0.14 - (y - base + hgt) * 0.015, x, y, 0.15))
        if k % 3 == 1:  # painted spirit marks on some faces
            q.set(round(sx - 1), base - hgt // 2, RED[2])
            q.set(round(sx - 1), base - hgt // 2 + 1, RED[2])
        if k % 4 == 0:
            q.set(round(sx - 1), base - hgt + 2, LEAF[3])
        q.outline()
        q.shadow(sx, base + 0.5, wid + 1, 1)
        for y in range(H):
            for x in range(W):
                if q.px[y][x] is not None and not (":" in q.px[y][x] and p.px[y][x] not in (None, "dust3:120")):
                    p.px[y][x] = q.px[y][x]
    register("az.obj.stone_circle", _art(p, note="ring of standing stones with painted marks, sacred ground"))


def _palisade(v: int) -> None:
    W, H = 32, 24
    p = Pic(W, H)
    r = rng_for("palisade", v)
    x = 1
    while x < 30:
        w = 3 if v == 0 else r.choice((3, 4))
        top = (3 if v == 0 else r.randint(1, 5)) + (x % 2)
        for xx in range(x, min(31, x + w)):
            k = xx - x
            for y in range(top + int(abs(k - (w - 1) / 2) * 1.2), 24):
                p.set(xx, y, [WOOD[4], WOOD[3], WOOD[2], WOOD[1]][min(3, k * 4 // w)])
        p.set(x + w // 2 - (1 if w == 4 else 0), top - 1, WOOD[5] if v == 0 else BONE[3])
        x += w
    for ry in (9, 18):  # lashings
        for xx in range(1, 31):
            if p.get(xx, ry):
                p.set(xx, ry, SAND[3] if xx % 3 else SAND[1])
    if v == 0:  # quilboar: briar wound along the wall, a boar skull
        brambles(p, lambda x, y: 1 <= x <= 30 and 12 <= y <= 16, 5, 14, lambda x, y: 0.5, 0.45)
        p.stamp([".abbba.", "abkbkba", ".abbba.", "t.bbb.t"],
                {"a": BONE[3], "b": BONE[4], "t": BONE[4]}, 12, 5)
    else:  # gnoll: hide scraps and bones hung on the stakes
        p.rect(6, 11, 5, 5, lambda x, y: tone(HIDE[1:4], 0.8 - (x - 6) * 0.1, x, y, 0.2))
        p.stamp(["t.t", ".t.", "t.t"], {"t": BONE[4]}, 21, 12)
        p.vline(17, 10, 13, BONE[3])
    p.outline()
    p.shadow(16, 23.5, 16, 1)
    register(f"az.obj.palisade@{v}", _art(p, note=["quilboar palisade: sharpened logs, briar, boar skull",
                                                   "gnoll palisade: ragged stakes, hide and bones"][v]))


def _hide_stretcher() -> None:
    W, H = 24, 24
    p = Pic(W, H)
    # a square frame of lashed poles on two legs
    for x0, y0, x1, y1 in ((3, 2, 3, 23), (19, 2, 19, 23)):
        pole(p, x0, y0, x1, y1)
    p.hline(2, 21, 2, WOOD[4])
    p.hline(2, 21, 3, WOOD[2])
    p.hline(2, 21, 17, WOOD[4])
    p.hline(2, 21, 18, WOOD[2])
    hide = [(8, 5), (11, 4.5), (15, 5), (17, 8), (16.5, 12), (17, 15), (12, 15.5), (7, 15), (6, 12), (6.5, 8)]
    p.poly(hide, lambda x, y: tone(HIDE[2:], 0.95 - (x - 6) * 0.04 - (y - 5) * 0.03, x, y, 0.1))
    for (hx, hy), (fx, fy) in zip(hide[::2], ((6, 4), (17, 4), (18, 9), (12, 16), (5, 12))):
        p.line(round(hx), round(hy), fx, fy, SAND[2])  # cords to the frame
    p.stamp(["..r..", ".rwr.", "r.r.r", "..r.."], {"r": RED[2]}, 9, 8)  # painted mark
    p.outline()
    p.shadow(12, 23.3, 10, 1)
    register("az.obj.hide_stretcher", _art(p, note="kodo hide laced into a pole frame, painted"))


def _kodo_saddle_rack() -> None:
    W, H = 24, 16
    p = Pic(W, H)
    for x in (2, 20):  # A-legs
        pole(p, x, 15, x + 1, 5, WOOD, 3)
    p.hline(1, 22, 5, WOOD[4])
    p.hline(1, 22, 6, WOOD[2])
    for sx in (4, 13):  # saddles slung over the rail: hide seat, red blanket, a horn pommel
        p.stamp([
            "t.....t",
            "hH...Hd",
            "hHHHHHd",
            "rrrrrrR",
            "yyyyyyY",
            "rRRRRRR",
            "r.....R",
        ], {"t": BONE[4], "h": HIDE[4], "H": HIDE[3], "d": HIDE[1], "r": RED[2], "R": RED[1],
            "y": BONE[3], "Y": BONE[2]}, sx, 2)
    p.vline(11, 7, 12, SAND[3])  # harness rope hanging with a ring
    p.stamp(["ab", "ba"], {"a": STEEL[4], "b": STEEL[2]}, 11, 12)
    p.outline()
    p.shadow(12, 15.3, 11, 0.9)
    register("az.obj.kodo_saddle_rack", _art(p, note="rack with two kodo saddles and a harness"))


def _grave_cairn(v: int) -> None:
    p = Pic(16, 16)
    rock(p, lambda x, y: ((x - 8) / 6.5) ** 2 + ((y - 15) / 7) ** 2 <= 1 and y < 15, STONE[1:], 81 + v)
    for y in range(9, 15):  # stacked stones: joints
        for x in range(p.w):
            if p.get(x, y) and (x * 3 + (y // 2) * 5) % 7 == 0:
                p.set(x, y, STONE[1])
    if v == 0:  # a feather staff planted in the cairn
        p.vline(8, 1, 9, WOOD[4])
        p.stamp(["ab", "ab", "rR"], {"a": BONE[4], "b": BONE[3], "r": RED[2], "R": RED[1]}, 9, 2)
        p.stamp(["a", "a", "b"], {"a": BONE[4], "b": BLUE[2]}, 6, 3)
    else:  # horns laid on top, prairie flowers left by mourners
        p.stamp(["t....t", "tT..Tt", ".TTTT."], {"t": BONE[4], "T": BONE[3]}, 5, 6)
        p.stamp(["f.p", "g.g"], {"f": BONE[4], "p": "flora4", "g": LEAF[3]}, 12, 13)
    p.outline()
    p.shadow(8, 15.3, 7, 0.9)
    register(f"az.obj.grave_cairn@{v}", _art(p, note=["tauren grave cairn with a feather staff",
                                                      "tauren grave cairn with horns and flowers"][v]))


def _dressing() -> None:
    for v in range(3):
        _fence(v)
    for v in range(2):
        _haystack(v)
        _signpost(v)
        _palisade(v)
        _grave_cairn(v)
    _cooking_pot()
    _torch()
    _prayer_flags()
    _stone_circle()
    _hide_stretcher()
    _kodo_saddle_rack()


# --- well-totem, hide lodge, windbreaks -------------------------------------------------------------

BEAST_FACE = [
    "hhhhhhhhhhd",
    "hTTmmmmmTTd",
    "htTTmmmTTtd",
    "hmookmookmd",
    "hmmmmhmmmmd",
    "hmmmhHhmmmd",
    "hmrmmhmmrmd",
    "hrkkkkkkkrd",
    "hkwkwkwkwkd",
    "hrkkkkkkkrd",
    "hmrrrrrrrmd",
    "ddddddddddd",
]


def stone_dais(th, z, r, v, ix, iy):
    """Low round dais of fitted grey stones (lathe material)."""
    if z > 3.4:   # the top: worn flat stones in rings
        return STONE[2] if int(r) % 5 == 0 else tone(STONE[2:], v, ix, iy, 0.15)
    if abs(z - 1.8) < 0.45 or (th * r / 4.5 + (0.5 if z > 1.8 else 0)) % 1.0 < 0.12:
        return STONE[1]
    return tone(STONE[1:], v, ix, iy, 0.15)


def _water_well() -> None:
    """The tauren well-totem: a round stone dais, four splayed log legs holding a carved
    beast-face box over a small drum, a wide shallow hide canopy with a spiky fringe, and a
    cross-pole on top with two dark hides hanging."""
    W, H = 48, 80
    cx = 24.0
    sc = Scene(W, H, 0, 68)
    sc.lathe(cx, 0, [(0, 19.5), (3.4, 19.2), (3.8, 18.0), (3.8, 0)], stone_dais)
    sc.lathe(cx, 0, [(8, 3.8), (13, 3.8), (13, 0)],
             lambda th, z, r, v, ix, iy: PAINT_RED[2] if 9.5 < z < 10.5 else tone(CANVAS, v, ix, iy, 0.1))
    for a in (0.785, 2.356, 3.927, 5.498):
        sc.rod((cx + 8 * math.cos(a), 8 * math.sin(a), 3.8), (cx + 3 * math.cos(a), 3 * math.sin(a), 27), 1.1, WOOD[1:])
    # the carved box: face toward the viewer, a shaded right side, a lit top
    sc.quad((cx - 5.5, 4.5, 15), (11, 0, 0), (0, 0, 12), decal(BEAST_FACE, _FACE_LG))
    sc.quad((cx + 5.5, 4.5, 15), (0, -9, 0), (0, 0, 12), lambda u, w, lv, ix, iy: tone(DRIFT[1:], lv, ix, iy, 0.1))
    sc.quad((cx - 5.5, -4.5, 27), (11, 0, 0), (0, 9, 0), lambda u, w, lv, ix, iy: DRIFT[4])
    # canopy: shallow hide cone, a teal band near the rim, a spiky red-brown fringe hanging below
    hide = canvas(12, 0.5, ramp=HIDE[1:], bands=((31.8, 33.2, lambda th, t, r, v, ix, iy: TEAL[2] if v < 0.5 else TEAL[3]),))

    def canopy(th, z, r, v, ix, iy):
        if z < 31.2:
            ph = (th * r / 2.6) % 1.0
            if (31.2 - z) > (1 - abs(ph - 0.5) * 2) * 3.4:
                return None
            return PAINT_RED[1] if v < 0.45 else PAINT_RED[2]
        return hide(th, z, r, v, ix, iy)
    sc.lathe(cx, 0, [(27.6, 22.2), (31.2, 22.0), (31.6, 21.6), (38.5, 1.2), (38.6, 0)], canopy)
    # cross-pole with two hides
    sc.rod((cx, 0, 37), (cx, 0, 62), 1.0, WOOD[1:])
    sc.rod((cx - 10, 0.5, 58), (cx + 10, 0.5, 58), 0.8, WOOD[1:])
    for x0 in (cx - 9, cx + 2.5):
        sc.quad((x0, 1.5, 44), (6.5, 0, 0), (0, 0, 13.5), lambda u, w, lv, ix, iy, x0=x0: (
            None if w < 0.1 and int(u * 6) % 2 else
            BONE[3] if abs(u - 0.5) < 0.2 and abs(w - 0.55) < 0.12 else
            HIDE[1] if x0 < cx else HIDE[0]))
    p = sc.pic()
    register("az.obj.water_well", _art(finish(p, 24, 77, 23, 2.5),
             note="tauren well-totem: stone dais, splayed legs, beast-face box, fringed hide canopy, hanging hides"))


def _hide_longhouse() -> None:
    """A long low lodge of brown hide stretched over arched poles, rounded ends, a doorway in
    the middle of the long side and crossed poles over both ends."""
    W, H = 96, 48
    sc = Scene(W, H, 0, 38)
    phi = 0.08
    P = box_frame(phi)
    cx, cy, L, R, HH = 48.0, -3.0, 30.0, 12.0, 14.0
    c, s = math.cos(phi), math.sin(phi)

    def hide(a, th, lv, ix, iy):
        rib = ((a + L) / 6.0) % 1.0
        z = HH * math.sin(th)
        if abs(a) < 4.2 and th < 1.25 and z < 10:
            if abs(a) > 3.2 or z > 9:
                return HIDE[4] if a < 0 else WOOD[1]
            return DEEP if z > 1.5 else FIRE[2]
        if rib < 0.12:
            return HIDE[0] if lv < 0.5 else HIDE[1]
        if rib < 0.26:
            lv += 0.12
        for sz in (0.55, 1.25):   # stitched seams along the lodge
            if abs(th - sz) * R < 0.55:
                return cord(lv) if int(a * 1.0) % 3 else HIDE[1]
        if -20 < a < -12 and 0.7 < th < 1.05 or 14 < a < 21 and 0.25 < th < 0.55:
            return tone(HIDE[2:], lv + 0.1, ix, iy, 0.1)   # lighter patches
        return tone(HIDE[0:5], lv, ix, iy, 0.12)

    def vault(u, w):
        a, th = -L + 2 * L * u, math.pi * w
        b, z = R * math.cos(th), HH * math.sin(th)
        nb, nz = math.cos(th) / R, math.sin(th) / HH
        return P(cx, cy, a, b, z), (-nb * s, nb * c, nz)
    sc.surface(vault, int(2 * L / 0.3), int(math.pi * R / 0.3),
               lambda u, w, lv, ix, iy: hide(-L + 2 * L * u, math.pi * w, lv, ix, iy))
    for end in (-1, 1):
        ex, ey, _ = P(cx, cy, end * L, 0, 0)
        prof = [(HH * math.sin(t * math.pi / 2 / 12), R * math.cos(t * math.pi / 2 / 12)) for t in range(13)]
        sc.lathe(ex, ey, prof, lambda th, z, r, v, ix, iy: (HIDE[1] if (th * 6 / math.pi) % 1.0 < 0.1
                                                             else tone(HIDE[0:5], v, ix, iy, 0.12)))
        for db in (-3.5, 3.5):
            sc.rod(P(cx, cy, end * (L + 2), 0, HH - 3), P(cx, cy, end * (L + 6), db, HH + 5), 0.7, WOOD[1:])
    # stakes pinning the hide hem along the front
    for a in range(-int(L) - 4, int(L) + 6, 7):
        sc.rod(P(cx, cy, a, R + 1, 0), P(cx, cy, a, R + 1, 2.2), 0.5, WOOD[2:])
    p = sc.pic()
    register("az.obj.hide_longhouse", _art(finish(p, 48, 45, 44, 3), note="long low lodge of brown hide over arched poles"))


def _windbreak(v: int) -> None:
    """Brown hide screens laced between poles (two or three poles)."""
    W, H = 48, 32
    sc = Scene(W, H, 0, 29)
    poles = [(5, -2), (43, 2)] if v == 0 else [(4, -3), (24, 0), (44, 3)]
    for x, y in poles:
        sc.rod((x, y, 0), (x, y, 25), 0.9, WOOD[1:])
        sc.put(x - 0.5, y, 25.5, WOOD[5], sc.new_id(), bias=2)
    for i, ((x0, y0), (x1, y1)) in enumerate(zip(poles, poles[1:])):
        ramp = HIDE[0:5] if (v + i) % 2 == 0 else HIDE[1:]

        def sheet(u, w, x0=x0, y0=y0, x1=x1, y1=y1):
            top = 21 - 2.5 * math.sin(math.pi * u)
            z = 3 + (top - 3) * w
            bulge = 1.6 * math.sin(math.pi * u) * math.sin(math.pi * w)
            return (x0 + 1.2 + (x1 - x0 - 2.4) * u, y0 + (y1 - y0) * u + bulge, z), (-0.1, 1.0, 0.25 * (w - 0.5))

        def mat(u, w, lv, ix, iy, ramp=ramp, i=i):
            if u < 0.04 or u > 0.96:
                return cord(lv) if int(w * 18) % 2 else None   # lacing to the poles
            if w > 0.94 or w < 0.05:
                return ramp[1]
            if v == 0 and abs(u - 0.5) * 3 + abs(w - 0.55) * 2.2 < 0.42:
                return TEAL[3] if abs(u - 0.5) * 3 + abs(w - 0.55) * 2.2 < 0.28 else PAINT_RED[2]
            if v == 1 and i == 1 and 0.2 < u < 0.42 and 0.3 < w < 0.6:
                return CANVAS[3] if (u * 40) % 3 > 0.6 else cord(lv)   # a stitched patch
            return tone(ramp, lv + 0.05 * math.sin(u * 20), ix, iy, 0.12)
        sc.surface(sheet, 120, 60, mat)
    p = sc.pic()
    register(f"az.obj.windbreak@{v}", _art(finish(p, 24, 29.5, 22, 2),
             note=["hide windbreak on two poles, painted diamond", "hide windbreak on three poles, patched"][v]))


# --- Palemane, Kodo Rock, stakes, thorn vines ---------------------------------------------------------


def boulder(sc: Scene, x: float, y: float, r: float, h: float, z0: float = 0.0, seed: int = 0) -> None:
    """A rounded blue-grey boulder with a few cracks."""
    prof = [(0, r * 0.8), (h * 0.3, r), (h * 0.7, r * 0.78), (h * 0.95, r * 0.3), (h, 0)]

    def mat(th, z, rr, v, ix, iy):
        if int(th * rr * 0.9 + seed * 3 + z * 0.4) % 7 == 0 and z < h * 0.85:
            return SLATE[1]
        return tone(SLATE, v + (bayer(ix + seed, iy) - 0.5) * 0.12, ix, iy, 0.15)
    sc.lathe(x, y, prof, mat, squash=0.85, lift=z0)


def _cave_mouth() -> None:
    """Palemane Rock: a dark cave in the foot of a pale streaked cliff, framed by blue-grey boulders."""
    W, H = 64, 48
    sc = Scene(W, H, 0, 44)
    cx, cy, RX, RY, RZ = 32.0, -8.0, 31.0, 10.0, 40.0

    def cliff(u, w):
        th, ph = math.pi * u, math.pi / 2 * w
        x, y, z = math.cos(th) * math.cos(ph), math.sin(th) * math.cos(ph), math.sin(ph)
        x *= 1 + 0.08 * math.sin(th * 7) * (1 - w)
        return (cx + RX * x, cy + RY * y, RZ * z ** 1.3), (x / RX, y / RY, z / RZ * 1.4)

    def rockface(u, w, lv, ix, iy):
        streak = ((ix * 7919) % 13) / 13.0 - 0.5
        return tone(PALE, lv + streak * 0.18 - 0.05, ix, iy, 0.1)
    sc.surface(cliff, 300, 160, rockface)
    p0 = sc.pic()
    # the cave: a dark arch with a dim floor
    for y in range(H):
        for x in range(W):
            dx, dy = (x + 0.5 - 32) / 9.5, (y + 0.5 - 43) / 17
            if dy < 0 and dx * dx + dy * dy < 1 and sc.col[y][x]:
                sc.col[y][x] = DEEP if dx * dx + dy * dy < 0.82 else PALE[0]
                sc.dep[y][x] -= 0.5
    for bx, by, r, h, z0, sd in ((-13, 5, 6.5, 11, 0, 1), (-20, 8, 5, 7, 0, 2), (-9, 10, 4, 5, 0, 3),
                                 (13, 5, 7, 12, 0, 4), (20, 9, 5.5, 7, 0, 5), (8, 11, 4, 4.5, 0, 6),
                                 (-4, 3, 6, 6, 15.5, 7), (5, 2, 5, 5, 15, 8), (-26, 4, 4, 5, 0, 9)):
        boulder(sc, cx + bx, by, r, h, z0, sd)
    p = sc.pic()
    del p0
    tufts(p, [(x, y) for y in range(H) for x in range(W) if p.px[y][x] in PALE], 61, 0.06)
    register("az.obj.cave_mouth", _art(finish(p, 32, 45, 31, 2.5),
             note="Palemane Rock: cave mouth in a pale cliff framed by blue-grey boulders"))


RUNES = [
    ".s.s.",
    "s.s.s",
    ".sss.",
    "..s..",
    ".sss.",
    "s...s",
    ".....",
    "..s..",
    ".s.s.",
]


def _standing_stone() -> None:
    """Kodo Rock: a single dark blue-grey standing stone with faint carved symbols."""
    W, H = 16, 32
    sc = Scene(W, H, 0, 29)

    def mat(th, z, r, v, ix, iy):
        u = wrap(th - FRONT) * r
        col, row = int(u + 2.5), int(20 - z)
        if 0 <= col < 5 and 0 <= row < len(RUNES) and RUNES[row][col] == "s":
            return SLATE[3] if v > 0.4 else SLATE[2]
        return tone(SLATE[:5], v - 0.05 + (0.08 if int(z * 0.7 + th * 2) % 5 == 0 else 0), ix, iy, 0.15)
    sc.lathe(8.0, 0.0, [(0, 5.2), (5, 5.6), (15, 5.0), (21, 4.0), (24.5, 2.4), (25.5, 0)], mat, squash=0.6)
    p = sc.pic()
    tufts(p, [(x, y) for y in range(24, H) for x in range(W) if p.px[y][x]], 63, 0.5)
    register("az.obj.standing_stone", _art(finish(p, 8, 30, 7, 1.6),
             note="Kodo Rock: dark blue-grey standing stone with faint carved runes"))


def _stake_row(v: int) -> None:
    """A row of crooked sharpened stakes angled outward (Grimtotem / quilboar barricades)."""
    W, H = 32, 16
    sc = Scene(W, H, 0, 13)
    r = rng_for("stakes", v)
    sc.rod((1, -2, 1.2), (31, -2, 1.2), 1.1, DRIFT[1:])     # the log they are lashed to
    xs = [3.5 + i * 4.2 for i in range(7)]
    for i, x in enumerate(xs):
        broken = v == 1 and i in (2, 5)
        h = 7.5 if broken else 11 + r.uniform(-1.2, 1.2)
        lean = r.uniform(-1.5, 1.5) if v == 1 else r.uniform(-0.5, 0.5)
        top = (x + lean, 3.5, h)
        sc.rod((x, -1, 0), top, 0.9, DRIFT[1:])
        if not broken:
            tip = (x + lean * 1.25, 4.2, h + 2.6)
            sc.rod(top, tip, 0.4, DRIFT[3:])
    if v == 0:
        sc.rod((2, 0.6, 4), (30, 0.6, 4), 0.35, HIDE[2:])   # rope binding
    p = sc.pic()
    register(f"az.obj.stake_row@{v}", _art(finish(p, 16, 14, 15, 1.5),
             note=["row of sharpened stakes lashed to a log", "crooked broken stake row"][v]))


VINES = [
    [[(-13, 2, 0), (-14, 1, 12), (-9, 0, 25), (0, -1, 35), (10, 0, 35), (15, 1, 26), (11, 2, 18), (4, 2, 20),
      (3, 2, 27), (8, 2, 29), (10, 2, 24), (7, 2, 23)]],
    [[(12, 2, 0), (15, 1, 14), (9, 0, 30), (-3, 0, 40), (-13, 1, 37), (-16, 2, 27), (-12, 3, 20), (-8, 3, 24)]],
    [[(-14, 2, 0), (-8, 0, 17), (4, 0, 30), (14, 1, 38), (18, 2, 32)],
     [(14, 4, 0), (7, 3, 13), (-5, 2, 24), (-14, 2, 28), (-17, 3, 21)]],
]


def _thorn_vine(v: int) -> None:
    """Giant coiled olive-brown thorn vines with big hooked thorns (the quilboar blight)."""
    W, H = 48, 64
    sc = Scene(W, H, 24, 60)
    spikes = []
    for k, pts in enumerate(VINES[v]):
        r0 = 5.0 if k == 0 else 3.8
        samples = sc.tube(pts, r0, 1.0, lambda lv, s, ix, iy: (
            VINE[1] if s % 4.5 < 0.9 else tone(VINE, lv + (0.06 if s % 9 < 4.5 else 0), ix, iy, 0.14)))
        spikes += [(q, samples[i - 1]) for i, q in enumerate(samples) if i and i % 9 == 4]
    p = sc.pic()
    for (x, y, z, r, _), (px, py, pz, _, _) in spikes:
        sx, sy = 24 + x, 60 + y * 0.5 - z
        dx, dy = sx - (24 + px), sy - (60 + py * 0.5 - pz)
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        for side in (1, -1):
            for t in range(1, 4):
                ex, ey = sx + side * nx * (r + t - 0.5) - dx / ln * t * 0.6, sy + side * ny * (r + t - 0.5) - dy / ln * t * 0.6
                c = BONE[3] if t == 3 else VINE[3] if side * nx - side * ny > 0 else VINE[2]
                if p.get(int(ex), int(ey)) is None or t == 1:
                    p.set(int(ex), int(ey), c)
    register(f"az.obj.thorn_vine@{v}", _art(finish(p, 24, 61, 20, 2.5),
             note=["giant thorn vine arching into a coil", "giant thorn vine hooked over", "two crossing thorn vines"][v]))


# --- the Great Gate: all carved wood ------------------------------------------------------------------

DIAMOND = [
    "....r....",
    "...rtr...",
    "..rtTtr..",
    ".rtToTtr.",
    "rtToooTtr",
    ".rtToTtr.",
    "..rtTtr..",
    "...rtr...",
    "....r....",
]


def fur_roof(sc: Scene, cx: float, cy: float, z: float, r0: float, r1: float, rise: float, fringe: float) -> None:
    """A pagoda-like tier: shallow hide cone with a teal band and a shaggy fur fringe below."""
    def mat(th, zz, r, v, ix, iy):
        if zz < z:
            ph = (th * r / 2.0) % 1.0
            if (z - zz) > fringe * (0.55 + 0.45 * math.sin(ph * math.pi)):
                return None
            return HIDE[0] if v < 0.4 else HIDE[1] if v < 0.65 else HIDE[2]
        if zz < z + 1.2:
            return TEAL[3] if v > 0.5 else TEAL[1]
        return tone(HIDE[0:4], v + (0.1 if (th * r / 3) % 1.0 < 0.3 else 0), ix, iy, 0.15)
    sc.lathe(cx, cy, [(z - fringe, r0 + 0.3), (z, r0), (z + rise, r1), (z + rise, 0)], mat)


def gate_tower(sc: Scene, cx: float, cy: float) -> None:
    def column(th, z, r, v, ix, iy):
        u = wrap(th - FRONT) * r
        if 9 <= z < 18 and abs(u) < 4.5:
            row = DIAMOND[int(17.99 - z)]
            ch = row[int(u + 4.5)]
            if ch != ".":
                return {"r": PAINT_RED[2], "t": TEAL[3], "T": TEAL[1], "o": CANVAS[4]}[ch]
        if 4 <= z < 5 or 22 <= z < 23:
            return PAINT_RED[2] if v > 0.4 else PAINT_RED[1]
        if 5 <= z < 6 or 21 <= z < 22:
            return TEAL[3] if v > 0.5 else TEAL[1]
        return tone(DRIFT[1:], v + (0.06 if int(th * r / 2.5) % 2 else 0), ix, iy, 0.12)
    sc.lathe(cx, cy, [(0, 9.0), (27, 8.5), (27, 0)], column)
    fur_roof(sc, cx, cy, 30.5, 16, 6, 9, 4.5)
    sc.lathe(cx, cy, [(38, 5.5), (56, 5.0), (56, 0)], totem_mat([(41, 53, "hex")]))
    fur_roof(sc, cx, cy, 58.5, 12, 4.5, 7, 3.5)
    sc.lathe(cx, cy, [(64, 4.0), (72, 3.8), (72, 0)], totem_mat([(64, 65, "red")]))


def _great_gate() -> None:
    """The Great Gate: a gate of tall rope-bound sharpened stakes with a carved eagle, two
    tower-totems with fur-fringed pagoda roofs and spread-winged eagles, two flaming torch
    totems with a rope of talismans between them, and the log palisade on either side."""
    W, H = 128, 112
    frames = []
    for fr in range(2):
        sc = Scene(W, H, 0, 104)
        # palisade: stacked horizontal logs and tall sharpened posts
        for x0, x1 in ((0, 30), (98, 128)):
            for z in range(2, 24, 3):
                sc.rod((x0, -7, z), (x1, -7, z), 1.4, WOOD[1:])
            for x in range(x0 + 4, x1, 9):
                sc.rod((x, -5, 0), (x, -5, 28), 1.8, WOOD[1:])
                sc.rod((x, -5, 28), (x, -5, 32), 0.6, WOOD[3:])
                sc.rod((x - 2, -3.6, 21), (x + 2, -3.6, 21), 0.4, HIDE[2:])
        # the stake gate
        for i, x in enumerate(range(47, 83, 3)):
            h = 42 + (3 if i % 2 else 0) - abs(i - 5.5) * 0.4
            sc.rod((x, -1, 0), (x, -1, h), 1.3, WOOD[1:])
            sc.rod((x, -1, h), (x, -1, h + 3.5), 0.5, WOOD[3:])
        for z in (8, 30):
            sc.rod((46, 0.5, z), (83, 0.5, z), 0.7, HIDE[2:])
        # torch totems (behind the towers, beside the gate)
        for x in (44, 84):
            sc.lathe(x, 1, [(0, 3.0), (54, 2.6), (54, 3.8), (57, 3.8), (57, 0)],
                     lambda th, z, r, v, ix, iy: (STONE[1] if z > 53.9 else
                                                  totem_mat([(8, 20, "hex"), (30, 31, "red"), (36, 48, "hex")])(th, z, r, v, ix, iy)))
        for x in (30, 98):
            gate_tower(sc, x, 3)
        p = sc.pic()
        # talisman rope sagging between the torch tops
        for x in range(45, 84):
            t = (x - 44) / 40
            y = int(round(104 - 55 + math.sin(t * math.pi) * 9))
            p.set(x, y, HIDE[1])
            if x % 5 == 2:
                c = [TEAL[3], PAINT_RED[2], BONE[4]][(x // 5) % 3]
                p.vline(x, y + 1, y + 2 + (x // 5) % 2, c)
        # carved eagle on the gate, eagles on the towers
        for ex, ey, dy in ((64, 70, 56), (30, 16, 2), (98, 16, 2)):
            tip = 2.0 if fr == 0 or ex == 64 else 5.0
            eagle_wing(p, ex - 1, -1, tip, True, dy=dy)
            eagle_wing(p, ex, 1, tip + 0.5, False, dy=dy)
            p.stamp(EAGLE[:13], {**_FACE_LG, "c": CANVAS[5], "C": CANVAS[3], "b": "gold2", "B": "gold1"}, ex - 5, dy + 3)
        # flames on the torch totems
        for x in (44, 84):
            flames(p, x + 0.3, 104 - 57, 3.2, 9, fr, 2, 90 + x)
        p.outline(skip=FIRE[2:])
        p.shadow(64, 106, 63, 4)
        frames.append(p)
    register("az.obj.great_gate", _art(frames, fps=4, note="the Great Gate: carved wooden eagle towers, stake gate, torch totems, palisade"))


# --- goblin wagon ------------------------------------------------------------------------------------


def _wagon() -> None:
    """A ravaged goblin caravan wagon: a boxy dark timber body, a rusty shingle roof with a
    hole, big iron-rimmed wheels (one torn off and lying in the grass), the shaft dropped."""
    W, H = 40, 24
    sc = Scene(W, H, 0, 20)
    P = box_frame(0.15)
    cx, cy, A, B = 17.0, -2.0, 10.0, 4.5

    def at(a, b, z):
        return P(cx, cy, a, b, z)

    def vec(a, b, z):
        return P(0, 0, a, b, z)

    def boards(u, w, lv, ix, iy):
        return WOOD[0] if (w * 9) % 3 < 0.9 else (WOOD[2] if lv > 0.45 else WOOD[1])
    sc.quad(at(-A, B, 4), vec(2 * A, 0, 0), (0, 0, 8), lambda u, w, lv, ix, iy: (
        DEEP if 0.62 < u < 0.8 and 0.3 < w < 0.75 else boards(u, w, lv, ix, iy)))
    sc.quad(at(A, B, 4), vec(0, -2 * B, 0), (0, 0, 8), boards)
    sc.quad(at(A, B, 12), vec(0, -2 * B, 0), (vec(0, -B, 0)[0], vec(0, -B, 0)[1], 4.5),
            lambda u, w, lv, ix, iy: WOOD[1], tri=True)

    def shingles(u, w, lv, ix, iy):
        if 0.25 < u < 0.42 and 0.3 < w < 0.75:
            return DEEP   # the hole torn in the roof
        row = int(w * 4)
        if (w * 4) % 1.0 < 0.22 or (u * 12 + row * 0.5) % 1.0 < 0.1:
            return RUST[1]
        return tone(RUST[1:], lv + (0.08 if (int(u * 12 + row * 0.5)) % 3 == 0 else 0), ix, iy, 0.12)
    for side in (1, -1):
        sc.quad(at(-A - 1, side * (B + 1), 11.2), vec(2 * A + 2, 0, 0),
                (vec(0, -side * (B + 1), 0)[0], vec(0, -side * (B + 1), 0)[1], 5.3), shingles)
    # chassis beam and wheels: iron rims, wooden spokes
    sc.rod(at(-A, B - 0.5, 3.6), at(A, B - 0.5, 3.6), 0.6, WOOD[0:3])

    def wheel(wx, wy, wz, radius):
        def fn(u, w):
            a, rr = u * math.tau, w * radius
            return (wx + math.cos(a) * rr, wy, wz + math.sin(a) * rr), (0, 1, 0)

        def mat(u, w, lv, ix, iy):
            if w > 0.78:
                return STEEL[3] if w > 0.9 and u < 0.5 else STEEL[2]
            if w < 0.25:
                return STEEL[2]
            return WOOD[2] if (u * 8) % 1.0 < 0.22 else None
        sc.surface(fn, 80, 16, mat)
    wx, wy, _ = at(-A + 3, B + 0.8, 0)
    wheel(wx, wy, 4.2, 4.2)
    # the torn-off wheel lying flat in the grass on the right, the shaft on the left
    lx, ly = cx + 15, 4.0
    sc.surface(lambda u, w: ((lx + math.cos(u * math.tau) * w * 4, ly + math.sin(u * math.tau) * w * 4, 0.4), (0, 0, 1)),
               80, 16, lambda u, w, lv, ix, iy: STEEL[3] if w > 0.8 else (STEEL[2] if w < 0.25 else
                                                                         WOOD[3] if (u * 8) % 1.0 < 0.25 else None))
    sc.rod(at(-A - 1, B - 2, 2), at(-A - 7, B + 3, 0.5), 0.6, WOOD[1:])
    sc.rod(at(-A + 7, B + 0.8, 4.2), at(-A + 7, B + 0.8, 0.5), 0.6, WOOD[0:3])   # a prop where the wheel was
    p = sc.pic()
    register("az.obj.wagon", _art(finish(p, 20, 21, 19, 2),
             note="ravaged goblin wagon: dark timber box, rusty shingle roof torn open, a wheel lost"))


def _extras() -> None:
    _water_well()
    _hide_longhouse()
    for v in range(2):
        _windbreak(v)
        _stake_row(v)
    _cave_mouth()
    _standing_stone()
    for v in range(3):
        _thorn_vine(v)


_buildings()
_camp()
_wilds()
_dressing()
_extras()
