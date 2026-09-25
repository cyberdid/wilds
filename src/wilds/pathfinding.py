"""Breadth-first path search over the hero's *remembered* map.

Unknown tiles are treated optimistically as walkable; actions replan when the
hero discovers that the way is blocked. Moves are 8-directional and all cost 1,
so BFS yields shortest paths.
"""

from __future__ import annotations

from collections import deque
from typing import Callable, Collection

from .tiles import Tile
from .world import NEIGHBORS, Level, Pos


def walkable(level: Level, known: dict[Pos, Tile], p: Pos, allow_unknown: bool = True) -> bool:
    if not level.in_bounds(p):
        return False
    tile = known.get(p)
    if tile is None:
        return allow_unknown
    return tile.passable


def find_path(
    level: Level,
    known: dict[Pos, Tile],
    start: Pos,
    goal: Callable[[Pos], bool],
    blocked: Collection[Pos] = (),
    allow_unknown: bool = True,
    max_nodes: int = 6000,
) -> list[Pos] | None:
    """Shortest path from start to the nearest position satisfying goal.

    Returns the positions to step through (excluding start); [] if start is
    already a goal; None if no goal is reachable.
    """
    if goal(start):
        return []
    parents: dict[Pos, Pos] = {start: start}
    queue = deque([start])
    while queue and len(parents) < max_nodes:
        p = queue.popleft()
        for dx, dy in NEIGHBORS:
            q = (p[0] + dx, p[1] + dy)
            if q in parents or not walkable(level, known, q, allow_unknown):
                continue
            parents[q] = p
            if goal(q):
                if q in blocked:
                    continue
                path = [q]
                while parents[path[-1]] != start:
                    path.append(parents[path[-1]])
                return path[::-1]
            if q in blocked:
                continue
            queue.append(q)
    return None


def frontier(level: Level, known: dict[Pos, Tile], start: Pos) -> dict[Pos, int]:
    """Reachable remembered tiles that border unexplored ground, with distances."""
    dist = {start: 0}
    queue = deque([start])
    result: dict[Pos, int] = {}
    while queue:
        p = queue.popleft()
        for dx, dy in NEIGHBORS:
            q = (p[0] + dx, p[1] + dy)
            if not level.in_bounds(q):
                continue
            if q not in known:
                result.setdefault(p, dist[p])
                continue
            if q in dist or not known[q].passable:
                continue
            dist[q] = dist[p] + 1
            queue.append(q)
    return result
