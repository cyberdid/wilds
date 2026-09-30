"""Provenance-aware reference catalog for the Mulgore atlas."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import content
from .scale import CHUNK, Geometry, load_geometry

_INTEGER = re.compile(r"\d+")
_LATER_ERA = re.compile(
    r"\b(?:The Burning Crusade|Burning Crusade|Wrath of the Lich King|Wrath|"
    r"Cataclysm|Mists of Pandaria|Warlords of Draenor|Legion|Battle for Azeroth|"
    r"Shadowlands|Dragonflight|The War Within)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpawnInstance:
    key: str
    kind: str
    spawn_id: int
    template_id: int
    map_id: int
    world_x: float
    world_y: float
    world_z: float
    orientation: float
    rotation: tuple[float, float, float, float] | None
    object_state: int | None
    tile: tuple[int, int] | None
    zone_status: str
    condition_ids: tuple[str, ...]
    spawn_time_seconds: int = 0
    movement_type: int | None = None
    spawn_distance: float | None = None
    model_id: int | None = None
    equipment_id: int | None = None
    pool_ids: tuple[int, ...] = ()
    event_ids: tuple[int, ...] = ()
    animation_progress: int | None = None
    source_fields: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CatalogEntry:
    key: str
    kind: str
    title: str
    template_id: int | None
    tile: tuple[int, int] | None
    spawn: SpawnInstance | None
    source_id: str
    source_revision: str
    era_status: str
    coordinate_status: str
    description: str
    source_url: str = ""
    links: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    info: Mapping[str, Any] = field(default_factory=dict)
    aggro: Mapping[str, Any] = field(default_factory=dict)
    source_coordinates: tuple[tuple[str, float, float], ...] = ()
    coordinate_basis: str = ""
    properties: Mapping[str, Any] = field(default_factory=dict)
    wiki_records: tuple[Mapping[str, Any], ...] = ()


@dataclass
class AtlasCatalog:
    entries: tuple[CatalogEntry, ...]
    coverage: dict[str, Any]
    features: tuple[dict[str, Any], ...] = ()
    approximate_roads: tuple[dict[str, Any], ...] = ()
    _search_text: dict[str, str] = field(init=False, repr=False)
    _spatial: dict[tuple[int, int], list[CatalogEntry]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._search_text = {}
        self._spatial = defaultdict(list)
        for entry in self.entries:
            words = [
                entry.title, entry.key, entry.source_id, entry.source_revision,
                entry.description, entry.coordinate_basis,
            ]
            if entry.template_id is not None:
                words.append(str(entry.template_id))
            if entry.spawn is not None:
                words.extend((str(entry.spawn.spawn_id), str(entry.spawn.template_id)))
            words.extend(entry.links)
            words.extend(entry.categories)
            words.extend(str(value) for value in entry.info.values())
            for record in entry.wiki_records:
                words.extend(str(value) for value in record.get("links", []))
                info = record.get("info", {})
                if isinstance(info, dict):
                    words.extend(str(value) for value in info.values())
            self._search_text[entry.key] = " ".join(words).casefold()
            if entry.tile is not None:
                self._spatial[(entry.tile[0] // CHUNK, entry.tile[1] // CHUNK)].append(entry)

    @property
    def unplaced(self) -> tuple[CatalogEntry, ...]:
        return tuple(entry for entry in self.entries if entry.tile is None)

    def search(self, query: str, kinds: set[str] | None = None) -> list[CatalogEntry]:
        needle = " ".join(query.casefold().split())
        if not needle:
            return []
        return [entry for entry in self.entries
                if (kinds is None or entry.kind in kinds) and needle in self._search_text[entry.key]]

    def visible(self, tile_bounds: tuple[int, int, int, int]) -> list[CatalogEntry]:
        """Return placed entries in half-open ``(x0, y0, x1, y1)`` tile bounds."""
        x0, y0, x1, y1 = tile_bounds
        if x1 <= x0 or y1 <= y0:
            return []
        found: dict[str, CatalogEntry] = {}
        for chunk_y in range(y0 // CHUNK, (y1 - 1) // CHUNK + 1):
            for chunk_x in range(x0 // CHUNK, (x1 - 1) // CHUNK + 1):
                for entry in self._spatial.get((chunk_x, chunk_y), ()):
                    assert entry.tile is not None
                    if x0 <= entry.tile[0] < x1 and y0 <= entry.tile[1] < y1:
                        found[entry.key] = entry
        return list(found.values())


def _record_kind(record: Mapping[str, Any]) -> str:
    return str(record.get("kind", "lore"))


def _wiki_template_id(record: Mapping[str, Any]) -> int | None:
    raw_id = record.get("info", {}).get("id")
    if raw_id is None:
        return None
    matches = _INTEGER.findall(str(raw_id))
    return int(matches[0]) if len(matches) == 1 else None


def _wiki_is_later(record: Mapping[str, Any]) -> bool:
    info = record.get("info", {})
    explicit_fields = ("expansion", "introduced", "added", "patch", "version")
    signals = [*record.get("categories", [])]
    if isinstance(info, dict):
        signals.extend(str(info[key]) for key in explicit_fields if info.get(key))
    return any(_LATER_ERA.search(str(signal)) for signal in signals)


def _wiki_coordinates(record: Mapping[str, Any], geometry: Geometry) -> tuple[
    tuple[int, int] | None, tuple[tuple[str, float, float], ...], str, str,
]:
    source_points: list[tuple[str, float, float]] = []
    mapped_tiles: set[tuple[int, int]] = set()
    for coordinate in record.get("coords", []):
        try:
            map_name = str(coordinate.get("map", ""))
            x, y = float(coordinate["x"]), float(coordinate["y"])
        except (KeyError, TypeError, ValueError):
            continue
        source_points.append((map_name, x, y))
        if not (0 <= x <= 100 and 0 <= y <= 100):
            continue
        if map_name.casefold() == geometry.name.casefold():
            mapped_tiles.add(geometry.pct_to_tile(x, y))
            continue
        submap = geometry.submap(map_name)
        if submap is not None:
            mapped_tiles.add(geometry.sub_to_tile(map_name, x, y))
    normalized_points = tuple(sorted(set(source_points)))
    if len(mapped_tiles) == 1:
        return next(iter(mapped_tiles)), normalized_points, "source_map", "Wiki page coordinate"
    if len(mapped_tiles) > 1:
        return None, normalized_points, "unplaced", "Multiple Wiki coordinates; no single point selected"
    if normalized_points:
        return None, normalized_points, "unplaced", "Wiki coordinates use an unsupported map or range"
    return None, (), "unplaced", "No trusted point in the Wiki record"


def _wiki_description(record: Mapping[str, Any]) -> str:
    sections = record.get("sections", {})
    if not isinstance(sections, dict):
        return ""
    return str(sections.get("Description") or next(iter(sections.values()), ""))


def _spawn_instance(raw: Mapping[str, Any]) -> SpawnInstance:
    raw_tile = raw.get("tile")
    tile = (int(raw_tile[0]), int(raw_tile[1])) if raw_tile is not None else None
    rotation_value = raw.get("rotation")
    rotation = tuple(float(value) for value in rotation_value) if rotation_value is not None else None
    return SpawnInstance(
        key=str(raw["key"]), kind=str(raw["kind"]), spawn_id=int(raw["guid"]),
        template_id=int(raw["template_id"]), map_id=int(raw["map_id"]),
        world_x=float(raw["world_x"]), world_y=float(raw["world_y"]), world_z=float(raw["world_z"]),
        orientation=float(raw["orientation"]), rotation=rotation,  # type: ignore[arg-type]
        object_state=int(raw["object_state"]) if raw.get("object_state") is not None else None,
        tile=tile, zone_status=str(raw.get("zone_status", "unknown")),
        condition_ids=tuple(str(value) for value in raw.get("condition_ids", [])),
        spawn_time_seconds=int(raw.get("spawn_time_seconds", 0)),
        movement_type=int(raw["movement_type"]) if raw.get("movement_type") is not None else None,
        spawn_distance=float(raw["spawn_distance"]) if raw.get("spawn_distance") is not None else None,
        model_id=int(raw["model_id"]) if raw.get("model_id") is not None else None,
        equipment_id=int(raw["equipment_id"]) if raw.get("equipment_id") is not None else None,
        pool_ids=tuple(int(value) for value in raw.get("pool_ids", [])),
        event_ids=tuple(int(value) for value in raw.get("event_ids", [])),
        animation_progress=int(raw["animation_progress"]) if raw.get("animation_progress") is not None else None,
        source_fields=dict(raw),
    )


def _load_wiki_pages(pack_dir: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for kind in ("npc", "mob", "object", "subzone", "quest", "lore"):
        result.extend(content.load(pack_dir, kind))
    return result


def _page_catalog_entry(record: Mapping[str, Any], geometry: Geometry) -> CatalogEntry:
    page_kind = _record_kind(record)
    entry_kind = {"mob": "creature", "object": "gameobject", "subzone": "landmark"}.get(page_kind, page_kind)
    tile, coordinates, coordinate_status, basis = _wiki_coordinates(record, geometry)
    page_id = record.get("source", {}).get("pageid") or record.get("id", "unknown")
    source = record.get("source", {})
    revid = source.get("revid") or source.get("timestamp") or "unknown"
    return CatalogEntry(
        key=f"wiki:{page_kind}:{record.get('id', page_id)}", kind=entry_kind,
        title=str(record.get("title", record.get("id", "Untitled Wiki page"))),
        template_id=None, tile=tile, spawn=None,
        source_id=f"warcraft_wiki:{page_id}", source_revision=str(revid),
        era_status="later_era" if _wiki_is_later(record) else "unknown",
        coordinate_status=coordinate_status, description=_wiki_description(record),
        source_url="https://warcraft.wiki.gg/", links=tuple(str(value) for value in record.get("links", [])),
        categories=tuple(str(value) for value in record.get("categories", [])),
        info=dict(record.get("info", {})), aggro=dict(record.get("aggro", {})),
        source_coordinates=coordinates, coordinate_basis=basis,
        properties={"wiki_kind": page_kind, "removed": bool(record.get("removed", False)),
                    "sections": dict(record.get("sections", {}))},
        wiki_records=(record,),
    )


def _feature_entry(feature: Mapping[str, Any], geometry: Geometry, note: str) -> CatalogEntry:
    title = str(feature.get("name", feature.get("id", "Map feature")))
    tile: tuple[int, int] | None = None
    try:
        x, y = float(feature["x"]), float(feature["y"])
        if 0 <= x <= 100 and 0 <= y <= 100:
            tile = geometry.pct_to_tile(x, y)
    except (KeyError, TypeError, ValueError):
        x = y = 0.0
    basis = str(feature.get("basis") or note or "Map feature coordinate")
    return CatalogEntry(
        key=f"feature:{feature.get('id', title)}", kind="landmark", title=title,
        template_id=None, tile=tile, spawn=None, source_id="mulgore.features",
        source_revision="data/azeroth/mulgore/features.json", era_status="unknown",
        coordinate_status="approximate" if tile is not None else "unplaced",
        description=basis, source_coordinates=(("Mulgore", x, y),) if tile is not None else (),
        coordinate_basis=basis, properties={"feature_kind": feature.get("kind", "landmark")},
    )


def load_catalog(pack_dir: Path | str, spawn_file: Path | str | None = None) -> AtlasCatalog:
    """Load local spawn records, Wiki references, and separate approximate map features."""
    pack_dir = Path(pack_dir)
    geometry = load_geometry(pack_dir)
    spawn_path = Path(spawn_file) if spawn_file is not None else None
    spawn_data: dict[str, Any] = {}
    if spawn_path is not None and spawn_path.exists():
        spawn_data = json.loads(spawn_path.read_text("utf-8"))

    source = spawn_data.get("source", {})
    db_source_id = str(source.get("source_id", "mangoszero_vanilla_world_db"))
    db_revision = str(source.get("source_revision", "unknown"))
    db_url = str(source.get("source_url", "https://github.com/mangoszero/database"))
    templates_raw = spawn_data.get("templates", {})
    templates: dict[str, dict[int, dict[str, Any]]] = {
        kind: {int(row["template_id"]): dict(row) for row in templates_raw.get(kind, [])}
        for kind in ("creature", "gameobject")
    }
    spawns: list[SpawnInstance] = [_spawn_instance(row) for row in spawn_data.get("spawns", [])]
    spawn_by_template: dict[tuple[str, int], list[SpawnInstance]] = defaultdict(list)
    spawn_keys_by_template: dict[tuple[str, int], list[str]] = defaultdict(list)
    for spawn in spawns:
        spawn_by_template[(spawn.kind, spawn.template_id)].append(spawn)
        spawn_keys_by_template[(spawn.kind, spawn.template_id)].append(spawn.key)

    pages = _load_wiki_pages(pack_dir)
    page_matches: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    matched_page_keys: set[str] = set()
    for page in pages:
        page_kind = _record_kind(page)
        db_kind = "creature" if page_kind in ("npc", "mob") else "gameobject" if page_kind == "object" else None
        template_id = _wiki_template_id(page)
        if db_kind is not None and template_id is not None and template_id in templates[db_kind]:
            page_matches[(db_kind, template_id)].append(page)
            matched_page_keys.add(f"{page_kind}:{page.get('id', '')}")

    entries: list[CatalogEntry] = []
    for spawn in spawns:
        template = templates.get(spawn.kind, {}).get(spawn.template_id, {})
        joined_pages = tuple(page_matches.get((spawn.kind, spawn.template_id), ()))
        unique_page = joined_pages[0] if len(joined_pages) == 1 else None
        npc_flags = int(template.get("npc_flags", 0)) if spawn.kind == "creature" else 0
        page_identifies_npc = any(_record_kind(page) == "npc" for page in joined_pages)
        if spawn.kind == "gameobject":
            entry_kind = "gameobject"
        else:
            entry_kind = "npc" if npc_flags or page_identifies_npc else "creature"
        title = str(unique_page.get("title")) if unique_page else str(template.get("name") or f"{entry_kind.title()} #{spawn.template_id}")
        wiki_links = tuple(link for page in joined_pages for link in page.get("links", []))
        description = _wiki_description(unique_page) if unique_page else str(template.get("subname", ""))
        entries.append(CatalogEntry(
            key=spawn.key, kind=entry_kind, title=title, template_id=spawn.template_id,
            tile=spawn.tile, spawn=spawn, source_id=db_source_id, source_revision=db_revision,
            era_status="vanilla_db", coordinate_status="source_spawn", description=description,
            source_url=db_url, links=wiki_links,
            info=dict(unique_page.get("info", {})) if unique_page else {},
            categories=tuple(unique_page.get("categories", [])) if unique_page else (),
            source_coordinates=(("world", spawn.world_x, spawn.world_y),),
            coordinate_basis="MaNGOSZero source spawn coordinates",
            properties={"template": template, "joined_wiki_keys": [
                f"{_record_kind(page)}:{page.get('id', '')}" for page in joined_pages
            ]}, wiki_records=joined_pages,
        ))

    # Retain template records without an instance should a future local snapshot include them.
    for kind, kind_templates in templates.items():
        for template_id, template in kind_templates.items():
            if (kind, template_id) in spawn_by_template:
                continue
            npc = kind == "creature" and int(template.get("npc_flags", 0)) != 0
            entry_kind = "npc" if npc else "creature" if kind == "creature" else "gameobject"
            joined_pages = tuple(page_matches.get((kind, template_id), ()))
            unique_page = joined_pages[0] if len(joined_pages) == 1 else None
            entries.append(CatalogEntry(
                key=f"template:{kind}:{template_id}", kind=entry_kind,
                title=str(unique_page.get("title")) if unique_page else str(template.get("name") or f"Template #{template_id}"),
                template_id=template_id, tile=None, spawn=None, source_id=db_source_id,
                source_revision=db_revision, era_status="vanilla_db", coordinate_status="unplaced",
                description=_wiki_description(unique_page) if unique_page else str(template.get("subname", "")),
                source_url=db_url, links=tuple(link for page in joined_pages for link in page.get("links", [])),
                info=dict(unique_page.get("info", {})) if unique_page else {},
                categories=tuple(unique_page.get("categories", [])) if unique_page else (),
                properties={"template": template}, wiki_records=joined_pages,
            ))

    wiki_only_pages = [page for page in pages
                       if f"{_record_kind(page)}:{page.get('id', '')}" not in matched_page_keys]
    entries.extend(_page_catalog_entry(page, geometry) for page in wiki_only_pages)

    features_data_path = pack_dir / "features.json"
    features_data = json.loads(features_data_path.read_text("utf-8")) if features_data_path.exists() else {}
    raw_features = tuple(dict(feature) for feature in features_data.get("features", []))
    entries.extend(_feature_entry(feature, geometry, str(features_data.get("note", "")))
                   for feature in raw_features)

    importer_coverage = spawn_data.get("coverage", {})
    unplaced_wiki = sum(entry.tile is None for entry in entries if entry.key.startswith("wiki:"))
    catalog_coverage = {
        "spawn_instances": len(spawns),
        "creature_spawns": sum(spawn.kind == "creature" for spawn in spawns),
        "gameobject_spawns": sum(spawn.kind == "gameobject" for spawn in spawns),
        "templates_loaded": sum(len(value) for value in templates.values()),
        "templates_without_spawns": sum(
            (kind, template_id) not in spawn_by_template
            for kind, values in templates.items() for template_id in values
        ),
        "wiki_pages_loaded": len(pages),
        "wiki_pages_joined_by_exact_id": len(matched_page_keys),
        "wiki_pages_catalog_only": len(wiki_only_pages),
        "wiki_pages_unplaced": unplaced_wiki,
        "ambiguous_exact_id_joins": sum(len(value) > 1 for value in page_matches.values()),
        "map_features": len(raw_features),
        "catalog_entries": len(entries),
        "catalog_entries_unplaced": sum(entry.tile is None for entry in entries),
    }
    coverage = {"importer": importer_coverage, "catalog": catalog_coverage}
    return AtlasCatalog(
        entries=tuple(sorted(entries, key=lambda entry: (entry.kind, entry.title.casefold(), entry.key))),
        coverage=coverage, features=raw_features,
        approximate_roads=tuple(dict(road) for road in features_data.get("roads", [])),
    )
