"""Cheap "watchability" metrics (no LLM): is the survivor's life interesting?

- action diversity: normalized Shannon entropy of the last 100 chosen actions
  (< 0.35 means a behavioural loop; 0.65-0.85 is lively);
- exploration: remembered surface tiles per sol;
- close calls: times hp or a need fell below 15 and then recovered above 40;
- thought novelty: share of unique word trigrams among recent thoughts.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sim import Decision
    from .world import World

DANGER = 15.0
SAFE = 40.0


class Metrics:
    def __init__(self) -> None:
        self.actions: deque[str] = deque(maxlen=100)
        self.thoughts: deque[str] = deque(maxlen=50)
        self.close_calls = 0
        self.rejections = 0
        self.conversations = 0
        self._in_danger = False
        self._explored = 0
        self._sols = 1

    def on_decision(self, decision: "Decision") -> None:
        self.actions.append(decision.action)
        if decision.thought:
            self.thoughts.append(decision.thought)

    def on_tick(self, world: "World") -> None:
        hero = world.hero
        worst = min(hero.hp, hero.satiety, hero.hydration, hero.warmth, hero.energy)
        if worst < DANGER:
            self._in_danger = True
        elif self._in_danger and worst > SAFE:
            self._in_danger = False
            self.close_calls += 1
        if world.tick % 60 == 0:
            self._explored = len(hero.known("surface"))
            self._sols = max(1, world.day)

    def action_diversity(self, menu_size: int) -> float:
        if len(self.actions) < 2 or menu_size < 2:
            return 0.0
        counts = Counter(self.actions)
        n = len(self.actions)
        entropy = -sum(c / n * math.log2(c / n) for c in counts.values())
        return entropy / math.log2(menu_size)

    @property
    def exploration_per_sol(self) -> float:
        return self._explored / self._sols

    def thought_novelty(self) -> float:
        grams: list[tuple[str, ...]] = []
        for t in self.thoughts:
            words = t.lower().split()
            grams.extend(tuple(words[i:i + 3]) for i in range(len(words) - 2))
        return len(set(grams)) / len(grams) if grams else 1.0

    def summary(self, menu_size: int) -> dict[str, float]:
        return {
            "action_diversity": round(self.action_diversity(menu_size), 2),
            "explored_tiles_per_sol": round(self.exploration_per_sol, 1),
            "close_calls": self.close_calls,
            "thought_novelty": round(self.thought_novelty(), 2),
            "rejected_decisions": self.rejections,
            "conversations": self.conversations,
        }
