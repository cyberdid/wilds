"""Stage 4: a ship for reaching locations beyond the home city - an orbital
station and a frontier outpost. Fuel/hull is the same "resource you must
manage" pattern as Tau-7's pod power, one level further out."""

from __future__ import annotations

from dataclasses import dataclass

MAX_FUEL = 100.0
MAX_HULL = 100.0
LAUNCH_FUEL = 35.0
LAUNCH_MINUTES = 240
FUEL_PRICE = 4  # nuyen per unit of fuel


@dataclass
class Ship:
    fuel: float = 60.0
    hull: float = MAX_HULL

    def status_line(self) -> str:
        condition = "damaged" if self.hull < 50 else "sound"
        return f"fuel {self.fuel:.0f}/{MAX_FUEL:.0f}, hull {self.hull:.0f}/{MAX_HULL:.0f} ({condition})"
