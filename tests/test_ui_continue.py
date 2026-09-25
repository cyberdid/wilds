"""Regression: continuing a save through the interactive UI must wire
legacy_dir/brain_name onto the loaded Simulation, same as the headless path -
otherwise a rescue reached via `--continue` in the TUI never writes a legacy
file (found by observing a real session: the UI showed "rescued" but no
legacy/*.json appeared)."""

from wilds.brain import ScriptedBrain
from wilds.sim import Simulation
from wilds.ui.app import WildsApp
from wilds.worldgen import generate


def test_loaded_sim_gets_legacy_dir_and_brain_name(tmp_path):
    loaded = Simulation(generate(1))
    assert loaded.legacy_dir is None

    app = WildsApp(generate, ScriptedBrain(), seed=1, legacy_dir=tmp_path, loaded=loaded)

    assert app.sim is loaded
    assert app.sim.legacy_dir == tmp_path
    assert app.sim.brain_name == "scripted"


def test_loaded_sim_keeps_default_legacy_dir_when_none_requested():
    loaded = Simulation(generate(1))
    app = WildsApp(generate, ScriptedBrain(), seed=1, legacy_dir=None, loaded=loaded)
    assert app.sim.legacy_dir is None  # --no-legacy: do not silently start writing one
