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


def coarse_passable(world: "ZoneWorld", cell: Pos) -> bool:
    """A coarse cell is open when the macro map under its centre is walkable land."""
    x, y = cell[0] * COARSE + COARSE // 2, cell[1] * COARSE + COARSE // 2
    return world.terrain.macro_walkable(x, y)


def find_route(world: "ZoneWorld", start: Pos, goal: Pos) -> list[Pos] | None:
    """Tile path from ``start`` to ``goal`` over the whole zone, or None if unreachable."""
    cw, ch = world.geo.width // COARSE + 1, world.geo.height // COARSE + 1
    a, b = (start[0] // COARSE, start[1] // COARSE), (goal[0] // COARSE, goal[1] // COARSE)
    coarse = astar(a, b, lambda c: coarse_passable(world, c) or c in (a, b), max_nodes=cw * ch,
                   bounds=lambda c: 0 <= c[0] < cw and 0 <= c[1] < ch)
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
