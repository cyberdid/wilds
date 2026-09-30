"""The Azeroth client: ``wilds --chapter azeroth --gfx`` (Mulgore).

A zone is millions of tiles, so this is not the fixed-level renderer of the other chapters: the
camera looks at a window of the lazily generated world, ground tiles blend into each other, and
only what is near the camera is drawn (people, creatures, structures, names, quest markers).
The AI lives, you watch.

Keys: space pause · +/- speed · [ ] or wheel zoom · d diary · m minimap · n names · Tab panel ·
s screenshot (F12) · h help · q quit.
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

from ..azeroth import content, quests, settlements
from ..azeroth.scale import CHUNK, TICK_SECONDS
from ..azeroth.terrain import Terrain
from . import hud
from . import text as txt
from .bank import SpriteBank
from .sprites import load_all, load_azeroth

TILE = 16
TPS = [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048]
ZOOMS = (1, 2, 3, 4, 5, 6)
PANEL_W = 400
FPS = 60
SCREENSHOT_DIR = Path("screenshots")
HELP = [
    ("Керування", "pixel"),
    ("пробіл - пауза        + / - - швидкість (тіків за секунду)", "text"),
    ("[ ] або коліщатко - масштаб        Tab - сховати панель", "text"),
    ("d - щоденник        m - мінікарта        n - імена над головами", "text"),
    ("F12 - скріншот        h / F1 - ця довідка        q - вихід", "text"),
    ("", "text"),
    ("Мулгор у справжньому масштабі: 5450 x 3633 ярдів, тайл = 2 ярди.", "text"),
    ("ШІ сам вирішує, що робити: думки видно над героєм.", "text"),
]

GROUND = {Terrain.GRASS: "az.ground.grass", Terrain.TALL_GRASS: "az.ground.tall_grass",
          Terrain.DRY_GRASS: "az.ground.dry_grass", Terrain.DIRT: "az.ground.dirt", Terrain.ROAD: "az.ground.road",
          Terrain.MESA: "az.ground.mesa", Terrain.WATER: "az.ground.water", Terrain.SHALLOWS: "az.ground.shallows",
          Terrain.BOULDER: "az.ground.grass", Terrain.MOUNTAIN: "az.mountain.top", Terrain.CLIFF: "az.cliff.face"}
# a higher-ranked neighbour bleeds into a lower-ranked tile along their shared edge
RANK = {Terrain.DIRT: 1, Terrain.ROAD: 2, Terrain.MESA: 3, Terrain.DRY_GRASS: 4, Terrain.GRASS: 5,
        Terrain.TALL_GRASS: 6, Terrain.BOULDER: 5}
WATERS = (Terrain.WATER, Terrain.SHALLOWS)
GRASSES = (Terrain.GRASS, Terrain.TALL_GRASS, Terrain.DRY_GRASS, Terrain.BOULDER)
SIDES = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}
CORNERS = {"ne": (1, -1), "nw": (-1, -1), "se": (1, 1), "sw": (-1, 1)}
DECO = ("az.deco.flower_red", "az.deco.flower_yellow", "az.deco.flower_blue", "az.deco.tuft", "az.deco.stones",
        "az.deco.tuft", "az.deco.dry_bush", "az.deco.bones")
NODES = ("az.node.peacebloom", "az.node.silverleaf", "az.node.earthroot", "az.node.copper_vein",
         "az.node.prairie_flower", "az.node.shiny_stone")
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
    """Ground tiles with soft edges; composites are cached by what they are made of."""

    def __init__(self, bank: SpriteBank) -> None:
        self.bank = bank
        self._composite: dict[tuple, pygame.Surface] = {}
        self._scaled: dict[tuple, pygame.Surface] = {}
        self._masks: dict[tuple, pygame.Surface] = {}

    def variant(self, base: str, x: int, y: int) -> str:
        vs = self.bank.registry.variants(base)
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

    def tile(self, grid, gx: int, gy: int, x: int, y: int, scale: int, t: float) -> pygame.Surface:
        """The finished ground tile at world (x, y); ``grid[gy][gx]`` is its terrain."""
        terr = grid[gy][gx]
        base = GROUND[terr]
        if terr in WATERS:
            return self._water(grid, gx, gy, x, y, scale, t)
        name = self.variant(base, x, y) if terr is not Terrain.BOULDER else self.variant(GROUND[Terrain.GRASS], x, y)
        blends, overlays = [], []
        rank = RANK.get(terr)
        for side, (dx, dy) in SIDES.items():
            nb = grid[gy + dy][gx + dx]
            if rank is not None and nb in RANK and RANK[nb] > rank:
                blends.append((side, self.variant(GROUND[nb if nb is not Terrain.BOULDER else Terrain.GRASS],
                                                  x + dx, y + dy), tile_hash(x, y, 3) % 4))
            if terr in (Terrain.DIRT, Terrain.ROAD) and nb in GRASSES:
                overlays.append(f"az.edge.dirt.{side}")
            elif terr is Terrain.CLIFF and nb in GRASSES:
                overlays.append(f"az.edge.cliff.{side}")
        if terr in (Terrain.DIRT, Terrain.ROAD, Terrain.CLIFF):
            kind = "cliff" if terr is Terrain.CLIFF else "dirt"
            for corner, (dx, dy) in CORNERS.items():
                sides = [f"az.edge.{kind}.{s}" for s, (sx, sy) in SIDES.items() if (sx == dx or sy == dy) and (sx, sy) != (0, 0)
                         and (sx == dx and sy == 0 or sy == dy and sx == 0)]
                if grid[gy + dy][gx + dx] in GRASSES and not any(o in overlays for o in sides):
                    overlays.append(f"az.edge.{kind}.corner.{corner}")
        key = (name, tuple(blends), tuple(overlays), scale)
        surf = self._scaled.get(key)
        if surf is None:
            comp = self.bank.base(name)[0].copy()
            for side, nb_name, var in blends:
                layer = self.bank.base(nb_name)[0].copy()
                layer.blit(self._mask(side, var), (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                comp.blit(layer, (0, 0))
            for ov in overlays:
                if ov in self.bank:
                    comp.blit(self.bank.base(ov)[0], (0, 0))
            surf = pygame.transform.scale(comp, (TILE * scale, TILE * scale)) if scale != 1 else comp
            self._scaled[key] = surf
        return surf

    def _water(self, grid, gx, gy, x, y, scale, t) -> pygame.Surface:
        terr = grid[gy][gx]
        surf = self.bank.frame(self.variant(GROUND[terr], x, y), t, scale).copy()
        land = {s: grid[gy + dy][gx + dx] not in WATERS and grid[gy + dy][gx + dx] is not Terrain.VOID
                for s, (dx, dy) in SIDES.items()}
        for side, is_land in land.items():
            name = f"az.edge.water.{side}"
            if is_land and name in self.bank:
                surf.blit(self.bank.frame(name, t, scale), (0, 0))
        for corner, (dx, dy) in CORNERS.items():
            sides = [s for s, (sx, sy) in SIDES.items() if (sx == dx and sy == 0) or (sy == dy and sx == 0)]
            nb = grid[gy + dy][gx + dx]
            if nb not in WATERS and nb is not Terrain.VOID and not any(land[s] for s in sides):
                name = f"az.edge.water.corner.{corner}"
                if name in self.bank:
                    surf.blit(self.bank.frame(name, t, scale), (0, 0))
        return surf


def outfit_of(rec: dict | None, title: str) -> str:
    text = ((rec["info"].get("profession", "") + " " + rec["info"].get("title", "")) if rec else "") + " " + title
    text = text.lower()
    return next((v for k, v in OUTFITS if k in text), "civilian")


def person_sprite(bank: SpriteBank, rec: dict | None, title: str, anim: str) -> str | None:
    race = quests.clean(rec["info"].get("race", "")) if rec else "tauren"
    if race in ("", "tauren", "highmountain tauren", "varies"):
        female = bool(rec) and rec["info"].get("gender", "").lower() == "female"
        body = "tauren_f" if female else "tauren_m"
        outfit = outfit_of(rec, title)
        name = f"az.person.{body}.{outfit}.{anim}"
        return name if name in bank else f"az.person.{body}.civilian.{anim}"
    if race in BODIES:
        name = f"az.person.{BODIES[race]}.civilian.{anim}"
        return name if name in bank else None
    slug = "_".join(race.replace("'", "").split())
    name = f"az.creature.{slug}.{'idle' if anim in ('idle', 'talk') else 'move'}"
    return name if name in bank else None


def creature_sprite(bank: SpriteBank, species: str, anim: str) -> str:
    slug = "_".join(species.replace("'", "").split())
    if slug in ("tauren",):
        return f"az.person.tauren_m.palemane.{ 'walk' if anim == 'move' else 'idle' if anim in ('idle', 'dead') else anim}"
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
                 size: tuple[int, int] = (1360, 820), zoom: int = 3, headless: bool = False,
                 fullscreen: bool = False, diary_dir: Path | None = None) -> None:
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
        self.painter = Painter(self.bank)
        self.sim = sim
        self.world = sim.world
        self.brain = brain
        self.seed = seed
        self.headless = headless
        self.speed_idx = max(0, min(len(TPS) - 1, speed + 1))
        self.zoom = zoom if zoom in ZOOMS else 3
        self.paused = False
        self.show_minimap = True
        self.show_panel = True
        self.show_names = True
        self.overlay: str | None = None
        self.scroll = 0
        self.max_scroll = 0
        self.thinking_since: float | None = None
        self.thinking_kind = "decide"
        self.results: queue.Queue = queue.Queue()
        self.events: deque = deque(maxlen=300)
        self.toasts: list[tuple[str, float]] = []
        self.acc = 0.0
        self.cam: list[float] | None = None
        self.t0 = time.monotonic()
        self.now = 0.0
        self.running = True
        self._shadows: dict[int, pygame.Surface] = {}
        self.floaters: list[list] = []   # [x, y, text, colour, born]
        self.bursts: list[tuple[str, float, float, float, float]] = []  # sprite, x, y, born, life
        self.vis: dict[object, list[float]] = {}     # drawn position per creature / the hero
        self.moved_at: dict[object, float] = {}
        self.facing: dict[object, bool] = {}
        self.records = {quests.clean(r["title"]): r for k in ("npc", "mob") for r in content.load(sim.world.pack, k)}
        self.structures = settlements.build_structures(self.world)
        self.platforms = settlements.platforms(self.world)
        self.bridge_tiles = self._bridge_tiles()
        self._index_static()
        self.minimap = self._minimap_surface()
        if diary_dir:
            diary_dir.mkdir(parents=True, exist_ok=True)
            sim.diary_path = diary_dir / f"diary-azeroth-{brain.name}-{seed}.md"
        self.world.listeners.append(self._on_event)
        for ev in self.world.events[-60:]:
            self.events.append(ev)

    # --- static world index ---------------------------------------------------------------------
    def _bridge_tiles(self) -> set[tuple[int, int]]:
        out: set[tuple[int, int]] = set()
        for (x0, y0), (x1, y1) in settlements.bridges(self.world):
            steps = max(abs(x1 - x0), abs(y1 - y0))
            for k in range(steps + 1):
                x, y = round(x0 + (x1 - x0) * k / steps), round(y0 + (y1 - y0) * k / steps)
                out.update((x + dx, y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        return out

    def _index_static(self) -> None:
        self.by_chunk: dict[tuple[int, int], list[tuple[str, object]]] = {}
        for s in self.structures:
            self.by_chunk.setdefault((s.pos[0] // CHUNK, s.pos[1] // CHUNK), []).append(("structure", s))
        for p in self.world.placements:
            if p.kind == "npc":
                self.by_chunk.setdefault((p.pos[0] // CHUNK, p.pos[1] // CHUNK), []).append(("npc", p))

    def _minimap_surface(self) -> pygame.Surface:
        macro = self.world.terrain.macro
        colors = {"g": (98, 160, 72), "d": (186, 176, 92), "r": (150, 122, 112), "m": (92, 66, 44),
                  "v": (18, 18, 26)}
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

    # --- brain ------------------------------------------------------------------------------------
    def _think(self, kind: str) -> None:
        self.thinking_since = time.monotonic()
        self.thinking_kind = kind
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
            else:
                self.sim.apply_conversation(result)

    # --- loop --------------------------------------------------------------------------------------
    @property
    def tps(self) -> int:
        return TPS[self.speed_idx]

    def update(self, dt: float) -> None:
        self.now = time.monotonic() - self.t0
        self._drain()
        sim = self.sim
        if sim.over:
            return
        if not self.paused and self.thinking_since is None:
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
        self._camera(dt)

    def _effects(self) -> None:
        """Turn the simulation's hit/hurt/level-up notes into sparks and floating numbers."""
        for kind, pos, text in self.sim.fx:
            x, y = float(pos[0]), float(pos[1])
            if kind == "hit":
                self.floaters.append([x, y, text, (255, 240, 140), self.now])
                self.bursts.append(("az.fx.hit_spark", x, y, self.now, 0.4))
            elif kind == "hurt":
                self.floaters.append([x, y, "-" + text, (255, 90, 90), self.now])
                self.bursts.append(("az.fx.hit_spark", x, y, self.now, 0.4))
            elif kind == "levelup":
                self.floaters.append([x, y, "РІВЕНЬ " + text, (120, 255, 150), self.now])
                self.bursts.append(("az.fx.level_up", x, y, self.now, 1.4))
        self.sim.fx.clear()
        self.floaters = [f for f in self.floaters if self.now - f[4] < 1.2]
        self.bursts = [b for b in self.bursts if self.now - b[3] < b[4]]

    def _animate(self, dt: float) -> None:
        """Ease the drawn positions towards the simulated ones (several tiles a frame at high speed)."""
        k = min(1.0, dt * max(3.0, self.tps * 1.2))
        hero = self.sim.hero
        targets = {"hero": hero.pos}
        for c in self.sim.near_creatures(3):
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
                if abs(dx) > 0.2:
                    self.facing[key] = dx < 0
            v[0] += dx * k
            v[1] += dy * k
        for key in [k2 for k2 in self.vis if k2 not in targets]:
            del self.vis[key]

    def _camera(self, dt: float) -> None:
        v = self.vis.get("hero") or [float(self.sim.hero.pos[0]), float(self.sim.hero.pos[1])]
        if self.cam is None:
            self.cam = [v[0], v[1]]
        else:
            k = 1 - math.exp(-dt * 8)
            self.cam[0] += (v[0] - self.cam[0]) * k
            self.cam[1] += (v[1] - self.cam[1]) * k
        self.cam[0] = max(0.0, min(self.world.geo.width, self.cam[0]))
        self.cam[1] = max(0.0, min(self.world.geo.height, self.cam[1]))

    def map_rect(self) -> pygame.Rect:
        w, h = self.screen.get_size()
        return pygame.Rect(0, 0, w - (PANEL_W if self.show_panel else 0), h)

    # --- drawing ------------------------------------------------------------------------------------
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
        if self.sim.over:
            self._banner(screen, view, "Мулгор пройдено: час рушати далі")
        if self.overlay == "diary":
            blocks = [(f"День {d}: {text}", hud.TEXT, "text") for d, text in self.sim.hero.diary] \
                or [("Щоденник ще порожній.", hud.DIM, "text")]
            self.max_scroll = hud.text_overlay(screen, "Щоденник", blocks, self.scroll,
                                               "Esc / d - закрити · ↑↓ гортати")
        elif self.overlay == "help":
            hud.text_overlay(screen, "Wilds - довідка", [(t, hud.TEXT, f) for t, f in HELP], 0, "Esc - закрити")
        self.toasts = [(m, until) for m, until in self.toasts if until > self.now]
        for i, (msg, _) in enumerate(self.toasts[-3:]):
            surf = txt.render(msg, "text", 16, hud.TEXT)
            r = pygame.Rect(view.centerx - surf.get_width() // 2 - 12, view.bottom - 90 - i * 40,
                            surf.get_width() + 24, 32)
            hud.frame_rect(screen, r)
            screen.blit(surf, (r.x + 12, r.y + 7))

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
            stamp = txt.render(f"{int(secs // 3600) % 24:02d}:{int(secs // 60) % 60:02d}", "pixel", 12, hud.FAINT)
            screen.blit(stamp, (x, y + 2))
            icon = f"ui.log.{ev.kind}"
            if icon in self.bank:
                screen.blit(self.bank.frame(icon, self.now, 2), (x + 30, y + 1))
            if ev.kind in ("death", "victory"):
                pygame.draw.rect(screen, (150, 30, 40) if ev.kind == "death" else (40, 120, 60),
                                 (x + 48, y, width - 4, block))
            for i, ln in enumerate(lines):
                screen.blit(txt.render(ln, "text", size, hud.LOG_COLORS.get(ev.kind, hud.TEXT)),
                            (x + 50, y + i * lh))
        screen.set_clip(prev)

    def _banner(self, screen, view, text: str) -> None:
        surf = txt.render(text, "bold", 22, hud.GOOD, shadow=(0, 0, 0))
        r = pygame.Rect(view.centerx - surf.get_width() // 2 - 16, view.y + 24, surf.get_width() + 32, 44)
        hud.frame_rect(screen, r)
        screen.blit(surf, (r.x + 16, r.y + 10))

    def draw_world(self, screen: pygame.Surface, view: pygame.Rect) -> None:
        z = self.zoom
        px = TILE * z
        cx, cy = self.cam or (float(self.sim.hero.pos[0]), float(self.sim.hero.pos[1]))
        cols, rows = view.width // px + 3, view.height // px + 3
        x0, y0 = int(cx - cols / 2), int(cy - rows / 2)
        ox = view.centerx - int((cx - x0) * px)   # screen x of tile column x0
        oy = view.centery - int((cy - y0) * px)
        canvas = pygame.Surface(view.size)
        canvas.fill((14, 13, 22))
        world = self.world
        grid = [[world.tile(x, y) for x in range(x0 - 1, x0 + cols + 1)] for y in range(y0 - 1, y0 + rows + 1)]
        sprites: list[tuple[float, str, float, float, bool, float]] = []  # sort y, name, x, y, flip, t
        for gy in range(rows):
            for gx in range(cols):
                x, y = x0 + gx, y0 + gy
                terr = grid[gy + 1][gx + 1]
                if terr is Terrain.VOID:
                    continue
                plat = settlements.on_platform(world, (x, y), self.platforms) if self.platforms_near(x, y) else None
                if plat or (x, y) in self.bridge_tiles:
                    tile = self._platform_tile(world, x, y, plat)
                else:
                    tile = self.painter.tile(grid, gx + 1, gy + 1, x, y, z, self.now)
                canvas.blit(tile, (ox - view.x + gx * px, oy - view.y + gy * px))
                if plat or terr in (Terrain.WATER, Terrain.SHALLOWS, Terrain.VOID):
                    continue
                if terr is Terrain.BOULDER:
                    sprites.append((y, self.painter.variant("az.boulder", x, y), x, y, False, 0.0))
                elif terr in GRASSES:
                    h = tile_hash(x, y, world.seed)
                    if h % 19 == 0:
                        sprites.append((y - 0.6, DECO[(h >> 8) % len(DECO)], x, y, False, 0.0))
                    elif h % 611 == 0:
                        sprites.append((y - 0.4, NODES[(h >> 8) % len(NODES)], x, y, False, self.now + (h % 7)))
        self.plates: list[tuple[float, float, int, str, tuple]] = []
        self._collect(sprites, x0, y0, cols, rows)
        for b_name, bx, by, born, _life in self.bursts:
            sprites.append((by + 1.5, b_name, bx, by, False, self.now - born))
        for _, name, x, y, flip, t in sorted(sprites, key=lambda s: (s[0], s[2])):
            name = self._resolve(name, x, y)
            if name not in self.bank:
                continue
            fr = self.bank.frame(name, t or self.now, z, flip)
            ax, ay = self.bank.anchor(name, z)
            sx = ox - view.x + int((x - x0) * px) + px // 2 - ax
            sy = oy - view.y + int((y - y0) * px) + px - 1 - ay
            if name.startswith(("az.person.", "az.creature.")):
                shadow = self._shadow(fr.get_width() * 6 // 10)
                canvas.blit(shadow, (sx + ax - shadow.get_width() // 2, sy + ay - shadow.get_height() // 2))
            if -fr.get_width() < sx < view.width and -fr.get_height() < sy < view.height + 40:
                canvas.blit(fr, (sx, sy))
        self._overlays(canvas, view, x0, y0, ox - view.x, oy - view.y)
        self._daylight(canvas)
        screen.blit(canvas, view.topleft)

    def _shadow(self, width: int) -> pygame.Surface:
        width = max(6, width)
        shadow = self._shadows.get(width)
        if shadow is None:
            shadow = pygame.Surface((width, max(3, width // 4)), pygame.SRCALPHA)
            pygame.draw.ellipse(shadow, (10, 12, 24, 90), shadow.get_rect())
            self._shadows[width] = shadow
        return shadow

    def platforms_near(self, x: int, y: int) -> bool:
        return any(abs(x - p.center[0]) <= p.radius + 2 and abs(y - p.center[1]) <= p.radius + 2 for p in self.platforms)

    def _platform_tile(self, world, x: int, y: int, plat) -> pygame.Surface:
        z = self.zoom
        south = settlements.on_platform(world, (x, y + 1), self.platforms) or (x, y + 1) in self.bridge_tiles
        if plat is None:
            name = self.painter.variant("az.tb.bridge", x, y)
        elif math.hypot(x - plat.center[0], (y - plat.center[1]) / 0.75) <= settlements.PLAZA_RADIUS \
                and "az.tb.platform.inlay" in self.bank.registry._variants:
            name = self.painter.variant("az.tb.platform.inlay", x, y)
        elif not south:
            name = self.painter.variant("az.tb.platform.edge", x, y)
        else:
            name = self.painter.variant("az.tb.platform", x, y)
        return self.bank.frame(name, 0.0, z)

    def _resolve(self, name: str, x: int, y: int) -> str:
        """``name@N`` fixed variants stay; a plain name that only exists as variants picks by position."""
        if name in self.bank.registry._arts:
            return name
        try:
            vs = self.bank.registry.variants(name)
        except KeyError:
            return name
        return vs[tile_hash(x, y) % len(vs)]

    def _collect(self, sprites: list, x0: int, y0: int, cols: int, rows: int) -> None:
        """Structures, people and creatures in the window."""
        c0x, c1x = (x0 - 12) // CHUNK, (x0 + cols + 12) // CHUNK
        c0y, c1y = (y0 - 12) // CHUNK, (y0 + rows + 12) // CHUNK
        sim = self.sim
        givers = {q2.giver for q2 in sim.quests if sim.available_from(q2.giver)}
        turn_ins = {a.quest.turn_in for a in sim.hero.active.values() if a.ready}
        for cx in range(c0x, c1x + 1):
            for cy in range(c0y, c1y + 1):
                for kind, obj in self.by_chunk.get((cx, cy), ()):
                    if kind == "structure":
                        s = obj
                        sprites.append((s.pos[1], s.sprite, s.pos[0], s.pos[1], False, self.now + s.pos[0] * 0.21))
                        if s.sprite in ("az.obj.bonfire", "az.tb.brazier", "az.obj.cooking_pot"):
                            sprites.append((s.pos[1] + 0.5, "az.fx.campfire_smoke", s.pos[0], s.pos[1] - 1.2, False,
                                            self.now + s.pos[0] * 0.3))
                    else:
                        p = obj
                        name = person_sprite(self.bank, self.records.get(quests.clean(p.title)), p.title, "idle")
                        if name:
                            sprites.append((p.pos[1], name, p.pos[0], p.pos[1], False, (p.pos[0] * 0.37) % 2))
                            self.plates.append((p.pos[0], p.pos[1], self.bank.art(name).size[1], p.title, hud.GOOD))
                        key = quests.clean(p.title)
                        marker = "az.fx.quest_turnin" if key in turn_ins else "az.fx.quest_marker" if key in givers else None
                        if marker:
                            sprites.append((p.pos[1] + 0.9, marker, p.pos[0], p.pos[1] - 1.8, False, self.now))
        for c in sim.near_creatures(3):
            v = self.vis.get(c.id)
            if v is None:
                continue
            moving = self.now - self.moved_at.get(c.id, -9) < 0.5
            anim = "dead" if not c.alive else ("attack" if c.target_hero and max(abs(c.pos[0] - sim.hero.pos[0]), abs(c.pos[1] - sim.hero.pos[1])) <= 1
                                               else "move" if moving else "idle")
            if not c.alive:
                continue
            cname = creature_sprite(self.bank, c.species, anim)
            sprites.append((v[1], cname, v[0], v[1], self.facing.get(c.id, False), self.now + c.id * 0.13))
            if abs(v[0] - sim.hero.pos[0]) < 26 and abs(v[1] - sim.hero.pos[1]) < 16:
                self.plates.append((v[0], v[1], self.bank.art(cname).size[1], f"{c.title} [{c.level}]",
                                    hud.BAD if c.hostile else hud.WARN))
        hv = self.vis.get("hero")
        if hv:
            act = sim.action
            attacking = act is not None and act.name == "hunt" and getattr(act, "victim", None) is not None \
                and max(abs(act.victim.pos[0] - sim.hero.pos[0]), abs(act.victim.pos[1] - sim.hero.pos[1])) <= 1
            moving = self.now - self.moved_at.get("hero", -9) < 0.5
            anim = "attack" if attacking else "walk" if moving else "work" if act is not None and act.name == "search" else "idle"
            if moving:
                sprites.append((hv[1] - 0.01, "az.fx.dust_kick", hv[0] + (0.6 if self.facing.get("hero") else -0.6),
                                hv[1], False, self.now))
            sprites.append((hv[1] + 0.01, f"az.person.hero.{anim}", hv[0], hv[1], self.facing.get("hero", False), self.now))
            self.plates.append((hv[0], hv[1], self.bank.art(f"az.person.hero.{anim}").size[1],
                                f"{sim.hero.name} [{sim.hero.level}]", hud.CYAN))

    def _overlays(self, canvas, view, x0, y0, ox, oy) -> None:
        """Names, health bars and the hero's thought over the heads."""
        z, px = self.zoom, TILE * self.zoom
        sim = self.sim
        hero = sim.hero
        if self.show_names and z >= 2:
            for x, y, h_px, text, color in self.plates:
                surf = txt.render(text, "text", 12 if z < 4 else 14, color, shadow=(0, 0, 0))
                canvas.blit(surf, (int(ox + (x - x0) * px + px // 2 - surf.get_width() // 2),
                                   int(oy + (y - y0) * px + px - 1 - h_px * z - surf.get_height() - 2)))
            for c in sim.near_creatures(3):
                v = self.vis.get(c.id)
                if v and c.alive and c.hp < c.max_hp and abs(v[0] - hero.pos[0]) < 26 and abs(v[1] - hero.pos[1]) < 16:
                    bx = int(ox + (v[0] - x0) * px + px // 2 - 14)
                    by = int(oy + (v[1] - y0) * px + px - 1 - 16 * z - 22)
                    pygame.draw.rect(canvas, (20, 10, 10), (bx, by, 28, 4))
                    pygame.draw.rect(canvas, (220, 60, 60), (bx, by, int(28 * c.hp / c.max_hp), 4))
        for fx_x, fx_y, text, color, born in self.floaters:
            age = self.now - born
            surf = txt.render(text, "bold", 16 + 2 * z, color, shadow=(0, 0, 0))
            canvas.blit(surf, (int(ox + (fx_x - x0) * px + px // 2 - surf.get_width() // 2),
                               int(oy + (fx_y - y0) * px - 20 * z - age * 40 * z // 2)))
        if sim.thought and self.vis.get("hero"):
            hv = self.vis["hero"]
            lines = txt.wrap(txt.clean(sim.thought), "text", 14, 280)[:3]
            w = max(txt.font("text", 14).size(ln)[0] for ln in lines) + 16
            h = 8 + 17 * len(lines)
            bx = int(ox + (hv[0] - x0) * px + px // 2 - w // 2)
            by = int(oy + (hv[1] - y0) * px - 26 * z - h - 14)
            r = pygame.Rect(max(4, min(canvas.get_width() - w - 4, bx)), max(4, by), w, h)
            pygame.draw.rect(canvas, (236, 240, 250), r, border_radius=4)
            pygame.draw.rect(canvas, (40, 44, 70), r, 2, border_radius=4)
            for i, ln in enumerate(lines):
                canvas.blit(txt.render(ln, "text", 14, (30, 34, 56)), (r.x + 8, r.y + 4 + i * 17))

    def _daylight(self, canvas: pygame.Surface) -> None:
        h = self.world.hour + self.world.minute / 60
        light = 1.0 if 7 <= h <= 18 else 0.0 if (h >= 21 or h <= 4) else (h - 4) / 3 if h < 7 else 1 - (h - 18) / 3
        alpha = int((1 - light) * 140)
        if alpha > 0:
            veil = pygame.Surface(canvas.get_size())
            veil.fill((12, 18, 60))
            veil.set_alpha(alpha)
            canvas.blit(veil, (0, 0))

    def draw_minimap(self, screen: pygame.Surface, view: pygame.Rect) -> None:
        m = self.minimap
        box = pygame.Rect(view.right - m.get_width() - 18, view.y + 12, m.get_width() + 6, m.get_height() + 6)
        hud.frame_rect(screen, box, bg=(6, 5, 12))
        screen.blit(m, (box.x + 3, box.y + 3))
        geo = self.world.geo
        for p in self.world.placements:
            if p.kind in ("settlement", "gate"):
                pygame.draw.circle(screen, (255, 160, 40), (box.x + 3 + int(p.pos[0] / geo.width * m.get_width()),
                                                             box.y + 3 + int(p.pos[1] / geo.height * m.get_height())), 2)
        hx, hy = self.sim.hero.pos
        if int(self.now * 3) % 2:
            pygame.draw.circle(screen, (255, 255, 255), (box.x + 3 + int(hx / geo.width * m.get_width()),
                                                         box.y + 3 + int(hy / geo.height * m.get_height())), 3)

    def draw_status(self, screen: pygame.Surface, rect: pygame.Rect) -> int:
        sim, world, hero = self.sim, self.world, self.sim.hero
        hud.frame_rect(screen, rect)
        L = hud.Layout(screen, self.bank, rect, self.now)
        L.title(world.clock(), "ui.day" if 6 <= world.hour < 20 else "ui.night")
        top = L.y
        if "az.portrait.hero" in self.bank:
            screen.blit(self.bank.frame("az.portrait.hero", self.now, 3), (L.x, top))
        bx = L.x + 84
        name = txt.render(hero.name, "bold", 18, hud.TEXT, shadow=(0, 0, 0))
        screen.blit(name, (bx, top))
        screen.blit(txt.render(f"рівень {hero.level} · тауренський мандрівник", "text", 14, hud.DIM), (bx, top + 24))
        place = self._place_name()
        screen.blit(txt.render(place, "text", 14, hud.CYAN), (bx, top + 44))
        L.y = top + 76
        L.bar("ui.hp", "здоров'я", hero.hp, hero.max_hp, text=f"{hero.hp:.0f}/{hero.max_hp:.0f}")
        L.bar("ui.energy", "досвід", hero.xp, hero.xp_to_next(), color=hud.MAGENTA, text=f"{hero.xp}/{hero.xp_to_next()}")
        L.space(4)
        act = sim.action
        shown = f"{act.name} {act.target}".strip() if act else ("думає" if self.thinking_since else "—")
        L.line(f"дія: {shown}", hud.TEXT, icon="ui.brain")
        if sim.thought:
            L.para("«" + sim.thought + "»", hud.CYAN, max_lines=2)
        L.line(f"вбито {sum(hero.kills.values())} · завдань {len(hero.done)} · смертей {hero.deaths}", hud.DIM, size=14)
        L.space(4)
        L.title("Задання", "ui.goal")
        if not hero.active:
            L.line("жодного активного", hud.DIM)
        for aq in list(hero.active.values())[:5]:
            mark = "✔ " if aq.ready else ""
            L.line(f"{mark}{aq.quest.title}", hud.GOOD if aq.ready else hud.TEXT, size=14)
            for o in aq.objectives[:2]:
                L.line(f"   {o.target} {o.done}/{o.count}", hud.DIM, size=13)
        return L.y

    def _place_name(self) -> str:
        hp = self.sim.hero.pos
        best, bd = "Мулгор", 10 ** 9
        for p in self.sim.landmarks():
            d = max(abs(p.pos[0] - hp[0]), abs(p.pos[1] - hp[1]))
            if d < bd and d < 60:
                best, bd = p.title, d
        return best

    # --- input --------------------------------------------------------------------------------------
    def handle(self, event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.MOUSEWHEEL:
            if self.overlay == "diary":
                self.scroll = max(0, self.scroll - event.y * 3)
            else:
                self._zoom(1 if event.y > 0 else -1)
        elif event.type == pygame.KEYDOWN:
            key, uni = event.key, event.unicode
            if self.overlay and key == pygame.K_ESCAPE:
                self.overlay = None
            elif self.overlay == "diary" and key in (pygame.K_UP, pygame.K_DOWN, pygame.K_PAGEUP, pygame.K_PAGEDOWN):
                step = {pygame.K_UP: -1, pygame.K_DOWN: 1, pygame.K_PAGEUP: -10, pygame.K_PAGEDOWN: 10}[key]
                self.scroll = max(0, min(self.max_scroll, self.scroll + step))
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
            elif key == pygame.K_d:
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
            elif key in (pygame.K_F12, pygame.K_s):
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
        pygame.quit()

    def shot(self, path: Path | str, frames: int = 45, dt: float = 1 / 30) -> Path:
        """Render a few frames without a window (animations settle) and save a PNG."""
        for _ in range(frames):
            self.update(dt)
            self.t0 -= dt
        self.draw()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(self.screen, str(path))
        return path


__all__ = ["AzApp", "TICK_SECONDS"]
