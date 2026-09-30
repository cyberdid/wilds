# Mulgore Static Atlas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build a local, full-scale 2D Mulgore atlas with a searchable catalog and individually addressable Vanilla 1.12.x creature/gameobject spawns, without a player or NPC movement.

**Architecture:** Import the pinned MaNGOSZero SQL rows into a local, ignored JSON snapshot, preserve source coordinates and confidence, and join existing Wiki text only by numeric template ID. Extend the existing world geometry and chunked terrain read path, then render it in a separate pygame atlas viewer with viewport culling, layer filters, search, and a detail panel.

**Tech Stack:** Python 3.12, existing pygame-ce, existing ZoneWorld/ZoneTerrain, standard-library SQL INSERT reader, JSON data files. No new runtime dependencies.

**Spec:** docs/superpowers/specs/2026-09-30-mulgore-static-atlas-design.md

## Global Constraints

- One tile represents 2 yards; the current zone bounds are approximately 5450 × 3633 yards.
- Pin MaNGOSZero database source revision 325948a78015794e6cc626212bc19fee70c805b2.
- Label source data as Vanilla 1.12.1–1.12.3; do not claim it represents Blizzard Classic Era 1.13.x or later.
- MaNGOSZero World Database is CC BY-NC-SA 3.0; retain attribution and keep raw/derived rows under ignored data/azeroth/raw/.
- Preserve source map IDs and coordinates; out-of-bounds points are not clamped or silently discarded.
- Do not infer a confirmed spawn from Wiki prose, page coordinates, or terrain noise.
- Keep the viewer independent from Simulation, Brain, player state, and the campaign GfxApp.
- NPCs and creatures remain at their spawn point; no movement or simulation is part of this milestone.
- Use the existing Azeroth sprite-art pipeline only after the marker-based atlas is complete; no sprite work is part of this plan.
- Do not fetch or commit WoW client assets.

---

## File Map

| File | Responsibility |
|---|---|
| data/azeroth/mulgore/source-manifest.json | Pinned source URL, revision, version, license, attribution, input tables, and local output path. |
| src/wilds/azeroth/scale.py | World-coordinate bounds and world-to-tile transform; keep existing Wiki-percent conversion. |
| src/wilds/azeroth/mangos_sql.py | Parse named-column SQL INSERT statements from the four required source tables and four condition tables. |
| tools/import_mulgore_spawns.py | Convert a pinned World/Setup/FullDB directory into local spawn/template/coverage JSON. |
| src/wilds/azeroth/catalog.py | Typed reference entries, spawn instances, provenance, joins to Wiki records, filtering, and search. |
| src/wilds/azeroth/atlas.py | Render the visible terrain viewport and catalog markers; cluster markers at overview zoom. |
| src/wilds/azeroth/viewer.py | Standalone pygame observer: camera, search/filter controls, selection, legend, and details panel. |
| tools/view_mulgore.py | Small CLI entry point for the standalone viewer. |
| docs/azeroth/mulgore-atlas.md | Run steps, controls, data coverage interpretation, source attribution, and license notice. |
| data/azeroth/raw/ | Ignored local checkout of upstream SQL and generated mulgore-spawns.json; never stage this directory. |

## Interfaces Shared Between Tasks

    # src/wilds/azeroth/scale.py
    Geometry.world_to_tile(map_id: int, x: float, y: float) -> tuple[int, int] | None

    # src/wilds/azeroth/mangos_sql.py
    parse_insert_rows(path: Path, table: str) -> Iterator[dict[str, str | int | float | None]]

    # src/wilds/azeroth/catalog.py
    @dataclass(frozen=True)
    class SpawnInstance:
        key: str                    # creature:<guid> or gameobject:<guid>
        kind: str                   # creature or gameobject
        spawn_id: int               # guid from source row
        template_id: int            # id from source row
        map_id: int
        world_x: float
        world_y: float
        world_z: float
        orientation: float
        rotation: tuple[float, float, float, float] | None
        object_state: int | None
        tile: tuple[int, int] | None
        zone_status: str            # inside_mask, edge_ambiguous, outside, wrong_map
        condition_ids: tuple[str, ...]

    @dataclass(frozen=True)
    class CatalogEntry:
        key: str
        kind: str                    # npc, creature, gameobject, landmark, quest, lore
        title: str
        template_id: int | None
        tile: tuple[int, int] | None
        spawn: SpawnInstance | None
        source_id: str
        source_revision: str
        era_status: str             # vanilla_db, later_era, unknown
        coordinate_status: str      # source_spawn, source_map, approximate, unplaced
        description: str

    AtlasCatalog.entries: tuple[CatalogEntry, ...]
    AtlasCatalog.coverage: dict[str, int]
    AtlasCatalog.search(query: str, kinds: set[str] | None = None) -> list[CatalogEntry]
    AtlasCatalog.visible(tile_bounds: tuple[int, int, int, int]) -> list[CatalogEntry]

    load_catalog(pack_dir: Path, spawn_file: Path | None) -> AtlasCatalog

    @dataclass(frozen=True)
    class AtlasFilters:
        npcs: bool
        creatures: bool
        gameobjects: bool
        landmarks: bool
        approximate: bool
        edge_ambiguous: bool
        uncertain_era: bool

The catalog owns searchable entities; atlas.py only draws entries with a tile. Wiki pages may enrich a matching template's title/details, but only an individual spawn row produces a creature or gameobject marker.

## Task 1: Pin the Local MaNGOSZero Snapshot and Provenance

**Files:**
- Create: data/azeroth/mulgore/source-manifest.json
- Local ignored inputs: data/azeroth/raw/mangoszero-database/World/Setup/FullDB/

- [ ] Clone the approved source revision into the already-ignored raw directory and sparse-checkout its FullDB folder:

    mkdir -p data/azeroth/raw
    git clone --filter=blob:none --sparse https://github.com/mangoszero/database.git data/azeroth/raw/mangoszero-database
    git -C data/azeroth/raw/mangoszero-database fetch --depth 1 origin 325948a78015794e6cc626212bc19fee70c805b2
    git -C data/azeroth/raw/mangoszero-database checkout --detach 325948a78015794e6cc626212bc19fee70c805b2
    git -C data/azeroth/raw/mangoszero-database sparse-checkout set World/Setup/FullDB

- [ ] Confirm the local checkout SHA is 325948a78015794e6cc626212bc19fee70c805b2 and inspect these eight files: creature.sql, creature_template.sql, gameobject.sql, gameobject_template.sql, pool_creature.sql, pool_gameobject.sql, game_event_creature.sql, game_event_gameobject.sql.
- [ ] Add a tracked JSON manifest with source_url, source_revision, source_era, license, license_url, attribution, input_tables, and generated_output. Set source_era to Vanilla 1.12.1–1.12.3, license to CC BY-NC-SA 3.0, license_url to https://creativecommons.org/licenses/by-nc-sa/3.0/, attribution to “based upon the work of getmangos.eu (MaNGOSZero)”, and generated_output to data/azeroth/raw/mulgore-spawns.json.
- [ ] Confirm Git reports data/azeroth/raw as ignored and leave it unstaged.
- [ ] Commit the tracked manifest as docs: record Mulgore data provenance.

## Task 2: Add the World-Coordinate Transform and Mulgore Mask

**Files:**
- Modify: src/wilds/azeroth/scale.py
- Read: data/azeroth/mulgore/zone.json and data/azeroth/mulgore/macro.json

- [ ] Extend Geometry with world_map_id, x_min, x_max, y_min, and y_max loaded from zone.json. Follow the coordinate convention documented by tools/zone_scale.py: world X runs north-south and world Y runs west-east.
- [ ] Implement Geometry.world_to_tile(map_id, x, y): return None for the wrong map ID or coordinates outside x_min < x <= x_max and y_min < y <= y_max. Compute tile_x = floor((y_max - y) / (y_max - y_min) * width) and tile_y = floor((x_max - x) / (x_max - x_min) * height). Do not swap these axes back or clamp.
- [ ] Keep original world coordinates beside the converted tile; do not overwrite them with rounded tile values.
- [ ] Add an importer helper that classifies the converted point against Macro.at(tile_x / geometry.width, tile_y / geometry.height): v is outside, a non-v cell touching a v neighbor or the outer macro border is edge_ambiguous, and other non-v cells are inside_mask.
- [ ] Confirm source bound (x_max, y_max) maps to tile (0, 0), values just above x_min/y_min map to the final row/column, and a sample map-1 point falls within Mulgore's macro mask. After Task 4, visually compare a joined NPC known to be in Thunder Bluff or Camp Narache against the corresponding approximate feature marker.
- [ ] Commit as feat: map Mulgore world coordinates to tiles.

## Task 3: Parse and Import Spawn Rows Into the Local JSON Snapshot

**Files:**
- Create: src/wilds/azeroth/mangos_sql.py
- Create: tools/import_mulgore_spawns.py
- Output, ignored: data/azeroth/raw/mulgore-spawns.json
- Input: the eight named World/Setup/FullDB/*.sql files from Task 1

- [ ] Implement parse_insert_rows(path, table) as a streaming reader for statements shaped as INSERT INTO table (column, ...) VALUES (...), (...);. Decode SQL NULL, integer/decimal literals, single-quoted strings, doubled quotes, and backslash escapes; ignore comments, TRUNCATE, locks, and inserts for other table names.
- [ ] Read spawn rows from creature.sql and gameobject.sql; read templates from creature_template.sql and gameobject_template.sql. Build dictionaries by INSERT column names, not positional schema assumptions.
- [ ] Parse condition relations from pool_creature.sql, pool_gameobject.sql, game_event_creature.sql, and game_event_gameobject.sql. Store matching pool/event IDs on each spawn; keep conditional spawns in the output rather than simulating an event state.
- [ ] Construct spawn keys from row kind and guid; template IDs come from row id. Preserve map, world x/y/z, orientation, movement type, spawn time, gameobject rotation0–rotation3, animprogress, state, and source fields needed to describe a static spawn.
- [ ] Keep creature_template distinct from spawn rows and gameobject_template distinct from object spawn rows. Preserve template name, subname, level range, faction IDs, NpcFlags, gameobject type, and displayId. Unresolved template IDs remain in the snapshot with an unresolved-template count.
- [ ] Implement CLI arguments --sql-dir, --pack-dir, and --out with defaults from the file map. Write JSON atomically through a sibling temporary file before replacing the target.
- [ ] Classify rows without a source area_id using map, Geometry.world_to_tile(), and the macro mask from Task 2. Preserve ambiguous/outside rows in coverage counters by reason; include edge-ambiguous candidates in the searchable catalog with their tile, but keep them off the default map layer until the uncertain-position filter is enabled.
- [ ] Include source URL/revision, version label, license, attribution, transform version, table totals, included totals, wrong-map/out-of-bounds/outside-mask/edge counts, and unresolved-template counts in the JSON header.
- [ ] Run the importer once locally; inspect its JSON header and a sample creature/object row. Keep its output under the ignored data/azeroth/raw/ directory.
- [ ] Commit code as feat: import Vanilla Mulgore spawns without staging raw SQL or generated JSON.

## Task 4: Build a Provenance-Aware Searchable Catalog

**Files:**
- Create: src/wilds/azeroth/catalog.py
- Read: src/wilds/azeroth/content.py
- Read: data/azeroth/mulgore/npcs.json, mobs.json, objects.json, subzones.json, quests.json, lores.json, and features.json

- [ ] Define SpawnInstance, CatalogEntry, and AtlasCatalog above, plus a Coverage mapping that retains every importer counter.
- [ ] Load each creature/gameobject template once and attach it to every spawn with the same numeric template_id; never merge spawn rows that share a template.
- [ ] Join Wiki NPC/mob/object pages only when info.id contains exactly one integer matching a template ID. Do not fuzzy-join by title. Keep nonmatching Wiki pages and templates as catalog-only entries without a marker.
- [ ] Mark DB-backed entries era_status=vanilla_db and coordinate_status=source_spawn. Display a creature spawn as an NPC when its template has nonzero NpcFlags or its exactly joined Wiki page identifies it as an NPC; otherwise display it as a creature. This changes its filter/marker category only and never duplicates the spawn. Mark Wiki-only pages era_status=unknown unless the record explicitly identifies a later expansion, in which case mark later_era; use source_map only for Wiki coordinates and unplaced when no trusted point exists.
- [ ] Keep features.json locations as separate source_map/approximate entries according to their basis; never pass heuristic ZoneWorld.placements into the trusted spawn list.
- [ ] Implement load_catalog(pack_dir, spawn_file) and case-insensitive AtlasCatalog.search(query, kinds). Search title, numeric source ID, template ID, and existing Wiki links; return unplaced rows as normal entries.
- [ ] Build catalog indexes once at load: normalized searchable names/IDs, a list of unplaced entries, and a spatial chunk index keyed by (tile_x // 64, tile_y // 64). AtlasCatalog.visible(tile_bounds) returns only entries in intersecting spatial chunks and inside the requested tile rectangle.
- [ ] Manually inspect counts for imported spawn rows, joined templates, joined Wiki pages, and unplaced pages against importer totals. Confirm there are no silent joins or drops.
- [ ] Commit as feat: add Mulgore entity catalog.

## Task 5: Render the Full-Scale Terrain Viewport and Static Markers

**Files:**
- Create: src/wilds/azeroth/atlas.py
- Read: src/wilds/azeroth/terrain.py, src/wilds/azeroth/world.py, tools/preview_zone.py

- [ ] Create MulgoreAtlasRenderer(world: ZoneWorld, catalog: AtlasCatalog) with render(surface, viewport, camera_x, camera_y, pixels_per_tile, filters: AtlasFilters, selected_key) -> None.
- [ ] Construct ZoneWorld(pack_dir, seed=0, roads=False) so route-finding approximation is not mistaken for a surveyed Classic road. Keep terrain-noise detail labeled as a procedural preview.
- [ ] Use world.chunk() and the existing terrain color palette to draw only chunks intersecting the camera viewport. Cache rendered chunk surfaces by chunk coordinates and zoom bucket in an LRU capped at 128 surfaces; draw full-resolution tiles when zoomed in.
- [ ] At overview scale, sample the macro classification directly rather than looping all 64×64 tile cells for each output pixel. Use nearest-neighbor sampling, north at the top, and preserve zone aspect ratio.
- [ ] Draw catalog markers only when filters accept the entry and CatalogEntry.tile exists. Give NPC, other creature, gameobject, landmark, source-map, and approximate markers distinct legend shapes/colors.
- [ ] Cluster unselected markers into screen-space 24 px buckets at low zoom; a selected search result always draws its exact marker above its cluster.
- [ ] Draw approximate feature roads only as a separate optional dashed layer labeled approximate route; never paint them into the terrain layer.
- [ ] Manually compare the viewer with tools/preview_zone.py at matching scales; confirm north/orientation, boundary, water, and aspect ratio, allowing the expected route-layer difference because the viewer constructs ZoneWorld with roads=False.
- [ ] Commit as feat: render Mulgore atlas layers.

## Task 6: Add the Standalone Pygame Viewer

**Files:**
- Create: src/wilds/azeroth/viewer.py
- Create: tools/view_mulgore.py
- Read: existing pygame usage in src/wilds/gfx/app.py and src/wilds/gfx/hud.py

- [ ] Implement MulgoreViewer(pack_dir, spawn_file, size=(1360, 820)) with its own pygame event loop and no Simulation, Brain, Hero, or GfxApp dependency.
- [ ] Render a 300 px right panel for search/results, layer filters, legend, selected entity details, source/version, confidence, world coordinates, and importer coverage summary. Use pygame fonts and drawing primitives; add no UI packages.
- [ ] Support left-drag pan, mouse-wheel zoom around the cursor, a home action to fit the zone, and click selection of an individual marker. Clamp only the camera view, never source coordinates.
- [ ] Support / to focus search, Esc to clear selection/close search, and H to fit the zone. Use pygame text input events for search typing; clicking a result selects it. Search is case-insensitive; selecting an unplaced result opens its details without moving the camera.
- [ ] Add filters for NPC spawns, other creature spawns, gameobject spawns, landmarks, Wiki-only/unplaced entries, approximate points, edge-ambiguous positions, and later-era/unknown entries. Default to in-mask Vanilla DB spawns and confirmed map features; keep unknown/later-era pages searchable but off-map until enabled.
- [ ] Show persistent badges Vanilla 1.12.x source and procedural preview; show CC BY-NC-SA 3.0 attribution in the details/about panel.
- [ ] Implement tools/view_mulgore.py with --pack-dir, --spawn-file, and --window WIDTHxHEIGHT. If local spawn JSON is missing, print this exact importer command and exit cleanly: python tools/import_mulgore_spawns.py --sql-dir data/azeroth/raw/mangoszero-database/World/Setup/FullDB --pack-dir data/azeroth/mulgore --out data/azeroth/raw/mulgore-spawns.json.
- [ ] Open the viewer and manually inspect full-zone fit, Camp Narache, Bloodhoof Village, Thunder Bluff, a dense creature camp, a placed search result, an unplaced search result, and the approximate layer toggle.
- [ ] Commit as feat: add Mulgore atlas viewer.

## Task 7: Document the Local Workflow and Coverage Limits

**Files:**
- Create: docs/azeroth/mulgore-atlas.md
- Read: docs/superpowers/specs/2026-09-30-mulgore-static-atlas-design.md

- [ ] Document the pinned upstream revision, its Vanilla 1.12.1–1.12.3 scope, the CC BY-NC-SA 3.0 license, and required attribution.
- [ ] Document the sparse-checkout, importer and viewer commands, controls, and the ignored source/output paths.
- [ ] Explain that MaNGOSZero is not an authoritative 1.13.x+ Blizzard Classic Era database, Wiki-only entries are not presumed Vanilla, and terrain noise/estimated routes are not exact geometry.
- [ ] Include actual coverage counters and describe totals as coverage of the pinned source snapshot, not of every current Classic Era realm.
- [ ] Run git diff --check, inspect git status --short, confirm no data/azeroth/raw files are staged, and manually open the documented viewer command from a clean shell.
- [ ] Commit as docs: explain Mulgore atlas data and controls.

## Self-Review Against the Spec

- **Full-scale static map:** Tasks 2 and 5 preserve the 2-yard tile scale, world-coordinate transform, overview ratio, and viewport rendering.
- **NPCs and objects:** Tasks 3 and 4 preserve each spawn GUID separately from templates and report unresolved/unplaced records.
- **No fabricated placements:** Tasks 2–4 avoid clamping, area-ID assumptions, title-based joins, and text-derived trusted points.
- **Classic version labeling:** Tasks 1, 3, 4, and 6 carry the exact pinned Vanilla 1.12.x label and keep modern Wiki-only content unverified by default.
- **Observer separate from gameplay:** Tasks 5 and 6 use a standalone renderer/viewer.
- **Source/layer accuracy:** Tasks 1 and 7 preserve source/license metadata; Task 5 distinguishes procedural terrain/routes from sourced spawn points.
- **Search, filters, and details:** Tasks 4 and 6 provide catalog search, layer filters, and source/confidence details.
- **Sprites and motion deferred:** All tasks use static markers and add no actor movement or art assets.
