"""Pathfinding at zone scale: a coarse route over the macro map, refined tile by tile.

A zone is millions of tiles; searching them all is out of the question. The route is
planned on a coarse grid (8x8 tiles per cell, from the macro map), then each leg
between waypoints is searched on real tiles, so a 2000-tile trip costs a few hundred
tiny searches instead of one huge one.
"""

from __future__ import annotations

import heapq
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .world import ZoneWorld

Pos = tuple[int, int]
COARSE = 8
_STEPS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
          (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]


def _octile(a: Pos, b: Pos) -> float:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return max(dx, dy) + 0.4142 * min(dx, dy)


def astar(start: Pos, goal: Pos, passable, max_nodes: int = 30000, bounds=None) -> list[Pos] | None:
    """A* on an 8-connected grid; returns positions after ``start`` up to and including ``goal``."""
    if start == goal:
        return []
    open_heap = [(_octile(start, goal), 0.0, start)]
    g = {start: 0.0}
    parent: dict[Pos, Pos] = {}
    closed: set[Pos] = set()
    while open_heap and len(closed) < max_nodes:
        _, cost, p = heapq.heappop(open_heap)
        if p in closed:
            continue
        if p == goal:
            path = [p]
            while path[-1] in parent:
                path.append(parent[path[-1]])
            return path[-2::-1]
        closed.add(p)
        for dx, dy, step in _STEPS:
            q = (p[0] + dx, p[1] + dy)
            if q in closed or (bounds and not bounds(q)) or not (q == goal or passable(q)):
                continue
            if dx and dy and not (passable((p[0] + dx, p[1])) and passable((p[0], p[1] + dy))):
                continue  # no cutting corners through obstacles
            nc = cost + step
            if nc < g.get(q, math.inf):
                g[q] = nc
                parent[q] = p
                heapq.heappush(open_heap, (nc + _octile(q, goal), nc, q))
    return None


class Coarse:
    """The zone at 8x8 tiles per cell: which cells are open and which connected region each is in."""

    def __init__(self, world: "ZoneWorld") -> None:
        self.w = world.geo.width // COARSE + 1
        self.h = world.geo.height // COARSE + 1
        t = world.terrain
        self.open = [[t.macro_walkable(x * COARSE + COARSE // 2, y * COARSE + COARSE // 2)
                      for x in range(self.w)] for y in range(self.h)]
        self.region = [[0] * self.w for _ in range(self.h)]
        next_id = 0
        for y0 in range(self.h):
            for x0 in range(self.w):
                if self.open[y0][x0] and not self.region[y0][x0]:
                    next_id += 1
                    self.region[y0][x0] = next_id
                    stack = [(x0, y0)]
                    while stack:
                        x, y = stack.pop()
                        for dx, dy, _ in _STEPS:
                            nx, ny = x + dx, y + dy
                            if 0 <= nx < self.w and 0 <= ny < self.h and self.open[ny][nx] \
                                    and not self.region[ny][nx]:
                                self.region[ny][nx] = next_id
                                stack.append((nx, ny))

    def passable(self, c: Pos) -> bool:
        return 0 <= c[0] < self.w and 0 <= c[1] < self.h and self.open[c[1]][c[0]]

    def snap(self, c: Pos, radius: int = 3) -> Pos | None:
        """The open cell at or nearest to ``c``."""
        if self.passable(c):
            return c
        for r in range(1, radius + 1):
            ring = [(c[0] + dx, c[1] + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                    if max(abs(dx), abs(dy)) == r and self.passable((c[0] + dx, c[1] + dy))]
            if ring:
                return ring[0]
        return None

    def region_of(self, c: Pos) -> int:
        return self.region[c[1]][c[0]] if self.passable(c) else 0


def coarse_map(world: "ZoneWorld") -> Coarse:
    cm = getattr(world, "_coarse", None)
    if cm is None:
        cm = world._coarse = Coarse(world)
    return cm


def reachable(world: "ZoneWorld", start: Pos, goal: Pos) -> bool:
    """Cheap test on the coarse map: are the two spots in the same connected region?"""
    cm = coarse_map(world)
    a = cm.snap((start[0] // COARSE, start[1] // COARSE))
    b = cm.snap((goal[0] // COARSE, goal[1] // COARSE))
    return a is not None and b is not None and cm.region_of(a) == cm.region_of(b)


def find_route(world: "ZoneWorld", start: Pos, goal: Pos) -> list[Pos] | None:
    """Tile path from ``start`` to ``goal`` over the whole zone, or None if unreachable."""
    cm = coarse_map(world)
    a = cm.snap((start[0] // COARSE, start[1] // COARSE))
    b = cm.snap((goal[0] // COARSE, goal[1] // COARSE))
    if a is None or b is None or cm.region_of(a) != cm.region_of(b):
        return None
    coarse = astar(a, b, cm.passable, max_nodes=cm.w * cm.h, bounds=lambda c: 0 <= c[0] < cm.w and 0 <= c[1] < cm.h)
    if coarse is None:
        return None
    waypoints = [start] + [(c[0] * COARSE + COARSE // 2, c[1] * COARSE + COARSE // 2) for c in coarse[:-1]] + [goal]
    path: list[Pos] = []
    here = start
    for wp in waypoints[1:]:
        if not world.passable(wp) and wp != goal:
            wp = world.nearest_passable(wp, 6) or wp
        leg = astar(here, wp, world.passable, max_nodes=4000,
                    bounds=lambda q: abs(q[0] - here[0]) < 40 and abs(q[1] - here[1]) < 40)
        if leg is None:
            return None
        path += leg
        here = wp
    return path
