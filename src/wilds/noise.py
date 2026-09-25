"""Deterministic 2D value noise with octaves (no external dependencies)."""

from __future__ import annotations

import math
import random


class ValueNoise:
    def __init__(self, seed: int, grid: int = 256) -> None:
        rng = random.Random(seed)
        self._grid = grid
        self._values = [rng.random() for _ in range(grid * grid)]

    def _lattice(self, ix: int, iy: int) -> float:
        g = self._grid
        return self._values[(iy % g) * g + (ix % g)]

    def sample(self, x: float, y: float) -> float:
        """Smoothly interpolated noise in [0, 1]."""
        ix, iy = math.floor(x), math.floor(y)
        fx, fy = x - ix, y - iy
        sx = fx * fx * (3 - 2 * fx)
        sy = fy * fy * (3 - 2 * fy)
        a = self._lattice(ix, iy)
        b = self._lattice(ix + 1, iy)
        c = self._lattice(ix, iy + 1)
        d = self._lattice(ix + 1, iy + 1)
        top = a + (b - a) * sx
        bottom = c + (d - c) * sx
        return top + (bottom - top) * sy

    def fractal(self, x: float, y: float, octaves: int = 4) -> float:
        total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
        for _ in range(octaves):
            total += self.sample(x * freq, y * freq) * amp
            norm += amp
            amp *= 0.5
            freq *= 2.0
        return total / norm
