"""Real-world scale of a zone.

One tile is ``TILE_YARDS`` yards. A tick is the time a hero running at the game's
run speed needs to cross one tile, so walking speed, travel times and zone size
stay true to the source game (Mulgore: 5450 x 3633 yards, about 2725 x 1817 tiles).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

TILE_YARDS = 2.0
RUN_SPEED_YD_S = 7.0  # the standard run speed of a player character
TICK_SECONDS = TILE_YARDS / RUN_SPEED_YD_S
CHUNK = 64  # tiles per chunk side (128 yards)


@dataclass(frozen=True)
class SubMap:
    name: str
    center_x_pct: float
    center_y_pct: float
    width_pct: float
    height_pct: float


@dataclass(frozen=True)
class Geometry:
    name: str
    width_yards: float
    height_yards: float
    submaps: tuple[SubMap, ...] = ()
    world_map_id: int | None = None
    x_min: float | None = None
    x_max: float | None = None
    y_min: float | None = None
    y_max: float | None = None

    @property
    def width(self) -> int:
        return round(self.width_yards / TILE_YARDS)

    @property
    def height(self) -> int:
        return round(self.height_yards / TILE_YARDS)

    def pct_to_tile(self, x_pct: float, y_pct: float) -> tuple[int, int]:
        """Wiki map coordinates (x% from the west edge, y% from the north) -> tile."""
        return (min(self.width - 1, max(0, int(x_pct / 100 * self.width))),
                min(self.height - 1, max(0, int(y_pct / 100 * self.height))))

    def world_to_tile(self, map_id: int, x: float, y: float) -> tuple[int, int] | None:
        """MaNGOS world coordinates -> tile, using the client map's rotated axes.

        The client coordinate convention has world X running north-south and world Y
        running west-east (see tools/zone_scale.py). Keep coordinates on the source
        record; this function only returns their tile location.
        """
        bounds = (self.x_min, self.x_max, self.y_min, self.y_max)
        if self.world_map_id is None or map_id != self.world_map_id or any(v is None for v in bounds):
            return None
        assert self.x_min is not None and self.x_max is not None
        assert self.y_min is not None and self.y_max is not None
        if not (self.x_min < x <= self.x_max and self.y_min < y <= self.y_max):
            return None
        tile_x = int((self.y_max - y) / (self.y_max - self.y_min) * self.width)
        tile_y = int((self.x_max - x) / (self.x_max - self.x_min) * self.height)
        # A valid coordinate just above a minimum bound can round to exactly the
        # tile count in floating point; keep that point in the final raster cell.
        return min(self.width - 1, tile_x), min(self.height - 1, tile_y)

    def tile_to_pct(self, tile: tuple[int, int]) -> tuple[float, float]:
        return tile[0] / self.width * 100, tile[1] / self.height * 100

    def submap(self, name: str) -> SubMap | None:
        return next((s for s in self.submaps if s.name.lower() == name.lower()), None)

    def sub_to_tile(self, map_name: str, x_pct: float, y_pct: float) -> tuple[int, int]:
        """Coordinates given on a sub-map (Thunder Bluff's own map) -> tile of the zone."""
        sub = self.submap(map_name)
        if sub is None:
            return self.pct_to_tile(x_pct, y_pct)
        zx = sub.center_x_pct + (x_pct - 50) / 100 * sub.width_pct
        zy = sub.center_y_pct + (y_pct - 50) / 100 * sub.height_pct
        return self.pct_to_tile(zx, zy)


def ticks_to_seconds(ticks: int) -> float:
    return ticks * TICK_SECONDS


def load_geometry(pack_dir: Path | str) -> Geometry:
    data = json.loads((Path(pack_dir) / "zone.json").read_text("utf-8"))
    y = data["yards"]
    subs = tuple(SubMap(s["name"], s["in_zone"]["center_x_pct"], s["in_zone"]["center_y_pct"],
                        s["in_zone"]["width_pct"], s["in_zone"]["height_pct"]) for s in data["submaps"])
    return Geometry(data["name"], y["east_west"], y["north_south"], subs,
                    world_map_id=y["map_id"], x_min=y["x_min"], x_max=y["x_max"],
                    y_min=y["y_min"], y_max=y["y_max"])
