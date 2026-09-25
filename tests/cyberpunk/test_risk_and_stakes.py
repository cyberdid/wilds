"""Stage: district heat, fail-forward, fixer cooldown, upkeep, debt
installments/collectors, district modifiers, and reputation-hostility
ambushes - the mechanics that finally give CyberHero.hp something to spend."""

from cp_helpers import make_world
from test_contracts import make_fixer_world

from wilds.cyberpunk.actions import CompleteJob, RequestJob, Trade, Use
from wilds.cyberpunk.contracts import Contract
from wilds.cyberpunk.npc import FIXER_COOLDOWN_MINUTES, JOBS_BEFORE_COOLDOWN
from wilds.cyberpunk.risk import (HEAT_MAX, add_heat, decay_heat, move_cost_for_district,
                                  price_multiplier_for_district, roll_outcome, success_probability)
from wilds.cyberpunk.sim import CitySim
from wilds.cyberpunk.world import CityLevel

_fixer_world = make_fixer_world


def _complete_active_contract(world, npc, reward=200):
    contract = Contract(id=f"job_{npc.id}_1", giver=npc.id, level_id=world.hero.level_id,
                        drop_pos=(0, 0), reward=reward, status="delivered")
    world.contract = contract
    world.hero.pos = npc.pos
    action = CompleteJob("")
    assert action.start(world) is None
    return action, action.step(world)


def test_success_probability_drops_as_heat_rises():
    low = success_probability(0.0, 0.0, False)
    high = success_probability(100.0, 0.0, False)
    assert high < low
    assert 0.15 <= high <= 0.95


def test_success_probability_floors_and_caps():
    assert success_probability(1000.0, -10.0, False) == 0.15
    assert success_probability(-1000.0, 10.0, True) == 0.95


def test_roll_outcome_bands():
    class FixedRng:
        def __init__(self, v):
            self.v = v

        def random(self):
            return self.v

    assert roll_outcome(FixedRng(0.0), 0.5) == "success"
    assert roll_outcome(FixedRng(0.6), 0.5) == "partial"
    assert roll_outcome(FixedRng(0.99), 0.5) == "critical"


def test_heat_rises_and_decays_and_is_capped():
    level = CityLevel("sprawl", "Насип", 5, 5, [[]])
    add_heat(level, 40)
    assert level.heat == 40
    add_heat(level, 1000)
    assert level.heat == HEAT_MAX
    decay_heat(level)
    assert level.heat < HEAT_MAX


def test_complete_job_success_pays_and_leaves_hp_untouched():
    world = _fixer_world()
    npc = world.level.npcs[0]
    world.rng.random = lambda: 0.0  # forces the top of the success band every time
    action, status = _complete_active_contract(world, npc, reward=250)
    assert world.hero.nuyen == 200 + 250
    assert world.hero.hp == 100.0
    assert status.value == "done"
    assert action.result.endswith(": success")


def test_complete_job_critical_failure_costs_hp_and_pays_nothing():
    world = _fixer_world()
    npc = world.level.npcs[0]
    world.level.heat = 100.0  # worst-case odds
    world.rng.random = lambda: 0.999  # forces past both the success and partial bands
    starting_nuyen = world.hero.nuyen
    action, status = _complete_active_contract(world, npc, reward=250)
    assert world.hero.nuyen == starting_nuyen  # no reward
    assert world.hero.hp < 100.0
    assert action.result.endswith(": critical")


def test_completing_a_job_always_raises_district_heat():
    world = _fixer_world()
    npc = world.level.npcs[0]
    world.rng.random = lambda: 0.0
    assert world.level.heat == 0.0
    _complete_active_contract(world, npc)
    assert world.level.heat > 0.0


def test_fixer_goes_on_cooldown_after_too_many_jobs_in_a_row():
    world = _fixer_world()
    npc = world.level.npcs[0]
    world.rng.random = lambda: 0.0  # always a clean success, isolating the cooldown behavior
    for _ in range(JOBS_BEFORE_COOLDOWN):
        _complete_active_contract(world, npc)
    assert npc.cooldown_until == world.tick + FIXER_COOLDOWN_MINUTES

    world.contract = None
    rejection = RequestJob(npc.id).start(world)
    assert rejection is not None and "no work" in rejection


def test_use_stim_patch_heals_and_is_consumed():
    world = make_world(["........."])
    world.hero.hp = 50.0
    world.hero.inventory["stim_patch"] = 1
    action = Use("stim_patch")
    assert action.start(world) is None
    action.step(world)
    assert world.hero.hp == 80.0
    assert world.hero.inventory["stim_patch"] == 0


def test_use_caps_healing_at_full_hp():
    world = make_world(["........."])
    world.hero.hp = 90.0
    world.hero.inventory["stim_patch"] = 1
    action = Use("stim_patch")
    action.start(world)
    action.step(world)
    assert world.hero.hp == 100.0


def test_use_rejects_an_item_with_no_effect():
    world = make_world(["........."])
    world.hero.inventory["trinket"] = 1
    assert Use("trinket").start(world) is not None


def test_upkeep_charges_nuyen_when_affordable():
    world = _fixer_world()
    world.hero.nuyen = 500
    sim = CitySim(world)
    sim._charge_upkeep(world)
    assert world.hero.nuyen < 500
    assert world.hero.debt == 5000
    assert not world.hero.evicted


def test_upkeep_shortfall_is_added_to_debt_and_marks_eviction():
    world = _fixer_world()
    world.hero.nuyen = 10
    sim = CitySim(world)
    sim._charge_upkeep(world)
    assert world.hero.nuyen == 0
    assert world.hero.debt > 5000
    assert world.hero.evicted


def test_missed_installment_marks_delinquent_and_spawns_a_collector():
    from wilds.cyberpunk.worldgen import HOME_DISTRICT

    world = _fixer_world()
    sim = CitySim(world)
    sim._check_installment(world)  # no debt paid down since sim creation
    assert world.delinquent
    assert any(n.role == "collector" for n in world.levels[HOME_DISTRICT].npcs)


def test_meeting_the_installment_clears_delinquency():
    world = _fixer_world()
    sim = CitySim(world)
    sim._check_installment(world)
    assert world.delinquent
    from wilds.cyberpunk.actions import PayDebt

    action = PayDebt("100")
    world.hero.nuyen = 100
    action.start(world)
    action.step(world)
    assert not world.delinquent
    from wilds.cyberpunk.worldgen import HOME_DISTRICT
    assert not any(n.role == "collector" for n in world.levels[HOME_DISTRICT].npcs)


def test_collector_hits_the_hero_when_adjacent():
    world = _fixer_world()
    sim = CitySim(world)
    sim._spawn_collector(world)
    from wilds.cyberpunk.worldgen import HOME_DISTRICT

    collector = next(n for n in world.levels[HOME_DISTRICT].npcs if n.role == "collector")
    world.hero.pos = collector.pos
    sim._ambient_hazards(world)
    assert world.hero.hp < 100.0


def test_district_modifiers_change_price_and_move_cost():
    assert move_cost_for_district("docks") == 2
    assert move_cost_for_district("sprawl") == 1
    assert price_multiplier_for_district("corp_row") > 1.0
    assert price_multiplier_for_district("sprawl") == 1.0


def test_trade_applies_the_district_price_markup():
    world = make_world(["V........"], npcs={"V": "vendor"})
    world.levels["corp_row"] = world.levels.pop("sprawl")  # relabel as the marked-up district
    world.levels["corp_row"].id = "corp_row"
    world.hero.level_id = "corp_row"
    world.hero.places.clear()
    world.hero.observe(world)  # rediscover places under the new district id
    npc = world.level.npcs[0]
    world.hero.nuyen = 1000
    action = Trade(f"{npc.id} buy synth_noodles")
    action.start(world)
    action.step(world)
    base_price = npc.price_for("synth_noodles", selling=False)
    assert (1000 - world.hero.nuyen) > base_price  # markup applied on top of the base price


def test_hostile_reputation_ganger_ambushes_the_hero():
    world = make_world(["G........"], npcs={"G": "ganger"})
    world.hero.reputation["gangs"] = -0.8
    ganger = world.level.npcs[0]
    world.hero.pos = ganger.pos
    sim = CitySim(world)
    sim._ambient_hazards(world)
    assert world.hero.hp < 100.0


def test_friendly_reputation_ganger_does_not_ambush():
    world = make_world(["G........"], npcs={"G": "ganger"})
    world.hero.reputation["gangs"] = 0.8
    ganger = world.level.npcs[0]
    world.hero.pos = ganger.pos
    sim = CitySim(world)
    sim._ambient_hazards(world)
    assert world.hero.hp == 100.0
