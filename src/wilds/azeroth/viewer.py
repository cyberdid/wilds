"""Standalone pygame viewer for a static Mulgore world atlas."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pygame

from .atlas import AtlasFilters, MulgoreAtlasRenderer
from .catalog import AtlasCatalog, CatalogEntry, load_catalog
from .scale import Geometry, load_geometry
from .world import ZoneWorld

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACK_DIR = ROOT / "data/azeroth/mulgore"
DEFAULT_SPAWN_FILE = ROOT / "data/azeroth/raw/mulgore-spawns.json"
PANEL_WIDTH = 300
PANEL_BG = (33, 37, 43)
PANEL_LINE = (66, 73, 81)
TEXT = (229, 232, 235)
MUTED = (165, 173, 182)


class MulgoreViewer:
    """A map observer with no dependency on the game's Simulation or GfxApp."""

    def __init__(self, pack_dir: Path | str = DEFAULT_PACK_DIR,
                 spawn_file: Path | str | None = DEFAULT_SPAWN_FILE,
                 size: tuple[int, int] = (1360, 820)) -> None:
        self.pack_dir = Path(pack_dir)
        self.spawn_file = Path(spawn_file) if spawn_file is not None else None
        self.geo: Geometry = load_geometry(self.pack_dir)
        self.world = ZoneWorld(self.pack_dir, seed=0, roads=False)
        self.catalog: AtlasCatalog = load_catalog(self.pack_dir, self.spawn_file)
        self.renderer = MulgoreAtlasRenderer(self.world, self.catalog)
        self.size = (max(900, size[0]), max(820, size[1]))
        self.running = False
        self.filters = AtlasFilters()
        self.selected_key: str | None = None
        self.search_query = ""
        self.search_focused = False
        self.search_results: list[CatalogEntry] = []
        self.search_result_offset = 0
        self.camera_x = self.geo.width / 2
        self.camera_y = self.geo.height / 2
        self.pixels_per_tile = 0.25
        self.map_viewport = pygame.Rect(0, 0, max(1, self.size[0] - PANEL_WIDTH), self.size[1])
        self._mouse_down: tuple[int, int] | None = None
        self._dragging = False
        self._entry_by_key = {entry.key: entry for entry in self.catalog.entries}
        self._font: pygame.font.Font | None = None
        self._small_font: pygame.font.Font | None = None
        self._title_font: pygame.font.Font | None = None
        self._search_rect = pygame.Rect(0, 0, 0, 0)
        self._result_rects: list[tuple[pygame.Rect, CatalogEntry]] = []
        self._filter_rects: list[tuple[pygame.Rect, str]] = []
        self.fit_zone()

    def fit_zone(self) -> None:
        width = max(1, self.size[0] - PANEL_WIDTH)
        height = max(1, self.size[1])
        self.map_viewport = pygame.Rect(0, 0, width, height)
        self.pixels_per_tile = self.renderer.effective_scale(
            min(width / self.geo.width, height / self.geo.height) * 0.94,
        )
        self.camera_x, self.camera_y = self.geo.width / 2, self.geo.height / 2
        self._clamp_camera()

    def _clamp_camera(self) -> None:
        scale = self.renderer.effective_scale(self.pixels_per_tile)
        half_width = self.map_viewport.width / (2 * scale)
        half_height = self.map_viewport.height / (2 * scale)
        if half_width * 2 >= self.geo.width:
            self.camera_x = self.geo.width / 2
        else:
            self.camera_x = min(self.geo.width - half_width, max(half_width, self.camera_x))
        if half_height * 2 >= self.geo.height:
            self.camera_y = self.geo.height / 2
        else:
            self.camera_y = min(self.geo.height - half_height, max(half_height, self.camera_y))

    def _ensure_fonts(self) -> None:
        if not pygame.font.get_init():
            pygame.font.init()
        if self._font is None:
            self._font = pygame.font.Font(None, 16)
            self._small_font = pygame.font.Font(None, 14)
            self._title_font = pygame.font.Font(None, 23)

    @property
    def selected_entry(self) -> CatalogEntry | None:
        return self._entry_by_key.get(self.selected_key or "")

    def _refresh_search(self) -> None:
        self.search_results = self.catalog.search(self.search_query)
        query = " ".join(self.search_query.casefold().split())
        if query:
            self.search_results.sort(key=lambda entry: (
                entry.title.casefold() != query,
                not entry.title.casefold().startswith(query),
                entry.spawn is None,
                entry.title.casefold(),
                entry.key,
            ))
        self.search_result_offset = 0

    def _select(self, entry: CatalogEntry) -> None:
        self.selected_key = entry.key
        if entry.tile is not None:
            self.camera_x, self.camera_y = entry.tile
            if self.pixels_per_tile < 2:
                self.pixels_per_tile = 2.0
            self._clamp_camera()

    def _toggle_search(self, active: bool) -> None:
        self.search_focused = active
        if active:
            pygame.key.start_text_input()
        else:
            pygame.key.stop_text_input()

    def _zoom_at(self, screen_point: tuple[int, int], steps: float) -> None:
        old_scale = self.renderer.effective_scale(self.pixels_per_tile)
        requested = min(12.0, max(0.125, old_scale * (1.2 ** steps)))
        new_scale = self.renderer.effective_scale(requested)
        world_x = self.camera_x + (screen_point[0] - self.map_viewport.centerx) / old_scale
        world_y = self.camera_y + (screen_point[1] - self.map_viewport.centery) / old_scale
        self.camera_x = world_x - (screen_point[0] - self.map_viewport.centerx) / new_scale
        self.camera_y = world_y - (screen_point[1] - self.map_viewport.centery) / new_scale
        self.pixels_per_tile = new_scale
        self._clamp_camera()

    def _visible_entries(self) -> list[CatalogEntry]:
        scale = self.renderer.effective_scale(self.pixels_per_tile)
        origin_x = self.map_viewport.centerx - self.camera_x * scale
        origin_y = self.map_viewport.centery - self.camera_y * scale
        bounds = (
            max(0, math.floor((self.map_viewport.left - origin_x) / scale)),
            max(0, math.floor((self.map_viewport.top - origin_y) / scale)),
            min(self.geo.width, math.ceil((self.map_viewport.right - origin_x) / scale)),
            min(self.geo.height, math.ceil((self.map_viewport.bottom - origin_y) / scale)),
        )
        return [entry for entry in self.catalog.visible(bounds)
                if self.renderer._allowed(entry, self.filters)]

    def _map_click(self, position: tuple[int, int]) -> None:
        scale = self.renderer.effective_scale(self.pixels_per_tile)
        origin_x = self.map_viewport.centerx - self.camera_x * scale
        origin_y = self.map_viewport.centery - self.camera_y * scale
        entries = self._visible_entries()
        if scale < 2:
            clusters: dict[tuple[int, int], list[CatalogEntry]] = {}
            for entry in entries:
                center = self.renderer._marker_center(entry, origin_x, origin_y, scale)
                bucket = (center[0] // 24, center[1] // 24)
                clusters.setdefault(bucket, []).append(entry)
            for bucket, group in clusters.items():
                if len(group) < 2:
                    continue
                center = (bucket[0] * 24 + 12, bucket[1] * 24 + 12)
                if math.dist(position, center) <= 14:
                    self.camera_x = sum(entry.tile[0] for entry in group if entry.tile is not None) / len(group)
                    self.camera_y = sum(entry.tile[1] for entry in group if entry.tile is not None) / len(group)
                    self.pixels_per_tile = min(12.0, max(2.0, scale * 2.5))
                    self._clamp_camera()
                    return
        candidates = []
        for entry in entries:
            center = self.renderer._marker_center(entry, origin_x, origin_y, scale)
            distance = math.dist(position, center)
            if distance <= max(9, min(16, round(scale * 0.8) + 7)):
                candidates.append((distance, entry.title.casefold(), entry))
        if candidates:
            self._select(min(candidates, key=lambda item: (item[0], item[1]))[2])
        else:
            self.selected_key = None

    def _handle_panel_click(self, position: tuple[int, int]) -> bool:
        if self._search_rect.collidepoint(position):
            self._toggle_search(True)
            return True
        for rect, entry in self._result_rects:
            if rect.collidepoint(position):
                self._select(entry)
                return True
        for rect, field_name in self._filter_rects:
            if rect.collidepoint(position):
                self.filters = replace(self.filters, **{field_name: not getattr(self.filters, field_name)})
                return True
        return False

    def _handle_key(self, event: pygame.event.Event) -> None:
        if event.key == pygame.K_ESCAPE:
            if self.search_focused:
                self.search_query = ""
                self._refresh_search()
                self._toggle_search(False)
            elif self.selected_key is not None:
                self.selected_key = None
            return
        if self.search_focused:
            if event.key == pygame.K_BACKSPACE:
                self.search_query = self.search_query[:-1]
                self._refresh_search()
            elif event.key == pygame.K_RETURN and self.search_results:
                index = min(self.search_result_offset, len(self.search_results) - 1)
                self._select(self.search_results[index])
                self._toggle_search(False)
            elif event.key == pygame.K_DOWN and self.search_results:
                self.search_result_offset = min(len(self.search_results) - 1,
                                                self.search_result_offset + 1)
            elif event.key == pygame.K_UP and self.search_results:
                self.search_result_offset = max(0, self.search_result_offset - 1)
            return
        if event.key == pygame.K_h:
            self.fit_zone()
            return
        if event.key == pygame.K_SLASH and not self.search_focused:
            self._toggle_search(True)
            return
        if event.key == pygame.K_q and not self.search_focused:
            self.running = False
            return

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return
        if event.type == pygame.VIDEORESIZE:
            self.size = (max(900, event.w), max(820, event.h))
            self.fit_zone()
            return
        if event.type == pygame.KEYDOWN:
            self._handle_key(event)
            return
        if event.type == pygame.TEXTINPUT and self.search_focused:
            self.search_query = (self.search_query + event.text)[:120]
            self._refresh_search()
            return
        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()
            if not self.map_viewport.collidepoint(mouse_pos):
                if 120 <= mouse_pos[1] <= 220:
                    self.search_result_offset = max(
                        0, min(max(0, len(self.search_results) - 4), self.search_result_offset - event.y),
                    )
                return
            if self.search_focused:
                self._toggle_search(False)
            self._zoom_at(mouse_pos, event.y)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._mouse_down = event.pos
            self._dragging = False
            return
        if (event.type == pygame.MOUSEMOTION and self._mouse_down is not None
                and self.map_viewport.collidepoint(self._mouse_down)):
            if self._dragging or math.dist(event.pos, self._mouse_down) >= 4:
                self._dragging = True
                scale = self.renderer.effective_scale(self.pixels_per_tile)
                self.camera_x -= event.rel[0] / scale
                self.camera_y -= event.rel[1] / scale
                self._clamp_camera()
            return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._mouse_down is not None:
            dragged = self._dragging
            self._mouse_down = None
            self._dragging = False
            if dragged:
                return
            if self.map_viewport.collidepoint(event.pos):
                if self.search_focused:
                    self._toggle_search(False)
                self._map_click(event.pos)
            else:
                self._handle_panel_click(event.pos)
            return
        # Compatibility with SDL builds that emit wheel buttons instead of MOUSEWHEEL.
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
            self._zoom_at(pygame.mouse.get_pos(), 1 if event.button == 4 else -1)

    @staticmethod
    def _fit_text(text: str, font: pygame.font.Font, width: int) -> list[str]:
        words = str(text).replace("\n", " ").split()
        if not words:
            return []
        lines: list[str] = []
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if font.size(candidate)[0] <= width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
        return lines

    def _text(self, surface: pygame.Surface, text: str, pos: tuple[int, int], color: tuple[int, int, int] = TEXT,
              font: pygame.font.Font | None = None, max_width: int | None = None,
              max_lines: int | None = None, line_height: int | None = None) -> int:
        self._ensure_fonts()
        font = font or self._font
        assert font is not None
        x, y = pos
        lines = self._fit_text(text, font, max_width) if max_width else str(text).splitlines() or [""]
        if max_lines is not None:
            lines = lines[:max_lines]
        step = line_height or font.get_linesize()
        for line in lines:
            surface.blit(font.render(line, True, color), (x, y))
            y += step
        return y

    def _draw_marker_legend(self, surface: pygame.Surface, x: int, y: int) -> None:
        samples = [("npc", (244, 76, 82)), ("creature", (80, 198, 244)),
                   ("gameobject", (246, 210, 76)), ("landmark", (244, 244, 236))]
        for index, (kind, color) in enumerate(samples):
            sx = x + (index % 2) * 132
            sy = y + (index // 2) * 18
            center = (sx + 7, sy + 7)
            if kind == "npc":
                pygame.draw.circle(surface, color, center, 5)
            elif kind == "creature":
                pygame.draw.polygon(surface, color, ((center[0], sy + 1), (sx + 13, sy + 13), (sx + 1, sy + 13)))
            elif kind == "gameobject":
                pygame.draw.rect(surface, color, pygame.Rect(sx + 2, sy + 2, 11, 11))
            else:
                pygame.draw.polygon(surface, color, ((center[0], sy), (sx + 14, center[1]),
                                                      (center[0], sy + 14), (sx, center[1])))
            self._text(surface, kind.title(), (sx + 19, sy), MUTED, self._small_font)

    def _draw_details(self, surface: pygame.Surface, panel_x: int, top: int, bottom: int) -> None:
        self._text(surface, "SELECTED ENTRY", (panel_x + 12, top), MUTED, self._small_font)
        content_top = top + 18
        available = max(0, bottom - content_top)
        clip = pygame.Rect(panel_x + 10, content_top, PANEL_WIDTH - 20, available)
        old_clip = surface.get_clip()
        surface.set_clip(clip)
        entry = self.selected_entry
        if entry is None:
            self._text(surface, "Search or select a map marker.", (panel_x + 12, content_top + 2), TEXT,
                       self._small_font, max_width=PANEL_WIDTH - 24)
            self._text(surface, "Unplaced records stay searchable.", (panel_x + 12, content_top + 20), MUTED,
                       self._small_font, max_width=PANEL_WIDTH - 24)
            surface.set_clip(old_clip)
            return
        y = content_top + 1
        y = self._text(surface, entry.title, (panel_x + 12, y), TEXT, self._font,
                       max_width=PANEL_WIDTH - 24, max_lines=2, line_height=16)
        state = f"{entry.kind} | {entry.era_status} | {entry.coordinate_status}"
        y = self._text(surface, state, (panel_x + 12, y + 1), MUTED, self._small_font,
                       max_width=PANEL_WIDTH - 24, max_lines=2, line_height=13)
        if entry.spawn is not None:
            spawn = entry.spawn
            y = self._text(surface, f"spawn #{spawn.spawn_id}  template #{spawn.template_id}",
                           (panel_x + 12, y + 1), TEXT, self._small_font, max_width=PANEL_WIDTH - 24)
            y = self._text(surface, f"world {spawn.world_x:.2f}, {spawn.world_y:.2f}, {spawn.world_z:.2f}",
                           (panel_x + 12, y), TEXT, self._small_font, max_width=PANEL_WIDTH - 24)
            tile = f"tile {spawn.tile[0]}, {spawn.tile[1]}" if spawn.tile else "no tile"
            y = self._text(surface, f"{tile} | {spawn.zone_status}", (panel_x + 12, y), MUTED, self._small_font)
            template = entry.properties.get("template", {})
            if spawn.kind == "creature":
                level = f"level {template.get('min_level', 0)}-{template.get('max_level', 0)}"
                flags = f"NPC flags {template.get('npc_flags', 0)}"
                y = self._text(surface, f"{level} | {flags}", (panel_x + 12, y), MUTED, self._small_font)
            else:
                y = self._text(surface, f"object type {template.get('gameobject_type', '?')} | state {spawn.object_state}",
                               (panel_x + 12, y), MUTED, self._small_font)
            if spawn.condition_ids:
                y = self._text(surface, "conditions: " + ", ".join(spawn.condition_ids),
                               (panel_x + 12, y), MUTED, self._small_font,
                               max_width=PANEL_WIDTH - 24, max_lines=2)
        else:
            if entry.template_id is not None:
                y = self._text(surface, f"template #{entry.template_id}", (panel_x + 12, y), TEXT,
                               self._small_font)
            if entry.source_coordinates:
                map_name, x, y_coord = entry.source_coordinates[0]
                y = self._text(surface, f"map point: {map_name} {x:.2f}, {y_coord:.2f}",
                               (panel_x + 12, y), TEXT, self._small_font, max_width=PANEL_WIDTH - 24)
            if entry.coordinate_basis:
                y = self._text(surface, entry.coordinate_basis, (panel_x + 12, y), MUTED, self._small_font,
                               max_width=PANEL_WIDTH - 24, max_lines=2)
            info = entry.info
            info_line = " | ".join(f"{key}: {value}" for key, value in info.items()
                                   if key in ("location", "level", "race", "faction", "expansion"))
            if info_line:
                y = self._text(surface, info_line, (panel_x + 12, y), MUTED, self._small_font,
                               max_width=PANEL_WIDTH - 24, max_lines=2)
        if entry.description:
            y = self._text(surface, entry.description, (panel_x + 12, y + 1), MUTED, self._small_font,
                           max_width=PANEL_WIDTH - 24, max_lines=3, line_height=13)
        revision = entry.source_revision
        if entry.source_id.startswith("mangoszero"):
            revision = revision[:12]
        self._text(surface, f"source {entry.source_id} / {revision}", (panel_x + 12, y + 1),
                   MUTED, self._small_font, max_width=PANEL_WIDTH - 24, max_lines=2)
        surface.set_clip(old_clip)

    def _draw_panel(self, surface: pygame.Surface) -> None:
        self._ensure_fonts()
        width, height = surface.get_size()
        panel_x = width - PANEL_WIDTH
        panel = pygame.Rect(panel_x, 0, PANEL_WIDTH, height)
        pygame.draw.rect(surface, PANEL_BG, panel)
        pygame.draw.line(surface, PANEL_LINE, panel.topleft, panel.bottomleft, 1)
        self._text(surface, "Mulgore atlas", (panel_x + 12, 11), TEXT, self._title_font)
        pygame.draw.rect(surface, (62, 88, 68), pygame.Rect(panel_x + 12, 40, 152, 19), border_radius=5)
        self._text(surface, "VANILLA 1.12.1-1.12.3", (panel_x + 17, 43), (220, 238, 220), self._small_font)
        pygame.draw.rect(surface, (78, 66, 43), pygame.Rect(panel_x + 170, 40, 118, 19), border_radius=5)
        self._text(surface, "PROCEDURAL PREVIEW", (panel_x + 174, 43), (250, 222, 172), self._small_font)

        self._search_rect = pygame.Rect(panel_x + 12, 68, PANEL_WIDTH - 24, 30)
        pygame.draw.rect(surface, (21, 24, 29), self._search_rect, border_radius=5)
        pygame.draw.rect(surface, (102, 147, 199) if self.search_focused else PANEL_LINE,
                         self._search_rect, 1, border_radius=5)
        search_text = self.search_query or ("Type to search (press /)" if not self.search_focused else "")
        self._text(surface, search_text, (self._search_rect.x + 8, self._search_rect.y + 7),
                   TEXT if self.search_query else MUTED, self._small_font, max_width=self._search_rect.width - 16)
        self._text(surface, "RESULTS" if self.search_query else "CATALOG SEARCH", (panel_x + 12, 105), MUTED,
                   self._small_font)
        result_top, row_height, visible_rows = 122, 22, 4
        self._result_rects = []
        if self.search_query:
            rows = self.search_results[self.search_result_offset:self.search_result_offset + visible_rows]
            for index, entry in enumerate(rows):
                rect = pygame.Rect(panel_x + 10, result_top + index * row_height, PANEL_WIDTH - 20, row_height - 1)
                if entry.key == self.selected_key:
                    pygame.draw.rect(surface, (55, 74, 92), rect, border_radius=3)
                self._text(surface, entry.title, (rect.x + 5, rect.y + 4), TEXT, self._small_font,
                           max_width=rect.width - 54, max_lines=1)
                badge = "unplaced" if entry.tile is None else entry.kind
                badge_surface = self._small_font.render(badge, True, MUTED)
                surface.blit(badge_surface, (rect.right - badge_surface.get_width() - 5, rect.y + 4))
                self._result_rects.append((rect, entry))
            if not self.search_results:
                self._text(surface, "No matches", (panel_x + 14, result_top + 5), MUTED, self._small_font)
            elif len(self.search_results) > visible_rows:
                self._text(surface, f"{self.search_result_offset + 1}-{min(len(self.search_results), self.search_result_offset + visible_rows)} of {len(self.search_results)}",
                           (panel_x + 12, result_top + visible_rows * row_height), MUTED, self._small_font)
        else:
            spawn_count = self.catalog.coverage.get("catalog", {}).get("spawn_instances", 0)
            self._text(surface, f"{spawn_count:,} sourced spawn records", (panel_x + 12, result_top + 5),
                       MUTED, self._small_font)

        self._text(surface, "MAP LAYERS", (panel_x + 12, 224), MUTED, self._small_font)
        filter_items = [
            ("npcs", "NPC spawns"), ("creatures", "Other creatures"),
            ("gameobjects", "Gameobjects"), ("landmarks", "Landmarks / features"),
            ("wiki_only", "Wiki-only / unplaced"), ("approximate", "Approximate points"),
            ("edge_ambiguous", "Edge-ambiguous spawns"), ("uncertain_era", "Unknown / later era"),
            ("approximate_roads", "Approximate routes (dashed)"),
        ]
        self._filter_rects = []
        for index, (field_name, label) in enumerate(filter_items):
            y = 242 + index * 19
            rect = pygame.Rect(panel_x + 10, y, PANEL_WIDTH - 20, 18)
            active = bool(getattr(self.filters, field_name))
            box = pygame.Rect(panel_x + 13, y + 2, 13, 13)
            pygame.draw.rect(surface, (76, 127, 99) if active else (42, 46, 52), box, border_radius=2)
            pygame.draw.rect(surface, (116, 131, 137), box, 1, border_radius=2)
            if active:
                pygame.draw.line(surface, (240, 248, 241), (box.x + 3, box.y + 7), (box.x + 6, box.y + 10), 2)
                pygame.draw.line(surface, (240, 248, 241), (box.x + 6, box.y + 10), (box.x + 11, box.y + 3), 2)
            self._text(surface, label, (panel_x + 33, y + 2), TEXT if active else MUTED,
                       self._small_font, max_width=PANEL_WIDTH - 48)
            self._filter_rects.append((rect, field_name))

        self._text(surface, "LEGEND", (panel_x + 12, 418), MUTED, self._small_font)
        self._draw_marker_legend(surface, panel_x + 12, 435)
        y = 473
        pygame.draw.circle(surface, (178, 126, 238), (panel_x + 19, y + 6), 5, 1)
        self._text(surface, "ring = Wiki source-map coordinate", (panel_x + 31, y), MUTED, self._small_font)
        pygame.draw.polygon(surface, (244, 162, 70), ((panel_x + 14, y + 18), (panel_x + 20, y + 24),
                                                       (panel_x + 14, y + 30), (panel_x + 8, y + 24)))
        self._text(surface, "orange = approximate feature", (panel_x + 31, y + 18), MUTED, self._small_font)

        coverage_top = height - 122
        detail_bottom = max(520, coverage_top - 8)
        self._draw_details(surface, panel_x, 506, detail_bottom)
        pygame.draw.line(surface, PANEL_LINE, (panel_x + 10, coverage_top - 7), (width - 10, coverage_top - 7), 1)
        self._text(surface, "SOURCE COVERAGE", (panel_x + 12, coverage_top), MUTED, self._small_font)
        coverage = self.catalog.coverage
        imported = coverage.get("importer", {})
        tables = imported.get("spawn_tables", {})
        creatures = tables.get("creature", {})
        objects = tables.get("gameobject", {})
        joined = coverage.get("catalog", {})
        self._text(surface, f"DB: {creatures.get('included', 0):,} creatures + {objects.get('included', 0):,} objects",
                   (panel_x + 12, coverage_top + 16), MUTED, self._small_font,
                   max_width=PANEL_WIDTH - 22)
        inside = creatures.get("inside_mask", 0) + objects.get("inside_mask", 0)
        edge = creatures.get("edge_ambiguous", 0) + objects.get("edge_ambiguous", 0)
        self._text(surface, f"Mask: {inside:,} inside, {edge:,} edge-ambiguous",
                   (panel_x + 12, coverage_top + 30), MUTED, self._small_font,
                   max_width=PANEL_WIDTH - 22)
        self._text(surface, f"Wiki {joined.get('wiki_pages_loaded', 0):,}; exact ID joins {joined.get('wiki_pages_joined_by_exact_id', 0):,}; unplaced {joined.get('wiki_pages_unplaced', 0):,}",
                   (panel_x + 12, coverage_top + 44), MUTED, self._small_font,
                   max_width=PANEL_WIDTH - 22)
        unresolved = imported.get("unresolved_templates", {})
        self._text(surface, f"Unresolved templates: {sum(unresolved.values())}",
                   (panel_x + 12, coverage_top + 58), MUTED, self._small_font)
        self._text(surface, "Based upon the work of getmangos.eu (MaNGOSZero)",
                   (panel_x + 12, coverage_top + 72), MUTED, self._small_font,
                   max_width=PANEL_WIDTH - 22)
        self._text(surface, "World DB license: CC BY-NC-SA 3.0",
                   (panel_x + 12, coverage_top + 86), MUTED, self._small_font,
                   max_width=PANEL_WIDTH - 22)

    def draw(self, surface: pygame.Surface) -> None:
        self._ensure_fonts()
        width, height = surface.get_size()
        self.size = (width, height)
        self.map_viewport = pygame.Rect(0, 0, max(1, width - PANEL_WIDTH), height)
        self.renderer.render(surface, self.map_viewport, self.camera_x, self.camera_y,
                             self.pixels_per_tile, self.filters, self.selected_key)
        banner = pygame.Rect(12, 12, 236, 36)
        pygame.draw.rect(surface, (22, 27, 32), banner, border_radius=5)
        pygame.draw.rect(surface, (94, 106, 116), banner, 1, border_radius=5)
        self._text(surface, "PROCEDURAL PREVIEW", (banner.x + 9, banner.y + 4),
                   (250, 222, 172), self._small_font)
        self._text(surface, "north up  |  2 yards / tile", (banner.x + 9, banner.y + 19),
                   MUTED, self._small_font)
        scale = self.renderer.effective_scale(self.pixels_per_tile)
        status = pygame.Rect(10, height - 27, min(450, self.map_viewport.width - 20), 19)
        pygame.draw.rect(surface, (22, 27, 32), status, border_radius=4)
        self._text(surface, f"zoom {scale:.3g} px/tile  |  drag pan  |  wheel zoom  |  H fit  |  / search",
                   (status.x + 7, status.y + 3), MUTED, self._small_font, max_width=status.width - 12)
        self._draw_panel(surface)

    def run(self) -> None:
        pygame.init()
        pygame.display.set_caption("Mulgore Atlas — static Vanilla 1.12.x reference")
        screen = pygame.display.set_mode(self.size, pygame.RESIZABLE)
        clock = pygame.time.Clock()
        self.running = True
        while self.running:
            for event in pygame.event.get():
                self.handle_event(event)
                if event.type == pygame.VIDEORESIZE:
                    screen = pygame.display.set_mode(self.size, pygame.RESIZABLE)
            self.draw(screen)
            pygame.display.flip()
            clock.tick(60)
        pygame.quit()
