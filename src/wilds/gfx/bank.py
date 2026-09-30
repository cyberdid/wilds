"""Registry Art -> pygame Surfaces, cached per (name, scale, flip, tint).

Also the art-override hook: if an overrides directory holds ``<sprite name>.png``
(all frames side by side at 1x, exactly the format ``wilds-sprites --strips``
exports), that image replaces the built-in pixels - so an artist, or an image
generator, can repaint any sprite without touching code.
"""

from __future__ import annotations

import math
from pathlib import Path

import pygame

from .pixelart import Art, emissive_rgba
from .registry import Registry

Tint = tuple[str, tuple[int, int, int]] | str | None


class SpriteBank:
    def __init__(self, registry: Registry | None = None, overrides: Path | str | None = None) -> None:
        if registry is None:
            from .sprites import load_all

            registry = load_all()
        self.registry = registry
        self.overrides = Path(overrides) if overrides else None
        self._base: dict[str, list[pygame.Surface]] = {}
        self._cache: dict[tuple, list[pygame.Surface]] = {}
        self._glow: dict[tuple, list[pygame.Surface | None]] = {}
        self._iso: dict[tuple, pygame.Surface | None] = {}
        self.overridden: set[str] = set()

    # --- lookup -------------------------------------------------------------
    def art(self, name: str) -> Art:
        return self.registry.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self.registry

    def base(self, name: str) -> list[pygame.Surface]:
        frames = self._base.get(name)
        if frames is None:
            frames = self._load(name)
            self._base[name] = frames
        return frames

    def _load(self, name: str) -> list[pygame.Surface]:
        a = self.registry.get(name)
        w, h = a.size
        if self.overrides is not None:
            path = self.overrides / f"{name}.png"
            if path.exists():
                strip = _convert(pygame.image.load(str(path)))
                n = max(1, strip.get_width() // w)
                fh = min(h, strip.get_height())
                self.overridden.add(name)
                return [strip.subsurface((i * w, 0, w, fh)).copy() for i in range(n)]
        return [_convert(pygame.image.frombytes(a.rgba(i), (w, h), "RGBA"))
                for i in range(len(a.frames))]

    def frames(self, name: str, scale: int = 1, flip: bool = False, tint: Tint = None) -> list[pygame.Surface]:
        key = (name, scale, flip, tint)
        out = self._cache.get(key)
        if out is None:
            out = []
            for s in self.base(name):
                if flip:
                    s = pygame.transform.flip(s, True, False)
                if tint is not None:
                    s = _tinted(s, tint)
                if scale != 1:
                    s = pygame.transform.scale(s, (s.get_width() * scale, s.get_height() * scale))
                out.append(s)
            self._cache[key] = out
        return out

    def frame(self, name: str, t: float = 0.0, scale: int = 1, flip: bool = False,
              tint: Tint = None) -> pygame.Surface:
        frames = self.frames(name, scale, flip, tint)
        a = self.registry.get(name)
        if len(frames) == 1:
            return frames[0]
        i = a.frame_index(t) if len(frames) == len(a.frames) else int(t * max(a.fps, 1)) % len(frames)
        return frames[i % len(frames)]

    def glow(self, name: str, t: float = 0.0, flip: bool = False) -> pygame.Surface | None:
        """The frame's light-emitting pixels only (1x), or None. Overridden art has none."""
        key = (name, flip)
        layers = self._glow.get(key)
        if layers is None:
            a = self.registry.get(name)
            layers = []
            if name not in self.overridden:
                for i in range(len(a.frames)):
                    data = emissive_rgba(a, i)
                    if data is None:
                        layers.append(None)
                        continue
                    s = _convert(pygame.image.frombytes(data, a.size, "RGBA"))
                    layers.append(pygame.transform.flip(s, True, False) if flip else s)
            self._glow[key] = layers
        if not layers:
            return None
        a = self.registry.get(name)
        return layers[a.frame_index(t) % len(layers)]

    # --- isometric ------------------------------------------------------------------
    def _index(self, name: str, t: float) -> int:
        frames = self.base(name)
        return self.registry.get(name).frame_index(t) % len(frames) if len(frames) > 1 else 0

    def iso_tile(self, name: str, t: float = 0.0) -> pygame.Surface:
        """A 16x16 ground texture mapped onto a 32x16 isometric diamond."""
        i = self._index(name, t)
        key = ("tile", name, i)
        s = self._iso.get(key)
        if s is None:
            s = _to_diamond(self.base(name)[i])
            self._iso[key] = s
        return s

    def iso_glow(self, name: str, t: float = 0.0) -> pygame.Surface | None:
        g = self.glow(name, t)
        if g is None:
            return None
        i = self._index(name, t)
        key = ("glow", name, i)
        if key not in self._iso:
            self._iso[key] = _to_diamond(g)
        return self._iso[key]

    def iso_block(self, top: str, face: str, t: float, height: int, south: bool, east: bool,
                  memory: bool = False) -> pygame.Surface:
        """An extruded isometric cube: the top texture on a diamond raised by
        ``height`` px, the face texture on the south (left) and east (right) walls."""
        ti, fi = self._index(top, t), self._index(face, t)
        key = ("block", top, face, ti, fi, height, south, east, memory)
        s = self._iso.get(key)
        if s is None:
            s = pygame.Surface((32, 16 + height), pygame.SRCALPHA)
            tex = self.base(face)[fi]
            if south:
                s.blit(_to_wall(tex, height, left=True, shade=236), (0, 8))
            if east:
                s.blit(_to_wall(tex, height, left=False, shade=176), (16, 8))
            s.blit(self.iso_tile(top, t), (0, 0))
            if south and east:
                pygame.draw.line(s, (20, 15, 30), (16, 16), (16, 15 + height))
            if memory:  # remembered, not seen: the fog veil only covers the footprint
                s = _tinted(s, "memory")
            self._iso[key] = s
        return s

    def facade(self, names: tuple[str, ...], t: float = 0.0) -> tuple[pygame.Surface, pygame.Surface | None]:
        """Stack facade modules top to bottom into one 16 px wide strip, plus the strip's
        light-emitting pixels (lit windows, neon) or None."""
        idx = tuple(self._index(n, t) for n in names)
        key = ("facade", names, idx)
        hit = self._iso.get(key)
        if hit is None:
            parts = [self.base(n)[i] for n, i in zip(names, idx)]
            s = pygame.Surface((16, sum(p.get_height() for p in parts)), pygame.SRCALPHA)
            g = pygame.Surface(s.get_size(), pygame.SRCALPHA)
            y, lit = 0, False
            for n, p in zip(names, parts):
                s.blit(p, (0, y))
                layer = self.glow(n, t)
                if layer is not None:
                    g.blit(layer, (0, y))
                    lit = True
                y += p.get_height()
            hit = (s, g if lit else None)
            self._iso[key] = hit
        return hit

    def iso_tower(self, top: str, names: tuple[str, ...], t: float, south: bool, east: bool,
                  memory: bool = False) -> tuple[pygame.Surface, pygame.Surface | None]:
        """An isometric building tile as tall as its facade strip: the roof diamond on
        top, the strip itself (1:1, not stretched) on the exposed south/east walls."""
        ti = self._index(top, t)
        idx = tuple(self._index(n, t) for n in names)
        key = ("tower", top, ti, names, idx, south, east, memory)
        hit = self._iso.get(key)
        if hit is None:
            strip, glow = self.facade(names, t)
            height = strip.get_height()
            s = pygame.Surface((32, 16 + height), pygame.SRCALPHA)
            g = pygame.Surface(s.get_size(), pygame.SRCALPHA) if glow is not None and not memory else None
            for side, x, shade in (("s", 0, 236), ("e", 16, 176)):
                if (south if side == "s" else east):
                    s.blit(_to_wall(strip, height, left=side == "s", shade=shade), (x, 8))
                    if g is not None:
                        g.blit(_to_wall(glow, height, left=side == "s", shade=255), (x, 8))
            s.blit(self.iso_tile(top, t), (0, 0))
            if south and east:
                pygame.draw.line(s, (20, 15, 30), (16, 16), (16, 15 + height))
            if memory:
                s = _tinted(s, "memory")
            hit = (s, g)
            self._iso[key] = hit
        return hit

    def anchor(self, name: str, scale: int = 1, flip: bool = False) -> tuple[int, int]:
        a = self.registry.get(name)
        ax, ay = a.ground_anchor
        if flip:
            ax = a.size[0] - 1 - ax
        return ax * scale, ay * scale

    def clear(self) -> None:
        self._cache.clear()
        self._glow.clear()
        self._iso.clear()


def _to_diamond(src: pygame.Surface) -> pygame.Surface:
    """Texture-map a square tile onto a 2:1 diamond, pixel-exact (nearest texel).

    Diamond vertices top (16,0), right (32,8), bottom (16,16), left (0,8) take the
    square's corners (0,0), (w,0), (w,h), (0,h): sx = 16 + u - v, sy = (u + v) / 2."""
    w, h = src.get_size()
    dst = pygame.Surface((32, 16), pygame.SRCALPHA)
    for sy in range(16):
        for sx in range(32):
            u = (sx + 2 * sy - 14.5) / 2
            v = (2 * sy - sx + 16.5) / 2
            if 0 <= u < 16 and 0 <= v < 16:
                dst.set_at((sx, sy), src.get_at((int(u * w / 16), int(v * h / 16))))
    return dst


def _to_wall(src: pygame.Surface, height: int, left: bool, shade: int) -> pygame.Surface:
    """Map a wall-face texture onto the slanted south (left) or east (right) wall."""
    w, h = src.get_size()
    dst = pygame.Surface((16, height + 8), pygame.SRCALPHA)
    if (w, h) == (16, height):  # an unstretched strip (a tall facade): shear it column by column
        for dx in range(16):
            dst.blit(src, (dx, math.ceil(dx / 2 if left else 8 - dx / 2)), pygame.Rect(dx, 0, 1, h))
        if shade < 255:
            dst.fill((shade, shade, min(255, shade + 14), 255), special_flags=pygame.BLEND_RGBA_MULT)
        return dst
    for dy in range(height + 8):
        for dx in range(16):
            v = dy - (dx / 2 if left else 8 - dx / 2)
            if 0 <= v < height:
                dst.set_at((dx, dy), src.get_at((int(dx * w / 16), min(h - 1, int(v * h / height)))))
    if shade < 255:
        dst.fill((shade, shade, min(255, shade + 14), 255), special_flags=pygame.BLEND_RGBA_MULT)
    return dst


def _convert(s: pygame.Surface) -> pygame.Surface:
    """convert_alpha() when a display exists (fast blits); plain copy otherwise."""
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        return s.convert_alpha()
    return s.copy()


def _tinted(s: pygame.Surface, tint: Tint) -> pygame.Surface:
    s = s.copy()
    if tint == "gray":
        return pygame.transform.grayscale(s)
    if tint == "memory":  # fog of war: remembered but not seen right now
        g = pygame.transform.grayscale(s)
        g.fill((105, 110, 140, 255), special_flags=pygame.BLEND_RGBA_MULT)
        return g
    if tint == "silhouette":  # x-ray outline of a figure hidden behind something tall
        mask = pygame.mask.from_surface(s)
        return mask.to_surface(setcolor=(255, 230, 120, 110), unsetcolor=(0, 0, 0, 0))
    mode, color = tint  # type: ignore[misc]
    if mode == "mul":
        s.fill((*color, 255), special_flags=pygame.BLEND_RGBA_MULT)
    elif mode == "add":
        s.fill((*color, 0), special_flags=pygame.BLEND_RGB_ADD)
    elif mode == "flat":  # every opaque pixel one colour (hit flash)
        mask = pygame.mask.from_surface(s)
        return mask.to_surface(setcolor=(*color, 255), unsetcolor=(0, 0, 0, 0))
    else:
        raise ValueError(f"unknown tint {tint!r}")
    return s
