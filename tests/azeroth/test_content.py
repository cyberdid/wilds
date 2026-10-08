import importlib.util
import json
from pathlib import Path

from wilds.azeroth import content

ROOT = Path(__file__).parents[2]
PACK = ROOT / "data" / "azeroth" / "mulgore"

QUEST = """{{questbox
| name= A Sacred Burial
| faction= Horde
| start = [[Lorekeeper Raintotem]]
| experience = 150
| id = 833
}}

==Objectives==
Kill 8 [[Bristleback Interloper]]s at {{co|62|21|Mulgore}}.

==Description==
Only the most valiant tauren are laid to rest at [[Red Rocks]].
==External links==
{{Elinks-quest|833}}
[[Category:Mulgore quests]]"""


def test_record_keeps_info_prose_coords_and_links():
    rec = content.record({"title": "A Sacred Burial", "text": QUEST, "pageid": 1, "revid": 2})
    assert rec["kind"] == "quest" and rec["zone"] == "mulgore" and not rec["removed"]
    assert rec["info"]["start"] == "Lorekeeper Raintotem" and rec["info"]["id"] == "833"
    assert rec["coords"] == [{"x": 62.0, "y": 21.0, "map": "Mulgore"}]
    assert "External links" not in rec["sections"]
    assert rec["sections"]["Description"] == "Only the most valiant tauren are laid to rest at Red Rocks."
    assert rec["links"] == ["Bristleback Interloper", "Red Rocks"]
    assert rec["source"]["license"] == "CC BY-SA"


def test_kind_and_zone_rules():
    assert content.kind_of(["Mulgore mobs"]) == "mob"
    assert content.kind_of(["Thunder Bluff NPCs"]) == "npc"
    assert content.kind_of(["Mulgore subzones"]) == "subzone"
    assert content.kind_of(["Removed Mulgore quests"]) == "quest"
    assert content.kind_of(["Horde"]) == "lore"
    assert content.zone_of(["Thunder Bluff NPCs"], "Ahanu", "") == "thunder_bluff"
    assert content.zone_of([], "X", "{{coords|45|55|Thunder Bluff}}") == "thunder_bluff"


def test_build_writes_one_file_per_kind_and_skips_redirects(tmp_path):
    raw = tmp_path / "categories.jsonl"
    rows = [{"title": "A Sacred Burial", "text": QUEST, "category": "Category:Mulgore quests"},
            {"title": "Old", "text": "#REDIRECT [[A Sacred Burial]]", "category": "Category:Mulgore quests"}]
    raw.write_text("\n".join(json.dumps(r) for r in rows), "utf-8")
    assert content.build(raw, tmp_path / "pack") == {"quest": 1}
    assert [r["title"] for r in content.load(tmp_path / "pack", "quest")] == ["A Sacred Burial"]


def test_shipped_pack_is_complete_enough():
    kinds = {k: content.load(PACK, k) for k in ("npc", "mob", "quest", "subzone", "object")}
    assert len(kinds["npc"]) > 150 and len(kinds["mob"]) > 50 and len(kinds["quest"]) > 100
    titles = {r["title"] for r in kinds["subzone"]}
    assert {"Bloodhoof Village", "Thunder Bluff", "Camp Narache", "Red Rocks"} <= titles
    ids = [r["id"] for k in kinds.values() for r in k]
    assert len(ids) == len(set(ids))  # one record per page, no id collisions across kinds


def test_zone_scale_is_the_clients_size_and_submaps_lie_inside():
    zone = json.loads((PACK / "zone.json").read_text("utf-8"))
    assert (zone["yards"]["east_west"], zone["yards"]["north_south"]) == (5450.0, 3633.3)
    for sub in zone["submaps"]:
        p = sub["in_zone"]
        assert 0 < p["center_x_pct"] - p["width_pct"] / 2 and p["center_x_pct"] + p["width_pct"] / 2 < 100
    tb = next(s for s in zone["submaps"] if s["name"] == "Thunder Bluff")
    assert abs(tb["in_zone"]["center_x_pct"] - 40.5) < 0.2 and abs(tb["in_zone"]["center_y_pct"] - 28.3) < 0.2


def test_zone_scale_place_matches_the_wiki_map_position():
    spec = importlib.util.spec_from_file_location("zone_scale", ROOT / "tools" / "zone_scale.py")
    zs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(zs)
    parent = {"x_min": 0, "x_max": 1000, "y_min": 0, "y_max": 2000, "east_west": 2000, "north_south": 1000}
    child = {"x_min": 400, "x_max": 600, "y_min": 1000, "y_max": 1200, "east_west": 200, "north_south": 200}
    # y grows westward: the child sits 40% from the west edge; x grows northward: 50% from the north
    assert zs.place(child, parent) == {"center_x_pct": 45.0, "center_y_pct": 50.0, "width_pct": 10.0, "height_pct": 20.0}
