"""Quests of a zone, read from the content pack.

The wiki gives each quest as free text plus a box (giver, level, XP, previous/next). The
objectives are bullet lines: ``- <mob> slain (N)`` is a kill, ``- <item> (N)`` something to
collect. Anything else (talk to, deliver, escort) is treated as "go there and report back".
Quests the game cannot yet play (no placed giver, other faction) are left out, not faked.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from typing import Any

from . import content

_KILL = re.compile(r"^- (.+?)\s+slain\s*\((\d+)\)", re.M | re.I)
_COLLECT = re.compile(r"^- (.+?)\s*\((\d+)\)\s*$", re.M)
_NUM = re.compile(r"\d+")


def clean(name: str) -> str:
    """NPC / mob title without the disambiguation in brackets, lower-cased."""
    return re.sub(r"\s*\(.*", "", name).strip().lower()


@dataclass
class Objective:
    kind: str       # kill | collect
    target: str     # lower-cased mob or item name
    count: int
    done: int = 0

    @property
    def complete(self) -> bool:
        return self.done >= self.count


@dataclass
class Quest:
    id: str
    title: str
    level: int
    req_level: int
    giver: str        # lower-cased NPC title
    turn_in: str      # lower-cased NPC title (the giver unless the box names an end)
    xp: int
    rewards: str
    previous: list[str] = field(default_factory=list)   # quest titles, lower-cased
    objectives: list[Objective] = field(default_factory=list)
    area: str = ""    # subzone the text sends you to, lower-cased
    brief: str = ""
    text: str = ""

    @property
    def errand(self) -> bool:
        """No counted objective: go to the area (or the turn-in NPC) and report back."""
        return not self.objectives

    @property
    def kills(self) -> list[Objective]:
        return [o for o in self.objectives if o.kind == "kill"]


def _int(text: str, default: int) -> int:
    m = _NUM.search(text or "")
    return int(m.group()) if m else default


def parse_quest(rec: dict[str, Any], subzones: set[str]) -> Quest:
    info = rec["info"]
    objectives_text = rec["sections"].get("Objectives", "")
    objectives = [Objective("kill", clean(m.group(1)), int(m.group(2))) for m in _KILL.finditer(objectives_text)]
    killed = {o.target for o in objectives}
    objectives += [Objective("collect", m.group(1).strip().lower(), int(m.group(2)))
                   for m in _COLLECT.finditer(objectives_text)
                   if "slain" not in m.group(1).lower() and clean(m.group(1)) not in killed]
    level = _int(info.get("level", ""), 1)
    area = next((clean(link) for link in rec["links"] if clean(link) in subzones), "")
    text = "\n\n".join(v for k, v in rec["sections"].items() if k in ("Description", "Progress", "Completion"))
    first = objectives_text.strip().split("\n")[0] if objectives_text.strip() else ""
    return Quest(
        id=rec["id"], title=rec["title"], level=level, req_level=_int(info.get("levelreq", ""), max(1, level - 2)),
        giver=clean(info.get("start", "")), turn_in=clean(info.get("end", "") or info.get("start", "")),
        xp=_int(info.get("experience", "").replace(",", ""), 40 * level),
        rewards=info.get("rewards", ""),
        previous=[clean(p) for p in re.split(r"[,\n]| and ", info.get("previous", "")) if p.strip()],
        objectives=objectives, area=area, brief=first, text=text)


def load_quests(pack, npc_titles: set[str], mob_titles: set[str], subzones: set[str]) -> list[Quest]:
    """Every Horde/neutral quest whose giver is in the world and whose kill targets exist."""
    out = []
    for rec in content.load(pack, "quest"):
        if rec["removed"] or rec["info"].get("faction", "Horde") not in ("Horde", "Both", ""):
            continue
        q = parse_quest(rec, subzones)
        if q.giver not in npc_titles or q.turn_in not in npc_titles:
            continue
        if any(o.target not in mob_titles for o in q.kills):
            continue
        if not (q.objectives or q.turn_in != q.giver or q.area):
            continue  # nothing the game could ask the hero to do
        out.append(q)
    return out


@functools.lru_cache(maxsize=8)
def _refs(pack_key: str) -> frozenset[str]:
    refs: set[str] = set()
    for rec in content.load(pack_key, "quest"):
        if rec["removed"] or rec["info"].get("faction", "Horde") not in ("Horde", "Both", ""):
            continue
        for key in ("start", "end"):
            if rec["info"].get(key):
                refs.add(clean(rec["info"][key]))
        refs.update(clean(m.group(1)) for m in _KILL.finditer(rec["sections"].get("Objectives", "")))
    return frozenset(refs)


def quest_refs(pack) -> frozenset[str]:
    """Cleaned titles of every giver, turn-in NPC and kill target of a live Horde/neutral quest,
    including ones the wiki marks as removed (classic quests still send you to them)."""
    return _refs(str(pack))
