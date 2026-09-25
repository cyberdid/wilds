"""The crashed escape pod: the hero's base and the way home.

Power is the central dilemma: the pod heater keeps the survivor warm but drains
the battery, solar panels only trickle it back by day, and the emergency beacon
needs a big charge to call for rescue.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .world import Pos

if TYPE_CHECKING:
    from .world import World

SOLAR_PER_TICK = 0.012  # daytime, no storm, no fault (~10 per sol)
HEATER_PER_TICK = 0.015  # ~22 per sol when left on
CELL_POWER = 15
BEACON_PARTS = {"alloy": 3, "circuit": 1}
TRANSMIT_POWER = 80
TRANSMIT_TICKS = 120
RESCUE_DELAY = 3 * 24 * 60


@dataclass
class Pod:
    pos: Pos
    level_id: str = "surface"
    power: float = 40.0
    heater_on: bool = False
    fault: bool = False
    beacon_repaired: bool = False
    transmitted: bool = False
    rescue_at: int | None = None
    storage: Counter[str] = field(default_factory=Counter)

    @property
    def heating(self) -> bool:
        return self.heater_on and self.power > 0 and not self.fault

    def missing_parts(self, inventory: Counter[str]) -> dict[str, int]:
        return {k: n - inventory[k] for k, n in BEACON_PARTS.items() if inventory[k] < n}

    def status_line(self) -> str:
        parts = [f"power {self.power:.0f}/100", f"heater {'ON' if self.heater_on else 'off'}"]
        if self.fault:
            parts.append("FAULT (heater and solar dead until `pod repair`)")
        if self.rescue_at is not None:
            parts.append("beacon: distress call SENT")
        elif self.beacon_repaired:
            parts.append(f"beacon: repaired, `pod transmit` needs {TRANSMIT_POWER} power")
        else:
            need = " + ".join(f"{n} {k}" for k, n in BEACON_PARTS.items())
            parts.append(f"beacon: broken (repair needs {need})")
        return ", ".join(parts)

    def update(self, world: "World", storm: bool) -> None:
        """One tick of the power budget; keeps the heat source in sync."""
        level = world.levels[self.level_id]
        if not self.fault and not world.is_night and not storm:
            self.power = min(100.0, self.power + SOLAR_PER_TICK)
        if self.heating:
            self.power = max(0.0, self.power - HEATER_PER_TICK)
            if self.power <= 0:
                self.heater_on = False
                world.log("Батарея капсули сіла - обігрів вимкнувся", "danger")
        if self.heating:
            level.warm_spots.add(self.pos)
        else:
            level.warm_spots.discard(self.pos)
