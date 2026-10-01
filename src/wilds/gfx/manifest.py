"""The sprite contract: every name the renderer may ask for, derived from the
game's own enums and registries wherever possible.

If a new tile, creature, item, NPC role, race or location is added to the game,
the lists below grow automatically and ``tests/gfx/test_sprite_coverage.py``
fails until it has art - "every object has a sprite" is enforced, not hoped for.

Size strings: ``"16x16"`` means exactly that; ``"<=32x24"`` means at most.
Actors (heroes, people, creatures) are drawn facing RIGHT in a 3/4 side view and
mirrored for left; their anchor is the pixel under their feet.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..creatures import KINDS
from ..cyberpunk.items import ITEMS as CITY_ITEMS
from ..cyberpunk.npc import ROLES
from ..cyberpunk.race import Race
from ..world import ITEMS as TAU7_ITEMS


@dataclass(frozen=True)
class Need:
    name: str  # exact name, or a variant-set base (then `variants` > 0)
    size: str
    frames: int = 1  # minimum animation frames
    variants: int = 0  # >0: needs at least this many `name@N` variants
    note: str = ""

    @property
    def exact(self) -> bool:
        return not self.size.startswith("<=")

    def dims(self) -> tuple[int, int]:
        w, h = self.size.lstrip("<=").split("x")
        return int(w), int(h)


# which Tau-7 wreck level is drawn with which interior theme (see worldgen.WRECK_NAMES)
WRECK_THEMES = {"wreck_1": "helios", "wreck_2": "kepler", "wreck_3": "hive"}
# city level id -> art theme
CITY_THEMES = {"sprawl": "sprawl", "docks": "docks", "corp_row": "corp",
               "orbital_station": "station", "outpost": "outpost"}
RACES = tuple(r.name.lower() for r in Race)

TAU7_ITEM_KEYS = tuple(TAU7_ITEMS)
CITY_ITEM_KEYS = tuple(CITY_ITEMS)
CREATURE_KEYS = tuple(KINDS)


def _tau7_terrain() -> list[Need]:
    n = [
        Need("t7.ground.moss", "16x16", variants=4, note="moss ground, seamless"),
        Need("t7.ground.dust", "16x16", variants=4, note="red dust ground, seamless"),
        Need("t7.ground.scorch", "16x16", variants=2, note="burnt ground around the pod / crash / craters"),
        Need("t7.ground.water", "16x16", frames=4, variants=2, note="animated water surface"),
        Need("t7.rock.top", "16x16", variants=3, note="top of a rock mass (plateau)"),
        Need("t7.rock.face", "16x16", variants=3, note="south cliff face of rock with ore veins"),
        Need("t7.water.bank", "16x16", note="overlay: earth bank at the top of a water tile below land"),
        Need("t7.flora", "<=16x32", frames=2, variants=3, note="tall xeno-flora, sways"),
        Need("t7.stalk", "<=16x16", note="cut flora stalk"),
        Need("t7.spore_bush", "<=16x16", frames=3, note="spore bush, glowing pods pulse"),
        Need("t7.spore_bush_empty", "<=16x16", note="harvested spore bush"),
        Need("t7.heater", "<=16x24", frames=3, note="working heater, flames/coils"),
        Need("t7.heater_off", "<=16x24", note="dead heater"),
        Need("t7.dome", "<=24x24", note="inflatable habitat dome"),
        Need("t7.grave", "<=16x16", note="a grave"),
        Need("t7.pod", "<=32x24", frames=2, note="the hero's crashed escape pod (beacon broken)"),
        Need("t7.pod.antenna", "<=32x24", frames=2, note="overlay on t7.pod: repaired beacon antenna"),
        Need("t7.pod.glow", "<=32x24", frames=2, note="overlay on t7.pod: heater on, warm glow"),
        Need("t7.crash", "<=32x24", note="the second pod's crash site"),
        Need("t7.wreck.helios", "<=40x32", frames=2, note="entrance: wreck of the ship Helios"),
        Need("t7.wreck.kepler", "<=40x32", frames=2, note="entrance: Kepler-9 station module"),
        Need("t7.wreck.hive", "<=40x32", frames=2, note="entrance: the precursor hive"),
    ]
    for side in ("n", "s", "e", "w"):
        n.append(Need(f"t7.water.edge.{side}", "16x16", frames=2, note=f"overlay: shore foam, land to the {side}"))
    for corner in ("ne", "nw", "se", "sw"):
        n.append(Need(f"t7.water.corner.{corner}", "16x16", frames=2,
                      note=f"overlay: inner shore corner, land only diagonally {corner}"))
    for theme in WRECK_THEMES.values():
        n += [
            Need(f"t7.{theme}.floor", "16x16", variants=4, note=f"{theme} interior deck"),
            Need(f"t7.{theme}.wall.top", "16x16", variants=2, note=f"{theme} bulkhead seen from above"),
            Need(f"t7.{theme}.wall.face", "16x16", variants=3, note=f"{theme} bulkhead face (south side)"),
            Need(f"t7.{theme}.hatch", "16x16", frames=2, note=f"{theme} exit hatch"),
        ]
    return n


def _tau7_life() -> list[Need]:
    n = [
        Need("t7.hero.idle", "<=16x16", frames=2),
        Need("t7.hero.walk", "<=16x16", frames=4),
        Need("t7.hero.work", "<=16x16", frames=2, note="gather / craft / build / cook / repair"),
        Need("t7.hero.drink", "<=16x16", frames=2, note="kneeling at water"),
        Need("t7.hero.attack", "<=16x16", frames=3),
        Need("t7.hero.sleep", "<=16x16", frames=2, note="lying down"),
        Need("t7.hero.hurt", "<=16x16"),
        Need("t7.hero.portrait", "24x24", note="HUD portrait"),
        Need("t7.lira.idle", "<=16x16", frames=2),
        Need("t7.lira.walk", "<=16x16", frames=4),
        Need("t7.lira.carry", "<=16x16", frames=4, note="walking with a fiber bundle"),
        Need("t7.lira.work", "<=16x16", frames=2),
        Need("t7.lira.sleep", "<=16x16", frames=2),
        Need("t7.lira.wave", "<=16x16", frames=2, note="stranded at her crash site, waving for help"),
        Need("t7.lira.portrait", "24x24", note="HUD portrait"),
    ]
    sizes = {"brute": "<=24x24"}
    for kind in CREATURE_KEYS:
        size = sizes.get(kind, "<=16x16")
        n.append(Need(f"t7.{kind}.idle", size, frames=2))
        n.append(Need(f"t7.{kind}.move", size, frames=3 if kind == "hopper" else 2 if kind == "drone" else 4))
        if KINDS[kind].hostile:
            n.append(Need(f"t7.{kind}.attack", size, frames=2))
    return n


def _items() -> list[Need]:
    n = [Need(f"t7.item.{k}", "16x16", note=TAU7_ITEMS[k].note) for k in TAU7_ITEM_KEYS]
    n += [Need(f"cp.item.{k}", "16x16", note=CITY_ITEMS[k].note) for k in CITY_ITEM_KEYS]
    return n


UI_ICONS = (
    # Tau-7 HUD
    "hp", "satiety", "hydration", "warmth", "energy", "day", "night", "power", "heater", "fault",
    "beacon", "shuttle", "weapon", "light", "companion", "trust", "tension", "warning", "threat",
    "goal", "thought", "diary", "brain", "storage", "skull",
    "phase.calm", "phase.rising", "phase.peak", "phase.relief",
    # city HUD
    "nuyen", "debt", "essence", "heat", "ship", "fuel", "hull", "contract", "delinquent", "evicted",
    "race", "location", "rep.fixers", "rep.vendors", "rep.gangs",
    # controls
    "speed", "pause",
)
LOG_KINDS = ("info", "danger", "good", "brain", "death", "event", "diary", "talk", "victory")


def _ui() -> list[Need]:
    n = [Need(f"ui.{i}", "12x12") for i in UI_ICONS]
    n += [Need(f"ui.log.{k}", "8x8", note=f"event-log marker for '{k}' events") for k in LOG_KINDS]
    return n


def _fx() -> list[Need]:
    return [
        Need("fx.spark", "<=8x8", frames=3),
        Need("fx.smoke", "<=16x16", frames=5, note="one puff rising and fading (loop=False)"),
        Need("fx.explosion", "<=48x48", frames=6, note="loop=False"),
        Need("fx.meteor", "<=16x32", frames=2, note="burning debris falling straight down"),
        Need("fx.impact_marker", "<=48x48", frames=4, note="pulsing target over the 3x3 impact zone"),
        Need("fx.zzz", "<=12x12", frames=3),
        Need("fx.slash", "<=16x16", frames=3, note="blade swing arc"),
        Need("fx.slash_plasma", "<=16x16", frames=3, note="plasma cutter arc"),
        Need("fx.punch", "<=16x16", frames=2),
        Need("fx.bite", "<=16x16", frames=2, note="creature attack"),
        Need("fx.zap", "<=16x16", frames=2, note="drone/android energy hit"),
        Need("fx.pickup", "<=16x16", frames=4, note="loop=False"),
        Need("fx.heal", "<=16x16", frames=4),
        Need("fx.blood", "<=8x8", frames=3, note="loop=False"),
        Need("fx.frost", "<=8x8", frames=2),
        Need("fx.dust", "<=4x4", variants=2),
        Need("fx.spore", "<=4x4", frames=2),
        Need("fx.rain", "<=4x12"),
        Need("fx.splash", "<=8x6", frames=3, note="loop=False"),
        Need("fx.beacon_wave", "<=32x32", frames=5, note="expanding radio ring"),
        Need("fx.steam", "<=16x16", frames=4),
        Need("fx.drop_marker", "<=16x24", frames=4, note="contract dead-drop hologram"),
        Need("fx.alert", "<=8x12", frames=2),
        Need("fx.thinking", "<=16x12", frames=3, note="thought bubble with dots"),
        Need("fx.death_poof", "<=16x16", frames=4, note="loop=False"),
        Need("fx.shuttle", "<=48x40", frames=2, note="rescue shuttle, thrusters on"),
        Need("fx.police", "<=16x16", frames=2, note="police drone, red/blue lights (district heat)"),
        Need("cp.ship", "<=48x24", frames=2, note="the runner's ship, side view facing right"),
        Need("cp.maglev", "<=64x24", frames=2, note="transit train car, side view facing right"),
    ]


CITY_SHARED = ("neon", "alley", "door", "shop", "bar", "fixer", "checkpoint", "fence", "trash")


def _city_terrain() -> list[Need]:
    n = []
    for theme in dict.fromkeys(CITY_THEMES.values()):
        n += [
            Need(f"cp.{theme}.sidewalk", "16x16", variants=3),
            Need(f"cp.{theme}.road", "16x16", variants=3),
            Need(f"cp.{theme}.wall.top", "16x16", variants=2, note="building roof"),
            Need(f"cp.{theme}.wall.face", "16x16", variants=3, note="building facade (south side)"),
            Need(f"cp.{theme}.facade.cap", "16x4", variants=1, note="facade column: parapet on top"),
            Need(f"cp.{theme}.facade.storey", "16x22", variants=3, note="facade column: one upper storey"),
            Need(f"cp.{theme}.facade.ground", "16x28", variants=3, note="facade column: street floor, doors"),
        ]
    n += [
        Need("cp.any.neon", "16x16", frames=2, note="neon-lit pavement"),
        Need("cp.any.alley", "16x16", variants=2, note="narrow grimy alley ground"),
        Need("cp.any.door", "<=16x24", note="doorway"),
        Need("cp.any.shop", "<=24x32", frames=2, note="street vendor stall, neon $ sign"),
        Need("cp.any.bar", "<=24x32", frames=2, note="bar / safehouse kiosk, yellow neon"),
        Need("cp.any.fixer", "<=24x32", frames=2, note="fixer's office booth, cyan holo sign"),
        Need("cp.any.checkpoint", "<=24x32", frames=2, note="corp checkpoint barrier, red scanner"),
        Need("cp.any.fence", "<=16x24", note="chain-link fence"),
        Need("cp.any.trash", "<=16x16", variants=2, note="trash bags / junk"),
    ]
    return n


def _city_people() -> list[Need]:
    n = []
    for race in RACES:
        size = "<=20x24" if race == "troll" else "<=16x16"
        n += [
            Need(f"cp.hero.{race}.idle", size, frames=2),
            Need(f"cp.hero.{race}.walk", size, frames=4),
            Need(f"cp.hero.{race}.hurt", size),
            # the same runner once they own any cyberware: chrome limb, glowing eye
            Need(f"cp.hero.{race}.aug.idle", size, frames=2, note="augmented runner"),
            Need(f"cp.hero.{race}.aug.walk", size, frames=4, note="augmented runner"),
        ]
        for role in ROLES:
            n += [
                Need(f"cp.npc.{role}.{race}.idle", size, frames=2),
                Need(f"cp.npc.{role}.{race}.talk", size, frames=2, note="gesturing mid-conversation"),
            ]
    return n


# owner sprite module -> the names it must define
REQUIRED: dict[str, list[Need]] = {
    "tau7_terrain": _tau7_terrain(),
    "tau7_life": _tau7_life(),
    "items": _items(),
    "ui_icons": _ui(),
    "fx": _fx(),
    "city_terrain": _city_terrain(),
    "city_people": _city_people(),
}


def all_needs() -> list[Need]:
    return [need for needs in REQUIRED.values() for need in needs]


def check(registry, modules: list[str] | None = None, required: dict[str, list[Need]] | None = None) -> list[str]:
    """Human-readable problems: missing names, too few frames/variants, wrong sizes."""
    problems = []
    for module, needs in (REQUIRED if required is None else required).items():
        if modules and module not in modules:
            continue
        for need in needs:
            names = [f"{need.name}@{i}" for i in range(need.variants)] if need.variants else [need.name]
            if need.variants:
                have = [n for n in registry.names(need.name + "@")]
                if len(have) < need.variants:
                    problems.append(f"[{module}] {need.name}: {len(have)}/{need.variants} variants")
                    continue
                names = have
            for name in names:
                if name not in registry:
                    problems.append(f"[{module}] missing {name} ({need.size}, {need.frames}f) {need.note}")
                    continue
                a = registry.get(name)
                w, h = a.size
                mw, mh = need.dims()
                if need.exact and (w, h) != (mw, mh):
                    problems.append(f"[{module}] {name}: is {w}x{h}, must be {need.size}")
                elif not need.exact and (w > mw or h > mh):
                    problems.append(f"[{module}] {name}: is {w}x{h}, must be {need.size}")
                if len(a.frames) < need.frames:
                    problems.append(f"[{module}] {name}: {len(a.frames)} frames, needs >= {need.frames}")
                if need.frames > 1 and a.fps <= 0:
                    problems.append(f"[{module}] {name}: animated but fps is 0")
    return problems
