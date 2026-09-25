"""The five metatypes (races), lightly adapted from Shadowrun for flavour and
small mechanical nudges - not a full tabletop stat block.

See docs/research/shadowrun-reference.md for the source material.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import random


@dataclass(frozen=True)
class RaceInfo:
    label: str  # Ukrainian display name
    note: str  # short English note for the LLM prompt
    trust_bonus: float = 0.0  # starting corp/NPC trust nudge
    intimidation: float = 0.0  # bonus in tense talk/trade scenes
    sinless_chance: float = 0.15  # chance to start without a corporate SIN


class Race(Enum):
    HUMAN = RaceInfo("людина", "baseline metatype, no particular edge or drawback", sinless_chance=0.10)
    ELF = RaceInfo("ельф", "agile, charismatic, low-light vision", trust_bonus=0.05, sinless_chance=0.10)
    DWARF = RaceInfo("гном", "hardy, strong-willed, thermographic vision, resists disease",
                     sinless_chance=0.15)
    ORK = RaceInfo("орк", "physically tough, less conventionally charismatic, often SINless",
                   intimidation=0.10, trust_bonus=-0.05, sinless_chance=0.35)
    TROLL = RaceInfo("троль", "huge, intimidating, often SINless, low-light vision",
                     intimidation=0.20, trust_bonus=-0.08, sinless_chance=0.40)

    @property
    def label(self) -> str:
        return self.value.label

    @property
    def note(self) -> str:
        return self.value.note

    @property
    def trust_bonus(self) -> float:
        return self.value.trust_bonus

    @property
    def intimidation(self) -> float:
        return self.value.intimidation

    def roll_sinless(self, rng: random.Random) -> bool:
        return rng.random() < self.value.sinless_chance


def random_race(rng: random.Random) -> Race:
    return rng.choice(list(Race))
