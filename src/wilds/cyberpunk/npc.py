"""NPCs the hero can talk to and trade with: fixers, vendors, gangers, street doctors."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from ..world import Pos
from .items import ITEMS
from .race import Race

# Roles shape how an NPC talks and what they sell; a fixer never stocks goods,
# a vendor always does.
ROLES = ("fixer", "vendor", "doc", "ganger", "civilian", "collector")

STOCK_BY_ROLE: dict[str, tuple[str, ...]] = {
    "fixer": (),
    "vendor": ("synth_noodles", "stim_patch", "burner_deck", "pistol", "armor_jacket", "trinket"),
    "doc": ("stim_patch", "cyber_eye", "cyber_arm", "dermal_plating",
           "cyber_eye_alpha", "cyber_arm_alpha", "dermal_plating_alpha"),
    "ganger": ("trinket", "pistol"),
    "civilian": (),
    "collector": (),
}
FIRST_NAMES = ["Джекі", "Ноа", "Рейн", "Кайто", "Соль", "Мірра", "Дікс", "Юна", "Гейл", "Тор"]
LAST_NAMES = ["Вейл", "Стрім", "Круз", "Оно", "Блек", "Іскра", "Ронін", "Найт", "Фокс", "Реле"]
PERSONALITIES = {
    "fixer": "обережний посередник, знає всіх і не довіряє нікому одразу",
    "vendor": "прагматична крамарка, торгується жорстко, але поважає постійних клієнтів",
    "doc": "тіньовий вуличний лікар-хірург, цинічний гумор, байдужий до законів",
    "ganger": "член вуличної банди, territorial, цінує повагу й силу більше за гроші",
    "civilian": "звичайний мешканець Насипу, обережний із незнайомцями",
    "collector": "холоднокровний вибивач боргів корпорації, byte-the-bullet professional",
}

# stage: fixer cooldown - a fixer who ran too many jobs in a row goes quiet for a
# while (an in-fiction reason, not an invisible reward-decay formula)
JOBS_BEFORE_COOLDOWN = 3
FIXER_COOLDOWN_MINUTES = 4 * 60


@dataclass
class NPC:
    id: str
    name: str
    race: Race
    role: str
    pos: Pos
    personality: str
    trust: float = 0.4
    affinity: float = 0.4
    stock: Counter[str] = field(default_factory=Counter)
    prices: dict[str, int] = field(default_factory=dict)
    last_talk: int = -10_000
    last_line: str = ""
    request: str = ""
    hostile: bool = False  # a collector, or a ganger the hero has burned too badly
    last_hit: int = -10_000  # tick of the last ambient ambush/collection hit, for a cooldown
    jobs_streak: int = 0  # consecutive contracts run for this fixer since their last cooldown
    cooldown_until: int = 0  # tick before which this fixer has no work (stage: fixer cooldown)

    def adjust(self, trust: float = 0.0, affinity: float = 0.0) -> None:
        self.trust = min(1.0, max(0.0, self.trust + trust))
        self.affinity = min(1.0, max(0.0, self.affinity + affinity))

    def sells(self) -> bool:
        return bool(self.stock)

    def price_for(self, item: str, selling: bool) -> int:
        base = self.prices.get(item, ITEMS[item].price)
        return max(1, round(base * (0.5 if selling else 1.0)))

    def status_line(self) -> str:
        mood = "friendly" if self.affinity > 0.65 else "wary" if self.trust < 0.3 else "neutral"
        text = (f"{self.name} ({self.race.label}, {self.role}) at ({self.pos[0]},{self.pos[1]}); "
                f"trust {self.trust:.2f}, affinity {self.affinity:.2f} ({mood})")
        if self.stock:
            # item key first: `trade` takes this key, not the Ukrainian display name
            goods = ", ".join(f"{i} ({ITEMS[i].name}) {self.price_for(i, False)}¥" for i in self.stock)
            text += f"; sells: {goods}"
        if self.request:
            text += f"; asked you: \"{self.request}\""
        return text


def spawn_npc(npc_id: str, role: str, pos: Pos, rng) -> NPC:
    race = rng.choice(list(Race))
    name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
    npc = NPC(npc_id, name, race, role, pos, PERSONALITIES[role])
    for item in STOCK_BY_ROLE[role]:
        npc.stock[item] = rng.randint(1, 3) if not ITEMS[item].cyberware else 1
    if race.trust_bonus:
        npc.adjust(trust=race.trust_bonus)
    return npc
