"""Import a pinned MaNGOSZero SQL snapshot into the local Mulgore spawn catalog.

    python tools/import_mulgore_spawns.py \
        --sql-dir data/azeroth/raw/mangoszero-database/World/Setup/FullDB \
        --pack-dir data/azeroth/mulgore \
        --out data/azeroth/raw/mulgore-spawns.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wilds.azeroth.mangos_sql import parse_insert_rows  # noqa: E402
from wilds.azeroth.scale import load_geometry  # noqa: E402
from wilds.azeroth.terrain import Macro  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQL_DIR = ROOT / "data/azeroth/raw/mangoszero-database/World/Setup/FullDB"
DEFAULT_PACK_DIR = ROOT / "data/azeroth/mulgore"
DEFAULT_OUT = ROOT / "data/azeroth/raw/mulgore-spawns.json"
MANIFEST = ROOT / "data/azeroth/mulgore/source-manifest.json"
TRANSFORM_VERSION = "mulgore-world-bounds-rotated-xy-v1"


def _int(row: dict[str, Any], key: str, *, default: int | None = None) -> int:
    value = row.get(key)
    if value is None:
        if default is None:
            raise ValueError(f"required integer field {key!r} is NULL or missing")
        return default
    return int(value)


def _float(row: dict[str, Any], key: str) -> float:
    value = row.get(key)
    if value is None:
        raise ValueError(f"required coordinate field {key!r} is NULL or missing")
    return float(value)


def _relation_ids(sql_dir: Path, table: str, selected_guids: set[int], value_column: str) -> dict[int, list[int]]:
    result: dict[int, list[int]] = defaultdict(list)
    for row in parse_insert_rows(sql_dir / f"{table}.sql", table):
        guid = _int(row, "guid")
        if guid in selected_guids:
            result[guid].append(_int(row, value_column))
    return {guid: sorted(set(values)) for guid, values in result.items()}


def _classify_spawns(
    sql_dir: Path, geometry: Any, macro: Macro, kind: str,
) -> tuple[list[dict[str, Any]], dict[str, int], set[int], dict[str, int]]:
    table = "creature" if kind == "creature" else "gameobject"
    counters: Counter[str] = Counter()
    wrong_maps: Counter[str] = Counter()
    spawns: list[dict[str, Any]] = []
    needed_templates: set[int] = set()
    for row in parse_insert_rows(sql_dir / f"{table}.sql", table):
        counters["total"] += 1
        guid = _int(row, "guid")
        template_id = _int(row, "id")
        map_id = _int(row, "map")
        if map_id != geometry.world_map_id:
            counters["wrong_map"] += 1
            wrong_maps[str(map_id)] += 1
            continue
        world_x = _float(row, "position_x")
        world_y = _float(row, "position_y")
        tile = geometry.world_to_tile(map_id, world_x, world_y)
        if tile is None:
            counters["out_of_bounds"] += 1
            continue
        status = macro.zone_status(tile, geometry)
        if status == "outside":
            counters["outside_mask"] += 1
            continue
        counters[status] += 1
        counters["included"] += 1
        needed_templates.add(template_id)
        spawn: dict[str, Any] = {
            "key": f"{kind}:{guid}",
            "kind": kind,
            "guid": guid,
            "template_id": template_id,
            "map_id": map_id,
            "world_x": world_x,
            "world_y": world_y,
            "world_z": _float(row, "position_z"),
            "orientation": _float(row, "orientation"),
            "tile": [tile[0], tile[1]],
            "zone_status": status,
            "spawn_time_seconds": _int(row, "spawntimesecs", default=0),
        }
        if kind == "creature":
            spawn.update({
                "movement_type": _int(row, "movementtype", default=0),
                "spawn_distance": _float(row, "spawndist"),
                "model_id": _int(row, "modelid", default=0),
                "equipment_id": _int(row, "equipment_id", default=0),
                "current_waypoint": _int(row, "currentwaypoint", default=0),
                "death_state": _int(row, "deathstate", default=0),
            })
        else:
            spawn.update({
                "rotation": [
                    _float(row, "rotation0"), _float(row, "rotation1"),
                    _float(row, "rotation2"), _float(row, "rotation3"),
                ],
                "animation_progress": _int(row, "animprogress", default=0),
                "object_state": _int(row, "state", default=0),
            })
        spawns.append(spawn)
    return spawns, dict(counters), needed_templates, dict(wrong_maps)


def _read_templates(sql_dir: Path, kind: str, needed: set[int]) -> tuple[list[dict[str, Any]], int]:
    table = "creature_template" if kind == "creature" else "gameobject_template"
    total = 0
    found: dict[int, dict[str, Any]] = {}
    for row in parse_insert_rows(sql_dir / f"{table}.sql", table):
        total += 1
        template_id = _int(row, "entry")
        if template_id not in needed:
            continue
        if kind == "creature":
            found[template_id] = {
                "template_id": template_id,
                "name": row.get("name") or "",
                "subname": row.get("subname") or "",
                "min_level": _int(row, "minlevel", default=0),
                "max_level": _int(row, "maxlevel", default=0),
                "faction_alliance": _int(row, "factionalliance", default=0),
                "faction_horde": _int(row, "factionhorde", default=0),
                "npc_flags": _int(row, "npcflags", default=0),
                "creature_type": _int(row, "creaturetype", default=0),
                "model_ids": [
                    _int(row, "modelid1", default=0), _int(row, "modelid2", default=0),
                    _int(row, "modelid3", default=0), _int(row, "modelid4", default=0),
                ],
            }
        else:
            found[template_id] = {
                "template_id": template_id,
                "name": row.get("name") or "",
                "gameobject_type": _int(row, "type", default=0),
                "display_id": _int(row, "displayid", default=0),
                "faction": _int(row, "faction", default=0),
                "flags": _int(row, "flags", default=0),
                "size": float(row.get("size") or 1),
            }
    return [found[key] for key in sorted(found)], total


def _atomic_json_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=1, allow_nan=False)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def import_spawns(sql_dir: Path, pack_dir: Path, out: Path) -> dict[str, Any]:
    sql_dir, pack_dir, out = Path(sql_dir), Path(pack_dir), Path(out)
    source = json.loads(MANIFEST.read_text("utf-8"))
    geometry = load_geometry(pack_dir)
    macro = Macro.load(pack_dir)

    creatures, creature_coverage, creature_template_ids, creature_maps = _classify_spawns(
        sql_dir, geometry, macro, "creature",
    )
    objects, object_coverage, object_template_ids, object_maps = _classify_spawns(
        sql_dir, geometry, macro, "gameobject",
    )

    creature_guids = {spawn["guid"] for spawn in creatures}
    object_guids = {spawn["guid"] for spawn in objects}
    pools = {
        "creature": _relation_ids(sql_dir, "pool_creature", creature_guids, "pool_entry"),
        "gameobject": _relation_ids(sql_dir, "pool_gameobject", object_guids, "pool_entry"),
    }
    events = {
        "creature": _relation_ids(sql_dir, "game_event_creature", creature_guids, "event"),
        "gameobject": _relation_ids(sql_dir, "game_event_gameobject", object_guids, "event"),
    }
    for spawn in (*creatures, *objects):
        kind = spawn["kind"]
        guid = spawn["guid"]
        spawn["pool_ids"] = pools[kind].get(guid, [])
        spawn["event_ids"] = events[kind].get(guid, [])
        spawn["condition_ids"] = [
            *(f"pool:{value}" for value in spawn["pool_ids"]),
            *(f"event:{value}" for value in spawn["event_ids"]),
        ]

    creature_templates, creature_template_total = _read_templates(
        sql_dir, "creature", creature_template_ids,
    )
    object_templates, object_template_total = _read_templates(
        sql_dir, "gameobject", object_template_ids,
    )
    found_creatures = {template["template_id"] for template in creature_templates}
    found_objects = {template["template_id"] for template in object_templates}
    unresolved = {
        "creature": len(creature_template_ids - found_creatures),
        "gameobject": len(object_template_ids - found_objects),
    }
    data = {
        "schema_version": 1,
        "source": {
            "source_id": source["source_id"],
            "source_url": source["source_url"],
            "source_revision": source["source_revision"],
            "version_label": source["source_era"],
            "license": source["license"],
            "license_url": source["license_url"],
            "attribution": source["attribution"],
            "transform_version": TRANSFORM_VERSION,
        },
        "coverage": {
            "spawn_tables": {"creature": creature_coverage, "gameobject": object_coverage},
            "wrong_map_ids": {
                "creature": dict(sorted(creature_maps.items(), key=lambda pair: int(pair[0]))),
                "gameobject": dict(sorted(object_maps.items(), key=lambda pair: int(pair[0]))),
            },
            "template_tables": {
                "creature_template": {"total": creature_template_total, "included": len(creature_templates)},
                "gameobject_template": {"total": object_template_total, "included": len(object_templates)},
            },
            "included_spawns_total": len(creatures) + len(objects),
            "input_spawns_total": creature_coverage.get("total", 0) + object_coverage.get("total", 0),
            "unresolved_templates": unresolved,
        },
        "templates": {"creature": creature_templates, "gameobject": object_templates},
        "spawns": sorted((*creatures, *objects), key=lambda spawn: (spawn["kind"], spawn["guid"])),
    }
    _atomic_json_write(out, data)
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql-dir", type=Path, default=DEFAULT_SQL_DIR)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    data = import_spawns(args.sql_dir, args.pack_dir, args.out)
    print(json.dumps(data["coverage"], ensure_ascii=False, indent=2))
    print(f"Wrote {data['coverage']['included_spawns_total']} Mulgore candidate spawns to {args.out}")


if __name__ == "__main__":
    main()
