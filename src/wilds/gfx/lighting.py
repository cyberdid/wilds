"""Day/night and light sources.

The world is first drawn fully lit; then a light map (ambient colour + every
light source's radial gradient, combined with MAX) multiplies it. Emissive
things (flames, neon, screens) additionally get a soft additive halo so they
bloom in the dark. Everything is drawn at the 1x canvas resolution, so it is
cheap and stays pixel-crisp after the integer upscale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from .palette import RGB, mix

DAY = (255, 255, 255)
NIGHT = (34, 40, 78)

# (hour, ambient colour) keyframes, interpolated; hours outside wrap around
TAU7_SKY = [
    (0.0, NIGHT), (4.8, NIGHT), (5.8, (92, 70, 112)), (6.6, (214, 150, 150)), (7.6, (246, 222, 206)),
    (8.6, DAY), (16.4, DAY), (17.6, (250, 214, 170)), (18.8, (228, 136, 110)), (19.6, (120, 74, 118)),
    (20.4, NIGHT), (24.0, NIGHT),
]
CITY_NIGHT = (58, 50, 100)  # dark enough for neon to own the night, light enough to read the street
CITY_SKY = [
    (0.0, CITY_NIGHT), (5.0, CITY_NIGHT), (6.2, (120, 104, 150)), (7.4, (206, 200, 222)),
    (8.4, (232, 230, 240)), (18.6, (232, 230, 240)), (19.8, (206, 150, 176)), (20.6, (116, 80, 130)),
    (21.4, CITY_NIGHT), (24.0, CITY_NIGHT),
]
STATION_SKY = [(0.0, (130, 140, 172)), (24.0, (130, 140, 172))]
OUTPOST_SKY = [
    (0.0, (36, 36, 70)), (5.2, (36, 36, 70)), (6.4, (226, 160, 128)), (7.6, (255, 236, 210)),
    (18.2, (255, 236, 210)), (19.6, (220, 120, 96)), (20.8, (36, 36, 70)), (24.0, (36, 36, 70)),
]
WRECK_AMBIENT = (16, 16, 26)
STORM_TINT = (196, 128, 96)


def sky(frames: list[tuple[float, RGB]], hour: float) -> RGB:
    hour %= 24.0
    for (h0, c0), (h1, c1) in zip(frames, frames[1:]):
        if h0 <= hour <= h1:
            t = (hour - h0) / (h1 - h0) if h1 > h0 else 0.0
            t = t * t * (3 - 2 * t)
            return mix(c0, c1, t)
    return frames[-1][1]


def darkness(ambient: RGB) -> float:
    """0 in daylight .. 1 in pitch dark (drives how much lights matter)."""
    return 1.0 - max(ambient) / 255.0


@dataclass
class Light:
    x: float  # canvas px
    y: float
    radius: float  # px
    color: RGB = (255, 236, 200)
    intensity: float = 1.0
    flicker: float = 0.0  # 0..1: radius jitter for flames and bad neon
    glow: bool = False  # also add a soft additive halo (bloom)
    phase: float = 0.0
    squash: float = 1.0  # vertical scale: 0.6 flattens pools of light onto an isometric floor


class LightMap:
    def __init__(self) -> None:
        self._grad: dict[int, pygame.Surface] = {}
        self._tint: dict[tuple, pygame.Surface] = {}
        self._map: pygame.Surface | None = None

    def gradient(self, r: int) -> pygame.Surface:
        g = self._grad.get(r)
        if g is None:
            g = pygame.Surface((2 * r, 2 * r))
            g.fill((0, 0, 0))
            steps = max(8, min(r, 40))
            for i in range(steps):
                d = 1.0 - i / steps  # outer -> inner
                v = int(255 * (1.0 - d) ** 1.35)
                pygame.draw.circle(g, (v, v, v), (r, r), max(1, int(r * d)))
            self._grad[r] = g
        return g

    def tinted(self, r: int, color: RGB, intensity: float, squash: float = 1.0) -> pygame.Surface:
        q = max(1, min(8, round(intensity * 8)))
        c = tuple(min(255, (v // 16) * 16 + 8) for v in color)
        sq = round(squash, 1)
        key = (r, c, q, sq)
        s = self._tint.get(key)
        if s is None:
            s = self.gradient(r).copy()
            if sq != 1.0:
                s = pygame.transform.smoothscale(s, (2 * r, max(2, int(2 * r * sq))))
            k = q / 8
            s.fill((int(c[0] * k), int(c[1] * k), int(c[2] * k)), special_flags=pygame.BLEND_MULT)
            if len(self._tint) > 600:
                self._tint.clear()
            self._tint[key] = s
        return s

    @staticmethod
    def _radius(light: Light, t: float) -> int:
        r = light.radius
        if light.flicker:
            n = math.sin(t * 9.1 + light.phase) * 0.5 + math.sin(t * 23.7 + light.phase * 2.3) * 0.3
            r *= 1.0 + light.flicker * 0.12 * n
        return max(4, int(r) // 2 * 2)

    def render(self, size: tuple[int, int], ambient: RGB, lights: list[Light], t: float) -> pygame.Surface:
        if self._map is None or self._map.get_size() != size:
            self._map = pygame.Surface(size)
        lm = self._map
        lm.fill(ambient)
        if darkness(ambient) < 0.04:
            return lm
        w, h = size
        for light in lights:
            r = self._radius(light, t)
            if light.x + r < 0 or light.y + r < 0 or light.x - r > w or light.y - r > h:
                continue
            spr = self.tinted(r, light.color, light.intensity, light.squash)
            lm.blit(spr, (int(light.x) - r, int(light.y) - spr.get_height() // 2),
                    special_flags=pygame.BLEND_MAX)
        return lm

    def bloom(self, canvas: pygame.Surface, ambient: RGB, lights: list[Light], t: float) -> None:
        """Additive halos for emissive lights, stronger the darker it is."""
        k = darkness(ambient)
        if k < 0.2:
            return
        for light in lights:
            if not light.glow:
                continue
            r = max(4, self._radius(light, t) // 2)
            halo = self.tinted(r, light.color, light.intensity * 0.45 * k)
            canvas.blit(halo, (int(light.x) - r, int(light.y) - r), special_flags=pygame.BLEND_ADD)
