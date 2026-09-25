"""Stage 5: factions & reputation."""

from cp_helpers import make_world, run_until_idle

from wilds.cyberpunk.factions import adjust, faction_of, price_multiplier
from wilds.cyberpunk.sim import CitySim, Conversation, Decision


def test_faction_of_known_roles():
    assert faction_of("fixer") == "fixers"
    assert faction_of("vendor") == "vendors"
    assert faction_of("doc") == "vendors"
    assert faction_of("ganger") == "gangs"
    assert faction_of("civilian") is None


def test_adjust_clamps_to_range():
    rep: dict[str, float] = {}
    adjust(rep, "gangs", 1.5)
    assert rep["gangs"] == 1.0
    adjust(rep, "gangs", -3.0)
    assert rep["gangs"] == -1.0
    adjust(rep, None, 0.5)  # no faction -> no-op, no crash
    assert rep == {"gangs": -1.0}


def test_price_multiplier_discounts_with_good_reputation():
    assert price_multiplier({}, "vendors") == 1.0
    assert price_multiplier({"vendors": 1.0}, "vendors") < 1.0
    assert price_multiplier({"vendors": -1.0}, "vendors") > 1.0
    assert price_multiplier({"vendors": 1.0}, None) == 1.0


def test_buying_raises_vendor_reputation_and_lowers_price(small_world):
    hero = small_world.hero
    npc = small_world.level.npcs[0]
    hero.nuyen = 100000
    hero.reputation["vendors"] = 1.0
    discounted = round(npc.price_for("synth_noodles", selling=False) * price_multiplier(hero.reputation, "vendors"))
    sim = CitySim(small_world)
    sim.apply(Decision("trade", f"{npc.id} buy synth_noodles"))
    run_until_idle(sim)
    assert hero.nuyen == 100000 - discounted
    assert hero.reputation["vendors"] > 1.0 - 1e-9  # already capped at 1.0, stays there


def test_completing_a_contract_raises_fixer_reputation():
    from test_contracts import make_fixer_world

    world = make_fixer_world()
    fixer = world.level.npcs[0]
    sim = CitySim(world)
    sim.apply(Decision("request_job", fixer.id))
    run_until_idle(sim)
    world.contract.status = "delivered"
    sim.apply(Decision("complete_job"))
    run_until_idle(sim)
    assert world.hero.reputation.get("fixers", 0.0) > 0


def test_positive_conversation_nudges_faction_reputation(small_world):
    npc = small_world.level.npcs[0]  # vendor
    sim = CitySim(small_world)
    sim.pending_conversation = npc.id
    sim.apply_conversation(Conversation([("npc", "Приємно бачити знову!")], trust_delta=0.1))
    assert small_world.hero.reputation["vendors"] == 0.05


def test_negative_conversation_can_lower_reputation(small_world):
    npc = small_world.level.npcs[0]
    sim = CitySim(small_world)
    sim.pending_conversation = npc.id
    sim.apply_conversation(Conversation([("npc", "Забирайся.")], trust_delta=-0.1))
    assert small_world.hero.reputation["vendors"] == -0.05


def test_observation_shows_reputation():
    from wilds.cyberpunk.observe import build_observation

    world = make_world(["." * 20 for _ in range(10)])
    world.hero.reputation["gangs"] = 0.3
    sim = CitySim(world)
    text = build_observation(sim)
    assert "REPUTATION" in text and "0.30" in text
