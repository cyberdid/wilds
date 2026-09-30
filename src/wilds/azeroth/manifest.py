"""The sprite contract of the Azeroth chapter: every name the renderer may ask for in Mulgore.

Derived from the content pack wherever possible (which species live there, which races and
roles of people, which quest givers deserve portraits) so the list grows with the data,
and from the terrain enum for ground. Sizes follow the world's scale: a tile is 16 px and
two yards, so one yard is 8 px. A human-sized body fits a tile; a tauren stands taller
(16x24), a kodo is two tiles long (32x24), Thunder Bluff's buildings are multi-tile pieces.

Sprite modules (``wilds.azeroth.sprites.<module>``) must satisfy ``REQUIRED[module]``;
``check`` reports what is still missing, with the same rules as the Wilds manifest.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from ..gfx.manifest import Need, check as _check
from .content import load, slug
from .terrain import Terrain

PACK = Path(__file__).resolve().parents[3] / "data" / "azeroth" / "mulgore"

# --- creatures --------------------------------------------------------------------------
# species slug -> (sprite size, yards it stands/measures): design classes, see module doc
CRITTER = "<=12x12"
SMALL = "<=16x16"
MEDIUM = "<=16x24"
LARGE = "<=32x24"
HUGE = "<=32x40"
SPECIES_SIZE = {
    "rabbit": CRITTER, "mouse": CRITTER, "ground_squirrel": CRITTER, "crawdad": CRITTER, "dog": CRITTER,
    "gazelle": SMALL, "wolf": SMALL, "timber_wolf": SMALL, "boar": SMALL, "vulture": SMALL, "eagle": SMALL,
    "cougar": SMALL, "lion": SMALL, "mountain_lion": SMALL, "gnoll": SMALL, "harpy": SMALL, "quilboar": SMALL,
    "homunculus": SMALL, "tentacle": SMALL, "skeleton": SMALL, "bag": SMALL, "barrel": SMALL,
    "tallstrider": MEDIUM, "ghost": MEDIUM, "wraith": MEDIUM, "haunt": MEDIUM, "earth_elemental": MEDIUM,
    "totem": MEDIUM, "training_dummy": MEDIUM, "ogre": MEDIUM, "nraqi": MEDIUM, "treant": LARGE,
    "kodo": LARGE, "pink_elekk": LARGE, "ancient": HUGE,
}
# species that are people: drawn from the body sets below, not as creatures
PERSON_SPECIES = {"tauren", "highmountain_tauren", "goblin", "forsaken", "dwarf", "orc", "pandaren", "earthen",
                  "blood_elf", "jungle_troll", "human", "varies", ""}
OBJECT_SPECIES = {"bag", "barrel", "totem", "training_dummy"}  # stand-alone props, handled as objects

# --- people -----------------------------------------------------------------------------
BODIES = {  # body -> sprite size
    "tauren_m": "<=16x24", "tauren_f": "<=16x24", "goblin": "<=16x16", "forsaken": "<=16x16", "dwarf": "<=16x16",
    "orc": "<=16x20", "pandaren": "<=16x20", "troll": "<=16x24", "earthen": "<=16x20", "blood_elf": "<=16x16",
    "human": "<=16x16",
}
TAUREN_OUTFITS = ("civilian", "hunter", "shaman", "druid", "warrior", "priest", "merchant", "trainer", "elder",
                  "guard", "palemane")
COMBAT_OUTFITS = {"hunter", "warrior", "guard", "palemane", "shaman", "druid"}
OTHER_OUTFITS = ("civilian", "merchant")
PORTRAIT_QUEST_GIVERS = 3  # an NPC who starts at least this many quests gets a portrait


def _active(kind: str, pack: Path) -> list[dict]:
    return [r for r in load(pack, kind) if not r["removed"]]


def species(pack: Path = PACK) -> list[str]:
    seen: collections.Counter[str] = collections.Counter()
    for kind in ("mob", "npc"):
        for r in _active(kind, pack):
            s = slug(r["info"].get("race", ""))
            if s and s not in PERSON_SPECIES and s not in OBJECT_SPECIES and s != "page":
                seen[s] += 1
    for s in ("tallstrider", "kodo", "wolf", "boar", "gazelle", "rabbit"):  # the plains fauna, always
        seen.setdefault(s, 0)
    return sorted(seen)


def hostile_species(pack: Path = PACK) -> set[str]:
    """Species with at least one mob that is hostile to the Horde (the hero's side)."""
    return {slug(r["info"]["race"]) for r in _active("mob", pack)
            if r["info"].get("race") and r.get("aggro", {}).get("horde") == -1}


def portraits(pack: Path = PACK) -> list[str]:
    starts = collections.Counter(re.sub(r"\s*\(.*", "", r["info"].get("start", "")).strip()
                                 for r in _active("quest", pack) if r["info"].get("start"))
    names = {r["title"]: r["id"] for r in _active("npc", pack)}
    return sorted(names[n] for n, c in starts.items() if c >= PORTRAIT_QUEST_GIVERS and n in names)


# --- needs, by sprite module ---------------------------------------------------------------
def terrain() -> list[Need]:
    n = [
        Need("az.ground.grass", "16x16", variants=4, note="short green prairie grass, seamless"),
        Need("az.ground.tall_grass", "16x16", variants=4, note="tall swaying golden-green grass, seamless"),
        Need("az.ground.dry_grass", "16x16", variants=4, note="yellowed dry grass, seamless"),
        Need("az.ground.dirt", "16x16", variants=3, note="bare earth, seamless"),
        Need("az.ground.road", "16x16", variants=3, note="packed dirt road, seamless with dirt"),
        Need("az.ground.mesa", "16x16", variants=3, note="red-brown rock plateau surface"),
        Need("az.ground.water", "16x16", frames=4, variants=2, note="lake water, animated"),
        Need("az.ground.shallows", "16x16", frames=4, variants=2, note="clear shallow water over sand"),
        Need("az.mountain.top", "16x16", variants=3, note="top of the mountain wall"),
        Need("az.mountain.face", "16x16", variants=3, note="south face of a mountain"),
        Need("az.cliff.face", "16x16", variants=3, note="cliff wall at the land's edge"),
        Need("az.boulder", "<=16x16", variants=3, note="boulder, blocks the way"),
    ]
    for kind in ("water", "dirt", "cliff"):
        for side in ("n", "s", "e", "w"):
            n.append(Need(f"az.edge.{kind}.{side}", "16x16", note=f"overlay: {kind} meets grass, grass to the {side}"))
        for corner in ("ne", "nw", "se", "sw"):
            n.append(Need(f"az.edge.{kind}.corner.{corner}", "16x16", note=f"overlay: inner corner {corner}"))
    n += [Need(f"az.deco.{d}", "<=16x16", variants=2, note="scattered, walkable decoration") for d in
          ("flower_red", "flower_yellow", "flower_blue", "tuft", "stones", "bones", "dry_bush", "stump")]
    return n


MONSTER_SPECIES = {"quilboar", "gnoll", "harpy", "ogre", "wraith", "ghost", "haunt", "earth_elemental", "treant",
                   "tentacle", "nraqi", "ancient", "skeleton", "homunculus", "pink_elekk"}


def _creature_needs(names: list[str], pack: Path) -> list[Need]:
    hostile = hostile_species(pack)
    n = []
    for s in names:
        size = SPECIES_SIZE.get(s, SMALL)
        n.append(Need(f"az.creature.{s}.idle", size, frames=2))
        n.append(Need(f"az.creature.{s}.move", size, frames=4 if size != CRITTER else 2))
        if s in hostile:
            n.append(Need(f"az.creature.{s}.attack", size, frames=2))
        n.append(Need(f"az.creature.{s}.dead", size))
    return n


def creatures(pack: Path = PACK) -> list[Need]:
    """Beasts and critters of the plains."""
    return _creature_needs([s for s in species(pack) if s not in MONSTER_SPECIES], pack)


def monsters(pack: Path = PACK) -> list[Need]:
    """Sapient and supernatural creatures: quilboar, gnolls, harpies, spirits, elementals, ogres."""
    return _creature_needs([s for s in species(pack) if s in MONSTER_SPECIES], pack)


def _body_needs(bodies: dict[str, str]) -> list[Need]:
    n = []
    for body, size in bodies.items():
        outfits = TAUREN_OUTFITS if body.startswith("tauren") else OTHER_OUTFITS
        for outfit in outfits:
            n += [Need(f"az.person.{body}.{outfit}.idle", size, frames=2),
                  Need(f"az.person.{body}.{outfit}.walk", size, frames=4),
                  Need(f"az.person.{body}.{outfit}.talk", size, frames=2, note="gesturing mid-conversation")]
            if outfit in COMBAT_OUTFITS:
                n.append(Need(f"az.person.{body}.{outfit}.attack", size, frames=3))
        n.append(Need(f"az.person.{body}.dead", size))
        n.append(Need(f"az.person.{body}.hurt", size))
    return n


def people_other() -> list[Need]:
    """Goblins, forsaken, dwarves, orcs, pandaren, trolls, earthen, blood elves, humans."""
    return _body_needs({b: z for b, z in BODIES.items() if not b.startswith("tauren")})


def people_tauren(pack: Path = PACK) -> list[Need]:
    """Tauren in every outfit, the hero (a tauren) and the quest-giver portraits."""
    n = _body_needs({b: z for b, z in BODIES.items() if b.startswith("tauren")})
    n += [Need(f"az.portrait.{p}", "24x24", note="quest giver portrait") for p in portraits(pack)]
    n.append(Need("az.portrait.hero", "24x24", note="the hero's portrait"))
    n += [Need("az.person.hero.idle", "<=16x24", frames=2), Need("az.person.hero.walk", "<=16x24", frames=4),
          Need("az.person.hero.attack", "<=16x24", frames=3), Need("az.person.hero.work", "<=16x24", frames=2)]
    return n


def structures() -> list[Need]:
    """Camps, villages, mines, nests, gates and things to gather or open."""
    return [
        # Bloodhoof Village, Camp Narache, Camp Sungraze
        Need("az.obj.hut_large", "<=48x40", frames=1, note="tauren hide-and-timber longhouse"),
        Need("az.obj.hut_small", "<=32x32", variants=2, note="small tauren hut"),
        Need("az.obj.tent", "<=32x28", variants=3, note="hide tent, three patterns"),
        Need("az.obj.totem_pole", "<=16x40", variants=3, note="carved totem pole"),
        Need("az.obj.bonfire", "<=16x16", frames=3, note="camp bonfire"),
        Need("az.obj.drying_rack", "<=24x16", note="hide/meat drying rack"),
        Need("az.obj.kodo_pen", "<=32x24", note="kodo corral fence section"),
        Need("az.obj.well", "<=16x24", note="water well with bucket"),
        Need("az.obj.banner", "<=16x32", frames=2, note="horde war banner, waves"),
        Need("az.obj.anvil", "<=16x16", note="blacksmith anvil"),
        Need("az.obj.forge", "<=24x24", frames=3, note="burning forge"),
        Need("az.obj.stable", "<=40x32", note="stable, kodo and strider stalls"),
        Need("az.obj.inn", "<=48x40", note="tauren inn"),
        Need("az.obj.training_dummy", "<=16x24", note="training dummy"),
        Need("az.obj.barrel", "<=16x16", variants=2),
        Need("az.obj.crate", "<=16x16", variants=2),
        Need("az.obj.wagon", "<=40x24", note="ravaged caravan wagon"),
        # Bael'dun Digsite, Venture Co. Mine
        Need("az.obj.dig_tent", "<=32x28", note="dwarven expedition tent"),
        Need("az.obj.scaffold", "<=32x32", note="wooden excavation scaffold"),
        Need("az.obj.mine_entrance", "<=48x40", note="Venture Co. mine shaft, timber frame"),
        Need("az.obj.goblin_shack", "<=32x28", note="goblin worker shack"),
        Need("az.obj.ore_cart", "<=24x16", note="mine cart"),
        # quilboar, harpies, palemane
        Need("az.obj.thorn_hut", "<=32x32", variants=2, note="quilboar thorn-and-hide hut"),
        Need("az.obj.barricade", "<=24x16", note="thorn barricade"),
        Need("az.obj.harpy_nest", "<=24x24", note="windfury harpy nest on a ridge"),
        Need("az.obj.rock_arch", "<=48x40", note="Palemane Rock natural arch"),
        Need("az.obj.kodo_bones", "<=32x16", note="Kodo Rock: bleached giant bones"),
        Need("az.obj.great_gate", "<=64x48", frames=2, note="Great Gate on the eastern edge, torches"),
        Need("az.obj.stonetalon_pass", "<=48x32", note="pass through the northern mountains"),
        # gathering and loot
        Need("az.node.peacebloom", "<=16x16", frames=2), Need("az.node.silverleaf", "<=16x16", frames=2),
        Need("az.node.earthroot", "<=16x16", frames=2), Need("az.node.copper_vein", "<=16x16"),
        Need("az.node.prairie_flower", "<=16x16", frames=2), Need("az.node.shiny_stone", "<=16x16", frames=2),
        Need("az.obj.chest", "<=16x16", frames=2, note="closed / opened by frame"),
        Need("az.obj.chest_locked", "<=16x16"), Need("az.obj.spirit_portal", "<=24x32", frames=4),
    ]


def thunder_bluff() -> list[Need]:
    """The bluff city: platform tileset and multi-tile buildings."""
    return [
        # Thunder Bluff: platform tileset and composite buildings
        Need("az.tb.platform", "16x16", variants=4, note="plank-and-hide platform floor"),
        Need("az.tb.platform.edge", "16x16", variants=4, note="platform edge over the drop"),
        Need("az.tb.bridge", "16x16", variants=2, note="rope bridge between rises"),
        Need("az.tb.rope_rail", "16x16", variants=2, note="rope railing"),
        Need("az.tb.support_pillar", "<=16x48", variants=2, note="pillar below a rise"),
        Need("az.tb.lodge", "<=64x48", variants=2, note="Elder Rise / High Rise lodge"),
        Need("az.tb.totem_tall", "<=24x64", note="tall ceremonial totem"),
        Need("az.tb.tent_row", "<=48x32", variants=2),
        Need("az.tb.spirit_pool", "<=32x24", frames=3, note="Pools of Vision"),
        Need("az.tb.lift", "<=32x24", frames=2, note="the rope elevator"),
        Need("az.tb.warrior_hall", "<=64x48", note="Hunter Rise / warrior hall"),
    ]


ITEM_FAMILIES = ("belt", "boots", "bracers", "chest", "gloves", "helm", "legs", "shoulders", "cloak", "shield",
                 "sword", "axe", "mace", "dagger", "staff", "ranged", "totem", "relic", "ring", "amulet", "food",
                 "drink", "potion", "bag", "reagent", "quest_item", "ticket", "book")


def items() -> list[Need]:
    return [Need(f"az.item.{f}", "16x16", variants=4, note="item icon family, four looks") for f in ITEM_FAMILIES]


def fx() -> list[Need]:
    return [
        Need("az.fx.dust_kick", "<=12x8", frames=3, note="dust under a running kodo/hero"),
        Need("az.fx.totem_glow", "<=16x16", frames=4, note="shaman totem pulse"),
        Need("az.fx.earth_spirit", "<=24x24", frames=4, note="earth elemental aura"),
        Need("az.fx.quest_marker", "<=8x16", frames=3, note="yellow exclamation over a quest giver"),
        Need("az.fx.quest_turnin", "<=8x16", frames=3, note="yellow question mark"),
        Need("az.fx.wind", "<=16x8", frames=4, note="wind streak over the plains"),
        Need("az.fx.grass_sway", "<=16x8", frames=4),
        Need("az.fx.campfire_smoke", "<=16x24", frames=5),
        Need("az.fx.water_ripple", "<=12x8", frames=4),
        Need("az.fx.cast_circle", "<=24x16", frames=4, note="ground circle while casting"),
        Need("az.fx.hit_spark", "<=8x8", frames=3),
        Need("az.fx.level_up", "<=32x32", frames=5),
    ]


def required(pack: Path = PACK) -> dict[str, list[Need]]:
    """Sprite module (``az_<key>``) -> what it must define."""
    return {"terrain": terrain(), "creatures": creatures(pack), "monsters": monsters(pack),
            "people_tauren": people_tauren(pack), "people_other": people_other(),
            "structures": structures(), "thunder_bluff": thunder_bluff(), "items": items(), "fx": fx()}


def check(registry, modules: list[str] | None = None, pack: Path = PACK) -> list[str]:
    return _check(registry, modules, required=required(pack))


def terrain_kinds() -> list[str]:
    """Terrain enum members that have ground art (everything but the void)."""
    return [t.name for t in Terrain if t is not Terrain.VOID]


def summary(pack: Path = PACK) -> dict[str, dict[str, int]]:
    out = {}
    for module, needs in required(pack).items():
        sprites = sum(n.variants or 1 for n in needs)
        frames = sum((n.variants or 1) * n.frames for n in needs)
        out[module] = {"names": len(needs), "sprites": sprites, "frames": frames}
    return out


def write_listing(path: Path, pack: Path = PACK) -> None:
    lines = ["# Mulgore art manifest", "", "Generated by `tools/azeroth_manifest.py` from the content pack.",
             "One tile = 16 px = 2 yards.", ""]
    for module, needs in required(pack).items():
        lines += [f"## {module}", "", "| name | size | frames | variants | note |", "|---|---|---|---|---|"]
        lines += [f"| `{n.name}` | {n.size} | {n.frames} | {n.variants or ''} | {n.note} |" for n in needs]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(summary(), indent=1))
