"""Stage 6 (stretch): alphaware costs more nuyen, less essence than basic grade."""

from cp_helpers import run_until_idle

from wilds.cyberpunk.items import ITEMS
from wilds.cyberpunk.sim import CitySim, Decision


def test_alpha_variants_exist_for_every_base_cyberware():
    base = [k for k, v in ITEMS.items() if v.cyberware and not k.endswith("_alpha")]
    assert base  # sanity: there is at least one base cyberware item
    for key in base:
        alpha = ITEMS[f"{key}_alpha"]
        basic = ITEMS[key]
        assert alpha.cyberware
        assert alpha.price > basic.price
        assert alpha.essence_cost < basic.essence_cost
        assert alpha.essence_cost > 0  # still costs something, just less


def test_doc_sells_both_grades(small_world):
    # small_world's only NPC is a vendor; give it doc-style stock to check grade coexistence
    npc = small_world.level.npcs[0]
    npc.stock["cyber_eye"] = 1
    npc.stock["cyber_eye_alpha"] = 1
    line = npc.status_line()
    assert "cyber_eye (" in line and "cyber_eye_alpha (" in line


def test_buying_alpha_costs_more_but_saves_essence(small_world):
    hero = small_world.hero
    npc = small_world.level.npcs[0]
    npc.stock["cyber_eye_alpha"] = 1
    hero.nuyen = 100000
    sim = CitySim(small_world)
    assert sim.apply(Decision("trade", f"{npc.id} buy cyber_eye_alpha")) is None
    run_until_idle(sim)
    assert hero.inventory["cyber_eye_alpha"] == 1
    assert hero.essence == 10.0 - ITEMS["cyber_eye_alpha"].essence_cost
    assert hero.essence > 10.0 - ITEMS["cyber_eye"].essence_cost
