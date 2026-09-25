"""Stage: district heat & "fail forward" resolution.

A risky act (turning in a courier job, buying cyberware) never just succeeds
or fails silently: it resolves as a full success, a "fail forward" (you get
the outcome but it costs you hp), or a critical failure - so `CyberHero.hp`
finally has something that can spend it, and heat gives every district a
legible, telegraphed sense of "how hot is this place for me right now"
instead of an invisible dice roll the LLM has no way to reason about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .world import CityLevel

HEAT_MAX = 100.0
# tuned against actual contract cadence (a round trip is often well under two
# hours on these district maps): fast enough that a fixer's own cooldown
# (see npc.FIXER_COOLDOWN_MINUTES) meaningfully cools things back down, slow
# enough that back-to-back jobs with no break at all still creep upward
HEAT_DECAY_PER_TICK = 0.1  # 6/hour at the baseline decay rate
CONTRACT_HEAT_GAIN = 12.0
CYBERWARE_HEAT_GAIN = 8.0
PARTIAL_BAND = 0.25  # width of the "fail forward" band above the success line


def success_probability(heat: float, rep_fixers: float, armored: bool) -> float:
    p = 0.85 - 0.006 * heat + 0.15 * rep_fixers + (0.05 if armored else 0.0)
    return max(0.15, min(0.95, p))


def roll_outcome(rng, p_success: float) -> str:
    """"success" | "partial" (fail forward) | "critical"."""
    x = rng.random()
    if x <= p_success:
        return "success"
    if x <= p_success + PARTIAL_BAND:
        return "partial"
    return "critical"


def _modifiers(level_id: str) -> dict:
    from .worldgen import DISTRICT_MODIFIERS

    return DISTRICT_MODIFIERS.get(level_id, {})


def add_heat(level: "CityLevel", amount: float) -> None:
    mult = _modifiers(level.id).get("heat_gain_mult", 1.0)
    level.heat = min(HEAT_MAX, level.heat + amount * mult)


def decay_heat(level: "CityLevel") -> None:
    mult = _modifiers(level.id).get("heat_decay_mult", 1.0)
    level.heat = max(0.0, level.heat - HEAT_DECAY_PER_TICK * mult)


def price_multiplier_for_district(level_id: str) -> float:
    return _modifiers(level_id).get("price_mult", 1.0)


def move_cost_for_district(level_id: str) -> int:
    return _modifiers(level_id).get("move_cost", 1)
