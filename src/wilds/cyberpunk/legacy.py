"""The narrative bridge from Wilds: Tau-7 into the cyberpunk chapter.

A rescue in Tau-7 writes a small JSON "legacy" file (see wilds.legacy_export).
This module only reads that plain JSON contract - no import of Tau-7 classes,
so the two chapters stay decoupled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STARTING_NUYEN = 300


@dataclass
class Legacy:
    name: str = "Раннер"
    race: str = ""  # a Race enum name, or "" to roll randomly
    traits: list[str] = field(default_factory=list)
    summary: str = ""  # one line about surviving Tau-7, for the diary/system prompt
    starting_nuyen: int = STARTING_NUYEN
    source_seed: int = 0


def import_legacy(path: str | Path) -> Legacy:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Legacy(
        name=str(data.get("name") or "Раннер"),
        race=str(data.get("race") or ""),
        traits=list(data.get("traits") or [])[:5],
        summary=str(data.get("summary") or ""),
        starting_nuyen=int(data.get("starting_nuyen") or STARTING_NUYEN),
        source_seed=int(data.get("source_seed") or 0),
    )
