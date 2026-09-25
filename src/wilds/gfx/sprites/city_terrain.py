"""City terrain: every ground tile, building and street structure of the five
chapter-2 locations, plus the shared street landmarks.

Themes (``manifest.CITY_THEMES``): ``sprawl`` (Насип - wet neon slum), ``docks``
(Доки - stacked rusty containers, sodium light), ``corp`` (Корпоративний ряд -
glass towers, polished stone), ``station`` (Станція «Кассандра» - deck plating,
bulkheads with portholes) and ``outpost`` (Форпост «Вертиго» - sand, adobe and
prefab modules).

How the pieces fit the renderer:

* ground (``sidewalk``, ``road``, ``neon``, ``alley``) is exactly 16x16, seamless
  with itself and with its sibling variants: every variant of a material shares
  the same edge band (noise is blended back to a common periodic field near the
  border) and features stay off the border;
* buildings are 2.5D blocks: ``wall.top`` is the roof seen from above (edge
  neutral, the renderer outlines exposed edges), ``wall.face`` is the south
  facade - rows 0-2 are the parapet (lit coping, front, drop shadow), the bottom
  row sinks into the street; facade features sit on a shared rhythm so any
  variant order reads as one building;
* street structures are anchored bottom-centre, carry a 1px ``ink`` outline and
  their own contact shadow; emitters use ``neon_*`` / ``win_warm`` / ``win_cold``
  only, so they are what glows at night.

Procedural pieces are drawn on ``procgen.Canvas`` with palette *names* as pixel
values and turned into a text grid + legend by ``_art``; hand-drawn pieces are
plain text grids. Every RNG is seeded.
"""

from __future__ import annotations

import random

from ..pixelart import Art, art, grid, mirror
from ..procgen import Canvas, bayer, fbm
from ..registry import register

T = 16
_ = "."  # transparent

# characters handed out to palette names when a name-canvas becomes an Art;
# k / K / w keep their default meaning (ink / ink2 / white)
_POOL = ("0123456789abcdefghijlmnopqrstuvxyzABCDEFGHIJLMNOPQRSTUVWXYZ"
         "#$%&*+-/:;<=>?@^_~!|()[]{},'`\"\\")
_FIXED = {"ink": "k", "ink2": "K", "white": "w"}


# --- helpers ------------------------------------------------------------------------


def _art(*frames: Canvas, fps: float = 0.0, anchor: tuple[int, int] | None = None,
         loop: bool = True, note: str = "") -> Art:
    """Name-canvases -> Art: every palette name gets a legend character."""
    names = sorted({n for f in frames for row in f.px for n in row} - {_})
    lut = {_: _}
    legend = {}
    pool = (ch for ch in _POOL)
    for n in names:
        ch = _FIXED.get(n) or next(pool)
        lut[n] = ch
        legend[ch] = n
    grids = [tuple("".join(lut[n] for n in row) for row in f.px) for f in frames]
    return art(*grids, legend=legend, fps=fps, anchor=anchor, loop=loop, note=note)


def _reg(name: str, *frames: Canvas, **kw) -> None:
    register(name, _art(*frames, **kw))


def _stamp(c: Canvas, text: str, legend: dict[str, str], x: int = 0, y: int = 0) -> None:
    """Paint a small text grid (chars -> palette names via ``legend``) onto a name-canvas."""
    g = grid(text)
    for yy, row in enumerate(g):
        for xx, ch in enumerate(row):
            if ch != _:
                c.set(x + xx, y + yy, legend.get(ch) or {"k": "ink", "K": "ink2", "w": "white"}[ch])


def _locked(seed: int, base_seed: int, cells: int = 4, octaves: int = 2, margin: float = 3.0,
            w: int = T, h: int = T, calm: float = 0.3) -> list[list[float]]:
    """Noise that is the variant's own inside but fades, near the border, into a calm
    (low-contrast) field shared by every variant of the material - so any variant meets
    any other without a seam and without a motif repeating along the tile grid."""
    a = fbm(w, h, seed, octaves, cells)
    b = fbm(w, h, base_seed, 2, 2)
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            d = min(x, y, w - 1 - x, h - 1 - y)
            t = min(1.0, d / margin)
            base = 0.5 + (b[y][x] - 0.5) * calm
            row.append(base + (a[y][x] - base) * t)
        out.append(row)
    return out


def _fill(c: Canvas, field: list[list[float]], names: list[str] | tuple[str, ...], dither: float = 0.8,
          only=None) -> Canvas:
    """Quantise a 0..1 field into ``names`` (dark -> light) with Bayer dithering."""
    n = len(names)
    for y in range(c.h):
        for x in range(c.w):
            if only is not None and c.px[y][x] not in only:
                continue
            v = field[y][x] * n + (bayer(x, y) - 0.5) * dither
            c.px[y][x] = names[max(0, min(n - 1, int(v)))]
    return c


def _speck(c: Canvas, name: str, count: int, rng: random.Random, only=None, margin: int = 1,
           box: tuple[int, int, int, int] | None = None) -> None:
    """``count`` single pixels of ``name`` away from the border (keeps edges neutral)."""
    x0, y0, x1, y1 = box or (margin, margin, c.w - 1 - margin, c.h - 1 - margin)
    for _i in range(count):
        x, y = rng.randint(x0, x1), rng.randint(y0, y1)
        if only is None or c.get(x, y) in only:
            c.set(x, y, name)


def _crack(c: Canvas, rng: random.Random, x: int, y: int, steps: int, dark: str, lit: str | None,
           box=(2, 2, 13, 13), dx_choices=(-1, 0, 1), dy_choices=(0, 1)) -> None:
    """A wandering hairline crack with a lit lip on its lower side."""
    x0, y0, x1, y1 = box
    for _i in range(steps):
        if not (x0 <= x <= x1 and y0 <= y <= y1):
            break
        c.set(x, y, dark)
        if lit and c.get(x, y + 1) != dark and y + 1 <= y1:
            c.set(x, y + 1, lit)
        x += rng.choice(dx_choices)
        y += rng.choice(dy_choices)


def _shade(name: str, ramp: str, steps: int, lo: int = 0, hi: int = 5) -> str:
    """``grey2`` -> ``grey{2+steps}`` clamped; non-ramp names pass through."""
    if not name.startswith(ramp):
        return name
    try:
        i = int(name[len(ramp):])
    except ValueError:
        return name
    return f"{ramp}{max(lo, min(hi, i + steps))}"


def _reflection(c: Canvas, x: int, y0: int, length: int, core: str, tint: str, halo: str,
                rng: random.Random, width: int = 1, hot: str | None = None) -> None:
    """Neon smeared down wet ground: a broken, rippling core that fades into tinted
    asphalt, with a faint halo either side (reads as a sign mirrored in water)."""
    dx = 0
    for k in range(length):
        t = k / max(1, length - 1)
        y = y0 + k
        if k and k % 3 == 0:  # ripple: the streak jitters sideways
            dx = rng.choice((-1, 0, 0, 1)) if width == 1 else rng.choice((0, 0, 1))
        gap = t > 0.2 and rng.random() < 0.2 + 0.45 * t
        for w in range(width):
            xx = x + dx + w
            if gap:
                if bayer(xx, y) < 0.7 - 0.5 * t:
                    c.set(xx, y, tint)
            elif t < 0.45 or (w == 0 and t < 0.6):
                c.set(xx, y, core)
            else:
                c.set(xx, y, tint)
        for xx in (x + dx - 1, x + dx + width):
            if bayer(xx, y) < 0.55 - 0.45 * t:
                c.set(xx, y, halo)
    if hot:  # the glint nearest the sign stays a real emitter (glows at night)
        c.set(x, y0, hot)


PINK_REFL = ("neon_pink_dim", "spore1", "spore0")
CYAN_REFL = ("neon_cyan_dim", "moss1", "moss0")


def _puddle(c: Canvas, cx: float, cy: float, rx: float, ry: float, water: str, deep: str, rim: str,
            glints: list[tuple[int, int, str]]) -> None:
    """A flat puddle seen from above: dark water, deeper middle, lit far rim, glints."""
    c.ellipse(cx, cy, rx, ry, water)
    c.ellipse(cx + 0.3, cy + 0.2, max(0.6, rx - 1.6), max(0.5, ry - 0.9), deep)
    for x in range(int(cx - rx), int(cx + rx) + 1):  # wet rim on the south side catches light
        y = int(cy + ry)
        if c.get(x, y - 1) in (water, deep) and c.get(x, y) not in (water, deep):
            c.set(x, y, rim)
    for x, y, n in glints:
        c.set(x, y, n)


# --- sprawl: ground ------------------------------------------------------------------

def _joints(c: Canvas, joint: str, period: int = 8, off: int = 3, keep=None) -> None:
    """Paving joints on a period that divides 16, offset from the border (seamless)."""
    for y in range(T):
        for x in range(T):
            if ((x - off) % period == 0 or (y - off) % period == 0) and (keep is None or c.get(x, y) in keep):
                c.set(x, y, joint)


MANHOLE = """
...KKKKK...
.KK43434KK.
K4343434K3K
K3434343433
.KK43434KK.
...KKKKK...
"""


def _sprawl_sidewalk(i: int) -> Canvas:
    rng = random.Random(7100 + i)
    c = Canvas(T, T)
    body = ("asph2", "conc1", "conc1", "conc1", "conc2")
    _fill(c, _locked(7110 + i, 7100, cells=4, margin=2.5), body, dither=1.0)
    _joints(c, "conc0")
    _speck(c, "asph1", 2 + i % 2, rng, only=("conc1",))   # gum / grime spots
    _speck(c, "conc3", 1 + i % 3, rng, only=("conc1", "conc2"))  # grit catching the light
    if i == 1:  # the middle slab is stained dark with old oil
        for x, y in c.where(lambda x, y, n: 5 <= x <= 9 and 6 <= y <= 9 and n != "conc0"):
            if bayer(x, y) < 0.7:
                c.set(x, y, "asph2")
    elif i == 4:  # cracked slab with a chipped corner
        _crack(c, rng, 5, 4, 8, "conc0", "conc2", box=(4, 4, 10, 10), dx_choices=(0, 1, 1))
        c.set(10, 9, "asph1")
        c.set(9, 10, "asph1")
        c.set(10, 10, "asph0")
    elif i == 5:  # a puddle mirroring a magenta sign
        _puddle(c, 8.0, 8.5, 4.6, 2.0, "asph1", "glass0", "conc2",
                [(6, 8, "neon_pink_dim"), (7, 8, "spore1"), (6, 9, "spore1"), (10, 8, "moss1")])
    elif i == 6:  # drain grate, wet streak running into it
        _stamp(c, """
            KkkkkK
            k3K3Kk
            kK3K3k
            KkkkkK
            """, {"3": "conc2"}, 5, 6)
        c.set(11, 7, "asph2")
        c.set(12, 7, "asph2")
    elif i == 7:  # litter: a crumpled flyer, a crushed can, a butt
        _stamp(c, """
            .32.
            3a33
            2332
            """, {"2": "bone2", "3": "bone3", "a": "spore3"}, 4, 9)
        _stamp(c, """
            cr
            RK
            """, {"c": "chrome1", "r": "red2", "R": "red1"}, 11, 4)
        c.set(10, 12, "bone3")
        c.set(11, 12, "rust3")
    return c


def _dash(c: Canvas, rng: random.Random, y: int, x0: int, x1: int, paint: str, worn: int,
          wear: str | None = None) -> None:
    for x in range(x0, x1 + 1):
        c.set(x, y, paint)
    for _i in range(worn):
        c.set(rng.randint(x0, x1), y, wear or c.get(x0 - 1, y))


def _sprawl_road(i: int) -> Canvas:
    rng = random.Random(7200 + i)
    c = Canvas(T, T)
    body = ("glass0", "asph1", "asph1", "asph1", "asph2")
    _fill(c, _locked(7210 + i, 7200, cells=3, margin=2.5), body, dither=0.7)
    _speck(c, "asph0", 3, rng, only=("asph1",))            # pits
    _speck(c, "asph3", 2, rng, only=("asph1", "asph2"))    # wet glints
    _dash(c, rng, 8, 4, 11, "hazard_dark", rng.randint(0, 2), "asph2")
    if i == 3:  # a sign above mirrored in the wet road
        _reflection(c, 3, 0, 8, *PINK_REFL, rng, hot="neon_pink")
        _reflection(c, 11, 0, 7, *PINK_REFL, rng, width=2)
    elif i == 4:
        _reflection(c, 6, 0, 7, *CYAN_REFL, rng, width=2, hot="neon_cyan")
        _reflection(c, 13, 1, 5, *PINK_REFL, rng)
    elif i == 5:  # manhole on the south lane
        _stamp(c, MANHOLE, {"3": "asph2", "4": "asph3"}, 3, 10)
    elif i == 6:  # pothole full of rain, a cyan sign in it
        _puddle(c, 9.0, 12.2, 4.0, 1.9, "asph0", "glass0", "asph3",
                [(8, 12, "neon_cyan_dim"), (9, 12, "moss1"), (11, 11, "asph2")])
        _crack(c, rng, 4, 11, 4, "asph0", None, box=(2, 10, 13, 14), dx_choices=(-1, -1, 0))
    elif i == 7:  # patched, cracked asphalt
        for x, y in c.where(lambda x, y, n: 2 <= x <= 7 and 2 <= y <= 5):
            c.set(x, y, "asph2" if bayer(x, y) < 0.75 else "asph1")
        c.set(2, 2, "asph1")
        c.set(7, 5, "asph1")
        _crack(c, rng, 10, 11, 5, "asph0", "asph2", box=(8, 10, 14, 14), dx_choices=(0, 1))
    return c


for _i in range(8):
    _reg(f"cp.sprawl.sidewalk@{_i}", _sprawl_sidewalk(_i), note="sprawl: grimy concrete slabs")
    _reg(f"cp.sprawl.road@{_i}", _sprawl_road(_i), note="sprawl: wet asphalt, worn centre dash")


# --- building helpers ------------------------------------------------------------------

def _parapet(c: Canvas, top: str, hi: str, front: str, shadow: str, rows: int = 3) -> None:
    """Rows 0-2 of every facade: lit coping, parapet front, drop shadow under it."""
    for x in range(T):
        c.set(x, 0, hi if bayer(x, 0) < 0.3 else top)
        c.set(x, 1, front)
        if rows > 2:
            c.set(x, 2, shadow)


def _base(c: Canvas, dark: str, deeper: str) -> None:
    """The facade's bottom row sinks into the street; the row above is half in shadow."""
    for x in range(T):
        c.set(x, T - 1, deeper)
        if bayer(x, T - 2) < 0.4 and c.get(x, T - 2) not in NEVER_SHADE:
            c.set(x, T - 2, dark)


# emitters and trims that ambient shadow must never paint over
NEVER_SHADE = {"win_warm", "win_cold", "neon_pink", "neon_cyan", "neon_green", "neon_yellow", "neon_red",
               "neon_orange", "neon_violet", "neon_pink_dim", "neon_cyan_dim", "neon_green_dim",
               "neon_yellow_dim", "neon_red_dim"}


def _box(c: Canvas, x: int, y: int, w: int, h: int, top: str, face: str, hi: str | None, dark: str,
         depth: int, shadow: str | None, outline: str = "ink") -> None:
    """A rooftop box in 3/4 view: lit top (w x h), south face ``depth`` rows tall,
    outlined, with a cast shadow falling to the south-east onto the roof."""
    if shadow:
        for yy in range(y + 1, y + h + depth + 2):
            for xx in range(x + 1, x + w + 2):
                c.set(xx, yy, shadow)
    c.rect(x, y, w, h, top)
    if hi:
        c.hline(x, x + w - 1, y, hi)
        c.vline(x, y, y + h - 1, hi)
    c.rect(x, y + h, w, depth, face)
    c.hline(x, x + w - 1, y + h + depth - 1, dark)
    c.rect(x - 1, y - 1, w + 2, h + depth + 2, outline, fill=False)


def _window(c: Canvas, x: int, y: int, kind: str, lintel: str, sill: str, w: int = 3, h: int = 3,
            rng: random.Random | None = None) -> None:
    """A recessed window: lintel shadow above, glass, lit sill below."""
    c.hline(x, x + w - 1, y - 1, lintel)
    glass = {"dark": "win_dark", "warm": "win_warm", "cold": "win_cold", "tv": "win_cold",
             "blind": "win_warm", "broken": "win_dark", "off": "win_dark"}[kind]
    c.rect(x, y, w, h, glass)
    if kind in ("dark", "off"):
        c.set(x, y, "glass2")  # sky glint in the pane
    elif kind == "warm":
        c.vline(x + w - 1, y, y + 1, "tent2")  # curtain
    elif kind == "blind":
        for yy in range(y + 1, y + h, 2):
            c.hline(x, x + w - 1, yy, "tent1")
    elif kind == "cold":
        c.set(x + 1, y + h - 1, "city1")  # somebody's head against the screen light
        c.set(x + 1, y + h - 2, "city1")
    elif kind == "broken":
        c.set(x + 1, y, "glass3")
        c.set(x, y + 1, "glass1")
        c.set(x + 2, y + 2, "ink2")
    if sill:
        c.hline(x, x + w - 1, y + h, sill)


# --- sprawl: buildings -----------------------------------------------------------------
# Tenement blocks: a lighter tar-and-gravel roof, a dark violet concrete facade with
# three storeys (two rows of small windows over a street-level floor).

SPRAWL_ROOF = ("city1", "grey0", "grey0", "grey0", "grey0", "grey0", "grey1")
ROOF_SH = "city1"   # cast shadows of rooftop kit
ROOF_EDGE = "ink2"  # soft outline of rooftop kit (no pure ink on terrain)


def _sprawl_roof_base(i: int) -> Canvas:
    rng = random.Random(7300 + i)
    c = Canvas(T, T)
    _fill(c, _locked(7310 + i, 7300, cells=3, margin=2.5), SPRAWL_ROOF, dither=0.6)
    _speck(c, "grey1", 4, rng, only=("grey0",))  # gravel catching light
    _speck(c, "grey2", 1, rng, only=("grey0",))
    _speck(c, "city1", 2, rng, only=("grey0",))
    return c


def _kit_box(c: Canvas, x: int, y: int, w: int, h: int, depth: int, top: str, face: str, hi: str,
             edge: str, shadow: str) -> None:
    """Rooftop kit in 3/4 view with a soft outline and a cast shadow to the south-east."""
    for yy in range(y + 1, y + h + depth + 1):
        for xx in range(x + 1, x + w + 1):
            c.set(xx, yy, shadow)
    c.rect(x, y, w, h, top)
    c.hline(x, x + w - 1, y, hi)
    c.rect(x, y + h, w, depth, face)
    c.rect(x - 1, y - 1, w + 2, h + depth + 2, edge, fill=False)


def _sprawl_roofs() -> list[Canvas]:
    out = [_sprawl_roof_base(i) for i in range(4)]  # 0-3: plain tar and gravel
    c = _sprawl_roof_base(4)  # 4: a bitumen seam
    for x in range(1, 15):
        c.set(x, 10, "city1" if bayer(x, 10) < 0.8 else "grey0")
    out.append(c)
    c = _sprawl_roof_base(5)  # 5: rain pooled on the flat roof
    _puddle(c, 10.5, 11.0, 3.2, 1.4, "city1", "glass0", "grey1", [(9, 11, "glass1"), (11, 10, "spore0")])
    out.append(c)
    # 6: AC unit with a fan grille
    c = _sprawl_roof_base(6)
    _kit_box(c, 3, 4, 5, 2, 2, "conc3", "conc2", "conc4", ROOF_EDGE, ROOF_SH)
    c.set(5, 4, "conc1")
    c.set(4, 5, "conc2")
    c.set(6, 5, "conc2")
    c.set(5, 5, "ink2")
    c.set(4, 7, "conc1")
    c.set(6, 7, "conc1")
    out.append(c)
    # 7: vent stacks
    c = _sprawl_roof_base(7)
    for vx, vy in ((9, 3), (5, 9)):
        _stamp(c, """
            e32e
            e21e
            .ee.
            """, {"1": "rust1", "2": "rust2", "3": "rust3", "e": ROOF_EDGE}, vx, vy)
        c.set(vx + 3, vy + 2, ROOF_SH)
        c.set(vx + 2, vy + 3, ROOF_SH)
    out.append(c)
    # 8: water tank on legs
    c = _sprawl_roof_base(8)
    c.ellipse(9.5, 12.0, 4.0, 1.6, ROOF_SH)
    _stamp(c, """
        .eeeee.
        e43332e
        e33332e
        e32322e
        e22221e
        .e111e.
        .e.e.e.
        """, {"1": "rust1", "2": "rust2", "3": "rust3", "4": "rust4", "e": ROOF_EDGE}, 5, 4)
    out.append(c)
    # 9: satellite dish, cable snaking off
    c = _sprawl_roof_base(9)
    _stamp(c, """
        .eee.
        e443e
        e432e
        .e2e.
        ..e..
        """, {"2": "conc2", "3": "conc3", "4": "conc4", "e": ROOF_EDGE}, 9, 4)
    for x, y in ((11, 9), (10, 10), (9, 10), (8, 11), (7, 11), (6, 12)):
        c.set(x, y, "ink2")
    out.append(c)
    # 10: skylight glowing from the flat below
    c = _sprawl_roof_base(10)
    _stamp(c, """
        eeeeeee
        e2Yy2ye
        eYy2Y2e
        eeeeeee
        """, {"y": "win_warm", "Y": "tent2", "2": "glass1", "e": ROOF_EDGE}, 4, 6)
    c.hline(5, 11, 10, ROOF_SH)
    out.append(c)
    # 11: roof-access hut with a lit door
    c = _sprawl_roof_base(11)
    _kit_box(c, 3, 2, 6, 2, 5, "grey2", "city2", "grey3", ROOF_EDGE, ROOF_SH)
    _stamp(c, """
        ee
        ye
        Ke
        """, {"y": "win_warm", "e": ROOF_EDGE}, 5, 6)
    out.append(c)
    return out


SPRAWL_WALL = ("city1", "city2", "city2", "city2", "city2", "city3")
TAGS = ("spore3", "hound3", "water4", "jacket2", "lira3", "cryst1")
UP_ROWS = (3, 7)  # glass rows of the two upper storeys (2 px tall each)
WIN_X = (2, 10)


def _win2(c: Canvas, x: int, y: int, kind: str, sill: str, w: int = 3) -> None:
    """A small 2px-tall upper-storey window with its sill."""
    glass = {"dark": "win_dark", "warm": "win_warm", "cold": "win_cold", "tv": "win_cold",
             "blind": "win_warm", "broken": "win_dark", "curtain": "win_warm"}[kind]
    c.rect(x, y, w, 2, glass)
    if kind == "dark":
        c.set(x, y, "glass1")
    elif kind == "broken":
        c.set(x + 1, y, "glass2")
        c.set(x + 2, y + 1, "ink2")
    elif kind == "blind":
        c.hline(x, x + w - 1, y + 1, "tent2")
    elif kind == "curtain":
        c.vline(x + w - 1, y, y + 1, "spore1")
    elif kind == "cold":
        c.set(x + 1, y + 1, "city1")  # a head against the screen light
    c.hline(x, x + w - 1, y + 2, sill)


def _sprawl_face_base(i: int, windows: tuple[str, str, str, str]) -> Canvas:
    rng = random.Random(7400 + i)
    c = Canvas(T, T)
    _fill(c, _locked(7410 + i, 7400, cells=4, margin=2.0), SPRAWL_WALL, dither=0.7)
    _parapet(c, "city4", "city5", "city3", "city1")
    k = 0
    for y in UP_ROWS:
        for x in WIN_X:
            _win2(c, x, y, windows[k], "city3")
            if rng.random() < 0.6:  # rain streak under the sill
                c.set(x + rng.randint(0, 2), y + 3, "city1")
            k += 1
    return c


def _tag(c: Canvas, x: int, y: int, shape: str, col: str, hi: str) -> None:
    """A spray tag from a tiny bitmap: 'a' paint, 'b' highlight/drip."""
    _stamp(c, shape, {"a": col, "b": hi}, x, y)


TAG_SHAPES = (
    """
    aa.a.aa
    a.aab.a
    """,
    """
    .aaa.ab
    aa.aaa.
    """,
    """
    ab.aa.a
    .aa..aa
    """,
)


def _sprawl_faces() -> list[list[Canvas]]:
    F = []
    # 0: roll-up shutter with a tag
    c = _sprawl_face_base(0, ("warm", "dark", "dark", "blind"))
    c.hline(2, 13, 10, "ink2")
    c.rect(2, 11, 12, 4, "conc1")
    c.hline(2, 13, 11, "conc2")
    c.hline(2, 13, 13, "conc0")
    _tag(c, 4, 12, TAG_SHAPES[0], "hound3", "hound4")
    c.set(12, 14, "conc3")
    F.append([c])
    # 1: noodle bar - warm window with a counter, pink tube sign flickers above
    c = _sprawl_face_base(1, ("dark", "cold", "curtain", "dark"))
    _stamp(c, """
        KKKKKKKKKKKK
        1y11y11y11yK
        101101001101
        222222222222
        K3K3K3K3K3KK
        """, {"0": "leather1", "1": "tent1", "2": "tent3", "3": "tent0", "y": "win_warm"}, 2, 10)
    c.vline(1, 10, 14, "ink2")
    c.vline(14, 10, 14, "ink2")
    on = c.copy()
    for x in range(3, 13):
        on.set(x, 9, "neon_pink" if x not in (6, 9) else "neon_pink_dim")
    dim = on.copy()
    for x in range(7, 11):
        dim.set(x, 9, "neon_pink_dim")
    F.append([on, on, dim, on, dim])
    # 2: stairwell door under a caged lamp; cyan kanji sign on the pier
    c = _sprawl_face_base(2, ("blind", "dark", "dark", "warm"))
    _stamp(c, """
        eeeee
        e1y1e
        e1K1e
        e1K1e
        e222e
        """, {"1": "conc1", "2": "conc2", "y": "win_warm", "e": "ink2"}, 3, 10)
    c.set(5, 9, "win_warm")
    sign = """
        KKK
        KaK
        aaK
        KaK
        aKa
        KKK
        """
    on = c.copy()
    _stamp(on, sign, {"a": "neon_cyan"}, 10, 9)
    off = c.copy()
    _stamp(off, sign, {"a": "neon_cyan_dim"}, 10, 9)
    off.set(11, 10, "neon_cyan")
    F.append([on, on, on, off])
    # 3: bare wall: tags, a drainpipe, a junction box
    c = _sprawl_face_base(3, ("dark", "warm", "broken", "dark"))
    c.vline(14, 2, 14, "rust2")
    c.set(14, 6, "rust3")
    c.set(14, 11, "rust3")
    _tag(c, 2, 11, TAG_SHAPES[1], "spore3", "spore4")
    _tag(c, 5, 13, TAG_SHAPES[2], "water4", "white")
    c.rect(10, 11, 2, 2, "conc2")
    c.set(10, 11, "conc3")
    c.set(11, 13, "city1")
    F.append([c])
    # 4: pawn shop, shutter half up over a cold-lit window; TV flicker upstairs
    c = _sprawl_face_base(4, ("cold", "dark", "dark", "tv"))
    c.hline(2, 13, 10, "ink2")
    c.rect(2, 11, 12, 2, "conc1")
    c.hline(2, 13, 11, "conc2")
    for x in range(3, 13):
        c.vline(x, 13, 14, "win_cold" if x % 2 else "ink2")
    c.set(5, 14, "steel2")
    c.set(9, 13, "steel2")
    tv = c.copy()
    tv.hline(10, 12, 8, "glass3")
    tv.set(11, 7, "glass3")
    F.append([c, tv])
    # 5: boarded shopfront plastered with flyers
    c = _sprawl_face_base(5, ("broken", "dark", "warm", "curtain"))
    c.rect(2, 10, 12, 5, "rust1")
    for x in (2, 6, 10):
        c.vline(x, 10, 14, "rust2")
    c.hline(2, 13, 10, "rust2")
    c.hline(2, 13, 12, "rust0")
    for x, y, n in ((4, 11, "bone3"), (5, 11, "bone3"), (4, 13, "bone2"), (8, 11, "spore2"), (9, 11, "spore2"),
                    (8, 12, "bone3"), (12, 13, "jacket2")):
        c.set(x, y, n)
    F.append([c])
    # 6: fire-escape landing and a vertical pink sign
    c = _sprawl_face_base(6, ("warm", "dark", "tv", "dark"))
    c.hline(1, 6, 9, "ink2")
    c.set(1, 8, "ink2")
    c.set(6, 8, "ink2")
    for x in (2, 4):
        c.set(x, 8, "ink2")
    c.hline(2, 13, 11, "city1")
    _stamp(c, """
        eeeee
        e1y1e
        e1K1e
        e222e
        """, {"1": "conc1", "2": "conc2", "y": "win_cold", "e": "ink2"}, 2, 11)
    sign = """
        KKKK
        KaaK
        KaKK
        KaaK
        KKaK
        KaaK
        KKKK
        """
    on = c.copy()
    _stamp(on, sign, {"a": "neon_pink"}, 10, 8)
    off = c.copy()
    _stamp(off, sign, {"a": "neon_pink_dim"}, 10, 8)
    F.append([on, off, on, on])
    for f in F:
        for fr in f:
            _base(fr, "city1", "city0")
    return F


for _i, _c in enumerate(_sprawl_roofs()):
    _reg(f"cp.sprawl.wall.top@{_i}", _c, note="sprawl roof: tar and gravel, rooftop kit")
_FPS = {1: 5, 2: 3, 4: 2, 6: 4}
for _i, _fr in enumerate(_sprawl_faces()):
    _reg(f"cp.sprawl.wall.face@{_i}", *_fr, fps=_FPS.get(_i, 0) if len(_fr) > 1 else 0,
         note="sprawl tenement facade, three storeys")


# --- docks -------------------------------------------------------------------------------
# The harbour: big oily quay slabs, a container-yard road with flush crane rails,
# and "buildings" that are stacks of rusty shipping containers - some converted into
# homes - under orange sodium light. Muted, brown and teal.

# container paint: (dark, mid, light) per colour
CONT = {
    "red": ("rust1", "cont_red", "rust3"),
    "blue": ("glass1", "cont_blue", "glass3"),
    "green": ("moss1", "cont_green", "moss3"),
    "yellow": ("gold0", "hazard_dark", "cont_yellow"),  # weathered mustard
    "teal": ("moss0", "moss2", "cryst0"),
    "white": ("stat0", "stat1", "stat2"),  # a grey reefer
    "rust": ("rust0", "rust1", "rust2"),   # nobody has painted this one in decades
}
SODIUM_REFL = ("rust3", "rust2", "rust1")


def _docks_sidewalk(i: int) -> Canvas:
    rng = random.Random(8100 + i)
    c = Canvas(T, T)
    body = ("conc0", "bone0", "bone0", "bone0", "bone0", "conc1")
    _fill(c, _locked(8110 + i, 8100, cells=3, margin=2.5), body, dither=0.8)
    _joints(c, "conc0", period=16, off=3)
    _speck(c, "rust1", 3, rng, only=("bone0",))
    _speck(c, "bone1", 2, rng, only=("bone0",))
    if i == 5:  # oil slick with an iridescent rim
        c.ellipse(9.0, 9.0, 4.0, 2.2, "asph1")
        c.ellipse(9.2, 9.1, 2.8, 1.3, "asph0")
        for x, y, n in ((6, 8, "flora1"), (7, 7, "moss1"), (11, 10, "flora1"), (12, 9, "moss1"), (9, 8, "glass1")):
            c.set(x, y, n)
    elif i == 6:  # tie-down ring bolted into the slab, rust bleeding from it
        _stamp(c, """
            .ee.
            e..e
            eKKe
            .ee.
            """, {"e": "steel3"}, 7, 6)
        c.set(7, 6, "steel4")
        for y in range(10, 13):
            c.set(9, y, "rust2" if y < 12 else "rust1")
        c.set(8, 11, "rust1")
    elif i == 7:  # rope scrap and fish-crate marks
        for x, y in ((4, 11), (5, 10), (6, 10), (7, 11), (8, 11), (9, 12), (10, 12)):
            c.set(x, y, "tent2")
            c.set(x, y + 1, "tent0")
        c.set(11, 11, "tent3")
    elif i == 8:  # drain grate with a teal stain
        _stamp(c, """
            KkkkkK
            k3K3Kk
            kK3K3k
            KkkkkK
            """, {"3": "bone1"}, 5, 7)
        c.set(6, 11, "moss1")
        c.set(7, 11, "moss0")
    elif i == 9:  # faded yellow safety chevron painted on the quay
        for k in range(4):
            c.set(5 + k, 9 - k, "hazard_dark")
            c.set(6 + k, 9 - k, "hazard_dark")
            c.set(9 + k, 6 + k, "hazard_dark")
            c.set(10 + k, 6 + k, "hazard_dark")
        c.set(8, 7, "conc1")
    return c


def _rails(c: Canvas, ys=(5, 10)) -> None:
    """Flush crane rails in every docks road tile: a lit head over a dark flangeway."""
    for y in ys:
        for x in range(T):
            c.set(x, y, "steel4" if bayer(x, y) < 0.8 else "steel3")
            c.set(x, y + 1, "steel0")


def _docks_road(i: int) -> Canvas:
    rng = random.Random(8200 + i)
    c = Canvas(T, T)
    body = ("asph1", "asph2", "asph2", "asph2", "asph3", "conc1")
    _fill(c, _locked(8210 + i, 8200, cells=3, margin=2.5), body, dither=0.9)
    _speck(c, "asph0", 2, rng, only=("asph2",))
    _speck(c, "conc2", 2, rng, only=("asph3", "conc1"))
    if i == 3:  # oil stain between the rails
        c.ellipse(8.0, 8.5, 3.6, 1.4, "asph0")
        c.set(6, 8, "flora1")
        c.set(10, 8, "moss1")
    elif i == 4:  # puddle mirroring a sodium lamp
        _puddle(c, 7.5, 13.0, 4.5, 1.6, "asph0", "glass0", "asph3", [])
        _reflection(c, 7, 12, 3, *SODIUM_REFL, rng, hot="neon_orange")
    elif i == 5:  # tyre tracks of a straddle carrier, shiny with oil
        for x in range(1, 15):
            if rng.random() < 0.7:
                c.set(x, 13, "asph1")
            if rng.random() < 0.3:
                c.set(x, 2, "asph1")
    elif i == 6:  # a cracked concrete repair patch
        for x, y in c.where(lambda x, y, n: 3 <= x <= 11 and 12 <= y <= 14):
            c.set(x, y, "conc1" if bayer(x, y) < 0.7 else "conc0")
        _crack(c, rng, 5, 12, 4, "asph0", None, box=(3, 12, 11, 14), dx_choices=(1,), dy_choices=(0, 1, -1))
    _rails(c)
    if i == 7:  # rail joint plates
        for y in (5, 10):
            c.set(7, y, "steel2")
            c.set(8, y, "steel2")
            c.set(7, y - 1, "steel3")
    return c


def _container_top(c: Canvas, x0: int, color: str, rng: random.Random, rust: int = 2) -> None:
    """One container roof seen from above, running N-S: 8 px wide, a tile long.
    A flat dusty plate with transverse dents - reads as a top, never as a side."""
    dark, mid, light = CONT[color]
    for y in range(T):
        for x in range(x0, x0 + 8):
            k = x - x0
            if k == 0:
                n = "ink2"  # gap between stacks
            elif k == 7 or y == T - 1:
                n = dark
            elif k == 1 or y == 0:
                n = light if bayer(x, y) < 0.7 else mid
            elif y % 4 == 2 and bayer(x, y) < 0.6:
                n = light  # transverse dent catching the light
            elif y % 4 == 3 and bayer(x, y) < 0.3:
                n = dark
            else:
                n = mid
            c.set(x, y, n)
    c.set(x0 + 1, 0, "chrome1")  # corner castings
    c.set(x0 + 6, 0, "chrome0")
    c.set(x0 + 1, T - 1, "chrome0")
    c.set(x0 + 6, T - 1, "ink2")
    for _i in range(rust):
        x, y = rng.randint(x0 + 2, x0 + 5), rng.randint(2, 12)
        c.set(x, y, "rust2")
        c.set(x, y + 1, "rust1")
        if rng.random() < 0.5:
            c.set(x + 1, y + 1, "rust2")


def _docks_roofs() -> list[Canvas]:
    combos = [("red", "blue"), ("teal", "rust"), ("blue", "white"), ("yellow", "red"), ("green", "teal"),
              ("white", "rust"), ("rust", "blue"), ("red", "teal"), ("teal", "white"), ("rust", "yellow")]
    out = []
    for i, (a, b) in enumerate(combos):
        rng = random.Random(8300 + i)
        c = Canvas(T, T)
        _container_top(c, 0, a, rng)
        _container_top(c, 8, b, rng)
        out.append(c)
    # rooftop life on a few of them
    c = out[2]  # a tarp and a water drum: somebody lives up here
    for x in range(2, 7):
        for y in range(3, 9):
            c.set(x, y, "tent1" if (x + 2 * y) % 5 else "tent2")
    c.hline(2, 6, 9, "tent0")
    c.vline(7, 4, 9, "ink2")
    _stamp(c, """
        .ee.
        e21e
        e11e
        .ee.
        """, {"1": "steel2", "2": "steel3", "e": "ink2"}, 10, 10)
    c = out[5]  # a sodium floodlight on a stub mast
    _stamp(c, """
        eeee
        eooe
        .ee.
        .ee.
        """, {"o": "neon_orange", "e": "ink2"}, 9, 4)
    c.set(12, 7, "stat0")
    c = out[7]  # an open roof hatch: dark inside
    c.rect(10, 6, 4, 4, "ink2")
    c.hline(10, 13, 6, "asph0")
    c.set(14, 7, CONT["teal"][2])
    return out


def _door_end(c: Canvas, x0: int, y0: int, color: str, top: bool, rng: random.Random,
              state: str = "shut") -> None:
    """A container's door end, 8x8: rails, corner posts, two doors with locking bars."""
    dark, mid, light = CONT[color]
    for y in range(y0, y0 + 8):
        for x in range(x0, x0 + 8):
            k, j = x - x0, y - y0
            if k in (0, 7):
                n = "ink2" if j in (0, 7) else dark     # corner posts / castings
            elif j == 0:
                n = light if top else mid                # top rail catches the light
            elif j == 1:
                n = dark if top else "ink2"              # shadow under the rail
            elif j == 7:
                n = dark                                 # bottom rail
            elif k in (2, 5):
                n = light if j < 6 else mid              # locking bars
            elif k in (3, 4):
                n = dark if k == 4 else mid              # the seam between the doors
            else:
                n = mid
            c.set(x, y, n)
    c.set(x0 + 3, y0 + 4, "chrome1")  # handles
    c.set(x0 + 4, y0 + 4, "chrome0")
    if rng.random() < 0.6:  # a rust bloom
        x = x0 + rng.choice((1, 6))
        c.set(x, y0 + rng.randint(2, 5), "rust2")
    if state == "open":  # right-hand door swung open: a lit room inside
        for y in range(y0 + 2, y0 + 7):
            c.set(x0 + 4, y, "ink2")
            c.set(x0 + 5, y, "win_warm" if y < y0 + 5 else "tent1")
            c.set(x0 + 6, y, "tent1" if y < y0 + 5 else "leather1")
        c.set(x0 + 6, y0 + 3, "win_warm")
    elif state == "window":  # a window cut through both doors, curtain inside
        for x in range(x0 + 2, x0 + 6):
            c.set(x, y0 + 3, "win_warm")
            c.set(x, y0 + 4, "win_warm" if x != x0 + 5 else "spore1")
        c.hline(x0 + 2, x0 + 5, y0 + 2, "ink2")
        c.hline(x0 + 2, x0 + 5, y0 + 5, light)
    elif state == "porthole":
        c.set(x0 + 3, y0 + 3, "win_cold")
        c.set(x0 + 4, y0 + 3, "win_cold")
        c.set(x0 + 3, y0 + 4, "glass2")
        c.set(x0 + 4, y0 + 4, "win_cold")


def _docks_faces() -> list[list[Canvas]]:
    # (top-left, top-right, bottom-left, bottom-right) colours + special states
    stacks = [
        (("blue", "red", "rust", "teal"), {}),
        (("teal", "rust", "red", "white"), {2: "window"}),
        (("red", "white", "blue", "rust"), {}),
        (("rust", "teal", "yellow", "blue"), {3: "open"}),
        (("white", "blue", "teal", "red"), {0: "porthole"}),
        (("green", "rust", "rust", "teal"), {}),
        (("rust", "red", "blue", "yellow"), {1: "window", 2: "open"}),
        (("teal", "blue", "red", "rust"), {}),
    ]
    F: list[list[Canvas]] = []
    for i, (cols, states) in enumerate(stacks):
        rng = random.Random(8400 + i)
        c = Canvas(T, T)
        for k, col in enumerate(cols):
            _door_end(c, (k % 2) * 8, (k // 2) * 8, col, k < 2, rng, states.get(k, "shut"))
        F.append([c])
    # a sodium lamp on a bracket, buzzing (variant 3: over the open workshop door)
    base = F[3][0]
    on = base.copy()
    _stamp(on, """
        kkk
        .o.
        """, {"o": "neon_orange"}, 11, 6)
    for x, y in ((9, 9), (10, 10), (13, 10), (14, 9)):
        on.set(x, y, "rust3")  # the lamp's pool of light on the doors below
    off = base.copy()
    _stamp(off, """
        kkk
        .o.
        """, {"o": "rust2"}, 11, 6)
    F[3] = [on, on, on, on, off, on, off, on]
    # flickering cold porthole (somebody watching a screen) on variant 4
    base = F[4][0]
    tv = base.copy()
    tv.set(3, 3, "glass3")
    tv.set(4, 4, "glass3")
    F[4] = [base, tv]
    for f in F:
        for fr in f:
            _base(fr, "ink2", "ink2")
    return F


for _i in range(10):
    _reg(f"cp.docks.sidewalk@{_i}", _docks_sidewalk(_i), note="docks: oily quay slabs")
for _i in range(8):
    _reg(f"cp.docks.road@{_i}", _docks_road(_i), note="docks: container-yard lane with crane rails")
for _i, _c in enumerate(_docks_roofs()):
    _reg(f"cp.docks.wall.top@{_i}", _c, note="docks: container roofs seen from above")
for _i, _fr in enumerate(_docks_faces()):
    _reg(f"cp.docks.wall.face@{_i}", *_fr, fps=3 if len(_fr) > 1 else 0,
         note="docks: container door ends, stacked two high")


# --- corp row -----------------------------------------------------------------------------
# Glass towers on polished stone: pale running-bond paving, a glossy road with crisp
# markings and LED studs, spotless roofs (HVAC, solar, beacons) and curtain walls whose
# mullions sit on the tile border, so each pane lives inside one tile and can be lit,
# mirror the sky, or carry a holographic ad.


def _corp_sidewalk(i: int) -> Canvas:
    rng = random.Random(9100 + i)
    c = Canvas(T, T)
    c.rect(0, 0, T, T, "stat2")  # polished: no mottling, just bevels and a few glints
    _speck(c, "stat3", 3, rng)
    for x in range(T):  # running bond: horizontal joints, vertical ones alternate per course
        c.set(x, 3, "stat1")
        c.set(x, 11, "stat1")
    for y in range(4, 11):
        c.set(11, y, "stat1")
    for y in list(range(12, 16)) + list(range(0, 3)):
        c.set(3, y, "stat1")
    for x in range(T):  # a polished bevel under each joint
        if bayer(x, 4) < 0.5:
            c.set(x, 4, "stat3")
        if bayer(x, 12) < 0.5:
            c.set(x, 12, "stat3")
    _speck(c, "chrome3", 1, rng, only=("stat2",))  # a glint
    if i == 5:  # the towers mirrored in the polish: a soft blue streak
        for k in range(6):
            c.set(5 + k, 9 - k, "glass4")
            if k % 2 == 0:
                c.set(6 + k, 9 - k, "glass4")
    elif i == 6:  # inlaid guide light
        for x in range(5, 11):
            c.set(x, 7, "win_cold" if x % 2 else "chrome2")
        c.hline(5, 10, 8, "stat1")
    elif i == 7:  # brushed-steel drain line
        c.hline(5, 10, 14, "chrome0")
        for x in range(5, 11, 2):
            c.set(x, 14, "chrome1")
        c.hline(5, 10, 13, "stat3")
    elif i == 8:  # corporate emblem inlaid in brass
        _stamp(c, """
            .gg.
            gGGg
            gG.g
            .gg.
            """, {"g": "gold1", "G": "gold2"}, 6, 5)
    return c


def _corp_road(i: int) -> Canvas:
    rng = random.Random(9200 + i)
    c = Canvas(T, T)
    c.rect(0, 0, T, T, "asph1")  # fresh, even asphalt with a faint sheen
    for y in range(T):
        for x in range(T):
            if bayer(x, y) < 0.12:
                c.set(x, y, "asph2")
    _speck(c, "glass1", 2, rng, only=("asph1",))
    _speck(c, "asph3", 1, rng, only=("asph1", "asph2"))
    for x in range(4, 12):  # crisp centre dash
        c.set(x, 8, "chrome3")
    c.set(14, 8, "neon_cyan")  # LED stud in the gap
    c.set(14, 9, "asph0")
    if i == 3:  # a tower's lit floors mirrored on the wet gloss
        _reflection(c, 5, 0, 6, "glass3", "glass1", "asph2", rng, width=2)
        _reflection(c, 11, 0, 5, "glass2", "glass1", "asph2", rng)
    elif i == 4:
        _reflection(c, 8, 0, 7, "win_cold", "glass2", "glass1", rng, width=1)
    elif i == 5:  # steel drain grille in the south lane
        _stamp(c, """
            KKKKKK
            K2K2K2
            KKKKKK
            """, {"2": "chrome1"}, 5, 11)
    elif i == 6:  # a bus-lane chevron, freshly painted
        for k in range(3):
            c.set(6 + k, 12 - k, "chrome2")
            c.set(10 - k, 12 - k, "chrome2")
    return c


def _corp_roof_base(i: int) -> Canvas:
    """Spotless roof deck in 8x8 panels: crisp seams, a lit bevel on each panel."""
    rng = random.Random(9300 + i)
    c = Canvas(T, T, "stat1")
    for y in range(T):
        for x in range(T):
            if (x - 3) % 8 == 0 or (y - 3) % 8 == 0:
                c.set(x, y, "stat0")
            elif ((x - 3) % 8 == 1 or (y - 3) % 8 == 1) and bayer(x, y) < 0.5:
                c.set(x, y, "stat2")
    _speck(c, "stat2", 2, rng, only=("stat1",))
    return c


def _corp_roofs() -> list[list[Canvas]]:
    out = [[_corp_roof_base(i)] for i in range(4)]
    # 4: HVAC unit, twin fans
    c = _corp_roof_base(4)
    _kit_box(c, 3, 3, 9, 3, 2, "stat3", "stat2", "stat4", "stat0", "stat1")
    for fx in (5, 9):
        c.ellipse(fx + 0.5, 4.5, 1.6, 1.2, "stat1")
        c.set(fx, 4, "ink2")
    out.append([c])
    # 5: solar array
    c = _corp_roof_base(5)
    for px in (2, 9):
        c.rect(px - 1, 2, 7, 11, "stat0")
        c.rect(px, 3, 5, 9, "glass2")
        for y in range(3, 12):
            for x in range(px, px + 5):
                if (x - px) % 2 == 1 or y % 3 == 0:
                    c.set(x, y, "glass1")
        c.set(px, 3, "glass4")
        c.set(px + 1, 3, "glass3")
    out.append([c])
    # 6: glass skylight over an atrium
    c = _corp_roof_base(6)
    c.rect(3, 4, 10, 7, "chrome1")
    c.rect(4, 5, 8, 5, "glass2")
    for x in range(4, 12):
        c.set(x, 7, "chrome1")
    c.set(8, 5, "chrome1")
    c.set(8, 6, "chrome1")
    c.set(8, 8, "chrome1")
    c.set(8, 9, "chrome1")
    for x, y in ((5, 5), (6, 5), (9, 8), (10, 9)):
        c.set(x, y, "win_cold")
    c.hline(4, 12, 11, "stat1")
    out.append([c])
    # 7: aircraft-warning beacon on an antenna, blinking red
    c = _corp_roof_base(7)
    c.rect(6, 11, 4, 2, "stat0")
    c.vline(7, 3, 10, "chrome1")
    c.vline(8, 4, 10, "chrome0")
    c.set(9, 12, "stat1")
    c.set(10, 12, "stat1")
    on = c.copy()
    on.set(7, 2, "neon_red")
    on.set(8, 2, "neon_red")
    off = c.copy()
    off.set(7, 2, "neon_red_dim")
    off.set(8, 2, "red1")
    out.append([on, off, off, off])
    # 8: security dome camera and a comms dish
    c = _corp_roof_base(8)
    _stamp(c, """
        .eee.
        e232e
        e221e
        .e1e.
        """, {"1": "chrome0", "2": "chrome1", "3": "chrome2", "e": "stat0"}, 3, 3)
    _stamp(c, """
        .kk.
        kKKk
        .kk.
        """, {}, 10, 10)
    c.set(11, 11, "neon_red")
    c.hline(10, 13, 13, "stat1")
    out.append([c])
    # 9: helipad corner marking
    c = _corp_roof_base(9)
    for k in range(3, 13):
        c.set(k, 3, "hazard")
        c.set(3, k, "hazard")
    c.set(3, 3, "white")
    _stamp(c, """
        w.w
        www
        w.w
        """, {}, 8, 8)
    out.append([c])
    return out


# panes: two per tile (x 1-7 and 9-15), two office floors over a lobby; mullions on x=0/8
CORP_FLOORS = ((3, 5), (7, 9), (11, 14))
# the sky mirrored down the tower: lighter high up, darker toward the street
SKY = {3: "glass3", 4: "glass3", 5: "glass2", 7: "glass3", 8: "glass2", 9: "glass2"}


def _pane(c: Canvas, x0: int, y0: int, y1: int, kind: str, rng: random.Random) -> None:
    for y in range(y0, y1 + 1):
        for x in range(x0, x0 + 7):
            if kind == "lit":
                n = "win_cold"
                if y == y1 and x % 3 == 1:
                    n = "glass2"  # desks and heads against the office light
            elif kind == "dim":
                n = "glass1" if y > y0 else "glass2"
            else:  # mirror: the sky, and a diagonal glare band sweeping across
                n = SKY.get(y, "glass2")
                if (x + y) % 12 in (0, 1):
                    n = "glass4"
            c.set(x, y, n)
    if kind == "lit" and rng.random() < 0.5:
        c.set(x0 + rng.randint(1, 5), y0, "white")  # a ceiling panel


def _corp_face_base(i: int, kinds: tuple[str, ...]) -> Canvas:
    rng = random.Random(9400 + i)
    c = Canvas(T, T, "glass2")
    _parapet(c, "chrome2", "chrome3", "chrome1", "glass1")
    k = 0
    for y0, y1 in CORP_FLOORS[:2]:
        for x0 in (1, 9):
            _pane(c, x0, y0, y1, kinds[k], rng)
            k += 1
    for y in (6, 10):  # slim spandrels between floors
        c.hline(0, T - 1, y, "glass1")
    for x in (0, 8):  # mullions catch the light
        c.vline(x, 3, 14, "chrome1")
        c.set(x, 3, "chrome2")
    return c


def _lobby(c: Canvas, kind: str) -> None:
    """Street-level floor (rows 11-14)."""
    if kind == "glass":  # double-height lobby, a cold ceiling light strip inside
        for x0 in (1, 9):
            for y in range(11, 15):
                for x in range(x0, x0 + 7):
                    n = "glass1"
                    if y == 11:
                        n = "win_cold" if x % 3 == 1 else "glass2"
                    elif y == 14 and x % 4 == 2:
                        n = "glass0"  # people / planters inside
                    c.set(x, y, n)
    elif kind == "doors":  # revolving door under a lit canopy
        _stamp(c, """
            1111111111111111
            1gg1yyyyyyyy1gg1
            1gg1yKwKKwKy1gg1
            1gg1yKwKKwKy1gg1
            """, {"1": "chrome1", "g": "glass1", "y": "win_warm"}, 0, 11)
        c.hline(3, 12, 10, "chrome2")


def _corp_faces() -> list[list[Canvas]]:
    F: list[list[Canvas]] = []
    # 0: mirror glass all the way
    c = _corp_face_base(0, ("mirror", "mirror", "mirror", "mirror"))
    _lobby(c, "glass")
    F.append([c])
    # 1: late office: two lit panes
    c = _corp_face_base(1, ("lit", "mirror", "dim", "lit"))
    _lobby(c, "glass")
    F.append([c])
    # 2: holographic ad across the second floor (cyan, cycling)
    c = _corp_face_base(2, ("mirror", "lit", "mirror", "mirror"))
    _lobby(c, "glass")
    frames = []
    ads = [
        """
        KKKKKKKKKKKKKKK
        KcccK.v.KcvvcKK
        KcKKKvvvKcKKcKK
        KcccK.v.KcvvcKK
        KKKKKKKKKKKKKKK
        """,
        """
        KKKKKKKKKKKKKKK
        KKcccKK.vKcvvcK
        KKcKKKvvvKcKKcK
        KKcccKK.vKcvvcK
        KKKKKKKKKKKKKKK
        """,
        """
        KKKKKKKKKKKKKKK
        KvvvvvvvvvvvvvK
        KvcccvvcvvvcvvK
        KvvvvvvvvvvvvvK
        KKKKKKKKKKKKKKK
        """,
    ]
    for ad in ads:
        fr = c.copy()
        _stamp(fr, ad, {"c": "neon_cyan", "v": "neon_violet", "K": "glass0"}, 1, 6)
        frames.append(fr)
    F.append([frames[0], frames[1], frames[0], frames[1], frames[2], frames[2]])
    # 3: surveillance camera under the coping, LED blinking
    c = _corp_face_base(3, ("dim", "mirror", "lit", "mirror"))
    _lobby(c, "glass")
    _stamp(c, """
        kkk.
        kKKk
        .kk.
        """, {}, 11, 3)
    on = c.copy()
    on.set(12, 4, "neon_red")
    off = c.copy()
    off.set(12, 4, "neon_red_dim")
    F.append([on, off])
    # 4: the lobby: revolving doors, brass emblem over them
    c = _corp_face_base(4, ("mirror", "mirror", "lit", "lit"))
    _lobby(c, "doors")
    F.append([c])
    # 5: pink holo ad (a face, blinking eyes)
    c = _corp_face_base(5, ("lit", "mirror", "mirror", "mirror"))
    _lobby(c, "glass")
    face = """
        KKKKKKKKKKKKKKK
        KKppppKKKp.pKKK
        KpKppKpKKpppKKK
        KKppppKKKKpKKKK
        KKKKKKKKKKKKKKK
        """
    blink = """
        KKKKKKKKKKKKKKK
        KKppppKKKp.pKKK
        KpppppppKpppKKK
        KKppppKKKKpKKKK
        KKKKKKKKKKKKKKK
        """
    a = c.copy()
    _stamp(a, face, {"p": "neon_pink", "K": "glass0"}, 1, 6)
    b = c.copy()
    _stamp(b, blink, {"p": "neon_pink", "K": "glass0"}, 1, 6)
    F.append([a, a, a, b])
    # 6: window-cleaning gondola hanging on the glass
    c = _corp_face_base(6, ("mirror", "dim", "mirror", "lit"))
    _lobby(c, "glass")
    c.vline(4, 3, 7, "ink2")
    c.vline(10, 3, 7, "ink2")
    _stamp(c, """
        kkkkkkkk
        khhhhhhk
        kkkkkkkk
        """, {"h": "hazard"}, 3, 8)
    F.append([c])
    for f in F:
        for fr in f:
            _base(fr, "glass0", "ink2")
    return F


for _i in range(9):
    _reg(f"cp.corp.sidewalk@{_i}", _corp_sidewalk(_i), note="corp: polished stone, running bond")
for _i in range(7):
    _reg(f"cp.corp.road@{_i}", _corp_road(_i), note="corp: glossy road, crisp dash, LED studs")
for _i, _fr in enumerate(_corp_roofs()):
    _reg(f"cp.corp.wall.top@{_i}", *_fr, fps=1.5 if len(_fr) > 1 else 0, note="corp tower roof")
_FPS = {2: 2, 3: 1.5, 5: 2}
for _i, _fr in enumerate(_corp_faces()):
    _reg(f"cp.corp.wall.face@{_i}", *_fr, fps=_FPS.get(_i, 0) if len(_fr) > 1 else 0,
         note="corp glass curtain wall")
