"""The cyberpunk chapter's minimal storyteller: closes the loop on the same
Shannon-entropy action-diversity signal Tau-7 tracks, nudging the hero when
their choices flatline instead of leaving the metric unused."""

from cp_helpers import make_world

from wilds.cyberpunk.director import CALM_TICKS_BEFORE_NUDGE, CyberDirector


def test_sustained_low_entropy_eventually_fires_a_nudge():
    world = make_world(["........."])
    director = CyberDirector()
    for _ in range(CALM_TICKS_BEFORE_NUDGE):
        director.update(world, entropy=0.1)
        world.tick += 1
        if director.alerts:
            break
    assert director.alerts, "a long low-diversity stretch should eventually nudge the hero"


def test_high_entropy_never_nudges():
    world = make_world(["........."])
    director = CyberDirector()
    for _ in range(CALM_TICKS_BEFORE_NUDGE + 100):
        director.update(world, entropy=0.9)
        world.tick += 1
    assert not director.alerts


def test_tension_rises_with_debt_and_heat():
    world = make_world(["........."])
    world.hero.debt = 0
    world.hero.hp = 100.0
    director = CyberDirector()
    director.update(world, entropy=1.0)
    baseline = director.tension
    world.hero.debt = 5000
    world.level.heat = 100.0
    world.hero.hp = 40.0
    director.update(world, entropy=1.0)
    assert director.tension > baseline
