from wilds.azeroth import wikitext as wt

NPC = """{{Npcbox
|name=Agitated Earth Spirit
|level={{Level|Mulgore}}
|aggro={{Aggro|0|0}}
|location=[[Bael'dun Digsite]], [[Mulgore]]{{co|31.6|49.5|Mulgore}}
}}__NOTOC__
'''Agitated Earth Spirits''' are [[earth elemental]]s in [[Mulgore|the plains]].<ref>x</ref>
==Abilities==
*{{Abilities|Rock Barrage|id=1|Launches a missile.}}
[[Category:Mulgore mobs]]"""


def test_template_named_args_survive_nesting():
    t = wt.template(NPC, "npcbox")
    assert t.named["name"] == "Agitated Earth Spirit"
    assert t.named["level"] == "{{Level|Mulgore}}"
    assert "{{co|31.6|49.5|Mulgore}}" in t.named["location"]


def test_positional_and_named_split():
    t = wt.parse_template("{{Npclocations|align=|loc=[[A|b]], {{Co|1|2|M}}|x|y}}")
    assert t.args == ["x", "y"] and t.named["loc"].startswith("[[A|b]]")


def test_coords_found_at_any_depth():
    assert wt.coords(NPC) == [(31.6, 49.5, "Mulgore")]
    assert wt.coords("{{Npclocations|loc=[[X]]{{coords|71|34.2|Thunder Bluff}}}}") == [(71.0, 34.2, "Thunder Bluff")]


def test_strip_markup_and_sections():
    body = wt.sections(NPC)[""]
    assert wt.strip_markup(body.split("}}__NOTOC__")[1]) == "Agitated Earth Spirits are earth elementals in the plains."
    assert "Abilities" in wt.sections(NPC)
    assert wt.categories(NPC) == ["Mulgore mobs"]


def test_links_skip_files_and_categories():
    assert wt.links("[[File:a.jpg|thumb|x]] [[Thunder Bluff]] [[Mulgore|m]] [[Category:Z]] [[Thunder Bluff]]") == ["Thunder Bluff", "Mulgore"]
