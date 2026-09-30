"""Regressions from a live Codex campaign (seed 157479): 115 of 340 decisions
were rejected - mostly `pod repair` on a healthy pod (44x), because a low
battery with no fault line read as "still broken" and last night's goal kept
saying "repair the solar panels"."""

from wilds.brain.observe import build_observation, repeated_rejections
from wilds.sim import Decision, HistoryEntry, Simulation
from wilds.worldgen import generate


def test_healthy_pod_says_there_is_nothing_to_repair():
    world = generate(1)
    world.pod.power = 11
    assert "no fault, nothing to repair" in world.pod.status_line()
    world.pod.fault = True
    assert "FAULT" in world.pod.status_line()
    assert "nothing to repair" not in world.pod.status_line()


def test_a_repeatedly_rejected_choice_is_called_out():
    history = [HistoryEntry(0, "pod", "repair", "", "rejected: the pod has no fault to repair"),
               HistoryEntry(1, "go_to", "pod_1", "", "done: arrived"),
               HistoryEntry(2, "pod", "repair", "", "rejected: the pod has no fault to repair")]
    lines = repeated_rejections(history)
    assert len(lines) == 1
    assert "`pod repair`" in lines[0] and "2 times" in lines[0] and "no fault" in lines[0]


def test_a_single_rejection_is_not_nagged_about():
    history = [HistoryEntry(0, "pod", "repair", "", "rejected: the pod has no fault to repair")]
    assert repeated_rejections(history) == []


def test_observation_carries_the_warning_and_the_goal_caveat():
    world = generate(1)
    world.hero.goal = "відремонтувати сонячні панелі"
    sim = Simulation(world)
    sim.apply(Decision("pod", "repair"))
    sim.apply(Decision("pod", "repair"))
    text = build_observation(sim)
    assert "STOP REPEATING: `pod repair`" in text
    assert "may already be done or out of date" in text
