"""The third dimension of Mulgore: how high each tile stands, in sprite pixels.

The 2.5D view draws anything above 0 as an extruded block: the mountain wall around the zone,
the cliffs at its foot, the red mesas, and Thunder Bluff's wooden platforms and bridges. The
heights are stylised (a tile is 16 px wide = 2 yards) but keep the shape of the land.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..noise import ValueNoise
from . import settlements
from .terrain import Terrain

if TYPE_CHECKING:
    from .world import ZoneWorld

MESA_HEIGHT = 20
PLATFORM_HEIGHT = 72  # the rises stand on sheer cliffs
BRIDGE_HEIGHT = 68
CLIFF_BASE, CLIFF_VAR = 14, 10
MOUNTAIN_BASE, MOUNTAIN_VAR = 30, 38
STEP = 4  # heights are quantised so the block cache stays small


class Relief:
    def __init__(self, world: "ZoneWorld") -> None:
        self.world = world
        self.noise = ValueNoise(world.seed * 13 + 3)
        self.platforms = settlements.platforms(world)
        self.bridges = settlements.bridge_tiles(world)

    def kind(self, x: int, y: int, terr: Terrain) -> str:
        """ground | mesa | cliff | mountain | platform | bridge | void"""
        if terr is Terrain.VOID:
            return "void"
        if self.platforms_near(x, y):
            if settlements.on_platform(self.world, (x, y), self.platforms):
                return "platform"
        if (x, y) in self.bridges:
            return "bridge"
        return {Terrain.MOUNTAIN: "mountain", Terrain.CLIFF: "cliff", Terrain.MESA: "mesa"}.get(terr, "ground")

    def platforms_near(self, x: int, y: int) -> bool:
        return any(abs(x - p.center[0]) <= p.radius + 2 and abs(y - p.center[1]) <= p.radius + 2
                   for p in self.platforms)

    def height(self, x: int, y: int, kind: str) -> int:
        if kind == "platform":
            return PLATFORM_HEIGHT
        if kind == "bridge":
            return BRIDGE_HEIGHT
        if kind == "mesa":
            return MESA_HEIGHT + (8 if self.noise.fractal(x / 26 + 9, y / 26 + 9, 2) > 0.62 else 0)  # rare terraces, not thin ledges
        if kind == "cliff":
            n = self.noise.fractal(x / 14, y / 14, 2)
            return self._q(CLIFF_BASE + CLIFF_VAR * n)
        if kind == "mountain":
            n = self.noise.fractal(x / 24 + 50, y / 24 + 50, 3)
            ridge = 0.5 + 0.5 * math.sin(x / 9.0 + y / 13.0 + n * 4)  # long ridges, not random lumps
            return self._q(MOUNTAIN_BASE + MOUNTAIN_VAR * (0.55 * n + 0.45 * ridge))
        return 0

    @staticmethod
    def _q(v: float) -> int:
        return int(v) // STEP * STEP
