"""Weather and ambient particles, simulated in world pixel space (x, y on the
ground plane plus a height z) so they stay put when the camera moves and look
right in both projections: rain falls straight down the screen, spores and
embers rise, storm dust is blown along the ground."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame

from .bank import SpriteBank


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    z: float = 0.0
    vz: float = 0.0
    age: float = 0.0
    sprite: str | None = None
    color: tuple[int, int, int] = (255, 255, 255)
    size: int = 1
    fade: bool = True
    glow: bool = False
    phase: float = 0.0
    wobble: float = 0.0  # sideways sine drift amplitude (spores)


class Particles:
    def __init__(self, seed: int = 7) -> None:
        self.items: list[Particle] = []
        self.rng = random.Random(seed)
        self._acc: dict[str, float] = {}

    def clear(self) -> None:
        self.items.clear()

    def emit(self, **kw) -> Particle:
        p = Particle(**kw)
        self.items.append(p)
        return p

    def update(self, dt: float) -> None:
        alive = []
        for p in self.items:
            p.age += dt
            if p.age >= p.life:
                continue
            p.x += p.vx * dt + (math.sin(p.age * 2.3 + p.phase) * p.wobble * dt if p.wobble else 0.0)
            p.y += p.vy * dt
            p.z += p.vz * dt
            if p.z < 0 and p.vz < 0:  # hit the ground
                continue
            alive.append(p)
        self.items = alive if len(alive) < 1500 else alive[-1500:]

    def spawn_rate(self, key: str, rate: float, dt: float) -> int:
        """How many to emit this frame for a steady `rate` per second."""
        acc = self._acc.get(key, 0.0) + rate * dt
        n = int(acc)
        self._acc[key] = acc - n
        return n

    # --- weather emitters (rect = world area in view, px) ------------------------------
    def storm(self, rect: pygame.Rect, dt: float, intensity: float = 1.0) -> None:
        rng = self.rng
        for _ in range(self.spawn_rate("storm", 260 * intensity * rect.width * rect.height / 90000, dt)):
            self.emit(x=rect.left - 20 + rng.random() * (rect.width + 40), y=rect.top + rng.random() * rect.height,
                      z=rng.random() * 24, vx=110 + rng.random() * 90, vy=18 + rng.random() * 24,
                      life=1.2 + rng.random(), sprite=f"fx.dust@{rng.randrange(2)}")

    def rain(self, rect: pygame.Rect, dt: float, intensity: float = 1.0) -> None:
        rng = self.rng
        for _ in range(self.spawn_rate("rain", 150 * intensity * rect.width * rect.height / 90000, dt)):
            self.emit(x=rect.left + rng.random() * rect.width, y=rect.top + rng.random() * rect.height,
                      z=60 + rng.random() * 60, vx=-18, vy=0, vz=-300 - rng.random() * 60, life=1.0,
                      sprite="fx.rain", fade=False)

    def spores(self, rect: pygame.Rect, dt: float, intensity: float = 1.0) -> None:
        rng = self.rng
        for _ in range(self.spawn_rate("spores", 6 * intensity * rect.width * rect.height / 90000, dt)):
            self.emit(x=rect.left + rng.random() * rect.width, y=rect.top + rng.random() * rect.height,
                      z=2 + rng.random() * 10, vx=rng.uniform(-3, 3), vy=rng.uniform(-2, 2),
                      vz=rng.uniform(3, 8), life=4 + rng.random() * 4, sprite="fx.spore", glow=True,
                      phase=rng.random() * 6.28, wobble=9)

    def embers(self, x: float, y: float, dt: float, rate: float = 3.0, key: str = "ember", z: float = 8,
               down: bool = False) -> None:
        """Rising sparks from a fire; ``down=True`` blasts them downward (thrusters)."""
        rng = self.rng
        for _ in range(self.spawn_rate(key, rate, dt)):
            vz = -rng.uniform(60, 110) if down else rng.uniform(12, 22)
            self.emit(x=x + rng.uniform(-2 if down else -3, 2 if down else 3), y=y, z=z,
                      vx=rng.uniform(-4, 4), vy=0, vz=vz, life=(0.25 if down else 0.6) + rng.random() * 0.4,
                      color=rng.choice([(255, 190, 90), (255, 120, 60)]), glow=True)

    def puff(self, x: float, y: float, n: int = 6, color=(200, 190, 210), speed: float = 20, z: float = 6) -> None:
        rng = self.rng
        for _ in range(n):
            a = rng.random() * math.tau
            s = speed * (0.4 + rng.random())
            self.emit(x=x, y=y, z=z, vx=math.cos(a) * s, vy=math.sin(a) * s * 0.5, vz=rng.uniform(4, 16),
                      life=0.4 + rng.random() * 0.4, color=color, size=rng.choice((1, 1, 2)))

    # --- drawing --------------------------------------------------------------------
    def draw(self, canvas: pygame.Surface, frame, bank: SpriteBank) -> None:
        w, h = canvas.get_size()
        t = frame.now
        for p in self.items:
            x, y = frame.project(p.x, p.y, p.z)
            if x < -16 or y < -16 or x > w + 16 or y > h + 16:
                continue
            k = 1.0 - p.age / p.life if p.fade else 1.0
            if p.sprite and p.sprite in bank:
                fr = bank.frame(p.sprite, t + p.phase)
                if k < 1.0:
                    fr = fr.copy()
                    fr.set_alpha(int(255 * k))
                canvas.blit(fr, (x - fr.get_width() // 2, y - fr.get_height() // 2),
                            special_flags=pygame.BLEND_ADD if p.glow else 0)
            else:
                c = p.color if k >= 1.0 else tuple(int(v * k) for v in p.color)
                canvas.fill(c, (x, y, p.size, p.size), special_flags=pygame.BLEND_ADD if p.glow else 0)
