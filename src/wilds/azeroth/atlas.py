"""Viewport renderer for the static, source-labelled Mulgore atlas."""

from __future__ import annotations

import math
from collections import OrderedDict, defaultdict
from dataclasses import dataclass

import pygame

from .catalog import AtlasCatalog, CatalogEntry
from .scale import CHUNK
from .terrain import Terrain
from .world import ZoneWorld

TERRAIN_COLORS = {
    Terrain.GRASS: (98, 160, 72), Terrain.TALL_GRASS: (70, 130, 58),
    Terrain.DRY_GRASS: (186, 176, 92), Terrain.DIRT: (150, 112, 70),
    Terrain.ROAD: (204, 178, 120), Terrain.MESA: (158, 130, 108),
    Terrain.BOULDER: (110, 104, 112), Terrain.MOUNTAIN: (92, 66, 44),
    Terrain.CLIFF: (122, 86, 54), Terrain.WATER: (54, 96, 168),
    Terrain.SHALLOWS: (104, 150, 200), Terrain.VOID: (22, 22, 30),
}
_MACRO_COLORS = {
    "g": TERRAIN_COLORS[Terrain.GRASS],
    "d": TERRAIN_COLORS[Terrain.DRY_GRASS],
    "r": TERRAIN_COLORS[Terrain.MESA],
    "m": TERRAIN_COLORS[Terrain.MOUNTAIN],
    "v": TERRAIN_COLORS[Terrain.VOID],
}
_MARKER_COLORS = {
    "npc": (238, 76, 82), "creature": (80, 198, 244),
    "gameobject": (246, 210, 76), "landmark": (244, 244, 236),
    "quest": (195, 130, 245), "lore": (170, 183, 202),
}


@dataclass(frozen=True)
class AtlasFilters:
    npcs: bool = True
    creatures: bool = True
    gameobjects: bool = True
    landmarks: bool = True
    wiki_only: bool = False
    approximate: bool = True
    edge_ambiguous: bool = False
    uncertain_era: bool = False
    quests: bool = False
    lore: bool = False
    approximate_roads: bool = False


class MulgoreAtlasRenderer:
    """Draw only viewport terrain and catalog entries onto a pygame surface.

    ``camera_x`` and ``camera_y`` are world tiles at the viewport centre. Zoom is
    snapped to eighth-pixel overview buckets and quarter-pixel detailed buckets so
    cached surfaces align exactly with their screen positions.
    """

    def __init__(self, world: ZoneWorld, catalog: AtlasCatalog) -> None:
        self.world = world
        self.catalog = catalog
        self._chunk_surfaces: OrderedDict[tuple[int, int, int], pygame.Surface] = OrderedDict()
        self._overview_surfaces: OrderedDict[int, pygame.Surface] = OrderedDict()
        self._overview_base: pygame.Surface | None = None
        self._cluster_font: pygame.font.Font | None = None
        self.chunk_surface_limit = 128
        self.overview_surface_limit = 4

    @staticmethod
    def effective_scale(pixels_per_tile: float) -> float:
        if pixels_per_tile <= 0:
            raise ValueError("pixels_per_tile must be positive")
        if pixels_per_tile < 1:
            return max(0.125, round(pixels_per_tile * 8) / 8)
        return max(1.0, round(pixels_per_tile * 4) / 4)

    def _overview(self, scale: float) -> pygame.Surface:
        cache_key = round(scale * 8)
        surface = self._overview_surfaces.get(cache_key)
        if surface is not None:
            self._overview_surfaces.move_to_end(cache_key)
            return surface
        if self._overview_base is None:
            macro = self.world.terrain.macro
            base = pygame.Surface((macro.width, macro.height), depth=32)
            pixels = pygame.PixelArray(base)
            mapped = {char: base.map_rgb(color) for char, color in _MACRO_COLORS.items()}
            lake = self.world.terrain._lake
            water = base.map_rgb(TERRAIN_COLORS[Terrain.WATER])
            for y, row in enumerate(macro.rows):
                for x, char in enumerate(row):
                    pixels[x, y] = water if (x, y) in lake else mapped.get(char, mapped["v"])
            del pixels
            self._overview_base = base
        geo = self.world.geo
        size = (max(1, round(geo.width * scale)), max(1, round(geo.height * scale)))
        surface = pygame.transform.scale(self._overview_base, size)
        self._overview_surfaces[cache_key] = surface
        while len(self._overview_surfaces) > self.overview_surface_limit:
            self._overview_surfaces.popitem(last=False)
        return surface

    def _chunk_surface(self, cx: int, cy: int, scale: float) -> pygame.Surface:
        cache_key = (cx, cy, round(scale * 4))
        surface = self._chunk_surfaces.get(cache_key)
        if surface is not None:
            self._chunk_surfaces.move_to_end(cache_key)
            return surface
        data = self.world.chunk(cx, cy)
        base = pygame.Surface((CHUNK, CHUNK), depth=32)
        pixels = pygame.PixelArray(base)
        mapped = {kind: base.map_rgb(color) for kind, color in TERRAIN_COLORS.items()}
        for y in range(CHUNK):
            start = y * CHUNK
            for x in range(CHUNK):
                pixels[x, y] = mapped[Terrain(data[start + x])]
        del pixels
        side = max(1, round(CHUNK * scale))
        surface = base if side == CHUNK else pygame.transform.scale(base, (side, side))
        self._chunk_surfaces[cache_key] = surface
        while len(self._chunk_surfaces) > self.chunk_surface_limit:
            self._chunk_surfaces.popitem(last=False)
        return surface

    @staticmethod
    def _allowed(entry: CatalogEntry, filters: AtlasFilters) -> bool:
        if entry.kind == "npc" and not filters.npcs:
            return False
        if entry.kind == "creature" and not filters.creatures:
            return False
        if entry.kind == "gameobject" and not filters.gameobjects:
            return False
        if entry.kind == "landmark" and not filters.landmarks:
            return False
        if entry.kind == "quest" and not filters.quests:
            return False
        if entry.kind == "lore" and not filters.lore:
            return False
        is_wiki_only = entry.spawn is None and entry.key.startswith("wiki:")
        if is_wiki_only and not filters.wiki_only:
            return False
        if is_wiki_only and entry.era_status in ("unknown", "later_era") and not filters.uncertain_era:
            return False
        if entry.coordinate_status == "approximate" and not filters.approximate:
            return False
        if entry.spawn is not None and entry.spawn.zone_status == "edge_ambiguous" and not filters.edge_ambiguous:
            return False
        return True

    @staticmethod
    def _marker_center(entry: CatalogEntry, origin_x: float, origin_y: float, scale: float) -> tuple[int, int]:
        assert entry.tile is not None
        return round(origin_x + (entry.tile[0] + 0.5) * scale), round(origin_y + (entry.tile[1] + 0.5) * scale)

    def _draw_marker(self, surface: pygame.Surface, entry: CatalogEntry, point: tuple[int, int], scale: float,
                     selected: bool = False) -> None:
        x, y = point
        base_radius = min(10, max(3, round(2.5 * math.sqrt(scale))))
        color = _MARKER_COLORS.get(entry.kind, _MARKER_COLORS["landmark"])
        if entry.coordinate_status == "approximate":
            color = (244, 162, 70)
        if entry.key.startswith("wiki:"):
            color = (190, 136, 246)
        black = (22, 24, 28)
        if entry.kind in ("npc", "creature"):
            pygame.draw.circle(surface, black, (x, y), base_radius + 1)
            pygame.draw.circle(surface, color, (x, y), base_radius)
        elif entry.kind == "gameobject":
            rect = pygame.Rect(x - base_radius, y - base_radius, base_radius * 2 + 1, base_radius * 2 + 1)
            pygame.draw.rect(surface, black, rect.inflate(2, 2))
            pygame.draw.rect(surface, color, rect)
        else:
            points = ((x, y - base_radius - 1), (x + base_radius + 1, y),
                      (x, y + base_radius + 1), (x - base_radius - 1, y))
            pygame.draw.polygon(surface, black, points)
            inner = ((x, y - base_radius), (x + base_radius, y),
                     (x, y + base_radius), (x - base_radius, y))
            pygame.draw.polygon(surface, color, inner)
        if entry.coordinate_status == "source_map":
            pygame.draw.circle(surface, (178, 126, 238), (x, y), base_radius + 3, 1)
        if selected:
            pygame.draw.circle(surface, (255, 255, 255), (x, y), base_radius + 5, 2)

    @staticmethod
    def _draw_dashed_line(surface: pygame.Surface, color: tuple[int, int, int], start: tuple[int, int],
                          end: tuple[int, int], dash: int = 8, gap: int = 5, width: int = 2) -> None:
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 0:
            return
        ux, uy = dx / length, dy / length
        offset = 0.0
        while offset < length:
            stop = min(length, offset + dash)
            a = (round(start[0] + ux * offset), round(start[1] + uy * offset))
            b = (round(start[0] + ux * stop), round(start[1] + uy * stop))
            pygame.draw.line(surface, color, a, b, width)
            offset = stop + gap

    def _draw_approximate_roads(self, surface: pygame.Surface, viewport: pygame.Rect,
                                origin_x: float, origin_y: float, scale: float) -> None:
        for road in self.catalog.approximate_roads:
            start_spec, end_spec = road.get("from"), road.get("to")
            if not isinstance(start_spec, (list, tuple)) or not isinstance(end_spec, (list, tuple)):
                continue
            try:
                a_tile = self.world.geo.pct_to_tile(float(start_spec[1]), float(start_spec[2]))
                b_tile = self.world.geo.pct_to_tile(float(end_spec[1]), float(end_spec[2]))
            except (IndexError, TypeError, ValueError):
                continue
            a = (round(origin_x + (a_tile[0] + 0.5) * scale), round(origin_y + (a_tile[1] + 0.5) * scale))
            b = (round(origin_x + (b_tile[0] + 0.5) * scale), round(origin_y + (b_tile[1] + 0.5) * scale))
            if viewport.inflate(24, 24).clipline(a, b):
                self._draw_dashed_line(surface, (238, 190, 106), a, b)

    def render(self, surface: pygame.Surface, viewport: pygame.Rect | tuple[int, int, int, int],
               camera_x: float, camera_y: float, pixels_per_tile: float,
               filters: AtlasFilters, selected_key: str | None = None) -> None:
        """Render a camera-centred map viewport and visible markers onto ``surface``."""
        viewport = pygame.Rect(viewport)
        if viewport.width <= 0 or viewport.height <= 0:
            return
        scale = self.effective_scale(pixels_per_tile)
        origin_x = viewport.centerx - camera_x * scale
        origin_y = viewport.centery - camera_y * scale
        old_clip = surface.get_clip()
        surface.set_clip(viewport)
        surface.fill(TERRAIN_COLORS[Terrain.VOID], viewport)

        if scale < 1:
            overview = self._overview(scale)
            map_rect = pygame.Rect(round(origin_x), round(origin_y), overview.get_width(), overview.get_height())
            surface.blit(overview, map_rect)
        else:
            geo = self.world.geo
            left = max(0, math.floor((viewport.left - origin_x) / scale))
            top = max(0, math.floor((viewport.top - origin_y) / scale))
            right = min(geo.width, math.ceil((viewport.right - origin_x) / scale))
            bottom = min(geo.height, math.ceil((viewport.bottom - origin_y) / scale))
            if right > left and bottom > top:
                min_cx, max_cx = left // CHUNK, (right - 1) // CHUNK
                min_cy, max_cy = top // CHUNK, (bottom - 1) // CHUNK
                for cy in range(min_cy, max_cy + 1):
                    for cx in range(min_cx, max_cx + 1):
                        chunk = self._chunk_surface(cx, cy, scale)
                        target = (round(origin_x + cx * CHUNK * scale),
                                  round(origin_y + cy * CHUNK * scale))
                        surface.blit(chunk, target)

        tile_left = max(0, math.floor((viewport.left - origin_x) / scale))
        tile_top = max(0, math.floor((viewport.top - origin_y) / scale))
        tile_right = min(self.world.geo.width, math.ceil((viewport.right - origin_x) / scale))
        tile_bottom = min(self.world.geo.height, math.ceil((viewport.bottom - origin_y) / scale))
        entries = [entry for entry in self.catalog.visible((tile_left, tile_top, tile_right, tile_bottom))
                   if self._allowed(entry, filters)]
        if filters.approximate_roads:
            self._draw_approximate_roads(surface, viewport, origin_x, origin_y, scale)

        selected = next((entry for entry in entries if entry.key == selected_key), None)
        to_draw = [entry for entry in entries if entry.key != selected_key]
        if scale < 2:
            clusters: dict[tuple[int, int], list[CatalogEntry]] = defaultdict(list)
            for entry in to_draw:
                center = self._marker_center(entry, origin_x, origin_y, scale)
                if viewport.collidepoint(center):
                    clusters[(center[0] // 24, center[1] // 24)].append(entry)
            if self._cluster_font is None:
                self._cluster_font = pygame.font.Font(None, 14)
            for (bucket_x, bucket_y), cluster in clusters.items():
                if len(cluster) == 1:
                    self._draw_marker(surface, cluster[0], self._marker_center(cluster[0], origin_x, origin_y, scale), scale)
                    continue
                center = (bucket_x * 24 + 12, bucket_y * 24 + 12)
                pygame.draw.circle(surface, (24, 34, 42), center, 10)
                pygame.draw.circle(surface, (210, 225, 224), center, 10, 1)
                label = self._cluster_font.render(str(len(cluster)), True, (255, 255, 255))
                surface.blit(label, label.get_rect(center=center))
        else:
            for entry in to_draw:
                center = self._marker_center(entry, origin_x, origin_y, scale)
                if viewport.collidepoint(center):
                    self._draw_marker(surface, entry, center, scale)
        if selected is not None:
            center = self._marker_center(selected, origin_x, origin_y, scale)
            if viewport.collidepoint(center):
                self._draw_marker(surface, selected, center, scale, selected=True)
        surface.set_clip(old_clip)
