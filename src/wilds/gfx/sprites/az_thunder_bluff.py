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
# Planks run east-west, 3 px board + 1 px gap, so every tile (floor, edge) shares the same
# rows and tiles seamlessly in both directions. Butt joints stay inside
# the tile; hide mats and pegs never touch the border.

PLANK = 4


def _plank_rows(c: Canvas, seed: int, rows: range) -> None:
    rng = random.Random(seed)
    grain = fbm(T, T, seed, 2, 4)
    for p in range(T // PLANK):
        y0 = p * PLANK
        if y0 not in rows:
            continue
        # one butt joint per board per tile, never on the tile border
        joint = (rng.randrange(2, 14) + p * 5) % 12 + 2
        for x in range(T):
            for r in range(PLANK):
                y = y0 + r
                if y not in rows:
                    continue
                if r == 0:
                    ch = "1"
                else:
                    g = grain[y][x] + (bayer(x, y) - 0.5) * 0.25
                    if r == 1:
                        lvl = 3 if g > 0.45 else 2
                    elif r == 2:
                        lvl = 3 if g > 0.85 else 2
                    else:
                        lvl = 2 if g > 0.3 else 1
                    ch = str(lvl)
                c.set(x, y, ch)
        for r in (1, 2, 3):  # butt joint: a dark seam with a peg beside it
            c.set(joint, y0 + r, "1")
        c.set(joint - 1, y0 + 2, "0")


def _hide_mat(c: Canvas, x: int, y: int, w: int, h: int, paint: str | None) -> None:
    """A stretched hide lashed onto the planks: lit top-left, stitched edge, lacing pegs."""
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            edge = yy in (y, y + h - 1) or xx in (x, x + w - 1)
            if edge:
                ch = "c" if (yy == y or xx == x) else "a"
            else:
                ch = "b" if (xx + yy) % 4 else "c"
            c.set(xx, yy, ch)
    for xx, yy in ((x - 1, y), (x + w, y), (x - 1, y + h - 1), (x + w, y + h - 1)):
        c.set(xx, yy, "0")  # corner pegs
    if paint == "sun":
        cx, cy = x + w // 2, y + h // 2
        _stamp(c, cx - 1, cy - 1, [".r.", "r.r", ".r."])
    elif paint == "zig":
        for i in range(1, w - 1):
            c.set(x + i, y + 1 + (i % 2), "t")


def _platform() -> None:
    """Four boards-and-joints layouts; one in four has a small hide lashed onto the deck,
    one a knot hole, so the floor stays calm when the variants repeat."""
    for i in range(4):
        c = Canvas(T, T)
        _plank_rows(c, 1000 + i * 7, range(T))
        if i == 3:
            _hide_mat(c, 5, 5, 6, 5, "sun")
        elif i == 2:  # a knot in a board
            _stamp(c, 9, 9, ["10", ".1"])
        register(f"az.tb.platform@{i}", art(c.grid(), legend=TB, note="plank-and-hide platform floor"))


def _drop(c: Canvas, y0: int, seed: int) -> None:
    """Below the rim: the mesa's rock face falling away into the dark."""
    f = fbm(T, T, seed, 2, 4)
    for y in range(y0, T):
        depth = (y - y0) / max(1, T - 1 - y0)
        for x in range(T):
            v = f[y][x] * 0.5 + (1 - depth) * 0.9 + (bayer(x, y) - 0.5) * 0.35
            c.set(x, y, "m" if v > 0.95 else "V" if v > 0.45 else "v")


def _platform_edge() -> None:
    """South rim: two plank rows, the round rim log lashed with rope, joist ends
    under it, and the rock face dropping into the dark."""
    extras = [None, "charm", None, "rope"]
    for i in range(4):
        seed = 1100 + i * 5
        rng = random.Random(seed)
        c = Canvas(T, T)
        _plank_rows(c, 1000 + i * 7, range(0, 7))
        _drop(c, 10, seed)
        for x in range(T):  # the rim log, lit on its top
            c.set(x, 6, "4")
            c.set(x, 7, "3")
            c.set(x, 8, "2")
            c.set(x, 9, "0")
        for x in range(T):
            if bayer(x, 6) < 0.25:
                c.set(x, 6, "5")
        lash = rng.randrange(2, 6)
        for lx in (lash, lash + 8):  # rope lashings every 8 px
            _stamp(c, lx, 6, ["j.", "ij", ".h", "h."])
            # a joist end under the rim
            _stamp(c, lx + 3, 10, ["32", "10"])
        if extras[i] == "charm":  # a bone-and-feather charm hanging off the rim
            _stamp(c, 11, 10, [".h", ".j", "jJ", "Ji", "R.", "r."])
        elif extras[i] == "rope":  # a loose rope end over the edge
            _stamp(c, 5, 10, ["j", "i", "j", "i", "h"])
        register(f"az.tb.platform.edge@{i}", art(c.grid(), legend=TB, note="platform edge over the drop"))


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
    # smoke hole ring at the top of the roof
    c.hline(29, 35, 10, "a")
    c.hline(28, 36, 11, "b")
    # a painted sun on the front of the roof
    sun = ["..q..", ".qRq.", "qRJRr", ".rRr.", "..r.."] if variant else \
        ["..T..", ".TtT.", "TtJtt", ".ttt.", "..t.."]
    _stamp(c, 14, 20, sun)
    _stamp(c, 45, 20, sun)
    # fringe of hide tassels under the eave
    for x in range(5, 60, 3):
        c.set(x, 31, "b")
        c.set(x, 32, "a")
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
    """The Pools of Vision: a misty, luminous pool in a rock basin under Spirit Rise,
    two rune stones at its sides; ripples spread and the mist rises and sways."""
    W, H = 32, 24
    frames = []
    for f in range(3):
        c = Canvas(W, H)
        cx, cy = 16.0, 15.5
        rim = fbm(64, 1, 31, 2, 4)[0]
        # a standing spirit stone behind the basin, a carved rune glowing in it
        _stamp(c, 3, 1, ["..pp.", ".pPOo", "pPPOo", "pPxOo", "pxPxo", "pPxOo", "pPPOo", "pPOOo",
                         "oPOoo", "oOOoo", "oOOoo"])
        _stamp(c, 25, 5, [".pO.", "pPOo", "pxOo", "xPxo", "pxOo", "oOOo", "oOoo"])
        for y in range(H):
            for x in range(W):
                nx, ny = (x + 0.5 - cx) / 15.5, (y + 0.5 - cy) / 7.5
                d = nx * nx + ny * ny
                ang = (math.atan2(ny, nx) / (2 * math.pi)) % 1.0
                if d > 0.86 + 0.14 * rim[int(ang * 64) % 64]:
                    continue
                v = -nx * 0.5 - ny * 0.7 + (bayer(x, y) - 0.5) * 0.5 + rim[(int(ang * 64) + 17) % 64] * 0.3
                c.set(x, y, "P" if v > 0.6 else "p" if v > 0.2 else "O" if v > -0.3 else "o")
                wx, wy = (x + 0.5 - cx) / 12.5, (y + 0.5 - cy + 0.5) / 5.0
                w = wx * wx + wy * wy
                if w <= 1:
                    # deep and dark under the far rim, glowing toward the middle
                    ch = "U" if wy < -0.6 else "u" if w > 0.6 else "y"
                    ring = (w * 3 - f / 3) % 1.0
                    if ring < 0.16 and w < 0.9 and wy > -0.6:
                        ch = "Y"
                    if w < 0.1:
                        ch = "Y"
                    c.set(x, y, ch)
        for (x, y) in ((13, 15), (19, 16), (16, 14), (10, 16)):
            if (x + y + f) % 3:
                c.set(x, y, "x")
        g = _finish(c)
        # mist: soft translucent wisps rising off the water, drawn after the outline;
        # each puff climbs 2 px per frame along a swaying path, 3 frames = one loop
        for k, bx in enumerate((9, 16, 22)):
            for j in range(3):
                y = 11 - ((j * 4 + f * 4 + k * 2) % 12)
                x = bx + round(1.2 * math.sin((y + k * 3) * 0.6))
                puff = [".s.", "sSs", ".s."] if y > 6 else [".s.", "s.s", ".s."]
                for pj, row in enumerate(puff):
                    for pi, ch in enumerate(row):
                        px, py = x - 1 + pi, y - 1 + pj
                        if ch != "." and 0 <= py < H and g.get(px, py) in ".z":
                            g.set(px, py, ch)
        frames.append(g.grid())
    register("az.tb.spirit_pool", art(*frames, legend=TB, fps=3, note="Pools of Vision: misty luminous pool"))


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


_platform()
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
