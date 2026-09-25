from cp_helpers import make_world, run_until_idle

from wilds.cyberpunk.scripted import CyberScriptedBrain
from wilds.cyberpunk.sim import CitySim, Conversation, Decision, Reflection
from wilds.cyberpunk.worldgen import generate


def test_meeting_a_new_npc_interrupts_exploration():
    world = make_world(["." * 40 for _ in range(20)], npcs={})
    from wilds.cyberpunk.npc import spawn_npc
    import random

    world.level.npcs.append(spawn_npc("vendor_1", "vendor", (30, 10), random.Random(1)))
    world.hero.pos = (1, 10)
    sim = CitySim(world)
    sim.apply(Decision("explore", "E"))
    for _ in range(200):
        if sim.action is None:
            break
        sim.tick()
    assert sim.action is None
    assert "met someone new" in sim.history[-1].outcome


def test_three_rejections_fall_back_to_rest(small_world):
    sim = CitySim(small_world)
    sim.apply(Decision("nope"))
    sim.apply(Decision("nope"))
    sim.apply(Decision("nope"))
    assert sim.action is not None and sim.action.name == "rest"


def test_new_day_triggers_reflection(small_world):
    world = small_world
    sim = CitySim(world)
    world.tick = 24 * 60 - 1
    sim.apply(Decision("rest", "5"))
    sim.tick()
    assert sim.pending == "reflect"
    assert sim.pending_reflection == 1
    sim.apply_reflection(Reflection("Перший день позаду.", "обережний", "Знайти роботу"))
    assert world.hero.diary[-1] == (1, "Перший день позаду.")
    assert world.hero.goal == "Знайти роботу"
    assert sim.pending != "reflect"


def test_conversation_updates_npc_trust_and_request(small_world):
    npc = small_world.level.npcs[0]
    trust_before, affinity_before = npc.trust, npc.affinity
    sim = CitySim(small_world)
    sim.pending_conversation = npc.id
    sim.apply_conversation(Conversation([("npc", "Привіт"), ("hero", "Здоров")], 0.9, -0.2, "Принеси воду"))
    assert npc.trust == min(1.0, trust_before + 0.15)  # delta is clamped to +-0.15
    assert npc.affinity == max(0.0, affinity_before - 0.15)
    assert npc.request == "Принеси воду"
    assert npc.last_line == "Привіт"
    assert sim.pending_conversation == ""


def test_over_when_free_or_dead(small_world):
    sim = CitySim(small_world)
    assert not sim.over
    small_world.hero.free = True
    assert sim.over
    small_world.hero.free = False
    small_world.hero.alive = False
    assert sim.over


def test_scripted_brain_runs_for_days_without_crashing():
    for seed in range(3):
        world = generate(seed)
        sim = CitySim(world)
        sim.run(CyberScriptedBrain(), 5 * 1440)
        assert world.day >= 5 or sim.over
        # the debt loop can now clear in well under a day, ending the chapter before
        # the first midnight reflection - a diary entry is only guaranteed if play continued past it
        assert world.hero.diary or (sim.over and world.day == 1), world.hero


def test_scripted_brain_can_clear_the_debt_via_contracts():
    world = generate(5)
    sim = CitySim(world)
    sim.run(CyberScriptedBrain(), 3 * 1440)
    assert world.hero.free and world.hero.debt == 0
    assert world.hero.contracts_done > 0


def test_talk_cooldown_prevents_immediate_repeat_conversation(small_world):
    npc = small_world.level.npcs[0]
    sim = CitySim(small_world)
    sim.apply(Decision("go_to", npc.id))
    run_until_idle(sim)
    sim.apply(Decision("talk", npc.id))
    run_until_idle(sim)
    assert sim.pending == "converse"
    sim.consult(CyberScriptedBrain())
    assert npc.last_talk == small_world.tick
    sim.apply(Decision("talk", npc.id))
    run_until_idle(sim)
    assert sim.pending != "converse", "cooldown should block an immediate second conversation"
