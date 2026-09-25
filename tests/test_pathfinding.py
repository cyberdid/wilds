from conftest import make_level

from wilds.pathfinding import find_path, frontier


def _known(level):
    return {p: level.tile(p) for p in level.positions()}


def test_path_goes_around_wall():
    level, marks = make_level([
        "..........",
        ".@...#..G.",
        ".....#....",
        ".....#....",
    ])
    start, goal = marks["@"][0], marks["G"][0]
    path = find_path(level, _known(level), start, lambda p: p == goal, allow_unknown=False)
    assert path is not None and path[-1] == goal
    assert all(level.passable(p) for p in path)
    for a, b in zip([start, *path], path):
        assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1


def test_no_path_returns_none():
    level, marks = make_level([
        ".@.#.G.",
        "...#...",
    ])
    goal = marks["G"][0]
    assert find_path(level, _known(level), marks["@"][0], lambda p: p == goal, allow_unknown=False) is None


def test_start_is_goal():
    level, marks = make_level(["@.."])
    assert find_path(level, _known(level), marks["@"][0], lambda p: True) == []


def test_unknown_tiles_are_optimistic():
    level, marks = make_level([
        ".@...G",
    ])
    goal = marks["G"][0]
    assert find_path(level, {}, marks["@"][0], lambda p: p == goal) is not None
    assert find_path(level, {}, marks["@"][0], lambda p: p == goal, allow_unknown=False) is None


def test_frontier_lists_edges_of_known_map():
    level, marks = make_level(["@....", "....."])
    known = {p: level.tile(p) for p in level.positions() if p[0] <= 2}
    edges = frontier(level, known, marks["@"][0])
    assert set(edges) == {(2, 0), (2, 1)}
