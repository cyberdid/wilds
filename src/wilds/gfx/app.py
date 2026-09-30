"""The sprite front-end: ``wilds --gfx`` (Tau-7) and ``wilds --chapter cyberpunk --gfx``.

Same aquarium as the terminal UI - the AI lives, you watch - drawn with pixel
art: the simulation ticks at a chosen speed, brain calls run on a worker thread
while the world waits (exactly like the Textual app), and the renderer only
reads game state.

Keys: space pause · +/- speed · [ ] or wheel zoom · i 2D <-> isometric 2.5D ·
d diary · g god view · m minimap · s save · n new world · Tab HUD ·
F11 fullscreen · F12 screenshot · h help · q quit.
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
from typing import Callable

import pygame

from ..campaign import CHAPTER2_TITLE, ready_for_chapter2
from ..eventlog import EventLog
from . import hud
from . import text as txt
from .bank import SpriteBank
from .render import PROJECTIONS, TILE, Renderer

TPS = [2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]  # simulation ticks per second
ZOOMS = (1, 2, 3, 4, 5, 6)
PANEL_W = 400
FPS = 60
RESTART_AFTER = 20.0
SCREENSHOT_DIR = Path("screenshots")

HELP = [
    ("Керування", "pixel"),
    ("пробіл — пауза        + / - — швидкість (тіків за секунду)", "text"),
    ("[ ] або коліщатко — масштаб        Tab — сховати панель", "text"),
    ("i — вид: 2D (3/4 зверху) ↔ ізометрія 2.5D", "text"),
    ("d — щоденник        g — «око бога»        m — мінікарта", "text"),
    ("s — зберегти               n — новий світ        q — вихід", "text"),
    ("F11 — повний екран        F12 — скріншот        h / F1 — ця довідка", "text"),
    ("", "text"),
    ("ШІ сам вирішує, що робити: думки видно над головою героя, щоденник — клавіша d.", "text"),
]


def speed_index(speed: int) -> int:
    """Map the CLI --speed (0-6, shared with the terminal UI) onto the TPS ladder."""
    return max(0, min(len(TPS) - 1, speed + 1))


# --- chapters ------------------------------------------------------------------------


class Tau7Chapter:
    title = "Wilds: Тау-7"
    log_title = "Тау-7"
    log_kind = "tau7"
    can_save = True

    def __init__(self, make_world: Callable, diary_dir: Path | None = None, save_dir: Path | None = None,
                 legacy_dir: Path | None = None) -> None:
        self.make_world = make_world
        self.diary_dir = diary_dir
        self.save_dir = save_dir
        self.legacy_dir = legacy_dir

    def new_sim(self, app, seed: int):
        from ..sim import Simulation

        brain = app.brain
        if hasattr(brain, "wrecks_done"):
            brain.wrecks_done = set()
        fallback = getattr(brain, "fallback", None)
        if fallback is not None:
            fallback.wrecks_done = set()
        sim = Simulation(self.make_world(seed))
        sim.brain_name = brain.name
        if self.diary_dir:
            self.diary_dir.mkdir(parents=True, exist_ok=True)
            sim.diary_path = self.diary_dir / f"diary-{brain.name}-{seed}.md"
        if self.legacy_dir:
            sim.legacy_dir = self.legacy_dir
        return sim

    def adopt(self, app, sim) -> None:
        """A loaded save: wire it up the same way the terminal UI does."""
        sim.brain_name = app.brain.name
        if self.legacy_dir:
            sim.legacy_dir = self.legacy_dir

    def scene(self, renderer: Renderer):
        from .tau7_scene import Tau7Scene

        return Tau7Scene(renderer)

    def status(self, app, screen, rect, t) -> int:
        from .tau7_hud import status

        return status(app, screen, rect, t)

    def overlays(self, app, screen, view, t) -> None:
        from .tau7_hud import overlays

        overlays(app, screen, view, t)

    def diary(self, app):
        from .tau7_hud import diary_blocks

        return diary_blocks(app)

    def minimap_color(self, tile, level_id: str) -> tuple[int, int, int]:
        from .palette import PALETTE
        from ..tiles import Tile

        name = {Tile.MOSS: "moss3", Tile.DUST: "dust3", Tile.FLORA: "flora3", Tile.STALK: "flora2",
                Tile.SPORE_BUSH: "spore3", Tile.SPORE_BUSH_EMPTY: "grey2", Tile.WATER: "water3",
                Tile.ROCK: "rock3", Tile.WRECK: "glowcyan", Tile.HEATER: "fire3", Tile.HEATER_OFF: "grey2",
                Tile.DOME: "tent2", Tile.GRAVE: "white", Tile.POD: "white", Tile.CRASH: "bone3",
                Tile.WALL: "steel3", Tile.FLOOR: "steel1", Tile.HATCH: "glowlime"}.get(tile, "grey2")
        return PALETTE[name]

    def tick_multiplier(self, sim) -> int:
        action = sim.action
        return 4 if sim.world.hero.sleeping or (action and action.effective_name in ("rest", "wait")) else 1

    def fallback_brain(self):
        from ..brain import ScriptedBrain

        return ScriptedBrain()

    def save(self, app, quiet: bool = False) -> Path | None:
        from ..save import save_game, save_path

        if self.save_dir is None or app.sim.over:
            return None
        path = save_path(app.sim, app.brain.name, self.save_dir)
        save_game(app.sim, path, {"wrecks_done": sorted(getattr(app.brain, "wrecks_done", set()))})
        if app.eventlog:
            app.eventlog.meta(f"збережено: {path}")
        if not quiet:
            app.toast(f"Гру збережено: {path}")
        return path

    def answered(self, app, kind: str) -> None:
        if kind == "reflect":
            self.save(app, quiet=True)  # autosave once per sol, like the terminal UI

    def over_title(self, sim) -> str:
        return ""


class CityChapter:
    title = "Wilds: Тінемісто"
    log_title = "Тінемісто"
    log_kind = "cyberpunk"
    can_save = True

    def __init__(self, make_world: Callable, diary_dir: Path | None = None, save_dir: Path | None = None) -> None:
        self.make_world = make_world
        self.diary_dir = diary_dir
        self.save_dir = save_dir

    def new_sim(self, app, seed: int):
        from ..cyberpunk.sim import CitySim

        sim = CitySim(self.make_world(seed))
        if self.diary_dir:
            self.diary_dir.mkdir(parents=True, exist_ok=True)
            sim.diary_path = self.diary_dir / f"diary-cyberpunk-{app.brain.name}-{seed}.md"
        return sim

    def adopt(self, app, sim) -> None:
        pass

    def scene(self, renderer: Renderer):
        from .city_scene import CityScene

        return CityScene(renderer)

    def status(self, app, screen, rect, t) -> int:
        from .city_hud import status

        return status(app, screen, rect, t)

    def overlays(self, app, screen, view, t) -> None:
        from .city_hud import overlays

        overlays(app, screen, view, t)

    def diary(self, app):
        from .city_hud import diary_blocks

        return diary_blocks(app)

    def minimap_color(self, tile, level_id: str) -> tuple[int, int, int]:
        from ..cyberpunk.tiles import CTile
        from .palette import PALETTE

        name = {CTile.SIDEWALK: "conc2", CTile.ROAD: "asph3", CTile.NEON: "neon_pink", CTile.ALLEY: "conc1",
                CTile.WALL: "city4", CTile.DOOR: "tent2", CTile.SHOP: "neon_green", CTile.BAR: "neon_yellow",
                CTile.FIXER: "neon_cyan", CTile.CHECKPOINT: "neon_red", CTile.FENCE: "grey3",
                CTile.TRASH: "rust2"}.get(tile, "grey2")
        return PALETTE[name]

    def tick_multiplier(self, sim) -> int:
        action = sim.action
        return 4 if action and action.name == "rest" else 1

    def fallback_brain(self):
        from ..cyberpunk.scripted import CyberScriptedBrain

        return CyberScriptedBrain()

    def save(self, app, quiet: bool = False) -> Path | None:
        from ..save import CITY_SUFFIX, save_game, save_path

        if self.save_dir is None or app.sim.over:
            return None
        path = save_game(app.sim, save_path(app.sim, app.brain.name, self.save_dir, CITY_SUFFIX))
        if app.eventlog:
            app.eventlog.meta(f"збережено: {path}")
        if not quiet:
            app.toast(f"Гру збережено: {path}")
        return path

    def answered(self, app, kind: str) -> None:
        if kind == "reflect":
            self.save(app, quiet=True)  # autosave once per day, like Tau-7


class Campaign:
    """The whole game in one window: Tau-7 until a rescue writes a legacy, then the
    city with that legacy. A death retries the same chapter; paying off the debt
    finishes the campaign and a new one begins on a fresh planet."""

    def __init__(self, tau7: Tau7Chapter, tau7_brain, city_brain, city: Callable) -> None:
        self.tau7, self.tau7_brain = tau7, tau7_brain
        self.city_brain = city_brain
        self.city = city  # Legacy -> CityChapter

    def hint(self, app) -> str:
        if app.chapter is self.tau7:
            return f"Глава 2 «{CHAPTER2_TITLE}»" if ready_for_chapter2(app.sim) else "Нова капсула"
        return "Нова кампанія на Тау-7" if app.sim.world.hero.free else "Нове місто"

    def advance(self, app) -> None:
        sim = app.sim
        if app.chapter is self.tau7:
            if ready_for_chapter2(sim):
                from ..cyberpunk.legacy import import_legacy

                if app.eventlog:
                    app.eventlog.meta(f"кампанія: глава 2 «{CHAPTER2_TITLE}», спадок {sim.legacy_path}")
                app.switch(self.city(import_legacy(sim.legacy_path)), self.city_brain, new_seed=False)
            else:
                app.new_world()
        elif sim.world.hero.free:
            if app.eventlog:
                app.eventlog.meta("кампанію завершено: борг погашено; нова кампанія")
                app.eventlog.close()
                app.eventlog = None
            app.switch(self.tau7, self.tau7_brain, new_seed=True)
        else:
            app.new_world()


# --- the app ---------------------------------------------------------------------------


class GfxApp:
    def __init__(self, chapter, brain, seed: int, speed: int = 1, sprites_dir: Path | str | None = None,
                 size: tuple[int, int] = (1360, 820), zoom: int = 3, loaded=None, headless: bool = False,
                 fullscreen: bool = False, view: str = "2d", campaign: Campaign | None = None) -> None:
        if headless:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        pygame.display.init()
        pygame.font.init()
        flags = 0 if headless else pygame.RESIZABLE | (pygame.FULLSCREEN if fullscreen else 0)
        self.screen = pygame.display.set_mode(size, flags)
        pygame.display.set_caption(chapter.title)
        pygame.key.set_repeat(300, 60)
        self.chapter = chapter
        self.brain = brain
        self.seed = seed
        self.headless = headless
        self.bank = SpriteBank(overrides=sprites_dir)
        self.renderer = Renderer(self.bank)
        self.scene = chapter.scene(self.renderer)
        self.speed_idx = speed_index(speed)
        self.zoom = zoom if zoom in ZOOMS else 3
        self.view = view if view in PROJECTIONS else "2d"
        self.paused = False
        self.god_view = False
        self.show_minimap = True
        self.show_panel = True
        self.overlay: str | None = None  # "diary" | "help"
        self.scroll = 0
        self.thinking_since: float | None = None
        self.thinking_kind = "decide"
        self.ended_at: float | None = None
        self.generation = 0
        self.results: queue.Queue = queue.Queue()
        self.events: deque = deque(maxlen=300)
        self.toasts: list[tuple[str, float]] = []
        self.acc = 0.0
        self.cam: list[float] | None = None
        self.t0 = time.monotonic()
        self.now = 0.0
        self.running = True
        self.minimap_colors = chapter.minimap_color
        self.campaign = campaign
        self.eventlog: EventLog | None = None
        if loaded is not None:
            self.sim = loaded
            self.seed = loaded.world.seed
            chapter.adopt(self, loaded)
            self._attach(loaded, resumed=True)
        else:
            self.sim = self._new_sim(seed)
        self._set_icon()

    # --- lifecycle -------------------------------------------------------------------
    def _attach(self, sim, resumed: bool = False) -> None:
        sim.world.listeners.append(self._on_event)
        self.generation += 1
        self.events.clear()
        for ev in sim.world.events[-60:]:
            self.events.append(ev)
        # the journal: one file per world, or one for the whole campaign
        log_dir = getattr(self.chapter, "diary_dir", None)
        if self.eventlog is None or self.campaign is None:
            if self.eventlog:
                self.eventlog.close()
            self.eventlog = EventLog.for_game(log_dir, self.brain.name, sim.world.seed, self.chapter.log_kind, sim=sim)
        if self.eventlog:
            self.eventlog.attach(sim, self.chapter.log_title, self.brain.label, resumed)

    def _new_sim(self, seed: int):
        sim = self.chapter.new_sim(self, seed)
        self._attach(sim)
        return sim

    def new_world(self) -> None:
        self.seed += 1
        self.ended_at = None
        self.thinking_since = None
        self.sim = self._new_sim(self.seed)
        self.cam = None
        self.scene.reset()

    def switch(self, chapter, brain, new_seed: bool = False) -> None:
        """Continue in another chapter (the campaign), in the same window."""
        self.chapter = chapter
        self.brain = brain
        if new_seed:
            self.seed += 1
        self.scene = chapter.scene(self.renderer)
        self.minimap_colors = chapter.minimap_color
        self.ended_at = None
        self.thinking_since = None
        self.cam = None
        self.sim = self._new_sim(self.seed)
        pygame.display.set_caption(chapter.title)
        self.toast(chapter.title)

    def next_hint(self) -> str | None:
        """What comes after this run's ending (for the end screen)."""
        return self.campaign.hint(self) if self.campaign else None

    def restart_in(self) -> float:
        if self.ended_at is None:
            return RESTART_AFTER
        return RESTART_AFTER - (self.now - self.ended_at)

    def toast(self, text: str) -> None:
        self.toasts.append((text, self.now + 3.0))

    def _on_event(self, ev) -> None:
        self.events.append(ev)
        try:
            self.scene.on_event(ev, self.now, self.sim.world)
        except AttributeError:
            pass

    @property
    def tps(self) -> int:
        return TPS[self.speed_idx]

    def _set_icon(self) -> None:
        for name in ("t7.item.artifact", "t7.hero.idle"):
            if name in self.bank:
                pygame.display.set_icon(self.bank.frame(name, 0, 2))
                return

    # --- brain ---------------------------------------------------------------------------
    def _think(self, kind: str) -> None:
        self.thinking_since = time.monotonic()
        self.thinking_kind = kind
        generation = self.generation
        sim = self.sim
        brain = self.brain
        chapter = self.chapter

        def work() -> None:
            try:
                result = getattr(brain, {"decide": "decide", "reflect": "reflect", "converse": "converse"}[kind])(sim)
            except Exception:  # a brain must never take the window down
                traceback.print_exc(file=sys.stderr)
                result = getattr(chapter.fallback_brain(), kind)(sim)
            self.results.put((kind, result, generation))

        if self.headless:
            work()
        else:
            threading.Thread(target=work, daemon=True, name=f"brain-{kind}").start()

    def _drain(self) -> None:
        while True:
            try:
                kind, result, generation = self.results.get_nowait()
            except queue.Empty:
                return
            self.thinking_since = None
            if generation != self.generation:
                continue  # the world was replaced while thinking
            if kind == "decide":
                self.sim.apply(result)
            elif kind == "reflect":
                self.sim.apply_reflection(result)
            else:
                self.sim.apply_conversation(result)
            self.chapter.answered(self, kind)

    # --- loop ------------------------------------------------------------------------------
    def update(self, dt: float) -> None:
        self.now = time.monotonic() - self.t0
        self._drain()
        sim = self.sim
        if sim.over:
            if self.eventlog:
                self.eventlog.check_end()
            if self.ended_at is None:
                self.ended_at = self.now
            elif self.now - self.ended_at > RESTART_AFTER and not self.paused:
                if self.campaign:
                    self.campaign.advance(self)
                else:
                    self.new_world()
                return
        elif not self.paused and self.thinking_since is None:
            if sim.pending:
                self._think(sim.pending)
                self._drain()
            else:
                self.acc += dt * self.tps * self.chapter.tick_multiplier(sim)
                n = min(int(self.acc), 4000)
                self.acc -= n
                for _ in range(n):
                    sim.tick()
                    if sim.pending or sim.over:
                        self.acc = 0.0
                        break
        self.scene.actors.set_speed(self.tps * self.chapter.tick_multiplier(sim))
        self.scene.update(sim, self.now, dt, self.thinking_since is not None, self._world_area())
        self._camera(dt)

    @property
    def proj(self):
        return PROJECTIONS[self.view]

    def _world_area(self) -> pygame.Rect:
        """World px rectangle around what the camera sees (weather is emitted there)."""
        view = self.map_rect()
        cw, ch = self.renderer.canvas_size(view, self.zoom)
        cx, cy = self.cam if self.cam else self.proj.to_view(*self.scene.hero_point(self.sim, self.now))
        tx0, ty0, tx1, ty1 = self.proj.tiles_in(cx - cw / 2, cy - ch / 2, cw, ch, margin=1, below=1)
        return pygame.Rect(tx0 * TILE, ty0 * TILE, (tx1 - tx0 + 1) * TILE, (ty1 - ty0 + 1) * TILE)

    def toggle_view(self) -> None:
        self.view = "iso" if self.view == "2d" else "2d"
        self.cam = None
        self.renderer.particles.clear()
        self.toast("Вид: " + ("ізометрія 2.5D" if self.view == "iso" else "2D, 3/4 зверху"))

    def map_rect(self) -> pygame.Rect:
        w, h = self.screen.get_size()
        return pygame.Rect(0, 0, w - (PANEL_W if self.show_panel else 0), h)

    def _camera(self, dt: float) -> None:
        tx, ty = self.proj.to_view(*self.scene.hero_point(self.sim, self.now))
        if self.cam is None:
            self.cam = [tx, ty]
        else:
            k = 1 - math.exp(-dt * 7)
            self.cam[0] += (tx - self.cam[0]) * k
            self.cam[1] += (ty - self.cam[1]) * k
        level = self.sim.world.level
        view = self.map_rect()
        cw, ch = view.width / self.zoom, view.height / self.zoom
        x0, y0, x1, y1 = self.proj.bounds(level.width, level.height)
        for i, (size, lo, hi) in enumerate(((cw, x0, x1), (ch, y0, y1))):
            if hi - lo <= size:
                self.cam[i] = (lo + hi) / 2
            else:
                self.cam[i] = max(lo + size / 2, min(hi - size / 2, self.cam[i]))

    def draw(self) -> None:
        screen = self.screen
        screen.fill((8, 7, 14))
        view = self.map_rect()
        cx, cy = self.cam or (0.0, 0.0)
        shake = getattr(self.scene, "shake_until", 0) > self.now
        if shake:
            cx += random.uniform(-2, 2)
            cy += random.uniform(-2, 2)
        cw, ch = self.renderer.canvas_size(view, self.zoom)
        frame = self.renderer.frame(cx - (cw - 1) / 2, cy - (ch - 1) / 2, view, self.zoom, self.now, self.proj)
        self.scene.build(self.sim, frame, self.god_view)
        self.renderer.draw(frame, screen, view, self.scene.weather(self.sim))
        fade = getattr(self.scene, "fade_until", 0) - self.now
        if fade > 0:
            veil = pygame.Surface(view.size)
            veil.fill((0, 0, 0))
            veil.set_alpha(int(255 * min(1.0, fade / 0.5)))
            screen.blit(veil, view.topleft)
        self.chapter.overlays(self, screen, view, self.now)
        if self.show_panel:
            rect = pygame.Rect(view.right, 0, PANEL_W, screen.get_height())
            y = self.chapter.status(self, screen, rect, self.now)
            log = pygame.Rect(rect.x + 2, y + 4, rect.width - 4, rect.bottom - y - 6)
            if log.height > 60:
                title = txt.render("ЖУРНАЛ", "pixel", 16, hud.TITLE, shadow=(0, 0, 0))
                screen.blit(title, (log.x + 8, log.y))
                pygame.draw.line(screen, hud.EDGE, (log.x + 8, log.y + 20), (log.right - 8, log.y + 20))
                hud.draw_log(screen, self.bank, pygame.Rect(log.x, log.y + 24, log.width, log.height - 26),
                             list(self.events), self.now)
        if self.overlay == "diary":
            title, blocks = self.chapter.diary(self)
            self.max_scroll = hud.text_overlay(screen, title, blocks, self.scroll, "Esc / d - закрити · ↑↓ гортати")
        elif self.overlay == "help":
            hud.text_overlay(screen, "Wilds - довідка", [(t, hud.TEXT, f) for t, f in HELP], 0, "Esc - закрити")
        self.toasts = [(m, until) for m, until in self.toasts if until > self.now]
        for i, (msg, _) in enumerate(self.toasts[-3:]):
            surf = txt.render(msg, "text", 16, hud.TEXT)
            r = pygame.Rect(view.centerx - surf.get_width() // 2 - 12, view.bottom - 90 - i * 40,
                            surf.get_width() + 24, 32)
            hud.frame_rect(screen, r)
            screen.blit(surf, (r.x + 12, r.y + 7))

    # --- input -------------------------------------------------------------------------------
    def handle(self, event) -> None:
        if event.type == pygame.QUIT:
            self.quit()
        elif event.type == pygame.MOUSEWHEEL:
            if self.overlay == "diary":
                self.scroll = max(0, self.scroll - event.y * 3)
            else:
                self._zoom(1 if event.y > 0 else -1)
        elif event.type == pygame.KEYDOWN:
            key, uni = event.key, event.unicode
            if self.overlay and key in (pygame.K_ESCAPE,):
                self.overlay = None
            elif self.overlay == "diary" and key in (pygame.K_UP, pygame.K_DOWN, pygame.K_PAGEUP, pygame.K_PAGEDOWN):
                step = {pygame.K_UP: -1, pygame.K_DOWN: 1, pygame.K_PAGEUP: -10, pygame.K_PAGEDOWN: 10}[key]
                self.scroll = max(0, min(getattr(self, "max_scroll", 0), self.scroll + step))
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
            elif key == pygame.K_g:
                self.god_view = not self.god_view
            elif key == pygame.K_i:
                self.toggle_view()
            elif key == pygame.K_m:
                self.show_minimap = not self.show_minimap
            elif key == pygame.K_TAB:
                self.show_panel = not self.show_panel
            elif key == pygame.K_s:
                self.chapter.save(self)
            elif key == pygame.K_n:
                self.new_world()
            elif key == pygame.K_F11:
                pygame.display.toggle_fullscreen()
            elif key == pygame.K_F12:
                SCREENSHOT_DIR.mkdir(exist_ok=True)
                path = SCREENSHOT_DIR / f"wilds-{self.sim.world.seed}-{int(time.time())}.png"
                pygame.image.save(self.screen, str(path))
                self.toast(f"Скріншот: {path}")
            elif key == pygame.K_q:
                self.quit()

    def _zoom(self, step: int) -> None:
        i = ZOOMS.index(self.zoom) if self.zoom in ZOOMS else 2
        self.zoom = ZOOMS[max(0, min(len(ZOOMS) - 1, i + step))]

    def quit(self) -> None:
        self.chapter.save(self, quiet=True)
        if self.eventlog:
            self.eventlog.close()
        self.running = False

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
            print("sprites missing (drawn as placeholders):", ", ".join(sorted(self.renderer.missing)),
                  file=sys.stderr)
        pygame.quit()

    def shot(self, path: Path | str, frames: int = 45, dt: float = 1 / 30) -> Path:
        """Render a few frames without a window (animations settle) and save a PNG."""
        for _ in range(frames):
            self.update(dt)
            self.t0 -= dt  # advance the clock deterministically
        self.draw()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(self.screen, str(path))
        return path
