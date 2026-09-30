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


def zigzag(colors: Sequence[str], mark: str, period: int = 4, scale: float = 1.0):
    """Painted band: ``colors`` shaded by light, a zigzag of ``mark`` through it."""
    def paint(x, y, u, t, v):
        base = colors[max(0, min(len(colors) - 1, int(v * len(colors) + 0.2)))]
        rows = 3
        r = min(rows - 1, int(t * rows))
        s = int(math.floor(math.asin(max(-1, min(1, u))) * scale * 8)) % period
        zig = {0: (0,), 1: (1, period - 1), 2: (period // 2,)}[r] if period == 4 else ()
        return mark if s in zig else base
    return paint


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


def lodge_poles(p: Pic, tops: Sequence[tuple[int, int, int, int]]) -> None:
    for x0, y0, x1, y1 in tops:
        pole(p, x0, y0, x1, y1)


# --- longhouse ----------------------------------------------------------------------------


def _hut_large() -> None:
    W, H = 48, 40
    p = Pic(W, H)
    cx, base = 24.0, 37.0
    # crossed poles above both ends (behind the hide: only the tips show)
    lodge_poles(p, [(4, 22, 12, 3), (14, 22, 6, 3), (34, 22, 42, 3), (44, 22, 36, 3)])
    zz = zigzag([RED[1], RED[2], RED[2], RED[3]], BONE[4])
    dome_shade(p, cx, base, 21.5, 23.5, HIDE[1:5], ribs=(-0.72, -0.45, 0.45, 0.72), flat=2.0,
               band=(-0.6, -0.47), paint=zz, seams=(-0.25,))
    # hem: earth piled against the hide
    for x in range(3, 45):
        if p.get(x, 36):
            p.set(x, 36, HIDE[1])
            p.set(x, 37 - (1 if bayer(x, 3) > 0.7 else 0), MESA[2] if x < 24 else MESA[1])
    # blue sun discs painted either side of the door
    for sx in (11, 36):
        p.ellipse(sx + 0.5, 28.5, 3.2, 3.2, lambda x, y, sx=sx: BLUE[2] if x + y < 40 + (sx - 11) else BLUE[1])
        p.ellipse(sx + 0.5, 28.5, 1.5, 1.5, lambda x, y: BONE[4])
    # door: timber posts, dark arch, tusks, skull
    p.rect(17, 19, 2, 18, lambda x, y: WOOD[3] if x == 17 else WOOD[1])
    p.rect(29, 19, 2, 18, lambda x, y: WOOD[3] if x == 29 else WOOD[1])
    p.hline(16, 31, 18, WOOD[4])
    p.hline(16, 31, 19, WOOD[2])
    door_arch(p, 19, 28, 20, 36, glow="fire2")
    # hide flap tied back on the left of the doorway
    p.poly([(19, 20), (23, 20), (19, 31)], lambda x, y: HIDE[4] if x < 20 else HIDE[3])
    p.line(19, 31, 22, 21, HIDE[2])
    tusk_pair(p, 15, 32, 36, 12)
    skull(p, 24, 11)
    p.outline()
    p.shadow(24, 38.2, 23, 2.2)
    register("az.obj.hut_large", _art(p, note="tauren hide-and-timber longhouse: bone-framed door, painted band"))


# --- small huts ---------------------------------------------------------------------------------


def _hut_small(v: int) -> None:
    W, H = 32, 32
    p = Pic(W, H)
    hide = HIDE[1:5] if v == 0 else SAND[1:5]
    band = [RED[1], RED[2], RED[2], RED[3]] if v == 0 else [BLUE[0], BLUE[1], BLUE[2], BLUE[3]]
    lodge_poles(p, [(9, 16, 18, 2), (22, 16, 13, 2), (15, 14, 15, 1)] if v == 0 else
                [(8, 16, 17, 3), (23, 16, 14, 3)])
    dome_shade(p, 16, 29.5, 13.5, 18 if v == 0 else 16, hide, ribs=(-0.55, 0.0, 0.55),
               band=(-0.58, -0.44), paint=zigzag(band, BONE[4] if v == 0 else RED[3]))
    # smoke hole ring near the top
    top = 12 if v == 0 else 14
    p.hline(14, 17, top + 1, WOOD[1])
    p.hline(14, 17, top, WOOD[4])
    # doorway
    p.rect(11, 18, 1, 11, WOOD[3])
    p.rect(20, 18, 1, 11, WOOD[1])
    door_arch(p, 12, 19, 18, 28, glow="fire1" if v == 0 else None)
    if v == 0:
        p.poly([(12, 18), (15, 18), (12, 26)], lambda x, y: hide[3] if x < 13 else hide[2])
        tusk_pair(p, 10, 21, 28, 8)
    else:
        # rolled-up door flap across the top of the doorway, hoof marks painted beside
        p.hline(11, 20, 18, hide[3])
        p.hline(11, 20, 19, hide[2])
        for hx, hy in ((6, 22), (24, 22)):
            p.stamp(["r.r", "r.r"], {"r": RED[2]}, hx, hy)
    for x in range(3, 29):
        if p.get(x, 28) and p.get(x, 28) not in (DEEP, "ink"):
            p.set(x, 29, MESA[2] if x < 16 else MESA[1])
    p.outline()
    p.shadow(16, 30.4, 15, 1.8)
    register(f"az.obj.hut_small@{v}", _art(p, note="small tauren hut: hide dome on bent poles"))


# --- tipis -------------------------------------------------------------------------------------------


def _tent(v: int) -> None:
    W, H = 32, 28
    p = Pic(W, H)
    ax, ay, base, half = 16.0, 4.0, 25.0, 12.5
    hide = [HIDE[1:5], SAND[1:5], HIDE[0:4]][v]
    for x0, x1 in ((16, 10), (16, 21), (15, 15), (17, 13)):  # pole tips above the smoke flap
        pole(p, x0, 8, x1, 0)
    for y in range(int(ay), int(base) + 1):
        t = (y + 0.5 - ay) / (base - ay)
        hw = half * t
        for x in range(W):
            u = (x + 0.5 - ax) / max(0.8, hw)
            if abs(u) > 1:
                continue
            nz = math.sqrt(max(0.0, 1 - u * u))
            vv = (lambert(u, -0.35, nz) + 0.3) / 1.25
            lvl = vv * len(hide) - 0.4 + (bayer(x, y) - 0.5) * 0.5
            for s in (-0.5, 0.5):  # pole ridges under the hide
                d = (u - s) * hw
                if -1 <= d < 0:
                    lvl += 1
                elif 0 <= d < 1:
                    lvl -= 1
            c = hide[max(0, min(len(hide) - 1, int(round(lvl))))]
            xs = int(math.floor(math.asin(u) * 9))
            if v == 0:
                if 17 <= y <= 19:  # red band, white zigzag
                    r = y - 17
                    c = (BONE[4] if xs % 4 in ((0,), (1, 3), (2,))[r] else (RED[2] if vv > 0.45 else RED[1]))
                elif y >= 23 and (xs % 4) < 2 and (y - 23) <= (1 - xs % 2):
                    c = RED[2] if vv > 0.45 else RED[1]
            elif v == 1:
                if y in (14, 21):
                    c = BLUE[2] if vv > 0.45 else BLUE[1]
                elif 16 <= y <= 19 and xs % 6 in (1, 2, 3) and (y in (17, 18) or xs % 6 == 2):
                    c = BONE[4] if y == 16 or xs % 6 == 1 else BONE[3]  # sun discs
            else:
                if 9 <= y <= 12 and (y - 9 + xs) % 3 == 0:
                    c = BONE[3]  # white rays near the top
                if y == 20 or y == 22:
                    c = RED[2] if vv > 0.45 else RED[1]
            p.set(x, y, c)
    # smoke flaps open at the top
    p.stamp(["hH.Hh", ".H.H."], {"h": hide[3], "H": hide[1]}, 14, 6)
    # doorway: a triangle flap folded back
    p.poly([(13, 25.9), (19, 25.9), (16, 15)], DEEP)
    p.poly([(12.5, 25.9), (15, 25.9), (16, 15)], lambda x, y: hide[3] if x < 14 else hide[2])
    p.line(16, 15, 16, 25, "ink")
    p.hline(2, 29, 25, lambda x, y: step(hide, p.get(x, y), -1))
    # stakes
    for sx in (3, 28):
        p.set(sx, 26, WOOD[3])
    p.outline()
    p.shadow(16, 26.3, 15, 1.7)
    register(f"az.obj.tent@{v}", _art(p, note=["hide tipi, red zigzag band", "orange hide tipi, blue sun band",
                                                "dark hide tipi, white rays"][v]))


# --- inn ---------------------------------------------------------------------------------------------


def _inn() -> None:
    W, H = 48, 40
    p = Pic(W, H)
    lodge_poles(p, [(14, 16, 24, 1), (32, 16, 22, 1), (20, 12, 25, 0), (28, 12, 21, 0)])
    zz = zigzag([RED[1], RED[2], RED[2], RED[3]], BONE[4])
    dome_shade(p, 23.5, 37, 20.5, 27, HIDE[1:5], ribs=(-0.66, -0.33, 0.0, 0.33, 0.66),
               band=(-0.78, -0.68), paint=zz, seams=(-0.45,))
    p.hline(20, 27, 10, WOOD[4])
    p.hline(20, 27, 11, WOOD[1])
    # hide awning over the door on two poles
    p.poly([(12, 21), (35, 21), (38, 26), (9, 26)],
           lambda x, y: tone(TENT[1:], 0.8 - (x - 9) / 45 - (y - 21) * 0.05, x, y, 0.1))
    p.hline(9, 38, 26, TENT[1])
    for x in range(10, 38, 4):
        p.set(x, 27, TENT[2])
    for px_ in (11, 36):
        p.vline(px_, 27, 36, WOOD[3])
        p.vline(px_ + 1, 27, 36, WOOD[1])
    door_arch(p, 18, 29, 27, 36, glow="win_warm")
    # sign on a post at the right: a mug of ale
    p.vline(43, 20, 37, WOOD[3])
    p.vline(44, 20, 37, WOOD[1])
    p.hline(38, 45, 20, WOOD[4])
    p.stamp(["kkkkkkk", "kpppppk", "kpyyGpk", "kpyYGyk", "kpyYGpk", "kpppppk", "kkkkkkk"],
            {"p": WOOD[4], "y": "gold2", "Y": "gold1", "G": BONE[4]}, 38, 22)
    p.set(40, 21, "ink")
    p.set(44, 21, "ink")
    for x in range(3, 45):
        if p.get(x, 36) in HIDE:
            p.set(x, 37, MESA[2] if x < 24 else MESA[1])
    p.outline(skip=())
    p.shadow(24, 38.3, 23, 2)
    register("az.obj.inn", _art(p, note="tauren inn: tall hide lodge, awning, warm doorway, ale sign"))


def _buildings() -> None:
    _hut_large()
    for v in range(2):
        _hut_small(v)
    for v in range(3):
        _tent(v)
    _inn()



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


# --- totem poles ----------------------------------------------------------------------------------

_CARVE = {"h": WOOD[4], "H": WOOD[5], "m": WOOD[3], "d": WOOD[1], "D": WOOD[0], "o": BONE[4],
          "y": "gold2", "Y": "gold1", "t": BONE[3], "T": BONE[2]}
FACE_BEAR = [
    ".hhhhhhhhd.",
    "hmdddmdddmD",
    "hmokdmokddD",
    "hrrmmhmmRRD",
    ".mmmmhmmmD.",
    ".mkkkkkkkD.",
    ".mkokokokD.",
    ".mmkkkkkmD.",
    "..ddddddD..",
]
FACE_BIRD = [
    "hhhhhhhhhdD",
    "hbbbhmmbbBD",
    "hbokbmbokBD",
    "hbbbmmmBBBD",
    ".mmmyyymmD.",
    "..mmyYYmD..",
    "...mYYYD...",
    ".rrrrrRRRD.",
    "..ddddddD..",
]
FACE_WOLF = [
    "H.........D",
    "hh.......dD",
    "hmhhhhhmmdD",
    "hmokmmmokdD",
    ".mmmmhmmmD.",
    "..mmmhmmD..",
    "..mkkkkkD..",
    "..boooooB..",
    "...ddddD...",
]
WINGS = [
    "r.......",
    "rr......",
    "brr.....",
    ".bbrm...",
    "..bbrmm.",
    "...bbrmm",
    ".....rhm",
    "......hm",
]
TOTEM_PAINT = [{"r": RED[2], "R": RED[1], "b": BLUE[2], "B": BLUE[1]},
               {"r": BLUE[2], "R": BLUE[1], "b": RED[2], "B": RED[1]},
               {"r": "gold2", "R": "gold1", "b": LEAF[3], "B": LEAF[2]}]


def _totem(v: int) -> None:
    W, H = 16, 40
    p = Pic(W, H)
    lg = {**_CARVE, **TOTEM_PAINT[v]}
    top = 8
    for y in range(top, 37):
        for x in range(5, 11):
            p.set(x, y, cyl(WOOD[1:5], x, 5, 10, y))
    faces = [[FACE_BIRD, FACE_BEAR], [FACE_BEAR, FACE_WOLF], [FACE_WOLF, FACE_BIRD]][v]
    y = 10
    for face in faces:
        p.stamp(face, lg, 2, y)
        y += 10
    # painted rings near the foot
    for yy, key in ((y + 1, "r"), (y + 3, "b")):
        for x in range(5, 11):
            p.set(x, yy, step([lg[key.upper()], lg[key]], lg[key], 0 if x < 8 else -1))
    if v == 0:  # thunderbird with spread wings
        wing = [row + row[::-1] for row in WINGS]
        p.stamp(wing, lg, 0, 2)
        for x in range(8, 16):  # right wing in shade
            for yy in range(2, 10):
                p.set(x, yy, lambda xx, y2: {lg["r"]: lg["R"], lg["b"]: lg["B"], WOOD[3]: WOOD[2],
                                            WOOD[4]: WOOD[3]}.get(p.get(xx, y2), p.get(xx, y2)))
        p.stamp([".hmd.", "hokmd", "hmmmd", ".yYd.", "..Y.."], lg, 6, 0)
    elif v == 1:  # kodo skull with sweeping horns on top
        p.rect(5, 7, 6, 3, lambda x, y: cyl(WOOD[1:5], x, 5, 10, y))
        skull(p, 8, 0)
    else:  # drum-shaped cap hung with feathers
        p.stamp(["..hhhhhhhhhd..", ".hmmmmmmmmmmd.", "hmrrrrrrrRRRdD", ".dddddddddddD."], lg, 1, 4)
        for fx, fy in ((1, 8), (4, 9), (11, 9), (14, 8)):
            p.vline(fx, fy, fy + 3, BONE[4] if fx < 8 else BONE[3])
            p.set(fx, fy + 4, RED[2])
        p.stamp(["..H..", ".hmd.", "hmmmd"], lg, 5, 1)
    # stones heaped around the foot
    p.stamp(["..abb.ab.abb..", ".abbcabbcabbc.", "abbccbbccbbccc"],
            {"a": STONE[4], "b": STONE[3], "c": STONE[1]}, 1, 36)
    p.outline()
    p.shadow(8, 39, 7, 1)
    register(f"az.obj.totem_pole@{v}", _art(p, note=["totem: thunderbird, owl and bear",
                                                     "totem: kodo skull, bear and wolf",
                                                     "totem: feathered drum, wolf and bird"][v]))


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


def _stable() -> None:
    p = Pic(40, 32)
    # back wall of hide, shadowed under the roof
    p.rect(4, 10, 32, 19, lambda x, y: tone(HIDE[0:3], 0.8 - (y - 10) * 0.03 - x * 0.006, x, y, 0.08))
    # hay heaped in the left stall
    p.ellipse(11, 29, 7, 5, lambda x, y: tone(SAND[1:], 1.0 - (y - 24) * 0.12 - (x - 4) * 0.02, x, y, 0.4))
    for x in range(6, 17, 3):
        p.set(x, 24 + (x % 2), SAND[4])
    # water trough in the right stall
    p.rect(24, 24, 11, 5, lambda x, y: WOOD[3] if y == 24 else (WOOD[2] if x < 33 else WOOD[1]))
    p.hline(25, 33, 25, WATER[3])
    p.set(26, 25, WATER[5])
    # stall divider rails
    for ry in (18, 23):
        p.hline(4, 35, ry, WOOD[4])
        p.hline(4, 35, ry + 1, WOOD[2])
    for px_ in (3, 19, 36):
        p.vline(px_, 9, 29, WOOD[3])
        p.vline(px_ + 1, 9, 29, WOOD[1])
    # slanted hide roof on the frame, poles crossed at both ends
    pole(p, 2, 9, 6, 0)
    pole(p, 8, 9, 3, 0)
    pole(p, 32, 9, 37, 0)
    pole(p, 38, 9, 33, 0)
    p.poly([(4, 3), (36, 3), (39.5, 10), (0.5, 10)],
           lambda x, y: tone(HIDE[1:5], 0.95 - (y - 3) * 0.06 - x * 0.008, x, y, 0.08))
    for x in range(1, 39):
        p.set(x, 10, HIDE[1])
        if x % 4 == 1:
            p.set(x, 11, HIDE[2])
    p.hline(4, 36, 3, WOOD[4])
    for x in (10, 20, 30):  # red painted marks along the eave
        p.stamp(["rRr", ".r."], {"r": RED[2], "R": RED[3]}, x, 6)
    for x in range(4, 36):
        p.set(x, 29, MESA[2] if p.get(x, 29) is None or x % 3 else MESA[1])
    p.outline()
    p.shadow(20, 30.5, 20, 1.5)
    register("az.obj.stable", _art(p, note="stable: hide roof on poles, hay and trough stalls"))


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


def _great_gate() -> None:
    frames = []
    W, H = 64, 48
    for fr in range(2):
        p = Pic(W, H)
        for tx in (1, 47):  # towers: log walls on a stone footing, hide cone roofs
            _log_wall(p, tx, 12, tx + 15, 37, False, dark=0.35)
            _stone_blocks(p, tx, 36, tx + 15, 46, lit=0.85)
            for x0, y0, x1, y1 in ((tx + 3, 10, tx + 9, 0), (tx + 12, 10, tx + 6, 0)):
                pole(p, x0, y0, x1, y1)
            p.poly([(tx + 7.5, 2), (tx - 0.8, 13), (tx + 16.8, 13)],
                   lambda x, y, tx=tx: tone(HIDE[1:5], 0.95 - (x - tx) * 0.05, x, y, 0.1))
            p.hline(tx - 1, tx + 16, 13, HIDE[1])
            for x in range(tx + 1, tx + 15, 3):
                p.set(x, 12, RED[2])
            # a hanging Horde banner on each tower
            p.rect(tx + 4, 15, 8, 16, lambda x, y, tx=tx: RED[2] if x < tx + 10 else RED[1])
            p.hline(tx + 3, tx + 12, 14, WOOD[4])
            for i in range(4):
                p.clear(tx + 4 + i, 30 - (3 - i) if i < 4 else 30)
                p.clear(tx + 11 - i, 30 - (3 - i))
            p.stamp(HORDE, {}, tx + 5, 19)
        # the gate: a lintel beam and two doors of upright logs, iron bands, a skull emblem
        p.rect(15, 11, 34, 4, lambda x, y: [WOOD[4], WOOD[3], WOOD[2], WOOD[1]][y - 11])
        _log_wall(p, 18, 15, 45, 46, True)
        for x in range(18, 46):
            p.set(x, 15, WOOD[1])
            if (x - 18) % 3 == 1:
                p.set(x, 16, WOOD[5])  # sharpened tops catching the light
        p.vline(31, 16, 46, "ink")
        p.vline(32, 16, 46, WOOD[1])
        for by in (23, 38):
            p.hline(18, 45, by, STEEL[3])
            p.hline(18, 45, by + 1, STEEL[1])
            for x in range(19, 46, 4):
                p.set(x, by, STEEL[5])
        skull(p, 32, 26)
        # tusks rising either side of the doors
        for i in range(30):
            t = i / 29
            off = round(math.sin(t * math.pi * 0.8) * 3)
            y = 46 - i
            p.set(17 - off, y, BONE[4])
            p.set(46 + off, y, BONE[3])
            if i < 20:
                p.set(16 - off, y, BONE[3])
                p.set(47 + off, y, BONE[2])
        # torches on the towers' inner faces, flickering
        for tx in (14, 49):
            p.vline(tx, 19, 23, WOOD[2])
            p.stamp(["ab.", ".c.", ".b."] if fr == 0 else [".ba", ".c.", ".b."],
                    {"a": FIRE[3], "b": FIRE[4], "c": FIRE[5]}, tx - 1, 16)
            p.set(tx, 15, FIRE[2] if fr == 0 else None)
        p.outline(skip=FIRE[2:])
        p.shadow(32, 47, 32, 1)
        frames.append(p)
    register("az.obj.great_gate", _art(frames, fps=4, note="the Great Gate: log towers, tusks, banners, torches"))


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


def _wagon() -> None:
    W, H = 40, 24
    p = Pic(W, H)

    def bed(x: float) -> int:
        return 13 + int((x - 3) * 4 // 31)
    # canvas cover over hoops, a hole torn in it; the last two hoops stand bare
    for x in range(5, 25):
        hoop = (x - 5) % 7
        top = bed(x) - 9 + (1 if hoop in (3, 4) else 0) + (1 if x in (5, 24) else 0)
        for y in range(top, bed(x)):
            t = (y - top) / 9
            c = tone(BONE[1:], 0.95 - t * 0.55 - (x - 5) * 0.01, x, y, 0.08)
            if hoop == 0 and y > top:
                c = step(BONE, c, -1)  # the hoop under the cloth
            p.set(x, y, c)
    for y in range(bed(17) - 7, bed(17) - 3):
        for x in range(15, 21):
            if abs(x - 17.5) + abs(y - (bed(17) - 5)) * 0.8 < 3.2:
                p.set(x, y, DEEP)
    for hx in (27, 32):  # bare hoops
        for a in range(0, 25):
            t = a / 24 * math.pi
            x = round(hx + 2.5 - math.cos(t) * 2.5)
            y = round(bed(hx) - math.sin(t) * 8)
            p.set(x, y, WOOD[3] if x <= hx + 2 else WOOD[2])
    for x, ln in ((24, 3), (22, 2), (26, 4)):  # tatters of cloth
        p.vline(x, bed(x) - 8, bed(x) - 8 + ln, BONE[2])
    # the bed, sagging to the right where the wheel broke off
    for x in range(3, 35):
        y = 13 + (x - 3) * 4 // 31
        p.set(x, y, WOOD[4])
        p.set(x, y + 1, WOOD[3])
        p.set(x, y + 2, WOOD[1])
    # intact wheel
    p.ellipse(10, 18.5, 5, 5, WOOD[2])
    for y in range(p.h):
        for x in range(p.w):
            d = math.hypot(x + 0.5 - 10, y + 0.5 - 18.5)
            if 3.2 < d <= 3.8:
                p.clear(x, y)
    p.line(10, 14, 10, 23, WOOD[3])
    p.line(5, 18, 15, 18, WOOD[3])
    p.line(7, 15, 13, 21, WOOD[2])
    p.line(13, 15, 7, 21, WOOD[2])
    p.set(10, 18, WOOD[5])
    # the broken wheel on the ground and spilled cargo
    p.ellipse(33, 22, 5.5, 1.6, WOOD[2])
    p.ellipse(33, 22, 3.5, 0.8, WOOD[0])
    p.rect(27, 17, 5, 4, lambda x, y: WOOD[4] if y == 17 else WOOD[3])
    p.ellipse(22.5, 21, 3, 2, lambda x, y: SAND[3] if x < 23 else SAND[2])
    p.line(33, 15, 36, 20, WOOD[3])  # snapped axle
    p.outline()
    p.shadow(20, 23, 19, 1)
    register("az.obj.wagon", _art(p, note="ravaged caravan wagon: torn cover, lost wheel, spilled cargo"))


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


_buildings()
_camp()
_wilds()
_dressing()
