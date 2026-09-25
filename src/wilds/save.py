"""Save / load a running game (the whole simulation, pickled).

Saves are local files written by this game only; never load a save from an
untrusted source (pickle can execute code).
"""

from __future__ import annotations

import pickle
from itertools import count
from pathlib import Path

from . import creatures
from .sim import Simulation

SAVE_VERSION = 1
SAVE_DIR = Path("saves")


def save_path(sim: Simulation, brain_name: str, directory: Path = SAVE_DIR) -> Path:
    return directory / f"{brain_name}-{sim.world.seed}.wsav"


def save_game(sim: Simulation, path: Path, brain_state: dict | None = None) -> Path:
    """Write the simulation to ``path`` atomically. UI listeners are not saved."""
    path.parent.mkdir(parents=True, exist_ok=True)
    world = sim.world
    listeners, world.listeners = world.listeners, []
    try:
        data = pickle.dumps({"version": SAVE_VERSION, "sim": sim, "brain_state": brain_state or {}})
    finally:
        world.listeners = listeners
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def load_game(path: Path) -> tuple[Simulation, dict]:
    data = pickle.loads(Path(path).read_bytes())
    if data.get("version") != SAVE_VERSION:
        raise ValueError(f"unsupported save version {data.get('version')}")
    sim: Simulation = data["sim"]
    # creature ids come from a global counter; continue after the saved ones
    ids = [c.id for lv in sim.world.levels.values() for c in lv.creatures]
    creatures._ids = count(max(ids, default=0) + 1)
    return sim, data.get("brain_state", {})


def latest_save(directory: Path = SAVE_DIR) -> Path | None:
    saves = sorted(directory.glob("*.wsav"), key=lambda p: p.stat().st_mtime)
    return saves[-1] if saves else None
