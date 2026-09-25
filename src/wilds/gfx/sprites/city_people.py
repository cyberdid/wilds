"""City people: the runner (five metatypes, plain and augmented) and every NPC
role x metatype of the cyberpunk chapter.

Everyone faces RIGHT in the same 3/4 side view as the Tau-7 survivor (the
renderer mirrors for left and adds the drop shadow) and stands with the soles
on the bottom row, so the default bottom-centre anchor is the ground point.

How the art is built
--------------------
Each metatype has a *rig*: hand-drawn, fill-only body parts (legs per pose,
torso, bald head, hairstyles, near-arm poses, role pieces such as coats, caps
or visors) written in *slot* characters instead of colours.  A figure is a
list of parts layered in order; the 1px ``ink`` outline is added after
composing (``outline_grid``), so any piece that changes the silhouette - a
coat tail, a mohawk, a raised baton - gets a clean outline for free.  A role
is a recipe (which parts in which frame) plus a slot -> palette mapping; the
skin tone and hair colour come from a per role x race cast table, so a street
is not a row of clones while each role keeps its uniform.

Slot characters (every rig uses the same ones)::

    q s S   skin      light / mid / shadow        e  eye (glows when augmented)
    j h H   hair      light / mid / shadow        m  open mouth
    y t T   top       light / mid / shadow        v  tusk
    x r R   sleeve    light / mid / shadow        n N  horn light / dark
    d D     hand      mid / shadow (skin, glove or chrome)
    o p P   trousers  light / mid / shadow        b B  boots mid / shadow
    i a A   accent    light / mid / shadow        u U  second garment mid / shadow
    g G     glow      bright / dim                c C  metal light / dark
    k K w   ink, ink2, white (always available)

Animations: ``idle`` 8 frames @4 fps (breathing at the reference 2 fps with a
blink - or a glint / visor sweep - once per loop), ``talk`` 4 frames @4 fps
(the mouth moves every frame, the gesture every other), hero ``walk`` 4
frames @8 fps with a 1px bob, ``hurt`` 1 frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..pixelart import Grid, art, blank, grid, outline_grid, overlay, swap
from ..registry import register

RACE_NAMES = ("human", "elf", "dwarf", "ork", "troll")
ROLE_NAMES = ("fixer", "vendor", "doc", "ganger", "civilian", "collector")


# --- parts and composition ---------------------------------------------------------


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


def dot(x: int, y: int, ch: str) -> Part:
    return Part((ch,), x, y)


def compose(size: tuple[int, int], parts, post=()) -> Grid:
    """Layer parts in order, outline the silhouette, then add unoutlined glows."""
    out = blank(*size)
    for p in parts:
        out = overlay(out, p.rows, p.x, p.y)
    out = outline_grid(out, "k")
    for p in post:
        out = overlay(out, p.rows, p.x, p.y)
    return out


class Rig:
    """One metatype's body parts plus where its eye and mouth are (stand pose)."""

    def __init__(self, race: str, size: tuple[int, int], eye: tuple[int, int],
                 mouth: tuple[int, int], parts: dict[str, Part]) -> None:
        self.race, self.size, self.eye, self.mouth, self.parts = race, size, eye, mouth, parts

    def __getitem__(self, name: str) -> Part:
        try:
            return self.parts[name]
        except KeyError:
            raise KeyError(f"{self.race} rig has no part {name!r}") from None


@dataclass(frozen=True)
class Look:
    """What a figure wears, by layer. ``skirt`` hangs from the hips and does not
    breathe (coat tails, aprons); ``wear`` sits on the torso; ``gear`` on the head."""

    hair: str = ""
    skirt: tuple[str, ...] = ()
    wear: tuple[str, ...] = ()
    gear: tuple[str, ...] = ()


def figure(rig: Rig, look: Look, legs: str = "legs.stand", arm: str = "arm.down", *,
           far: str = "", dx: int = 0, dy: int = 0, head: tuple[int, int] = (0, 0),
           mouth: bool = False, blink: bool = False, extra: tuple[str, ...] = (),
           gear: tuple[str, ...] | None = None, post: tuple[Part, ...] = ()) -> Grid:
    """One frame: legs and skirt stay put, everything above moves by (dx, dy)
    (breathing, walk bob, recoil) and the head group by a further ``head``."""
    hx, hy = head
    lower = [rig[legs]] + [rig[n] for n in look.skirt]
    body = [rig["torso"]] + [rig[n] for n in look.wear]
    heads = [rig["head"]] + ([rig[look.hair]] if look.hair else [])
    heads += [rig[n] for n in (look.gear if gear is None else gear)]
    if mouth:
        heads.append(dot(*rig.mouth, "m"))
    top = [rig[arm]] + [rig[n] for n in extra]
    parts = [rig[far].at(dx, dy)] if far else []
    parts += lower + [p.at(dx, dy) for p in body]
    parts += [p.at(dx + hx, dy + hy) for p in heads] + [p.at(dx, dy) for p in top]
    g = compose(rig.size, parts, [p.at(dx, dy) for p in post])
    return swap(g, {"e": "S"}) if blink else g


# --- colours ------------------------------------------------------------------------

SKIN = {  # light, mid, shadow
    "fair": ("skin4", "skin3", "skin2"),
    "tan": ("skin3", "skin2", "skin1"),
    "brown": ("skin2", "skin1", "skin0"),
    "pale": ("elf3", "elf2", "elf1"),
    "rose": ("skin4", "elf2", "elf1"),
    "ork": ("ork4", "ork3", "ork2"),
    "ork_dark": ("ork3", "ork2", "ork1"),
    "troll": ("troll4", "troll3", "troll2"),
    "troll_dark": ("troll3", "troll2", "troll1"),
}
HAIR = {  # light, mid, shadow
    "black": ("grey1", "ink2", "hair_black"),
    "brown": ("rust2", "hair_brown", "skin0"),
    "blond": ("sand4", "hair_blond", "gold1"),
    "red": ("hair_copper", "hair_red", "rust1"),
    "copper": ("tent3", "hair_copper", "hair_red"),
    "white": ("white", "hair_white", "grey3"),
    "grey": ("grey4", "grey3", "grey2"),
    "blue": ("glass4", "hair_blue", "denim2"),
    "green": ("moss5", "hair_green", "neon_green_dim"),
    "pink": ("spore4", "hair_pink", "spore2"),
    "mohawk": ("spore4", "hair_pink", "neon_pink_dim"),
}

BASE = {"e": "ink2", "m": "red1", "v": "tusk", "n": "bone3", "N": "bone1",
        "g": "neon_cyan", "G": "neon_cyan_dim", "c": "chrome2", "C": "chrome0"}


def legend(outfit: dict[str, str], skin: str, hair: str, hands: str = "skin") -> dict[str, str]:
    q, s, S = SKIN[skin]
    j, h, H = HAIR[hair]
    out = {**BASE, "q": q, "s": s, "S": S, "j": j, "h": h, "H": H}
    if hands == "skin":
        out.update(d=s, D=S)
    out.update(outfit)
    return out


# the runner: yellow jacket (the yellow @), dark jeans, the orange scarf cut from
# the Tau-7 survival suit
HERO_OUTFIT = {
    "y": "jacket3", "t": "jacket2", "T": "jacket1",
    "x": "jacket3", "r": "jacket2", "R": "jacket1",
    "o": "denim2", "p": "denim1", "P": "denim0",
    "b": "leather3", "B": "leather1",
    "i": "suit4", "a": "suit3", "A": "suit1",
    "u": "grey1", "U": "grey0",
}
# cyberware: the near arm is chrome from the shoulder (the sleeve torn off), one eye glows
AUG = {"x": "chrome3", "r": "chrome1", "R": "chrome0", "d": "chrome2", "D": "chrome1",
       "e": "neon_cyan"}

OUTFITS = {
    # long indigo coat, popped collar lined in cyan, shades with a neon glint, commlink
    "fixer": {"y": "city5", "t": "city4", "T": "city3", "x": "city5", "r": "city4", "R": "city3",
              "o": "grey1", "p": "grey0", "P": "ink2", "b": "grey1", "B": "grey0",
              "i": "neon_cyan", "a": "neon_cyan_dim", "A": "city2", "u": "grey2", "U": "grey1",
              "g": "neon_cyan", "G": "neon_cyan_dim", "c": "chrome1", "C": "grey0"},
    # blue work shirt, olive apron, green cap, neon-green cred reader
    "vendor": {"y": "denim3", "t": "denim2", "T": "denim1", "x": "denim3", "r": "denim2", "R": "denim1",
               "o": "leather3", "p": "leather2", "P": "leather1", "b": "rust2", "B": "rust1",
               "i": "moss5", "a": "moss4", "A": "moss3", "u": "olive3", "U": "olive2",
               "g": "neon_green", "G": "neon_green_dim", "c": "grey2", "C": "grey1"},
    # white coat over teal scrubs, red cross, blue gloves, goggles, glowing syringe
    "doc": {"y": "white", "t": "grey4", "T": "grey3", "x": "white", "r": "grey4", "R": "grey3",
            "d": "water4", "D": "water3",
            "o": "grey2", "p": "grey1", "P": "grey0", "b": "grey1", "B": "grey0",
            "i": "red4", "a": "red3", "A": "red2", "u": "cryst1", "U": "cryst0",
            "g": "glowcyan", "G": "cryst1", "c": "chrome2", "C": "chrome0"},
    # sleeveless black-leather vest with chrome spikes, tattooed arms, ripped jeans
    "ganger": {"y": "leather3", "t": "leather2", "T": "leather1",
               "o": "denim2", "p": "denim1", "P": "denim0", "b": "grey1", "B": "grey0",
               "i": "neon_pink", "a": "neon_pink_dim", "A": "ink2", "u": "grey2", "U": "grey1",
               "g": "neon_pink", "G": "neon_pink_dim", "c": "chrome3", "C": "chrome1"},
    # plain hoodie in a muted colour, jeans, sneakers, hands in the pouch
    "civilian": {"y": "grey3", "t": "grey2", "T": "grey1", "x": "grey3", "r": "grey2", "R": "grey1",
                 "o": "denim2", "p": "denim1", "P": "denim0", "b": "bone3", "B": "bone2",
                 "i": "grey3", "a": "grey2", "A": "grey1", "u": "grey1", "U": "grey0",
                 "g": "neon_cyan", "G": "neon_cyan_dim", "c": "grey3", "C": "grey1"},
    # black suit, white shirt, dark tie, black gloves, glowing red visor, stun baton
    "collector": {"y": "grey2", "t": "grey1", "T": "grey0", "x": "grey2", "r": "grey1", "R": "grey0",
                  "d": "grey1", "D": "grey0",
                  "o": "grey1", "p": "grey0", "P": "ink2", "b": "grey1", "B": "ink2",
                  "i": "red3", "a": "red2", "A": "red1", "u": "grey4", "U": "grey3",
                  "g": "neon_red", "G": "neon_red_dim", "W": "fire5", "c": "chrome2", "C": "chrome0"},
}


@dataclass(frozen=True)
class Role:
    look: Look
    idle_arm: str
    talk_arms: tuple[str, str]
    hands: str = "skin"  # skin | glove (the outfit colours the hands)
    blink: bool = True  # False when the eyes are hidden (shades, visor)
    extra: tuple[str, ...] = ()  # drawn over the arm (a sleeve cross, a tattoo)
    # gear part -> replacement per frame index (a glint, a visor sweep)
    cycle: dict[str, tuple[str, ...]] = field(default_factory=dict)


_GLINT = ("fixer.shades",) * 7 + ("fixer.shades2",)
_SWEEP = ("collector.visor", "collector.visor1", "collector.visor2", "collector.visor1") * 2

ROLES = {
    "fixer": Role(Look("hair.slick", ("fixer.coat",), (), ("fixer.collar", "fixer.shades")),
                  "fixer.hold", ("fixer.show", "fixer.show2"), blink=False,
                  cycle={"fixer.shades": _GLINT}),
    "vendor": Role(Look("hair.short", ("vendor.apron",), ("vendor.bib",), ("vendor.cap",)),
                   "vendor.rest", ("arm.open", "vendor.reader")),
    "doc": Role(Look("hair.short", ("doc.coat",), ("doc.scrubs",), ("doc.goggles",)),
                "doc.gloves_up", ("doc.syringe", "doc.syringe2"), hands="glove",
                extra=("doc.cross",)),
    "ganger": Role(Look("", (), ("ganger.spikes",), ("ganger.mohawk",)),
                   "arm.down", ("ganger.point", "ganger.pump"), extra=("ganger.tattoo",)),
    "civilian": Role(Look("", (), (), ("civilian.hood",)),
                     "civilian.pocket", ("civilian.shrug", "arm.open")),
    "collector": Role(Look("hair.crop", (), ("collector.shirt",), ("collector.visor",)),
                      "collector.baton", ("collector.raise", "collector.tap"), hands="glove",
                      blink=False, cycle={"collector.visor": _SWEEP}),
}

# idle: breathe in, in, out, out (x2) = the reference 2 fps; the last frame blinks
IDLE_DY = (0, 0, 1, 1, 0, 0, 1, 1)


def _gear(look: Look, role: Role, i: int) -> tuple[str, ...]:
    return tuple(role.cycle[n][i % len(role.cycle[n])] if n in role.cycle else n for n in look.gear)


def npc_frames(rig: Rig, role: Role, look: Look) -> tuple[list[Grid], list[Grid]]:
    idle = [figure(rig, look, arm=role.idle_arm, dy=dy, blink=role.blink and i == 7,
                   gear=_gear(look, role, i), extra=role.extra)
            for i, dy in enumerate(IDLE_DY)]
    talk = [figure(rig, look, arm=role.talk_arms[i // 2], mouth=i % 2 == 0,
                   gear=_gear(look, role, i), extra=role.extra)
            for i in range(4)]
    return idle, talk


HERO_LOOK = Look("hair.hero", (), ("hero.scarf", "hero.tee"), ())


def hero_frames(rig: Rig, look: Look = HERO_LOOK) -> dict[str, list[Grid]]:
    idle = [figure(rig, look, dy=dy, blink=i == 7, extra=("hero.tail.down",))
            for i, dy in enumerate(IDLE_DY)]
    walk = [
        figure(rig, look, "legs.w0", "arm.back", far="far.fwd", extra=("hero.tail.down",)),
        figure(rig, look, "legs.w1", "arm.down", dy=-1, extra=("hero.tail.up",)),
        figure(rig, look, "legs.w2", "arm.fwd", far="far.back", extra=("hero.tail.down",)),
        figure(rig, look, "legs.w3", "arm.down", dy=-1, extra=("hero.tail.mid",)),
    ]
    # doubled over, clutching the gut: what the collector's baton does
    hurt = [figure(rig, look, "legs.hurt", "arm.clutch", dy=1, head=(1, 0), mouth=True,
                   blink=True, extra=("hero.tail.up",))]
    return {"idle": idle, "walk": walk, "hurt": hurt}


# --- the human rig (16x16) ----------------------------------------------------------
# head rows 2-6 (eye 9,5, nose 11,5, mouth 9,6), torso rows 7-11 with the near arm
# at x 7-9 (7 = the ink line on its back edge), legs rows 12-13, boots row 14.

HUMAN = Rig("human", (16, 16), eye=(9, 5), mouth=(9, 6), parts={
    "head": part(2, """
        .....qqsss......
        ....qqsssss.....
        ....sssssss.....
        ....sSSssess....
        .....SSsss......
        """),
    "hair.hero": part(2, """
        .....jjhhhh.....
        ....jhhhhhhhh...
        ....hhhhHhs.....
        ....hhHh........
        ....hHh.........
        """),
    "hair.short": part(2, """
        .....jjhhh......
        ....jhhhhhhh....
        ....hhhhhhh.....
        ....hhHh........
        .....Hh.........
        """),
    "hair.slick": part(2, """
        .....jjhhh......
        ....jhhhhhh.....
        ....hhhhhH......
        ....hhHH........
        .....H..........
        """),
    "hair.crop": part(2, """
        .....hhhhh......
        ....hhhhhhH.....
        ....hHHh........
        """),
    "torso": part(7, """
        ......tttt......
        .....yyyttt.....
        .....yyyttt.....
        .....yyyttT.....
        .....TTTTTT.....
        """),
    "legs.stand": part(12, """
        ......PPpP......
        ......PP.pP.....
        .....BBB.bbB....
        """),
    "legs.w0": part(12, """
        .....PPppP......
        ....PP...pP.....
        ...BBB....bbB...
        """),
    "legs.w1": part(11, """
        ......PPpp......
        ......PPpp......
        .....BBBpp......
        ........bbB.....
        """),
    "legs.w2": part(12, """
        .....ppPPP......
        ....pP...PP.....
        ...bbB....BBB...
        """),
    "legs.w3": part(11, """
        ......PPpp......
        ......PPpp......
        ......PPbbB.....
        .....BBB........
        """),
    "legs.hurt": part(13, """
        ....PPp.pPp.....
        ...BBB...bbB....
        """),
    "arm.down": part(8, """
        .......kxr......
        .......kxr......
        .......kxR......
        .......kdD......
        """),
    "arm.back": part(8, """
        .......kxr......
        .......kxr......
        ......kxR.......
        ......kdD.......
        """),
    "arm.fwd": part(8, """
        .......kxr......
        .......kxr......
        ........kxR.....
        ........kdD.....
        """),
    "far.fwd": part(10, """
        ...........D....
        """),
    "far.back": part(10, """
        ....D...........
        """),
    "arm.clutch": part(8, """
        .......kxr......
        .......kxRr.....
        ........kRdD....
        """),
    "arm.open": part(8, """
        .......kxr......
        .......kxr..dD..
        .......kxRrr....
        """),
    "arm.open_up": part(7, """
        ............dD..
        .......kxr.rr...
        .......kxrr.....
        .......kxR......
        """),
    # the runner
    "hero.scarf": part(7, """
        .....Aaaai......
        """),
    "hero.tee": part(8, """
        ..........u.....
        ..........u.....
        ..........U.....
        """),
    "hero.tail.down": part(8, """
        ....a...........
        ....A...........
        """),
    "hero.tail.up": part(7, """
        ...aa...........
        ..A.............
        """),
    "hero.tail.mid": part(7, """
        ....a...........
        ...a............
        ...A............
        """),
    # fixer
    "fixer.coat": part(12, """
        .....yttttT.....
        ....yyttTT......
        """),
    "fixer.collar": part(4, """
        ...tT...........
        ...ta...........
        ....ta..........
        .....t..........
        """),
    "fixer.shades": part(5, """
        ........kKg.....
        """),
    "fixer.shades2": part(5, """
        ........kgK.....
        """),
    "fixer.hold": part(8, """
        .......kxr......
        .......kxr..g...
        .......kxRrdC...
        """),
    "fixer.show": part(7, """
        ............gC..
        .......kxr..dD..
        .......kxrrr....
        .......kxR......
        """),
    "fixer.show2": part(7, """
        ................
        .......kxr..GC..
        .......kxrrdD...
        .......kxR......
        """),
    # vendor
    "vendor.cap": part(1, """
        ......iaa.......
        .....iaaaa......
        ....aaaaaaAAA...
        """),
    "vendor.apron": part(11, """
        ........uuU.....
        .......uuuU.....
        .......uuUU.....
        """),
    "vendor.bib": part(7, """
        .........U......
        ..........u.....
        ..........u.....
        """),
    "vendor.rest": part(8, """
        .......kxr......
        .......kxr......
        .......kxrrd....
        """),
    "vendor.reader": part(7, """
        ............Cg..
        .......kxr..dD..
        .......kxrrr....
        .......kxR......
        """),
    # doc
    "doc.coat": part(12, """
        .....yttttT.....
        ....yyttTT......
        """),
    "doc.scrubs": part(7, """
        .........u......
        ..........u.....
        ..........u.....
        ..........U.....
        """),
    "doc.goggles": part(3, """
        ....CCCCCgG.....
        """),
    "doc.cross": part(8, """
        ........a.......
        .......aaa......
        ........a.......
        """),
    "doc.gloves_up": part(7, """
        ..........dD....
        .......kxr.r....
        .......kxrr.....
        .......kxR......
        """),
    "doc.syringe": part(8, """
        .......kxr...cg.
        .......kxrrdD...
        .......kxR......
        """),
    "doc.syringe2": part(7, """
        .............g..
        .......kxr..c...
        .......kxrrdD...
        .......kxR......
        """),
    # ganger
    "ganger.spikes": part(7, """
        .....c..........
        ....c...........
        """),
    "ganger.mohawk": part(0, """
        .......g.g......
        ......jhhhh.....
        .....hhhhH......
        ....SS..........
        ....Sa..........
        """),
    "ganger.tattoo": part(9, """
        ........a.......
        """),
    "ganger.point": part(8, """
        .......kxrrrdD..
        .......kxR......
        """),
    "ganger.pump": part(5, """
        ..........dD....
        ..........rr....
        ..........r.....
        .......kxrr.....
        .......kxR......
        """),
    # civilian
    "civilian.hood": part(1, """
        ......yyt.......
        .....yyttt......
        ....yyttttT.....
        ....ytTK........
        ....ytK.........
        .....tT.........
        """),
    "civilian.pocket": part(8, """
        .......kxr......
        .......kxr......
        .......kxRr.....
        ........kRU.....
        """),
    "civilian.shrug": part(8, """
        .......kxr......
        .......kxr......
        .......kxRr.dD..
        ..........rr....
        """),
    # collector
    "collector.shirt": part(7, """
        ........uu......
        ..........A.....
        ..........A.....
        """),
    "collector.visor": part(4, """
        ........CCC.....
        ......CCWggG....
        """),
    "collector.visor1": part(4, """
        ........CCC.....
        ......CCgWgG....
        """),
    "collector.visor2": part(4, """
        ........CCC.....
        ......CCggWG....
        """),
    "collector.baton": part(8, """
        .......kxr......
        .......kxr......
        .......kxR......
        .......kdD......
        .........c......
        ..........c.....
        ...........g....
        """),
    "collector.raise": part(4, """
        .............g..
        ............c...
        ...........c....
        ..........dD....
        .......kxrr.....
        .......kxR......
        """),
    "collector.tap": part(8, """
        .......kxr......
        .......kxr......
        .......kxRrdDccg
        """),
})

RIGS = {"human": HUMAN}


@dataclass(frozen=True)
class Cast:
    """Who plays a role in one metatype: skin tone, hair colour, optional
    hairstyle override and outfit tweaks (slot -> colour)."""

    skin: str
    hair: str
    style: str | None = None
    outfit: dict[str, str] = field(default_factory=dict)


CAST = {
    ("hero", "human"): Cast("fair", "brown"),
    ("fixer", "human"): Cast("brown", "black"),
    ("vendor", "human"): Cast("tan", "red"),
    ("doc", "human"): Cast("fair", "brown"),
    ("ganger", "human"): Cast("fair", "mohawk"),
    ("civilian", "human"): Cast("tan", "black"),
    ("collector", "human"): Cast("fair", "black"),
}


def _look(look: Look, cast: Cast) -> Look:
    return look if cast.style is None else Look(cast.style, look.skirt, look.wear, look.gear)


def _register_all() -> None:
    for race, rig in RIGS.items():
        cast = CAST[("hero", race)]
        hero = hero_frames(rig, _look(HERO_LOOK, cast))
        plain = legend({**HERO_OUTFIT, **cast.outfit}, cast.skin, cast.hair)
        aug = {**plain, **AUG}
        note = f"the runner ({race}): yellow jacket, the orange Tau-7 scarf"
        register(f"cp.hero.{race}.idle", art(*hero["idle"], legend=plain, fps=4, note=note))
        register(f"cp.hero.{race}.walk", art(*hero["walk"], legend=plain, fps=8, note=note))
        register(f"cp.hero.{race}.hurt", art(*hero["hurt"], legend=plain, note=note))
        note = f"the runner ({race}) with cyberware: chrome arm, glowing eye"
        register(f"cp.hero.{race}.aug.idle", art(*hero["idle"], legend=aug, fps=4, note=note))
        register(f"cp.hero.{race}.aug.walk", art(*hero["walk"], legend=aug, fps=8, note=note))
        for role_name, role in ROLES.items():
            cast = CAST[(role_name, race)]
            outfit = dict(OUTFITS[role_name])
            if role_name == "ganger":  # bare tattooed arms
                q, s, S = SKIN[cast.skin]
                outfit.update(x=q, r=s, R=S)
            outfit.update(cast.outfit)
            lg = legend(outfit, cast.skin, cast.hair, role.hands)
            idle, talk = npc_frames(rig, role, _look(role.look, cast))
            note = f"{role_name} ({race})"
            register(f"cp.npc.{role_name}.{race}.idle", art(*idle, legend=lg, fps=4, note=note))
            register(f"cp.npc.{role_name}.{race}.talk", art(*talk, legend=lg, fps=4, note=note))


_register_all()
