"""Azeroth / Mulgore art: thunder bluff. Must satisfy
``wilds.azeroth.manifest.required()["thunder_bluff"]`` (see docs/azeroth/mulgore-art-manifest.md).

Thunder Bluff is built on windswept mesas high above the plains: plank-and-hide decks,
rope bridges between the rises, and the tallest things in Mulgore - hide lodges on timber
ribs, painted totems, tents, the Hunter's Hall. Tiles are seamless 16x16 textures (seeded,
no outline); buildings are composed on a ``Canvas`` from shaded shapes and small stamps,
then outlined in ``ink`` in one pass and given a soft ground shadow.
"""

from __future__ import annotations

import math
import random

from ..palette import _ramp
from ..pixelart import art, outline_grid
from ..procgen import Canvas, bayer, fbm
from ..registry import register

T = 16

# Weathered grey-brown timber (planks, poles, logs): distinct from the red mesa rock.
_ramp("azb_wood", "#2a1a16", "#4a2f22", "#6e4a32", "#936644", "#b98a5c", "#dcb482")
# Tanned kodo hide (lodge roofs, tents, mats): warm cream, shadows lean red-brown.
_ramp("azb_hide", "#5a3a2a", "#8a6446", "#b8916a", "#dcc094", "#f4e2bc")

# Thunder Bluff as it really looks (v4): teal-painted roof boards, the pale tan-grey cliffs
# the rises stand on, and the dark mountain pines with sunlit tips that grow on top.
_ramp("azb_teal", "#173c44", "#24606a", "#3a8a8e", "#62b3ad", "#a3dacb")
_ramp("azb_cliff", "#3b3431", "#5f5650", "#867b70", "#ab9f8f", "#cdc1ad", "#ebe0cb")
_ramp("azb_pine", "#0e2016", "#173522", "#234d2d", "#336839", "#558a45", "#a8b25a")

# One legend for the whole city. Digits = wood, a-e = hide, r/R/q = Horde red,
# h/i/j/J = bone and horn, t/T = turquoise paint, m/M/n = mesa rock, v/V = the drop.
TB = {
    "0": "azb_wood0", "1": "azb_wood1", "2": "azb_wood2", "3": "azb_wood3", "4": "azb_wood4",
    "5": "azb_wood5",
    "a": "azb_hide0", "b": "azb_hide1", "c": "azb_hide2", "d": "azb_hide3", "e": "azb_hide4",
    "r": "red1", "R": "red2", "q": "red3",
    "h": "bone1", "i": "bone2", "j": "bone3", "J": "bone4",
    "t": "cryst0", "T": "cryst1",
    "m": "dust1", "M": "dust2", "n": "dust3", "N": "dust4",
    "o": "rock1", "O": "rock2", "p": "rock3", "P": "rock4",
    "g": "moss3", "G": "moss4",
    "v": "void", "V": "ink2",
    "f": "fire3", "F": "fire4",
    "x": "glowcyan", "y": "water4", "Y": "water5", "u": "water3", "U": "water2",
    "s": "white:70", "S": "glowcyan:90",
    "z": "ink:96",
    # clay (pots, braziers), flames, soft glows
    "A": "tent0", "B": "tent1", "C": "tent2", "D": "tent3", "E": "tent4",
    "Q": "fire2", "W": "fire5", "l": "fire1",
    "X": "water5:190", "H": "water5:120", "Z": "glowcyan:210",
    # teal roof boards
    "6": "azb_teal0", "7": "azb_teal1", "8": "azb_teal2", "9": "azb_teal3", "%": "azb_teal4",
}


def _stamp(c: Canvas, x: int, y: int, rows, wrap: bool = False) -> None:
    """Paint a small pattern (``.`` = keep) at (x, y)."""
    if isinstance(rows, str):
        rows = [r.strip() for r in rows.strip().splitlines()]
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == ".":
                continue
            if wrap:
                c.set((x + i) % c.w, (y + j) % c.h, ch)
            else:
                c.set(x + i, y + j, ch)


def _finish(c: Canvas, shadow: tuple[float, float, float, float] | None = None) -> Canvas:
    """Outline every opaque pixel in ink, then lay a soft ground shadow (cx, cy, rx, ry)."""
    g = Canvas.of(outline_grid(c.grid(), "k"))
    if shadow:
        cx, cy, rx, ry = shadow
        for y in range(g.h):
            for x in range(g.w):
                nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                if nx * nx + ny * ny <= 1 and g.px[y][x] == ".":
                    g.px[y][x] = "z"
    return g


def _outlined(c: Canvas, draw, *args) -> None:
    """Draw a piece on its own layer, outline it in ink and paste it: horns and skulls
    must stand out against the pale hide behind them."""
    layer = Canvas(c.w, c.h)
    draw(layer, *args)
    c.blit(outline_grid(layer.grid(), "k"))


# --- the platform tileset ------------------------------------------------------------------
# Boards run east-west in three rows of uneven height (gaps at y = 0, 5, 10), identical in
# every floor, edge and inlay tile, so they join in both directions whatever variant the
# renderer picks. What breaks the grid:
# - 0-2 butt joints per board per tile, anywhere (a joint on column 0 is allowed), so
#   boards run 5 to 40+ px long;
# - only a board piece closed by joints on both sides may be darker (worn) or lighter
#   (new); a piece touching the tile border keeps the base tone, so it continues
#   seamlessly into any neighbour;
# - grain is the tile's own noise in the middle, blended into one shared profile on the
#   two border columns;
# - knots, lashings, pegs and hide patches are rare, small, low-contrast and in a
#   different place in each variant.

BOARDS = ((1, 4), (6, 9), (11, 15))   # (top, bottom) row of each board; the rest are gaps
_SHARED = fbm(T, T, 4242, 2, 4)


def _grain(seed: int) -> list[list[float]]:
    """Grain streaking along the boards, forced to the shared profile at the borders."""
    rng = random.Random(seed)
    own = fbm(T, T, seed, 2, 4)
    streak = [rng.random() for _ in range(T)]
    out = []
    for y in range(T):
        row = []
        for x in range(T):
            w = max(0.0, 1.0 - min(x, T - 1 - x) / 3.0)
            v = 0.6 * own[y][x] + 0.4 * streak[y]
            row.append(v * (1 - w) + _SHARED[y][x] * w)
        out.append(row)
    return out


def _boards(c: Canvas, seed: int, boards=BOARDS, worn: int = 1) -> list[tuple[int, int, int]]:
    """Paint the boards; return the joints as (board index, x, tone of the piece right of it)."""
    rng = random.Random(seed)
    g = _grain(seed)
    joints_out = []
    for y in range(T):  # gaps between boards
        if not any(a <= y <= b for a, b in boards):
            for x in range(T):
                c.set(x, y, "0" if bayer(x, y) < 0.8 else "1")
    for bi, (a, b) in enumerate(boards):
        n = rng.choices((0, 1, 2), (3, 5, 3))[0]
        joints: list[int] = []
        for _ in range(n):
            for _try in range(12):
                j = rng.randrange(0, T - 1)
                if all(abs(j - k) >= 5 for k in joints):
                    joints.append(j)
                    break
        joints.sort()
        # tones of the pieces: only closed pieces (joint on both sides) may differ
        tone = [0] * T
        for k in range(len(joints) - 1):
            t = rng.choice((-1, -1, 1, 0)) if worn else 0
            for x in range(joints[k] + 1, joints[k + 1]):
                tone[x] = t
        for y in range(a, b + 1):
            r = y - a
            for x in range(T):
                gv = g[y][x] + (bayer(x, y) - 0.5) * 0.22
                lvl = 2 + tone[x]
                if r == 0:
                    lvl += 1 if gv > 0.4 else 0
                elif y == b:
                    lvl -= 1 if gv < 0.5 else 0
                else:
                    lvl += 1 if gv > 0.82 else -1 if gv < 0.12 else 0
                c.set(x, y, str(max(1, min(4, lvl))))
        for j in joints:  # the butt joint: a dark seam, a lit end on the next board
            c.vline(j, a, b, "1")
            c.set(j, b, "0")
            if j + 1 < T:
                c.set(j + 1, a, str(max(1, min(4, 3 + tone[j + 1]))))
            joints_out.append((bi, j, tone[min(T - 1, j + 1)]))
    return joints_out


def _pegs(c: Canvas, joints, rng: random.Random, boards=BOARDS) -> None:
    """Wooden pegs holding a board end: a dark dot beside some joints."""
    for bi, j, _t in joints:
        a, b = boards[bi]
        if rng.random() < 0.6 and 1 <= j - 1 <= T - 2:
            c.set(j - 1, (a + b) // 2, "0")


def _knot(c: Canvas, x: int, y: int) -> None:
    _stamp(c, x, y, ["12", "01"])


def _lashing(c: Canvas, x: int, gap_y: int) -> None:
    """Rope binding across a gap: two turns of rope, lit on top."""
    _stamp(c, x, gap_y - 1, ["ba", "cb", "ba"])


def _patch(c: Canvas, x: int, y: int) -> None:
    """A small hide patch nailed over a worn spot, low contrast, pegged at the corners."""
    _stamp(c, x, y, ["0bbbb0", ".bccb.", "0abba0"])


def _crack(c: Canvas, x: int, y: int, n: int) -> None:
    for i in range(n):
        c.set(x + i, y + (1 if i % 3 == 2 else 0), "1")


def _floor(i: int) -> Canvas:
    seed = 1000 + i * 37
    rng = random.Random(seed + 1)
    c = Canvas(T, T)
    joints = _boards(c, seed)
    _pegs(c, joints, rng)
    extras = (
        [], ["knot"], ["lash"], ["patch"], ["knot", "crack"], ["lash"], [], ["crack"],
    )[i]
    for e in extras:
        if e == "knot":
            b = BOARDS[rng.randrange(3)]
            _knot(c, rng.randrange(3, 11), b[0] + 1)
        elif e == "lash":
            _lashing(c, rng.randrange(3, 12), rng.choice((5, 10)))
        elif e == "patch":
            _patch(c, rng.randrange(2, 8), rng.choice((6, 11)))
        elif e == "crack":
            b = BOARDS[rng.randrange(3)]
            _crack(c, rng.randrange(2, 7), b[0] + 1, rng.randrange(4, 7))
    _balance(c, seed)
    return c


FLOOR_LUMA = 74.0


def _balance(c: Canvas, seed: int) -> None:
    """Nudge interior grain pixels one step so every floor variant has the same mean
    brightness (the border columns are never touched)."""
    rng = random.Random(seed + 99)
    cells = [(x, y) for y in range(T) for x in range(2, T - 2)]
    rng.shuffle(cells)
    for x, y in cells:
        d = _luma(c) - FLOOR_LUMA
        if abs(d) < 0.3:
            return
        ch = c.get(x, y)
        if d < 0 and ch in "12":
            c.set(x, y, str(int(ch) + 1))
        elif d > 0 and ch in "34":
            c.set(x, y, str(int(ch) - 1))


def _luma(c: Canvas) -> float:
    from ..palette import rgb
    tot = 0.0
    for row in c.px:
        for ch in row:
            r, g, b = rgb(TB[ch].partition(":")[0])
            tot += 0.3 * r + 0.59 * g + 0.11 * b
    return tot / (c.w * c.h)


def _platform() -> None:
    """Eight plank-and-hide floor tiles (see the tileset notes above)."""
    for i in range(8):
        register(f"az.tb.platform@{i}", art(_floor(i).grid(), legend=TB, note="plank-and-hide platform floor"))


# Painted inlay for plazas. The game paints whole plazas with it, so it is a quiet,
# worn pattern rather than a medallion per tile: a diamond lattice of red lines that runs
# on across every border (x + y and x - y are periodic in 16), with a small accent in the
# middle of each diamond (the tile centre) that differs per variant. Paint is thin and scuffed; the boards
# and their seams show through.
INLAY_ACCENTS = (
    ["..t..", ".tTt.", "tTeTt", ".tTt.", "..t.."],   # turquoise diamond
    [".rRr.", "rR.Rr", "R.e.R", "rR.Rr", ".rRr."],   # red sun ring
    ["e...e", ".e.e.", "..e..", ".....", "..t.."],   # cream chevron over a turquoise dot
)


def _inlay() -> None:
    for i, accent in enumerate(INLAY_ACCENTS):
        c = _floor((1, 6, 7)[i])
        wear = random.Random(3000 + i)
        for y in range(T):
            for x in range(T):
                # the diamond's corners sit on the middle of each tile border
                if (x + y) % T != 7 and (x - y) % T != 8:
                    continue
                ch = "R" if (x + y) % T == 7 else "r"  # lines facing the light are brighter
                if wear.random() < 0.18:
                    continue  # scuffed off
                if c.get(x, y) in "01":
                    ch = "r" if ch == "R" else "l"
                c.set(x, y, ch)
        for j, row in enumerate(accent):  # the accent in the middle of the diamond
            for k, ch in enumerate(row):
                if ch == "." or wear.random() < 0.1:
                    continue
                x, y = 6 + k, 6 + j
                if c.get(x, y) in "01":
                    ch = {"R": "r", "T": "t", "e": "d", "r": "l"}.get(ch, ch)
                c.set(x, y, ch)
        register(f"az.tb.platform.inlay@{i}", art(c.grid(), legend=TB, note="painted tribal floor inlay (plazas)"))


def _under_deck(c: Canvas, y0: int) -> None:
    """The dark under the deck: a fixed dithered fall-off (the same on every column
    phase, so any two edge variants join)."""
    for y in range(y0, T):
        depth = (y - y0) / max(1, T - 1 - y0)
        for x in range(T):
            v = 1 - depth + (bayer(x, y) - 0.5) * 0.5
            c.set(x, y, "0" if v > 0.85 else "V" if v > 0.35 else "v")


def _platform_edge() -> None:
    """South rim of a wooden deck: the last board row, a thick fascia log lashed with
    rope, and under it the deck's timber posts and braces fading into the drop. Six
    variants move the posts and lashings and add a charm, a loose rope, a board end
    jutting out or a hide strip hung over the edge."""
    extras = [None, "charm", "rope", "jut", "brace", "hide"]
    for i in range(6):
        seed = 1100 + i * 5
        rng = random.Random(seed)
        c = Canvas(T, T)
        _under_deck(c, 10)
        joints = _boards(c, 1500 + i * 13, boards=((1, 4),))
        _pegs(c, joints, rng, boards=((1, 4),))
        for x in range(T):
            c.set(x, 5, "0")
        bark = fbm(T, 1, 77, 2, 4)[0]  # shared by every variant: the log runs on seamlessly
        for x in range(T):  # the fascia log: lit top, bark, shadowed underside
            c.set(x, 6, "5" if bark[x] > 0.6 else "4")
            c.set(x, 7, "4" if bark[(x + 5) % T] > 0.55 else "3")
            c.set(x, 8, "3" if bark[(x + 9) % T] > 0.5 else "2")
            c.set(x, 9, "1")
        # posts under the deck, never on the border columns
        posts = [rng.randrange(2, 6), rng.randrange(9, 13)]
        if rng.random() < 0.4:
            posts = posts[:1]
        for px in posts:
            for y in range(10, T):
                fade = y - 10
                c.set(px, y, "3" if fade < 2 else "2" if fade < 4 else "1")
                c.set(px + 1, y, "1" if fade < 3 else "0")
            _stamp(c, px, 9, ["dc", "cb"])  # the lashing that holds the post to the log
        for lx in [x for x in (rng.randrange(1, 4), rng.randrange(7, 9)) if all(abs(x - p) > 2 for p in posts)]:
            _stamp(c, lx, 6, ["d.", "cd", ".b", "b."])  # extra rope turns on the log
        e = extras[i]
        if e == "charm":  # a bone-and-feather charm hanging off the rim
            _stamp(c, 8, 10, [".h", ".j", "jJ", "Ji", "R.", "r."])
        elif e == "rope":  # a loose rope end over the edge
            _stamp(c, 8, 10, ["c", "b", "c", "b", "a"])
        elif e == "jut":  # a board end sticking out past the rim
            _stamp(c, 7, 5, ["443", "332", "221", "110"])
        elif e == "brace":  # a diagonal brace between the posts
            c.line(posts[0] + 2, 11, min(13, posts[0] + 7), 15, "2")
        elif e == "hide":  # a strip of hide hung over the edge to dry
            _stamp(c, 7, 9, ["bccb", "bdcb", "bccb", "bcca", ".bb."])
        register(f"az.tb.platform.edge@{i}", art(c.grid(), legend=TB, note="plank rim of the deck over the drop"))


PLANK = 4  # bridge slats: 3 px slat + 1 px gap


def _bridge() -> None:
    """Rope bridge running north-south: lashed slats over the drop, two side ropes."""
    for i in range(2):
        seed = 1200 + i
        rng = random.Random(seed)
        c = Canvas(T, T)
        for y in range(T):  # the dark below the gaps (no rock face here, just depth)
            for x in range(T):
                c.set(x, y, "V" if (bayer(x, y) < 0.3 and x in (0, 15)) else "v")
        grain = fbm(T, T, seed, 2, 4)
        for p in range(T // PLANK):
            y0 = p * PLANK
            dx = rng.choice((0, 0, 1, -1))
            x0, x1 = 2 + dx, 13 + dx
            if i == 1 and p == 2:
                x1 = 10  # a short, broken slat
            for x in range(x0, x1 + 1):
                for r in range(3):
                    g = grain[y0 + r][x] + (bayer(x, y0 + r) - 0.5) * 0.25
                    ch = ("4" if g > 0.35 else "3") if r == 0 else ("3" if g > 0.6 else "2") if r == 1 else "1"
                    c.set(x, y0 + r, ch)
            if x1 < 13:
                c.set(x1 + 1, y0 + 1, "0")
        for y in range(T):  # side ropes, twisted: alternate light and mid strands
            c.set(1, y, "j" if y % 2 else "d")
            c.set(2, y, "c" if y % 4 == 0 else c.get(2, y))
            c.set(14, y, "i" if y % 2 else "c")
            c.set(13, y, "b" if y % 4 == 2 else c.get(13, y))
        for p in range(T // PLANK):  # lashings where each slat meets the rope
            c.set(1, p * PLANK + 1, "J")
            c.set(14, p * PLANK + 1, "j")
        register(f"az.tb.bridge@{i}", art(c.grid(), legend=TB, note="rope bridge between rises (north-south)"))


def _rope_y(x: float, top: float, sag: float) -> int:
    """Rope sagging between posts: highest at the post (x=7.5), lowest at the tile edges."""
    return round(top + sag * (1 - math.cos(math.pi * abs(x + 0.5 - 8) / 8)) / 2)


def _rope_rail() -> None:
    """Rope railing along a rim: a lashed post each tile, two ropes sagging between
    posts (lowest at the tile edges so neighbours join)."""
    for i in range(2):
        c = Canvas(T, T)
        for y in range(2, 15):  # the post
            c.set(7, y, "4" if y < 4 else "3")
            c.set(8, y, "2")
        c.set(7, 2, "5")
        c.set(8, 2, "3")
        if i == 1:  # a horn tip on top of the post
            _stamp(c, 7, 0, ["JJ", "ji"])
        g = Canvas.of(outline_grid(c.grid(), "k"))
        # the ropes go on after the outline: light twisted strands with a soft shadow
        for x in range(T):
            for top, sag in ((4, 3), (9, 2)):
                y = _rope_y(x, top, sag)
                g.set(x, y, "d" if x % 2 else "c")
                if g.get(x, y + 1) in ".":
                    g.set(x, y + 1, "z")
        _stamp(g, 6, 4, ["j..j", "ijji"])  # lashings where the ropes meet the post
        _stamp(g, 6, 9, ["i..i", "hiih"])
        if i == 1:
            _stamp(g, 9, 6, ["R", "r"])  # a red cloth tied to the post
        for x in range(6, 10):  # foot of the post: small contact shadow
            if g.get(x, 15) == ".":
                g.set(x, 15, "z")
        register(f"az.tb.rope_rail@{i}", art(g.grid(), legend=TB, note="rope railing"))


# --- shared building parts ---------------------------------------------------------------------


def _log_v(c: Canvas, x0: int, x1: int, y0: int, y1: int) -> None:
    """Vertical log/post lit from the left: highlight, body, shade, dark rim."""
    w = x1 - x0 + 1
    for x in range(x0, x1 + 1):
        i = x - x0
        ch = "4" if i == 0 else "1" if i == w - 1 and w > 2 else "2" if i >= w - 2 and w > 3 else "3"
        c.vline(x, y0, y1, ch)


def _band(c: Canvas, x0: int, x1: int, y: int, light: str, mid: str, dark: str) -> None:
    """A painted or roped band across a vertical shaft: lit left, shaded right."""
    n = x1 - x0
    for x in range(x0, x1 + 1):
        t = (x - x0) / max(1, n)
        c.set(x, y, light if t < 0.25 else dark if t > 0.75 else mid)


def _deck(c: Canvas, x0: int, x1: int, y: int) -> None:
    """A low plank deck in front of a building: lit top edge, plank face, post ends."""
    for x in range(x0, x1 + 1):
        c.set(x, y, "4" if bayer(x, y) < 0.6 else "5")
        c.set(x, y + 1, "3")
        c.set(x, y + 2, "2")
        c.set(x, y + 3, "1")
    for x in range(x0 + 2, x1, 8):
        c.vline(x, y + 1, y + 3, "0")
        c.set(x + 1, y + 1, "4")


def _banner(c: Canvas, x: int, y0: int, h: int, pole_top: int | None = None) -> None:
    """A Horde-red banner 4 px wide with a white mark and a notched tail; optional pole."""
    if pole_top is not None:
        c.vline(x - 1, pole_top, y0 + h + 6, "3")
        c.set(x - 1, pole_top, "J")
        c.hline(x - 1, x + 4, y0, "2")
    for y in range(y0 + 1, y0 + h):
        c.set(x, y, "q")
        c.set(x + 1, y, "R")
        c.set(x + 2, y, "R")
        c.set(x + 3, y, "r")
    my = y0 + h // 2 - 1
    _stamp(c, x + 1, my - 1, ["J.", "JJ", ".J"])
    c.set(x, y0 + h, "q")
    c.set(x + 3, y0 + h, "r")
    c.set(x + 1, y0 + h, "R")


def _skull_horns(c: Canvas, cx: int, y: int, span: int) -> None:
    """A kodo skull with horns sweeping out and up: bone lit from the top-left."""
    _stamp(c, cx - 3, y, ["iJJJJi", "JJjjji", "jVjjVh", "ijjjjh", ".ijjh.", ".hiih."])
    for s in (-1, 1):
        for k in range(span):
            x = cx + (k + 3 if s > 0 else -k - 4)
            yy = y + 1 - (k * k) // (span * 2 if span > 3 else 3)
            c.set(x, yy, "J" if s < 0 else "j")
            c.set(x, yy + 1, "j" if s < 0 else "i")
        tip = cx + (span + 3 if s > 0 else -span - 4)
        c.set(tip, y + 1 - (span * span) // (span * 2) - 1, "J" if s < 0 else "j")


# --- lodge (Elder Rise / High Rise) --------------------------------------------------------------


def _lodge(variant: int) -> Canvas:
    """A tauren lodge: an arched hide roof over bent timber ribs, the pole bundle rising
    out of the smoke hole, a painted band and sun, hide walls between log posts, a
    doorway with a rolled-up flap, and a deck. Elder Rise (0): turquoise paint, the
    Cenarion leaf-and-moon emblem, the council drum. High Rise (1): red paint, kodo horns, two Horde banners."""
    W, H = 64, 48
    c = Canvas(W, H)
    cx, base, rx, ry = 32.0, 31.0, 29.5, 21.0
    paint, paint_l, paint_d = ("t", "T", "t") if variant == 0 else ("R", "q", "r")
    # the pole bundle first: it sticks out of the smoke hole above the roof
    for k, top in ((-3, 1), (-1, 0), (1, 0), (3, 2)):
        c.line(32 + k * 2, 13, 32 - k, top, "3" if k < 0 else "2")
    for k in (-1, 1):
        c.line(32 + k * 3, 12, 32 + k * 5, 3, "2" if k > 0 else "3")
    lx, ly, lz = -0.45, -0.65, 0.61
    ribs = (-0.72, -0.36, 0.0, 0.36, 0.72)
    for y in range(H):
        for x in range(W):
            nx = (x + 0.5 - cx) / rx
            ny = (y + 0.5 - base) / ry
            if ny > 0 or nx * nx + ny * ny > 1:
                continue
            nz = math.sqrt(max(0.0, 1 - nx * nx - ny * ny))
            v = (nx * lx + ny * ly + nz * lz + 0.35) / 1.35 + (bayer(x, y) - 0.5) * 0.12
            ch = "bcde"[max(0, min(3, int(v * 3.7)))]
            hw = math.sqrt(max(1e-6, 1 - ny * ny))
            u = nx / hw
            for r in ribs:  # the bent timber ribs under the hide
                d = (u - r) * hw * rx
                if -0.5 <= d < 0.5:
                    ch = "3" if nx < 0.2 else "2"
            if -0.52 < ny < -0.44:  # the painted band around the roof
                ch = paint_l if nx < -0.3 else paint_d if nx > 0.4 else paint
            elif -0.58 < ny <= -0.52 and (x // 2) % 2 == 0:
                ch = "V"
            elif -0.44 <= ny < -0.37 and ((x + (y % 2)) // 2) % 2 == 0:
                ch = "J" if variant == 0 else "e"
            if ny > -0.07:  # the eave: dark hem
                ch = "a" if ny > -0.035 else "b"
            c.set(x, y, ch)
    # a stitched seam where two courses of hide meet, halfway up the roof
    for x in range(W):
        for y in range(H):
            nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - base) / ry
            if -0.27 < ny < -0.21 and nx * nx + ny * ny < 0.97 and c.get(x, y) in "bcde" and x % 2:
                c.set(x, y, "b" if c.get(x, y) in "de" else "a")
    # smoke hole ring at the top of the roof
    c.hline(29, 35, 10, "a")
    c.hline(28, 36, 11, "b")
    # a painted sun on the front of the roof
    sun = ["..q..", ".qRq.", "qRJRr", ".rRr.", "..r.."] if variant else \
        ["..T..", ".TtT.", "TtJtt", ".ttt.", "..t.."]
    _stamp(c, 14, 20, sun)
    _stamp(c, 45, 20, sun)
    # fringe of hide tassels under the eave, every fourth one a feather
    for k, x in enumerate(range(5, 60, 3)):
        c.set(x, 31, "b")
        c.set(x, 32, "a")
        if k % 4 == 2 and not 24 <= x <= 39:
            _stamp(c, x, 31, ["J", "j", paint])
    # walls: hide stretched between log posts, dark under the eave
    for y in range(31, 42):
        for x in range(7, 57):
            if c.get(x, y) not in ".":
                continue
            v = 0.3 + 0.5 * (y - 31) / 10 - 0.15 * (x - 7) / 49 + (bayer(x, y) - 0.5) * 0.3
            c.set(x, y, "b" if v < 0.4 else "c" if v < 0.85 else "d")
    for px in (7, 19, 42, 54):
        _log_v(c, px, px + 2, 30, 41)
    for x in range(10, 54):  # painted triangles along the wall
        if 19 <= x <= 44:
            continue
        k = x % 4
        if k in (0, 1, 2):
            c.set(x, 36, paint if variant else "t")
        if k == 1:
            c.set(x, 35, paint_l if variant else "T")
    # a tall doorway (a tauren is 3 yards tall) under a log lintel, flap rolled up
    for y in range(25, 42):
        half = 4 if y > 26 else 3
        for x in range(32 - half, 32 + half):
            c.set(x, y, "V" if y < 31 or x < 30 else "0")
    for y in range(24, 42):
        c.set(26, y, "4")
        c.set(27, y, "3")
        c.set(36, y, "2")
        c.set(37, y, "1")
    c.hline(25, 38, 22, "4")
    c.hline(25, 38, 23, "2")
    c.set(25, 23, "3")
    for y in range(25, 36):
        c.set(28, y, "d" if y % 2 else "c")
    c.set(28, 36, "b")
    _deck(c, 3, 60, 42)
    _stamp(c, 28, 42, ["55555555", "43333332", "32222221", "21111110"])  # step
    if variant == 0:
        # the Cenarion emblem painted on the roof: a green leaf in a turquoise moon ring
        _stamp(c, 28, 13, ["..tTt..", ".T...t.", "T..Gg.t", "T.Ggg.t", "T.gg..t", ".t...t.", "..ttt.."],)
        for y in range(14, 19):
            for x in range(29, 34):
                if c.get(x, y) not in "tTgG":
                    c.set(x, y, "e")
        # the Elder Rise drum beside the door
        _stamp(c, 10, 35, [".dddddd.", "deeeeddc", "cddddccb", "3R3R3R32", "34343332", "3R3R3R21",
                           "22222211", ".111111."])
        _stamp(c, 17, 33, ["4.", ".3", "..", ".."])  # drumstick
        # moss in the roof seams: the Cenarion Circle lives here
        for x, y in ((9, 27), (10, 27), (22, 13), (41, 12), (54, 26), (53, 27)):
            c.set(x, y, "g" if (x + y) % 2 else "G")
    else:
        _outlined(c, _skull_horns, 32, 15, 6)
        _banner(c, 13, 18, 12, pole_top=16)
        _banner(c, 48, 18, 12, pole_top=16)
        # a fire bowl by the door
        _stamp(c, 39, 37, [".fF.", "fFFf", "MnnM", ".mm."])
    return _finish(c, (32, 46.2, 31.5, 2.2))


def _lodges() -> None:
    notes = ("Elder Rise lodge: council hall, Cenarion emblem, drum", "High Rise lodge: chieftain's hall, horns, banners")
    for i in range(2):
        register(f"az.tb.lodge@{i}", art(_lodge(i).grid(), legend=TB, note=notes[i]))


# --- Hunter Rise: the Hunter's Hall ------------------------------------------------------------


def _warrior_hall() -> None:
    """Hunter's Hall on Hunter Rise: a squared log hall under a hipped roof of layered
    hides, a ridge log with crossed pole ends, a great kodo skull on the ridge, war
    shields and red banners on the wall, crossed spears over the door."""
    W, H = 64, 48
    c = Canvas(W, H)
    top, eave = 8, 27
    for y in range(top, eave + 1):
        t = (y - top) / (eave - top)
        x0 = round(16 - t * 14)
        x1 = round(47 + t * 14)
        for x in range(x0, x1 + 1):
            # left hip faces west/up (lit), right hip east (shade), front plane between
            side = -1 if x < 16 else 1 if x > 47 else 0
            row = (y - top) % 4
            if side < 0:
                ch = "e" if row == 0 else "d"
            elif side > 0:
                ch = "c" if row == 0 else "b"
            else:
                ch = "d" if row == 0 else "c" if row < 3 else "b"
            if row == 3:
                ch = "a" if side > 0 else "b"
            if side == 0 and (x - 16) % 6 == 0:
                ch = "3"  # rafters under the hides
            c.set(x, y, ch)
    for y in range(top, eave + 1):  # the hip ridges from ridge ends to eave corners
        t = (y - top) / (eave - top)
        c.set(round(16 - t * 6), y, "3")
        c.set(round(47 + t * 6), y, "2")
    for x in range(2, 62):  # painted red band of triangles along the eave
        k = x % 5
        c.set(x, eave - 2, "R" if k < 4 else "r")
        if k in (1, 2):
            c.set(x, eave - 3, "q" if x < 32 else "R")
    c.hline(1, 62, eave, "a")
    # ridge log with crossed pole ends
    c.hline(14, 49, top - 2, "4")
    c.hline(14, 49, top - 1, "3")
    c.hline(14, 49, top, "1")
    for ex, s in ((14, -1), (49, 1)):
        c.line(ex, top, ex + s * 4, top - 7, "3" if s < 0 else "2")
        c.line(ex + s * 4, top, ex, top - 7, "3" if s < 0 else "2")
    _outlined(c, _skull_horns, 32, 1, 7)
    # log walls
    for y in range(eave + 1, 42):
        r = (y - eave - 1) % 3
        for x in range(5, 59):
            c.set(x, y, "3" if r == 0 else "2" if r == 1 else "1")
            if r == 0 and bayer(x, y) < 0.2:
                c.set(x, y, "4")
    for y in range(eave + 1, 42, 3):  # log ends at the corners
        _stamp(c, 3, y, ["cd", "bc"])
        _stamp(c, 59, y, ["cb", "ba"])
    # a porch over the tall door: crossed spears behind a painted hide awning on two posts
    c.line(22, 23, 41, 12, "3")
    c.line(22, 12, 41, 23, "2")
    _stamp(c, 40, 10, [".P", "Pp"])
    _stamp(c, 21, 10, ["P.", "pP"])
    for y in range(24, 42):
        for x in range(28, 36):
            c.set(x, y, "V" if y < 30 else "0")
    for y in range(26, 34):
        c.set(28, y, "d" if y % 2 else "c")
        c.set(35, y, "c" if y % 2 else "b")
    _log_v(c, 25, 27, 20, 41)
    _log_v(c, 36, 38, 20, 41)
    for y in range(14, 23):
        hw = (y - 14) * 1.1 + 1
        for x in range(round(31.5 - hw), round(31.5 + hw) + 1):
            v = 0.6 - 0.5 * (x - 31.5) / max(1, hw) + (bayer(x, y) - 0.5) * 0.3
            ch = "e" if v > 0.9 else "d" if v > 0.5 else "c" if v > 0.15 else "b"
            if y == 21:
                ch = "q" if x < 31 else "R"
            elif y == 22:
                ch = "a"
            c.set(x, y, ch)
    _stamp(c, 30, 16, [".J.", "JVJ", ".j."])  # a painted eye on the awning
    # war shields on the wall
    for sx in (10, 46):
        _stamp(c, sx, 30, [".RRqq.", "RRddqR", "RdJJdR", "RdJJdr", "rRddRr", ".rrrr."])
        _stamp(c, sx + 1, 36, ["j..j", "J..j"])  # feathers hanging from it
    _banner(c, 19, 28, 10)
    _banner(c, 41, 28, 10)
    _deck(c, 2, 61, 42)
    _stamp(c, 28, 42, ["55555555", "43333332", "32222221", "21111110"])
    # a training dummy's stump of weapons: a spear rack by the corner
    for k, x in enumerate((57, 59, 61)):
        c.vline(x, 30 + k, 41, "3")
        c.set(x, 29 + k, "P")
    g = _finish(c, (32, 46.2, 31.5, 2.2))
    register("az.tb.warrior_hall", art(g.grid(), legend=TB, note="Hunter Rise: the Hunter's Hall"))


# --- tall ceremonial totem ----------------------------------------------------------------------

# Decorations authored as the left half (12 px) and mirrored; '.' leaves the pole showing.
TOTEM_TOP = """
...........e
.......e...e
.......eR..R
........eR.R
........eRRr
.........Rrr
........TTTT
.......TTJJT
.......TJVwJ
.......TJJJj
........tTJj
.....eeettjJ
...eedddttjj
.eedRRRRtt.i
eddRqRRRRttt
eRRqRRRRRt..
eRRRVRRVRt..
VeRV.eRV.V..
.V.V..VV....
"""

TOTEM_FACE = """
...J........
...jJ.......
....jJ......
.....jJiiiJJ
......jJJJJJ
.......jVVjJ
.......JwVJJ
.......qJJJJ
........jjjj
........eeee
........deed
........cVVc
........ddjd
........Rjjr
.........jj.
"""


def _right_shade(g: list[str]) -> list[str]:
    """Mirror a left half and darken the mirrored (right, away-from-light) side."""
    dark = str.maketrans({"e": "d", "d": "c", "J": "j", "j": "i", "q": "R", "R": "r", "T": "t",
                          "4": "3", "3": "2"})
    out = []
    for row in g:
        row = row.strip()
        out.append(row + row[::-1].translate(dark))
    return out


def _totem() -> None:
    """The tall ceremonial totem: a thunderbird with spread wings on top, a horned tauren
    face, rope rings and the red-and-turquoise painted shaft on a stone footing."""
    W, H = 24, 64
    c = Canvas(W, H)
    _log_v(c, 8, 15, 6, 59)
    grain = fbm(8, 64, 77, 2, 4)
    for y in range(6, 60):  # a little wood grain on the lit side of the shaft
        for x in range(9, 13):
            if grain[y][x - 8] > 0.78:
                c.set(x, y, "2")
    _stamp(c, 0, 0, _right_shade([r for r in TOTEM_TOP.strip().splitlines()]))
    _stamp(c, 0, 20, _right_shade([r for r in TOTEM_FACE.strip().splitlines()]))
    for y in (37, 38):  # rope rings
        for x in range(8, 16):
            c.set(x, y, "J" if (x + y) % 2 else "j")
        c.set(15, y, "i")
    for y in range(40, 58):  # painted shaft: red bands, turquoise diamonds between
        if y in (40, 41, 55, 56):
            _band(c, 8, 15, y, "q", "R", "r")
        elif 43 <= y <= 53:
            half = 5 - abs(y - 48)
            for x in range(8, 16):
                if abs(x - 11.5) <= half * 0.7:
                    c.set(x, y, "T" if x < 12 else "t")
            c.set(max(8, round(11.5 - half * 0.7)), y, "V")
            c.set(min(15, round(11.5 + half * 0.7)), y, "V")
    _stamp(c, 9, 58, ["jJJ", "Jii"])  # the painted eye ring at the foot
    # stone footing
    for y in range(58, 63):
        for x in range(3, 21):
            nx, ny = (x + 0.5 - 12) / 9, (y + 0.5 - 62) / 4.2
            if nx * nx + ny * ny <= 1 and (y > 59 or not 8 <= x <= 15):
                v = -nx * 0.5 - ny * 0.6 + (bayer(x, y) - 0.5) * 0.4
                c.set(x, y, "N" if v > 0.5 else "n" if v > 0.1 else "M" if v > -0.35 else "m")
    for x, y in ((4, 22), (19, 22)):  # feathers hanging from the horn tips
        _stamp(c, x - 1, y, ["j", "e", "R", "V"] if x < 12 else ["i", "d", "r", "V"])
    g = _finish(c, (12, 63, 11, 1.4))
    register("az.tb.totem_tall", art(g.grid(), legend=TB, anchor=(12, 62),
                                     note="tall ceremonial totem: thunderbird, tauren face, painted shaft"))


# --- tents ---------------------------------------------------------------------------------------


def _tipi(c: Canvas, cx: float, base: int, w: int, h: int, paint: tuple[str, str, str], sym: str) -> None:
    """A hide tent: a cone lit from the left, pole seams, painted bands, a symbol, the
    door opening and the pole tips crossing above the smoke flap."""
    apex = base - h
    pl, pm, pd = paint
    for k in (-1, 0, 1):  # pole tips fanning out of the smoke hole
        c.line(round(cx), apex + 2, round(cx) + k * 3, apex - 4, "4" if k < 0 else "3" if k == 0 else "2")
    for y in range(apex, base + 1):
        t = (y - apex) / h
        hw = max(0.6, t * w / 2)
        for x in range(round(cx - hw), round(cx + hw) + 1):
            u = (x + 0.5 - cx) / hw
            if abs(u) > 1.05:
                continue
            v = 0.62 - 0.5 * u + (bayer(x, y) - 0.5) * 0.25
            ch = "b" if v < 0.3 else "c" if v < 0.6 else "d" if v < 0.95 else "e"
            if any(abs(u - s) < 0.5 / hw for s in (-0.55, 0.0, 0.55)) and t > 0.2:
                ch = "cbba"["bcde".index(ch)] if ch != "b" else "a"
            if 0.78 < t < 0.86:
                ch = pl if u < -0.4 else pd if u > 0.4 else pm
            elif 0.86 <= t < 0.9 and (x % 3):
                ch = "V"
            elif 0.24 < t < 0.3 and ((x + y) % 3 == 0):
                ch = pm
            c.set(x, y, ch)
    # the smoke flap at the apex
    c.set(round(cx) - 1, apex + 1, "a")
    c.set(round(cx), apex + 1, "b")
    # the painted symbol on the front
    sx, sy = round(cx) - 2, apex + int(h * 0.45)
    if sym == "sun":
        _stamp(c, sx, sy, [".{0}{0}.".format(pm), "{0}JJ{1}".format(pl, pd), "{0}JJ{1}".format(pm, pd),
                           ".{0}{0}.".format(pd)])
    elif sym == "hoof":
        _stamp(c, sx, sy, ["V..V", "VV.V", ".VVV", "..V."])
    elif sym == "bolt":
        _stamp(c, sx, sy, ["..{0}.".format(pm), ".{0}..".format(pm), "{0}{0}{0}.".format(pm), "..{0}.".format(pd),
                           ".{0}..".format(pd)])
    # door: a dark triangular opening with the flap tied back
    for y in range(base - 8, base + 1):
        half = (y - (base - 8)) * 0.35
        for x in range(round(cx - half), round(cx + half) + 1):
            c.set(x, y, "V" if y < base - 4 else "0")
        c.set(round(cx - half) - 1, y, "d")
    c.set(round(cx) - 3, base, "3")  # pegs
    c.set(round(cx - w / 2), base, "2")
    c.set(round(cx + w / 2), base, "2")


def _hide_frame(c: Canvas, x0: int, y0: int, w: int, h: int) -> None:
    """A hide stretched on a pole frame to dry, laced at the edges, painted."""
    for y in range(y0 + 2, y0 + h - 2):
        for x in range(x0 + 2, x0 + w - 2):
            v = 0.7 - 0.4 * (x - x0) / w - 0.2 * (y - y0) / h + (bayer(x, y) - 0.5) * 0.3
            c.set(x, y, "e" if v > 0.62 else "d" if v > 0.35 else "c")
    for y in range(y0 + 2, y0 + h - 2, 2):
        c.set(x0 + 1, y, "i")
        c.set(x0 + w - 2, y, "i")
    _stamp(c, x0 + w // 2 - 2, y0 + h // 2 - 2, [".RR.", "RqRr", "RRRr", ".rr."])
    _log_v(c, x0, x0 + 1, y0 - 2, y0 + h + 2)
    _log_v(c, x0 + w - 2, x0 + w - 1, y0 - 2, y0 + h + 2)
    c.hline(x0, x0 + w - 1, y0, "3")
    c.hline(x0 - 1, x0 + w, y0 + h - 1, "2")


def _tent_rows() -> None:
    reds = ("q", "R", "r")
    teal = ("T", "t", "t")
    earth = ("n", "M", "m")
    for i in range(2):
        c = Canvas(48, 32)
        if i == 0:
            _tipi(c, 9.5, 29, 16, 24, reds, "sun")
            _tipi(c, 38.5, 29, 16, 24, earth, "hoof")
            _tipi(c, 24.0, 29, 19, 27, teal, "bolt")
        else:
            _hide_frame(c, 17, 9, 14, 17)
            _tipi(c, 9.5, 29, 17, 26, teal, "hoof")
            _tipi(c, 38.5, 29, 17, 25, reds, "bolt")
            _stamp(c, 21, 27, [".fFf.", "fFFFf", "M3n2m", ".mMm."])  # a small cooking fire
        g = _finish(c, (24, 30.6, 23, 1.6))
        register(f"az.tb.tent_row@{i}", art(g.grid(), legend=TB, anchor=(24, 30),
                                            note="row of painted hide tents" + ("" if i == 0 else " with a drying hide")))


# --- Pools of Vision ------------------------------------------------------------------------------


def _spirit_pool() -> None:
    """The Pools of Vision: a luminous pool in a grotto under Spirit Rise. Dark rock with
    stalagmites closes around the back, lit cyan from below by the water; the pool glows
    brightest at its heart, ripples spread from it, and glowing mist rises and drifts."""
    W, H = 32, 24
    frames = []
    cx, cy, rx, ry = 16.0, 17.0, 14.5, 5.5
    spikes = {3: 3, 4: 5, 5: 3, 9: 3, 10: 4, 22: 3, 23: 5, 27: 4, 28: 6, 29: 3}
    rock = fbm(W, H, 61, 2, 4)
    for f in range(3):
        c = Canvas(W, H)
        # the grotto: high at the sides, low over the middle, stalagmites on the rim
        for x in range(W):
            top = 3 + round(6 * math.sin(math.pi * x / (W - 1))) - spikes.get(x, 0)
            for y in range(max(0, top), 16):
                v = rock[y][x] + (bayer(x, y) - 0.5) * 0.3
                lit_edge = y <= top + 1 and x < 16
                glow = max(0.0, (y - 5) / 8) * max(0.0, 1 - abs(x + 0.5 - cx) / 18)
                mouth = ((x + 0.5 - cx) / 5.5) ** 2 + ((y + 0.5 - 13.5) / 5.5) ** 2
                if mouth < 1.0:  # the tunnel running back into the mesa
                    ch = "v" if mouth < 0.55 else "V" if mouth < 0.8 or v < 0.5 else "U"
                elif glow > 0.5:
                    ch = "u" if v > 0.55 else "U"
                elif glow > 0.2:
                    ch = "U" if v > 0.45 else "o"
                elif lit_edge:
                    ch = "p" if v > 0.4 else "O"
                else:
                    ch = "O" if v > 0.62 else "o"
                c.set(x, y, ch)
        # the pool: dark at the edge, brightening to a glowing heart; one ripple ring
        for y in range(H):
            for x in range(W):
                nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                d = nx * nx + ny * ny
                if d > 1.0:
                    if d <= 1.25 and ny > 0.2:  # a low lip of wet pebbles at the front
                        c.set(x, y, "O" if bayer(x, y) < 0.5 else "o")
                    continue
                ch = "U" if d > 0.8 else "u" if d > 0.5 else "y" if d > 0.22 else "Y"
                ring = (math.sqrt(d) * 2.0 - f / 3.0) % 1.0
                if ring < 0.14 and 0.08 < d < 0.8:
                    ch = {"U": "u", "u": "y", "y": "Y", "Y": "x"}[ch]
                if d < 0.05:
                    ch = "x"
                c.set(x, y, ch)
        for (x, y) in ((12, 16), (20, 18), (17, 15), (9, 18), (23, 16)):
            if (x + y + f) % 3 == 0:
                c.set(x, y, "x")
        g = _finish(c)
        # luminous mist, drawn over everything after the outline: streaks lying on the
        # water sway back and forth, neighbours in opposite directions
        for k, (y, x0, n) in enumerate(((10, 7, 6), (12, 17, 7), (13, 4, 5), (14, 20, 6), (11, 12, 4),
                                        (15, 10, 5))):
            xs = x0 + round(1.2 * math.sin(2 * math.pi * f / 3)) * (1 if k % 2 == 0 else -1)
            for i in range(n):
                x = xs + i
                if 1 <= x < W - 1:
                    g.set(x, y, "H" if i in (0, n - 1) else "X" if (i + k) % 3 else "Z")
        frames.append(g.grid())
    register("az.tb.spirit_pool", art(*frames, legend=TB, fps=3,
                                      note="Pools of Vision: glowing grotto pool with luminous mist"))


# --- the rope elevator ------------------------------------------------------------------------------


def _lift() -> None:
    """The tauren rope elevator: a plank car on four ropes between two guide posts,
    hung from a crossbeam with pulleys; the ropes creep and the car bobs by 1 px."""
    W, H = 32, 24
    frames = []
    for f in range(2):
        c = Canvas(W, H)
        dy = -f
        _log_v(c, 1, 3, 1, 22)
        _log_v(c, 28, 30, 1, 22)
        c.hline(1, 30, 1, "4")
        c.hline(1, 30, 2, "3")
        c.hline(1, 30, 3, "1")
        for px in (6, 24):  # pulleys
            _stamp(c, px, 3, ["jii", "i0h", "hhh"] if f == 0 else ["iji", "j0i", "hih"])
        # ropes from the pulleys to the car corners, twist moving between frames
        for rx in (7, 25, 10, 22):
            for y in range(6, 14 + dy):
                c.set(rx, y, "j" if (y + f) % 2 else "i")
        # the car: plank floor seen from above, front beam, rope rail
        for y in range(14 + dy, 18 + dy):
            for x in range(5, 27):
                r = (y - 14 - dy)
                c.set(x, y, "4" if r == 0 else "3" if (x + r) % 7 else "1")
        for x in range(5, 27):
            c.set(x, 18 + dy, "2")
            c.set(x, 19 + dy, "1")
        c.set(5, 18 + dy, "3")
        for x in range(5, 27):  # the rope rail across the front of the car
            c.set(x, 12 + dy + (1 if 9 < x < 22 else 0), "d" if x % 2 else "c")
        for px in (5, 26):
            c.vline(px, 11 + dy, 17 + dy, "4" if px == 5 else "2")
        _stamp(c, 12, 11 + dy, [".dcb.", "deddb", "cddcb", "bccba"])  # a hide sack of goods
        _stamp(c, 18, 12 + dy, ["3333", "4332", "3221"])  # a crate
        _stamp(c, 26, 9 + dy, ["qR", "Rr"])  # red pennant on the corner post
        # landing: the guide posts stand in a stone footing
        for x in range(0, 32):
            if x < 5 or x > 26:
                c.set(x, 22, "M" if x % 3 else "n")
                c.set(x, 23, "m")
        frames.append(_finish(c).grid())
    register("az.tb.lift", art(*frames, legend=TB, fps=2, note="the rope elevator"))


# --- support pillar -----------------------------------------------------------------------------------


def _support_pillars() -> None:
    """A lashed timber pillar holding up a rise: beam ends under the deck on top,
    three bundled logs with rope bands, paint or a hanging banner, a stone footing."""
    for i in range(2):
        c = Canvas(16, 48)
        _log_v(c, 2, 5, 5, 42)
        _log_v(c, 10, 13, 5, 42)
        _log_v(c, 5, 10, 4, 43)
        # capital: the rise's underside, beam ends in end grain
        for x in range(1, 15):
            c.set(x, 0, "3")
            c.set(x, 1, "2")
            c.set(x, 2, "1")
        _stamp(c, 2, 1, ["dc", "cb"])
        _stamp(c, 11, 1, ["dc", "cb"])
        c.hline(1, 14, 3, "0")
        for y in (8, 9, 24, 25, 38, 39):
            for x in range(2, 14):
                c.set(x, y, "J" if (x + y) % 2 and x < 9 else "j" if (x + y) % 2 else "i")
        if i == 0:
            for y in (13, 14, 32, 33):
                _band(c, 5, 10, y, "q", "R", "r")
            for y in range(17, 30):
                d = abs(y - 23)
                half = (6 - d) * 0.45
                for x in range(5, 11):
                    if abs(x + 0.5 - 8) <= half:
                        c.set(x, y, "T" if x < 8 else "t")
        else:
            _stamp(c, 4, 11, ["00000000", "qRRRRRRr", "qJRRRRJr", "qRJRRJRr", "qRRJJRRr", "qRRRRRRr",
                              "qVRRRRVr", "qRVRRVRr", "qRRVVRRr", "qRRRRRRr", "qR.qR.Rr", "q...R..r"])
            _stamp(c, 12, 26, ["h", "j", "J", "e", "R"])  # a bone-and-feather charm
        for y in range(42, 47):  # stone footing
            for x in range(1, 15):
                v = -(x - 7.5) / 8 - (y - 44) / 4 + (bayer(x, y) - 0.5) * 0.4
                c.set(x, y, "N" if v > 0.6 else "n" if v > 0.1 else "M" if v > -0.4 else "m")
        c.hline(2, 13, 42, "n")
        g = _finish(c)
        for x in range(1, 15):  # contact shadow beside the footing
            if g.get(x, 47) == ".":
                g.set(x, 47, "z")
        register(f"az.tb.support_pillar@{i}", art(g.grid(), legend=TB,
                                                  note="lashed timber pillar below a rise"))


# --- small props ------------------------------------------------------------------------------------


def _ball(c: Canvas, cx: float, cy: float, rx: float, ry: float, ramp: str, x0: int = 0, y0: int = 0,
          y_min: int = -99, y_max: int = 99) -> None:
    """A round body (pot, drum, bowl) lit from the top-left, quantised into ``ramp``
    (dark -> light), Bayer-dithered between steps."""
    n = len(ramp)
    for y in range(max(0, y_min), min(c.h, y_max + 1)):
        for x in range(c.w):
            nx, ny = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
            d = nx * nx + ny * ny
            if d > 1:
                continue
            nz = math.sqrt(1 - d)
            v = (-0.55 * nx - 0.45 * ny + 0.7 * nz + 0.3) / 1.6 + (bayer(x, y) - 0.5) * 0.14
            c.set(x, y, ramp[max(0, min(n - 1, int(v * n)))])


FLAMES = (
    ["....Q.....",
     "...QfQ..Q.",
     "...QfQ.QQ.",
     "..QfFfQfQ.",
     "..QfFWFfQ.",
     ".QfFWWFfQ.",
     ".QfFWWWFfQ",
     "QfFFWWFFfQ",
     "QffFFFFffQ"],
    ["......Q...",
     "..Q..QfQ..",
     "..QQ.QfQ..",
     ".QfQQfFfQ.",
     ".QfFfFWFQ.",
     ".QfFWWFfQ.",
     "QfFWWWFFfQ",
     "QfFFWWFFfQ",
     "QffFFFFffQ"],
    [".....Q....",
     "....QfQ...",
     ".Q..QfFQ..",
     ".QQ.QFfQQ.",
     ".QfQfFWfQ.",
     "QfFfWWFfQ.",
     "QfFWWWWFfQ",
     "QfFFWWFFfQ",
     "QffFFFFffQ"],
)


def _brazier() -> None:
    """A standing fire brazier: a painted clay bowl on a lashed timber tripod, the fire
    licking up out of it (3 frames), a spark drifting off."""
    frames = []
    for f in range(3):
        c = Canvas(16, 24)
        # tripod legs, lashed under the bowl
        c.line(4, 13, 2, 22, "3")
        c.line(11, 13, 13, 22, "2")
        c.vline(7, 13, 22, "3")
        c.vline(8, 13, 22, "2")
        _stamp(c, 3, 15, ["dcddcddcdc", "cbccbccbcb"])
        # the bowl
        _ball(c, 7.5, 9.5, 6.5, 4.5, "ABCDE", y_min=9, y_max=13)
        for x in range(1, 15):
            c.set(x, 9, "D" if x < 8 else "C")
        for x in range(2, 14):
            if c.get(x, 11) != ".":
                c.set(x, 11, "q" if x < 5 else "R" if x < 11 else "r")
            if x % 3 == 0 and c.get(x, 12) != ".":
                c.set(x, 12, "T" if x < 8 else "t")
        g = _finish(c, (8, 23.3, 6, 1.1))
        _stamp(g, 3, 0, FLAMES[f])  # fire after the outline: flames stay soft
        for x in range(2, 14):
            if g.get(x, 9) in "DC":
                g.set(x, 9, "l" if x % 2 else "Q")  # coals glowing on the rim
        sx, sy = ((12, 1), (2, 0), (13, 3))[f]
        g.set(sx, sy, "F")
        frames.append(g.grid())
    register("az.tb.brazier", art(*frames, legend=TB, fps=6, note="standing fire brazier"))


def _drum() -> None:
    """A big ceremonial drum: a hide head stretched over a wide timber body, laced down
    to a lower hoop, painted bands; Elder Rise's has a beater resting on it."""
    for i in range(2):
        c = Canvas(16, 16)
        paint = ("q", "R", "r") if i == 0 else ("T", "t", "t")
        # body: a squat cylinder
        for y in range(5, 14):
            for x in range(2, 14):
                t = (x - 2) / 11
                c.set(x, y, "4" if t < 0.15 else "3" if t < 0.55 else "2" if t < 0.85 else "1")
        # lacing zigzag from the top hoop to the bottom hoop
        for x in range(2, 14):
            y = 7 + (x % 4 if x % 4 < 3 else 1)
            c.set(x, y, "d" if x < 8 else "c")
        _band(c, 2, 13, 11, *paint)
        _band(c, 2, 13, 12, *paint)
        c.hline(2, 13, 13, "1")
        # the hide head seen from above
        for y in range(2, 7):
            for x in range(1, 15):
                nx, ny = (x + 0.5 - 7.5) / 6.5, (y + 0.5 - 4.5) / 2.3
                d = nx * nx + ny * ny
                if d <= 1:
                    c.set(x, y, "b" if d > 0.72 else "e" if nx < -0.2 and ny < 0.3 else "d")
        if i == 0:
            _stamp(c, 6, 3, ["rRr", "R.r", "rrr"])  # a red sun ring painted on the head
        else:
            _stamp(c, 5, 3, ["t...t", ".tTt."])  # a turquoise moon painted on the head
            c.line(9, 1, 14, 4, "3")  # the beater
            _stamp(c, 8, 0, ["ee", "dd"])
        # short feet
        c.set(3, 14, "2")
        c.set(12, 14, "1")
        g = _finish(c, (8, 15.2, 7, 1.0))
        if i == 1:
            _stamp(g, 14, 8, ["j", "e", "R"])  # feathers tied to the hoop
        register(f"az.tb.drum@{i}", art(g.grid(), legend=TB, note="big ceremonial drum"))


def _stairs() -> None:
    """Wooden stairs climbing north between platform levels: four steps a tile (lit
    tread, dark riser), log stringers on both sides; seamless when stacked."""
    for i in range(2):
        c = Canvas(T, T)
        g = _grain(2000 + i)
        for y in range(T):
            r = y % 4
            for x in range(2, 14):
                gv = g[y][x] + (bayer(x, y) - 0.5) * 0.2
                if r == 0:
                    ch = "5" if gv > 0.6 else "4"
                elif r == 1:
                    ch = "4" if gv > 0.5 else "3"
                elif r == 2:
                    ch = "1"
                else:
                    ch = "0" if bayer(x, y) < 0.5 else "1"
                c.set(x, y, ch)
            c.set(0, y, "3")
            c.set(1, y, "2")
            c.set(14, y, "2")
            c.set(15, y, "1")
            if r == 2:  # pegs where each tread sits on the stringer
                c.set(1, y, "0")
                c.set(14, y, "0")
        if i == 1:  # a red hide runner laid down the middle
            for y in range(T):
                r = y % 4
                for x in range(6, 10):
                    base = {0: "q", 1: "R", 2: "r", 3: "r"}[r]
                    c.set(x, y, "c" if x in (6, 9) and r < 2 else base)
        else:  # treads worn pale in the middle
            for y in range(0, T, 4):
                for x in range(6, 10):
                    if bayer(x, y) < 0.5:
                        c.set(x, y, "5")
        register(f"az.tb.stairs@{i}", art(c.grid(), legend=TB, note="wooden stairs between platform levels"))


HIDE = [
    ".b....b.",
    "bccccccb",
    ".cddddc.",
    ".cdeedc.",
    ".cdeedcb",
    ".cddddc.",
    ".cdddcc.",
    "bcddccc.",
    ".ccccccb",
    "b.cccc..",
    "..cccc..",
    "...cc...",
]


def _hanging_hides() -> None:
    """Hides and feathers hung from a lashed beam between two posts to dry."""
    for i in range(2):
        c = Canvas(32, 24)
        _log_v(c, 1, 2, 2, 22)
        _log_v(c, 29, 30, 2, 22)
        c.hline(0, 31, 2, "4")
        c.hline(0, 31, 3, "2")
        for lx in (1, 29):
            _stamp(c, lx, 2, ["dc", "cb"])
        if i == 0:
            spots = [(4, "plain"), (13, "paint"), (22, "dark")]
        else:
            spots = [(4, "dark"), (15, "paint")]
        for x0, kind in spots:
            h = [row for row in HIDE]
            if kind == "dark":
                h = [r.translate(str.maketrans("bcde", "abbc")) for r in h]
            _stamp(c, x0, 4, h)
            if kind == "paint":
                _stamp(c, x0 + 2, 6, ["R..R", "Rq.R", "qR.R", ".R.r", "....", "rRRr"])  # a hoofprint
        # strings of feathers between the hides (and a bone charm on the second)
        strings = [(12, 4)] if i == 0 else [(24, 4), (27, 4)]
        for sx, sy in strings:
            c.vline(sx, sy, sy + 4, "b")
            _stamp(c, sx, sy + 5, ["J", "j", "R"] if (sx + i) % 2 else ["i", "J", "t"])
        if i == 1:
            _stamp(c, 25, 13, ["jJ", "ij", "Jj"])  # a small bone charm
        g = _finish(c, (16, 23.3, 15, 1.1))
        register(f"az.tb.hanging_hides@{i}", art(g.grid(), legend=TB, note="hides and feathers hung from a beam"))


def _prayer_flags() -> None:
    """Prayer flags on a rope between two short posts; the flags flutter in the wind
    (their tails flick out to the right in the second frame)."""
    colors = [("q", "R"), ("e", "d"), ("T", "t"), ("D", "C"), ("R", "r")]
    frames = []
    for f in range(2):
        c = Canvas(32, 16)
        _log_v(c, 1, 2, 1, 14)
        _log_v(c, 29, 30, 1, 14)
        for x in range(1, 31):
            y = 2 + round(2.5 * math.sin(math.pi * (x - 1) / 29))
            c.set(x, y, "c" if x % 2 else "b")
        for k, x in enumerate(range(5, 27, 4)):
            y = 3 + round(2.5 * math.sin(math.pi * (x - 1) / 29))
            lit, dark = colors[k % len(colors)]
            wave = (f + k) % 2
            rows = [lit + lit + dark, lit + lit + dark, lit + dark + dark, lit + dark + "."]
            for j, row in enumerate(rows):
                dx = 1 if (wave and j >= 2) else 0
                _stamp(c, x + dx, y + j, [row])
        g = _finish(c, (16, 15.3, 15, 0.8))
        frames.append(g.grid())
    register("az.tb.prayer_flags", art(*frames, legend=TB, fps=3, note="prayer flags on a rope, flutter"))


def _pots() -> None:
    """Clay pots: a tall water jar with a painted band and a glint of water in its
    mouth, and a squat storage pot with a hide cover tied down with rope."""
    # 0: tall water jar
    c = Canvas(16, 16)
    _ball(c, 7.5, 9.5, 5.5, 5.5, "ABCDE", y_min=4, y_max=14)
    for y in range(1, 5):
        for x in range(5, 11):
            c.set(x, y, "D" if x < 7 else "C" if x < 9 else "B")
    c.hline(4, 11, 1, "D")
    c.set(11, 1, "C")
    _stamp(c, 6, 1, ["uyy.", ".uu."])  # water in the mouth
    for x in range(3, 13):  # painted band with a zigzag
        if c.get(x, 8) != ".":
            c.set(x, 8, "R" if x < 10 else "r")
        if c.get(x, 10) != ".":
            c.set(x, 10, "R" if x < 10 else "r")
        if c.get(x, 9) != ".":
            c.set(x, 9, "V" if x % 2 else c.get(x, 9))
    _stamp(c, 2, 6, ["C", "B"])  # lug handles
    _stamp(c, 13, 6, ["B", "A"])
    g = _finish(c, (8, 15.3, 6, 0.9))
    register("az.tb.pot@0", art(g.grid(), legend=TB, note="clay water jar"))
    # 1: squat storage pot with a hide cover
    c = Canvas(16, 16)
    _ball(c, 7.5, 10.5, 6.5, 4.5, "ABCDE", y_min=7, y_max=14)
    for y in range(4, 8):  # the hide cover, bunched over the mouth
        for x in range(3, 13):
            nx, ny = (x + 0.5 - 7.5) / 5.2, (y + 0.5 - 7.0) / 3.2
            if nx * nx + ny * ny <= 1:
                c.set(x, y, "e" if nx < -0.2 and ny < 0 else "d" if nx < 0.4 else "c")
    c.hline(2, 13, 8, "b")  # the rope tying it down
    c.set(2, 8, "c")
    _stamp(c, 12, 8, ["b", "c"])
    for x in range(3, 13, 3):  # turquoise dots on the belly
        c.set(x, 11, "T" if x < 8 else "t")
    g = _finish(c, (8, 15.3, 7, 0.9))
    register("az.tb.pot@1", art(g.grid(), legend=TB, note="storage pot with a hide cover"))


def _banner_cloth(f: int) -> list[str]:
    """The Bloodhoof banner (10 x 23 with a spare column): red field, brown border, a cream hoofprint, a
    swallowtail with fringe. Frame 1 ripples: the lower half sways right by a pixel."""
    rows = []
    for y in range(23):
        row = ""
        for x in range(9):
            edge = x in (0, 8)
            ch = "2" if edge else "q" if x == 1 else "r" if x == 7 else "R"
            if y in (0, 1):
                ch = "2" if y == 0 else "3"
            row += ch
        rows.append(row)
    hoof = ["..J.J..", ".JJ.JJ.", ".JJ.JJ.", ".Jj.Jj.", "..j.j..", "..jJj..", "...j..."]
    for j, hr in enumerate(hoof):
        rows[6 + j] = rows[6 + j][:1] + "".join(h if h != "." else rows[6 + j][1 + i] for i, h in enumerate(hr)) + rows[6 + j][8:]
    rows[15] = "2rRRRRRr2"
    rows[16] = "2RqRRRRr2"
    tail = ["2RRRRRRr2", ".2RRRRr2.", ".2RR.Rr2.", "..2R.r2..", "..2...2..", "..i...i..", "..j...j.."]
    rows[16:23] = tail
    rows = [r + "." for r in rows]  # one spare column for the ripple
    if f == 1:  # the wind catches the lower half: it swings a pixel to the right
        rows = rows[:11] + ["." + r[:-1] for r in rows[11:]]
    return rows


def _banner_pole() -> None:
    """A tall Bloodhoof banner on a carved pole: horns and feathers on top, bone rings,
    a crossbar, the red banner fluttering, a stone footing."""
    frames = []
    for f in range(2):
        c = Canvas(16, 40)
        c.vline(3, 3, 37, "4")
        c.vline(4, 3, 37, "2")
        for y in (12, 13, 24, 25, 32):  # carved bone rings
            c.set(3, y, "J")
            c.set(4, y, "j")
        _stamp(c, 0, 0, ["J......J", "Jj....jj", ".jj..ji.", "..jJJi..", "...43..."])  # horns on top
        _stamp(c, 5, 3, ["R", "q", "j"])  # a red-tipped feather under the horns
        c.hline(3, 14, 4, "3")
        c.hline(3, 14, 5, "1")
        _stamp(c, 5, 5, _banner_cloth(f))
        for y in range(36, 40):  # stone footing
            for x in range(1, 8):
                v = -(x - 4) / 4 - (y - 37) / 2 + (bayer(x, y) - 0.5) * 0.4
                if y == 39 and x in (1, 7):
                    continue
                c.set(x, y, "N" if v > 0.6 else "n" if v > 0 else "M" if v > -0.6 else "m")
        g = _finish(c)
        frames.append(g.grid())
    register("az.tb.banner_pole", art(*frames, legend=TB, fps=2, anchor=(4, 39),
                                      note="tall Bloodhoof banner on a carved pole"))


# === Thunder Bluff v4: grassy mesa tops on sheer cliffs ==========================================

CLIFF = {**{str(i): f"azb_cliff{i}" for i in range(6)}, "g": "azb_pine3", "G": "azb_pine4", "f": "azb_pine1",
         "K": "ink2"}
_CLIFF_SHARED = [random.Random(5150).random() for _ in range(T)]


def _ridge_profile(seed: int) -> list[float]:
    """1D periodic height across the cliff (ridges and crevices), blended to a shared
    profile on the border columns so every variant joins every other sideways."""
    rng = random.Random(seed)
    k = [(rng.uniform(0.4, 1.0), rng.random()) for _ in range(3)]
    out = []
    for x in range(T):
        v = sum(a * math.sin(2 * math.pi * ((i + 1) * x / T + ph)) / (i + 1) for i, (a, ph) in enumerate(k))
        w = max(0.0, 1.0 - min(x, T - 1 - x) / 3.0)
        out.append(v * (1 - w) + (_CLIFF_SHARED[x] - 0.5) * 1.2 * w)
    return out


def _cliff_face() -> None:
    """The sheer pale cliffs the rises stand on: tall ridges and dark crevices running top
    to bottom (lit on their left, light from the top-left), long water stains, a pale lip
    at the top and the face darkening toward the foot. Horizontal detail is kept to a
    minimum because the client stretches this tile 2.5-5x vertically."""
    for i in range(6):
        seed = 5200 + i * 11
        rng = random.Random(seed)
        prof = _ridge_profile(seed)
        stain = fbm(T, T, seed + 3, 2, 2)
        c = Canvas(T, T)
        for x in range(T):
            slope = prof[(x + 1) % T] - prof[x - 1]
            for y in range(T):
                v = 0.6 + 0.18 * prof[x] - 0.45 * slope       # ridges up, faces turned left lit
                v += (stain[y][x] - 0.5) * 0.2 - 0.22 * (y / (T - 1)) ** 2
                v += (bayer(x, y // 3) - 0.5) * 0.1              # dither in tall cells: survives stretching
                c.set(x, y, str(max(2, min(5, int(v * 4.6) + 1))))
            if slope > 0.75:  # the deep crevices: a dark slot full height, a shadowed lip beside it
                for y in range(T):
                    c.set(x, y, "1" if y > 1 else "2")
                    if c.get((x + 1) % T, y) in "45":
                        c.set((x + 1) % T, y, "3")
        for x in range(T):  # the pale lip where the grass top breaks off
            c.set(x, 0, "5" if c.get(x, 0) not in "01" else "2")
        if i in (2, 5):  # a few moss tufts on a ledge
            lx = rng.randrange(3, 10)
            ly = rng.randrange(5, 10)
            _stamp(c, lx, ly, [".gG.", "fggG", ".ff."])
        if i == 4:  # a long dark water stain
            sx = rng.randrange(4, 12)
            for y in range(2, T):
                if c.get(sx, y) not in "0":
                    c.set(sx, y, "2" if c.get(sx, y) in "345" else "1")
        register(f"az.tb.cliff.face@{i}", art(c.grid(), legend=CLIFF, note="sheer pale cliff, vertical streaks"))


COBBLE = {**{str(i): f"azb_cliff{i}" for i in range(6)}, "m": "azb_cliff0", "M": "azb_cliff1", "g": "azb_pine3",
          "G": "azb_pine4"}
_CR = random.Random(77)
# a jittered 3x3 grid of stone centres; the eight outer ones are shared by every variant
# (the middle row is staggered by half a stone so the joints never line up)
_COBBLE_SHARED = [(((gx + 0.5 + (0.5 if gy == 1 else 0)) * T / 3 + _CR.uniform(-1.6, 1.6)) % T,
                   (gy + 0.5) * T / 3 + _CR.uniform(-1.4, 1.4))
                  for gy in range(3) for gx in range(3) if (gx, gy) != (1, 1)]


def _cobble() -> None:
    """Light cobblestone paving: rounded pale stones in dark earth joints, each stone lit
    on its top-left. Stones touching the border come from one shared set, so the four
    variants join each other in any order; interior stones differ per variant."""
    def dist(ax, ay, bx, by):
        dx = min(abs(ax - bx), T - abs(ax - bx))
        dy = min(abs(ay - by), T - abs(ay - by))
        return math.hypot(dx, dy * 1.15)

    for i in range(4):
        rng = random.Random(6100 + i * 7)
        inner = [(10.7 + rng.uniform(-1.2, 1.2), 8 + rng.uniform(-1.2, 1.2))]
        if i % 2:  # the middle stone split in two
            ix, iy = inner[0]
            inner = [(ix - 1.6, iy - 0.4), (ix + 1.6, iy + 0.5)]
        pts = _COBBLE_SHARED + inner
        tone = [random.Random(900 + k + (0 if k < len(_COBBLE_SHARED) else i * 31)).random() for k in range(len(pts))]
        c = Canvas(T, T)
        for y in range(T):
            for x in range(T):
                border = min(x, y, T - 1 - x, T - 1 - y) < 2
                cand = range(len(_COBBLE_SHARED)) if border else range(len(pts))
                ds = sorted((dist(x + 0.5, y + 0.5, *pts[k]), k) for k in cand)
                (d1, k1), (d2, _) = ds[0], ds[1]
                if d2 - d1 < 0.9:
                    ch = "m" if bayer(x, y) < 0.7 else "M"
                else:
                    px, py = pts[k1]
                    ddx = (x + 0.5 - px + T / 2) % T - T / 2
                    ddy = (y + 0.5 - py + T / 2) % T - T / 2
                    lit = -(ddx + ddy) / max(1.0, d1 * 2.2)
                    v = 0.5 + 0.25 * tone[k1] + lit * 0.5 - (0.18 if d2 - d1 < 1.9 else 0)
                    v += (bayer(x, y) - 0.5) * 0.15
                    ch = str(max(2, min(5, int(v * 5.2))))
                c.set(x, y, ch)
        if i == 3:  # grass pushing up in a joint
            for x, y in ((7, 7), (8, 6)):
                if c.get(x, y) in "mM":
                    c.set(x, y, "g")
        register(f"az.tb.cobble@{i}", art(c.grid(), legend=COBBLE, note="light cobblestone paving"))


# The Mulgore pine (v5): olive / yellow-green boughs, sunlit gold on the upper-left tips, and
# a red-brown trunk. Deliberately warmer and yellower than the dark azb_pine of the cliffs.
_ramp("azb_olive", "#20250f", "#313b16", "#46541c", "#5f7224", "#7d912e", "#a4ad3b", "#d8c95c")
_ramp("azb_bark", "#2a1510", "#45231a", "#633424", "#81492f", "#9e623f", "#b97f55")
PINE = {**{str(i): f"azb_olive{i}" for i in range(7)}, **{"abcdef"[i]: f"azb_bark{i}" for i in range(6)},
        "z": "ink:70", "y": "ink:36"}


def _pine() -> None:
    """The pine of all Mulgore, 15-25 yd tall: a tall straight red-brown trunk, flared at the
    root and bare for the lower third, under tiers of DROOPING boughs with gaps between them
    where the trunk shows. Each tier is a pair of boughs leaving the trunk and arching down,
    hung with a ragged curtain of needles: lit along the top, dark underneath, golden at the
    upper-left tips. Tier widths, lengths and droop vary per side so no two trees match.
    Anchor = the trunk base centre; only a faint contact smudge (the ground is lit in code)."""
    bark = "abcdef"
    for i, (w, h, seed) in enumerate(((24, 64, 11), (28, 76, 23), (30, 86, 37), (32, 96, 41))):
        rng = random.Random(7100 + seed)
        c = Canvas(w, h)
        tx = w // 2  # trunk centre column (the anchor)
        base = h - 2  # the lowest bark row; the ink outline closes it on row h-1
        crown_bot = base - round(h * 0.34)  # the trunk is bare below the lowest tier
        top = 2
        tw = 4 if h >= 80 else 3  # trunk width in the bare part

        # -- trunk: straight, tapering upward, flared at the root, lit from the left
        for y in range(top, base + 1):
            f = (base - y) / (base - top)
            wid = tw if f < 0.4 else max(1, round(tw - (f - 0.4) * tw * 1.5))
            fl = base - y
            x0 = tx - (tw + 1) // 2 + (1 if wid < tw - 1 else 0)
            x1 = x0 + wid - 1
            if fl < 3:  # the flare: roots spread, a little further on the right
                x0 -= (2, 1, 0)[fl]
                x1 += (2, 1, 1)[fl]
            for x in range(x0, x1 + 1):
                t = (x - x0 + 0.5) / (x1 - x0 + 1)
                v = 4 if t < 0.25 else 3 if t < 0.55 else 2 if t < 0.8 else 1
                if y < crown_bot + 4:  # in the canopy's shadow
                    v = max(0, v - (2 if y < crown_bot + 1 else 1))
                c.set(x, y, bark[v])
        for _ in range(h // 5):  # bark furrows: short dark vertical seams
            x = tx - (tw + 1) // 2 + rng.randrange(tw)
            y0 = rng.randrange(crown_bot, base - 1)
            for y in range(y0, min(base, y0 + rng.randint(2, 5))):
                ch = c.get(x, y)
                if ch in "cde":
                    c.set(x, y, bark[bark.index(ch) - 1 - (ch == "e")])

        # -- tiers: positions top to bottom, drawn bottom first so upper tiers overlap
        n = max(5, round((crown_bot - top) / 8))
        ys = [top + 2 + round((crown_bot - top - 7) * (k / n) ** 0.85) + (rng.choice((-1, 0, 1)) if 0 < k < n else 0)
              for k in range(n + 1)]
        hw_max = w / 2 - 1.0
        tiers = []
        for k in range(n):
            g = ((k + 1) / n) ** 0.75
            hw = 2.5 + (hw_max - 2.5) * g
            if k == n - 1:
                hw *= rng.uniform(0.85, 0.97)  # the lowest bough pair is a little shorter
            sides = {s: min(hw_max - (0 if s < 0 else 0.6), hw * rng.uniform(0.68, 1.1)) for s in (-1, 1)}
            tiers.append((k, ys[k], ys[k + 1] - ys[k], sides))
        k, a, sp, sides = tiers[rng.randrange(n // 2, n - 1)]  # one bough reaches out further
        sides[rng.choice((-1, 1))] = hw_max
        for k, a, sp, sides in reversed(tiers):
            upper = k < n * 0.55
            for s, hw in sides.items():
                droop = sp * rng.uniform(0.9, 1.3) + 1.5  # how far the tip hangs below the root
                curtain = max(2.0, sp * rng.uniform(0.65, 0.85))
                for x in range(w):
                    d = (x + 0.5 - tx) * s
                    if d < -0.6 or d > hw:
                        continue
                    u = max(0.0, d) / hw
                    ytop = a + droop * (0.35 * u + 0.65 * u * u)
                    # needles hang thin near the trunk (the gap shows), fullest mid-bough
                    th = 0.5 + curtain * math.sin(min(1.0, u * 1.25) * math.pi * 0.85)
                    hem = (x * 5 + k * 3 + i + (s > 0)) % 4
                    th += (0, 1, 0, 2)[hem] if u > 0.3 else 0
                    if u > 0.88:  # the tip narrows to a hanging point
                        th = max(1.0, th * (1 - (u - 0.88) * 5))
                    y0, y1 = round(ytop), round(ytop + th)
                    for y in range(y0, y1 + 1):
                        if not 1 <= y <= base - 4:
                            continue
                        r = (y - y0) / max(1, y1 - y0)
                        v = 4.6 - 3.6 * r - (1.0 * u if s > 0 else -0.4 * u) + (0.4 if upper else 0)
                        v += -0.8 * ((x * 3 + y * 7 + k) % 5 == 0) + (bayer(x, y) - 0.5) * 0.7
                        if y == y1 and y1 > y0:
                            v = min(v, 1.0 if s < 0 else 0.0)  # the shadowed hem
                        if y == y0 and u > 0.12:
                            if s < 0 and u > 0.25:
                                v = 6 if (upper or u > 0.55) and (x + k) % 3 else 5  # golden tips
                            else:
                                v = max(v, 4.4 if s < 0 else 3.2)
                        c.set(x, y, str(max(0, min(6, round(v)))))
        # the leader: a thin spire with two tufts and a lit tip
        for y in range(1, top + 3):
            c.set(tx - 1, y, "4" if y < 3 else "3")
        c.set(tx - 1, 1, "6")
        c.set(tx - 2, top + 2, "5")

        g = Canvas.of(outline_grid(c.grid(), "k"))
        # soft ground contact only: no ink line under the roots, a faint smudge around them
        for x in range(w):
            if g.get(x, h - 1) == "k":
                g.set(x, h - 1, "z")
        for dx in (-5, -4, 4, 5, 6):
            if 0 <= tx + dx < w and g.get(tx + dx, h - 1) == ".":
                g.set(tx + dx, h - 1, "y")
        register(f"az.tb.pine@{i}", art(g.grid(), legend=PINE, anchor=(tx, h - 1),
                                         note=f"tall olive Mulgore pine, {h // 8} yd"))


def _cyl(t: float, light: str, mid: str, dark: str, deep: str | None = None) -> str:
    """Colour for a column at t (0 = left rim, 1 = right rim) of a cylinder lit from the left."""
    if t < 0.18:
        return light
    if t < 0.6:
        return mid
    if t < 0.9 or deep is None:
        return dark
    return deep


PAINT = {  # paint name -> (lit, mid, dark, deep) on a cylinder
    "cream": ("e", "d", "c", "b"), "red": ("q", "R", "r", "r"), "teal": ("%", "9", "8", "7"),
    "wood": ("4", "3", "2", "1"), "line": ("b", "a", "a", "0"), "dark": ("V", "V", "v", "v"),
}

BULL = [
    "J...............",
    "Jj..............",
    ".jj.............",
    ".ijj............",
    "..ijj...........",
    "...ijjj.........",
    "....hijjj.....kk",
    ".....hiijjj.kddd",
    ".......hhiijddee",
    "........bdddddee",
    ".......cbcddeeee",
    "........cRRddeee",
    ".........dVwdeee",
    ".........dddqRRe",
    "..........ddeeee",
    "..........cdeeDD",
    "...........cDDDD",
    "...........cDVDD",
    "............cDDj",
    ".............ccj",
]


def _tower_totem() -> None:
    """The High Rise tower: a tall painted cylinder (the wind rider roost) in bands of
    red, teal hexagons and cream zigzags, a round window and an arched door, a wide rim
    near the top and a great carved bull head with sweeping horns crowning it."""
    W, H = 32, 96
    c = Canvas(W, H)
    x0, x1 = 5, 26
    top, foot = 24, 88

    def paint(x: int, y: int, name: str) -> None:
        t = (x - x0) / (x1 - x0)
        lit, mid, dark, deep = PAINT[name]
        c.set(x, y, _cyl(t, lit, mid, dark, deep))

    # body and bands, top to bottom
    bands = []
    y = top
    pattern = ["red2", "hex8", "cream_zig4", "red2", "window8", "red1", "hex8", "red2", "cream_zig4",
               "red2", "plain4", "door99"]
    for item in pattern:
        name = item.rstrip("0123456789")
        n = int(item[len(name):])
        bands.append((name, y, min(foot, y + n)))
        y += n
        if y >= foot:
            break
    for x in range(x0, x1 + 1):
        for yy in range(top, foot + 1):
            paint(x, yy, "cream")
    for name, ya, yb in bands:
        for yy in range(ya, yb):
            for x in range(x0, x1 + 1):
                k = yy - ya
                if name == "red":
                    paint(x, yy, "red")
                elif name == "hex":
                    # two rows of teal hexagons outlined in red, offset by half a cell
                    row = k // 4
                    off = 3 if row % 2 else 0
                    cx = (x - x0 + off) % 6
                    ky = k % 4
                    if ky == 0 or cx == 0 or (ky in (1, 3) and cx in (1, 5)):
                        paint(x, yy, "red")
                    else:
                        paint(x, yy, "teal")
                elif name == "cream_zig":
                    zig = abs(((x - x0) % 6) - 3)
                    paint(x, yy, "red" if k == zig or k == zig - 1 else "cream")
                elif name == "window" and k in range(1, 7):
                    d = ((x + 0.5 - 15.5) / 3.5) ** 2 + ((k - 3.5) / 3.0) ** 2
                    if d < 0.55:
                        c.set(x, yy, "V" if d > 0.2 or x > 15 else "v")
                    elif d < 1.0:
                        paint(x, yy, "wood")
                elif name == "door":
                    d = abs(x + 0.5 - 15.5)
                    if d < 4.5 and (k > 2 or d < 3):
                        c.set(x, yy, "v" if d < 3.3 and k > 1 else "2" if x > 15 else "4")
    for yy in range(top, foot + 1):  # the left rim catches light, the right is in shade
        c.set(x0, yy, "e" if c.get(x0, yy) in "dcb" else c.get(x0, yy))
        c.set(x1, yy, "a" if c.get(x1, yy) in "dcbe" else c.get(x1, yy))
    # the rim near the top: a wide wooden ring with post ends
    for yy in range(19, 24):
        for x in range(2, 30):
            t = (x - 2) / 27
            k = yy - 19
            if k == 0:
                ch = "5" if t < 0.4 else "4"
            elif k < 3:
                ch = _cyl(t, "4", "3", "2", "1")
            else:
                ch = _cyl(t, "2", "1", "0", "0")
            c.set(x, yy, ch)
    for x in range(3, 29, 4):
        c.set(x, 21, "1")
    for x in range(4, 28, 6):  # feathers hanging from the rim
        _stamp(c, x, 24, ["J", "j", "R" if x < 16 else "r"])
    # the carved bull head with its horns
    head = _right_shade([r for r in BULL])
    _stamp(c, 0, 0, head)
    # a wider stone footing
    for yy in range(88, 96):
        for x in range(2, 30):
            nx, ny = (x + 0.5 - 16) / 14, (yy + 0.5 - 92) / 3.6
            if nx * nx + ny * ny <= 1:
                v = -nx * 0.5 - ny * 0.6 + (bayer(x, yy) - 0.5) * 0.4
                c.set(x, yy, "N" if v > 0.5 else "n" if v > 0.1 else "M" if v > -0.35 else "m")
    for yy in range(89, 92):  # steps up to the door
        for x in range(11, 21):
            c.set(x, yy, "4" if yy == 89 else "3" if yy == 90 else "2")
    g = _finish(c)
    register("az.tb.tower_totem", art(g.grid(), legend=TB, anchor=(16, 94),
                                      note="High Rise tower: painted cylinder, bull head"))


def _windmill_totem() -> None:
    """A wind totem: a carved, painted pole with a four-blade pinwheel of hide sails on
    wooden spars at the top, turning (4 frames = a quarter turn, the blades repeat)."""
    W, H = 24, 40
    frames = []
    hub = (11.5, 10.5)
    for f in range(4):
        c = Canvas(W, H)
        # the pole
        for y in range(10, 38):
            c.set(11, y, "4")
            c.set(12, y, "2")
        for y, name in ((16, "red"), (17, "red"), (22, "teal"), (23, "teal"), (28, "red"), (31, "cream"),
                        (32, "cream")):
            c.set(11, y, PAINT[name][0])
            c.set(12, y, PAINT[name][2])
        _stamp(c, 10, 19, ["eJJe", ".jj."])  # carved bone collar
        # blades
        for b in range(4):
            ang = math.pi / 2 * b + f * math.pi / 8
            dx, dy = math.cos(ang), math.sin(ang)
            px, py = -dy, dx
            for s10 in range(3, 100):
                s_ = s10 / 10
                if s_ > 10:
                    break
                wdt = 0.6 + 1.8 * min(1.0, s_ / 6)
                for wv in (-wdt, -wdt / 2, 0, wdt / 2, wdt):
                    x = hub[0] + dx * s_ + px * wv * (1 if s_ > 2.5 else 0)
                    y = hub[1] + dy * s_ * 0.8 + py * wv * 0.8 * (1 if s_ > 2.5 else 0)
                    xi, yi = int(x), int(y)
                    if wv == 0 or s_ <= 2.5:
                        ch = "3"  # the spar
                    elif wv > 0:
                        ch = "e" if b % 2 == 0 else "q"
                    else:
                        ch = "d" if b % 2 == 0 else "R"
                    if c.get(xi, yi) != "3" or ch == "3":
                        c.set(xi, yi, ch)
        _stamp(c, 10, 9, ["jJ", "ij"])  # the hub
        g = _finish(c, (12, 39.2, 4, 0.9))
        for x in range(9, 15):  # a footing of stones
            g.set(x, 38, "M" if x % 2 else "n")
        frames.append(g.grid())
    register("az.tb.windmill_totem", art(*frames, legend=TB, fps=6, anchor=(12, 38),
                                         note="wind totem: painted pole, spinning pinwheel"))


def _lift_tower() -> None:
    """The rope elevator: a very tall carved pole with a crossbeam, pulley and horn
    finial, a small cab riding on the rope (it climbs 2 px between frames), and a round
    wooden landing disc at its foot with a ramp running down toward the viewer."""
    W, H = 32, 80
    frames = []
    for f in range(2):
        c = Canvas(W, H)
        # landing disc: plank top, thick rim
        for y in range(64, 80):
            for x in range(W):
                nx, ny = (x + 0.5 - 16) / 15.5, (y + 0.5 - 70) / 5.0
                if nx * nx + ny * ny <= 1:
                    k = (y - 65) % 3
                    ch = "4" if k == 0 else "3"
                    if nx < -0.5 and k == 0:
                        ch = "5"
                    if (x + (y // 3) * 5) % 11 == 0:
                        ch = "1"  # board ends
                    c.set(x, y, ch)
                nyr = (y + 0.5 - 72.5) / 5.0
                if nx * nx + nyr * nyr <= 1 and c.get(x, y) == "." and y > 70:
                    c.set(x, y, "2" if nx < 0.3 else "1")
        for x in range(1, 31, 5):  # posts under the rim
            if c.get(x, 77) in "12":
                c.set(x, 77, "0")
        for y in range(73, 80):  # the ramp toward the viewer
            for x in range(12, 20):
                c.set(x, y, "4" if (y - 73) % 2 == 0 else "3")
            c.set(11, y, "2")
            c.set(20, y, "1")
        # the tall pole, carved and painted in bands
        for y in range(4, 69):
            c.set(14, y, "4")
            c.set(15, y, "3")
            c.set(16, y, "3")
            c.set(17, y, "2")
        for y0, name in ((10, "red"), (11, "red"), (20, "teal"), (21, "teal"), (22, "teal"), (30, "cream"),
                         (31, "cream"), (40, "red"), (50, "teal"), (51, "teal"), (60, "red"), (61, "red")):
            for x in range(14, 18):
                c.set(x, y0, _cyl((x - 14) / 3, *PAINT[name]))
        for y in (15, 35, 45, 55):  # rope lashings
            for x in range(14, 18):
                c.set(x, y, "d" if x < 16 else "c")
        # crossbeam, pulley and horn finial
        for x in range(8, 25):
            c.set(x, 4, "4")
            c.set(x, 5, "2")
        _stamp(c, 12, 0, ["J......J", "jJ....Jj", ".jJ44Jj."])
        _stamp(c, 21, 5, [".ii.", "i00i", ".ii."] if f == 0 else [".ji.", "j00i", ".ij."])
        cab_y = 40 - f * 2
        for y in range(8, cab_y):  # the hoist rope, twisted
            c.set(22, y, "j" if (y + f) % 2 else "i")
        for y in range(8, 64):  # the counter rope down to the disc
            c.set(24, y, "i" if (y + f) % 2 else "h")
        # the cab: a small plank basket with hide sides and red trim
        cab = ["..jj....", ".j..j...", "44444444", "4dddddc3", "3dRRRdc2", "3ddddcc2", "33333322",
               ".1....1."]
        _stamp(c, 18, cab_y - 2, cab)
        g = _finish(c)
        frames.append(g.grid())
    register("az.tb.lift_tower", art(*frames, legend=TB, fps=2, anchor=(16, 79),
                                     note="rope elevator: tall carved pole, cab, landing disc"))


_platform()
_inlay()
_platform_edge()
_bridge()
_rope_rail()
_support_pillars()
_lodges()
_totem()
_tent_rows()
_spirit_pool()
_lift()
_warrior_hall()
_brazier()
_drum()
_stairs()
_hanging_hides()
_prayer_flags()
_pots()
_banner_pole()
_cliff_face()
_cobble()
_pine()
_tower_totem()
_windmill_totem()
_lift_tower()
