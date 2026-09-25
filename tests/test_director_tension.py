"""Stage: multi-axis Director-7 tension - folding the already-existing
metrics.Metrics action-diversity entropy in as a "novelty" term, and a
safety rule that never forces a scheduled peak while hp/needs are critical
(avoiding a death spiral right when the survivor can least afford one)."""

from wilds.director import CRITICAL_HP, GRACE_TICKS, MAX_CALM
from wilds.worldgen import generate


def test_low_entropy_raises_tension_via_the_novelty_term():
    world = generate(1)
    director = world.director
    director._measure(world, entropy=1.0)
    high_entropy_tension = director.tension
    director._measure(world, entropy=0.0)
    low_entropy_tension = director.tension
    assert low_entropy_tension > high_entropy_tension


def test_update_still_works_without_an_explicit_entropy_argument():
    world = generate(1)
    world.director.update(world)  # existing call sites/tests call it with just `world`
    assert world.director.tension >= 0.0


def test_critical_hp_suppresses_a_forced_peak_even_past_max_calm():
    world = generate(1)
    world.tick = GRACE_TICKS + 10
    director = world.director
    director.calm_ticks = MAX_CALM + 10
    world.hero.hp = CRITICAL_HP - 5
    director.update(world, entropy=1.0)
    assert not director.events, "a forced peak while critically hurt would risk a death spiral"


def test_recovering_above_critical_allows_the_overdue_peak_to_fire():
    world = generate(1)
    world.tick = GRACE_TICKS + 10
    director = world.director
    director.calm_ticks = MAX_CALM + 10
    world.hero.hp = 100.0
    world.hero.satiety = world.hero.hydration = world.hero.warmth = world.hero.energy = 100.0
    director.update(world, entropy=1.0)
    assert director.events, "an overdue peak should fire once no longer critical"
