"""View state of everything that moves: tweened positions between ticks,
facing, which animation plays and since when, hit flashes. The simulation only
knows tile positions; this turns them into smooth, readable motion."""

from __future__ import annotations

from dataclasses import dataclass

Pos = tuple[int, int]


@dataclass
class ActorView:
    key: object
    pos: Pos
    from_x: float
    from_y: float
    moved_at: float = -99.0
    facing: int = 1  # +1 right, -1 left
    anim: str = "idle"
    anim_since: float = 0.0
    flash_until: float = -1.0
    seen_at: float = 0.0


class ActorTracker:
    """Feed it every actor's tile position each frame; ask for smooth positions."""

    def __init__(self) -> None:
        self.views: dict[object, ActorView] = {}
        self.step = 0.12  # seconds a one-tile move takes on screen

    def set_speed(self, ticks_per_second: float) -> None:
        # slower than a tick when the sim is slow (smooth), instant when it races
        self.step = 0.0 if ticks_per_second >= 30 else min(0.28, 0.9 / max(ticks_per_second, 1))

    def update(self, key: object, pos: Pos, now: float) -> ActorView:
        v = self.views.get(key)
        if v is None:
            v = ActorView(key, pos, float(pos[0]), float(pos[1]), anim_since=now)
            self.views[key] = v
        elif pos != v.pos:
            fx, fy = self.visual(v, now)
            jump = max(abs(pos[0] - fx), abs(pos[1] - fy))
            if jump > 2.5:  # teleport / level change: no tween
                fx, fy = float(pos[0]), float(pos[1])
            if pos[0] != v.pos[0]:
                v.facing = 1 if pos[0] > v.pos[0] else -1
            v.from_x, v.from_y = fx, fy
            v.pos = pos
            v.moved_at = now
        v.seen_at = now
        return v

    def visual(self, v: ActorView, now: float) -> tuple[float, float]:
        if self.step <= 0:
            return float(v.pos[0]), float(v.pos[1])
        t = min(1.0, (now - v.moved_at) / self.step)
        return v.from_x + (v.pos[0] - v.from_x) * t, v.from_y + (v.pos[1] - v.from_y) * t

    def moving(self, v: ActorView, now: float) -> bool:
        return now - v.moved_at < max(self.step * 1.6, 0.22)

    def set_anim(self, v: ActorView, anim: str, now: float) -> None:
        if anim != v.anim:
            v.anim = anim
            v.anim_since = now

    def face(self, v: ActorView, target_x: float) -> None:
        if target_x != v.pos[0]:
            v.facing = 1 if target_x > v.pos[0] else -1

    def forget_stale(self, now: float, keep: float = 5.0) -> None:
        self.views = {k: v for k, v in self.views.items() if now - v.seen_at < keep}

    def reset(self) -> None:
        self.views.clear()
