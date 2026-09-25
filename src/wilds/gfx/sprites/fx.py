"""Visual effects and vehicles: combat feedback, status icons, Tau-7 world
events, weather and city ambience, the rescue shuttle, the runner's ship and
the maglev.

Visual language (keeps effects coherent with the outlined, top-left-lit actors):

* light (slashes, plasma, zaps, sparks, glows, holograms, radio rings) has no
  outline: a white-hot core, one or two glow tones, then translucent falloff;
* matter (smoke, dust, blood, steam) has no outline either, but is shaded like
  everything else - highlight top-left, shadow bottom-right - and thins out
  through dithering plus alpha instead of just vanishing;
* floating icons (alert, thinking, zzz) and solid things (vehicles, the police
  drone, meteor debris) get the 1px ``ink`` outline of actors and items.

Timing: one-shot effects (``loop=False``, 10-14 fps) are spawned by an event and
should be removed after ``len(frames) / fps`` seconds - their last frame is
already a faint remnant. Looping effects are drawn for as long as the state
lasts (sleeping, freezing, a pending impact, a transmitting beacon...).

Anchors: unless noted, the default bottom-centre anchor goes on the tile's
ground point, so a 16x16 hit effect covers the target's tile exactly. Floating
icons sit on the head (see each note); the 3x3-zone effects (impact marker,
explosion) are anchored on the centre tile's ground point and cover the zone.
"""

from __future__ import annotations

import math
import random

from ..pixelart import art, grid, outline_grid, overlay, pad, shift, swap
from ..procgen import Canvas, bayer
from ..registry import register


# --- helpers -------------------------------------------------------------------------


def _frames(n: int, w: int, h: int, draw) -> list:
    """Grids of ``n`` frames, each painted by ``draw(canvas, i)`` on a fresh canvas."""
    out = []
    for i in range(n):
        c = Canvas(w, h)
        draw(c, i)
        out.append(c.grid())
    return out


def _ring_pts(cx: float, cy: float, r: float) -> set[tuple[int, int]]:
    """A clean 1px ring (no doubled corner pixels) of radius ``r`` around
    (cx, cy). Centres are multiples of 0.5: x.0 lies between pixels (even
    sizes), x.5 on a pixel centre (odd sizes); the ring is exactly symmetric."""
    pts: set[tuple[int, int]] = set()
    if r < 0.75:
        return {(math.floor(cx), math.floor(cy))}
    ox = 0.5 if float(cx).is_integer() else 0.0
    oy = 0.5 if float(cy).is_integer() else 0.0

    def put(dx: float, dy: float) -> None:
        for sx in (1, -1):
            for sy in (1, -1):
                pts.add((round(cx + sx * dx - 0.5), round(cy + sy * dy - 0.5)))

    lim = r / math.sqrt(2) + 0.5
    k = 0
    while k + ox <= lim:  # columns: pick the nearest row
        dx = k + ox
        if dx <= r:
            dy = math.sqrt(r * r - dx * dx)
            put(dx, round(dy - oy) + oy)
        k += 1
    k = 0
    while k + oy <= lim:  # rows: pick the nearest column
        dy = k + oy
        if dy <= r:
            dx = math.sqrt(r * r - dy * dy)
            put(round(dx - ox) + ox, dy)
        k += 1
    return pts


def _ring(c: Canvas, cx: float, cy: float, r: float, ch: str, dashes: int = 0,
          phase: float = 0.0, duty: float = 0.5) -> None:
    """Paint a clean ring; ``dashes`` > 0 breaks it into that many dashes."""
    for x, y in _ring_pts(cx, cy, r):
        if dashes:
            a = (math.atan2(y + 0.5 - cy, x + 0.5 - cx) / (2 * math.pi) + phase) % 1.0
            if (a * dashes) % 1.0 > duty:
                continue
        c.set(x, y, ch)


def _put(c: Canvas, g, dx: int, dy: int) -> None:
    """Blit a grid (or text) onto a canvas at (dx, dy)."""
    c.blit(grid(g) if isinstance(g, str) else g, dx, dy)


# --- combat and feedback ---------------------------------------------------------------
# All hit effects are 16x16, centred on the struck actor's tile (default anchor).

# A blade swing drawn across the target: the arc runs from the top-left over to
# the bottom-right (a right-facing forehand; flip it for a left-facing hero),
# white at the travelling edge, steel behind it, the tail going translucent.
SLASH_FRAMES = [
    """
    ................
    ................
    ccbaw...........
    ..cbaww.........
    ....baww........
    ......aw........
    ................
    ................
    ................
    ................
    ................
    ................
    ................
    ................
    ................
    ................
    """,
    """
    ................
    ................
    cc..............
    .ccbb...........
    ...cbbaa........
    .....bbaaw......
    ......bbaaw.....
    .......bbaww....
    .........baww...
    ..........aww...
    ............w...
    ................
    ................
    ................
    ................
    ................
    """,
    """
    ................
    ................
    cccb............
    ..cbbaa.........
    ....bbaaw.......
    .....bbaaw......
    ......bbaaw.....
    .......bbaww....
    ........bbaww...
    .........baaw...
    .........bbaww..
    ..........baww..
    ..........baww..
    ...........aaww.
    ............aww.
    .............ww.
    """,
    """
    ................
    ................
    ................
    ................
    ................
    ........c.......
    .........cc.....
    ..........cb....
    ..........cbb...
    ...........bb...
    ...........bba..
    ...........bba..
    ...........bba..
    ............baw.
    ............baw.
    .............aw.
    """,
    """
    ................
    ................
    ................
    ................
    ................
    ................
    ................
    ................
    ................
    ................
    ............c...
    ............c...
    ............cc..
    .............c..
    .............cb.
    .............cb.
    """,
]
SLASH = {"w": "white", "a": "steel5", "b": "steel4", "c": "steel4:140"}
register("fx.slash", art(*SLASH_FRAMES, legend=SLASH, fps=14, loop=False,
                         note="blade swing arc across the target (one-shot)"))


def _plasma_frames() -> list:
    """The slash arc as a plasma cutter: white-hot core, cyan body, a soft
    translucent halo and a few sparks thrown off the cutting edge."""
    sparks = {2: [(15, 10), (15, 7)], 3: [(15, 12), (14, 8), (15, 5)], 4: [(15, 11)]}
    out = []
    for i, f in enumerate(SLASH_FRAMES):
        g = grid(f)
        g = outline_grid(g, "h")
        c = Canvas.of(g)
        for x, y in sparks.get(i, []):
            c.set(x, y, "s")
        out.append(c.grid())
    return out


PLASMA = {"w": "white", "a": "glowcyan", "b": "cryst1", "c": "cryst1:150", "h": "glowcyan:60",
          "s": "cryst2"}
register("fx.slash_plasma", art(*_plasma_frames(), legend=PLASMA, fps=14, loop=False,
                                note="plasma cutter arc: white-hot core, cyan glow (one-shot)"))

# Blunt impact: a starburst that blows open into a ring of motion dashes.
PUNCH_FRAMES = [
    """
    ................
    ................
    ................
    ................
    .......yy.......
    .......ww.......
    ......wwww......
    ....yywwwwyy....
    ....yywwwwyy....
    ......wwww......
    .......ww.......
    .......yy.......
    ................
    ................
    ................
    ................
    """,
    """
    ................
    .......oo.......
    .......yy.......
    ..o....yy....o..
    ...y...yy...y...
    ....y.ywwy.y....
    ......wwww......
    .ooyyywwwwyyyoo.
    .ooyyywwwwyyyoo.
    ......wwww......
    ....y.ywwy.y....
    ...y...yy...y...
    ..o....yy....o..
    .......yy.......
    .......oo.......
    ................
    """,
    """
    .......tt.......
    .......oo.......
    .t............t.
    ..o...yyyy...o..
    ....yy....yy....
    ....y......y....
    ...y........y...
    to.y........y.ot
    to.y........y.ot
    ...y........y...
    ....y......y....
    ....yy....yy....
    ..o...yyyy...o..
    .t............t.
    .......oo.......
    .......tt.......
    """,
    """
    .......tt.......
    ................
    t..............t
    ......tttt......
    ....t......t....
    ................
    ...t........t...
    t..............t
    t..............t
    ...t........t...
    ................
    ....t......t....
    ......tttt......
    t..............t
    ................
    .......tt.......
    """,
]
PUNCH = {"w": "white", "y": "fire5", "o": "fire4", "t": "fire5:110"}
register("fx.punch", art(*PUNCH_FRAMES, legend=PUNCH, fps=14, loop=False,
                         note="fist impact starburst (one-shot)"))

# Creature bite: a maw of fangs (three above, two below, interlocking) snaps
# shut on the target, a red flash bursts behind it, puncture marks linger.
_UPPER_JAW = """
    kkkkkkkkkkkkkkkk
    kwwwgkwwwgkwwwgk
    kwwwgkwwwgkwwwgk
    .kwgk.kwgk.kwgk.
    .kwgk.kwgk.kwgk.
    ..kk...kk...kk..
    """
_LOWER_JAW = """
    .....kk...kk....
    ....kwgk.kwgk...
    ....kwgk.kwgk...
    ...kwwwgkwwwgk..
    ...kwwwgkwwwgk..
    ...kkkkkkkkkkk..
    """
_BITE_FLASH = """
    .....r..r.....
    ..r..rrrr..r..
    ...rrRRRRrr...
    .rrRRRwwRRRrr.
    .rrRRRwwRRRrr.
    ...rrRRRRrr...
    ..r..rrrr..r..
    .....r..r.....
    """
_BITE_MARKS = """
    ..d....d....d...
    ..d....d....d...
    ................
    ................
    .....d....d.....
    .....d....d.....
    """


def _bite_frames() -> list:
    cool = swap(grid(_BITE_FLASH), {"R": "r", "w": "R"})
    # (upper jaw y, lower jaw y, flash)
    plan = [(0, 10, None), (2, 8, cool), (3, 7, _BITE_FLASH), (1, 9, cool), None]
    out = []
    for step in plan:
        c = Canvas(16, 16)
        if step is None:  # only the puncture marks linger
            _put(c, _BITE_MARKS, 0, 5)
        else:
            up, low, flash = step
            if flash is not None:
                _put(c, flash, 1, 4)
            _put(c, _UPPER_JAW, 0, up)
            _put(c, _LOWER_JAW, 0, low)
        out.append(c.grid())
    return out


BITE = {"g": "bone3", "r": "red3:170", "R": "red3", "d": "red2:170"}
register("fx.bite", art(*_bite_frames(), legend=BITE, fps=14, loop=False,
                        note="creature bite: fangs snap shut on the target (one-shot)"))


def _spray(seed: int, n: int, origin: tuple[float, float], speed: float, angle: float,
           spread: float, gravity: float, frames: int, drag: float = 1.0) -> list:
    """Seeded particle paths: for each particle, its (x, y) at every frame.
    Angles in degrees on screen: 0 = right, 90 = down, -90 = up. Directions
    are spread evenly over ``angle`` +- ``spread`` (jittered), so a burst
    always radiates instead of clumping."""
    rng = random.Random(seed)
    paths = []
    for k in range(n):
        even = -spread + (k + 0.5) * 2 * spread / n
        a = math.radians(angle + even + rng.uniform(-0.35, 0.35) * spread / n)
        s = speed * rng.uniform(0.55, 1.0)
        vx, vy = math.cos(a) * s, math.sin(a) * s
        x, y = origin
        path = []
        for _f in range(frames):
            path.append((x, y))
            x, y = x + vx, y + vy
            vx, vy = vx * drag, vy * drag + gravity
        paths.append(path)
    return paths


def _streak(c: Canvas, a: tuple[float, float], b: tuple[float, float], tail: str, head: str) -> None:
    """A moving particle: a line from where it was (tail) to where it is (head)."""
    ax, ay, bx, by = int(a[0]), int(a[1]), int(b[0]), int(b[1])
    c.line(ax, ay, bx, by, tail)
    c.set(bx, by, head)


def _cloud(c: Canvas, lobes, chars: str, erode: float = 0.0) -> None:
    """A shaded puff made of round lobes ``(cx, cy, r)``.

    Each pixel is shaded by the lobe it sits deepest in, lit from the top-left
    like every sprite: ``chars`` = shadow, mid, light[, highlight]. The result
    reads as a cluster of soft balls - a shadow crescent bottom-right, a lit
    top-left, a thin highlight rim. ``erode`` (0..~1.5) thins the puff from its
    edges inward through an ordered-dither threshold."""
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
            lit = -0.6 * nx - 0.8 * ny  # 1 = facing the light
            if hi and lit > 0.62 and depth < 0.55:
                k = 3
            elif lit > 0.12:
                k = 2
            elif lit > -0.42 or depth > 0.45:
                k = 1
            else:
                k = 0
            c.set(x, y, chars[k])


def _puff_ring(cx: float, cy: float, ring: float, r: float, n: int = 6, core: float = 0.0,
               turn: float = 30.0) -> list:
    """Lobes for a burst: ``n`` puffs on a ring (squashed a little for the
    top-down view) plus an optional centre puff."""
    lobes = [(cx + math.cos(math.radians(turn + k * 360 / n)) * ring,
              cy + math.sin(math.radians(turn + k * 360 / n)) * ring * 0.85, r) for k in range(n)]
    if core:
        lobes.append((cx, cy, core))
    return lobes


def _star(c: Canvas, cx: int, cy: int, arm: int, ramp: str, diag: int = 0, dramp: str = "") -> None:
    """A 4-point sparkle centred on pixel (cx, cy). ``ramp`` colours the rays from
    the core outward (last char at the tips); optional short diagonal rays."""
    c.set(cx, cy, ramp[0])
    for d in range(1, arm + 1):
        ch = ramp[min(len(ramp) - 1, round(d / arm * (len(ramp) - 1)))] if arm > 1 else ramp[-1]
        for sx, sy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            c.set(cx + sx * d, cy + sy * d, ch)
    for d in range(1, diag + 1):
        ch = dramp[min(len(dramp) - 1, d - 1)]
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            c.set(cx + sx * d, cy + sy * d, ch)


def _bolt(c: Canvas, x0: float, y0: float, ang: float, length: float, rng: random.Random,
          ch: str) -> list:
    """A jagged lightning bolt: waypoints every ~3px, pushed sideways at random,
    joined by 1px lines. Returns the waypoints (for branching)."""
    steps = max(1, round(length / 3))
    pts = [(round(x0), round(y0))]
    for i in range(1, steps + 1):
        d = i * length / steps
        j = rng.uniform(-1.7, 1.7) if i < steps else rng.uniform(-0.8, 0.8)
        x = x0 + math.cos(ang) * d - math.sin(ang) * j
        y = y0 + math.sin(ang) * d + math.cos(ang) * j
        pts.append((round(x), round(y)))
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        c.line(ax, ay, bx, by, ch)
    return pts


# Energy hit from a drone or an android: forked violet-white bolts crackle out of
# a hot core over the target; every frame re-rolls the bolts, so it flickers.
def _zap_frames() -> list:
    rng = random.Random(4077)
    spec = [  # (bolts, length, branches, bolt char, core)
        (3, 5.0, 0, "b", "w"),
        (4, 7.5, 2, "w", "w"),
        (3, 7.0, 1, "b", "b"),
        (3, 4.5, 0, "d", ""),
    ]
    out = []
    for n, length, branches, ch, core in spec:
        c = Canvas(16, 16)
        base = rng.uniform(0, math.tau)
        tips = []
        for k in range(n):
            ang = base + k * math.tau / n + rng.uniform(-0.35, 0.35)
            pts = _bolt(c, 7.5, 7.5, ang, length * rng.uniform(0.8, 1.05), rng, ch)
            tips.append((pts, ang))
        for k in range(branches):
            pts, ang = tips[k]
            mx, my = pts[len(pts) // 2]
            _bolt(c, mx, my, ang + rng.choice((-0.9, 0.9)), 3, rng, ch)
        g = outline_grid(c.grid(), "h")
        if ch == "w":  # white-hot bolts get a violet sheath before the soft halo
            g = outline_grid(swap(g, {"h": "."}), "b")
            g = outline_grid(g, "h")
        c = Canvas.of(g)
        if core:
            c.rect(7, 7, 2, 2, core)
            if core == "w":
                for x, y in ((7, 6), (8, 6), (6, 7), (9, 7), (6, 8), (9, 8), (7, 9), (8, 9)):
                    c.set(x, y, "b")
        for pts, _ in tips:  # the bolt ends spit cold sparks
            x, y = pts[-1]
            if ch in "wb":
                c.set(x, y, "c")
        out.append(c.grid())
    return out


ZAP = {"w": "white", "b": "glowviolet", "c": "cryst2", "d": "glowviolet:150", "h": "neon_violet:55"}
register("fx.zap", art(*_zap_frames(), legend=ZAP, fps=14, loop=False,
                       note="drone/android energy hit: forked violet bolts (one-shot)"))


# The hero got hurt: a few drops burst from the wound (the sprite's centre) and
# fall away. Matter, not light - drawn lit, so it darkens at night like the hero.
def _blood_frames() -> list:
    paths = _spray(51, 5, (3.6, 3.4), 2.0, -90, 80, 0.6, 5)
    out = []
    for f in range(5):
        c = Canvas(8, 8)
        if f == 0:
            _put(c, """
                .Rr.
                RRrd
                rrdd
                .dd.
                """, 2, 2)
        for p in paths:
            if f == 0:
                continue
            tail, head = ("d", "R") if f < 3 else ("d", "r") if f < 4 else ("u", "u")
            _streak(c, p[f - 1], p[f], tail, head)
        g = c.grid()
        if f < 4:  # a dark rim keeps the drops readable over the orange suit
            g = outline_grid(g, "o")
        out.append(g)
    return out


BLOOD = {"R": "red3", "r": "red2", "d": "red1", "u": "red1:130", "o": "red0:150"}
register("fx.blood", art(*_blood_frames(), legend=BLOOD, fps=12, loop=False,
                         note="hero hurt: drops burst from the sprite centre and fall (one-shot)"))


# Short circuit / metal hit: a blue-white flash, then molten sparks fly out,
# arc down and cool from white through yellow to red.
def _spark_frames() -> list:
    paths = _spray(9, 6, (4.0, 4.0), 3.0, -90, 150, 0.5, 4)
    heads = ["", "w", "y", "o"]
    tails = ["", "y", "o", "r"]
    out = []
    for f in range(4):
        c = Canvas(8, 8)
        if f == 0:
            _put(c, """
                ..c.
                .cwc
                cwwc
                .cc.
                """, 2, 2)
            for x, y in ((1, 1), (6, 1), (1, 6), (6, 6)):
                c.set(x, y, "t")
        else:
            for p in paths:
                _streak(c, p[f - 1], p[f], tails[f], heads[f])
            if f == 1:
                c.rect(3, 3, 2, 2, "c")
        out.append(c.grid())
    return out


SPARK = {"w": "white", "c": "cryst2", "t": "cryst2:120", "y": "fire5", "o": "fire4", "r": "fire3:170"}
register("fx.spark", art(*_spark_frames(), legend=SPARK, fps=14, loop=False,
                         note="short circuit / metal hit: flash, then flying sparks (one-shot)"))


# A creature dies: its body bursts into a puff of dust that swells, breaks up
# and drifts away. Drawn lit (matter), centred on the creature.
def _poof_frames() -> list:
    specs = [  # (lobes, chars, erode)
        ([(8, 8.5, 3.4)], "3444", 0.0),
        (_puff_ring(8, 8.5, 3.0, 2.5, core=2.7), "1234", 0.0),
        (_puff_ring(8, 8.3, 4.6, 2.6, core=1.8), "1234", 0.1),
        (_puff_ring(8, 7.6, 5.8, 2.3), "5678", 0.35),
        (_puff_ring(8, 6.8, 6.6, 1.8), "5678", 0.7),
        (_puff_ring(8, 6.0, 7.0, 1.4), "abcd", 0.9),
    ]
    motes = _spray(33, 6, (8.0, 8.5), 2.3, -90, 180, 0.25, 7, drag=0.8)
    out = []
    for f, (lobes, chars, erode) in enumerate(specs):
        c = Canvas(16, 16)
        _cloud(c, lobes, chars, erode)
        if 1 <= f <= 4:
            for p in motes:
                x, y = p[f + 2]
                c.set(int(x), int(y), "p" if f < 3 else "q")
        out.append(c.grid())
    return out


POOF = {"1": "grey2", "2": "grey3", "3": "grey4", "4": "white",
        "5": "grey2:170", "6": "grey3:170", "7": "grey4:170", "8": "white:170",
        "a": "grey2:90", "b": "grey3:90", "c": "grey4:90", "d": "white:90",
        "p": "grey4", "q": "grey3:140"}
register("fx.death_poof", art(*_poof_frames(), legend=POOF, fps=12, loop=False,
                              note="creature killed: dust puff bursts and drifts apart (one-shot)"))


# Item picked up: a golden sparkle flares, sheds small glints that rise, and is gone.
def _pickup_frames() -> list:
    out = []
    glints = [(-6, -6), (6, -5), (-5, 5), (6, 6)]
    for f in range(6):
        c = Canvas(16, 16)
        if f == 0:
            _star(c, 8, 8, 2, "wg")
        elif f == 1:
            _star(c, 8, 8, 6, "wwgGGt", diag=1, dramp="g")
            for gx, gy in glints:
                _star(c, 8 + gx, 8 + gy, 1, "gt")
        elif f == 2:
            _star(c, 8, 7, 4, "wgGt", diag=1, dramp="G")
            for gx, gy in glints:
                _star(c, 8 + gx + (1 if gx > 0 else -1), 7 + gy - 1, 1, "wG")
        elif f == 3:
            _star(c, 8, 6, 2, "gG")
            for gx, gy in glints:
                c.set(8 + gx + (1 if gx > 0 else -1), 6 + gy - 2, "g")
            c.set(8, 1, "w")
        elif f == 4:
            c.set(8, 5, "G")
            for gx, gy in glints[:2]:
                c.set(8 + gx + (2 if gx > 0 else -2), 4 + gy - 2, "G")
            _star(c, 9, 1, 1, "wt")
        else:
            c.set(2, 0, "t")
            c.set(9, 1, "t")
            c.set(14, 2, "t")
        out.append(c.grid())
    return out


PICKUP = {"w": "white", "g": "gold3", "G": "gold2", "t": "gold2:120"}
register("fx.pickup", art(*_pickup_frames(), legend=PICKUP, fps=12, loop=False,
                          note="item picked up: gold sparkle with rising glints (one-shot)"))


# Medkit / stim: a green pulse spreads at the feet while plus signs and motes
# rise off the body and fade.
_PLUS = {
    3: [".g.", "gwg", ".g."],
    5: ["..g..", "..G..", "gGwGg", "..G..", "..g.."],
    1: ["t"],
}


def _heal_frames() -> list:
    # (x, birth frame, start y, sizes over its life)
    pluses = [(8, 0, 10, (3, 5, 5, 3, 1)), (4, 2, 11, (3, 3, 5, 3, 1)), (12, 3, 12, (1, 3, 3, 3, 1))]
    motes = [(2, 1, 14), (6, 0, 13), (10, 2, 14), (13, 4, 13), (5, 4, 15), (11, 5, 15)]  # x, birth, y
    out = []
    for f in range(8):
        c = Canvas(16, 16)
        if f < 3:  # the pulse ring at the feet
            rx = (3.5, 5.5, 7.0)[f]
            ch = ("a", "t", "t")[f]
            for x in range(16):
                for y in range(11, 16):
                    d = ((x + 0.5 - 8) / rx) ** 2 + ((y + 0.5 - 14) / (rx * 0.35)) ** 2
                    if 0.55 <= d <= 1.0:
                        c.set(x, y, ch)
        for x0, birth, y0 in motes:
            age = f - birth
            if 0 <= age < 4:
                c.set(x0, y0 - age * 3, "G" if age < 2 else "t")
        crosses = Canvas(16, 16)
        for x0, birth, y0, sizes in pluses:
            age = f - birth
            if 0 <= age < len(sizes):
                size = sizes[age]
                g = _PLUS[size]
                y = y0 - age * 2
                _put(crosses, g, x0 - size // 2, y - size // 2)
        c.blit(outline_grid(crosses.grid(), "h"))
        out.append(c.grid())
    return out


HEAL = {"w": "white", "G": "glowlime", "g": "neon_green", "t": "neon_green:130", "a": "glowlime:170",
        "h": "neon_green:70"}
register("fx.heal", art(*_heal_frames(), legend=HEAL, fps=10, loop=False,
                        note="medkit / stim: green pulse at the feet, pluses rise (one-shot)"))


# The hero is freezing: one ice glint twinkles and melts away. The renderer
# spawns one every ~0.8 s at a random spot on the upper body (0.8 s each).
def _frost_frames() -> list:
    out = []
    for f in range(4):
        c = Canvas(8, 8)
        if f == 0:
            _star(c, 4, 4, 1, "ca")
        elif f == 1:
            _star(c, 4, 4, 2, "wcb")
        elif f == 2:
            _star(c, 4, 4, 3, "wwcb", diag=2, dramp="ba")
        else:
            _star(c, 4, 4, 1, "ba")
        g = c.grid()
        out.append(outline_grid(g, "h") if f in (1, 2) else g)
    return out


FROST = {"w": "white", "c": "cryst2", "b": "water4", "a": "water4:140", "h": "water2:110"}
register("fx.frost", art(*_frost_frames(), legend=FROST, fps=5, loop=False,
                         note="freezing: an ice glint twinkles (one-shot, 0.8 s)"))


# --- floating icons -----------------------------------------------------------------------
# Outlined like items so they read over any ground, day or night.

def _glyph(rows: list[str], faded: bool) -> tuple:
    g = outline_grid(pad(grid(rows), 1, 1, 1, 1), "k")
    return swap(g, {"w": "f", "b": "g", "k": "o"}) if faded else g


# Sleeping: a small "z" then a big "Z" swell up one after the other; the
# renderer spawns one every 1.4 s and drifts it up and to the right.
_Z_SMALL = ["wwww", "..w.", ".w..", "bbbb"]
_Z_BIG = ["wwwww", "...w.", "..w..", ".w...", "bbbbb"]


def _zzz_frames() -> list:
    # per frame: small z state, big Z state (None / "faded" / "solid")
    plan = [("faded", None), ("solid", None), ("solid", "faded"), ("solid", "solid"),
            ("faded", "solid"), (None, "solid"), (None, "faded")]
    out = []
    for small, big in plan:
        c = Canvas(12, 12)
        if small:
            _put(c, _glyph(_Z_SMALL, small == "faded"), 0, 6)
        if big:
            _put(c, _glyph(_Z_BIG, big == "faded"), 5, 0)
        out.append(c.grid())
    return out


ZZZ = {"b": "water5", "f": "white:130", "g": "water5:130", "o": "ink:130"}
register("fx.zzz", art(*_zzz_frames(), legend=ZZZ, fps=5, loop=False,
                       note="sleeping: z then Z swell up (1.4 s; spawned every 1.4 s, drifting)"))

# A hostile noticed the hero: a red "!" that hops, then hangs there.
_ALERT = """
    ..kkkk..
    ..kyrk..
    ..kyrk..
    ..kyrk..
    ..krRk..
    ..kkkk..
    ........
    ..kkkk..
    ..kyRk..
    ..kRRk..
    ..kkkk..
    """


def _alert_frames() -> list:
    g = grid(_ALERT)
    hop = swap(g, {"y": "w"})
    rest = pad(g, top=1)
    return [pad(hop, bottom=1), rest, rest, rest]


ALERT = {"y": "red4", "r": "neon_red", "R": "red2"}
register("fx.alert", art(*_alert_frames(), legend=ALERT, fps=5,
                         note="a hostile noticed the hero: '!' hops then hangs; anchor = bottom "
                              "centre, put it just above the head"))

# The AI hero is thinking: a thought bubble whose dots fill in one by one, in
# the same colours and rhythm as the renderer's own drawn bubble.
_THINK = """
    ...kkkkkkkkkk...
    ..kwwwwwwwwwwk..
    .kwwwwwwwwwwwbk.
    .kwwwwwwwwwwwbk.
    ..kbbbbbbbbbbk..
    ...kkkkkkkkkk...
    ................
    ..kk............
    .kwwk...........
    .kwbk...........
    ..kk............
    kk..............
    """


def _thinking_frames() -> list:
    out = []
    for n in (1, 2, 3):
        c = Canvas.of(grid(_THINK))
        for i in range(n):
            c.rect(4 + i * 3, 2, 2, 2, "d")
        out.append(c.grid())
    return out


THINK = {"w": "stat4", "b": "water5", "d": "steel1"}
register("fx.thinking", art(*_thinking_frames(), legend=THINK, fps=2.5, anchor=(0, 11),
                            note="AI hero thinking: bubble with filling dots; anchor = the tail's "
                                 "last dot, put it on top of the head (bubble floats up-right)"))
