"""The 2.5D scene renderer shared by both chapters, in two projections.

A chapter scene fills a ``Frame`` in *world* terms - ground tiles, blocks
(rock, bulkheads, buildings) with their open sides, sprites standing on world
points with a height ``z`` above the ground, lights, fog per tile - and the
frame's projection decides where that lands on the canvas:

* ``TopDown`` - the 3/4 view: square tiles, blocks show a front face where the
  street/ground opens to the south, sprites are sorted by their ground row.
* ``Iso`` - isometric 2.5D: ground textures are mapped onto 2:1 diamonds,
  blocks become extruded cubes (skylines, cliffs), everything is depth-sorted
  along the diagonal.

The ``Renderer`` then composes on a 1x canvas: ground -> sorted sprites ->
light map (multiply) -> emissive pixels -> bloom -> emissive sprites ->
particles -> fog of war -> weather tint, scales it up by an integer zoom and
draws bubbles and numbers crisp at screen resolution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pygame

from . import text as txt
from .bank import SpriteBank, Tint
from .effects import Effects
from .lighting import DAY, Light, LightMap
from .particles import Particles

TILE = 16
VOID = (7, 6, 13)
EDGE = (20, 15, 30)
FOG_MEMORY = (8, 10, 22, 150)
FOG_UNKNOWN = (0, 0, 0, 255)


# --- projections -------------------------------------------------------------------


class TopDown:
    """The 3/4 top-down view: world px are view px, height is simply 'up'."""

    iso = False
    name = "2D"

    @staticmethod
    def to_view(gx: float, gy: float, z: float = 0.0) -> tuple[float, float]:
        return gx, gy - z

    @staticmethod
    def depth(gx: float, gy: float) -> float:
        return gy

    @staticmethod
    def tile_origin(tx: int, ty: int) -> tuple[int, int]:
        return tx * TILE, ty * TILE

    @staticmethod
    def tiles_in(x0: float, y0: float, w: int, h: int, margin: int = 1, below: int = 3):
        return (int(x0 // TILE) - margin, int(y0 // TILE) - margin,
                int((x0 + w) // TILE) + margin, int((y0 + h) // TILE) + margin + below)

    @staticmethod
    def bounds(level_w: int, level_h: int) -> tuple[float, float, float, float]:
        return 0.0, 0.0, level_w * TILE, level_h * TILE


class Iso:
    """Isometric 2:1: tile (x, y) is a 32x16 diamond whose top vertex sits at
    ((x - y) * 16, (x + y) * 8); a world ground point maps to its diamond centre."""

    iso = True
    name = "2.5D"

    @staticmethod
    def to_view(gx: float, gy: float, z: float = 0.0) -> tuple[float, float]:
        fx, fy = (gx - TILE // 2) / TILE, (gy - (TILE - 1)) / TILE
        return (fx - fy) * TILE, (fx + fy) * (TILE // 2) + TILE // 2 - z

    @staticmethod
    def depth(gx: float, gy: float) -> float:
        return (gx - TILE // 2) / TILE + (gy - (TILE - 1)) / TILE

    @staticmethod
    def tile_origin(tx: int, ty: int) -> tuple[int, int]:
        """Top-left of the tile's 32x16 diamond bounding box."""
        return (tx - ty) * TILE - TILE, (tx + ty) * (TILE // 2)

    @staticmethod
    def tiles_in(x0: float, y0: float, w: int, h: int, margin: int = 2, below: int = 4):
        pts = []
        for vx, vy in ((x0, y0), (x0 + w, y0), (x0, y0 + h), (x0 + w, y0 + h)):
            a, b = vx / TILE, (vy - TILE // 2) / (TILE // 2)
            pts.append(((a + b) / 2, (b - a) / 2))
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (int(min(xs)) - margin, int(min(ys)) - margin,
                int(max(xs)) + margin + below, int(max(ys)) + margin + below)

    @staticmethod
    def bounds(level_w: int, level_h: int) -> tuple[float, float, float, float]:
        return -level_h * TILE, 0.0, level_w * TILE, (level_w + level_h) * (TILE // 2) + TILE


PROJECTIONS = {"2d": TopDown(), "iso": Iso()}


# --- the frame ----------------------------------------------------------------------


@dataclass
class Placed:
    surf: pygame.Surface
    x: int
    y: int
    sort: tuple
    shadow: int = 0  # shadow width in px, drawn at the ground point
    gx: int = 0  # canvas px of the ground point
    gy: int = 0
    xray: pygame.Surface | None = None  # silhouette shown if something tall hides this sprite
    glow: pygame.Surface | None = None  # its emissive pixels, redrawn after lighting
    solid: bool = False  # can hide what is behind it (objects, blocks)


@dataclass
class Frame:
    """Everything one world frame needs. Scenes speak world px; the projection places it."""

    bank: SpriteBank
    cam_x: float  # view px of the canvas' top-left (float: sub-pixel scrolling)
    cam_y: float
    w: int
    h: int
    now: float
    zoom: int
    proj: object = field(default_factory=TopDown)
    ground: list = field(default_factory=list)
    glow: list = field(default_factory=list)  # emissive pixel layers of ground, drawn after lighting
    lines: list = field(default_factory=list)
    placed: list[Placed] = field(default_factory=list)
    post: list[Placed] = field(default_factory=list)
    lights: list[Light] = field(default_factory=list)
    ambient: tuple[int, int, int] = DAY
    fog: dict = field(default_factory=dict)  # (tx, ty) -> rgba, None = no fog (god view)
    fog_on: bool = False
    fog_range: tuple = (0, 0, -1, -1)
    anchors: dict = field(default_factory=dict)  # actor key -> (gx, gy, z) world, for bubbles
    missing: set = field(default_factory=set)

    @property
    def ox(self) -> int:
        return int(math.floor(self.cam_x))

    @property
    def oy(self) -> int:
        return int(math.floor(self.cam_y))

    def project(self, gx: float, gy: float, z: float = 0.0) -> tuple[int, int]:
        vx, vy = self.proj.to_view(gx, gy, z)
        return int(round(vx)) - self.ox, int(round(vy)) - self.oy

    def tile_range(self, rise: int = 0) -> tuple[int, int, int, int]:
        """Tiles that can touch the canvas (with slack for tall objects); ``rise`` px of
        buildings standing below the canvas can still reach up into it."""
        extra = 0
        if rise:
            extra = rise // (TILE // 2 if self.proj.iso else TILE) + 1
        tx0, ty0, tx1, ty1 = self.proj.tiles_in(self.ox, self.oy, self.w, self.h)
        return tx0, ty0, tx1 + (extra if self.proj.iso else 0), ty1 + extra

    def _surf(self, name: str, t: float, flip: bool = False, tint: Tint = None) -> pygame.Surface:
        if name in self.bank:
            return self.bank.frame(name, t, 1, flip, tint)
        self.missing.add(name)
        return _placeholder()

    # --- ground ---------------------------------------------------------------------
    def ground_tile(self, name: str, tx: int, ty: int, t: float = 0.0, tint: Tint = None,
                    glow: bool = True) -> None:
        x, y = self.proj.tile_origin(tx, ty)
        pos = (x - self.ox, y - self.oy)
        if self.proj.iso:
            if name not in self.bank:
                self.missing.add(name)
                return
            self.ground.append((self.bank.iso_tile(name, t), pos))
            if glow and tint is None:
                g = self.bank.iso_glow(name, t)
                if g is not None:
                    self.glow.append((g, pos))
            return
        self.ground.append((self._surf(name, t, tint=tint), pos))
        if glow and tint is None and name in self.bank:
            g = self.bank.glow(name, t)
            if g is not None:
                self.glow.append((g, pos))

    @property
    def iso(self) -> bool:
        return self.proj.iso

    @property
    def flat_z(self) -> int:
        """Height that puts a centred sprite on the tile's visual centre."""
        return 0 if self.proj.iso else TILE // 2 - 1

    def block(self, top: str, face: str, tx: int, ty: int, t: float, open_sides: str,
              height: int = 12, memory: bool = False) -> None:
        """A rock / bulkhead / building tile. ``open_sides`` (subset of 'nesw') are the
        sides whose neighbour is not the same block."""
        if not self.proj.iso:
            if "s" in open_sides:
                self.ground_tile(face, tx, ty, t)
            else:
                self.ground_tile(top, tx, ty, t)
                x, y = tx * TILE - self.ox, ty * TILE - self.oy
                for s in open_sides:
                    self.lines.append({"n": (x, y, TILE, 1), "w": (x, y, 1, TILE),
                                       "e": (x + TILE - 1, y, 1, TILE)}[s])
            return
        for name in (top, face):
            if name not in self.bank:
                self.missing.add(name)
                return
        x0, y0 = self.proj.tile_origin(tx, ty)
        x0, y0 = x0 - self.ox, y0 - self.oy
        cube = self.bank.iso_block(top, face, t, height, "s" in open_sides, "e" in open_sides, memory)
        depth = tx + ty + 0.5
        self.placed.append(Placed(cube, x0, y0 - height, (depth, 0, tx), solid=True))

    def tower(self, top: str, facade: tuple[str, ...], tx: int, ty: int, t: float, open_sides: str,
              front_row: int, memory: bool = False) -> None:
        """A building tile at street scale: ``facade`` is its column of modules (parapet,
        storeys, street floor), which also sets its height. In 2.5D it is an extruded cube;
        in 3/4 view the roof is lifted by that height and the south-most row of the block
        (``front_row``) shows the facade - the whole block sorts at its street front, so
        people behind it are covered (and get the x-ray outline)."""
        for name in (top, *facade):
            if name not in self.bank:
                self.missing.add(name)
                return
        if self.proj.iso:
            cube, glow = self.bank.iso_tower(top, facade, t, "s" in open_sides, "e" in open_sides, memory)
            x0, y0 = self.proj.tile_origin(tx, ty)
            height = cube.get_height() - TILE
            self.placed.append(Placed(cube, x0 - self.ox, y0 - self.oy - height, (tx + ty + 0.5, 0, tx),
                                      solid=True, glow=glow))
            return
        strip, glow = self.bank.facade(facade, t)
        height = strip.get_height()
        x = tx * TILE - self.ox
        sort = ((front_row + 1) * TILE - 0.5, 0, tx * TILE)
        roof = self.bank.frame(top, t)
        edges = "".join(sd for sd in "nwe" if sd in open_sides)
        if edges:
            roof = roof.copy()
            for sd in edges:
                roof.fill(EDGE, {"n": (0, 0, TILE, 1), "w": (0, 0, 1, TILE), "e": (TILE - 1, 0, 1, TILE)}[sd])
        self.placed.append(Placed(roof, x, ty * TILE - self.oy - height, sort, solid=True))
        # the lifted roof stands over tiles further north: don't let their fog veil it
        for row in range((ty * TILE - height) // TILE, ty):
            self.fog.setdefault((tx, row), FOG_MEMORY if memory else (0, 0, 0, 0))
        if ty == front_row:
            self.placed.append(Placed(strip, x, (ty + 1) * TILE - self.oy - height, sort, solid=True,
                                      glow=glow))

    def fog_tile(self, tx: int, ty: int, rgba: tuple[int, int, int, int] | None) -> None:
        """Mark a drawn tile: None = in plain sight, FOG_MEMORY = remembered only.
        Tiles never marked are unknown (pitch black)."""
        self.fog[(tx, ty)] = rgba if rgba is not None else (0, 0, 0, 0)

    # --- sprites and lights --------------------------------------------------------------
    def sprite(self, name: str, gx: float, gy: float, t: float = 0.0, flip: bool = False,
               tint: Tint = None, layer: int = 0, sort_y: float | None = None, alpha: int = 255,
               emissive: bool = False, shadow: int = 0, center: bool = False, z: float = 0.0,
               solid: bool | None = None) -> Placed:
        """Place a sprite so its anchor (or centre) sits ``z`` px above world point (gx, gy)."""
        surf = self._surf(name, t, flip, tint)
        if center:
            ax, ay = surf.get_width() // 2, surf.get_height() // 2
        elif name in self.bank:
            ax, ay = self.bank.anchor(name, 1, flip)
        else:
            ax, ay = surf.get_width() // 2, surf.get_height() - 1
        if alpha < 255:
            surf = surf.copy()
            surf.set_alpha(alpha)
        cx, cy = self.project(gx, gy, z)
        bx, by = self.project(gx, gy)
        depth = self.proj.depth(gx, sort_y if sort_y is not None else gy)
        p = Placed(surf, cx - ax, cy - ay, (depth, layer, gx), shadow, bx, by,
                   solid=(layer == 0) if solid is None else solid)
        (self.post if emissive else self.placed).append(p)
        if not emissive and tint is None and name in self.bank:
            g = self.bank.glow(name, t, flip)
            if g is not None:
                if alpha < 255:
                    g = g.copy()
                    g.set_alpha(alpha)
                p.glow = g
        return p

    def light(self, gx: float, gy: float, radius: float, color=(255, 236, 200), intensity: float = 1.0,
              flicker: float = 0.0, glow: bool = False, phase: float = 0.0, z: float = 0.0) -> None:
        x, y = self.project(gx, gy, z)
        self.lights.append(Light(x, y, radius, color, intensity, flicker, glow, phase,
                                 squash=0.6 if self.proj.iso else 1.0))


_PLACEHOLDER: pygame.Surface | None = None
_SHADOWS: dict[int, pygame.Surface] = {}
_DIAMONDS: dict[tuple, pygame.Surface] = {}


def _placeholder() -> pygame.Surface:
    global _PLACEHOLDER
    if _PLACEHOLDER is None:
        s = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
        for y in range(0, TILE, 4):
            for x in range(0, TILE, 4):
                s.fill((255, 0, 255, 200) if (x + y) // 4 % 2 else (0, 0, 0, 200), (x, y, 4, 4))
        _PLACEHOLDER = s
    return _PLACEHOLDER


def shadow(width: int) -> pygame.Surface:
    s = _SHADOWS.get(width)
    if s is None:
        h = max(3, width // 3)
        s = pygame.Surface((width, h), pygame.SRCALPHA)
        pygame.draw.ellipse(s, (0, 0, 0, 80), (0, 0, width, h))
        pygame.draw.ellipse(s, (0, 0, 0, 60), (1, 0, width - 2, max(1, h - 1)))
        _SHADOWS[width] = s
    return s


def diamond(rgba: tuple[int, int, int, int]) -> pygame.Surface:
    s = _DIAMONDS.get(rgba)
    if s is None:
        s = pygame.Surface((2 * TILE, TILE), pygame.SRCALPHA)
        pygame.draw.polygon(s, rgba, [(TILE, 0), (2 * TILE, TILE // 2), (TILE, TILE), (0, TILE // 2)])
        _DIAMONDS[rgba] = s
    return s


class Renderer:
    def __init__(self, bank: SpriteBank) -> None:
        self.bank = bank
        self.light = LightMap()
        self.particles = Particles()
        self.effects = Effects()
        self._canvas: pygame.Surface | None = None
        self._fog: pygame.Surface | None = None
        self.missing: set[str] = set()

    def canvas_size(self, view: pygame.Rect, zoom: int) -> tuple[int, int]:
        return math.ceil(view.width / zoom) + 1, math.ceil(view.height / zoom) + 1

    def frame(self, cam_x: float, cam_y: float, view: pygame.Rect, zoom: int, now: float,
              proj=None) -> Frame:
        w, h = self.canvas_size(view, zoom)
        return Frame(self.bank, cam_x, cam_y, w, h, now, zoom, proj or PROJECTIONS["2d"])

    def draw(self, f: Frame, screen: pygame.Surface, view: pygame.Rect, weather: tuple = ()) -> None:
        size = (f.w, f.h)
        if self._canvas is None or self._canvas.get_size() != size:
            self._canvas = pygame.Surface(size)
        c = self._canvas
        c.fill(VOID)
        c.fblits(f.ground)
        for rect in f.lines:
            c.fill(EDGE, rect)
        f.placed.sort(key=lambda p: p.sort)
        for p in f.placed:
            if p.shadow:
                s = shadow(p.shadow)
                c.blit(s, (p.gx - s.get_width() // 2, p.gy - s.get_height() // 2))
            c.blit(p.surf, (p.x, p.y))
        for i, p in enumerate(f.placed):  # x-ray: actors hidden behind tall things
            if p.xray is None:
                continue
            r = pygame.Rect(p.x, p.y, p.surf.get_width(), p.surf.get_height()).inflate(-4, -4)
            if any(q.solid and r.colliderect(q.x, q.y, q.surf.get_width(), q.surf.get_height())
                   for q in f.placed[i + 1:]):
                c.blit(p.xray, (p.x, p.y))
        # light
        lights = f.lights + self.effects.lights(f)
        lm = self.light.render(size, f.ambient, lights, f.now)
        c.blit(lm, (0, 0), special_flags=pygame.BLEND_MULT)
        if f.ambient != DAY:
            c.fblits(f.glow)
            for p in f.placed:  # emissive pixels stay bright (still behind what covers them)
                if p.glow is not None:
                    c.blit(p.glow, (p.x, p.y))
        self.light.bloom(c, f.ambient, lights, f.now)
        f.post.sort(key=lambda p: p.sort)
        for p in f.post:
            c.blit(p.surf, (p.x, p.y))
        self.particles.draw(c, f, self.bank)
        # fog of war goes over particles too, so nothing drifts over never-seen darkness
        if f.fog_on:
            self._draw_fog(c, f)
        for kind, strength in weather:
            if kind == "storm":
                tint = pygame.Surface(size, pygame.SRCALPHA)
                tint.fill((150, 70, 40, int(70 * strength)))
                c.blit(tint, (0, 0))
        self.missing |= f.missing
        # integer upscale with sub-pixel camera offset
        z = f.zoom
        scaled = pygame.transform.scale(c, (f.w * z, f.h * z))
        fx = int((f.cam_x - f.ox) * z)
        fy = int((f.cam_y - f.oy) * z)
        prev = screen.get_clip()
        screen.set_clip(view)
        screen.blit(scaled, (view.x - fx, view.y - fy))
        self._overlays(f, screen, view)
        screen.set_clip(prev)

    def _draw_fog(self, c: pygame.Surface, f: Frame) -> None:
        tx0, ty0, tx1, ty1 = f.fog_range
        if tx1 < tx0 or ty1 < ty0:
            return
        if f.proj.iso:
            # diamonds per tile; unknown tiles were never drawn, so only memory needs a veil
            for (tx, ty), rgba in f.fog.items():
                if 0 < rgba[3] < 255:
                    x, y = f.proj.tile_origin(tx, ty)
                    c.blit(diamond(rgba), (x - f.ox, y - f.oy))
            return
        # 1 px per tile, smoothed up: smoothscale aligns corners, so N px -> 16(N-1)+1 px puts
        # mask pixel i at 16i, and shifting by half a tile lands it on tile i's centre
        fw, fh = tx1 - tx0 + 1, ty1 - ty0 + 1
        if self._fog is None or self._fog.get_size() != (fw, fh):
            self._fog = pygame.Surface((fw, fh), pygame.SRCALPHA)
        mask = self._fog
        mask.fill(FOG_UNKNOWN)
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                mask.set_at((tx - tx0, ty - ty0), f.fog.get((tx, ty), FOG_UNKNOWN))
        big = pygame.transform.smoothscale(mask, (max(1, TILE * (fw - 1) + 1), max(1, TILE * (fh - 1) + 1)))
        c.blit(big, (tx0 * TILE + TILE // 2 - f.ox, ty0 * TILE + TILE // 2 - f.oy))

    # --- screen-space overlays ---------------------------------------------------
    def to_screen(self, f: Frame, view: pygame.Rect, gx: float, gy: float, z: float = 0.0) -> tuple[int, int]:
        vx, vy = f.proj.to_view(gx, gy, z)
        return int(view.x + (vx - f.cam_x) * f.zoom), int(view.y + (vy - f.cam_y) * f.zoom)

    def _overlays(self, f: Frame, screen: pygame.Surface, view: pygame.Rect) -> None:
        now = f.now
        for t in self.effects.texts:
            k = (now - t.start) / max(0.01, t.until - t.start)
            sx, sy = self.to_screen(f, view, t.x, t.y, t.z + t.rise * k)
            surf = txt.render(t.text, "pixel", t.size, t.color, shadow=(10, 8, 16))
            if k > 0.7:
                surf = surf.copy()
                surf.set_alpha(int(255 * (1 - k) / 0.3))
            screen.blit(surf, (sx - surf.get_width() // 2, sy - surf.get_height()))
        for who, b in self.effects.bubbles.items():
            anchor = f.anchors.get(who)
            if anchor is None:
                continue
            sx, sy = self.to_screen(f, view, *anchor)
            draw_bubble(screen, view, sx, sy - 4, b.text, b.kind, now - b.start)


BUBBLE_BG = {"speech": (244, 240, 250), "thought": (214, 236, 246), "thinking": (214, 236, 246)}
BUBBLE_FG = {"speech": (26, 20, 40), "thought": (20, 40, 60), "thinking": (20, 40, 60)}


def draw_bubble(screen: pygame.Surface, view: pygame.Rect, x: int, y: int, text: str, kind: str,
                age: float) -> None:
    """A pixel-style bubble whose tail points down at (x, y)."""
    if kind == "thinking":
        text = "." * (1 + int(age * 2.5) % 3)
    size = 15
    lines = txt.wrap(txt.clean(text), "text", size, 230)[:4]
    if len(lines) == 4:
        lines[3] = lines[3][:max(0, len(lines[3]) - 1)] + "…"
    surfs = [txt.render(line, "text", size, BUBBLE_FG[kind]) for line in lines if line]
    if not surfs:
        return
    w = max(s.get_width() for s in surfs) + 14
    lh = txt.line_height("text", size)
    h = lh * len(surfs) + 8
    pop = min(1.0, age * 8)
    bx = max(view.left + 4, min(view.right - w - 4, x - w // 2))
    by = max(view.top + 4, y - h - 10 - int((1 - pop) * 6))
    bg, fg = BUBBLE_BG[kind], (22, 18, 34)
    rect = pygame.Rect(bx, by, w, h)
    pygame.draw.rect(screen, fg, rect.inflate(4, 4), border_radius=6)
    pygame.draw.rect(screen, bg, rect, border_radius=5)
    if kind == "speech":
        tail = [(x - 5, by + h), (x + 5, by + h), (x, by + h + 8)]
        pygame.draw.polygon(screen, fg, [(tx, ty + 2) for tx, ty in tail])
        pygame.draw.polygon(screen, bg, tail)
    else:  # thought: trailing dots
        for dx, dy, r in ((0, 6, 4), (-3, 14, 3)):
            pygame.draw.circle(screen, fg, (x + dx, by + h + dy), r + 2)
            pygame.draw.circle(screen, bg, (x + dx, by + h + dy), r)
    for i, s in enumerate(surfs):
        screen.blit(s, (bx + 7, by + 4 + i * lh))
