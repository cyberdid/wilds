"""Viewport renderer for the static, source-labelled Mulgore atlas."""

from __future__ import annotations

import math
from collections import OrderedDict, defaultdict
from dataclasses import dataclass

import pygame

from ..gfx.bank import SpriteBank
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
    edge_ambiguous: bool = True
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

    def __init__(self, world: ZoneWorld, catalog: AtlasCatalog, bank: SpriteBank | None = None) -> None:
        self.world = world
        self.catalog = catalog
        if bank is None:
            from ..gfx.sprites import load_azeroth

            bank = SpriteBank(load_azeroth())
        self.bank = bank
        self._chunk_surfaces: OrderedDict[tuple[int, int, int], pygame.Surface] = OrderedDict()
        self._overview_surfaces: OrderedDict[int, pygame.Surface] = OrderedDict()
        self._tile_surfaces: dict[tuple, pygame.Surface] = {}
        self._scaled_sprites: dict[tuple[str, int, int], pygame.Surface] = {}
        self._void_tile = pygame.Surface((16, 16), depth=32)
        self._void_tile.fill(TERRAIN_COLORS[Terrain.VOID])
        self._overview_base: pygame.Surface | None = None
        self._cluster_font: pygame.font.Font | None = None
        # Native-detail chunks use 16x art before scaling. Keep the viewport-sized
        # raster cache bounded so zooming around the full zone stays lightweight.
        self.chunk_surface_limit = 12
        self.overview_surface_limit = 4

    @staticmethod
    def effective_scale(pixels_per_tile: float) -> float:
        if pixels_per_tile <= 0:
            raise ValueError("pixels_per_tile must be positive")
        if pixels_per_tile < 1:
            return max(0.125, round(pixels_per_tile * 8) / 8)
        return max(1.0, round(pixels_per_tile * 4) / 4)

    @staticmethod
    def cluster_cell_size(scale: float) -> int:
        """Broaden count bubbles as more of the zone comes into view."""
        return max(24, min(128, round(24 / max(scale, 0.125))))

    @staticmethod
    def cluster_radius(scale: float) -> int:
        return max(8, min(16, round(8 / math.sqrt(max(scale, 0.125)))))

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
        native = pygame.Surface((CHUNK * 16, CHUNK * 16), depth=32)
        native.fill(TERRAIN_COLORS[Terrain.VOID])
        for y in range(CHUNK):
            start = y * CHUNK
            for x in range(CHUNK):
                terrain = Terrain(data[start + x])
                tile = self._terrain_tile(terrain, cx * CHUNK + x, cy * CHUNK + y)
                native.blit(tile, (x * 16, y * 16))
        side = max(1, round(CHUNK * scale))
        surface = native if native.get_size() == (side, side) else pygame.transform.scale(native, (side, side))
        self._chunk_surfaces[cache_key] = surface
        while len(self._chunk_surfaces) > self.chunk_surface_limit:
            self._chunk_surfaces.popitem(last=False)
        return surface

    def _variant_index(self, terrain: Terrain, x: int, y: int) -> int:
        bases = {
            Terrain.GRASS: "az.ground.grass", Terrain.TALL_GRASS: "az.ground.tall_grass",
            Terrain.DRY_GRASS: "az.ground.dry_grass", Terrain.DIRT: "az.ground.dirt",
            Terrain.ROAD: "az.ground.road", Terrain.MESA: "az.ground.mesa",
            Terrain.MOUNTAIN: "az.mountain.top", Terrain.CLIFF: "az.cliff.face",
            Terrain.WATER: "az.ground.water", Terrain.SHALLOWS: "az.ground.shallows",
        }
        base = bases.get(terrain)
        if base is None:
            base = "az.ground.grass"
        variants = len(self._sprite_variants(base))
        return ((x * 92821) ^ (y * 68917) ^ (x * y * 31)) % variants

    def _sprite_variants(self, base: str) -> list[str]:
        return self.bank.registry.variants(base)

    def _terrain_tile(self, terrain: Terrain, x: int, y: int) -> pygame.Surface:
        """Compose one native 16px terrain tile using original pixel art."""
        if terrain == Terrain.BOULDER:
            ground = Terrain.GRASS
            base = "az.ground.grass"
            index = self._variant_index(ground, x, y)
        else:
            base = {
                Terrain.GRASS: "az.ground.grass", Terrain.TALL_GRASS: "az.ground.tall_grass",
                Terrain.DRY_GRASS: "az.ground.dry_grass", Terrain.DIRT: "az.ground.dirt",
                Terrain.ROAD: "az.ground.road", Terrain.MESA: "az.ground.mesa",
                Terrain.MOUNTAIN: "az.mountain.top", Terrain.CLIFF: "az.cliff.face",
                Terrain.WATER: "az.ground.water", Terrain.SHALLOWS: "az.ground.shallows",
            }.get(terrain)
            if base is None:
                return self._void_tile
            index = self._variant_index(terrain, x, y)
        transitions = self._terrain_transitions(terrain, x, y)
        cache_key = (int(terrain), index, *transitions)
        result = self._tile_surfaces.get(cache_key)
        if result is None:
            sprite_name = self._sprite_variants(base)[index]
            result = self.bank.base(sprite_name)[0].copy()
            if terrain == Terrain.BOULDER:
                boulder_names = self._sprite_variants("az.boulder")
                boulder = self.bank.base(boulder_names[index % len(boulder_names)])[0]
                result.blit(boulder, (0, 0))
            for edge_name in transitions:
                result.blit(self.bank.base(edge_name)[0], (0, 0))
            self._tile_surfaces[cache_key] = result
        return result

    def _terrain_transitions(self, terrain: Terrain, x: int, y: int) -> tuple[str, ...]:
        """Blend tile edges with adjacent water, bare earth and cliff materials."""
        if terrain not in (Terrain.GRASS, Terrain.TALL_GRASS, Terrain.DRY_GRASS,
                           Terrain.DIRT, Terrain.ROAD, Terrain.MESA, Terrain.BOULDER):
            return ()
        edges = []
        neighbors = (("n", 0, -1), ("e", 1, 0), ("s", 0, 1), ("w", -1, 0))
        for direction, dx, dy in neighbors:
            neighbor = self.world.terrain.tile(x + dx, y + dy)
            kind = None
            if neighbor in (Terrain.WATER, Terrain.SHALLOWS):
                kind = "water"
            elif neighbor in (Terrain.CLIFF, Terrain.MOUNTAIN):
                kind = "cliff"
            elif neighbor == Terrain.DRY_GRASS and terrain in (Terrain.GRASS, Terrain.TALL_GRASS):
                kind = "drygrass"
            elif terrain == Terrain.DRY_GRASS and neighbor in (Terrain.GRASS, Terrain.TALL_GRASS):
                kind = "grass"
            elif neighbor in (Terrain.DIRT, Terrain.ROAD) and terrain in (
                    Terrain.GRASS, Terrain.TALL_GRASS, Terrain.DRY_GRASS):
                kind = "dirt"
            if kind is not None:
                edges.append(f"az.edge.{kind}.{direction}")
        return tuple(edges)

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

    def map_position(self, entry: CatalogEntry) -> tuple[float, float] | None:
        """Continuous world tile position; Wiki map pins use their cell centre."""
        if entry.spawn is not None:
            geo = self.world.geo
            if (geo.world_map_id == entry.spawn.map_id and geo.x_min is not None and geo.x_max is not None
                    and geo.y_min is not None and geo.y_max is not None):
                world_x = (geo.y_max - entry.spawn.world_y) / (geo.y_max - geo.y_min) * geo.width
                world_y = (geo.x_max - entry.spawn.world_x) / (geo.x_max - geo.x_min) * geo.height
                return world_x, world_y
        if entry.tile is not None:
            return entry.tile[0] + 0.5, entry.tile[1] + 0.5
        return None

    def _screen_anchor(self, entry: CatalogEntry, origin_x: float, origin_y: float,
                       scale: float) -> tuple[int, int]:
        """Use continuous DB world coordinates where available; Wiki points stay tile-based."""
        position = self.map_position(entry)
        if position is None:
            return round(origin_x), round(origin_y)
        return round(origin_x + position[0] * scale), round(origin_y + position[1] * scale)

    @staticmethod
    def _archetype(entry: CatalogEntry) -> str:
        template = entry.properties.get("template", {})
        if not isinstance(template, dict):
            template = {}
        text = " ".join((entry.title, entry.description, str(template.get("name", "")),
                         str(template.get("subname", "")), " ".join(entry.categories))).casefold()
        if entry.kind in ("npc", "creature"):
            if any(word in text for word in ("ghost", "spirit", "wraith", "haunt", "ancestral")):
                return "az.atlas.actor.spirit"
            if "quilboar" in text:
                return "az.atlas.actor.quilboar"
            if any(word in text for word in ("kodo", "kodo bull", "kodo calf")):
                return "az.atlas.actor.kodo"
            if any(word in text for word in ("plainstrider", "tallstrider", "strider")):
                return "az.atlas.actor.strider"
            if any(word in text for word in ("adder", "snake", "serpent")):
                return "az.atlas.actor.snake"
            if any(word in text for word in ("wolf", "cougar", "lion", "cat", "prowler")):
                return "az.atlas.actor.wolf"
            if any(word in text for word in ("boar", "squealer")):
                return "az.atlas.actor.boar"
            if any(word in text for word in ("eagle", "vulture", "hawk", "bird")):
                return "az.atlas.actor.bird"
            if any(word in text for word in ("rabbit", "mouse", "squirrel", "rat", "critter")):
                return "az.atlas.actor.critter"
            if entry.kind == "npc":
                if any(word in text for word in ("goblin", "venture", "foreman", "apothecary", "centaur")):
                    return "az.atlas.actor.humanoid"
                return "az.atlas.actor.tauren"
            return "az.atlas.actor.humanoid"
        if entry.kind == "gameobject":
            if any(word in text for word in ("peacebloom", "silverleaf", "earthroot", "mageroyal", "briarthorn",
                                               "bruiseweed", "steelbloom", "kingsblood", "prairie flower")):
                return "az.atlas.object.herb"
            if any(word in text for word in ("vein", "deposit", "ore")):
                return "az.atlas.object.ore"
            if any(word in text for word in ("fire", "bonfire", "brazier", "ember", "forge")):
                return "az.atlas.object.fire"
            if any(word in text for word in ("well", "water pump", "water trough")):
                return "az.atlas.object.well"
            if any(word in text for word in ("totem", "shrine", "moonkin stone")):
                return "az.atlas.object.totem"
            if "mailbox" in text:
                return "az.atlas.object.mailbox"
            if any(word in text for word in ("banner", "flag", "drum")):
                return "az.atlas.object.banner"
            if any(word in text for word in ("tent", "pavilion")):
                return "az.atlas.object.tent"
            if any(word in text for word in ("mine entrance", "cave entrance")):
                return "az.atlas.object.stone"
            if "outhouse" in text:
                return "az.atlas.object.generic"
            if any(word in text for word in ("hut", "shack", "lodge", "inn", "house")):
                return "az.atlas.object.hut"
            if any(word in text for word in ("barrel", "keg", "pitcher", "milk", "jug")):
                return "az.atlas.object.barrel"
            if any(word in text for word in ("crate", "goods", "supplies", "basket")):
                return "az.atlas.object.crate"
            if any(word in text for word in ("chest", "cache", "scroll", "egg", "map", "supply")):
                return "az.atlas.object.chest"
            if any(word in text for word in ("stone", "rock", "cairn", "elevator")):
                return "az.atlas.object.stone"
            return "az.atlas.object.generic"
        return ""

    def _draw_world_sprite(self, surface: pygame.Surface, entry: CatalogEntry,
                           anchor: tuple[int, int], scale: float, selected: bool = False) -> None:
        geometry = self._world_sprite_geometry(entry, anchor, scale)
        if geometry is None:
            self._draw_marker(surface, entry, anchor, scale, selected)
            return
        sprite, rect = geometry
        surface.blit(sprite, rect)
        if entry.spawn is not None and entry.spawn.zone_status == "edge_ambiguous":
            pygame.draw.circle(surface, (238, 162, 70), anchor, max(2, rect.width // 4), 1)
        if selected:
            color = (255, 250, 224)
            opaque_rect = sprite.get_bounding_rect().move(rect.topleft)
            pygame.draw.ellipse(surface, color, opaque_rect.inflate(max(6, rect.width // 2),
                                                                      max(5, rect.height // 4)), 1)

    def _world_sprite_geometry(self, entry: CatalogEntry, anchor: tuple[int, int],
                               scale: float) -> tuple[pygame.Surface, pygame.Rect] | None:
        name = self._archetype(entry)
        if not name or name not in self.bank.registry:
            return None
        variants = self._sprite_variants(name)
        spawn_id = entry.spawn.spawn_id if entry.spawn is not None else entry.template_id or 0
        variant = variants[spawn_id % len(variants)]
        sprite_art = self.bank.registry.get(variant)
        width = max(1, round(sprite_art.size[0] * scale / 16))
        height = max(1, round(sprite_art.size[1] * scale / 16))
        cache_key = (variant, width, height)
        sprite = self._scaled_sprites.get(cache_key)
        if sprite is None:
            source = self.bank.base(variant)[0]
            sprite = source if source.get_size() == (width, height) else pygame.transform.scale(source, (width, height))
            self._scaled_sprites[cache_key] = sprite
        source_anchor_x, source_anchor_y = sprite_art.ground_anchor
        anchor_x = round(source_anchor_x * width / sprite_art.size[0])
        anchor_y = round(source_anchor_y * height / sprite_art.size[1])
        rect = sprite.get_rect(topleft=(anchor[0] - anchor_x, anchor[1] - anchor_y))
        return sprite, rect

    def _world_sprite_hit(self, entry: CatalogEntry, anchor: tuple[int, int], scale: float,
                          point: tuple[int, int]) -> bool:
        geometry = self._world_sprite_geometry(entry, anchor, scale)
        if geometry is None:
            return False
        sprite, rect = geometry
        if not rect.collidepoint(point):
            return False
        return sprite.get_at((point[0] - rect.x, point[1] - rect.y)).a > 0

    def _draw_marker(self, surface: pygame.Surface, entry: CatalogEntry, point: tuple[int, int], scale: float,
                     selected: bool = False) -> None:
        x, y = point
        base_radius = min(10, max(3, round(2.5 * math.sqrt(scale))))
        color = _MARKER_COLORS.get(entry.kind, _MARKER_COLORS["landmark"])
        if entry.coordinate_status == "approximate":
            color = (244, 162, 70)
        if entry.key.startswith("wiki:"):
            color = (190, 136, 246)
        if entry.spawn is not None and entry.spawn.zone_status == "edge_ambiguous":
            color = (238, 162, 70)
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
                visible_chunks = (max_cx - min_cx + 1) * (max_cy - min_cy + 1)
                self.chunk_surface_limit = min(256, max(12, visible_chunks + max(2, visible_chunks // 4)))
                for cy in range(min_cy, max_cy + 1):
                    for cx in range(min_cx, max_cx + 1):
                        chunk = self._chunk_surface(cx, cy, scale)
                        target = (round(origin_x + cx * CHUNK * scale),
                                  round(origin_y + cy * CHUNK * scale))
                        surface.blit(chunk, target)

        # Let tall and wide art enter from just outside the viewport while its
        # bottom-centre anchor stays in the spatial query.
        art_margin = 2 if scale >= 2 else 0
        tile_left = max(0, math.floor((viewport.left - origin_x) / scale) - art_margin)
        tile_top = max(0, math.floor((viewport.top - origin_y) / scale) - art_margin)
        tile_right = min(self.world.geo.width, math.ceil((viewport.right - origin_x) / scale) + art_margin)
        tile_bottom = min(self.world.geo.height, math.ceil((viewport.bottom - origin_y) / scale) + art_margin)
        entries = [entry for entry in self.catalog.visible((tile_left, tile_top, tile_right, tile_bottom))
                   if self._allowed(entry, filters)]
        if filters.approximate_roads:
            self._draw_approximate_roads(surface, viewport, origin_x, origin_y, scale)

        selected = next((entry for entry in entries if entry.key == selected_key), None)
        to_draw = [entry for entry in entries if entry.key != selected_key]
        if scale < 2:
            clusters: dict[tuple[int, int], list[CatalogEntry]] = defaultdict(list)
            cell_size = self.cluster_cell_size(scale)
            radius = self.cluster_radius(scale)
            for entry in to_draw:
                center = self._screen_anchor(entry, origin_x, origin_y, scale)
                if viewport.collidepoint(center):
                    clusters[(center[0] // cell_size, center[1] // cell_size)].append(entry)
            if self._cluster_font is None:
                self._cluster_font = pygame.font.Font(None, 14)
            for (bucket_x, bucket_y), cluster in clusters.items():
                if len(cluster) == 1:
                    self._draw_marker(surface, cluster[0], self._screen_anchor(cluster[0], origin_x, origin_y, scale), scale)
                    continue
                center = (bucket_x * cell_size + cell_size // 2, bucket_y * cell_size + cell_size // 2)
                pygame.draw.circle(surface, (24, 34, 42), center, radius)
                pygame.draw.circle(surface, (210, 225, 224), center, radius, 1)
                label = self._cluster_font.render(str(len(cluster)), True, (255, 255, 255))
                surface.blit(label, label.get_rect(center=center))
        else:
            to_draw.sort(key=lambda entry: (self._screen_anchor(entry, origin_x, origin_y, scale)[1],
                                             entry.kind == "gameobject"))
            visible_art = viewport.inflate(max(8, round(4 * scale)), max(8, round(4 * scale)))
            for entry in to_draw:
                center = self._screen_anchor(entry, origin_x, origin_y, scale)
                if visible_art.collidepoint(center):
                    if entry.spawn is not None:
                        self._draw_world_sprite(surface, entry, center, scale)
                    else:
                        self._draw_marker(surface, entry, center, scale)
        if selected is not None:
            center = self._screen_anchor(selected, origin_x, origin_y, scale)
            if viewport.collidepoint(center):
                if selected.spawn is not None and scale >= 2:
                    self._draw_world_sprite(surface, selected, center, scale, selected=True)
                else:
                    self._draw_marker(surface, selected, center, scale, selected=True)
        surface.set_clip(old_clip)
