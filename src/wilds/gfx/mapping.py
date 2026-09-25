"""Game object -> sprite name. The one place that knows which art stands for
which tile, creature, item, NPC or hero state (tests walk every enum through
these functions to prove nothing is left without a sprite)."""

from __future__ import annotations

from ..cyberpunk.tiles import CTile
from ..tiles import Tile
from .manifest import CITY_THEMES, WRECK_THEMES
from .registry import Registry


def hash2(x: int, y: int, salt: int = 0) -> int:
    """Stable, well-mixed 32-bit hash of a tile position (variant picking)."""
    h = (x * 374761393 + y * 668265263 + salt * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return h ^ (h >> 16)


def pick(reg: Registry, base: str, x: int, y: int, salt: int = 0) -> str:
    """A stable variant of ``base`` for this position (or ``base`` itself).

    A missing name is returned unchanged: the renderer draws a placeholder and
    reports it, and the coverage tests make sure that never ships."""
    if base not in reg:
        return base
    vs = reg.variants(base)
    return vs[0] if len(vs) == 1 else vs[hash2(x, y, salt) % len(vs)]


def first(reg: Registry, *candidates: str) -> str:
    """First existing candidate; the first one (-> placeholder) if none exists."""
    return reg.resolve(*candidates) or candidates[0]


# --- Tau-7 -----------------------------------------------------------------------

T7_BLOCKS = (Tile.ROCK, Tile.WALL)
# tiles that are an object standing on some ground (not ground themselves)
T7_OBJECTS = {
    Tile.FLORA: "t7.flora", Tile.STALK: "t7.stalk", Tile.SPORE_BUSH: "t7.spore_bush",
    Tile.SPORE_BUSH_EMPTY: "t7.spore_bush_empty", Tile.HEATER: "t7.heater",
    Tile.HEATER_OFF: "t7.heater_off", Tile.DOME: "t7.dome", Tile.GRAVE: "t7.grave",
    Tile.POD: "t7.pod", Tile.CRASH: "t7.crash",
}


def wreck_theme(level_id: str) -> str:
    return WRECK_THEMES.get(level_id, "helios")


def t7_ground_base(tile: Tile, level_id: str, underlay: Tile = Tile.MOSS) -> str | None:
    """Ground drawn at the tile rect; None for blocks (they draw top/face)."""
    if tile in T7_BLOCKS:
        return None
    if tile is Tile.WATER:
        return "t7.ground.water"
    if tile is Tile.DUST:
        return "t7.ground.dust"
    if tile in (Tile.POD, Tile.CRASH):
        return "t7.ground.scorch"
    if tile is Tile.WRECK:
        return "t7.ground.dust"
    if tile is Tile.FLOOR:
        return f"t7.{wreck_theme(level_id)}.floor"
    if tile is Tile.HATCH:
        return f"t7.{wreck_theme(level_id)}.hatch"
    # objects stand on whatever ground surrounds them
    return "t7.ground.dust" if underlay is Tile.DUST else "t7.ground.moss"


def t7_block(tile: Tile, level_id: str) -> tuple[str, str] | None:
    """(top base, face base) for block tiles."""
    if tile is Tile.ROCK:
        return "t7.rock.top", "t7.rock.face"
    if tile is Tile.WALL:
        theme = wreck_theme(level_id)
        return f"t7.{theme}.wall.top", f"t7.{theme}.wall.face"
    return None


def t7_object(tile: Tile, wreck_level: str | None = None) -> str | None:
    if tile is Tile.WRECK:
        return f"t7.wreck.{wreck_theme(wreck_level or 'wreck_1')}"
    return T7_OBJECTS.get(tile)


def t7_item(key: str) -> str:
    return f"t7.item.{key}"


def t7_actor(reg: Registry, who: str, anim: str) -> str:
    """who: 'hero', 'lira' or a creature kind key."""
    chain = {
        "drink": ("drink", "work", "idle"), "work": ("work", "idle"), "carry": ("carry", "walk", "idle"),
        "wave": ("wave", "idle"), "sleep": ("sleep", "idle"), "hurt": ("hurt", "idle"),
        "attack": ("attack", "move", "walk", "idle"), "walk": ("walk", "move", "idle"),
        "move": ("move", "walk", "idle"),
    }.get(anim, (anim, "idle"))
    return first(reg, *(f"t7.{who}.{a}" for a in chain))


# --- the city ------------------------------------------------------------------------

CP_OBJECTS = {
    CTile.SHOP: "shop", CTile.BAR: "bar", CTile.FIXER: "fixer", CTile.CHECKPOINT: "checkpoint",
    CTile.FENCE: "fence", CTile.TRASH: "trash", CTile.DOOR: "door",
}


def city_theme(level_id: str) -> str:
    return CITY_THEMES.get(level_id, "sprawl")


def cp_ground_base(reg: Registry, tile: CTile, level_id: str, underlay: CTile = CTile.SIDEWALK) -> str | None:
    theme = city_theme(level_id)
    if tile is CTile.WALL:
        return None
    if tile is CTile.ROAD:
        return f"cp.{theme}.road"
    if tile is CTile.NEON:
        return first(reg, f"cp.{theme}.neon", "cp.any.neon")
    if tile is CTile.ALLEY:
        return first(reg, f"cp.{theme}.alley", "cp.any.alley")
    base = CTile.ROAD if underlay is CTile.ROAD else CTile.SIDEWALK
    return f"cp.{theme}.{'road' if base is CTile.ROAD else 'sidewalk'}"


def cp_block(tile: CTile, level_id: str) -> tuple[str, str] | None:
    if tile is CTile.WALL:
        theme = city_theme(level_id)
        return f"cp.{theme}.wall.top", f"cp.{theme}.wall.face"
    return None


def cp_object(reg: Registry, tile: CTile, level_id: str) -> str | None:
    what = CP_OBJECTS.get(tile)
    if what is None:
        return None
    return first(reg, f"cp.{city_theme(level_id)}.{what}", f"cp.any.{what}")


def cp_item(key: str) -> str:
    return f"cp.item.{key}"


def cp_hero(reg: Registry, race: str, anim: str, augmented: bool = False) -> str:
    chain = (anim, "idle") if anim != "hurt" else ("hurt", "idle")
    if augmented:
        names = [f"cp.hero.{race}.aug.{a}" for a in chain] + [f"cp.hero.{race}.{a}" for a in chain]
    else:
        names = [f"cp.hero.{race}.{a}" for a in chain]
    return first(reg, *names)


def cp_npc(reg: Registry, role: str, race: str, anim: str = "idle") -> str:
    return first(reg, f"cp.npc.{role}.{race}.{anim}", f"cp.npc.{role}.{race}.idle")
