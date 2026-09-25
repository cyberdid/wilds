"""Stage 5: factions. Reputation is hero-side (-1..1 per faction) and modulates
outcomes live - prices, mostly - rather than being baked into NPCs at worldgen
time, since NPCs exist before the hero has done anything to earn a reputation.

Every positive conversation nudges reputation with the NPC's faction (reusing
the trust/affinity delta the conversation already produced, so no new LLM
field is needed); completing a contract and trading nudge it a little too.
"""

from __future__ import annotations

FACTION_BY_ROLE: dict[str, str] = {
    "fixer": "fixers",
    "vendor": "vendors",
    "doc": "vendors",
    "ganger": "gangs",
}
FACTION_NAMES = {"fixers": "фіксери", "vendors": "торговці", "gangs": "банди"}
PRICE_DISCOUNT_PER_REP = 0.15  # at +1.0 reputation, buy prices drop ~15%


def faction_of(role: str) -> str | None:
    return FACTION_BY_ROLE.get(role)


def adjust(reputation: dict[str, float], faction: str | None, delta: float) -> None:
    if not faction or delta == 0:
        return
    reputation[faction] = max(-1.0, min(1.0, reputation.get(faction, 0.0) + delta))


def price_multiplier(reputation: dict[str, float], faction: str | None) -> float:
    if not faction:
        return 1.0
    return max(0.7, 1.0 - reputation.get(faction, 0.0) * PRICE_DISCOUNT_PER_REP)
