"""Turn the cyberpunk simulation state into text for the LLM: the per-action
observation, the nightly diary reflection, and a conversation with an NPC."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..world import chebyshev, direction_name
from .actions import ACTION_HELP
from .hero import MAX_ESSENCE
from .tiles import CTile
from .factions import FACTION_NAMES
from .worldgen import DISTRICTS, OFFWORLD

_DISTRICT_NAMES = dict(DISTRICTS)
_OFFWORLD_NAMES = {d: n for d, n, _ in OFFWORLD}

if TYPE_CHECKING:
    from .npc import NPC
    from .sim import CitySim

MAP_W, MAP_H = 25, 13
_TILE_NOTES = {
    CTile.SIDEWALK: "sidewalk (walkable)",
    CTile.ROAD: "road (walkable)",
    CTile.NEON: "neon-lit pavement (walkable)",
    CTile.ALLEY: "narrow alley",
    CTile.WALL: "building wall (impassable)",
    CTile.DOOR: "doorway",
    CTile.SHOP: "storefront (an NPC vendor may be here)",
    CTile.BAR: "bar / safehouse",
    CTile.FIXER: "fixer's office",
    CTile.CHECKPOINT: "corp checkpoint",
    CTile.FENCE: "chain-link fence (impassable)",
    CTile.TRASH: "junk on the ground",
}


def system_prompt(lang: str = "Ukrainian") -> str:
    actions = "\n".join(
        f"- {name}" + (f" <{target}>" if target else "") + f": {desc}"
        for name, (target, desc) in ACTION_HELP.items()
    )
    return f"""You are the mind of a runner starting out in the Sprawl, one district of a nameless cyberpunk
megacity. A corporation "rescued" your escape pod from the planet Tau-7 and now you owe them
a large debt (see STATUS below) - work it off however you can: trade, favors, whatever the
street offers. Nobody controls you: you decide what to do with your life here.

HOW THIS CITY WORKS
- Money is nuyen (¥). Trading, not violence, is how this stage of your life works.
- Essence (0-{MAX_ESSENCE:.0f}) drops when you install cyberware bought from a street doc; low essence is a
  real cost, not just flavor - think before augmenting. Alphaware grade (item id ends in "_alpha")
  costs about 3x the nuyen but only half the essence of the same basic part.
- NPCs remember you: trust and affinity move with what you do, and a good relationship means
  better prices and more information. A hostile one may refuse to deal with you at all.
- Paying off your debt in full (`pay_debt`) ends this chapter successfully: you're free.
- The fixer hands out courier jobs (`request_job`): pick up a package at a dead-drop, bring it back
  (`complete_job`) for nuyen. Only one job at a time; this is your main income while contracts are
  the only paid work available.
- The city has several districts (`travel` between them costs nuyen and time). Each fixer only
  knows about jobs in their own district, so you must be physically there to request or turn one in.
  Districts differ: some are slower to cross on foot, some tax purchases, some run hotter or
  cooler (see HEAT below).
- Every district has HEAT (0-100, shown in STATUS): completing a job or installing cyberware there
  raises it, and it cools on its own over time. High heat makes `complete_job` riskier - it can
  still resolve as a clean success, but may instead become a "fail forward" (you still get paid but
  take a beating) or a critical failure (no pay, a heavy hit). A fixer who hands you 3 jobs in a row
  also goes quiet for a few hours - too many jobs draws attention. Pace yourself, or heal up with
  `use stim_patch` (+30 hp) when hurt.
- You owe periodic debt installments, not just the total: miss one and the corp is delinquent -
  it sends a "collector" who will hurt you near your home turf until you pay something toward the
  debt again. Missing daily rent/upkeep adds the shortfall straight onto your debt instead.
- You have a ship. `launch` flies it to a place beyond the city (an orbital station, a frontier
  outpost) - costs fuel instead of nuyen, takes longer, and rarely wears the hull or turns up a
  find. `refuel_ship` only works back in your home district.
- People belong to loose factions - fixers, vendors (incl. street docs), gangs. Helping someone
  (trading, finishing their job, a warm conversation) nudges your reputation with their faction,
  which quietly improves prices with everyone in it; hostility would do the opposite.

ACTIONS (you choose one; it runs for many ticks until done or until something interrupts it,
then you are asked again - so prefer purposeful multi-step actions):
{actions}

Reply with JSON only: "thought" (1-2 short sentences in {lang}, first person, your honest
reasoning or feeling - your traits and today's goal should colour it), "action" and "target"
(empty string if none).
"""


def reflection_system(lang: str = "Ukrainian") -> str:
    return f"""You are the inner voice of a cyberpunk runner, writing a personal diary entry at
the end of a day. Be honest and concrete about what happened (use the events given), how it felt,
what you fear and hope for. Stay consistent with your existing traits, but let today change you.
Reply with JSON only:
- "diary": first person, in {lang}, 40-90 words, vivid but plain, no lists;
- "trait": one NEW trait or habit formed today (max 6 words, in {lang}), or "" if none;
- "goal": your concrete top priority for tomorrow (max 15 words, in {lang}).
"""


def conversation_system(lang: str = "Ukrainian") -> str:
    return f"""You write a short scene: a cyberpunk runner talks to a local NPC (their
personality, race and role are given). Write 2-4 short, natural, alternating spoken lines in
{lang} - specific to their situation and relationship, no narration. "hero" speaks as the runner,
"npc" as the other person. Then judge how the talk changed the NPC's trust and warmth toward the
hero (small numbers between -0.15 and 0.15) and whether they ask the hero for something concrete
(a short sentence in {lang}, or ""). Reply with JSON only.
"""


def _heat_word(heat: float) -> str:
    if heat < 25:
        return "quiet"
    if heat < 55:
        return "warm"
    if heat < 80:
        return "hot"
    return "scorching"


def _vector(src, dst) -> str:
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    return f"{chebyshev(src, dst)} tiles {direction_name(src, dst)} (dx={dx:+d}, dy={dy:+d})"


def _map(sim: "CitySim") -> tuple[str, set[str]]:
    world = sim.world
    hero = world.hero
    level = world.level
    known = hero.known()
    npcs = {n.pos: n for n in level.npcs}
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
            elif p in npcs and p in hero.visible:
                ch = "N"
                used.add(f"n:{npcs[p].id}")
            elif p in known:
                tile = known[p]
                ch = tile.glyph
                used.add(f"t:{tile.name}")
            else:
                ch = "?"
            row.append(ch)
        rows.append(f"{y:>2} " + "".join(row))
    header = "   " + "".join(str((x // 10) % 10) if x % 10 == 0 else " " for x in range(x0, x0 + len(rows[0]) - 3))
    return header + "\n" + "\n".join(rows), used


def _legend(used: set[str], level) -> str:
    parts = ["@ you", "? unexplored"]
    for key in sorted(used):
        kind, name = key.split(":", 1)
        if kind == "t":
            tile = CTile[name]
            parts.append(f"{tile.glyph} {_TILE_NOTES.get(tile, tile.label)}")
        else:
            npc = next((n for n in level.npcs if n.id == name), None)
            if npc:
                parts.append(f"N {npc.id}: {npc.name} ({npc.role})")
    return "; ".join(parts)


def build_observation(sim: "CitySim") -> str:
    world = sim.world
    hero = world.hero
    out: list[str] = []
    out.append(f"TIME: day {world.day}, {world.hour:02d}:{world.minute:02d} "
              f"({'night' if world.is_night else 'day'})")
    out.append(f"LOCATION: district '{world.level.name}' ({hero.level_id}), you are at "
              f"({hero.pos[0]},{hero.pos[1]})")
    out.append(f"WHY YOU ARE DECIDING NOW: {sim.wake_reason}")
    if hero.traits:
        out.append("YOUR TRAITS: " + "; ".join(hero.traits))
    if hero.goal:
        out.append(f"TODAY'S GOAL: {hero.goal}")
    out.append("")
    out.append(f"STATUS: race {hero.race.label} ({hero.race.note}); hp {hero.hp:.0f}/100; "
              f"essence {hero.essence:.1f}/{MAX_ESSENCE:.0f} ({hero.essence_state}); "
              f"nuyen {hero.nuyen}¥; DEBT {hero.debt}¥; "
              f"HEAT here {world.level.heat:.0f}/100 ({_heat_word(world.level.heat)})")
    if hero.evicted:
        out.append("WARNING: missed rent last night - the shortfall was added to your debt.")
    if world.delinquent:
        out.append("WARNING: a debt installment is overdue - a collector is hunting you near home "
                  "until you pay something toward the debt.")
    if world.ship is not None:
        out.append(f"SHIP: {world.ship.status_line()}")
    if hero.reputation:
        rep = ", ".join(f"{FACTION_NAMES.get(f, f)} {v:+.2f}" for f, v in hero.reputation.items())
        out.append(f"REPUTATION: {rep}")
    if world.contract is not None and world.contract.status != "done":
        c = world.contract
        where = (f"Drop point {_vector(hero.pos, c.drop_pos)}." if c.level_id == hero.level_id
                else f"Drop point is in district '{c.level_id}'.")
        out.append(f"ACTIVE CONTRACT ({c.id}, status: {c.status}, district: {c.level_id}): {c.brief} {where}")
    elif hero.contracts_done:
        out.append(f"Contracts completed so far: {hero.contracts_done}. Ask a fixer for another.")
    inv = ", ".join(f"{k} x{v}" for k, v in sorted(hero.inventory.items()) if v > 0)
    out.append(f"INVENTORY: {inv or 'empty'}")
    out.append("")

    map_text, used = _map(sim)
    out.append("MAP (your memory around you; x across the top, y on the left):")
    out.append(map_text)
    out.append(f"LEGEND: {_legend(used, world.level)}")
    out.append("")

    visible_npcs = [n for n in world.level.npcs if n.pos in hero.visible]
    if visible_npcs:
        out.append("VISIBLE PEOPLE:")
        for n in sorted(visible_npcs, key=lambda n: chebyshev(n.pos, hero.pos)):
            out.append(f"- {n.status_line()}, {_vector(hero.pos, n.pos)}")

    places = list(hero.places.values())
    if places:
        out.append("KNOWN PLACES:")
        here = [p for p in places if p.level_id == hero.level_id]
        elsewhere = [p for p in places if p.level_id != hero.level_id]
        for p in sorted(here, key=lambda p: chebyshev(p.pos, hero.pos)):
            out.append(f"- {p.id}: {p.label} at ({p.pos[0]},{p.pos[1]}), {_vector(hero.pos, p.pos)}")
        for p in sorted(elsewhere, key=lambda p: p.level_id):
            out.append(f"- {p.id}: {p.label} in district '{p.level_id}' (use `travel {p.level_id}` to reach it)")
    known_districts = ", ".join(f"{d} ({n})" for d, n in _DISTRICT_NAMES.items())
    known_offworld = ", ".join(f"{d} ({n})" for d, n in _OFFWORLD_NAMES.items())
    out.append(f"DISTRICTS (use `travel`): {known_districts}")
    out.append(f"BEYOND THE CITY (use `launch`): {known_offworld}")
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


def build_reflection_prompt(sim: "CitySim") -> str:
    world = sim.world
    hero = world.hero
    day = sim.pending_reflection or max(1, world.day - 1)
    out = [f"It is the end of day {day} in district '{world.level.name}'. "
          f"You are {hero.name}, a {hero.race.label} runner."]
    if hero.traits:
        out.append("YOUR TRAITS: " + "; ".join(hero.traits))
    if hero.goal:
        out.append(f"TODAY'S GOAL WAS: {hero.goal}")
    out.append(f"How you are now: hp {hero.hp:.0f}, essence {hero.essence:.1f}, "
              f"nuyen {hero.nuyen}¥, debt {hero.debt}¥, heat here {world.level.heat:.0f}/100"
              + (", an overdue debt collector is after you" if world.delinquent else ""))
    events = [f"[{e.tick // 60 % 24:02d}:{e.tick % 60:02d}] {e.text}" for e in world.events
              if (e.tick // 1440) + 1 == day and e.kind not in ("brain", "diary")]
    out.append("WHAT HAPPENED TODAY:")
    out.extend(f"- {e}" for e in (events[:40] or ["a quiet day"]))
    thoughts = [h.thought for h in sim.history if h.thought and (h.tick // 1440) + 1 == day][-8:]
    if thoughts:
        out.append("YOUR THOUGHTS DURING THE DAY:")
        out.extend(f"- {t}" for t in thoughts)
    out.append("\nWrite tonight's diary entry.")
    return "\n".join(out)


def build_conversation_prompt(sim: "CitySim", npc: "NPC") -> str:
    world = sim.world
    hero = world.hero
    out = [f"TIME: day {world.day}, {world.hour:02d}:{world.minute:02d}"]
    out.append(f"HERO ({hero.name}, {hero.race.label} runner): hp {hero.hp:.0f}, "
              f"nuyen {hero.nuyen}¥, debt {hero.debt}¥")
    if hero.goal:
        out.append(f"HERO'S CURRENT GOAL: {hero.goal}")
    out.append(f"NPC: {npc.status_line()}. Personality: {npc.personality}.")
    if npc.last_line:
        out.append(f"NPC said last time: \"{npc.last_line}\"")
    recent = [e.text for e in world.events if e.kind not in ("brain", "diary")][-6:]
    if recent:
        out.append("RECENT EVENTS: " + " | ".join(recent))
    out.append("\nWrite their conversation.")
    return "\n".join(out)
