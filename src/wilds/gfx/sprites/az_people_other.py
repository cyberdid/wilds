"""Azeroth / Mulgore art: people other. Must satisfy
``wilds.azeroth.manifest.required()["people_other"]`` (see docs/azeroth/mulgore-art-manifest.md).

The other peoples met in Mulgore and Thunder Bluff: goblins (Venture Company),
Forsaken (the Pools of Vision), dwarves (the Bael'dun digsite), orcs, pandaren,
jungle trolls (Darkspear), earthen, blood elves and humans, each in plain
``civilian`` clothes and as a ``merchant`` (the same clothes plus an apron and a
satchel), with idle, walk, talk, hurt and dead.

Everyone faces RIGHT in 3/4 side view with the soles on the last filled row and
the 1px ``ink`` outline under them on the bottom row, so the default bottom-centre
anchor is the ground point. Sizes follow the real scale (1 yard = 8 px): a goblin
is barely 11 px tall, a human 15, an orc 18, a hunched jungle troll 22.

How the art is built
--------------------
Each race has a *rig*: a hand-drawn head (ears, tusks, beard, mohawk - the part
that makes the race readable) and torso written in *slot* characters, plus a
leg spec and an arm spec from which the legs and near/far arms of every pose
are generated. A frame layers far arm, legs, skirt (apron), torso, head, near
arm, then the whole silhouette gets its ink outline (``outline_grid``). Colours
come from the race's skin/hair table and the outfit; the merchant is the
civilian recipe plus an apron and a satchel.

Slot characters::

    q s S   face skin light / mid / shadow    e  eye      m  open mouth
    j h H   hair / beard light / mid / shadow  v  tusk, bone, teeth
    y t T   top light / mid / shadow           i a A  accent (belt, trim, gear)
    x r R   sleeve light / mid / shadow        d D  arm skin / fur light / shadow
    o p P   legs light / mid / far leg         b B  near / far foot
    u U     apron                              c C  satchel
    f F     second fur / cloth light / dark    g    glow (eyes, crystal)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..palette import _ramp
from ..pixelart import TRANSPARENT, Grid, art, blank, grid, outline_grid, overlay, swap
from ..registry import register

# --- colours ---------------------------------------------------------------------------
# goblin: bright yellow-green; forsaken: grey-green dead flesh; jungle troll: sea-blue;
# earthen: warm living stone
_ramp("azo_gob", "#2c4416", "#4f7424", "#7ea634", "#aed24c", "#dcef8a")
_ramp("azo_und", "#2b3230", "#4a5750", "#728577", "#9fb09a", "#c9d4bd")
_ramp("azo_trl", "#172c42", "#244f6c", "#357996", "#58a3b8", "#94d0d0")
_ramp("azo_stn", "#302d33", "#4f4b52", "#736d70", "#9a928c", "#c4bbb0")


# --- parts ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Part:
    """A fill-only piece of a figure: full-width rows placed at row ``y``."""

    rows: Grid
    x: int = 0
    y: int = 0

    def at(self, dx: int = 0, dy: int = 0) -> "Part":
        return Part(self.rows, self.x + dx, self.y + dy)


def part(y: int, text: str, x: int = 0) -> Part:
    return Part(grid(text), x, y)


class Pix:
    """Sparse pixel set that becomes a Part (for generated limbs)."""

    def __init__(self) -> None:
        self.px: dict[tuple[int, int], str] = {}

    def put(self, x: int, y: int, ch: str, over: bool = True) -> None:
        if over or (x, y) not in self.px:
            self.px[(x, y)] = ch

    def part(self, w: int, h: int) -> Part:
        rows = [[TRANSPARENT] * w for _ in range(h)]
        for (x, y), ch in self.px.items():
            if 0 <= x < w and 0 <= y < h:
                rows[y][x] = ch
        return Part(tuple("".join(r) for r in rows))


# --- legs --------------------------------------------------------------------------------


@dataclass(frozen=True)
class LegSpec:
    x: int  # left column of the far leg at the hip
    y: int  # hip row: first row of the legs
    ground: int  # the row the soles stand on
    w: int = 2  # leg width
    gap: int = 0  # columns between the far and the near leg
    foot: int = 1  # toe length in front of the leg
    stride: int = 2  # how far a foot swings at contact
    heel: int = 0  # heel length behind the leg


def _ramp_offsets(k: int, n: int) -> list[int]:
    if n <= 1:
        return [k] * n
    return [round(k * i / (n - 1)) for i in range(n)]


def _leg(pix: Pix, spec: LegSpec, x: int, top: int, offs: list[int], foot_y: int, near: bool) -> None:
    for i, off in enumerate(offs):
        for c in range(spec.w):
            if near:
                ch = "o" if (c == 0 and spec.w > 1) else "p"
            else:
                ch = "P"
            pix.put(x + off + c, top + i, ch)
    fdx = offs[-1] if offs else 0
    for c in range(-spec.heel, spec.w + spec.foot):
        pix.put(x + fdx + c, foot_y, "b" if near else "B")


def legs(spec: LegSpec, pose: str, w: int, h: int) -> Part:
    """Generated legs: stand, w0 (near leg forward), w1 (passing, far foot lifted),
    w2 (far leg forward), w3 (passing, near foot lifted), hurt (stagger)."""
    n = spec.ground - spec.y  # leg rows above the sole row
    fx, nx = spec.x, spec.x + spec.w + spec.gap
    s = spec.stride
    pix = Pix()
    if pose == "stand":
        _leg(pix, spec, fx, spec.y, [0] * n, spec.ground, False)
        _leg(pix, spec, nx, spec.y, [0] * n, spec.ground, True)
    elif pose in ("w0", "w2", "hurt"):
        k = s if pose != "hurt" else max(1, s - 1)
        near_k = k if pose == "w0" else -k
        _leg(pix, spec, fx, spec.y, _ramp_offsets(-near_k, n), spec.ground, False)
        _leg(pix, spec, nx, spec.y, _ramp_offsets(near_k, n), spec.ground, True)
    elif pose in ("w1", "w3"):
        mid = (fx + nx) // 2
        lifted = [0] * (n - 1) + [-1] if n > 1 else [-1]
        straight = [0] * (n + 1)
        if pose == "w1":  # near leg carries, far foot passes
            _leg(pix, spec, mid - 1, spec.y - 1, lifted, spec.ground - 1, False)
            _leg(pix, spec, mid, spec.y - 1, straight, spec.ground, True)
        else:  # far leg carries, near foot passes
            _leg(pix, spec, mid - 1, spec.y - 1, straight, spec.ground, False)
            _leg(pix, spec, mid, spec.y - 1, lifted, spec.ground - 1, True)
    else:
        raise KeyError(pose)
    return pix.part(w, h)


# --- arms --------------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmSpec:
    x: int  # left column of the upper arm at the shoulder
    y: int  # shoulder row
    length: int  # rows from the shoulder to the wrist
    w: int = 2  # arm width
    upper: int = 0  # rows of upper arm (0: half the length)


# template chars: 1 2 upper arm light / dark, 3 4 forearm, 5 6 hand
def _arm_cells(spec: ArmSpec, pose: str) -> list[tuple[int, int, str, str]]:
    """(dx, dy, kind, orient): kind u/f/h, orient v (spans w columns) or h (spans w rows)."""
    a = spec.length
    u = spec.upper or max(1, a // 2)
    f = a - u
    cells = [(0, i, "u", "v") for i in range(u)]
    if pose == "down":
        cells += [(0, i, "f", "v") for i in range(u, a)] + [(0, a, "h", "v")]
    elif pose in ("back", "fwd"):
        k = -1 if pose == "back" else 1
        far = 2 if a >= 6 else 1
        for i in range(u, a):
            step = k * (1 if i - u < (f + 1) // 2 or far == 1 else far)
            cells.append((step, i, "f", "v"))
        cells.append((k * far, a, "h", "v"))
    elif pose == "open":  # elbow bent, forearm forward, palm up: talking
        fl = max(2, f)
        cells.append((0, u, "f", "v"))
        cells += [(spec.w + i, u, "f", "h") for i in range(fl)]
        cells.append((spec.w + fl, u - 1, "h", "h"))
    elif pose == "raise":  # forearm up and forward, hand at chest height: making a point
        fl = max(1, f - 1)
        for i in range(fl):
            cells.append((spec.w + i, u - i, "f", "h"))
        cells.append((spec.w + fl, u - fl, "h", "h"))
    elif pose == "clutch":  # forearm across the belly: hurt
        fl = max(1, f - 1)
        cells.append((0, u, "f", "v"))
        cells += [(spec.w + i - 1, u + 1, "f", "h") for i in range(fl)]
        cells.append((spec.w + fl - 1, u + 1, "h", "h"))
    else:
        raise KeyError(pose)
    return cells


def arm(spec: ArmSpec, pose: str, w: int, h: int, far: bool = False, ink: bool = True) -> Part:
    pix = Pix()
    light = {"u": "1", "f": "3", "h": "5"}
    dark = {"u": "2", "f": "4", "h": "6"}
    for dx, dy, kind, orient in _arm_cells(spec, pose):
        x, y = spec.x + dx, spec.y + dy
        for c in range(spec.w):
            ch = dark[kind] if (far or c > 0) else light[kind]
            if orient == "v":
                pix.put(x + c, y, ch)
            else:
                pix.put(x, y + c, ch)
        if ink and not far and orient == "v" and kind != "h":
            pix.put(x - 1, y, "k", over=False)
    return pix.part(w, h)


def arm_chars(sleeve: str) -> dict[str, str]:
    """Template chars -> slot chars for a sleeve length: long, short or bare."""
    if sleeve == "long":
        return {"1": "x", "2": "r", "3": "r", "4": "R", "5": "d", "6": "D"}
    if sleeve == "short":
        return {"1": "x", "2": "r", "3": "d", "4": "D", "5": "d", "6": "D"}
    return {"1": "d", "2": "D", "3": "d", "4": "D", "5": "d", "6": "D"}


# --- rigs and figures -----------------------------------------------------------------------


@dataclass(frozen=True)
class Rig:
    race: str
    size: tuple[int, int]
    head: Part
    torso: Part
    legs: LegSpec
    arm: ArmSpec
    eye: tuple[int, int]
    mouth: tuple[int, int]
    apron: Part
    satchel: Part  # drawn behind the near arm: bag on the hip plus the strap
    closed_eye: str = "S"
    sleeve: str = "short"
    wear: tuple[Part, ...] = ()  # drawn over the torso (necklaces, trims, badges)
    civ_gear: tuple[Part, ...] = ()  # drawn over the head of the civilian (hats)
    mer_gear: tuple[Part, ...] = ()  # drawn over the head of the merchant
    glow: tuple[Part, ...] = ()  # drawn after the outline (glowing eyes)


def compose(size: tuple[int, int], parts: list[Part], post: list[Part] = (), outline: bool = True) -> Grid:
    out = blank(*size)
    for p in parts:
        out = overlay(out, p.rows, p.x, p.y)
    if outline:
        out = outline_grid(out, "k")
    for p in post:
        out = overlay(out, p.rows, p.x, p.y)
    return out


def figure(rig: Rig, merchant: bool, legs_pose: str = "stand", arm_pose: str = "down", *,
           far_pose: str = "", dy: int = 0, dx: int = 0, head: tuple[int, int] = (0, 0),
           mouth: bool = False, shut: bool = False, outline: bool = True) -> Grid:
    w, h = rig.size
    amap = arm_chars(rig.sleeve)
    parts: list[Part] = []
    if far_pose:
        fdx = 2 if far_pose == "fwd" else -2
        parts.append(Part(swap(arm(rig.arm, far_pose, w, h, far=True).rows, amap)).at(dx + fdx, dy))
    parts.append(legs(rig.legs, legs_pose, w, h))
    parts.append(rig.torso.at(dx, dy))
    parts += [p.at(dx, dy) for p in rig.wear]
    if merchant:
        parts += [rig.apron.at(dx, dy), rig.satchel.at(dx, dy)]
    hx, hy = head
    parts.append(rig.head.at(dx + hx, dy + hy))
    parts += [p.at(dx + hx, dy + hy) for p in (rig.mer_gear if merchant else rig.civ_gear)]
    if mouth:
        parts.append(Part(("m",), rig.mouth[0] + dx + hx, rig.mouth[1] + dy + hy))
    parts.append(Part(swap(arm(rig.arm, arm_pose, w, h).rows, amap)).at(dx, dy))
    post = [] if shut else [p.at(dx + hx, dy + hy) for p in rig.glow]
    g = compose(rig.size, parts, post, outline)
    if shut:
        ex, ey = rig.eye[0] + dx + hx, rig.eye[1] + dy + hy
        g = overlay(g, (rig.closed_eye,), ex, ey)
    return g


def fallen(size: tuple[int, int], text: str) -> Grid:
    """A hand-drawn body fallen on its side (head to the right, where it fell), rows padded
    to the canvas width and set on the ground row, then outlined."""
    w, h = size
    rows = [r.strip() for r in text.strip().splitlines()]
    body = tuple(r + TRANSPARENT * (w - len(r)) for r in rows)
    return outline_grid(overlay(blank(w, h), body, 0, h - 1 - len(body)), "k")


@dataclass(frozen=True)
class Race:
    rig: Rig
    skin: dict[str, str]  # q s S d D (+ anything race-bound: eyes, tusks, fur)
    civilian: dict[str, str]
    merchant: dict[str, str] = field(default_factory=dict)  # changes to the civilian colours
    note: str = ""


BASE = {"e": "ink2", "m": "red1", "v": "tusk"}
# merchant: undyed linen apron, a leather satchel on the back hip
MERCHANT = {"u": "bone3", "U": "bone2", "c": "tent1", "C": "tent0"}

IDLE_FPS, WALK_FPS, TALK_FPS = 2, 8, 3


def register_race(body: str, race: Race) -> None:
    rig = race.rig
    for outfit in ("civilian", "merchant"):
        merchant = outfit == "merchant"
        leg = {**BASE, **race.civilian, **(MERCHANT if merchant else {}),
               **(race.merchant if merchant else {}), **race.skin}
        what = f"{race.note}, {'merchant: apron and satchel' if merchant else 'plain clothes'}"
        f = lambda *a, **k: figure(rig, merchant, *a, **k)  # noqa: E731
        idle = [f(), f(dy=1)]
        walk = [f("w0", "back", far_pose="fwd"), f("w1", "down", dy=-1),
                f("w2", "fwd", far_pose="back"), f("w3", "down", dy=-1)]
        talk = [f(arm_pose="open", mouth=True), f(arm_pose="raise")]
        name = f"az.person.{body}.{outfit}"
        register(f"{name}.idle", art(*idle, legend=leg, fps=IDLE_FPS, note=f"{what}, breathing"))
        register(f"{name}.walk", art(*walk, legend=leg, fps=WALK_FPS, note=f"{what}, walking"))
        register(f"{name}.talk", art(*talk, legend=leg, fps=TALK_FPS,
                                     note=f"{what}, gesturing mid-conversation"))
    leg = {**BASE, **race.civilian, **race.skin}
    hurt = figure(rig, False, "hurt", "clutch", dx=-1, dy=1, head=(-1, 0), mouth=True, shut=True)
    register(f"az.person.{body}.hurt", art(hurt, legend=leg, note=f"{race.note}, recoiling from a blow"))
    register(f"az.person.{body}.dead", art(fallen(rig.size, DEAD[body]), legend=leg,
                                           note=f"{race.note}, fallen on its side"))


# Fallen bodies, hand-drawn: each lies on its side where it fell, head to the right
# (the way it was facing), back up, face turned to the viewer, the near arm flung
# out on the ground and the near knee bent. Race marks stay readable: the goblin's
# ear, the troll's mohawk and tusks, the dwarf's beard, the pandaren's black limbs.
DEAD = {
    "human": """
        ...........jhh
        ......yyyyjhhhh
        ..PPPPyyytSshhh
        .BpppoattTSqSqh
        .bb...TTddddsSq
        """,
    "blood_elf": """
        ..........q
        ......yyyyqjhh
        ..PPPPyyyyjhhhh
        .BpppoiyyTSqSqh
        .bb...TTdddsSqh
        """,
    "forsaken": """
        ...........hhh
        ......yyyThhhhh
        ..P.PPyyytSshhh
        .bp.ppaytTSqSSh
        ..b..tT.ddSvvS
        """,
    "dwarf": """
        ..........jhhh
        .....yyyyyjhhhh
        ..PPPyyyyySshhh
        .BppoatttTSqSnh
        .bb...TTddjjhhn
        """,
    "goblin": """
        ..........qq
        ...........qs
        ......yyt.sqAg
        ..PPPyyyTsqqqq
        .BppoaiaTSqSqss
        .bb...dd..SvvSs
        """,
    "orc": """
        ...........jh
        ......yyyyshhh
        ..PPPPyyyySqhhs
        .BppppaiaTSqSqs
        .bboop.TTTSsvsv
        ...bb..dddddSS
        """,
    "pandaren": """
        ...........fF
        ......Fyyyqqqqf
        ..PPPPFyyyqqqqq
        .BppppaiaFsqFqq
        .bboop.yyFSqqqF
        ...bb..DdddSsS
        """,
    "troll": """
        ............hh
        ...........jhhh
        .....yyyytqhhh
        .PPPPyyyyySqqq
        BppppaiaaTSqSqqv
        bb.oop.yyTSsssv
        ...bb.dddd.SS
        """,
    "earthen": """
        ...........sqq
        .....yyyyysqqqq
        ..PPPyyyyyySqqq
        .BppoaaiaaTSqeq
        .bb..TTTdddhjjq
        ........DdhhhH
        """,
}

# --- human (16x16): a Stormwind peasant, tan skin, brown hair ------------------------------

HUMAN = Rig(
    "human", (16, 16),
    head=part(1, """
        ......jhhh......
        .....jhhhhhq....
        .....hhhqqqq....
        .....hhsSqeqs...
        ......hSsssS....
        """),
    torso=part(6, """
        ......yyttt.....
        .....yyyttT.....
        .....aaaiaA.....
        .....yyttTT.....
        """),
    legs=LegSpec(x=6, y=10, ground=14),
    arm=ArmSpec(x=8, y=6, length=4),
    eye=(10, 4), mouth=(11, 5),
    apron=part(7, """
        .........uU.....
        .........uuU....
        ........uuuU....
        ........uuuU....
        ........uuU.....
        """),
    satchel=part(6, """
        .........C......
        ........C.......
        ....cCC.........
        ....cCC.........
        """),
)

register_race("human", Race(
    HUMAN,
    skin={"q": "skin3", "s": "skin2", "S": "skin1", "d": "skin2", "D": "skin1",
          "j": "rust2", "h": "hair_brown", "H": "skin0"},
    civilian={"y": "sand3", "t": "sand2", "T": "sand1", "x": "sand3", "r": "sand2", "R": "sand1",
              "i": "gold1", "a": "leather3", "A": "leather2",
              "o": "denim3", "p": "denim2", "P": "denim1", "b": "leather2", "B": "leather1"},
    merchant={"y": "water3", "t": "water2", "T": "water1", "x": "water3", "r": "water2", "R": "water1"},
    note="human",
))




# --- goblin (16x16): barely a yard tall, lime skin, huge ears and nose, Venture Co. red ------

GOBLIN = Rig(
    "goblin", (16, 16),
    head=part(4, """
        ......sqqqs.....
        .qq..AaaaggA....
        ..qqsqqqqeqqs...
        ...sSssqqqqsss..
        .....SsSvvvS....
        """),
    torso=part(9, """
        ......yyyt......
        .....yyyttT.....
        .....aaiaaA.....
        """),
    legs=LegSpec(x=6, y=12, ground=14, w=1, gap=1, foot=2, stride=1),
    arm=ArmSpec(x=8, y=9, length=3, w=1),
    eye=(9, 6), mouth=(10, 8),
    apron=part(10, """
        .........uU.....
        ........uuU.....
        ........uuU.....
        """),
    satchel=part(8, """
        ...W.W..........
        ....W....C......
        ....cC..........
        ....CC..........
        """),
    # Venture Co. badge on the jacket; the worker's hard hat with its lamp
    wear=(Part(("i",), 10, 10),),
    civ_gear=(part(2, """
        ......zzZ.......
        .....zzzzZl.....
        ....ZZZZZZZZ....
        """),),
)

register_race("goblin", Race(
    GOBLIN,
    skin={"q": "azo_gob3", "s": "azo_gob2", "S": "azo_gob1", "d": "azo_gob2", "D": "azo_gob1",
          "v": "bone4", "g": "glass4", "z": "hazard", "Z": "hazard_dark", "l": "win_warm",
          "W": "grey3"},
    civilian={"y": "red3", "t": "red2", "T": "red1", "x": "red3", "r": "red2", "R": "red1",
              "i": "gold2", "a": "leather3", "A": "leather2",
              "o": "tent1", "p": "tent1", "P": "tent0", "b": "leather2", "B": "leather1"},
    note="goblin of the Venture Co.: hard hat and lamp, or goggles and a wrench in the satchel",
))


# --- forsaken (16x16): hunched undead, grey-green flesh, glowing eyes, bare jaw, rags --------

FORSAKEN = Rig(
    "forsaken", (16, 16),
    head=part(2, """
        .......hhhh.....
        ......hhhhqqs...
        ......hhsSqeS...
        ......h.SsqqSs..
        ........SvvvS...
        """),
    torso=part(7, """
        ......yyyt......
        .....yyyttT.....
        .....aaiaaA.....
        ....tyT.ytT.....
        """),
    legs=LegSpec(x=6, y=11, ground=14, w=1, gap=1, foot=1, stride=1),
    arm=ArmSpec(x=8, y=7, length=4, w=1),
    eye=(11, 4), mouth=(11, 6),
    apron=part(8, """
        .........uU.....
        ........uuU.....
        ........uuU.....
        ........uU......
        """),
    satchel=part(7, """
        .........C......
        ........C.......
        ....cCC.........
        ....cCC.........
        """),
    glow=(Part(("g",), 11, 4),),
)

register_race("forsaken", Race(
    FORSAKEN,
    skin={"q": "azo_und3", "s": "azo_und2", "S": "azo_und1", "d": "azo_und3", "D": "azo_und2",
          "j": "grey2", "h": "grey1", "H": "ink2", "v": "bone3", "e": "ink2", "g": "fire4",
          "b": "azo_und2", "B": "azo_und1"},
    civilian={"y": "flora3", "t": "flora2", "T": "flora1", "x": "flora3", "r": "flora2", "R": "flora1",
              "i": "bone3", "a": "bone2", "A": "bone1", "o": "grey2", "p": "grey2", "P": "grey1"},
    note="Forsaken, ragged Undercity purple",
))


# --- dwarf (16x16): four and a half feet of beard, ginger-brown, blue tunic -----------------

DWARF = Rig(
    "dwarf", (16, 16),
    head=part(3, """
        ......jhhh......
        .....jhhhhqqs...
        .....hhsSqeqnn..
        .....hhSjjjnnS..
        ......hjjhhhh...
        ........jhhhH...
        .........hhH....
        """),
    torso=part(7, """
        .....yyyttt.....
        ....yyyytttT....
        ....yyyytttT....
        ....aaaaiaaA....
        ....yyyttttT....
        """),
    legs=LegSpec(x=5, y=12, ground=14, w=2, gap=1, foot=1, stride=1),
    arm=ArmSpec(x=6, y=7, length=3, w=2),
    eye=(10, 5), mouth=(11, 7),
    apron=part(10, """
        ........uuuU....
        .......uuuuU....
        .......uuuU.....
        """),
    satchel=part(7, """
        .........C......
        ........C.......
        ...cCC..........
        ...cCC..........
        """),
)

register_race("dwarf", Race(
    DWARF,
    skin={"q": "skin4", "s": "skin3", "S": "skin2", "d": "skin3", "D": "skin2", "n": "blush",
          "j": "hair_copper", "h": "hair_red", "H": "rust1"},
    civilian={"y": "denim3", "t": "denim2", "T": "denim1", "x": "denim3", "r": "denim2", "R": "denim1",
              "i": "gold2", "a": "leather3", "A": "leather2",
              "o": "sand2", "p": "sand2", "P": "sand1", "b": "leather2", "B": "leather1"},
    note="Ironforge dwarf, braided beard",
))


# --- orc (16x20): broad green shoulders, jutting jaw and tusks, black topknot, hide vest -------

ORC = Rig(
    "orc", (16, 20),
    head=part(1, """
        ......jhh.......
        .....hhhqqqqs...
        ....hhsqSSeSqq..
        ....HhSsqqqqqvs.
        ......SSssssSvS.
        .......SSSSSSS..
        """),
    torso=part(6, """
        ...yyyyyt.......
        ..yyyyyytttT....
        ..yyyyyttttT....
        ..tyyyyttttT....
        ...ttttttTTT....
        ...AaaaaiaaA....
        """),
    legs=LegSpec(x=4, y=12, ground=18, w=3, gap=0, foot=1, stride=2),
    arm=ArmSpec(x=5, y=7, length=5, w=2),
    eye=(10, 3), mouth=(12, 5),
    sleeve="bare",
    apron=part(8, """
        ........uuU.....
        ........uuuU....
        ........uuuU....
        .......uuuuU....
        .......uuuuU....
        ........uuU.....
        """),
    satchel=part(7, """
        .........C......
        ........C.......
        ................
        .cCC............
        .cCC............
        """),
)

register_race("orc", Race(
    ORC,
    skin={"q": "ork4", "s": "ork3", "S": "ork2", "d": "ork3", "D": "ork2",
          "j": "grey1", "h": "hair_black", "H": "ink2"},
    civilian={"y": "tent1", "t": "dust2", "T": "dust1", "i": "gold1", "a": "red2", "A": "red1",
              "o": "grey2", "p": "grey1", "P": "grey0", "b": "leather2", "B": "leather1"},
    note="orc, hide vest and a Horde-red sash",
))


# --- pandaren (16x20): round black-and-white panda, green vest, red sash ----------------------

PANDAREN = Rig(
    "pandaren", (16, 20),
    head=part(1, """
        .....FF..Ff.....
        .....sqqqqq.....
        ....sqqqqqqqq...
        ...sqqqqqFFqq...
        ...ssqqqqFeqqqF.
        ...Sssqqqsqqqs..
        ....SSsssssS....
        """),
    torso=part(8, """
        ....FFFyyt......
        ...FFfyyyttqq...
        ...FfyyyyttqsS..
        ...FAaaaiaaAsS..
        ....ttttTTSSS...
        """),
    legs=LegSpec(x=5, y=13, ground=18, w=2, gap=1, foot=1, stride=2),
    arm=ArmSpec(x=5, y=8, length=5, w=2),
    eye=(10, 5), mouth=(12, 6),
    sleeve="bare",
    apron=part(10, """
        ..........uU....
        .........uuuU...
        .........uuuU...
        .........uuuU...
        .........uuU....
        """),
    satchel=part(8, """
        ..........C.....
        .........C......
        ..cCC...........
        ..cCC...........
        """),
    closed_eye="F",
)

register_race("pandaren", Race(
    PANDAREN,
    skin={"q": "white", "s": "bone3", "S": "bone2", "f": "grey1", "F": "ink2", "e": "white",
          "d": "grey1", "D": "ink2", "b": "grey1", "B": "ink2"},
    civilian={"y": "moss4", "t": "moss3", "T": "moss2", "i": "red4", "a": "red3", "A": "red2",
              "o": "sand3", "p": "sand2", "P": "sand1"},
    note="pandaren, green vest and red sash",
))


# --- jungle troll (16x24): tall and hunched, sea-blue skin, red mohawk, curling tusks ----------

TROLL = Rig(
    "troll", (16, 24),
    head=part(1, """
        ....hh..........
        ....jhhh........
        .....jhhhh......
        .q....jhhhqq....
        ..qs...hSqqeq...
        ...sSssSqqqqqSv.
        .......Ssssqsv..
        ........SsSSs...
        """),
    torso=part(8, """
        ....yyyyt.......
        ...yyyyyytt.....
        ...yyyyyyttT....
        ....yyyyyttT....
        ....yyyyyttT....
        ....aaaaiaaA....
        .....ytttttT....
        ......yttT......
        """),
    legs=LegSpec(x=6, y=15, ground=22, w=2, gap=1, foot=1, stride=2),
    arm=ArmSpec(x=5, y=9, length=7, w=2, upper=2),
    eye=(11, 5), mouth=(12, 7),
    wear=(part(9, """
        ........v.v.....
        .........v......
        """),),
    apron=part(10, """
        .........uU.....
        .........uuU....
        ........uuuU....
        ........uuuU....
        ........uuuU....
        ........uuU.....
        """),
    satchel=part(9, """
        .........C......
        ........C.......
        ................
        .cCC............
        .cCC............
        """),
)

register_race("troll", Race(
    TROLL,
    skin={"q": "azo_trl3", "s": "azo_trl2", "S": "azo_trl1", "d": "azo_trl3", "D": "azo_trl2",
          "j": "hair_copper", "h": "hair_red", "H": "rust1",
          "o": "azo_trl3", "p": "azo_trl3", "P": "azo_trl1", "b": "azo_trl2", "B": "azo_trl1"},
    civilian={"y": "dust4", "t": "dust3", "T": "dust2", "x": "leather3", "r": "leather2", "R": "leather1",
              "i": "bone4", "a": "leather3", "A": "leather2"},
    note="Darkspear jungle troll, tooth necklace and hide kilt",
))


# --- earthen (16x20): a dwarf of living stone, slate beard, glowing eyes, bronze tunic ---------

EARTHEN = Rig(
    "earthen", (16, 20),
    head=part(3, """
        ......sqqqs.....
        .....sqqSqqqs...
        .....SsSqqeqq...
        .....SsSsqSqqq..
        ......Shjjjhhj..
        .......hjhhhhH..
        ........hhhhH...
        .........hHH....
        """),
    torso=part(8, """
        .....yyyyt......
        ....yyyyyttT....
        ...yyyyyytttT...
        ...tyyyyttttT...
        ...AaaaaiaaaA...
        ....ttttTTTT....
        """),
    legs=LegSpec(x=5, y=14, ground=18, w=2, gap=1, foot=1, stride=1),
    arm=ArmSpec(x=5, y=9, length=4, w=2),
    eye=(10, 5), mouth=(12, 6),
    wear=(part(7, """
        ....gG..........
        ...gGG..........
        """),),
    apron=part(11, """
        .........uuU....
        ........uuuuU...
        ........uuuuU...
        .........uuU....
        """),
    satchel=part(9, """
        .........C......
        ........C.......
        ..cCC...........
        ..cCC...........
        """),
    glow=(Part(("e",), 10, 5),),
)

register_race("earthen", Race(
    EARTHEN,
    skin={"q": "azo_stn4", "s": "azo_stn3", "S": "azo_stn2", "d": "azo_stn3", "D": "azo_stn2",
          "j": "rock3", "h": "rock2", "H": "rock1", "e": "glowcyan", "g": "cryst2", "G": "cryst1"},
    civilian={"y": "rust4", "t": "rust3", "T": "rust2", "x": "rust4", "r": "rust3", "R": "rust2",
              "i": "gold2", "a": "gold1", "A": "gold0",
              "o": "grey3", "p": "grey2", "P": "grey1", "b": "leather2", "B": "leather1"},
    note="earthen of living stone, crystal growing from the shoulder",
))


# --- blood elf (16x16): slender, long swept ears, golden hair, fel-green eyes, Silvermoon red ---

BLOOD_ELF = Rig(
    "blood_elf", (16, 16),
    head=part(1, """
        ......jhhh......
        ..q..jhhhhhq....
        ...qsshhqqqq....
        .....hSShqeqs...
        .....hhSsssS....
        .....hH.........
        """),
    torso=part(6, """
        ......yytt......
        .....yyyttT.....
        .....iaaaiA.....
        .....yyyttT.....
        .....yytttT.....
        """),
    legs=LegSpec(x=6, y=11, ground=14),
    arm=ArmSpec(x=8, y=6, length=4, w=2),
    eye=(10, 4), mouth=(11, 5),
    apron=part(7, """
        .........uU.....
        .........uuU....
        ........uuuU....
        ........uuuU....
        ........uuU.....
        """),
    satchel=part(6, """
        .........C......
        ........C.......
        ....cCC.........
        ....cCC.........
        """),
    glow=(Part(("g",), 10, 4),),
)

register_race("blood_elf", Race(
    BLOOD_ELF,
    skin={"q": "skin4", "s": "skin3", "S": "skin2", "d": "skin3", "D": "skin2",
          "j": "sand4", "h": "hair_blond", "H": "gold1", "g": "glowlime"},
    civilian={"y": "red2", "t": "red1", "T": "red0", "x": "red2", "r": "red1", "R": "red0",
              "i": "gold2", "a": "gold1", "A": "gold0",
              "o": "red1", "p": "red1", "P": "red0", "b": "leather2", "B": "leather1"},
    note="blood elf, Silvermoon crimson and gold",
))
