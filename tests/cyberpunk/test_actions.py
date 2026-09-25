from cp_helpers import make_world, run_until_idle

from wilds.cyberpunk.sim import CitySim, Decision


def test_go_to_walks_to_known_place(small_world):
    hero = small_world.hero
    npc_id = next(iter(hero.places))
    sim = CitySim(small_world)
    assert sim.apply(Decision("go_to", npc_id)) is None
    run_until_idle(sim)
    place = hero.places[npc_id]
    assert max(abs(hero.pos[0] - place.pos[0]), abs(hero.pos[1] - place.pos[1])) <= 1
    assert sim.history[-1].outcome.startswith("done")


def test_go_to_unknown_place_rejected(small_world):
    sim = CitySim(small_world)
    assert "unknown place" in sim.apply(Decision("go_to", "nope"))


def test_explore_reveals_new_tiles():
    world = make_world(["." * 60 for _ in range(15)])
    before = len(world.hero.known())
    sim = CitySim(world)
    assert sim.apply(Decision("explore", "E")) is None
    run_until_idle(sim)
    assert len(world.hero.known()) > before


def test_talk_walks_up_and_sets_pending_conversation(small_world):
    hero = small_world.hero
    npc_id = next(iter(hero.places))
    sim = CitySim(small_world)
    assert sim.apply(Decision("talk", npc_id)) is None
    run_until_idle(sim)
    assert sim.pending == "converse"
    assert sim.pending_conversation == npc_id


def test_talk_unknown_npc_rejected(small_world):
    sim = CitySim(small_world)
    assert "unknown NPC" in sim.apply(Decision("talk", "ghost"))


def test_buy_from_vendor_spends_nuyen_and_adds_item(small_world):
    hero = small_world.hero
    npc = small_world.level.npcs[0]
    hero.nuyen = 1000
    price = npc.price_for("synth_noodles", selling=False)
    sim = CitySim(small_world)
    assert sim.apply(Decision("trade", f"{npc.id} buy synth_noodles 2")) is None
    run_until_idle(sim)
    assert hero.inventory["synth_noodles"] == 2
    assert hero.nuyen == 1000 - price * 2


def test_buy_more_than_in_stock_rejected(small_world):
    npc = small_world.level.npcs[0]
    small_world.hero.nuyen = 100000
    sim = CitySim(small_world)
    assert sim.apply(Decision("trade", f"{npc.id} buy synth_noodles 99")) is None
    run_until_idle(sim)
    assert "does not have" in sim.history[-1].outcome


def test_buy_without_enough_nuyen_rejected(small_world):
    npc = small_world.level.npcs[0]
    small_world.hero.nuyen = 1
    sim = CitySim(small_world)
    assert sim.apply(Decision("trade", f"{npc.id} buy synth_noodles")) is None
    run_until_idle(sim)
    assert "not enough nuyen" in sim.history[-1].outcome


def test_sell_item_gives_nuyen(small_world):
    hero = small_world.hero
    npc = small_world.level.npcs[0]
    hero.inventory["trinket"] = 3
    hero.nuyen = 0
    sim = CitySim(small_world)
    price = npc.price_for("trinket", selling=True)
    assert sim.apply(Decision("trade", f"{npc.id} sell trinket 2")) is None
    run_until_idle(sim)
    assert hero.inventory["trinket"] == 1
    assert hero.nuyen == price * 2


def test_buying_cyberware_costs_essence(small_world):
    hero = small_world.hero
    npc = small_world.level.npcs[0]
    npc.stock["cyber_eye"] = 1
    hero.nuyen = 10000
    sim = CitySim(small_world)
    assert sim.apply(Decision("trade", f"{npc.id} buy cyber_eye")) is None
    run_until_idle(sim)
    assert hero.essence < 10.0


def test_pay_debt_reduces_debt_and_frees_hero(small_world):
    hero = small_world.hero
    hero.nuyen = 6000
    hero.debt = 5000
    sim = CitySim(small_world)
    assert sim.apply(Decision("pay_debt", "")) is None
    run_until_idle(sim)
    assert hero.debt == 0
    assert hero.free
    assert hero.nuyen == 1000


def test_pay_debt_partial_amount(small_world):
    hero = small_world.hero
    hero.nuyen, hero.debt = 1000, 5000
    sim = CitySim(small_world)
    sim.apply(Decision("pay_debt", "300"))
    run_until_idle(sim)
    assert hero.debt == 4700 and not hero.free


def test_pay_debt_with_nothing_rejected(small_world):
    small_world.hero.nuyen = 0
    sim = CitySim(small_world)
    assert "nothing to pay" in sim.apply(Decision("pay_debt", ""))


def test_rest_runs_for_requested_minutes(small_world):
    sim = CitySim(small_world)
    sim.apply(Decision("rest", "20"))
    run_until_idle(sim)
    assert sim.history[-1].outcome == "done: rested 20 minutes"


def test_unknown_action_rejected(small_world):
    sim = CitySim(small_world)
    assert "unknown action" in sim.apply(Decision("hack_the_planet"))


def test_npc_status_line_shows_item_ids_not_just_names(small_world):
    npc = small_world.level.npcs[0]
    assert "synth_noodles (" in npc.status_line()
