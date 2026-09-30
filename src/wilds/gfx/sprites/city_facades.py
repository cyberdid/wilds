"""Building facades at street scale, stacked into real multi-storey buildings.

The 16x16 ``wall.face`` tiles squeeze a whole three-storey building into one
person's height, so a street read as a doll's house. These modules are drawn to
the runner's scale instead (a person is ~15 px): a storey is 22 px with windows
taller than the runner's head, the street floor is 28 px with doors a person
walks through. The renderer stacks, per 16 px column of a building,
``cap`` + N x ``storey`` + ``ground`` into one strip (``SpriteBank.facade``).

Every module tiles horizontally with any sibling: piers stay on the column edges,
floor slabs and sills run edge to edge at the same rows in every variant.
"""

from __future__ import annotations

import random

from ..procgen import Canvas, bayer
from .city_terrain import CONT, SPRAWL_WALL, TAG_SHAPES, _fill, _locked, _porthole, _reg, _stamp

W = 16
CAP_H, STOREY_H, GROUND_H = 4, 22, 28
WIN_Y, WIN_H = 5, 11  # upper-storey window glass rows 5..15
WIN_X = (2, 9)
WIN_W = 5


def _wall(seed: int, base: int, h: int, ramp: tuple[str, ...], dither: float = 0.7) -> Canvas:
    c = Canvas(W, h)
    return _fill(c, _locked(seed, base, cells=4, margin=2.0, w=W, h=h), ramp, dither=dither)


def _cap(c: Canvas, coping: str, hi: str, front: str, shadow: str) -> Canvas:
    for x in range(W):
        c.set(x, 0, hi if bayer(x, 0) < 0.3 else coping)
        c.set(x, 1, front)
        c.set(x, 2, front)
        c.set(x, 3, shadow)
    return c


def _slab(c: Canvas, ledge: str, shadow: str) -> None:
    """The floor slab closing every storey: a lit ledge over a shadow line (same rows everywhere)."""
    c.hline(0, W - 1, STOREY_H - 2, ledge)
    c.hline(0, W - 1, STOREY_H - 1, shadow)


def _win(c: Canvas, x: int, kind: str, frame: str, sill: str, y: int = WIN_Y, h: int = WIN_H,
         w: int = WIN_W, rng: random.Random | None = None) -> None:
    """A tall window: dark reveal above, glass, a transom bar, a lit sill below."""
    glass = {"dark": "win_dark", "warm": "win_warm", "cold": "win_cold", "tv": "win_cold", "blind": "win_warm",
             "curtain": "win_warm", "broken": "win_dark", "off": "win_dark"}[kind]
    c.hline(x, x + w - 1, y - 1, frame)
    c.rect(x, y, w, h, glass)
    c.hline(x, x + w - 1, y + 3, frame)  # transom
    if kind in ("dark", "off"):
        c.set(x, y, "glass2")
        c.set(x + 1, y + 4, "glass1")
        c.set(x, y + 5, "glass1")
    elif kind == "warm":
        c.vline(x + w - 1, y, y + h - 1, "tent2")  # curtain pulled aside
        c.vline(x + w - 2, y + 4, y + h - 1, "tent1")
    elif kind == "curtain":
        for xx in range(x, x + w):
            c.vline(xx, y + 4, y + h - 1, "spore1" if xx % 2 else "spore2")
    elif kind == "blind":
        for yy in range(y + 4, y + h, 2):
            c.hline(x, x + w - 1, yy, "tent1")
    elif kind in ("cold", "tv"):
        cx = x + w // 2
        c.set(cx, y + h - 4, "city1")  # somebody's head against the screen light
        c.hline(cx - 1, cx + 1, y + h - 3, "city1")
        c.hline(cx - 2, cx + 2, y + h - 2, "city1")
        c.hline(x, x + w - 1, y + h - 1, "city1")
    elif kind == "broken":
        c.set(x + 1, y + 5, "glass3")
        c.set(x + 2, y + 6, "glass2")
        c.set(x + 3, y + 7, "ink2")
        c.set(x + 1, y + 8, "ink2")
    c.hline(x, x + w - 1, y + h, sill)
    if rng is not None and rng.random() < 0.6:  # a rain streak under the sill
        c.set(x + rng.randint(0, w - 1), y + h + 1, "city1")


def _door(c: Canvas, x: int, frame: str, light: str = "win_warm", lamp: str | None = "neon_orange") -> None:
    """A street door (7 x 17): frame, a lit stairwell behind, threshold, a caged lamp."""
    top = GROUND_H - 1 - 17
    c.rect(x - 1, top - 1, 9, 19, frame)
    c.rect(x, top, 7, 17, "ink2")
    c.rect(x + 1, top + 1, 5, 7, light)  # the lit stairwell through the glass
    for k in range(4):
        c.hline(x + 1, x + 5 - k, top + 11 + k, "city1" if k % 2 else "conc1")  # stairs
    c.hline(x, x + 6, GROUND_H - 2, "conc2")  # threshold
    c.set(x + 5, top + 10, "chrome1")  # handle
    if lamp:
        c.set(x + 3, top - 3, "ink2")
        c.set(x + 3, top - 2, lamp)


def _sign(c: Canvas, x0: int, x1: int, y: int, tube: str, board: str = "ink2") -> None:
    """A shop sign band: dark board with a neon strip and letters-ish dashes."""
    c.rect(x0, y, x1 - x0 + 1, 4, board)
    for x in range(x0 + 1, x1):
        if (x - x0) % 3 != 2:
            c.set(x, y + 1, tube)
            c.set(x, y + 2, tube if (x + y) % 2 else board)


def _sink(c: Canvas, deeper: str, dark: str) -> None:
    """The ground floor's bottom row sinks into the street, the row above is half in shadow."""
    c.hline(0, W - 1, GROUND_H - 1, deeper)
    for x in range(W):
        if bayer(x, GROUND_H - 2) < 0.4 and c.get(x, GROUND_H - 2) not in ("win_warm", "win_cold", "conc2"):
            c.set(x, GROUND_H - 2, dark)


# --- sprawl: violet concrete tenements, neon, fire escapes ------------------------------------

def _sprawl_storey(i: int, kinds: tuple[str, str]) -> Canvas:
    rng = random.Random(21000 + i)
    c = _wall(21010 + i, 21000, STOREY_H, SPRAWL_WALL)
    for x, kind in zip(WIN_X, kinds):
        _win(c, x, kind, "city1", "city4", rng=rng)
    _slab(c, "city3", "city1")
    return c


def _sprawl_storeys() -> list[list[Canvas]]:
    F = [[_sprawl_storey(i, k)] for i, k in enumerate(
        (("warm", "dark"), ("dark", "dark"), ("cold", "warm"), ("blind", "broken"), ("curtain", "dark"),
         ("dark", "warm")))]
    # a fire-escape landing across the storey, ladder going down
    c = _sprawl_storey(10, ("dark", "warm"))
    c.hline(0, W - 1, 17, "ink2")
    for x in range(0, W, 3):
        c.vline(x, 15, 16, "ink2")
    c.hline(0, W - 1, 15, "ink2")
    c.vline(13, 18, 21, "ink2")
    c.vline(15, 18, 21, "ink2")
    F.append([c])
    # an AC unit dripping under a window, and a vertical pink sign on the pier (flickers)
    c = _sprawl_storey(11, ("warm", "cold"))
    c.rect(9, 16, 5, 3, "grey2")
    c.hline(9, 13, 16, "grey3")
    c.set(11, 17, "ink2")
    c.set(12, 20, "water3")
    on = c.copy()
    off = c.copy()
    for cc, tube in ((on, "neon_pink"), (off, "neon_pink_dim")):
        cc.rect(7, 2, 2, 15, "ink2")
        for y in range(3, 16, 2):
            cc.set(7, y, tube)
            cc.set(8, y + 1, tube)
    F.append([on, on, off, on])
    return F


def _sprawl_grounds() -> list[list[Canvas]]:
    def base(i: int) -> Canvas:
        c = _wall(21510 + i, 21500, GROUND_H, SPRAWL_WALL)
        c.hline(0, W - 1, 0, "city3")  # the ledge under the first storey
        c.hline(0, W - 1, 1, "city1")
        return c

    F = []
    # 0: a door to the stairwell
    c = base(0)
    _door(c, 5, "city1")
    F.append([c])
    # 1: roll-up shutter with a tag
    c = base(1)
    c.rect(1, 9, 14, 17, "conc1")
    for y in range(10, 26, 2):
        c.hline(1, 14, y, "conc2")
    c.hline(1, 14, 8, "ink2")
    _stamp(c, TAG_SHAPES[0], {"a": "hound3", "b": "hound4"}, 4, 16)
    F.append([c])
    # 2/3: shopfronts - a neon sign over a lit window full of goods (flickering sign)
    for k, (tube, dim) in enumerate((("neon_cyan", "neon_cyan_dim"), ("neon_yellow", "neon_yellow_dim"))):
        c = base(2 + k)
        c.rect(1, 11, 14, 14, "city1")
        c.rect(2, 12, 12, 12, "win_warm")
        for x in range(3, 13, 3):
            c.rect(x, 18, 2, 5, ("jacket2", "spore2", "cryst1", "gold2")[x % 4])
        c.hline(2, 13, 17, "tent2")
        on, off = c.copy(), c.copy()
        _sign(on, 1, 14, 5, tube)
        _sign(off, 1, 14, 5, dim)
        F.append([on, on, on, off, on])
    # 4: boarded shopfront plastered with flyers
    c = base(4)
    c.rect(1, 9, 14, 17, "rust1")
    for x in (1, 6, 11):
        c.vline(x, 9, 25, "rust2")
    for x, y, n in ((3, 12, "bone3"), (4, 12, "bone3"), (3, 13, "bone2"), (8, 15, "spore2"), (9, 15, "spore2"),
                    (8, 16, "bone3"), (12, 20, "jacket2"), (13, 20, "jacket2")):
        c.set(x, y, n)
    F.append([c])
    # 5: a noodle counter: open hatch, steam, red lantern
    c = base(5)
    c.rect(1, 10, 14, 10, "ink2")
    c.rect(2, 11, 12, 8, "win_warm")
    c.hline(1, 14, 20, "leather2")
    c.hline(1, 14, 21, "leather1")
    for x, y in ((4, 12), (5, 11), (9, 13), (10, 12)):
        c.set(x, y, "white:120")
    c.set(13, 6, "ink2")
    c.rect(12, 7, 3, 3, "neon_red")
    F.append([c])
    for f in F:
        for fr in f:
            _sink(fr, "city0", "city1")
    return F


# --- docks: stacked shipping containers, sodium light ----------------------------------------

def _container(color: str, i: int, state: str = "shut") -> Canvas:
    """One container side, a storey tall: top rail, corrugated ribs, bottom rail."""
    dark, mid, light = CONT[color]
    rng = random.Random(22000 + i)
    c = Canvas(W, STOREY_H, mid)
    for x in range(W):
        rib = (dark, mid, light, mid)[x % 4]
        c.vline(x, 2, STOREY_H - 3, rib)
    c.hline(0, W - 1, 0, light)
    c.hline(0, W - 1, 1, dark)
    c.hline(0, W - 1, STOREY_H - 2, dark)
    c.hline(0, W - 1, STOREY_H - 1, "ink2")  # the gap between stacked containers
    for _k in range(3):  # rust blooms
        x, y = rng.randint(1, 14), rng.randint(4, 17)
        c.set(x, y, "rust2")
        c.set(x, y + 1, "rust1")
    if state == "window":  # cut through the steel and turned into a home
        c.rect(4, 6, 8, 8, "ink2")
        c.rect(5, 7, 6, 6, "win_warm")
        c.vline(10, 7, 12, "spore1")
        c.hline(4, 11, 14, light)
    elif state == "porthole":
        c.rect(6, 7, 4, 4, "win_cold")
        c.set(6, 7, "glass3")
        c.rect(5, 6, 6, 1, dark)
    elif state == "post":  # corner post and castings where two containers meet
        c.vline(0, 0, STOREY_H - 1, "ink2")
        c.vline(1, 0, STOREY_H - 1, dark)
        c.vline(15, 0, STOREY_H - 1, dark)
    return c


def _docks_storeys() -> list[list[Canvas]]:
    F = [[_container(col, i)] for i, col in enumerate(("red", "blue", "rust", "teal", "green", "white"))]
    F.append([_container("yellow", 6, "window")])
    F.append([_container("teal", 7, "post")])
    tv = _container("white", 8, "porthole")
    flick = tv.copy()
    flick.set(8, 9, "glass3")
    F.append([tv, flick])
    return F


def _docks_grounds() -> list[list[Canvas]]:
    F = []
    for i, (color, state) in enumerate((("rust", "gate"), ("blue", "open"), ("red", "shut"), ("teal", "lamp"))):
        dark, mid, light = CONT[color]
        c = Canvas(W, GROUND_H, mid)
        for x in range(W):
            c.vline(x, 2, GROUND_H - 3, (dark, mid, light, mid)[x % 4])
        c.hline(0, W - 1, 0, light)
        c.hline(0, W - 1, 1, dark)
        if state == "gate":  # a warehouse roll-up gate
            c.rect(1, 7, 14, 19, "steel2")
            for y in range(8, 26, 2):
                c.hline(1, 14, y, "steel1")
            c.hline(1, 14, 6, "hazard")
        elif state == "open":  # doors swung open: a lit workshop inside
            c.rect(2, 8, 12, 18, "ink2")
            c.rect(3, 9, 10, 10, "win_warm")
            c.rect(3, 19, 10, 6, "tent1")
            c.vline(13, 8, 25, light)
            c.rect(5, 16, 3, 3, "leather1")  # a workbench
        elif state == "lamp":  # a buzzing sodium lamp over a shut door
            _door(c, 5, dark, light="win_dark", lamp=None)
            on, off = c.copy(), c.copy()
            for cc, bulb in ((on, "neon_orange"), (off, "rust2")):
                _stamp(cc, """
                    kkk
                    .o.
                    """, {"o": bulb}, 7, 3)
            F.append([on, on, on, off, on, on, off])
            continue
        else:
            _door(c, 5, dark, light="win_dark", lamp=None)
        F.append([c])
    for f in F:
        for fr in f:
            _sink(fr, "ink2", "ink2")
    return F


# --- corp row: glass curtain walls, lobbies -------------------------------------------------

SKY_ROWS = ("glass3", "glass3", "glass3", "glass2", "glass2", "glass2", "glass2", "glass1")


def _pane(c: Canvas, x0: int, y0: int, y1: int, kind: str, rng: random.Random) -> None:
    for y in range(y0, y1 + 1):
        for x in range(x0, x0 + 7):
            if kind == "lit":
                n = "win_cold"
                if y >= y1 - 3 and x % 3 == 1:
                    n = "glass2"  # desks and heads against the office light
            elif kind == "dim":
                n = "glass1" if y > y0 + 1 else "glass2"
            else:  # mirror: the sky, and a diagonal glare band
                n = SKY_ROWS[min(len(SKY_ROWS) - 1, (y - y0) // 2)]
                if (x + y) % 14 in (0, 1):
                    n = "glass4"
            c.set(x, y, n)
    if kind == "lit" and rng.random() < 0.6:
        c.hline(x0 + 1, x0 + 4, y0, "white")  # a ceiling light panel


def _corp_storey(i: int, kinds: tuple[str, str]) -> Canvas:
    rng = random.Random(23000 + i)
    c = Canvas(W, STOREY_H, "glass2")
    c.hline(0, W - 1, 0, "chrome1")  # spandrel between floors
    c.hline(0, W - 1, 1, "glass1")
    for x0, kind in zip((1, 9), kinds):
        _pane(c, x0, 2, STOREY_H - 1, kind, rng)
    for x in (0, 8):  # mullions catch the light
        c.vline(x, 0, STOREY_H - 1, "chrome1")
        c.set(x, 0, "chrome2")
    return c


def _corp_storeys() -> list[list[Canvas]]:
    F = [[_corp_storey(i, k)] for i, k in enumerate(
        (("mirror", "mirror"), ("lit", "mirror"), ("mirror", "lit"), ("lit", "lit"), ("dim", "mirror"),
         ("dim", "lit")))]
    # a corporate logo band across the floor (a slow pulse)
    c = _corp_storey(9, ("mirror", "mirror"))
    on, off = c.copy(), c.copy()
    for cc, tube in ((on, "neon_violet"), (off, "neon_cyan_dim")):
        cc.rect(0, 8, W, 5, "ink2")
        for x in range(1, W - 1):
            if x % 4 != 3:
                cc.set(x, 10, tube)
    F.append([on, on, off])
    return F


def _corp_grounds() -> list[list[Canvas]]:
    F = []
    for i, kind in enumerate(("lobby", "doors", "desk", "holo")):
        c = Canvas(W, GROUND_H, "glass1")
        c.hline(0, W - 1, 0, "chrome2")
        c.hline(0, W - 1, 1, "chrome1")
        c.rect(0, 2, W, 3, "stat2")  # a stone band over the lobby
        c.hline(0, W - 1, 4, "stat1")
        for y in range(5, GROUND_H - 1):
            for x in range(W):
                c.set(x, y, "win_cold" if y < 8 else ("glass2" if (x + y) % 9 else "glass3"))
        for x in (0, 8):
            c.vline(x, 5, GROUND_H - 1, "chrome1")
        if kind == "doors":  # revolving door
            c.rect(4, 9, 8, 17, "chrome1")
            c.rect(5, 10, 6, 15, "glass3")
            c.vline(8, 10, 24, "chrome2")
        elif kind == "desk":  # the security desk and a guard
            c.rect(2, 19, 12, 6, "stat3")
            c.hline(2, 13, 19, "stat4")
            c.set(10, 16, "skin2")
            c.rect(9, 17, 3, 2, "suit1")
        elif kind == "holo":  # a holographic logo turning in the lobby
            f = [c.copy() for _k in range(3)]
            for k, fr in enumerate(f):
                w = (3, 5, 3)[k]
                fr.rect(8 - w // 2, 12, w, w, "glowcyan:170")
                fr.set(8, 12 + w // 2, "white")
            F.append(f)
            continue
        F.append([c])
    for f in F:
        for fr in f:
            _sink(fr, "stat0", "stat1")
    return F


# --- station «Кассандра»: bulkheads, portholes onto space -------------------------------------

def _station_storey(i: int, feature: str) -> Canvas:
    rng = random.Random(24000 + i)
    c = Canvas(W, STOREY_H, "stat1")
    c.hline(0, W - 1, 0, "steel1")
    for x in range(2, 14):
        c.set(x, 1, "win_cold")  # a light strip under the deck above
    c.hline(0, W - 1, 2, "stat2")
    for y in range(3, STOREY_H - 2):
        c.set(0, y, "steel2")
        c.set(15, y, "stat2")
    for x, y in ((2, 4), (13, 4), (2, 17), (13, 17)):
        c.set(x, y, "stat3")  # rivets
    if feature == "portholes":
        stars = [(1, 2, "white"), (3, 1, "glass3"), (2, 4, "white")]
        _porthole(c, 3, 7, 6, stars)
        _porthole(c, 9, 8, 5, stars[:2])
    elif feature == "vent":
        c.rect(4, 7, 8, 8, "steel0")
        for y in range(8, 15, 2):
            c.hline(4, 11, y, "steel2")
    elif feature == "pipes":
        for y, col in ((9, "steel3"), (12, "hazard"), (15, "steel2")):
            c.hline(0, W - 1, y, col)
            c.hline(0, W - 1, y + 1, "steel0")
    elif feature == "screen":
        c.rect(3, 7, 10, 7, "ink2")
        c.rect(4, 8, 8, 5, "win_cold")
        c.hline(5, 9, 10, "glass1")
    _ = rng
    _slab(c, "stat2", "steel0")
    return c


def _station_storeys() -> list[list[Canvas]]:
    F = [[_station_storey(i, f)] for i, f in enumerate(("portholes", "vent", "pipes", "portholes"))]
    s = _station_storey(4, "screen")
    blink = s.copy()
    blink.hline(5, 10, 11, "glass3")
    F.append([s, blink])
    return F


def _station_grounds() -> list[list[Canvas]]:
    F = []
    for i, kind in enumerate(("hatch", "shop", "cargo")):
        c = Canvas(W, GROUND_H, "stat1")
        c.hline(0, W - 1, 0, "steel1")
        c.hline(0, W - 1, 1, "stat2")
        if kind == "hatch":  # an airlock hatch with hazard stripes
            c.rect(3, 8, 10, 18, "steel2")
            c.rect(4, 9, 8, 16, "steel3")
            c.vline(8, 9, 24, "ink2")
            for y in range(6, 8):
                for x in range(3, 13):
                    c.set(x, y, "hazard" if (x + y) % 4 < 2 else "hazard_dark")
            c.set(6, 16, "neon_green")
        elif kind == "shop":
            c.rect(1, 8, 14, 16, "ink2")
            c.rect(2, 9, 12, 14, "win_cold")
            c.hline(2, 13, 18, "stat3")
            _sign(c, 1, 14, 3, "neon_cyan", "steel0")
        else:  # a cargo door
            c.rect(1, 6, 14, 20, "steel2")
            for y in range(7, 26, 3):
                c.hline(1, 14, y, "steel1")
            c.set(13, 5, "neon_red")
        F.append([c])
    for f in F:
        for fr in f:
            _sink(fr, "steel0", "stat0")
    return F


# --- outpost «Вертиго»: adobe and prefab -------------------------------------------------------

ADOBE = ("sand1", "sand2", "sand2", "sand2", "sand2", "sand3")


def _outpost_storey(i: int, feature: str) -> Canvas:
    rng = random.Random(25000 + i)
    c = _wall(25010 + i, 25000, STOREY_H, ADOBE, dither=0.8)
    for x in (1, 14):  # viga beam ends at the same rhythm everywhere
        c.set(x, 2, "leather2")
        c.set(x, 3, "sand1")
    if feature == "windows":
        for x in (3, 10):
            c.rect(x - 1, 6, 5, 9, "sand1")  # deep reveal
            c.rect(x, 7, 3, 7, "win_warm" if rng.random() < 0.6 else "win_dark")
            c.hline(x - 1, x + 3, 15, "leather1")
    elif feature == "prefab":  # a bolted-on prefab module
        c.rect(0, 4, W, 14, "stat2")
        c.hline(0, W - 1, 4, "stat3")
        c.rect(5, 8, 6, 5, "win_cold")
    elif feature == "cloth":
        c.rect(4, 6, 8, 10, "sand1")
        c.rect(5, 7, 6, 9, "tent2")
        c.vline(8, 7, 15, "tent1")
    _slab(c, "sand3", "sand1")
    return c


def _outpost_storeys() -> list[list[Canvas]]:
    return [[_outpost_storey(i, f)] for i, f in enumerate(("windows", "prefab", "cloth", "windows"))]


def _outpost_grounds() -> list[list[Canvas]]:
    F = []
    for i, kind in enumerate(("door", "arch", "awning")):
        c = _wall(25510 + i, 25500, GROUND_H, ADOBE, dither=0.8)
        if kind == "door":
            _door(c, 5, "leather1", light="win_warm", lamp="neon_orange")
        elif kind == "arch":
            c.rect(4, 9, 8, 17, "sand0")
            c.ellipse(8, 10, 4, 3, "sand0")
            c.rect(5, 11, 6, 15, "tent1")
        else:  # a market awning over goods
            c.rect(0, 6, W, 3, "tent3")
            for x in range(0, W, 2):
                c.set(x, 8, "tent1")
            c.rect(2, 14, 12, 10, "sand1")
            for x in range(3, 13, 3):
                c.rect(x, 18, 2, 3, ("spore2", "gold2", "jacket2", "cryst1")[x % 4])
        F.append([c])
    for f in F:
        for fr in f:
            _sink(fr, "sand0", "sand1")
    return F


# --- registration --------------------------------------------------------------------------------

CAPS = {
    "sprawl": ("city4", "city5", "city3", "city1"),
    "docks": ("rust2", "rust3", "rust1", "ink2"),
    "corp": ("chrome2", "chrome3", "chrome1", "glass1"),
    "station": ("stat3", "stat4", "stat2", "steel1"),
    "outpost": ("sand3", "sand4", "sand3", "sand1"),
}
MODULES = {
    "sprawl": (_sprawl_storeys, _sprawl_grounds),
    "docks": (_docks_storeys, _docks_grounds),
    "corp": (_corp_storeys, _corp_grounds),
    "station": (_station_storeys, _station_grounds),
    "outpost": (_outpost_storeys, _outpost_grounds),
}

for _theme, (_coping, _hi, _front, _shadow) in CAPS.items():
    _reg(f"cp.{_theme}.facade.cap@0", _cap(Canvas(W, CAP_H), _coping, _hi, _front, _shadow),
         note=f"{_theme}: parapet crowning a facade column")
    _storeys, _grounds = MODULES[_theme]
    for _i, _fr in enumerate(_storeys()):
        _reg(f"cp.{_theme}.facade.storey@{_i}", *_fr, fps=3 if len(_fr) > 1 else 0,
             note=f"{_theme}: one upper storey of a facade column, street scale")
    for _i, _fr in enumerate(_grounds()):
        _reg(f"cp.{_theme}.facade.ground@{_i}", *_fr, fps=4 if len(_fr) > 1 else 0,
             note=f"{_theme}: street-level floor of a facade column, doors at a person's height")
