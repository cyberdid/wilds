from pathlib import Path

import pytest

from wilds.azeroth import quests as q
from wilds.azeroth.actions import ACTION_HELP, make_action
from wilds.azeroth.brain import ScriptedZoneBrain
from wilds.azeroth.route import reachable
from wilds.azeroth.sim import GOAL_LEVEL, ZoneSim
from wilds.azeroth.world import ZoneWorld
from wilds.sim import Decision

PACK = Path(__file__).parents[2] / "data" / "azeroth" / "mulgore"


@pytest.fixture(scope="module")
def built():
    world = ZoneWorld(PACK, seed=1, roads=False)
    return world


def fresh(built, seed=1):
    return ZoneSim(built, seed=seed)


def test_the_hero_starts_at_camp_narache_with_a_living_zone(built):
    sim = fresh(built)
    assert sim.hero.level == 1 and sim.hero.alive
    narache = sim.places["camp narache"]
    assert max(abs(sim.hero.pos[0] - narache.pos[0]), abs(sim.hero.pos[1] - narache.pos[1])) < 60
    assert len(sim.creatures) > 150 and len(sim.quests) > 50
    assert {"hunt", "talk", "go_to", "search", "explore", "rest"} == set(ACTION_HELP)


def test_quests_are_read_from_the_pack_with_objectives():
    kill = q.parse_quest({"id": "a", "title": "A", "info": {"level": "3", "levelreq": "2", "start": "Bob (npc)",
                                                               "experience": "150", "rewards": "Axe"},
                          "sections": {"Objectives": "Kill 8 x.\n- Bristleback Quilboar slain (8)\n- Hide (3)"},
                          "links": ["Red Rocks"]}, {"red rocks"})
    assert kill.giver == "bob" and kill.turn_in == "bob" and kill.xp == 150 and kill.level == 3
    assert [(o.kind, o.target, o.count) for o in kill.objectives] == \
        [("kill", "bristleback quilboar", 8), ("collect", "hide", 3)]
    assert kill.area == "red rocks" and not kill.errand


def test_dead_creatures_come_back_even_far_from_the_hero(built):
    sim = fresh(built)
    c = next(c for c in sim.creatures.values() if c.hostile)
    c.hp = 0
    c.respawn_at = 5
    sim._dead[c.id] = 5
    sim.world.tick = 10
    sim.action = make_action("rest", "10")
    sim.action.start(sim)
    sim._update_creatures()
    assert c.alive and c.id not in sim._dead


def test_hunting_kills_and_gives_experience(built):
    sim = fresh(built)
    victim = min((c for c in sim.creatures.values() if c.hostile and c.level <= 2),
                 key=lambda c: abs(c.pos[0] - sim.hero.pos[0]) + abs(c.pos[1] - sim.hero.pos[1]))
    assert sim.apply(Decision("hunt", victim.title)) is None
    for _ in range(3000):
        if sim.action is None:
            break
        sim.tick()
    assert sim.hero.kills and (sim.hero.xp > 0 or sim.hero.level > 1)


def test_unknown_or_unreachable_choices_are_rejected_not_crashed(built):
    sim = fresh(built)
    assert "unknown place" in sim.apply(Decision("go_to", "Nowhere Land"))
    assert "unknown action" in sim.apply(Decision("fly", ""))
    assert "no living" in sim.apply(Decision("hunt", "Dragon of Nonsense"))


def test_hero_cannot_walk_out_through_the_mountains(built):
    sim = fresh(built)
    assert not reachable(sim.world, sim.hero.pos, (5, 5))


def test_the_scripted_hero_finishes_the_chapter_at_real_scale():
    world = ZoneWorld(PACK, seed=2, roads=False)
    sim = ZoneSim(world, seed=2)
    sim.run(ScriptedZoneBrain(), 80000)
    assert sim.hero.level >= GOAL_LEVEL - 1
    assert sim.hero.done and sim.hero.kills and len(sim.hero.discovered) > 5
    assert world.seconds > 3600  # the zone is big: leveling up took over an hour of game time
