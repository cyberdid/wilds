"""Tile-level terrain of a zone: the macro layout from the world-map art, detailed by noise.

``macro.json`` (tools/build_macro.py) says which parts of the zone are grassland, dry
ground, plateau, mountain wall or void. This module turns that into one tile per two
yards, deterministically from (seed, tile): the same call always gives the same tile,
so chunks can be generated lazily and in any order.
"""

from __future__ import annotations

import json
from collections import deque
from enum import IntEnum
from pathlib import Path

from ..noise import ValueNoise
from .scale import Geometry

LAKE_SEED_PCT = (49.3, 51.5)       # inside the Stonebull Lake blob on the zone map


class Terrain(IntEnum):
    GRASS = 0
    TALL_GRASS = 1
    DRY_GRASS = 2
    DIRT = 3
    ROAD = 4
    MESA = 5
    BOULDER = 6
    MOUNTAIN = 7
    CLIFF = 8
    WATER = 9
    SHALLOWS = 10
    VOID = 11

    @property
    def passable(self) -> bool:
        return self not in IMPASSABLE


IMPASSABLE = frozenset({Terrain.BOULDER, Terrain.MOUNTAIN, Terrain.CLIFF, Terrain.WATER, Terrain.VOID})
_LAND = "gdr"


class Macro:
    def __init__(self, rows: list[str]) -> None:
        self.rows = rows
        self.height = len(rows)
        self.width = len(rows[0])

    @classmethod
    def load(cls, pack_dir: Path | str) -> "Macro":
        return cls(json.loads((Path(pack_dir) / "macro.json").read_text("utf-8"))["rows"])

    def at(self, u: float, v: float) -> str:
        """Class at fractional map position (0..1, 0..1)."""
        x = min(self.width - 1, max(0, int(u * self.width)))
        y = min(self.height - 1, max(0, int(v * self.height)))
        return self.rows[y][x]

    def zone_status(self, tile: tuple[int, int], geometry: Geometry) -> str:
        """Classify a map tile against the coarse zone outline in the macro image."""
        tx, ty = tile
        if not (0 <= tx < geometry.width and 0 <= ty < geometry.height):
            return "outside"
        mx = min(self.width - 1, int(tx / geometry.width * self.width))
        my = min(self.height - 1, int(ty / geometry.height * self.height))
        if self.rows[my][mx] == "v":
            return "outside"
        if mx in (0, self.width - 1) or my in (0, self.height - 1):
            return "edge_ambiguous"
        for ny in range(max(0, my - 1), min(self.height, my + 2)):
            for nx in range(max(0, mx - 1), min(self.width, mx + 2)):
                if self.rows[ny][nx] == "v":
                    return "edge_ambiguous"
        return "inside_mask"

    def component(self, x: int, y: int) -> set[tuple[int, int]]:
        """Connected cells of the same class as (x, y)."""
        cls = self.rows[y][x]
        seen = {(x, y)}
        queue = deque([(x, y)])
        while queue:
            cx, cy = queue.popleft()
            for n in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if n not in seen and 0 <= n[0] < self.width and 0 <= n[1] < self.height \
                        and self.rows[n[1]][n[0]] == cls:
                    seen.add(n)
                    queue.append(n)
        return seen


class ZoneTerrain:
    def __init__(self, geometry: Geometry, macro: Macro, seed: int = 0) -> None:
        self.geo = geometry
        self.macro = macro
        self.seed = seed
        self._warp = ValueNoise(seed * 7 + 1)
        self._patch = ValueNoise(seed * 7 + 2)
        self._fine = ValueNoise(seed * 7 + 3)
        lx = int(LAKE_SEED_PCT[0] / 100 * macro.width)
        ly = int(LAKE_SEED_PCT[1] / 100 * macro.height)
        self._lake = macro.component(lx, ly) if macro.rows[ly][lx] == "r" else set()
        self.roads: set[tuple[int, int]] = set()

    def in_bounds(self, p: tuple[int, int]) -> bool:
        return 0 <= p[0] < self.geo.width and 0 <= p[1] < self.geo.height

    def _macro_class(self, x: int, y: int) -> tuple[str, bool]:
        """Macro class under a tile, with the coast wobbled by domain-warp noise."""
        wx = (self._warp.fractal(x / 55, y / 55, 3) - 0.5) * 34
        wy = (self._warp.fractal(x / 55 + 91, y / 55 + 37, 3) - 0.5) * 34
        u = (x + wx) / self.geo.width
        v = (y + wy) / self.geo.height
        cls = self.macro.at(u, v)
        in_lake = False
        if cls == "r" and self._lake:
            cx = min(self.macro.width - 1, max(0, int(u * self.macro.width)))
            cy = min(self.macro.height - 1, max(0, int(v * self.macro.height)))
            in_lake = (cx, cy) in self._lake
        return cls, in_lake

    def tile(self, x: int, y: int) -> Terrain:
        if not self.in_bounds((x, y)):
            return Terrain.VOID
        if (x, y) in self.roads:
            return Terrain.ROAD
        cls, in_lake = self._macro_class(x, y)
        if cls == "v":
            return Terrain.VOID
        if cls == "m":
            edge = self._fine.fractal(x / 9, y / 9, 2)
            return Terrain.CLIFF if edge < 0.42 else Terrain.MOUNTAIN
        patch = self._patch.fractal(x / 38, y / 38, 4)
        fine = self._fine.fractal(x / 5, y / 5, 2)
        if in_lake:
            return Terrain.SHALLOWS if fine > 0.74 else Terrain.WATER
        if cls == "r":
            return Terrain.BOULDER if fine > 0.83 else (Terrain.MESA if patch > 0.36 else Terrain.DIRT)
        if cls == "d":
            return Terrain.DIRT if fine > 0.8 else (Terrain.DRY_GRASS if patch > 0.3 else Terrain.GRASS)
        # grassland: patches of tall grass, sparse dirt and stones
        if fine > 0.9:
            return Terrain.DIRT
        if patch > 0.6:
            return Terrain.TALL_GRASS
        return Terrain.GRASS

    def passable(self, p: tuple[int, int]) -> bool:
        return self.in_bounds(p) and self.tile(*p).passable

    def macro_walkable(self, x: int, y: int) -> bool:
        """Cheap test on the macro map only: is this spot walkable land (not wall, void or lake)?"""
        u, v = x / self.geo.width, y / self.geo.height
        cls = self.macro.at(u, v)
        if cls not in _LAND:
            return False
        if cls == "r" and self._lake:
            cx = min(self.macro.width - 1, int(u * self.macro.width))
            cy = min(self.macro.height - 1, int(v * self.macro.height))
            return (cx, cy) not in self._lake
        return True
