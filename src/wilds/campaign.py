"""The whole game in one run (`wilds --campaign`): Tau-7 until the hero is rescued,
then - with the legacy the rescue wrote - the cyberpunk chapter. Each front-end
(terminal UI, sprite window, headless) chains the chapters itself; this module
only holds the shared rule for when chapter 2 may begin."""

from __future__ import annotations

from pathlib import Path

CHAPTER2_TITLE = "Тінемісто"


def ready_for_chapter2(sim) -> bool:
    """The Tau-7 run ended in a rescue and left a legacy file to continue from."""
    path = getattr(sim, "legacy_path", None)
    return bool(sim.world.hero.rescued and path and Path(path).exists())
