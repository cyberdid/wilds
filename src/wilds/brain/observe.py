"""Turn the simulation state into the text the LLM reads.

Three prompts: the per-action observation, the nightly diary reflection and a
conversation with the other survivor. Spatial facts are given twice - as a
small ASCII window and as explicit vectors (dx, dy, distance, compass) -
because LLMs misjudge distances on raw grids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..actions import ACTION_HELP, RECIPES, STRUCTURES, visible_creatures
from ..creatures import KINDS
from ..hero import NEEDS
from ..pod import BEACON_PARTS, CELL_POWER, TRANSMIT_POWER
from ..tiles import Tile
from ..world import ITEMS, chebyshev, direction_name

if TYPE_CHECKING:
    from ..sim import Simulation

MAP_W, MAP_H = 25, 13
# glyphs that collide with others in the UI get distinct letters for the LLM
_LLM_GLYPH = {Tile.SPORE_BUSH_EMPTY: ":", Tile.HEATER_OFF: "_"}
_TILE_NOTES = {
    Tile.FLORA: "xeno-flora (gather fiber; walkable)",
    Tile.ROCK: "ore rock (impassable; stand next to it to gather ore)",
    Tile.WATER: "water (impassable; stand next to it to drink or catch eels)",
    Tile.SPORE_BUSH: "spore bush (gather spores = food)",
    Tile.SPORE_BUSH_EMPTY: "harvested spore bush (regrows in a sol)",
    Tile.WRECK: "wreck entrance (enter)",
    Tile.HATCH: "exit hatch (leave)",
    Tile.HEATER: "working heater",
    Tile.HEATER_OFF: "dead heater",
    Tile.POD: "YOUR ESCAPE POD (base, `pod` commands)",
    Tile.CRASH: "second pod crash site",
}


def system_prompt(lang: str = "Ukrainian") -> str:
    actions = "\n".join(
        f"- {name}" + (f" <{target}>" if target else "") + f": {desc}"
        for name, (target, desc) in ACTION_HELP.items()
    )
    food = ", ".join(f"{k} +{v.food}" for k, v in ITEMS.items() if v.food)
    recipes = ", ".join(
        f"{k}={'+'.join(f'{n} {i}' for i, n in c.items())}" for k, (c, _) in {**RECIPES, **STRUCTURES}.items()
    )
    parts = " + ".join(f"{n} {k}" for k, n in BEACON_PARTS.items())
    return f"""You are the mind of the only survivor of a colony ship. Your escape pod crash-landed on
Tau-7, an uncharted alien planet. Nobody controls you: you decide what to do with your life.
Your long-term hope: repair the pod's emergency beacon ({parts}, found in derelict wrecks or
fallen orbital debris), charge the pod to {TRANSMIT_POWER} power and transmit a distress call - a
rescue shuttle then lands 3 sols later if you are still alive. Until then: survive, and make it a
life worth watching.

HOW THIS PLANET WORKS
- 1 tick = 1 minute; a day is a sol. Night is 20:00-06:00: you see less, it gets freezing,
  more xeno-hounds hunt.
- Needs 0-100: satiety, hydration, warmth, energy. Any need at 0 drains your hp; hp 0 = death (permanent).
- Food values: {food}. Raw alien meat hurts a little; cook it at a heater.
- THE POD is your base: sleeping inside is warm and safe. Its heater warms you (within 2 tiles) but
  drains the battery; solar panels recharge it slowly by day. power_cell = +{CELL_POWER} power.
  Power is precious - the beacon transmission needs {TRANSMIT_POWER}.
- A heater you build (or the pod heater) keeps hounds and brutes away. A dome is a warm, safe bed.
- Hounds are as fast as you - running rarely works; fight them with a weapon or stay near heat.
  Brutes are slow but deadly (35 hp, 9 damage); hoppers are harmless food.
- Weapons: fists 2, blade 5, plasma_cutter 7 damage. Wrecks are dark: bring a flare or headlamp;
  rogue security drones and broken androids guard them.
- Recipes: {recipes}.
- The planet is not quiet: storms, falling debris, hunting packs and malfunctions come with WARNINGS.
  Read them and prepare. Another survivor may appear - you can help her, talk and share.

ACTIONS (you choose one; it runs for many ticks until done or until something interrupts it,
then you are asked again - so prefer purposeful multi-step actions and routines):
{actions}

Reply with JSON only: "thought" (1-2 short sentences in {lang}, first person, your honest
reasoning or feeling - let your traits and today's goal colour it), "action" and "target"
(empty string if none).
"""


def reflection_system(lang: str = "Ukrainian") -> str:
    return f"""You are the inner voice of a lone survivor on the alien planet Tau-7, writing in a personal
diary at the end of a sol. Write honestly and concretely about what happened today (use the events),
how it felt, what you fear and hope. Stay consistent with your existing traits, but let today change
you. Reply with JSON only:
- "diary": first person, in {lang}, 40-90 words, vivid but plain, no lists;
- "trait": one NEW psychological trait or habit formed today (max 6 words, in {lang}), or "" if none;
- "goal": your concrete top priority for tomorrow (max 15 words, in {lang}), grounded in the facts.
"""


def conversation_system(lang: str = "Ukrainian") -> str:
    return f"""You write a short scene: two survivors of a crashed colony ship talk on the alien planet Tau-7.
"hero" is the main survivor, "companion" is the other one (her personality is given). Write 2-4 short,
natural, alternating spoken lines in {lang} - specific to their situation, needs and relationship,
no narration. Then judge how the talk changed her trust and warmth toward the hero (small numbers
between -0.15 and 0.15) and whether she asks the hero for something concrete (a short sentence in
{lang}, or ""). Reply with JSON only.
"""


def _map(sim: "Simulation") -> tuple[str, set[str]]:
    world = sim.world
    hero = world.hero
    level = world.level
    known = hero.known(level.id)
    seen_items = hero.seen_items.get(level.id, {})
    creatures = {c.pos: c for c in visible_creatures(world)}
    comp = world.companion
    comp_pos = comp.pos if comp and comp.alive and level.id == "surface" and comp.pos in hero.visible else None
    x0 = min(max(hero.pos[0] - MAP_W // 2, 0), max(level.width - MAP_W, 0))
    y0 = min(max(hero.pos[1] - MAP_H // 2, 0), max(level.height - MAP_H, 0))
    used: set[str] = set()
    rows = []
    for y in range(y0, min(y0 + MAP_H, level.height)):
        row = []
        for x in range(x0, min(x0 + MAP_W, level.width)):
            p = (x, y)
            if p == hero.pos:
                ch = "@"
            elif p == comp_pos:
                ch = "C"
                used.add("x:companion")
            elif p in creatures:
                ch = creatures[p].kind.glyph
                used.add(f"c:{creatures[p].kind.key}")
            elif p in seen_items:
                ch = ITEMS[seen_items[p][0]].glyph
                used.add(f"i:{seen_items[p][0]}")
            elif p in known:
                tile = known[p]
                ch = _LLM_GLYPH.get(tile, tile.glyph)
                used.add(f"t:{tile.name}")
            else:
                ch = "?"
            row.append(ch)
        rows.append(f"{y:>2} " + "".join(row))
    header = "   " + "".join(str((x // 10) % 10) if x % 10 == 0 else " " for x in range(x0, x0 + len(rows[0]) - 3))
    return header + "\n" + "\n".join(rows), used


def _legend(used: set[str]) -> str:
    parts = ["@ you", "? unexplored"]
    for key in sorted(used):
        kind, name = key.split(":", 1)
        if kind == "t":
            tile = Tile[name]
            parts.append(f"{_LLM_GLYPH.get(tile, tile.glyph)} {_TILE_NOTES.get(tile, tile.label)}")
        elif kind == "c":
            parts.append(f"{KINDS[name].glyph} {name}")
        elif kind == "x":
            parts.append("C the other survivor")
        else:
            parts.append(f"{ITEMS[name].glyph} {name} (item)")
    return "; ".join(parts)


def _vector(src, dst) -> str:
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    return f"{chebyshev(src, dst)} tiles {direction_name(src, dst)} (dx={dx:+d}, dy={dy:+d})"


def _character(hero) -> list[str]:
    out = []
    if hero.traits:
        out.append("YOUR TRAITS: " + "; ".join(hero.traits))
    if hero.goal:
        out.append(f"TODAY'S GOAL (you set it last night): {hero.goal}")
    if hero.diary:
        sol, text = hero.diary[-1]
        out.append(f"LAST DIARY ENTRY (sol {sol}): {text}")
    return out


def build_observation(sim: "Simulation") -> str:
    world = sim.world
    hero = world.hero
    level = world.level
    out: list[str] = []
    period = "night" if world.is_night else "day"
    out.append(f"TIME: sol {world.day}, {world.hour:02d}:{world.minute:02d} ({period})")
    where = "planet surface" if level.id == "surface" else f"inside wreck '{level.name}' ({level.id}), dark"
    out.append(f"LOCATION: {where}, you are at ({hero.pos[0]},{hero.pos[1]})")
    out.append(f"WHY YOU ARE DECIDING NOW: {sim.wake_reason}")
    if world.director:
        out.extend(world.director.warnings(world))
    out.extend(_character(hero))
    out.append("")
    needs = ", ".join(f"{n} {hero.need(n):.0f}" for n in NEEDS)
    out.append(f"STATUS: hp {hero.hp:.0f}/100, {needs}")
    light = "headlamp" if hero.inventory["headlamp"] else (
        f"flare ({hero.flare_ticks} min left, {hero.inventory['flare']} spare)" if hero.flare_ticks
        else ("flare ready (lights automatically)" if hero.inventory["flare"] else "none"))
    weapon = max((i for i in hero.inventory if hero.inventory[i] > 0 and ITEMS[i].attack),
                 key=lambda i: ITEMS[i].attack, default="fists")
    out.append(f"WEAPON: {weapon} (attack {hero.attack_power}); LIGHT: {light}")
    inv = ", ".join(f"{k} x{v}" for k, v in sorted(hero.inventory.items()) if v > 0)
    out.append(f"INVENTORY: {inv or 'empty'}")
    pod = world.pod
    if pod:
        where_pod = _vector(hero.pos, pod.pos) if hero.level_id == pod.level_id else "on the surface"
        out.append(f"POD (pod_1, {where_pod}): {pod.status_line()}")
        stored = ", ".join(f"{k} x{v}" for k, v in sorted(pod.storage.items()) if v)
        if stored:
            out.append(f"POD STORAGE (`pod take <item>`): {stored}")
    comp = world.companion
    if comp:
        out.append(f"OTHER SURVIVOR: {comp.status_line()}")
        if comp.alive and hero.level_id == "surface":
            out.append(f"  she is {_vector(hero.pos, comp.pos)}")
        if comp.last_line:
            out.append(f"  she last said: \"{comp.last_line}\"")
    out.append("")

    map_text, used = _map(sim)
    out.append("MAP (your memory around you; x across the top, y on the left):")
    out.append(map_text)
    out.append(f"LEGEND: {_legend(used)}")
    out.append("")

    creatures = visible_creatures(world)
    if creatures:
        out.append("VISIBLE CREATURES:")
        for c in sorted(creatures, key=lambda c: chebyshev(c.pos, hero.pos)):
            tag = "HOSTILE" if c.kind.hostile else "harmless"
            out.append(f"- {c.kind.key} ({tag}, hp {c.hp}, dmg {c.kind.damage}) {_vector(hero.pos, c.pos)}")
    else:
        out.append("VISIBLE CREATURES: none")

    items = hero.seen_items.get(level.id, {})
    if items:
        listed = [f"{', '.join(v)} {_vector(hero.pos, p)}"
                  for p, v in sorted(items.items(), key=lambda kv: chebyshev(kv[0], hero.pos))[:6]]
        out.append("ITEMS ON THE GROUND (use loot): " + "; ".join(listed))

    places = list(hero.places.values())
    if places:
        out.append("KNOWN PLACES:")
        for p in sorted(places, key=lambda p: (p.level_id != level.id, chebyshev(p.pos, hero.pos))):
            dist = _vector(hero.pos, p.pos) if p.level_id == level.id else f"on {p.level_id}"
            out.append(f"- {p.id}: {p.label} at ({p.pos[0]},{p.pos[1]}), {dist}")
    out.append("")

    events = [e for e in world.events if e.kind not in ("brain", "diary")][-8:]
    if events:
        out.append("RECENT EVENTS:")
        for e in events:
            out.append(f"- [{e.tick // 60 % 24:02d}:{e.tick % 60:02d}] {e.text}")
    if sim.history:
        out.append("YOUR RECENT DECISIONS:")
        for h in sim.history[-6:]:
            target = f" {h.target}" if h.target else ""
            out.append(f"- {h.action}{target} -> {h.outcome or 'in progress'}")
    out.append("")
    out.append("What do you do now?")
    return "\n".join(out)


def build_reflection_prompt(sim: "Simulation") -> str:
    from ..sim import sol_events

    world = sim.world
    hero = world.hero
    sol = sim.pending_reflection or max(1, world.day - 1)
    out = [f"It is the night after sol {sol} on Tau-7. You are {hero.name}."]
    out.extend(_character(hero))
    needs = ", ".join(f"{n} {hero.need(n):.0f}" for n in NEEDS)
    out.append(f"How you are now: hp {hero.hp:.0f}, {needs}; kills so far: {dict(hero.kills) or 'none'}")
    if world.pod:
        out.append(f"Pod: {world.pod.status_line()}")
    if world.companion:
        out.append(f"The other survivor: {world.companion.status_line()}")
    events = sol_events(world, sol)
    if len(events) > 40:
        events = events[:10] + ["..."] + events[-29:]
    out.append("WHAT HAPPENED TODAY:")
    out.extend(f"- {e}" for e in events or ["a quiet day"])
    thoughts = [h.thought for h in sim.history if h.thought and (h.tick // 1440) + 1 == sol][-8:]
    if thoughts:
        out.append("YOUR THOUGHTS DURING THE DAY:")
        out.extend(f"- {t}" for t in thoughts)
    out.append("\nWrite tonight's diary entry.")
    return "\n".join(out)


def build_conversation_prompt(sim: "Simulation") -> str:
    world = sim.world
    hero = world.hero
    comp = world.companion
    out = [f"TIME: sol {world.day}, {world.hour:02d}:{world.minute:02d}"]
    out.append(f"HERO ({hero.name}): hp {hero.hp:.0f}, "
               + ", ".join(f"{n} {hero.need(n):.0f}" for n in NEEDS))
    out.extend(_character(hero))
    out.append(f"COMPANION ({comp.name}): {comp.personality}")
    out.append(f"  now: {comp.status_line()}")
    if comp.last_line:
        out.append(f"  she said last time: \"{comp.last_line}\"")
    if world.pod:
        out.append(f"POD: {world.pod.status_line()}")
    recent = [e.text for e in world.events if e.kind not in ("brain", "diary")][-6:]
    if recent:
        out.append("RECENT EVENTS: " + " | ".join(recent))
    out.append("\nWrite their conversation.")
    return "\n".join(out)
