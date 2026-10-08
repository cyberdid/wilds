"""Turn the Mulgore simulation into text for a model: the per-decision observation and
the nightly diary reflection. Mirrors the other chapters' observe modules.

The hero is a young tauren living in Mulgore. Conversations (accepting and handing in
quests) are resolved deterministically inside the Talk action, so - unlike the city
chapter - the brain is only ever asked to decide and to reflect, never to converse."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..brain.observe import repeated_rejections
from ..world import direction_name
from .actions import ACTION_HELP
from .sim import GOAL_LEVEL, SIGHT, cheb

if TYPE_CHECKING:
    from .sim import ZoneSim

_LANDMARK_SHOWN = 10
_HOSTILES_SHOWN = 6


def system_prompt(lang: str = "Ukrainian") -> str:
    actions = "\n".join(
        f"- {name}" + (f" <{target}>" if target else "") + f": {desc}"
        for name, (target, desc) in ACTION_HELP.items()
    )
    return f"""You are the mind of a young tauren starting life on the plains of Mulgore, the Horde's
homeland. Nobody controls you: you choose what to do with your days here. The honourable path
is to take on tasks (quests) from your people, earn your place and grow stronger, until you are
ready to leave for the wider world (reaching level {GOAL_LEVEL} ends this chapter).

HOW MULGORE WORKS
- Mulgore is a huge open prairie at real scale (a tile is 2 yards); travelling takes real time,
  so prefer purposeful actions over wandering.
- Your people (NPCs) at the camps - Camp Narache, Bloodhoof Village, Thunder Bluff, Camp Sungraze -
  offer tasks. `talk` to one to accept the quests they have for you and to hand in finished ones.
- A quest asks you to kill a number of creatures (`hunt`) or to collect something in an area
  (`search`). Finish its objectives, then `talk` to the NPC who takes it in for experience.
- The plains hold beasts and hostile creatures. `hunt` the ones near your own level to grow;
  flee or rest if one is far above you or you are badly hurt. Resting (`rest`) heals you.
- `go_to` a place you know by name; `explore` walks to the nearest landmark you have not seen.

ACTIONS (you choose one; it runs for many ticks until it finishes or something interrupts it,
then you are asked again):
{actions}

Reply with JSON only: "thought" (1-2 short sentences in {lang}, first person, your honest
feeling or reasoning - your traits and goal should colour it), "action" and "target"
(empty string if the action takes none).
"""


def reflection_system(lang: str = "Ukrainian") -> str:
    return f"""You are the inner voice of a young tauren in Mulgore, writing a short diary at the
end of a stretch of days. Be honest and concrete about what happened (use the events given), how
it felt, what you hope for. Stay consistent with your traits, but let what happened change you.
Reply with JSON only:
- "diary": first person, in {lang}, 40-90 words, vivid but plain, no lists;
- "trait": one NEW trait or habit formed (max 6 words, in {lang}), or "" if none;
- "goal": your concrete top priority next (max 15 words, in {lang}).
"""


def _vec(src, dst) -> str:
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    return f"{cheb(src, dst)} tiles {direction_name(src, dst)} (dx={dx:+d}, dy={dy:+d})"


def _quest_lines(sim: "ZoneSim") -> list[str]:
    out: list[str] = []
    for aq in sim.hero.active.values():
        q = aq.quest
        if aq.ready:
            out.append(f"- READY «{q.title}»: finished, hand in to {q.turn_in.title()} (`talk {q.turn_in.title()}`)")
            continue
        if aq.objectives:
            objs = "; ".join(f"{o.kind} {o.target} {o.done}/{o.count}" for o in aq.objectives)
        else:
            objs = f"go to {q.area.title()} and report" if q.area else f"report to {q.turn_in.title()}"
        area = f" [area: {q.area.title()}]" if q.area else ""
        out.append(f"- «{q.title}»: {objs}{area}")
    return out


def build_observation(sim: "ZoneSim") -> str:
    w, hero = sim.world, sim.hero
    here = hero.pos
    out: list[str] = []
    out.append(f"TIME: {w.clock()}")
    out.append(f"LOCATION: Mulgore at ({here[0]},{here[1]})")
    out.append(f"WHY YOU ARE DECIDING NOW: {sim.wake_reason}")
    if hero.traits:
        out.append("YOUR TRAITS: " + "; ".join(hero.traits))
    if hero.goal:
        out.append(f"YOUR GOAL (set earlier; may be done or out of date - trust STATUS over it): {hero.goal}")
    out.append("")
    out.append(f"STATUS: level {hero.level}/{GOAL_LEVEL}; hp {hero.hp:.0f}/{hero.max_hp:.0f}; "
              f"attack {hero.attack}; xp {hero.xp}/{hero.xp_to_next()}; "
              f"quests done {len(hero.done)}; kills {sum(hero.kills.values())}")
    out.append("")

    attackers = sim.attackers()
    if attackers:
        out.append("FIGHTING YOU RIGHT NOW:")
        for c in attackers:
            out.append(f"- {c.title} (level {c.level}, hp {c.hp}/{c.max_hp}) {_vec(here, c.pos)}")
    hostiles = [c for c in sim.visible_hostiles() if c not in attackers][:_HOSTILES_SHOWN]
    if hostiles:
        out.append(f"HOSTILES IN SIGHT (within {SIGHT} tiles):")
        for c in hostiles:
            note = "stronger than you" if c.level > hero.level + 2 else "your level" if c.level >= hero.level - 2 \
                else "weaker"
            out.append(f"- {c.title} (level {c.level}, {note}) {_vec(here, c.pos)}")
    if not attackers and not hostiles:
        out.append("No hostiles in sight.")
    out.append("")

    quest_lines = _quest_lines(sim)
    if quest_lines:
        out.append("YOUR QUESTS:")
        out.extend(quest_lines)
    givers = sorted({qu.giver for qu in sim.quests if sim.available_from(qu.giver)},
                    key=lambda g: cheb(here, sim.places[g].pos) if g in sim.places else 10 ** 9)
    if givers:
        out.append("NPCs WHO HAVE A NEW TASK FOR YOU:")
        for g in givers[:6]:
            p = sim.places.get(g)
            if p:
                out.append(f"- {p.title} {_vec(here, p.pos)}")
    out.append("")

    landmarks = sorted(sim.landmarks(), key=lambda p: cheb(here, p.pos))[:_LANDMARK_SHOWN]
    if landmarks:
        out.append("KNOWN PLACES (use the name with go_to / search):")
        for p in landmarks:
            seen = "" if p.title.lower() in {d for d in hero.discovered} else " (not yet visited)"
            out.append(f"- {p.title} ({p.kind}){seen} {_vec(here, p.pos)}")
    out.append("")

    events = [e for e in w.events if e.kind not in ("brain",)][-8:]
    if events:
        out.append("RECENT EVENTS:")
        for e in events:
            out.append(f"- {e.text}")
    if sim.history:
        out.append("YOUR RECENT DECISIONS:")
        for h in sim.history[-6:]:
            target = f" {h.target}" if h.target else ""
            out.append(f"- {h.action}{target} -> {h.outcome or 'in progress'}")
    out.extend(repeated_rejections(sim.history))
    out.append("")
    out.append("What do you do now?")
    return "\n".join(out)


def build_reflection_prompt(sim: "ZoneSim") -> str:
    w, hero = sim.world, sim.hero
    out = [f"It is a quiet moment in Mulgore ({w.clock()}). You are {hero.name}, a tauren of level "
           f"{hero.level}."]
    if hero.traits:
        out.append("YOUR TRAITS: " + "; ".join(hero.traits))
    if hero.goal:
        out.append(f"YOUR GOAL WAS: {hero.goal}")
    out.append(f"How you are now: level {hero.level}, hp {hero.hp:.0f}/{hero.max_hp:.0f}, "
              f"quests done {len(hero.done)}, kills {sum(hero.kills.values())}")
    events = [e.text for e in w.events if e.kind in ("good", "event", "victory", "death")][-16:]
    out.append("WHAT HAPPENED LATELY:")
    out.extend(f"- {e}" for e in (events or ["the plains were quiet"]))
    thoughts = [h.thought for h in sim.history if h.thought][-6:]
    if thoughts:
        out.append("YOUR RECENT THOUGHTS:")
        out.extend(f"- {t}" for t in thoughts)
    out.append("\nWrite your diary entry now.")
    return "\n".join(out)
