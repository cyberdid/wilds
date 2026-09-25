"""Stage 2: contracts. A fixer hands out simple courier runs - go to a
dead-drop somewhere in the Sprawl, then report back for payment. This is the
income loop stage 1 deliberately lacked (see the design doc's stage 1 notes).

Kept deterministic (no LLM call to generate a job): the brief is templated,
the reward comes from distance and a little randomness, mirroring how Tau-7's
wrecks hand out loot without an LLM call.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..world import Pos, chebyshev
from .npc import NPC
from .world import CityWorld

MIN_REWARD = 150
PER_TILE_REWARD = 12
RISK_BONUS = 80  # extra pay for a drop point deep in ganger territory


@dataclass
class Contract:
    id: str
    giver: str  # npc id
    level_id: str  # district the drop (and giver) are in - same-district only for now
    drop_pos: Pos
    reward: int
    status: str = "active"  # active | delivered | done
    brief: str = ""


def _pick_drop(world: "CityWorld", giver_pos: Pos) -> Pos | None:
    level = world.level
    candidates = [p for p in level.positions() if level.passable(p)
                 and chebyshev(p, giver_pos) >= 8 and level.npc_at(p) is None]
    if not candidates:
        return None
    return world.rng.choice(sorted(candidates))


def generate_contract(world: "CityWorld", giver: NPC, seq: int) -> Contract | None:
    drop = _pick_drop(world, giver.pos)
    if drop is None:
        return None
    dist = chebyshev(giver.pos, drop)
    ganger_near = any(n.role == "ganger" and chebyshev(n.pos, drop) <= 6 for n in world.level.npcs)
    reward = MIN_REWARD + dist * PER_TILE_REWARD + (RISK_BONUS if ganger_near else 0)
    reward += world.rng.randint(-20, 20)
    brief = (f"Забери пакунок біля ({drop[0]},{drop[1]}) і принеси назад. "
            + ("Там неспокійно - тримайся насторожі. " if ganger_near else "Робота спокійна. ")
            + f"Оплата {reward}¥ по завершенню.")
    return Contract(f"job_{giver.id}_{seq}", giver.id, world.hero.level_id, drop, reward, brief=brief)
