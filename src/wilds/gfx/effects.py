"""Transient visuals: one-shot sprite effects in the world (hits, sparks,
explosions, beacon waves), floating numbers, and speech / thought bubbles that
follow an actor. The simulation never sees any of this."""

from __future__ import annotations

from dataclasses import dataclass, field

from .bank import SpriteBank
from .lighting import Light

RGB = tuple[int, int, int]


@dataclass
class Effect:
    name: str
    x: float  # world px
    y: float
    start: float
    until: float
    vx: float = 0.0
    vy: float = 0.0
    z: float = 0.0  # height above the ground point, px
    vz: float = 0.0
    emissive: bool = False
    anchored: bool = False  # True: (x, y) is the sprite's ground anchor; False: its centre
    flip: bool = False
    light: tuple[float, RGB] | None = None  # (radius px, colour) while alive
    sort_bias: float = 8.0  # effects sort slightly in front of what they hit

    def pos(self, now: float) -> tuple[float, float, float]:
        dt = now - self.start
        return self.x + self.vx * dt, self.y + self.vy * dt, max(0.0, self.z + self.vz * dt)


@dataclass
class FloatText:
    text: str
    color: RGB
    x: float  # world px
    y: float
    start: float
    until: float
    rise: float = 16.0
    size: int = 16
    z: float = 0.0


@dataclass
class Bubble:
    text: str
    kind: str  # speech | thought | thinking
    start: float
    until: float


@dataclass
class Effects:
    fx: list[Effect] = field(default_factory=list)
    texts: list[FloatText] = field(default_factory=list)
    bubbles: dict[object, Bubble] = field(default_factory=dict)

    def spawn(self, bank: SpriteBank, name: str, x: float, y: float, now: float,
              duration: float | None = None, **kw) -> Effect | None:
        if name not in bank:
            return None
        a = bank.art(name)
        if duration is None:
            duration = len(a.frames) / a.fps if (a.fps and not a.loop) else 1.0
        e = Effect(name, x, y, now, now + duration, **kw)
        self.fx.append(e)
        if len(self.fx) > 400:
            del self.fx[:100]
        return e

    def text(self, text: str, color: RGB, x: float, y: float, now: float, duration: float = 1.2,
             **kw) -> None:
        # don't stack identical numbers on the same spot
        for t in self.texts:
            if t.text == text and abs(t.x - x) < 4 and now - t.start < 0.25:
                return
        self.texts.append(FloatText(text, color, x, y, now, now + duration, **kw))
        if len(self.texts) > 60:
            del self.texts[:20]

    def say(self, who: object, text: str, kind: str, now: float, duration: float | None = None) -> None:
        if duration is None:
            duration = min(9.0, 2.5 + len(text) * 0.06)
        self.bubbles[who] = Bubble(text, kind, now, now + duration)

    def prune(self, now: float) -> None:
        self.fx = [e for e in self.fx if e.until > now]
        self.texts = [t for t in self.texts if t.until > now]
        self.bubbles = {k: b for k, b in self.bubbles.items() if b.until > now}

    def lights(self, frame) -> list[Light]:
        out = []
        now = frame.now
        for e in self.fx:
            if e.light is None or e.start > now:
                continue
            x, y, z = e.pos(now)
            radius, color = e.light
            fade = max(0.2, min(1.0, (e.until - now) / max(0.01, e.until - e.start) * 1.5))
            cx, cy = frame.project(x, y, z)
            out.append(Light(cx, cy, radius, color, intensity=fade, glow=True))
        return out

    def clear(self) -> None:
        self.fx.clear()
        self.texts.clear()
        self.bubbles.clear()
