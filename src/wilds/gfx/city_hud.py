"""City HUD content and the travel / launch cutscenes."""

from __future__ import annotations

import math
import time

import pygame

from ..cyberpunk.actions import Launch, Travel
from ..cyberpunk.factions import FACTION_NAMES
from ..cyberpunk.hero import MAX_ESSENCE
from ..cyberpunk.items import ITEMS
from ..cyberpunk.ship import LAUNCH_MINUTES, MAX_FUEL, MAX_HULL
from ..cyberpunk.actions import TRAVEL_MINUTES
from . import hud
from . import text as txt
from .hud import CYAN, DIM, GOOD, MAGENTA, TEXT, WARN, Layout
from .mapping import cp_hero

THINKING = {"decide": "думає", "reflect": "пише щоденник", "converse": "розмовляє"}
FACTION_ICON = {"fixers": "ui.rep.fixers", "vendors": "ui.rep.vendors", "gangs": "ui.rep.gangs"}
CONTRACT = {"active": "забрати пакунок", "delivered": "повернутися до фіксера", "done": "виконано"}


def status(app, screen: pygame.Surface, rect: pygame.Rect, t: float) -> int:
    bank = app.bank
    sim = app.sim
    world = sim.world
    hero = world.hero
    level = world.level
    hud.frame_rect(screen, rect)
    L = Layout(screen, bank, rect, t)
    L.title(world.clock(), "ui.night" if world.is_night else "ui.day")
    top = L.y
    race = hero.race.name.lower()
    aug = any(ITEMS[k].cyberware for k, n in hero.inventory.items() if n > 0)
    name = cp_hero(bank.registry, race, "idle", aug) if f"cp.hero.{race}.idle" in bank else None
    if name:
        surf = bank.frame(name, t, 4 if race != "troll" else 3)
        box = pygame.Rect(L.x, top, 72, 76)
        pygame.draw.rect(screen, (10, 9, 18), box)
        pygame.draw.rect(screen, hud.EDGE, box, 1)
        screen.blit(surf, (box.centerx - surf.get_width() // 2, box.bottom - 2 - surf.get_height()))
        L2 = Layout(screen, bank, pygame.Rect(L.x + 72, top - 10, L.w - 62, 300), t)
        L2.line(f"{hero.name} · {hero.race.label}", TEXT, face="bold", size=15)
        L2.bar("ui.hp", "здоров'я", hero.hp)
        L2.bar("ui.essence", "есенс", hero.essence, MAX_ESSENCE, color=(120, 220, 255),
               text=f"{hero.essence:.1f}")
        L.y = max(L2.y, top + 80) + 2
    else:
        L.line(f"{hero.name} · {hero.race.label}", TEXT, face="bold")
        L.bar("ui.hp", "здоров'я", hero.hp)
        L.bar("ui.essence", "есенс", hero.essence, MAX_ESSENCE, color=(120, 220, 255), text=f"{hero.essence:.1f}")
    L.line(f"{hero.nuyen}¥", (255, 226, 110), face="bold", icon="ui.nuyen", right=f"борг {hero.debt}¥",
           right_color=(255, 150, 130) if hero.debt else GOOD)
    L.bar("ui.debt", "борг", min(hero.debt, 5000), 5000, color=(230, 100, 110), text=f"{hero.debt}")
    heat = level.heat
    L.bar("ui.heat", "теплота", heat, 100, color=(255, 90, 80) if heat > 65 else WARN if heat > 30 else (150, 150, 190))
    if world.delinquent:
        L.line("прострочений внесок - шлють колектора", (255, 110, 110), icon="ui.delinquent")
    if hero.evicted:
        L.line("виселення: оренду не сплачено", (255, 110, 110), icon="ui.evicted")
    if world.ship is not None:
        L.bar("ui.fuel", "паливо", world.ship.fuel, MAX_FUEL, color=(255, 170, 80))
        L.bar("ui.hull", "корпус", world.ship.hull, MAX_HULL)
    for faction, value in hero.reputation.items():
        L.bar(FACTION_ICON.get(faction, "ui.race"), FACTION_NAMES.get(faction, faction), value, 1.0,
              text=f"{value:+.2f}", bipolar=True)
    items = [(f"cp.item.{k}", v) for k, v in sorted(hero.inventory.items()) if v > 0]
    if items:
        L.item_grid(items)
    c = world.contract
    if c is not None and c.status != "done":
        L.line(f"Контракт: {CONTRACT.get(c.status, c.status)}", CYAN, icon="ui.contract", right=f"{c.reward}¥")
    L.space(4)
    L.title("Думки", "ui.brain", color=CYAN)
    if hero.goal:
        L.line(f"Мета: {hero.goal}", TEXT, face="bold", icon="ui.goal")
    if sim.thought:
        L.para(f"«{sim.thought}»", (150, 226, 240), max_lines=4)
    if app.thinking_since is not None:
        dots = "." * (1 + int(time.monotonic() * 2) % 3)
        L.line(f"{THINKING.get(app.thinking_kind, 'думає')}{dots} {time.monotonic() - app.thinking_since:.0f}с",
               WARN, icon="ui.thought")
    elif sim.action:
        L.para(f"→ {sim.action.label()}", TEXT, face="bold", max_lines=2)
    calls = getattr(app.brain, "calls", sim.decisions)
    errors = getattr(app.brain, "errors", 0)
    L.line(f"рішень {sim.decisions} · викликів ШІ {calls} · помилок {errors}", DIM, face="pixel", size=12)
    return L.y


def overlays(app, screen: pygame.Surface, view: pygame.Rect, t: float) -> None:
    bank = app.bank
    sim = app.sim
    world = sim.world
    god = " · око бога" if app.god_view else ""
    hud.plate(screen, bank, view.x + 10, view.y + 10, [("ui.location", world.level.name + god)], t)
    speed = "ПАУЗА" if app.paused else f"x{app.tps} т/с"
    hud.plate(screen, bank, view.x + 10, view.bottom - 44,
              [("ui.pause" if app.paused else "ui.speed", speed), (None, f"seed {world.seed}"),
               (None, f"zoom {app.zoom}"), (None, app.proj.name)], t, color=DIM)
    action = sim.action
    if isinstance(action, (Travel, Launch)):
        _cutscene(app, screen, view, t, action)
    elif app.show_minimap:
        _minimap(app, screen, view, t)
    if sim.over:
        _ending(app, screen, view, t)


def _minimap(app, screen, view, t) -> None:
    world = app.sim.world
    level = world.level
    hero = world.hero
    known = hero.known(level.id)

    def color_at(x, y):
        p = (x, y)
        seen = app.god_view or p in hero.visible
        tile = level.tile(p) if seen else known.get(p)
        if tile is None:
            return None
        c = app.minimap_colors(tile, level.id)
        return c if seen else tuple(v // 2 for v in c)

    markers = [(*n.pos, (255, 80, 80) if n.hostile else (110, 240, 255), False) for n in level.npcs
               if app.god_view or n.pos in known]
    if world.contract and world.contract.status == "active" and world.contract.level_id == level.id:
        markers.append((*world.contract.drop_pos, (255, 220, 90), True))
    markers.append((*hero.pos, (255, 230, 80), True))
    rect = pygame.Rect(view.right - 200, view.y + 10, 190, 120)
    hud.draw_minimap(screen, rect, level.width, level.height, color_at, markers, t)


def _cutscene(app, screen, view, t, action) -> None:
    """A maglev ride between districts, or the ship flying past the stars."""
    bank = app.bank
    is_launch = isinstance(action, Launch)
    total = LAUNCH_MINUTES if is_launch else TRAVEL_MINUTES
    k = max(0.0, min(1.0, action.ticks / max(1, total)))
    rect = pygame.Rect(view.x + 40, view.bottom - 230, view.width - 80, 170)
    hud.frame_rect(screen, rect, bg=(8, 7, 16))
    # stars / city lights streaking past
    for i in range(40):
        x = rect.x + (i * 97 + int(t * (240 if is_launch else 160) * (1 + i % 3))) % rect.width
        y = rect.y + 10 + (i * 53) % (rect.height - 20)
        color = (200, 210, 255) if is_launch else ((255, 60, 200) if i % 3 == 0 else (60, 220, 255))
        pygame.draw.line(screen, color, (x, y), (x + (2 if is_launch else 10), y))
    name = "cp.ship" if is_launch else "cp.maglev"
    if name in bank:
        surf = bank.frame(name, t, 4)
        x = rect.x + 20 + int((rect.width - surf.get_width() - 40) * k)
        y = rect.centery - surf.get_height() // 2 + int(math.sin(t * 3) * 2)
        screen.blit(surf, (x, y))
    label = f"{action.label()}  ·  {int(k * 100)}%"
    s = txt.render(txt.clean(label), "bold", 18, TEXT, shadow=(0, 0, 0))
    screen.blit(s, (rect.x + 16, rect.y + 10))
    pygame.draw.rect(screen, (40, 36, 60), (rect.x + 16, rect.bottom - 18, rect.width - 32, 6))
    pygame.draw.rect(screen, CYAN, (rect.x + 16, rect.bottom - 18, int((rect.width - 32) * k), 6))


def _ending(app, screen, view, t) -> None:
    hero = app.sim.world.hero
    left = max(0, app.restart_in())
    if hero.free:
        title, color, icon = f"{hero.name} розрахувався з боргом!", GOOD, "ui.nuyen"
    else:
        title, color, icon = f"{hero.name} вибув ({hero.cause_of_death})", (255, 110, 110), "ui.skull"
    box = pygame.Rect(view.centerx - 300, view.centery - 70, 600, 130)
    hud.frame_rect(screen, box, bg=(14, 12, 22), edge=color)
    x = box.x + 20
    if icon in app.bank:
        screen.blit(app.bank.frame(icon, t, 3), (x, box.y + 18))
        x += 50
    screen.blit(txt.render(title, "bold", 24, color, shadow=(0, 0, 0)), (x, box.y + 18))
    lines = [f"{app.sim.world.clock()} · нуєни {hero.nuyen}¥ · контрактів {hero.contracts_done}",
             f"Нове місто через {left:.0f} с  (N - зараз, D - щоденник)"]
    for i, ln in enumerate(lines):
        screen.blit(txt.render(ln, "text", 16, TEXT), (box.x + 20, box.y + 66 + i * 22))


def diary_blocks(app) -> tuple[str, list]:
    hero = app.sim.world.hero
    blocks = []
    if hero.traits:
        blocks.append(("Риси: " + "; ".join(hero.traits), CYAN, "text"))
    if hero.goal:
        blocks.append((f"Мета: {hero.goal}", TEXT, "bold"))
    blocks.append(("", TEXT, "text"))
    if not hero.diary:
        blocks.append(("Ще жодного запису. Перший з'явиться опівночі.", DIM, "text"))
    for day, entry in reversed(hero.diary):
        blocks.append((f"День {day}", MAGENTA, "bold"))
        blocks.append((entry, TEXT, "text"))
        blocks.append(("", TEXT, "text"))
    return f"Щоденник: {hero.name} ({hero.race.label})", blocks
