"""Turn raw wiki pages into the structured content pack of a zone.

Every page becomes one record: what it is (npc, mob, object, quest, subzone,
lore), its infobox fields, coordinates (percent of a zone map), every section
of prose as plain text, and the pages it links to. Nothing is summarised:
the full description stays in the record so the game can quote it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import wikitext as wt

INFOBOXES = ("npcbox", "questbox", "infobox zone", "infobox town", "infobox subzone", "infobox location",
             "infobox object", "infobox dungeon", "infobox area", "infobox")
_SKIP_SECTIONS = {"external links", "references", "patch changes", "gallery", "see also", "trivia"}


def slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", title.lower().replace("'", "")).strip("_")
    return s or "page"


def kind_of(categories: list[str], infobox: str = "") -> str:
    """What a page is: the infobox decides first, categories second ('Quest givers' is an NPC)."""
    names = " | ".join(c.lower() for c in categories)
    if infobox == "questbox":
        return "quest"
    if infobox == "npcbox":
        return "mob" if re.search(r"\bmobs?\b", names) else "npc"
    if "subzone" in names:
        return "subzone"
    if re.search(r"\bquests\b(?! givers)", names) and not re.search(r"\bnpcs?\b|\bmobs?\b", names):
        return "quest"
    if re.search(r"\bmobs?\b", names):
        return "mob"
    if re.search(r"\bnpcs?\b|\bshops?\b|\bvendors?\b", names):
        return "npc"
    if re.search(r"\bobjects?\b|fixed devices", names):
        return "object"
    if "subzone" in names:
        return "subzone"
    return "lore"


def zone_of(categories: list[str], title: str, text: str) -> str:
    joined = " ".join(categories).lower()
    if "thunder bluff" in joined or title.lower().startswith("thunder bluff"):
        return "thunder_bluff"
    if "mulgore" in joined:
        return "mulgore"
    tb = sum(1 for _, _, m in wt.coords(text) if "thunder bluff" in m.lower())
    return "thunder_bluff" if tb else "mulgore"


def _infobox(text: str) -> tuple[str, dict[str, Any]]:
    for name in INFOBOXES:
        t = wt.template(text, name)
        if t:
            info = {k: wt.strip_markup(v) for k, v in t.named.items() if v.strip()}
            return t.name.lower(), {k: v for k, v in info.items() if v and k not in ("image", "ss")}
    return "", {}


def _aggro(text: str) -> dict[str, int]:
    """{{Aggro|alliance|horde}}: -1 hostile, 0 neutral, 1 friendly (and -2 'kill on sight' for some)."""
    t = wt.template(text, "npcbox")
    raw = (t.named.get("aggro") or t.named.get("reaction") or "") if t else ""
    if not raw:
        n = wt.template(text, "npclocations")
        raw = n.named.get("reaction", "") if n else ""
    a = wt.template(raw, "aggro") if raw else None
    if not a or len(a.args) < 2:
        return {}
    try:
        return {"alliance": int(a.args[0]), "horde": int(a.args[1])}
    except ValueError:
        return {}


def record(page: dict[str, Any]) -> dict[str, Any]:
    text = page["text"]
    cats = wt.categories(text)
    source = page.get("category", "").removeprefix("Category:")
    box, info = _infobox(text)
    aggro = _aggro(text)
    lead = text
    first = wt.find_templates(text)
    for t in first:  # the lead is the prose after the infobox
        if t.name.lower() in INFOBOXES:
            lead = text.replace(t.raw, "", 1)
            break
    secs = wt.sections(lead)
    prose = {name or "Description": wt.strip_markup(body) for name, body in secs.items()
             if name.lower() not in _SKIP_SECTIONS}
    prose = {k: v for k, v in prose.items() if v}
    removed = any("removed" in c.lower() for c in cats)
    return {
        "id": slug(page["title"]),
        "title": page["title"],
        "kind": kind_of([*cats, source] if source else cats, box),
        "aggro": aggro,
        "zone": zone_of([*cats, source] if source else cats, page["title"], text),
        "removed": removed,
        "infobox": box,
        "info": info,
        "coords": [{"x": x, "y": y, "map": m} for x, y, m in wt.coords(text)],
        "sections": prose,
        "links": [link for link in wt.links(lead) if link != page["title"]],
        "categories": cats,
        "source": {"wiki": "warcraft.wiki.gg", "pageid": page.get("pageid"), "revid": page.get("revid"),
                   "timestamp": page.get("timestamp"), "license": "CC BY-SA"},
    }


def build(raw_file: Path, out_dir: Path) -> dict[str, int]:
    """Read categories.jsonl (see tools/wiki_dump.py --category) and write the pack."""
    out_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict[str, Any]] = {}
    for line in raw_file.read_text("utf-8").splitlines():
        page = json.loads(line)
        if page["text"].lstrip().lower().startswith("#redirect"):
            continue
        rec = record(page)
        records.setdefault(rec["id"], rec)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for rec in sorted(records.values(), key=lambda r: (r["zone"], r["title"])):
        by_kind.setdefault(rec["kind"], []).append(rec)
    counts = {}
    for kind, items in by_kind.items():
        (out_dir / f"{kind}s.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), "utf-8")
        counts[kind] = len(items)
    return counts


def load(pack_dir: Path, kind: str) -> list[dict[str, Any]]:
    path = Path(pack_dir) / f"{kind}s.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else []
