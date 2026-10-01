"""The Azeroth client: ``wilds --chapter azeroth --gfx`` (Mulgore), in 2.5D.

A zone is millions of tiles, so the camera looks at a window of the lazily generated world and
only what is near it is drawn. The scene is the same 2.5D machinery as the cyberpunk chapter
(``render.Renderer``): ground textures mapped onto isometric diamonds, the mountain wall, cliffs,
red mesas and Thunder Bluff's wooden platforms as extruded blocks, sprites standing on world
points at their elevation, day/night light with fires, and the 3/4 top-down view as an
alternative.

The camera is free: arrows/WASD or dragging move it, digits jump between places, the minimap is
clickable, ``f`` follows the hero. Keys: space pause · +/- speed · [ ] or wheel zoom · i 2.5D <-> 3/4
view · d diary · m minimap · n names · Tab panel · F12 screenshot · h help · q quit.
"""

from __future__ import annotations

import math
import os
import queue
import random
import sys
import threading
import time
import traceback
from collections import deque
from pathlib import Path

import pygame

from ..azeroth import content, quests, relief, settlements
from ..azeroth.scale import CHUNK, TICK_SECONDS
from ..azeroth.terrain import Terrain
from . import hud
from . import text as txt
from .bank import SpriteBank, _to_diamond
from .lighting import TAU7_SKY, sky
from .render import PROJECTIONS, TILE, Frame, Renderer
from .sprites import load_all, load_azeroth

TPS = [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048]
ZOOMS = (1, 2, 3, 4, 5, 6)
PANEL_W = 400
FPS = 60
SCREENSHOT_DIR = Path("screenshots")
HELP = [
    ("Керування", "pixel"),
    ("стрілки / WASD - рух камери (Shift - швидше)        ліва кнопка миші - тягнути карту", "text"),
    ("1-9 - стрибок до місць        клік по мінікарті - стрибок        f - слідувати за героєм", "text"),
    ("[ ] або коліщатко - масштаб        i - 2.5D ↔ 3/4 зверху        Tab - сховати панель", "text"),
    ("пробіл - пауза світу        + / - - швидкість        m - мінікарта        n - імена", "text"),
    ("F12 - скріншот        h / F1 - ця довідка        q - вихід", "text"),
    ("", "text"),
    ("Мулгор у справжньому масштабі: 5450 x 3633 ярдів, тайл = 2 ярди.", "text"),
]
PLACES = ("Camp Narache", "Bloodhoof Village", "Thunderhorn Water Well", "High Rise", "Venture Co. Mine",
          "Bael'dun Digsite", "Camp Sungraze", "Palemane Rock", "Great Gate")

GROUND = {Terrain.GRASS: "az.ground.grass", Terrain.TALL_GRASS: "az.ground.tall_grass",
          Terrain.DRY_GRASS: "az.ground.dry_grass", Terrain.DIRT: "az.ground.dirt", Terrain.ROAD: "az.ground.road",
          Terrain.MESA: "az.ground.mesa", Terrain.WATER: "az.ground.water", Terrain.SHALLOWS: "az.ground.shallows",
          Terrain.BOULDER: "az.ground.grass", Terrain.MOUNTAIN: "az.mountain.top", Terrain.CLIFF: "az.mountain.top"}
# a higher-ranked neighbour bleeds into a lower-ranked tile along their shared edge
RANK = {Terrain.DIRT: 1, Terrain.ROAD: 2, Terrain.MESA: 3, Terrain.DRY_GRASS: 4, Terrain.GRASS: 5,
        Terrain.TALL_GRASS: 6, Terrain.BOULDER: 5}
WATERS = (Terrain.WATER, Terrain.SHALLOWS)
GRASSES = (Terrain.GRASS, Terrain.TALL_GRASS, Terrain.DRY_GRASS, Terrain.BOULDER)
SIDES = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}
CORNERS = {"ne": (1, -1), "nw": (-1, -1), "se": (1, 1), "sw": (-1, 1)}
FIRES = {"az.obj.bonfire": ((255, 170, 90), 60), "az.tb.brazier": ((255, 180, 100), 52),
         "az.obj.torch": ((255, 190, 110), 40), "az.obj.forge": ((255, 140, 70), 56),
         "az.obj.cooking_pot": ((255, 170, 100), 26)}
OUTFITS = (("guard", "guard"), ("warrior", "warrior"), ("hunter", "hunter"), ("shaman", "shaman"),
           ("druid", "druid"), ("priest", "priest"), ("trainer", "trainer"), ("elder", "elder"),
           ("innkeeper", "merchant"), ("vendor", "merchant"), ("goods", "merchant"), ("supplies", "merchant"),
           ("armor", "merchant"), ("weapon", "merchant"), ("baker", "merchant"), ("bowyer", "merchant"),
           ("merchant", "merchant"), ("banker", "merchant"), ("stable", "merchant"), ("fisher", "merchant"))
BODIES = {"goblin": "goblin", "forsaken": "forsaken", "dwarf": "dwarf", "orc": "orc", "pandaren": "pandaren",
          "jungle troll": "troll", "troll": "troll", "earthen": "earthen", "blood elf": "blood_elf", "human": "human"}


def tile_hash(x: int, y: int, seed: int = 0) -> int:
    h = (x * 73856093) ^ (y * 19349663) ^ (seed * 83492791)
    h ^= h >> 13
    h = (h * 0x5bd1e995) & 0xFFFFFFFF
    return h ^ (h >> 15)


class Painter:
    """Ground tiles with soft edges (16x16 composites, cached), ready to be mapped onto diamonds."""

    def __init__(self, bank: SpriteBank) -> None:
        self.bank = bank
        self._composite: dict[tuple, pygame.Surface] = {}
        self._diamond: dict[tuple, pygame.Surface] = {}
        self._masks: dict[tuple, pygame.Surface] = {}
        self._slopes: dict[tuple, tuple] = {}

    def variant(self, base: str, x: int, y: int) -> str:
        try:
            vs = self.bank.registry.variants(base)
        except KeyError:
            return base
        return vs[tile_hash(x, y) % len(vs)]

    def _mask(self, side: str, var: int) -> pygame.Surface:
        key = (side, var)
        m = self._masks.get(key)
        if m is None:
            rng = random.Random(1000 + var * 7 + "nsew".index(side))
            m = pygame.Surface((TILE, TILE), pygame.SRCALPHA)
            depths = [max(2, min(10, int(6 + rng.gauss(0, 2.2)))) for _ in range(TILE)]
            for i in range(TILE):
                d = depths[i]
                for k in range(d + 1):
                    a = 255 if k < d - 1 else 130
                    pos = {"n": (i, k), "s": (i, TILE - 1 - k), "w": (k, i), "e": (TILE - 1 - k, i)}[side]
                    m.set_at(pos, (255, 255, 255, a))
            self._masks[key] = m
        return m

    def composite(self, grid, gx: int, gy: int, x: int, y: int, t: float) -> tuple[pygame.Surface, tuple]:
        """The finished 16x16 ground of tile (x, y); ``grid[gy][gx]`` is its terrain."""
        terr = grid[gy][gx]
        if terr in WATERS:
            return self._water(grid, gx, gy, x, y, t)
        name = self.variant(GROUND[terr if terr is not Terrain.BOULDER else Terrain.GRASS], x, y)
        blends, overlays = [], []
        rank = RANK.get(terr)
        for side, (dx, dy) in SIDES.items():
            nb = grid[gy + dy][gx + dx]
            if rank is not None and nb in RANK and RANK[nb] > rank:
                blends.append((side, self.variant(GROUND[nb if nb is not Terrain.BOULDER else Terrain.GRASS],
                                                  x + dx, y + dy), tile_hash(x, y, 3) % 4))
            if terr in (Terrain.DIRT, Terrain.ROAD) and nb in GRASSES:
                overlays.append(f"az.edge.dirt.{side}")
        if terr in (Terrain.DIRT, Terrain.ROAD):
            for corner, (dx, dy) in CORNERS.items():
                sides = [f"az.edge.dirt.{s}" for s, (sx, sy) in SIDES.items() if (sx == dx and sy == 0) or (sy == dy and sx == 0)]
                if grid[gy + dy][gx + dx] in GRASSES and not any(o in overlays for o in sides):
                    overlays.append(f"az.edge.dirt.corner.{corner}")
        key = (name, tuple(blends), tuple(overlays))
        surf = self._composite.get(key)
        if surf is None:
            surf = self.bank.base(name)[0].copy()
            for side, nb_name, var in blends:
                layer = self.bank.base(nb_name)[0].copy()
                layer.blit(self._mask(side, var), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                surf.blit(layer, (0, 0))
            for ov in overlays:
                if ov in self.bank:
                    surf.blit(self.bank.base(ov)[0], (0, 0))
            self._composite[key] = surf
        return surf, key

    def _water(self, grid, gx, gy, x, y, t) -> tuple[pygame.Surface, tuple]:
        terr = grid[gy][gx]
        name = self.variant(GROUND[terr], x, y)
        a = self.bank.art(name)
        idx = a.frame_index(t) % len(a.frames)
        land = {s: grid[gy + dy][gx + dx] not in WATERS and grid[gy + dy][gx + dx] is not Terrain.VOID
                for s, (dx, dy) in SIDES.items()}
        overlays = [f"az.edge.water.{s}" for s, is_land in land.items() if is_land]
        for corner, (dx, dy) in CORNERS.items():
            sides = [s for s, (sx, sy) in SIDES.items() if (sx == dx and sy == 0) or (sy == dy and sx == 0)]
            nb = grid[gy + dy][gx + dx]
            if nb not in WATERS and nb is not Terrain.VOID and not any(land[s] for s in sides):
                overlays.append(f"az.edge.water.corner.{corner}")
        key = ("water", name, idx, tuple(overlays))
        surf = self._composite.get(key)
        if surf is None:
            surf = self.bank.base(name)[idx].copy()
            for ov in overlays:
                if ov in self.bank:
                    o = self.bank.art(ov)
                    surf.blit(self.bank.base(ov)[o.frame_index(t) % len(o.frames)], (0, 0))
            self._composite[key] = surf
        return surf, key

    def slope(self, surf: pygame.Surface, key: tuple, corners: tuple[int, int, int, int]) -> tuple[pygame.Surface, int]:
        """A ground tile draped over its four corner heights: the diamond is lifted column by column
        and shaded by the slope (light from the top-left), so the land rolls without any seams.
        Returns the surface and the height of its top edge above the tile's flat diamond."""
        top = max(corners)
        low = min(corners)
        k = (key, tuple(c - low for c in corners))
        hit = self._slopes.get(k)
        if hit is None:
            flat = self.diamond(surf, key)
            hn, he, hs, hw = (c - low for c in corners)
            span = top - low
            out = pygame.Surface((32, 16 + span), pygame.SRCALPHA)
            du = ((he + hs) - (hn + hw)) / 2  # rise towards the east corner, px per tile
            dv = ((hw + hs) - (hn + he)) / 2
            shade = int(max(-46, min(46, 15 * (0.85 * du + 0.15 * dv))))
            for sx in range(32):
                prev_y, prev_c = None, None
                for sy in range(16):
                    c = flat.get_at((sx, sy))
                    if c.a == 0:
                        continue
                    # inverse of the diamond mapping: texel coordinates (0..1) of this pixel
                    a, b = (sx + 0.5 - 16) / 16, (sy + 0.5) / 8
                    pu, pv = (a + b) / 2, (b - a) / 2
                    pu, pv = min(1.0, max(0.0, pu)), min(1.0, max(0.0, pv))
                    h = (1 - pu) * (1 - pv) * hn + pu * (1 - pv) * he + pu * pv * hs + (1 - pu) * pv * hw
                    y = sy + span - int(round(h))
                    col = (max(0, min(255, c.r + shade)), max(0, min(255, c.g + shade)), max(0, min(255, c.b + shade)), c.a)
                    if prev_y is not None and y > prev_y + 1:
                        for fy in range(prev_y + 1, y):  # a steep slope: stretch the pixel above
                            out.set_at((sx, fy), prev_c)
                    out.set_at((sx, y), col)
                    prev_y, prev_c = y, col
            hit = self._slopes[k] = out
        return hit, top

    def diamond(self, surf: pygame.Surface, key: tuple) -> pygame.Surface:
        d = self._diamond.get(key)
        if d is None:
            d = self._diamond[key] = _to_diamond(surf)
        return d


def outfit_of(rec: dict | None, title: str) -> str:
    text = ((rec["info"].get("profession", "") + " " + rec["info"].get("title", "")) if rec else "") + " " + title
    text = text.lower()
    return next((v for k, v in OUTFITS if k in text), "civilian")


def person_sprite(bank: SpriteBank, rec: dict | None, title: str, anim: str) -> str | None:
    race = quests.clean(rec["info"].get("race", "")) if rec else "tauren"
    if race in ("", "tauren", "highmountain tauren", "varies"):
        female = bool(rec) and rec["info"].get("gender", "").lower() == "female"
        body = "tauren_f" if female else "tauren_m"
        name = f"az.person.{body}.{outfit_of(rec, title)}.{anim}"
        return name if name in bank else f"az.person.{body}.civilian.{anim}"
    if race in BODIES:
        name = f"az.person.{BODIES[race]}.civilian.{anim}"
        return name if name in bank else None
    slug = "_".join(race.replace("'", "").split())
    name = f"az.creature.{slug}.{'idle' if anim in ('idle', 'talk') else 'move'}"
    return name if name in bank else None


def creature_sprite(bank: SpriteBank, species: str, anim: str) -> str:
    slug = "_".join(species.replace("'", "").split())
    if slug == "tauren":
        return f"az.person.tauren_m.palemane.{'walk' if anim == 'move' else 'idle' if anim in ('idle', 'dead') else anim}"
    if slug in BODIES or slug.replace("_", " ") in BODIES:
        body = BODIES.get(slug, BODIES.get(slug.replace("_", " "), "goblin"))
        return f"az.person.{body}.civilian.{'walk' if anim == 'move' else 'idle'}"
    name = f"az.creature.{slug}.{anim}"
    if name in bank:
        return name
    fallback = f"az.creature.{slug}.idle"
    return fallback if fallback in bank else f"az.creature.wolf.{anim if anim != 'attack' else 'move'}"


class AzApp:
    title = "Wilds: Мулгор"

    def __init__(self, sim, brain, seed: int, speed: int = 1, sprites_dir: Path | str | None = None,
                 size: tuple[int, int] = (1360, 820), zoom: int = 2, headless: bool = False,
                 fullscreen: bool = False, diary_dir: Path | None = None, view: str = "iso",
                 follow: bool = False) -> None:
        if headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        pygame.display.init()
        pygame.font.init()
        flags = 0 if headless else pygame.RESIZABLE | (pygame.FULLSCREEN if fullscreen else 0)
        self.screen = pygame.display.set_mode(size, flags)
        pygame.display.set_caption(self.title)
        pygame.key.set_repeat(300, 60)
        load_all()
        load_azeroth()
        self.bank = SpriteBank(overrides=sprites_dir)
        self.renderer = Renderer(self.bank)
        self.painter = Painter(self.bank)
        self.sim = sim
        self.world = sim.world
        self.relief = relief.Relief(self.world)
        self.brain = brain
        self.seed = seed
        self.headless = headless
        self.view = view if view in PROJECTIONS else "iso"
        self.speed_idx = max(0, min(len(TPS) - 1, speed + 1))
        self.zoom = zoom if zoom in ZOOMS else 2
        self.paused = False
        self.follow = follow
        self.show_minimap = True
        self.show_panel = True
        self.show_names = True
        self.overlay: str | None = None
        self.scroll = 0
        self.max_scroll = 0
        self.thinking_since: float | None = None
        self.results: queue.Queue = queue.Queue()
        self.events: deque = deque(maxlen=300)
        self.toasts: list[tuple[str, float]] = []
        self.acc = 0.0
        self.cam = [float(sim.hero.pos[0]), float(sim.hero.pos[1])]   # tile coordinates of the view centre
        self.t0 = time.monotonic()
        self.now = 0.0
        self.running = True
        self.drag: tuple[int, int] | None = None
        self.vis: dict[object, list[float]] = {}
        self.moved_at: dict[object, float] = {}
        self.facing: dict[object, bool] = {}
        self.plates: list[tuple[float, float, float, str, tuple]] = []
        self.minimap_rect = pygame.Rect(0, 0, 0, 0)
        self.records = {quests.clean(r["title"]): r for k in ("npc", "mob") for r in content.load(sim.world.pack, k)}
        self.structures = settlements.build_structures(self.world)
        self.by_chunk: dict[tuple[int, int], list[tuple[str, object]]] = {}
        for s in self.structures:
            self.by_chunk.setdefault((s.pos[0] // CHUNK, s.pos[1] // CHUNK), []).append(("structure", s))
        for p in self.world.placements:
            if p.kind == "npc":
                self.by_chunk.setdefault((p.pos[0] // CHUNK, p.pos[1] // CHUNK), []).append(("npc", p))
        self.minimap = self._minimap_surface()
        if diary_dir:
            diary_dir.mkdir(parents=True, exist_ok=True)
            sim.diary_path = diary_dir / f"diary-azeroth-{brain.name}-{seed}.md"
        self.world.listeners.append(self._on_event)
        for ev in self.world.events[-60:]:
            self.events.append(ev)

    # --- setup --------------------------------------------------------------------------------------
    def _minimap_surface(self) -> pygame.Surface:
        macro = self.world.terrain.macro
        colors = {"g": (98, 160, 72), "d": (186, 176, 92), "r": (150, 122, 112), "m": (92, 66, 44), "v": (18, 18, 26)}
        small = pygame.Surface((macro.width, macro.height))
        lake = self.world.terrain._lake
        for y, row in enumerate(macro.rows):
            for x, c in enumerate(row):
                small.set_at((x, y), (54, 96, 168) if (x, y) in lake else colors[c])
        return pygame.transform.smoothscale(small, (268, round(268 * macro.height / macro.width)))

    def _on_event(self, ev) -> None:
        self.events.append(ev)

    def toast(self, text: str) -> None:
        self.toasts.append((text, self.now + 3.0))

    def goto(self, name: str) -> None:
        spot = self.sim.find_place(name)
        if spot is None:
            return
        pos = self.world.nearest_passable(spot[0], 40) or spot[0]
        self.cam = [float(pos[0]), float(pos[1])]
        self.follow = False
        self.toast(name)

    # --- brain --------------------------------------------------------------------------------------
    def _think(self, kind: str) -> None:
        self.thinking_since = time.monotonic()
        sim, brain = self.sim, self.brain

        def work() -> None:
            try:
                result = getattr(brain, kind)(sim)
            except Exception:  # a brain must never take the window down
                traceback.print_exc(file=sys.stderr)
                from ..azeroth.brain import ScriptedZoneBrain

                result = getattr(ScriptedZoneBrain(), kind)(sim)
            self.results.put((kind, result))

        if self.headless or getattr(brain, "name", "") == "scripted":
            work()
        else:
            threading.Thread(target=work, daemon=True, name=f"brain-{kind}").start()

    def _drain(self) -> None:
        while True:
            try:
                kind, result = self.results.get_nowait()
            except queue.Empty:
                return
            self.thinking_since = None
            if kind == "decide":
                self.sim.apply(result)
            elif kind == "reflect":
                self.sim.apply_reflection(result)

    # --- loop ---------------------------------------------------------------------------------------
    @property
    def tps(self) -> int:
        return TPS[self.speed_idx]

    def update(self, dt: float) -> None:
        self.now = time.monotonic() - self.t0
        self._drain()
        sim = self.sim
        if not sim.over and not self.paused and self.thinking_since is None:
            if sim.pending:
                self._think(sim.pending)
                self._drain()
            else:
                self.acc += dt * self.tps
                n = min(int(self.acc), 6000)
                self.acc -= n
                for _ in range(n):
                    sim.tick()
                    if sim.pending or sim.over:
                        self.acc = 0.0
                        break
        self._effects()
        self._animate(dt)
        self._move_camera(dt)

    def _effects(self) -> None:
        """The simulation's hit/hurt/level-up notes become sparks and floating numbers."""
        fx = self.renderer.effects
        for kind, pos, text in self.sim.fx:
            gx, gy = pos[0] * TILE + TILE // 2, pos[1] * TILE + TILE - 1
            z = self.relief.height(pos[0], pos[1], "ground")
            if kind == "hit":
                fx.text(text, (255, 240, 140), gx, gy, self.now, z=22 + z)
                fx.spawn(self.bank, "az.fx.hit_spark", gx, gy, self.now, duration=0.4, z=12 + z)
            elif kind == "hurt":
                fx.text("-" + text, (255, 90, 90), gx, gy, self.now, z=22 + z)
                fx.spawn(self.bank, "az.fx.hit_spark", gx, gy, self.now, duration=0.4, z=12 + z)
            elif kind == "levelup":
                fx.text("РІВЕНЬ " + text, (120, 255, 150), gx, gy, self.now, duration=2.0, z=34 + z, size=20)
                fx.spawn(self.bank, "az.fx.level_up", gx, gy, self.now, duration=1.4, anchored=True, z=z)
        self.sim.fx.clear()
        fx.prune(self.now)

    def _animate(self, dt: float) -> None:
        """Ease drawn positions towards the simulated ones."""
        k = min(1.0, dt * max(3.0, self.tps * 1.2))
        targets = {"hero": self.sim.hero.pos}
        for c in self.sim.near_creatures(2):
            targets[c.id] = c.pos
        for key, pos in targets.items():
            v = self.vis.get(key)
            if v is None:
                self.vis[key] = [float(pos[0]), float(pos[1])]
                continue
            dx, dy = pos[0] - v[0], pos[1] - v[1]
            if abs(dx) + abs(dy) > 6:
                v[0], v[1] = float(pos[0]), float(pos[1])
                continue
            if abs(dx) > 0.05 or abs(dy) > 0.05:
                self.moved_at[key] = self.now
                if abs(dx - dy) > 0.2:
                    self.facing[key] = (dx - dy) < 0  # facing the left of the screen
            v[0] += dx * k
            v[1] += dy * k
        for key in [k2 for k2 in self.vis if k2 not in targets]:
            del self.vis[key]

    def _screen_to_tiles(self, dx: float, dy: float) -> tuple[float, float]:
        """A screen movement (px) as a movement over the ground, in tiles."""
        dx, dy = dx / self.zoom, dy / self.zoom
        if self.view == "iso":
            return (dx / 16 + dy / 8) / 2, (dy / 8 - dx / 16) / 2
        return dx / TILE, dy / TILE

    def _move_camera(self, dt: float) -> None:
        w, h = self.world.geo.width, self.world.geo.height
        if self.follow:
            v = self.vis.get("hero") or self.sim.hero.pos
            k = 1 - math.exp(-dt * 8)
            self.cam[0] += (v[0] - self.cam[0]) * k
            self.cam[1] += (v[1] - self.cam[1]) * k
        elif not self.headless:
            keys = pygame.key.get_pressed()
            sx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
            sy = (keys[pygame.K_DOWN] or keys[pygame.K_s]) - (keys[pygame.K_UP] or keys[pygame.K_w])
            if sx or sy:
                speed = 26 * (4 if keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT] else 1) * dt
                tx, ty = self._screen_to_tiles(sx * 16, sy * 8 if self.view == "iso" else sy * 16)
                n = math.hypot(tx, ty) or 1
                self.cam[0] += tx / n * speed
                self.cam[1] += ty / n * speed
        self.cam[0] = max(0.0, min(w - 1.0, self.cam[0]))
        self.cam[1] = max(0.0, min(h - 1.0, self.cam[1]))

    def map_rect(self) -> pygame.Rect:
        w, h = self.screen.get_size()
        return pygame.Rect(0, 0, w - (PANEL_W if self.show_panel else 0), h)

    # --- drawing -----------------------------------------------------------------------------------
    def draw(self) -> None:
        screen = self.screen
        screen.fill((8, 7, 14))
        view = self.map_rect()
        self.draw_world(screen, view)
        if self.show_minimap:
            self.draw_minimap(screen, view)
        if self.show_panel:
            rect = pygame.Rect(view.right, 0, PANEL_W, screen.get_height())
            y = self.draw_status(screen, rect)
            log = pygame.Rect(rect.x + 2, y + 4, rect.width - 4, rect.bottom - y - 6)
            if log.height > 60:
                screen.blit(txt.render("ЖУРНАЛ", "pixel", 16, hud.TITLE, shadow=(0, 0, 0)), (log.x + 8, log.y))
                pygame.draw.line(screen, hud.EDGE, (log.x + 8, log.y + 20), (log.right - 8, log.y + 20))
                self._draw_log(screen, pygame.Rect(log.x, log.y + 24, log.width, log.height - 26))
        if self.overlay == "diary":
            blocks = [(f"День {d}: {text}", hud.TEXT, "text") for d, text in self.sim.hero.diary] \
                or [("Щоденник ще порожній.", hud.DIM, "text")]
            self.max_scroll = hud.text_overlay(screen, "Щоденник", blocks, self.scroll, "Esc / d - закрити · ↑↓ гортати")
        elif self.overlay == "help":
            hud.text_overlay(screen, "Wilds - довідка", [(t, hud.TEXT, f) for t, f in HELP], 0, "Esc - закрити")
        self.toasts = [(m, until) for m, until in self.toasts if until > self.now]
        for i, (msg, _) in enumerate(self.toasts[-3:]):
            surf = txt.render(msg, "text", 16, hud.TEXT)
            r = pygame.Rect(view.centerx - surf.get_width() // 2 - 12, view.bottom - 90 - i * 40, surf.get_width() + 24, 32)
            hud.frame_rect(screen, r)
            screen.blit(surf, (r.x + 12, r.y + 7))

    def _hour(self) -> float:
        return self.world.hour + self.world.minute / 60

    def draw_world(self, screen: pygame.Surface, view: pygame.Rect) -> None:
        proj = PROJECTIONS[self.view]
        gx, gy = self.cam[0] * TILE + TILE // 2, self.cam[1] * TILE + TILE - 1
        cx, cy = proj.to_view(gx, gy)
        cw, ch = self.renderer.canvas_size(view, self.zoom)
        f = self.renderer.frame(cx - (cw - 1) / 2, cy - (ch - 1) / 2, view, self.zoom, self.now, proj)
        f.ambient = sky(TAU7_SKY, self._hour())
        self.build(f)
        self.renderer.draw(f, screen, view)
        if self.show_names and self.zoom >= 2:
            self._draw_plates(screen, view, f)

    def build(self, f: Frame) -> None:
        w, h = self.world.geo.width, self.world.geo.height
        tx0, ty0, tx1, ty1 = f.tile_range(rise=80)
        tx0, ty0, tx1, ty1 = max(0, tx0), max(0, ty0), min(w - 1, tx1), min(h - 1, ty1)
        if tx1 < tx0 or ty1 < ty0:
            return
        world, rel = self.world, self.relief
        cols, rows = tx1 - tx0 + 1, ty1 - ty0 + 1
        grid = [[world.tile(x, y) for x in range(tx0 - 1, tx1 + 2)] for y in range(ty0 - 1, ty1 + 2)]
        kinds = [[rel.kind(tx0 - 1 + gx, ty0 - 1 + gy, grid[gy][gx]) for gx in range(cols + 2)] for gy in range(rows + 2)]
        heights = [[rel.height(tx0 - 1 + gx, ty0 - 1 + gy, kinds[gy][gx]) for gx in range(cols + 2)] for gy in range(rows + 2)]
        self.plates = []
        seed = world.seed
        now = self.now
        iso = f.proj.iso
        for gy in range(1, rows + 1):
            for gx in range(1, cols + 1):
                x, y = tx0 - 1 + gx, ty0 - 1 + gy
                terr, kind, hgt = grid[gy][gx], kinds[gy][gx], heights[gy][gx]
                if kind == "void":
                    continue
                if kind in ("ground", "water") or hgt == 0:
                    surf, key = self.painter.composite(grid, gx, gy, x, y, now)
                    pos = f.proj.tile_origin(x, y)
                    if not iso:
                        f.ground.append((surf, (pos[0] - f.ox, pos[1] - f.oy)))
                    elif kind == "ground" and hgt:
                        tile, top = self.painter.slope(surf, key, rel.corners(x, y))
                        f.ground.append((tile, (pos[0] - f.ox, pos[1] - f.oy - top)))
                    else:
                        f.ground.append((self.painter.diamond(surf, key), (pos[0] - f.ox, pos[1] - f.oy)))
                else:
                    open_sides = "".join(s for s, (dx, dy) in SIDES.items() if heights[gy + dy][gx + dx] < hgt)
                    top, face = self._block_art(kind, x, y)
                    f.block(top, face, x, y, now, open_sides, hgt)
                gxw, gyw = x * TILE + TILE // 2, y * TILE + TILE - 1
                if kind in ("ground", "water"):
                    self._scatter(f, terr, x, y, gxw, gyw, seed, now, hgt)
                elif kind in ("mesa", "platform"):
                    if kind == "platform":
                        self._scatter_top(f, x, y, gxw, gyw, hgt, seed, now)
                    if kind == "mesa" and terr is Terrain.MESA:
                        self._scatter_mesa(f, x, y, gxw, gyw, hgt, seed, now)
                if terr is Terrain.BOULDER and hgt == 0:
                    f.sprite(self.painter.variant("az.boulder", x, y), gxw, gyw)
        self._collect(f, tx0, ty0, tx1, ty1)

    def _block_art(self, kind: str, x: int, y: int) -> tuple[str, str]:
        v = self.painter.variant
        if kind == "mountain":
            return v("az.mountain.top", x, y), v("az.mountain.face", x, y)
        if kind == "cliff":
            return v("az.mountain.top", x, y), v("az.cliff.face", x, y)
        if kind == "mesa":
            face = v("az.mesa.face", x, y)
            return v("az.ground.mesa", x, y), face if face in self.bank else v("az.cliff.face", x, y)
        if kind == "platform":
            face = v("az.tb.cliff.face", x, y)
            return self._plateau_top(x, y), face if face in self.bank else v("az.tb.platform.edge", x, y)
        return v("az.tb.bridge", x, y), v("az.tb.platform.edge", x, y)

    def _plateau_cell(self, x: int, y: int) -> str:
        """What lies on a Thunder Bluff rise at (x, y): cobble | road | grass | dry."""
        plat = settlements.on_platform(self.world, (x, y), self.relief.platforms)
        if plat is None:
            return "grass"
        dx, dy = x - plat.center[0], (y - plat.center[1]) / 0.75
        d = math.hypot(dx, dy) + 2.2 * (self.relief.noise.fractal(x / 7 + 3, y / 7 + 3, 2) - 0.5)
        plaza = settlements.PLAZA_RADIUS
        if d <= plaza:
            return "cobble"
        ring = plat.radius * 0.55
        spoke = abs(math.sin(math.atan2(dy, dx) * 3 + 0.6)) * d / 3.0  # three roads out from the plaza
        if abs(d - ring) < 1.5 or d < plaza + 1.5 or (d < ring + 4 and spoke < 0.75):
            return "road"
        return "dry" if tile_hash(x // 6, y // 6) % 5 == 0 else "grass"

    def _plateau_top(self, x: int, y: int) -> str:
        cell = self._plateau_cell(x, y)
        if cell == "cobble" and "az.tb.cobble" in self.bank.registry._variants:
            return self.painter.variant("az.tb.cobble", x, y)
        return self.painter.variant({"cobble": GROUND[Terrain.ROAD], "road": GROUND[Terrain.ROAD],
                                     "dry": GROUND[Terrain.DRY_GRASS]}.get(cell, GROUND[Terrain.GRASS]), x, y)

    def _scatter_top(self, f: Frame, x: int, y: int, gx: float, gy: float, z: float, seed: int, now: float) -> None:
        """Pines, tufts and flowers on a rise's grass (never on roads or the plaza)."""
        if self._plateau_cell(x, y) not in ("grass", "dry"):
            return
        h = tile_hash(x, y, seed)
        v = self.painter.variant
        if h % 17 == 0 and "az.tb.pine" in self.bank.registry._variants:
            f.sprite(v("az.tb.pine", x, y), gx, gy, z=z, shadow=18)
        elif h % 29 == 0:
            f.sprite(v("az.plant.bush", x, y), gx, gy, z=z, shadow=8)
        elif h % 9 == 0:
            f.sprite(v("az.plant.grass_clump", x, y), gx, gy, now + (h % 11) * 0.27, z=z, solid=False)
        elif h % 13 == 0:
            f.sprite(v("az.plant.wildflowers", x, y), gx, gy, now + (h % 7) * 0.3, z=z, solid=False)

    def _scatter(self, f: Frame, terr: Terrain, x: int, y: int, gx: float, gy: float, seed: int, now: float, z: float = 0) -> None:
        """Plants, flowers and stones on open ground, deterministic per tile."""
        h = tile_hash(x, y, seed)
        bank = self.bank
        if terr in WATERS:
            if terr is Terrain.SHALLOWS and h % 5 == 0 and "az.plant.reeds" in bank.registry._variants:
                f.sprite(self.painter.variant("az.plant.reeds", x, y), gx, gy, now + (h % 9) * 0.3, z=z)
            return
        if terr not in GRASSES:
            if terr is Terrain.DIRT and h % 37 == 0:
                f.sprite(self.painter.variant("az.deco.stones", x, y), gx, gy, solid=False, z=z)
            return
        # Mulgore: open lime-gold pasture; tall pines stand alone or in tight clumps far apart
        n = self.relief.noise.fractal(x / 40 + 31, y / 40 + 5, 2)
        if (n > 0.74 and h % 7 == 0 or h % 600 == 0) and "az.tb.pine" in bank.registry._variants:
            f.sprite(self.painter.variant("az.tb.pine", x, y), gx, gy, shadow=20, z=z)
        elif h % 15 == 0 and "az.plant.grass_clump" in bank.registry._variants:  # golden tufts: the ground texture
            f.sprite(self.painter.variant("az.plant.grass_clump", x, y), gx, gy, now + (h % 11) * 0.27, solid=False, z=z)
        elif h % 330 == 0 and "az.plant.wildflowers" in bank.registry._variants:
            f.sprite(self.painter.variant("az.plant.wildflowers", x, y), gx, gy, now + (h % 7) * 0.3, solid=False, z=z)
        elif h % 420 == 0 and "az.plant.bush" in bank.registry._variants:
            f.sprite(self.painter.variant("az.plant.bush", x, y), gx, gy, shadow=10, z=z)
        elif h % 811 == 0:
            node = ("az.node.peacebloom", "az.node.silverleaf", "az.node.earthroot", "az.node.copper_vein",
                    "az.node.prairie_flower", "az.node.shiny_stone")[(h >> 8) % 6]
            f.sprite(node, gx, gy, now + (h % 7), z=z)
        elif h % 260 == 0:
            f.sprite(self._variant_name(("az.deco.stones", "az.deco.tuft", "az.deco.bones")[(h >> 5) % 3], x, y),
                     gx, gy, solid=False, z=z)

    def _scatter_mesa(self, f: Frame, x: int, y: int, gx: float, gy: float, z: float, seed: int, now: float) -> None:
        """Dry scrub, spires and stones on a mesa top."""
        h = tile_hash(x, y, seed)
        v = self.painter.variant
        if h % 47 == 0:
            f.sprite(v("az.rock.spire", x, y), gx, gy, z=z, shadow=14)
        elif h % 31 == 0:
            f.sprite(v("az.rock.boulder_big", x, y), gx, gy, z=z, shadow=12)
        elif h % 23 == 0:
            f.sprite(v("az.rock.slab", x, y), gx, gy, z=z)
        elif h % 37 == 0:
            f.sprite(v("az.plant.dead_tree", x, y), gx, gy, z=z, shadow=10)
        elif h % 11 == 0:
            f.sprite(v("az.plant.thornbush", x, y), gx, gy, z=z, shadow=8)
        elif h % 7 == 0:
            f.sprite(v("az.plant.grass_clump", x, y), gx, gy, now + (h % 11) * 0.27, z=z, solid=False)
        elif h % 13 == 0:
            f.sprite(self._variant_name(("az.deco.dry_bush", "az.deco.stones", "az.deco.bones", "az.deco.tuft")[(h >> 5) % 4], x, y),
                     gx, gy, z=z, solid=False)

    def _variant_name(self, name: str, x: int, y: int) -> str:
        return name if name in self.bank.registry._arts else self.painter.variant(name, x, y)

    def _collect(self, f: Frame, tx0: int, ty0: int, tx1: int, ty1: int) -> None:
        """Structures, people, creatures and the hero in the window."""
        sim, bank, now = self.sim, self.bank, self.now
        givers = {q2.giver for q2 in sim.quests if sim.available_from(q2.giver)}
        turn_ins = {a.quest.turn_in for a in sim.hero.active.values() if a.ready}
        near = lambda x, y: abs(x - self.cam[0]) < 34 and abs(y - self.cam[1]) < 28  # noqa: E731
        for cx in range((tx0 - 12) // CHUNK, (tx1 + 12) // CHUNK + 1):
            for cy in range((ty0 - 12) // CHUNK, (ty1 + 12) // CHUNK + 1):
                for kind, obj in self.by_chunk.get((cx, cy), ()):
                    if kind == "structure":
                        s = obj
                        if not (tx0 - 8 <= s.pos[0] <= tx1 + 8 and ty0 - 4 <= s.pos[1] <= ty1 + 12):
                            continue
                        gx, gy = s.pos[0] * TILE + TILE // 2, s.pos[1] * TILE + TILE - 1
                        sprite = self._variant_name(s.sprite, *s.pos)
                        if sprite not in bank:
                            continue
                        z = self._z(s.pos)
                        f.sprite(sprite, gx, gy, now + s.pos[0] * 0.21, z=z, shadow=0)
                        if s.sprite in FIRES:
                            color, radius = FIRES[s.sprite]
                            f.light(gx, gy, radius, color, 1.0, 0.6, True, phase=s.pos[0] * 0.7, z=z + 8)
                            if "az.fx.campfire_smoke" in bank and s.sprite != "az.obj.torch":
                                f.sprite("az.fx.campfire_smoke", gx, gy - 6, now + s.pos[0] * 0.3, z=z + 10, layer=1)
                    else:
                        p = obj
                        if not (tx0 - 2 <= p.pos[0] <= tx1 + 2 and ty0 - 2 <= p.pos[1] <= ty1 + 6):
                            continue
                        rec = self.records.get(quests.clean(p.title))
                        name = person_sprite(bank, rec, p.title, "idle")
                        if not name:
                            continue
                        gx, gy = p.pos[0] * TILE + TILE // 2, p.pos[1] * TILE + TILE - 1
                        z = self._z(p.pos)
                        f.sprite(name, gx, gy, (p.pos[0] * 0.37) % 2, shadow=12, z=z)
                        key = quests.clean(p.title)
                        marker = "az.fx.quest_turnin" if key in turn_ins else "az.fx.quest_marker" if key in givers else None
                        if marker:
                            f.sprite(marker, gx, gy, now, z=z + bank.art(name).size[1] + 6, layer=1, emissive=True)
                        if near(*p.pos):
                            self.plates.append((gx, gy, z + bank.art(name).size[1], p.title, hud.GOOD))
        for c in sim.near_creatures(2):
            v = self.vis.get(c.id)
            if v is None or not c.alive or not (tx0 - 2 <= v[0] <= tx1 + 2 and ty0 - 2 <= v[1] <= ty1 + 6):
                continue
            moving = now - self.moved_at.get(c.id, -9) < 0.5
            adj = max(abs(c.pos[0] - sim.hero.pos[0]), abs(c.pos[1] - sim.hero.pos[1])) <= 1
            anim = "attack" if c.target_hero and adj else "move" if moving else "idle"
            name = creature_sprite(bank, c.species, anim)
            gx, gy = v[0] * TILE + TILE // 2, v[1] * TILE + TILE - 1
            z = self._z((round(v[0]), round(v[1])))
            f.sprite(name, gx, gy, now + c.id * 0.13, flip=self.facing.get(c.id, False), shadow=max(10, bank.art(name).size[0] * 6 // 10), z=z)
            if near(*c.pos):
                self.plates.append((gx, gy, z + bank.art(name).size[1], f"{c.title} [{c.level}]", hud.BAD if c.hostile else hud.WARN))
        hv = self.vis.get("hero")
        if hv and tx0 - 2 <= hv[0] <= tx1 + 2 and ty0 - 2 <= hv[1] <= ty1 + 6:
            act = sim.action
            attacking = act is not None and act.name == "hunt" and getattr(act, "victim", None) is not None \
                and max(abs(act.victim.pos[0] - sim.hero.pos[0]), abs(act.victim.pos[1] - sim.hero.pos[1])) <= 1
            moving = now - self.moved_at.get("hero", -9) < 0.5
            anim = "attack" if attacking else "walk" if moving else "work" if act is not None and act.name == "search" else "idle"
            name = f"az.person.hero.{anim}"
            gx, gy = hv[0] * TILE + TILE // 2, hv[1] * TILE + TILE - 1
            z = self._z((round(hv[0]), round(hv[1])))
            if moving and "az.fx.dust_kick" in bank:
                f.sprite("az.fx.dust_kick", gx + (5 if not self.facing.get("hero") else -5), gy, now, z=z, layer=1)
            f.sprite(name, gx, gy, now, flip=self.facing.get("hero", False), shadow=12, z=z)
            f.anchors["hero"] = (gx, gy, z + bank.art(name).size[1])
            if sim.thought and self.follow:
                self.renderer.effects.say("hero", sim.thought, "thought", now, 4.0) if "hero" not in self.renderer.effects.bubbles else None
            self.plates.append((gx, gy, z + bank.art(name).size[1], f"{sim.hero.name} [{sim.hero.level}]", hud.CYAN))
        for e in self.renderer.effects.fx:
            ex, ey, ez = e.pos(now)
            f.sprite(e.name, ex, ey, now - e.start, emissive=e.emissive, center=not e.anchored, z=ez, layer=2)

    def _z(self, pos: tuple[int, int]) -> int:
        kind = self.relief.kind(pos[0], pos[1], self.world.tile(*pos))
        return self.relief.height(pos[0], pos[1], kind)

    def _draw_plates(self, screen: pygame.Surface, view: pygame.Rect, f: Frame) -> None:
        size = 12 if self.zoom < 4 else 14
        for gx, gy, top, text, color in self.plates:
            sx, sy = self.renderer.to_screen(f, view, gx, gy, top + 6)
            surf = txt.render(text, "text", size, color, shadow=(0, 0, 0))
            screen.blit(surf, (sx - surf.get_width() // 2, sy - surf.get_height() * 2 // 3))

    def _draw_log(self, screen: pygame.Surface, rect: pygame.Rect) -> None:
        """Newest event at the bottom, stamped with the game clock (a tick is not a minute here)."""
        size = 14
        lh = txt.line_height("text", size)
        y, x, width = rect.bottom - 6, rect.x + 8, rect.width - 16 - 44
        prev = screen.get_clip()
        screen.set_clip(rect)
        for ev in reversed(list(self.events)):
            lines = txt.wrap(txt.clean(ev.text), "text", size, width)[:6]
            block = lh * len(lines)
            y -= block + 3
            if y + block < rect.y:
                break
            secs = ev.tick * TICK_SECONDS
            screen.blit(txt.render(f"{int(secs // 3600) % 24:02d}:{int(secs // 60) % 60:02d}", "pixel", 12, hud.FAINT), (x, y + 2))
            icon = f"ui.log.{ev.kind}"
            if icon in self.bank:
                screen.blit(self.bank.frame(icon, self.now, 2), (x + 30, y + 1))
            if ev.kind in ("death", "victory"):
                pygame.draw.rect(screen, (150, 30, 40) if ev.kind == "death" else (40, 120, 60), (x + 48, y, width - 4, block))
            for i, ln in enumerate(lines):
                screen.blit(txt.render(ln, "text", size, hud.LOG_COLORS.get(ev.kind, hud.TEXT)), (x + 50, y + i * lh))
        screen.set_clip(prev)

    def draw_minimap(self, screen: pygame.Surface, view: pygame.Rect) -> None:
        m = self.minimap
        box = pygame.Rect(view.right - m.get_width() - 18, view.y + 12, m.get_width() + 6, m.get_height() + 6)
        self.minimap_rect = pygame.Rect(box.x + 3, box.y + 3, m.get_width(), m.get_height())
        hud.frame_rect(screen, box, bg=(6, 5, 12))
        screen.blit(m, self.minimap_rect.topleft)
        geo = self.world.geo
        for p in self.world.placements:
            if p.kind in ("settlement", "gate"):
                pygame.draw.circle(screen, (255, 160, 40), (self.minimap_rect.x + int(p.pos[0] / geo.width * m.get_width()),
                                                             self.minimap_rect.y + int(p.pos[1] / geo.height * m.get_height())), 2)
        cx, cy = self.cam
        if int(self.now * 3) % 2:
            pygame.draw.circle(screen, (255, 255, 255), (self.minimap_rect.x + int(cx / geo.width * m.get_width()),
                                                         self.minimap_rect.y + int(cy / geo.height * m.get_height())), 3, 1)

    def draw_status(self, screen: pygame.Surface, rect: pygame.Rect) -> int:
        sim, world = self.sim, self.world
        hud.frame_rect(screen, rect)
        L = hud.Layout(screen, self.bank, rect, self.now)
        L.title(world.clock(), "ui.day" if 6 <= world.hour < 20 else "ui.night")
        x, y = int(self.cam[0]), int(self.cam[1])
        geo = world.geo
        L.line(self._place_name(), hud.CYAN, face="bold", size=17)
        L.line(f"тайл {x},{y} · {x * 2},{y * 2} ярдів", hud.DIM, size=14)
        L.line(f"на карті зони: {x / geo.width * 100:.1f}%, {y / geo.height * 100:.1f}%", hud.DIM, size=14)
        L.line(f"вид: {'2.5D' if self.view == 'iso' else '3/4'} · масштаб x{self.zoom} · швидкість {self.tps}", hud.DIM, size=14)
        L.space(6)
        L.title("Місця (цифри)", "ui.location")
        for i, name in enumerate(PLACES[:9], 1):
            L.line(f"{i}  {name}", hud.TEXT, size=13)
        if self.follow:
            L.space(4)
            L.title(sim.hero.name, "ui.brain")
            L.bar("ui.hp", "здоров'я", sim.hero.hp, sim.hero.max_hp, text=f"{sim.hero.hp:.0f}")
            act = sim.action
            L.line(f"дія: {act.name} {act.target}".strip() if act else "дія: —", hud.TEXT, size=14)
        return L.y

    def _place_name(self) -> str:
        cx, cy = self.cam
        best, bd = "Мулгор", 10 ** 9
        for p in self.sim.landmarks():
            d = max(abs(p.pos[0] - cx), abs(p.pos[1] - cy))
            if d < bd and d < 70:
                best, bd = p.title, d
        return best

    # --- input -----------------------------------------------------------------------------------
    def handle(self, event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.MOUSEWHEEL:
            if self.overlay == "diary":
                self.scroll = max(0, self.scroll - event.y * 3)
            else:
                self._zoom(1 if event.y > 0 else -1)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.show_minimap and self.minimap_rect.collidepoint(event.pos):
                u = (event.pos[0] - self.minimap_rect.x) / self.minimap_rect.width
                v = (event.pos[1] - self.minimap_rect.y) / self.minimap_rect.height
                self.cam = [u * self.world.geo.width, v * self.world.geo.height]
                self.follow = False
            elif self.map_rect().collidepoint(event.pos):
                self.drag = event.pos
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.drag = None
        elif event.type == pygame.MOUSEMOTION and self.drag is not None:
            dx, dy = self._screen_to_tiles(event.pos[0] - self.drag[0], event.pos[1] - self.drag[1])
            self.cam[0] -= dx
            self.cam[1] -= dy
            self.drag = event.pos
            self.follow = False
        elif event.type == pygame.KEYDOWN:
            key, uni = event.key, event.unicode
            if self.overlay and key == pygame.K_ESCAPE:
                self.overlay = None
            elif self.overlay == "diary" and key in (pygame.K_UP, pygame.K_DOWN, pygame.K_PAGEUP, pygame.K_PAGEDOWN):
                step = {pygame.K_UP: -1, pygame.K_DOWN: 1, pygame.K_PAGEUP: -10, pygame.K_PAGEDOWN: 10}[key]
                self.scroll = max(0, min(self.max_scroll, self.scroll + step))
            elif pygame.K_1 <= key <= pygame.K_9:
                self.goto(PLACES[key - pygame.K_1])
            elif key == pygame.K_SPACE:
                self.paused = not self.paused
            elif uni in ("+", "=") or key in (pygame.K_KP_PLUS, pygame.K_EQUALS):
                self.speed_idx = min(self.speed_idx + 1, len(TPS) - 1)
            elif uni == "-" or key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.speed_idx = max(self.speed_idx - 1, 0)
            elif uni == "]":
                self._zoom(1)
            elif uni == "[":
                self._zoom(-1)
            elif key == pygame.K_f:
                self.follow = not self.follow
                self.toast("Камера слідує за героєм" if self.follow else "Вільна камера")
            elif key == pygame.K_i:
                self.view = "2d" if self.view == "iso" else "iso"
                self.toast("Вид: " + ("2.5D" if self.view == "iso" else "3/4 зверху"))
            elif key == pygame.K_e:
                self.overlay = None if self.overlay == "diary" else "diary"
                self.scroll = 0
            elif key in (pygame.K_h, pygame.K_F1):
                self.overlay = None if self.overlay == "help" else "help"
            elif key == pygame.K_m:
                self.show_minimap = not self.show_minimap
            elif key == pygame.K_n:
                self.show_names = not self.show_names
            elif key == pygame.K_TAB:
                self.show_panel = not self.show_panel
            elif key == pygame.K_F12:
                SCREENSHOT_DIR.mkdir(exist_ok=True)
                path = SCREENSHOT_DIR / f"wilds-mulgore-{self.seed}-{int(time.time())}.png"
                pygame.image.save(self.screen, str(path))
                self.toast(f"Скріншот: {path}")
            elif key == pygame.K_F11:
                pygame.display.toggle_fullscreen()
            elif key == pygame.K_q:
                self.running = False

    def _zoom(self, step: int) -> None:
        i = ZOOMS.index(self.zoom) if self.zoom in ZOOMS else 2
        self.zoom = ZOOMS[max(0, min(len(ZOOMS) - 1, i + step))]

    def run(self) -> None:
        clock = pygame.time.Clock()
        while self.running:
            dt = min(clock.tick(FPS) / 1000.0, 0.1)
            for event in pygame.event.get():
                self.handle(event)
            self.update(dt)
            self.draw()
            pygame.display.flip()
        if self.renderer.missing:
            print("sprites missing (drawn as placeholders):", ", ".join(sorted(self.renderer.missing)), file=sys.stderr)
        pygame.quit()

    def shot(self, path: Path | str, frames: int = 30, dt: float = 1 / 30) -> Path:
        """Render a few frames without a window (animations settle) and save a PNG."""
        for _ in range(frames):
            self.update(dt)
            self.t0 -= dt
        self.draw()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(self.screen, str(path))
        return path


__all__ = ["AzApp"]
