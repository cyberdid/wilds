"""Azeroth / Mulgore art: fx. Must satisfy
``wilds.azeroth.manifest.required()["fx"]`` (see docs/azeroth/mulgore-art-manifest.md).

Same visual language as the Wilds ``fx`` module:

* light (totem pulse, spirit motes, cast circle, hit spark, level-up) has no
  outline: a white-hot core, one or two glow tones, then translucent falloff.
  Only these use emissive colours;
* matter (dust, smoke, pebbles of the earth spirit, grass) has no outline
  either except solid pebbles, is lit from the top-left and thins out through
  dither plus alpha;
* floating icons (the quest "!" and "?") get the 1px ``ink`` outline of actors
  and a bold gold ramp so they read at x1 over a tauren's head. The renderer
  may draw them after the night pass (emissive placement) to keep them bright.

Timing: ``az.fx.hit_spark`` and ``az.fx.level_up`` are one-shot (``loop=False``);
every other effect loops for as long as its state lasts. Anchors: the default
bottom-centre anchor sits on the ground point (dust under the feet, the totem's
base, the caster, the fire, the ripple centre); the quest markers' anchor is
their bottom centre, put it 1-2 px above the head.
"""

from __future__ import annotations

import math
import random

from ..pixelart import art, grid, pad, swap
from ..procgen import Canvas, bayer
from ..registry import register


# --- helpers -------------------------------------------------------------------------


def _cloud(c: Canvas, lobes, chars: str, erode: float = 0.0) -> None:
    """A puff of round lobes ``(cx, cy, r)`` lit from the top-left.
    ``chars`` = shadow, mid, light[, highlight]; ``erode`` thins it from the
    edges inward through an ordered dither."""
    hi = len(chars) >= 4
    for y in range(c.h):
        for x in range(c.w):
            best = None
            for lx, ly, r in lobes:
                dx, dy = x + 0.5 - lx, y + 0.5 - ly
                d = math.hypot(dx, dy) / r
                if d <= 1.0 and (best is None or 1.0 - d > best[0]):
                    best = (1.0 - d, dx / r, dy / r)
            if best is None:
                continue
            depth, nx, ny = best
            if erode > 0 and depth * 1.6 < erode * bayer(x, y) + erode * 0.25:
                continue
            lit = -0.6 * nx - 0.8 * ny
            if hi and lit > 0.62 and depth < 0.55:
                k = 3
            elif lit > 0.12:
                k = 2
            elif lit > -0.42 or depth > 0.45:
                k = 1
            else:
                k = 0
            c.set(x, y, chars[k])


def _ellipse_pts(cx: float, cy: float, rx: float, ry: float) -> list[tuple[int, int]]:
    """A clean 1px ellipse outline: sample the curve, then drop the corner pixels
    of every L-shaped step (they double the line without adding to it)."""
    pts = set()
    steps = max(24, int((rx + ry) * 8))
    for i in range(steps):
        a = i * math.tau / steps
        pts.add((math.floor(cx + math.cos(a) * rx), math.floor(cy + math.sin(a) * ry)))
    for x, y in sorted(pts):
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            if (x + dx, y) in pts and (x, y + dy) in pts and (x + dx, y + dy) not in pts:
                pts.discard((x, y))
                break
    return sorted(pts)


def _ellipse_ring(c: Canvas, cx: float, cy: float, rx: float, ry: float, ch: str, dashes: int = 0,
                  phase: float = 0.0, duty: float = 0.5, only_empty: bool = False) -> None:
    for x, y in _ellipse_pts(cx, cy, rx, ry):
        if dashes:
            a = (math.atan2((y + 0.5 - cy) / ry, (x + 0.5 - cx) / rx) / math.tau + phase) % 1.0
            if (a * dashes) % 1.0 > duty:
                continue
        if only_empty and c.get(x, y) != ".":
            continue
        c.set(x, y, ch)


def _star(c: Canvas, cx: int, cy: int, arm: int, ramp: str, diag: int = 0, dramp: str = "") -> None:
    """A 4-point sparkle on pixel (cx, cy); ``ramp`` runs core -> tips."""
    c.set(cx, cy, ramp[0])
    for d in range(1, arm + 1):
        ch = ramp[min(len(ramp) - 1, round(d / arm * (len(ramp) - 1)))] if arm > 1 else ramp[-1]
        for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            c.set(cx + sx * d, cy + sy * d, ch)
    for d in range(1, diag + 1):
        ch = dramp[min(len(dramp) - 1, d - 1)]
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            c.set(cx + sx * d, cy + sy * d, ch)


# --- dust kicked up by running feet ------------------------------------------------------
# The runner faces right: puffs are born under the feet (bottom right), roll back
# and up, swell and thin out. Two puffs half a cycle apart make a seamless loop.
def _dust_frames() -> list:
    out = []
    for f in range(3):
        c = Canvas(12, 8)
        for ph in sorted(((f / 3 + k / 2) % 1.0 for k in range(2)), reverse=True):
            x = 8.6 - ph * 5.6
            y = 6.4 - ph * 2.4
            r = 1.5 + ph * 1.5
            chars = "1234" if ph < 0.4 else "5678" if ph < 0.75 else "abcd"
            _cloud(c, [(x, y, r), (x + r * 0.7, y + r * 0.35, r * 0.6)], chars,
                   erode=max(0.0, ph - 0.35) * 1.6)
        grains = {0: [(10, 7), (11, 6)], 1: [(9, 7), (1, 3)], 2: [(10, 6), (0, 4)]}
        for x, y in grains[f]:
            if c.get(x, y) == ".":
                c.set(x, y, "g")
        out.append(c.grid())
    return out


DUST = {"1": "sand1", "2": "sand2", "3": "sand3", "4": "sand4",
        "5": "sand1:180", "6": "sand2:180", "7": "sand3:180", "8": "sand4:180",
        "a": "sand1:100", "b": "sand2:100", "c": "sand3:100", "d": "sand4:100", "g": "sand3:150"}
register("az.fx.dust_kick", art(*_dust_frames(), legend=DUST, fps=10,
                                note="dust kicked up behind a running kodo/hero (loop while running; "
                                     "anchor = the rear foot, flip for a left-facing runner)"))


# --- shaman totem pulse -------------------------------------------------------------------
# An ember-gold pulse around a totem's base: a ring swells out on the ground and
# fades, a soft halo breathes around the pole, sparks drift up.
def _totem_frames() -> list:
    out = []
    for f in range(4):
        c = Canvas(16, 16)
        # a warm glow on the ground at the base, breathing with the pulse
        c.ellipse(8.0, 13.5, (3.5, 3.0, 2.5, 3.0)[f], 1.5, "h")
        # ground ring swelling out from the base
        rx = 3.5 + f * 1.3
        _ellipse_ring(c, 8.0, 13.5, rx, max(1.6, rx * 0.36), ("R", "r", "q", "Q")[f])
        # sparks rising around the pole, a new one every frame
        for k in range(4):
            age = (f - k) % 4
            x = (5, 11, 6, 10)[k] + (1 if age >= 2 and k % 2 else -1 if age >= 2 else 0)
            y = 11 - age * 3
            c.set(x, y, ("w", "y", "o", "t")[age])
        out.append(c.grid())
    return out


TOTEM = {"w": "fire5", "y": "fire4", "o": "fire3:200", "t": "fire3:110",
         "h": "fire4:60",
         "R": "fire4:230", "r": "fire4:170", "q": "fire3:130", "Q": "fire3:70"}
register("az.fx.totem_glow", art(*_totem_frames(), legend=TOTEM, fps=6,
                                 note="shaman totem pulse: ember ring at the base, breathing halo, "
                                      "rising sparks (loop); anchor = the totem's base"))


# --- earth spirit aura --------------------------------------------------------------------
# Red-brown pebbles orbit an earth elemental (three pebbles, 30 degrees a frame
# so the loop is seamless), a dust ring turns on the ground and green spirit
# motes rise. Pebbles behind the body are smaller and darker.
_PEBBLE_BIG = """
    .kkkk.
    kaabbk
    kabbck
    kbccdk
    .kkkk.
    """
_PEBBLE_SMALL = """
    .kkk.
    kabck
    kbcdk
    .kkk.
    """


def _earth_frames() -> list:
    big = grid(_PEBBLE_BIG)
    small = grid(_PEBBLE_SMALL)
    back = swap(small, {"a": "c", "b": "c", "c": "d", "k": "K"})
    out = []
    for f in range(4):
        c = Canvas(24, 24)
        # ground: a dashed dust ring turning the other way
        _ellipse_ring(c, 12.0, 20.5, 10.0, 3.0, "u", dashes=6, phase=-f / 24, duty=0.55)
        _ellipse_ring(c, 12.0, 20.5, 8.0, 2.2, "v", dashes=6, phase=f / 24 + 0.08, duty=0.4)
        # spirit motes rising (seeded, each on its own 4-frame life)
        rng = random.Random(4242)
        for k in range(5):
            x0 = rng.randint(3, 20)
            y0 = rng.randint(14, 20)
            age = (f + k) % 4
            ch = ("G", "g", "g", "t")[age]
            c.set(x0 + (age // 2) * (1 if k % 2 else -1), y0 - age * 3, ch)
        # pebbles orbiting the body
        pebs = []
        for k in range(3):
            a = math.radians(f * 30 + k * 120)
            x = 12 + math.cos(a) * 8.5
            y = 12.5 + math.sin(a) * 4.0 - (1.5 if k == 1 else 0)
            pebs.append((math.sin(a), x, y))
        for s, x, y in sorted(pebs):
            g = big if s > 0.3 else small if s > -0.5 else back
            gw, gh = len(g[0]), len(g)
            c.blit(g, round(x - gw / 2), round(y - gh / 2))
        out.append(c.grid())
    return out


EARTH = {"a": "dust5", "b": "dust4", "c": "dust3", "d": "dust2",
         "u": "dust4:140", "v": "dust3:90",
         "G": "glowlime", "g": "glowlime:150", "t": "glowlime:70"}
register("az.fx.earth_spirit", art(*_earth_frames(), legend=EARTH, fps=6,
                                   note="earth elemental aura: orbiting pebbles, turning dust ring, "
                                        "green spirit motes (loop); anchor = the elemental's feet"))


# --- quest markers ----------------------------------------------------------------------
# The quest giver's bold golden "!" and the turn-in "?": ink outline, gold lit
# from the top-left, a white glint that runs down the glyph on the rising frame.
# They bob 1 px (up, down, down) at 3 fps; anchor = bottom centre, put it just
# above the head (a 16x24 tauren: the anchor on its row -1).
_BANG = """
    ..kkk..
    .khysk.
    .khysk.
    .khysk.
    .khysk.
    .khysk.
    .kyssk.
    ..kkk..
    .......
    ..kkk..
    .khysk.
    .kyssk.
    ..kkk..
    """
_QUERY = """
    ..kkkk..
    .khhyyk.
    khhkkysk
    .kk.kysk
    ..kyysk.
    ..khsk..
    ..kysk..
    ..kkkk..
    ........
    ..kkkk..
    ..khyk..
    ..kysk..
    ..kkkk..
    """


def _marker_frames(glyph: str, glint: list[tuple[int, int]]) -> list:
    g = grid(glyph)
    c = Canvas.of(g)
    for x, y in glint:
        c.set(x, y, "w")
    shine = c.grid()
    return [pad(shine, bottom=1), pad(g, top=1), pad(g, top=1)]


MARKER = {"h": "gold3", "y": "gold2", "s": "gold1", "w": "white"}
register("az.fx.quest_marker", art(*_marker_frames(_BANG, [(2, 1), (3, 1), (2, 2)]), legend=MARKER, fps=3,
                                   note="quest available: bold golden '!' bobbing (loop); anchor = "
                                        "bottom centre, 1-2 px above the NPC's head"))
register("az.fx.quest_turnin", art(*_marker_frames(_QUERY, [(2, 1), (3, 1), (1, 2)]), legend=MARKER, fps=3,
                                   note="quest ready to turn in: bold golden '?' bobbing (loop); anchor "
                                        "= bottom centre, 1-2 px above the NPC's head"))


# --- wind over the plains ----------------------------------------------------------------
# Two thin gusts blow left to right half a cycle apart; each fades in, runs,
# curls up at its head and fades out, so the loop never pops.
def _wind_frames() -> list:
    out = []
    for f in range(4):
        c = Canvas(16, 8)
        for k, (base, length) in enumerate(((2, 7), (5, 5))):
            ph = (f / 4 + k / 2) % 1.0
            head = round(-1 + ph * 18)
            fade = "1" if ph < 0.2 or ph > 0.8 else "2" if ph < 0.4 or ph > 0.6 else "3"
            for i in range(length):
                x = head - i
                y = base + (1 if (x + k) % 8 >= 4 else 0)
                t = i / (length - 1)
                ch = fade if t < 0.35 else chr(ord(fade) - 1) if fade != "1" and t < 0.7 else "0"
                if 0 <= x < 16:
                    c.set(x, y, ch)
            if ph >= 0.45 and 0 <= head + 1 < 16:  # the curl at the head
                y = base + (1 if (head + k) % 8 >= 4 else 0)
                c.set(head + 1, y - 1, fade)
        out.append(c.grid())
    return out


WIND = {"3": "white:200", "2": "white:140", "1": "white:90", "0": "white:50"}
register("az.fx.wind", art(*_wind_frames(), legend=WIND, fps=6,
                           note="wind gusts streaking right over the plains (loop)"))


# --- swaying grass ---------------------------------------------------------------------
# Prairie tufts laid over a ground tile; their tips lean with the wind in a
# wave that travels to the right. Golden-green, no outline (ground layer).
_TUFTS = [  # (x, blade heights, wave offset)
    (1, (4, 6), 0), (4, (7, 5, 3), 1), (7, (3, 5), 1), (9, (6, 7, 4), 2), (13, (5, 3, 6), 3),
]
_LEAN = (0, 1, 2, 1)


def _grass_frames() -> list:
    out = []
    for f in range(4):
        c = Canvas(16, 8)
        for x0, heights, off in _TUFTS:
            lean = _LEAN[(f - off) % 4]
            for j, h in enumerate(heights):
                bx = x0 + j - len(heights) // 2 + (1 if j == len(heights) - 1 and j else 0)
                for d in range(h):  # d = 0 at the root
                    t = d / max(1, h - 1)
                    dx = round(lean * t * t * (h / 7))
                    ch = "1" if t < 0.3 else "2" if t < 0.6 else "3" if d < h - 1 else "4"
                    c.set(bx + dx, 7 - d, ch)
        out.append(c.grid())
    return out


GRASS = {"1": "hound1", "2": "hound2", "3": "hound3", "4": "sand4"}
register("az.fx.grass_sway", art(*_grass_frames(), legend=GRASS, fps=5,
                                 note="prairie grass tufts swaying in the wind (loop); lay it on the "
                                      "tile's bottom edge"))


# --- campfire smoke ------------------------------------------------------------------------
# Wisps rise from the fire (bottom centre), swell, drift downwind and dissolve:
# warm and dense where the fire lights them, cool grey and thin higher up.
def _campfire_smoke_frames(n: int = 5) -> list:
    out = []
    for f in range(n):
        c = Canvas(16, 24)
        for ph in sorted(((f / n + k / 4) % 1.0 for k in range(4)), reverse=True):
            y = 21.8 - ph * 18.5
            r = 1.8 + ph * 3.0
            x = 7.8 + math.sin(ph * math.pi * 1.4) * 1.2 + ph * 2.0
            chars = "1234" if ph < 0.25 else "5678" if ph < 0.6 else "abcd"
            _cloud(c, [(x, y, r), (x - r * 0.55, y + r * 0.4, r * 0.65)], chars,
                   erode=max(0.0, ph - 0.45) * 1.9)
        out.append(c.grid())
    return out


CAMPSMOKE = {"1": "bone1:220", "2": "bone2:220", "3": "grey4:220", "4": "bone3:220",
             "5": "grey2:170", "6": "grey3:170", "7": "grey4:170", "8": "white:150",
             "a": "grey2:100", "b": "grey3:100", "c": "grey4:100", "d": "white:90"}
register("az.fx.campfire_smoke", art(*_campfire_smoke_frames(), legend=CAMPSMOKE, fps=5,
                                     note="smoke rising from a campfire (loop); anchor = the fire"))


# --- water ripple ------------------------------------------------------------------------
# A ring spreads out on the water and fades while the next one is born; the
# second ring trails by a third of a cycle so no two frames repeat.
def _ripple_frames() -> list:
    out = []
    for f in range(4):
        c = Canvas(12, 8)
        for ph in sorted(((f / 4 + k / 3) % 1.0 for k in range(2)), reverse=True):
            rx = 2.5 + ph * 3.3
            ch = "3" if ph < 0.3 else "2" if ph < 0.6 else "1"
            _ellipse_ring(c, 6.0, 4.0, rx, max(1.5, rx * 0.48), ch)
        out.append(c.grid())
    return out


RIPPLE = {"3": "white:170", "2": "water5:150", "1": "water5:80"}
register("az.fx.water_ripple", art(*_ripple_frames(), legend=RIPPLE, fps=5, anchor=(6, 4),
                                   note="rings spreading on water (loop); anchor = the ripple's centre"))


# --- cast circle -----------------------------------------------------------------------------
# A spirit-light circle on the ground under a caster: a bright outer ring, an
# inner ring of dashes turning, four rune sparks that pulse in turn, a faint
# glow inside. The dashes turn by a quarter period a frame (seamless loop).
def _cast_frames() -> list:
    out = []
    for f in range(4):
        c = Canvas(24, 16)
        cx, cy = 12.0, 8.0
        for y in range(16):  # faint glow inside
            for x in range(24):
                d = ((x + 0.5 - cx) / 10.0) ** 2 + ((y + 0.5 - cy) / 5.6) ** 2
                if d < 0.6 and bayer(x, y) < (0.45 if f % 2 else 0.3):
                    c.set(x, y, "f")
        _ellipse_ring(c, cx, cy, 11.4, 7.0, "o")
        _ellipse_ring(c, cx, cy, 10.2, 6.1, "O" if f % 2 else "o")
        _ellipse_ring(c, cx, cy, 7.4, 4.3, "d", dashes=8, phase=f / 32, duty=0.55)
        runes = [(12, 1), (22, 8), (12, 14), (1, 8)]
        for k, (x, y) in enumerate(runes):
            _star(c, x, y, 1, "w" + ("c" if k == f else "C"))
        out.append(c.grid())
    return out


CAST = {"w": "white", "c": "glowcyan", "C": "glowcyan:150", "o": "glowcyan:190", "O": "water5:230",
        "d": "water5:170", "f": "glowcyan:40"}
register("az.fx.cast_circle", art(*_cast_frames(), legend=CAST, fps=8, anchor=(12, 8),
                                  note="spirit-light circle on the ground while casting (loop); "
                                       "anchor = centre, on the caster's ground point"))


# --- hit spark ---------------------------------------------------------------------------------
# A melee blow lands: a white flash, a starburst, then embers flying apart.
def _hit_frames() -> list:
    out = []
    c = Canvas(8, 8)
    _star(c, 3, 4, 2, "wwy", diag=1, dramp="y")
    c.set(4, 4, "w")
    c.set(3, 3, "w")
    out.append(c.grid())
    c = Canvas(8, 8)
    _star(c, 4, 4, 3, "wyyo", diag=2, dramp="yo")
    out.append(c.grid())
    c = Canvas(8, 8)
    for x, y in ((0, 0), (7, 1), (0, 7), (7, 7), (4, 0), (0, 4), (7, 4)):
        c.set(x, y, "t")
    out.append(c.grid())
    return out


HIT = {"w": "white", "y": "fire5", "o": "fire4", "t": "fire4:120"}
register("az.fx.hit_spark", art(*_hit_frames(), legend=HIT, fps=14, loop=False,
                                note="melee hit: flash, starburst, flying embers (one-shot); centre "
                                     "it on the struck body"))


# --- level up ---------------------------------------------------------------------------------
# A golden pillar of light bursts up around the hero, a ring races out on the
# ground and sparkles climb the pillar, then it all thins to a few glints.
def _level_frames() -> list:
    out = []
    gy = 28.5  # the ground ring's centre line (the hero's feet)
    sparks = [(9, 26), (23, 24), (12, 20), (21, 16), (8, 14), (24, 10)]
    plan = [  # (pillar top, pillar half width, ring rx, spark rise, spark style)
        (16, 3.0, 4.0, 0, "s"),
        (0, 5.0, 8.5, 4, "S"),
        (0, 4.5, 12.5, 9, "S"),
        (2, 2.5, 15.0, 14, "s"),
        (None, 0, 0, 19, "t"),
    ]
    for f, (top, half, rx, rise, style) in enumerate(plan):
        c = Canvas(32, 32)
        if top is not None:
            for y in range(top, 31):
                u = (y - top) / 8.0  # 0 at the tip .. 1 eight rows down
                h = half * min(1.0, 0.35 + 0.65 * u) if top > 0 or f == 3 else half
                for x in range(32):
                    d = abs(x + 0.5 - 16.0) / h
                    if d > 1.0:
                        continue
                    if u < 1.0 and (top > 0 or f == 3) and bayer(x, y) > u + 0.2:
                        continue  # the tip dissolves into light
                    if f < 3:
                        ch = "W" if d < 0.3 else "g" if d < 0.6 else "a" if d < 0.85 else "b"
                    else:
                        ch = "g" if d < 0.3 else "a" if d < 0.7 else "b"
                    c.set(x, y, ch)
        if rx:
            _ellipse_ring(c, 16.0, gy, rx, rx * 0.3 + 0.5, "G" if f < 2 else "r" if f < 3 else "b")
            if f in (1, 2):
                _ellipse_ring(c, 16.0, gy, rx - 2.5, (rx - 2.5) * 0.3 + 0.5, "b", only_empty=True)
        for k, (x, y) in enumerate(sparks):
            yy = y - rise - (k % 2) * 2
            if yy < 1 or f == 0 and k > 1:
                continue
            if style == "S" and k % 2 == f % 2:
                _star(c, x, yy, 2, "wGa")
            elif style == "t":
                if k % 2:
                    _star(c, x, yy, 1, "ga")
                else:
                    c.set(x, yy, "a")
            else:
                _star(c, x, yy, 1, "wG")
        out.append(c.grid())
    return out


LEVEL = {"W": "white", "w": "white", "g": "fire5", "G": "gold2", "r": "gold2:180", "a": "gold2:160",
         "b": "gold2:80"}
register("az.fx.level_up", art(*_level_frames(), legend=LEVEL, fps=10, loop=False,
                               note="level up: golden pillar of light, ground ring, climbing sparkles "
                                    "(one-shot); anchor = the hero's feet"))
