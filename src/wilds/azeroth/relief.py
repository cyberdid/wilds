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
HILL_GAIN = 280  # the prairie swells up to ~90 px (11 yards) over tens of tiles
STEP = 4  # heights are quantised so the block cache stays small


class Relief:
    def __init__(self, world: "ZoneWorld") -> None:
        self.world = world
        self.noise = ValueNoise(world.seed * 13 + 3)
        self.platforms = settlements.platforms(world)
        self.bridges = settlements.bridge_tiles(world)
        self.flat = [(world.nearest_passable(p.pos, 30) or p.pos, settlements.RECIPES[p.title][0])
                     for p in world.placements if p.title in settlements.RECIPES]  # villages sit on level ground
        line = settlements.gate_line(world)  # the gate's wall needs level ground along its whole length
        if line:
            self.flat += [(c, 5) for c in (line[0], *line[1][::4])]
        self._heights: dict[tuple[int, int, str], int] = {}
        self._vertices: dict[tuple[int, int], int] = {}

    def kind(self, x: int, y: int, terr: Terrain) -> str:
        """ground | mesa | cliff | mountain | platform | bridge | void"""
        if terr is Terrain.VOID:
            return "void"
        if terr in (Terrain.WATER, Terrain.SHALLOWS):
            return "water"
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
        key = (x, y, kind)
        h = self._heights.get(key)
        if h is None:
            if len(self._heights) > 400_000:
                self._heights.clear()
            h = self._heights[key] = self._height(x, y, kind)
        return h

    def vertex(self, vx: int, vy: int) -> int:
        """Ground height (px) at a tile corner: smooth rolling swells, level around villages, flat at lakes.

        Corners are shared by the four tiles around them, so the land has no seams."""
        key = (vx, vy)
        h = self._vertices.get(key)
        if h is None:
            if len(self._vertices) > 600_000:
                self._vertices.clear()
            h = self._vertices[key] = self._vertex(vx, vy)
        return h

    def _vertex(self, vx: int, vy: int) -> int:
        tiles = ((vx - 1, vy - 1), (vx, vy - 1), (vx - 1, vy), (vx, vy))
        if any(self.world.terrain.tile(*t) in (Terrain.WATER, Terrain.SHALLOWS, Terrain.VOID) for t in tiles):
            return 0
        wet = self._water_distance(vx, vy)
        if wet < 1:
            return 0
        n = 0.7 * self.noise.fractal(vx / 55 + 7, vy / 55 + 7, 2) + 0.3 * self.noise.fractal(vx / 22 + 70, vy / 22 + 11, 2)
        lift = max(0.0, n - 0.38) * HILL_GAIN
        for (cx, cy), r in self.flat:
            d = math.hypot(vx - cx, (vy - cy) / 0.75)
            if d < r + 14:
                lift *= max(0.0, (d - r * 0.8) / (r * 0.2 + 14))
        return int(lift * min(1.0, wet / 14) ** 1.5)  # banks slope gently down to the water

    def _water_distance(self, vx: int, vy: int) -> int:
        """Rough tiles to the nearest lake (probed along 8 directions), capped at 14."""
        tile = self.world.terrain.tile
        for r in (1, 3, 6, 10, 14):
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
                if tile(vx + dx * r, vy + dy * r) in (Terrain.WATER, Terrain.SHALLOWS):
                    return r - 1
        return 14

    def corners(self, x: int, y: int) -> tuple[int, int, int, int]:
        """Heights of a tile's north, east, south and west corners (screen top, right, bottom, left)."""
        return self.vertex(x, y), self.vertex(x + 1, y), self.vertex(x + 1, y + 1), self.vertex(x, y + 1)

    def _height(self, x: int, y: int, kind: str) -> int:
        if kind == "ground":
            return sum(self.corners(x, y)) // 4
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
    def _q(v: float, step: int = STEP) -> int:
        return int(v) // step * step
