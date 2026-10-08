"""Azeroth / Mulgore art: terrain tiles and material transitions.

The terrain contract lives in ``wilds.azeroth.manifest``. The authored families cover
prairie grass, dry ground, paths, mesa, rocks, water, cliffs and mountain tops, with
pixel-art edge overlays to soften material boundaries. Tiles are 16x16 px (2 yards)
and use seeded periodic textures so exports are repeatable and seams stay quiet.
"""

from __future__ import annotations

import random
import math

from ..pixelart import art
from ..procgen import Canvas, bayer, fbm
from ..registry import register

TILE = 16

PRAIRIE = {str(i): f"prairie{i}" for i in range(6)}
DRY = {str(i): f"straw{i}" for i in range(6)}
EARTH = {str(i): color for i, color in enumerate(
    ("earth0", "earth1", "earth2", "earth3", "earth4", "earth5"))}
ROAD = {str(i): color for i, color in enumerate(
    ("earth0", "earth1", "earth2", "earth3", "earth2", "earth4"))}
MESA = {str(i): f"mesa{i}" for i in range(6)}
ROCK = {str(i): f"rock{i}" for i in range(6)}
WATER = {str(i): f"water{i}" for i in range(6)}
SHALLOWS = {**WATER, "s": "sand3", "S": "sand4"}


def _quantize(field: list[list[float]], chars: str, weights: tuple[float, ...],
              dither: float = 0.08) -> Canvas:
    """Rank a periodic field into a stable colour mix for one 16px ground tile."""
    values = sorted(field[y][x] for y in range(TILE) for x in range(TILE))
    total = sum(weights)
    cuts = []
    acc = 0.0
    for weight in weights[:-1]:
        acc += weight
        cuts.append(values[min(len(values) - 1, int(acc / total * len(values)))])

    canvas = Canvas(TILE, TILE)
    for y in range(TILE):
        for x in range(TILE):
            value = field[y][x] + (bayer(x, y) - 0.5) * dither
            index = 0
            while index < len(cuts) and value >= cuts[index]:
                index += 1
            canvas.set(x, y, chars[index])
    return canvas


def _field(seed: int) -> list[list[float]]:
    broad = fbm(TILE, TILE, seed, octaves=2, cells=3)
    fine = fbm(TILE, TILE, seed + 13, octaves=2, cells=7)
    return [[0.68 * broad[y][x] + 0.32 * fine[y][x]
             for x in range(TILE)] for y in range(TILE)]


def _soil_field(seed: int) -> list[list[float]]:
    """Warm, sunlit earth with the broken planes of compacted soil."""
    cushions = _cushions(seed, count=9, squash=1.15)
    broad = fbm(TILE, TILE, seed + 3, octaves=2, cells=3)
    fine = fbm(TILE, TILE, seed + 11, octaves=2, cells=8)
    return _mix_fields(((0.42, _emboss(cushions)), (0.18, cushions),
                        (0.25, broad), (0.15, fine)))


def _road_field(seed: int) -> list[list[float]]:
    """Shallow, wind-rounded tracks running across a packed prairie path."""
    warp = fbm(TILE, TILE, seed, octaves=2, cells=2)
    tracks = [[0.5 + 0.5 * math.cos(2 * math.pi * (2 * x / TILE + 0.22 * warp[y][x]))
               for x in range(TILE)] for y in range(TILE)]
    grain = fbm(TILE, TILE, seed + 17, octaves=2, cells=7)
    broad = fbm(TILE, TILE, seed + 29, octaves=2, cells=3)
    return _mix_fields(((0.45, tracks), (0.35, broad), (0.20, grain)))


def _mesa_field(seed: int) -> list[list[float]]:
    """Sun-baked red stone, with strata only as a quiet secondary grain."""
    cushions = _cushions(seed, count=9, squash=1.25)
    warp = fbm(TILE, TILE, seed, octaves=2, cells=2)
    strata = [[0.5 + 0.5 * math.sin(2 * math.pi * (1.5 * y / TILE + 0.24 * warp[y][x]))
               for x in range(TILE)] for y in range(TILE)]
    broad = fbm(TILE, TILE, seed + 19, octaves=2, cells=3)
    grain = fbm(TILE, TILE, seed + 31, octaves=2, cells=7)
    return _mix_fields(((0.34, _emboss(cushions)), (0.12, strata),
                        (0.36, broad), (0.18, grain)))


def _normalize(field: list[list[float]]) -> list[list[float]]:
    lo = min(min(row) for row in field)
    hi = max(max(row) for row in field)
    span = hi - lo or 1.0
    return [[(value - lo) / span for value in row] for row in field]


def _cushions(seed: int, count: int = 12, squash: float = 1.2) -> list[list[float]]:
    """Periodic overlapping prairie clumps, with a soft light-facing pixel ramp."""
    rng = random.Random(seed)
    points = [(rng.uniform(0, TILE), rng.uniform(0, TILE), rng.uniform(2.0, 4.0))
              for _ in range(count)]
    out = []
    for y in range(TILE):
        row = []
        for x in range(TILE):
            best = 0.0
            for px, py, radius in points:
                dx = min(abs(x + 0.5 - px), TILE - abs(x + 0.5 - px))
                dy = min(abs(y + 0.5 - py), TILE - abs(y + 0.5 - py)) * squash
                distance = (dx * dx + dy * dy) / (radius * radius)
                if distance < 1.0:
                    best = max(best, 1.0 - distance)
            row.append(best)
        out.append(row)
    return out


def _emboss(field: list[list[float]]) -> list[list[float]]:
    raw = [[field[(y + 1) % TILE][(x + 1) % TILE] - field[y][x]
            for x in range(TILE)] for y in range(TILE)]
    return _normalize(raw)


def _mix_fields(parts: tuple[tuple[float, list[list[float]]], ...]) -> list[list[float]]:
    return _normalize([[sum(weight * field[y][x] for weight, field in parts)
                        for x in range(TILE)] for y in range(TILE)])


def _grass_field(seed: int) -> list[list[float]]:
    cushions = _cushions(seed)
    fine = fbm(TILE, TILE, seed + 7, octaves=2, cells=4)
    return _mix_fields(((0.55, _emboss(cushions)), (0.25, cushions), (0.20, fine)))


def _dry_field(seed: int) -> list[list[float]]:
    warp = fbm(TILE, TILE, seed, octaves=2, cells=2)
    ripples = [[0.5 + 0.5 * math.sin(2 * math.pi * (3 * y / TILE + 1.25 * warp[y][x]
                                                        + 0.15 * math.sin(2 * math.pi * x / TILE)))
                for x in range(TILE)] for y in range(TILE)]
    fine = fbm(TILE, TILE, seed + 5, octaves=2, cells=8)
    base = fbm(TILE, TILE, seed + 9, octaves=2, cells=4)
    return _mix_fields(((0.30, _emboss(ripples)), (0.35, base), (0.35, fine)))


def _share_edge_band(canvas: Canvas, common: Canvas, width: int = 3) -> None:
    """Keep sibling variants on one quiet, shared pixel band around every edge."""
    for y in range(TILE):
        for x in range(TILE):
            if min(x, y, TILE - 1 - x, TILE - 1 - y) < width:
                canvas.set(x, y, common.get(x, y))


def _tufts(canvas: Canvas, seed: int, *, tall: bool) -> None:
    """Add sparse interior blades; keep the tile border free of hard motifs."""
    rng = random.Random(seed + 91)
    count = 3 if tall else 2
    blade, shadow = "5", "3"
    for _ in range(count):
        margin = 4 if tall else 3
        x, y = rng.randrange(margin, TILE - margin), rng.randrange(margin, TILE - margin)
        if tall:
            # Little fan-shaped clumps read as taller grass without crossing the tile edge.
            canvas.set(x, y - 2, blade)
            canvas.set(x - 1, y - 1, "4")
            canvas.set(x, y - 1, blade)
            canvas.set(x + 1, y - 1, "4")
            canvas.set(x, y, shadow)
            canvas.set(x - 1, y + 1, "2")
            canvas.set(x + 1, y + 1, "2")
        else:
            canvas.set(x, y, blade)
            canvas.set(x, y + 1, shadow)


def _register_grass(base: str, palette: dict[str, str], *, tall: bool = False,
                    dry: bool = False, dither: float = 0.08) -> None:
    common_seed = 1600 if dry else 1500
    field = _dry_field if dry else _grass_field
    weights = (7, 33, 38, 16, 5, 1)
    common = _quantize(field(common_seed), "012345", weights, dither)
    for variant in range(4):
        seed = 1400 + variant + (100 if tall else 0) + (200 if dry else 0)
        canvas = _quantize(field(seed), "012345", weights, dither)
        _tufts(canvas, seed, tall=tall)
        _share_edge_band(canvas, common)
        register(f"{base}@{variant}", art(
            canvas.grid(), legend=palette,
            note="Mulgore prairie ground, seamless seeded 16px tile",
        ))


def _register_ground(base: str, palette: dict[str, str], variants: int,
                     seed: int, weights: tuple[float, ...], note: str,
                     field_fn=_soil_field, marks: bool = True) -> None:
    common = _quantize(field_fn(seed + 900), "012345", weights, dither=0.035)
    for variant in range(variants):
        canvas = _quantize(field_fn(seed + variant), "012345", weights, dither=0.035)
        rng = random.Random(seed + variant)
        if marks:
            for _ in range(2):
                x, y = rng.randrange(4, 12), rng.randrange(4, 12)
                canvas.set(x, y, rng.choice(("0", "1")))
        _share_edge_band(canvas, common, width=2)
        register(f"{base}@{variant}", art(canvas.grid(), legend=palette, note=note))


def _register_water(base: str, palette: dict[str, str], seed: int, shallow: bool) -> None:
    weights = (18, 48, 27, 6, 1)
    water_chars = "12345"
    water_palette = {"1": palette["1"], "2": palette["2"], "3": palette["3"],
                     "4": palette["4"], "5": palette["5"]}
    common = _quantize(_water_field(seed + 900), water_chars, weights, dither=0.025)
    for variant in range(2):
        base_seed = seed + variant * 31
        base_tile = _quantize(_water_field(base_seed), water_chars, weights, dither=0.025)
        # A quiet, shared glint set makes the lake lively without turning into glitter.
        rng = random.Random(base_seed + 5)
        glints = [(rng.randrange(3, 13), rng.randrange(3, 13), index % 4) for index in range(5)]
        frames = []
        for frame in range(4):
            canvas = base_tile.copy()
            if shallow:
                for x, y in ((4, 10), (12, 5), (8, 13)):
                    canvas.set(x, y, "s")
                    if x + 1 < TILE:
                        canvas.set(x + 1, y, "S" if frame % 2 else "s")
            for x, y, phase in glints:
                state = (frame + phase) % 4
                if state in (0, 2):
                    canvas.set(x, y, "4")
                elif state == 1 and x < TILE - 3:
                    canvas.set(x, y, "4")
                    canvas.set(x + 1, y, "3")
            _share_edge_band(canvas, common)
            frames.append(canvas.grid())
        legend = {**water_palette, **({"s": palette["s"], "S": palette["S"]} if shallow else {})}
        register(f"{base}@{variant}", art(*frames, legend=legend, fps=2.5,
                                           note="Mulgore water with looping surface glints"))


def _water_field(seed: int) -> list[list[float]]:
    swell = fbm(TILE, TILE, seed, octaves=2, cells=4)
    slope = _emboss(fbm(TILE, TILE, seed + 7, octaves=2, cells=4))
    fine = fbm(TILE, TILE, seed + 13, octaves=2, cells=8)
    return _mix_fields(((0.50, slope), (0.34, swell), (0.16, fine)))


def _register_face(base: str, palette: dict[str, str], seed: int, *, cliff: bool) -> None:
    for variant in range(3):
        canvas = _quantize(_field(seed + variant), "012345", (10, 25, 30, 21, 11, 3), 0.04)
        rng = random.Random(seed + variant)
        # Short fractures and strata are kept off the edge so adjacent face tiles join cleanly.
        for _ in range(3):
            x, y = rng.randrange(2, 14), rng.randrange(2, 13)
            canvas.set(x, y, "1" if cliff else "2")
            if x + 1 < 15:
                canvas.set(x + 1, y, "2" if cliff else "3")
        _share_edge_band(canvas, _quantize(_field(seed + 900), "012345", (10, 25, 30, 21, 11, 3), 0.04))
        register(f"{base}@{variant}", art(canvas.grid(), legend=palette,
                                           note="Mulgore rocky face, repeatable pixel texture"))


def _register_boulders() -> None:
    for variant in range(3):
        canvas = Canvas(TILE, TILE)
        cx, cy = 7 + (variant % 2), 8 + (variant == 2)
        rx, ry = (5, 4) if variant != 1 else (6, 3)
        for y in range(3, 14):
            for x in range(2, 15):
                distance = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
                if distance <= 1.0:
                    canvas.set(x, y, "k" if distance > 0.82 else ("4" if x + y < cx + cy else "2"))
        canvas.set(cx - 2, cy - 2, "5")
        canvas.set(cx - 1, cy - 2, "4")
        register(f"az.boulder@{variant}", art(canvas.grid(), legend={**ROCK, "k": "ink"},
                                               note="small Mulgore field boulder, bottom anchored"))


def _edge(base: str, palette: dict[str, str], direction: str, seed: int,
          *, corner: bool = False, watery: bool = False) -> None:
    canvas = Canvas(TILE, TILE)
    field = fbm(TILE, TILE, seed, octaves=2, cells=4)
    grain = fbm(TILE, TILE, seed + 19, octaves=2, cells=8)
    for y in range(TILE):
        for x in range(TILE):
            n = (field[y][x] - 0.5) * 2.0
            if corner:
                east, north = direction.endswith("e"), direction.startswith("n")
                dx = (x - (11 if east else 4)) / 7
                dy = (y - (4 if north else 11)) / 7
                inside = dx * dx + dy * dy > 0.72 + n * 0.12
            else:
                edge = (5.5 + n * 2.0)
                inside = {
                    "n": y < edge, "s": y >= TILE - edge,
                    "e": x >= TILE - edge, "w": x < edge,
                }[direction]
            if inside:
                level = "1" if grain[y][x] < 0.25 else "2" if grain[y][x] < 0.62 else "3"
                canvas.set(x, y, level)
            elif watery:
                # A sparse foam line sits just landward of the irregular shore.
                near = (direction == "n" and 5 <= y <= 7 or direction == "s" and 8 <= y <= 10
                        or direction == "e" and 8 <= x <= 10 or direction == "w" and 5 <= x <= 7)
                if near and (x * 3 + y * 5 + seed) % 11 < 2:
                    canvas.set(x, y, "f")
    register(base, art(canvas.grid(), legend={**palette, "f": "white"},
                        note="transparent irregular Mulgore terrain transition"))


def _register_edges() -> None:
    for kind, palette, seed, watery in (
        ("water", WATER, 2600, True), ("dirt", EARTH, 2700, False),
        ("cliff", ROCK, 2800, False), ("drygrass", DRY, 2900, False),
        ("grass", PRAIRIE, 3000, False),
    ):
        for index, side in enumerate(("n", "s", "e", "w")):
            _edge(f"az.edge.{kind}.{side}", palette, side, seed + index, watery=watery)
        for index, corner in enumerate(("ne", "nw", "se", "sw")):
            _edge(f"az.edge.{kind}.corner.{corner}", palette, corner, seed + 10 + index, corner=True)


def _deco(name: str, variant: int) -> None:
    canvas = Canvas(TILE, TILE)
    rng = random.Random(3200 + variant + sum(map(ord, name)))
    x, y = 5 + rng.randrange(6), 5 + rng.randrange(6)
    if name.startswith("flower_"):
        petal = {"flower_red": "fire3", "flower_yellow": "gold2", "flower_blue": "water5"}[name]
        canvas.set(x, y, "p")
        canvas.set(x - 1, y + 1, "p")
        canvas.set(x + 1, y + 1, "p")
        canvas.set(x, y + 2, "l")
        legend = {"p": petal, "l": "prairie2"}
    elif name == "tuft":
        canvas.set(x, y, "4")
        canvas.set(x - 1, y + 1, "3")
        canvas.set(x, y + 1, "5")
        canvas.set(x + 1, y + 1, "4")
        legend = PRAIRIE
    elif name == "stones":
        canvas.set(x, y, "2")
        canvas.set(x + 2, y + 1, "4")
        canvas.set(x - 1, y + 2, "3")
        legend = ROCK
    elif name == "bones":
        for dx, dy in ((0, 0), (1, 0), (2, 0), (5, 2), (6, 2)):
            canvas.set(x + dx - 2, y + dy, "b")
        legend = {"b": "bone3"}
    elif name == "dry_bush":
        for dx, dy, color in ((0, 0, "3"), (-1, 1, "2"), (1, 1, "4"), (0, 2, "3"), (2, 0, "2")):
            canvas.set(x + dx - 1, y + dy - 1, color)
        legend = DRY
    else:  # stump
        canvas.set(x, y, "k")
        canvas.set(x + 1, y, "3")
        canvas.set(x, y + 1, "2")
        canvas.set(x + 1, y + 1, "1")
        legend = {"k": "ink", "1": "tent1", "2": "tent2", "3": "tent3"}
    register(f"az.deco.{name}@{variant}", art(canvas.grid(), legend=legend,
                                               note="small Mulgore ground decoration"))


_register_grass("az.ground.grass", PRAIRIE)
_register_grass("az.ground.tall_grass", PRAIRIE, tall=True)
_register_grass("az.ground.dry_grass", DRY, dry=True, dither=0.06)
_register_ground("az.ground.dirt", EARTH, 3, 1700, (7, 27, 35, 21, 8, 2), "Mulgore bare earth")
_register_ground("az.ground.road", ROAD, 3, 1800, (7, 30, 37, 19, 6, 1), "Mulgore packed dirt road",
                 field_fn=_road_field, marks=False)
_register_ground("az.ground.mesa", MESA, 3, 1900, (7, 26, 35, 20, 9, 3), "Mulgore red-brown mesa",
                 field_fn=_mesa_field)
_register_water("az.ground.water", WATER, 2000, shallow=False)
_register_water("az.ground.shallows", SHALLOWS, 2100, shallow=True)
_register_ground("az.mountain.top", ROCK, 3, 2200, (6, 21, 34, 24, 11, 4), "Mulgore mountain top")
_register_face("az.mountain.face", ROCK, 2300, cliff=False)
_register_face("az.cliff.face", EARTH, 2400, cliff=True)
_register_boulders()
_register_edges()
for _name in ("flower_red", "flower_yellow", "flower_blue", "tuft", "stones", "bones", "dry_bush", "stump"):
    for _variant in range(2):
        _deco(_name, _variant)
