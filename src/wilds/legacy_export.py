"""Writes the narrative bridge from a rescued Tau-7 hero into the cyberpunk
chapter: a small JSON file, read by wilds.cyberpunk.legacy.import_legacy.

Kept as plain JSON (not a pickled object) so the two chapters never need to
import each other's classes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .world import World

LEGACY_DIR = Path("legacy")
ARTIFACT_VALUE = 500  # nuyen a corp broker pays per precursor artifact, on top of a base sum
BASE_NUYEN = 300


def legacy_path(world: "World", brain_name: str, directory: Path = LEGACY_DIR) -> Path:
    return directory / f"{brain_name}-{world.seed}.json"


def write_legacy(world: "World", brain_name: str, directory: Path = LEGACY_DIR) -> Path:
    hero = world.hero
    summary = ""
    if hero.diary:
        sol, text = hero.diary[-1]
        summary = f"Пережив аварію на Тау-7 (сол {sol}): {text}"
    nuyen = BASE_NUYEN + hero.inventory.get("artifact", 0) * ARTIFACT_VALUE
    data = {
        "name": hero.name,
        "race": "",  # Tau-7 has no races; the cyberpunk chapter rolls one
        "traits": list(hero.traits)[-5:],
        "summary": summary,
        "starting_nuyen": nuyen,
        "source_seed": world.seed,
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = legacy_path(world, brain_name, directory)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
