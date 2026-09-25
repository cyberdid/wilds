"""Stage 2: contracts - the income loop stage 1 was missing."""

from cp_helpers import make_world, run_until_idle

from wilds.cyberpunk.contracts import generate_contract
from wilds.cyberpunk.sim import CitySim, Decision
from wilds.pathfinding import find_path


def make_fixer_world():
    """A plain open block big enough that dead-drops (>=8 tiles from the fixer) exist.

    Uses 'X' (not 'F') to mark the fixer: 'F' is already a tile glyph (CTile.FIXER)
    in cp_helpers.GLYPHS, so it would be consumed as terrain, not an NPC marker.
    """
    lines = ["." * 40 for _ in range(30)]
    lines[3] = "....X" + "." * 35
    lines[10] = "....@" + "." * 35
    return make_world(lines, npcs={"X": "fixer"})


def test_generate_contract_is_reachable_and_far_from_giver():
    world = make_fixer_world()
    fixer = world.level.npcs[0]
    for seq in range(5):
        c = generate_contract(world, fixer, seq)
        assert c is not None
        full_map = {p: world.level.tile(p) for p in world.level.positions()}
        path = find_path(world.level, full_map, fixer.pos, lambda p, t=c.drop_pos: p == t, allow_unknown=False)
        assert path is not None
        assert c.reward >= 130


def test_request_job_then_complete_pays_reward():
    world = make_fixer_world()
    fixer = world.level.npcs[0]
    hero = world.hero
    sim = CitySim(world)
    assert sim.apply(Decision("request_job", fixer.id)) is None
    run_until_idle(sim)
    contract = world.contract
    assert contract is not None and contract.status == "active"
    drop_place_id = f"drop_{contract.id}"
    assert drop_place_id in hero.places

    sim.apply(Decision("go_to", drop_place_id))
    run_until_idle(sim)
    assert world.contract.status == "delivered"

    before = hero.nuyen
    sim.apply(Decision("complete_job"))
    run_until_idle(sim)
    assert world.contract.status == "done"
    assert hero.nuyen == before + contract.reward
    assert hero.contracts_done == 1
    assert drop_place_id not in hero.places


def test_complete_job_before_pickup_rejected():
    world = make_fixer_world()
    fixer = world.level.npcs[0]
    sim = CitySim(world)
    sim.apply(Decision("request_job", fixer.id))
    run_until_idle(sim)
    assert "have not picked up" in sim.apply(Decision("complete_job"))


def test_complete_job_without_contract_rejected(small_world):
    sim = CitySim(small_world)
    assert "no active contract" in sim.apply(Decision("complete_job"))


def test_request_job_from_non_fixer_rejected(small_world):
    vendor = small_world.level.npcs[0]
    sim = CitySim(small_world)
    assert "only a fixer" in sim.apply(Decision("request_job", vendor.id))


def test_cannot_request_a_second_job_while_one_is_active():
    world = make_fixer_world()
    fixer = world.level.npcs[0]
    sim = CitySim(world)
    sim.apply(Decision("request_job", fixer.id))
    run_until_idle(sim)
    assert "already have an active contract" in sim.apply(Decision("request_job", fixer.id))


def test_can_request_a_new_job_after_finishing_the_last_one():
    world = make_fixer_world()
    fixer = world.level.npcs[0]
    sim = CitySim(world)
    sim.apply(Decision("request_job", fixer.id))
    run_until_idle(sim)
    world.contract.status = "delivered"
    sim.apply(Decision("complete_job"))
    run_until_idle(sim)
    assert sim.apply(Decision("request_job", fixer.id)) is None
