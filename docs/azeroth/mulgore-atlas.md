# Mulgore static atlas

The atlas is a standalone, top-down map for inspecting Mulgore. It shows static
spawn records and searchable reference pages; it does not run a player, NPC
movement, combat, or the game's simulation. Markers are geometric symbols. Sprite
art is a later step.

## Sources and accuracy

Creature and gameobject spawns come from the pinned MaNGOSZero World Database
revision `325948a78015794e6cc626212bc19fee70c805b2`. Upstream describes this
database as targeting Vanilla 1.12.1–1.12.3, and explicitly excludes 1.13.x and
later. It is a versioned Vanilla reference, not an authoritative database for a
current Blizzard Classic Era realm. See the upstream [README](https://github.com/mangoszero/database/blob/master/README.md).

The World Database is licensed CC BY-NC-SA 3.0. Required attribution:
“Based upon the work of getmangos.eu (MaNGOSZero).” Keep source and derived spawn
rows in the ignored local data directory unless you have reviewed and followed
the license terms for redistribution. See the upstream
[license](https://github.com/mangoszero/database/blob/master/LICENSE.md) and the
tracked [source manifest](../../data/azeroth/mulgore/source-manifest.json).

The atlas uses the existing Mulgore macro map and procedural terrain detail. The
coarse map mask is a position filter, not exact boundary geometry; zone bounds
can include neighboring terrain. Noise, terrain transitions, and any displayed
approximate route are previews, not surveyed Vanilla data. The atlas constructs
`ZoneWorld` with `roads=False`; approximate routes are a separate optional layer.

The transform keeps the source world coordinates in each spawn record. On map 1,
world Y maps west-to-east and world X maps north-to-south. The display scale is
2 yards per tile. Points near the coarse mask edge are retained and counted, but
their markers are hidden by default.

Warcraft Wiki pages enrich the local reference catalog, but the current pack has
no numeric `info.id` on its NPC, mob, or object pages. Therefore the importer
does not join any Wiki page to a database template by title. All 801 pages remain
independent searchable entries; 133 have one mappable page coordinate and 668
have no single trusted map point. Wiki page coordinates and approximate map
features use separate coordinate-status labels. Wiki-only records default off
the map and remain available in search, including records with no coordinates.

## Prepare local data

Run these commands from the repository root. The raw checkout and generated
spawn JSON are ignored by Git.

```bash
uv sync
mkdir -p data/azeroth/raw
git clone --filter=blob:none --sparse https://github.com/mangoszero/database.git data/azeroth/raw/mangoszero-database
git -C data/azeroth/raw/mangoszero-database fetch --depth 1 origin 325948a78015794e6cc626212bc19fee70c805b2
git -C data/azeroth/raw/mangoszero-database checkout --detach 325948a78015794e6cc626212bc19fee70c805b2
git -C data/azeroth/raw/mangoszero-database sparse-checkout set World/Setup/FullDB
```

The importer reads the eight named tables from the sparse checkout and writes a
local JSON snapshot atomically:

```bash
uv run python tools/import_mulgore_spawns.py \
  --sql-dir data/azeroth/raw/mangoszero-database/World/Setup/FullDB \
  --pack-dir data/azeroth/mulgore \
  --out data/azeroth/raw/mulgore-spawns.json
```

Open the atlas:

```bash
uv run python tools/view_mulgore.py
```

Optional arguments:

```bash
uv run python tools/view_mulgore.py \
  --pack-dir data/azeroth/mulgore \
  --spawn-file data/azeroth/raw/mulgore-spawns.json \
  --window 1600x1000
```

The viewer enforces a minimum window size of 900×820 for the side panel. If the
spawn snapshot is missing, it prints the importer command and exits without a
traceback.

## Controls

| Input | Action |
|---|---|
| Left-drag | Pan the map |
| Mouse wheel | Zoom around the pointer |
| `H` | Fit the full zone |
| `/` | Focus search |
| Text input | Search names, spawn IDs, template IDs, and Wiki links |
| Up/down, Enter | Move through results and select the highlighted result |
| Click a result | Select it; move the camera when it has a map point |
| Click a marker | Select that spawn or map entry |
| Click a cluster | Zoom toward the cluster |
| `Esc` | Close and clear search, then clear the selection |
| `Q` or window close | Exit the viewer |

Unplaced records remain searchable and open in the details panel without moving
the camera. The right panel shows source, revision/version, coordinate status,
world coordinates for DB spawns, condition IDs, and import coverage. The layer
checkboxes control NPCs, other creatures, gameobjects, landmarks, Wiki-only page
points, approximate points, edge-ambiguous spawns, uncertain Wiki eras, and the
separate dashed approximate-route layer. Unknown/later-era Wiki pins require both
the Wiki-only and unknown/later-era layers to be enabled.

The persistent badges identify the Vanilla 1.12.1–1.12.3 source and procedural
terrain preview. The panel carries the MaNGOSZero attribution and CC BY-NC-SA 3.0
notice.

## Snapshot coverage

These are counts from the pinned source revision, not estimates of all spawns on
current Classic Era realms. The full source tables contain records from every
zone and map. “Wrong map” counts rows whose map ID is not Mulgore's map 1;
“out of bounds” counts map-1 points outside the Mulgore world-coordinate
rectangle; “outside mask” counts points inside that rectangle but in a void cell
of the coarse Mulgore mask.

| Spawn table | Source rows | Wrong map | Out of bounds | Outside mask | Inside mask | Edge ambiguous | Included |
|---|---:|---:|---:|---:|---:|---:|---:|
| Creatures | 63,326 | 36,226 | 22,095 | 2,792 | 2,189 | 24 | 2,213 |
| Gameobjects | 42,008 | 24,866 | 14,081 | 1,326 | 1,719 | 16 | 1,735 |
| **Total** | **105,334** | **61,092** | **36,176** | **4,118** | **3,908** | **40** | **3,948** |

“Included” is inside-mask plus edge-ambiguous. The 40 edge candidates are kept in
the catalog but hidden on the map until the edge-ambiguous layer is enabled.
Conditional pool/event memberships are preserved on each matching spawn; the
atlas does not evaluate event state.

| Template table | Source templates | Kept for included spawns | Unresolved references |
|---|---:|---:|---:|
| Creature templates | 9,113 | 348 | 0 |
| Gameobject templates | 10,534 | 326 | 0 |

The catalog contains 3,948 distinct spawn instances, 801 Wiki pages, and 7
separate map features. The current Wiki pack yields zero exact numeric-ID joins;
names that happen to match remain separate entries. Use the details panel to
distinguish a source spawn, a Wiki page coordinate, an approximate feature, and
an unplaced reference.
