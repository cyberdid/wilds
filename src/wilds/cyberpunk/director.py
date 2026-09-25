"""A minimal storyteller for the cyberpunk chapter.

Unlike Tau-7's Director-7 this city has no wildlife or weather to schedule -
the "story" here is the hero's own choices. Its only job is to notice when
those choices have flatlined (the same Shannon-entropy action-diversity
signal Tau-7 tracks in wilds.metrics.Metrics) and nudge the hero out of a
safe grinding loop with an ambient, in-fiction prod, rather than silently
letting a spectator watch the same three actions forever. It deliberately
does not duplicate the heat/collector/hostility mechanics - those already
give this chapter real stakes; this only watches for boredom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .world import CityWorld

LOW_ENTROPY = 0.35
CALM_TICKS_BEFORE_NUDGE = 3 * 24 * 60  # a low-diversity stretch of ~3 in-game days
NUDGE_COOLDOWN = 2 * 24 * 60

NUDGES = [
    "Хтось у провулку довго дивиться на тебе, перш ніж зникнути в натовпі.",
    "Знайомий голос у натовпі кличе інше ім'я - але озирається саме на тебе.",
    "На стіні свіжий графіті-теґ із твоїм вуличним прізвиськом.",
    "Фіксер по коротких хвилях згадує, що про тебе питали чужі.",
]


@dataclass
class CyberDirector:
    tension: float = 0.0
    alerts: list[str] = field(default_factory=list)
    _low_streak: int = 0
    _last_nudge: int = -10_000

    def update(self, world: "CityWorld", entropy: float) -> None:
        self.alerts = []
        hero = world.hero
        debt_ratio = min(1.0, hero.debt / 5000) if hero.debt > 0 else 0.0
        novelty = 1 - entropy
        self.tension = (0.35 * (1 - hero.hp / 100) + 0.25 * debt_ratio
                        + 0.2 * (world.level.heat / 100) + 0.2 * novelty)

        self._low_streak = self._low_streak + 1 if entropy < LOW_ENTROPY else 0
        if (self._low_streak >= CALM_TICKS_BEFORE_NUDGE
                and world.tick - self._last_nudge >= NUDGE_COOLDOWN):
            text = world.rng.choice(NUDGES)
            world.log(text, "event")
            self.alerts.append(f"something odd just happened: {text}")
            self._last_nudge = world.tick
            self._low_streak = 0
