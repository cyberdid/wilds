"""Tau-7 HUD content: the same information as the terminal UI's status/mind
panels, drawn with sprite icons, bars and item grids."""

from __future__ import annotations

import time

import pygame

from ..actions import visible_creatures
from ..hero import NEED_NAMES, NEEDS
from ..pod import BEACON_PARTS
from . import hud
from . import text as txt
from .hud import CYAN, DIM, GOOD, MAGENTA, TEXT, WARN, Layout

PHASE_ICON = {"затишшя": "ui.phase.calm", "наростання": "ui.phase.rising", "пік": "ui.phase.peak",
              "перепочинок": "ui.phase.relief"}
PHASE_COLOR = {"затишшя": (150, 150, 180), "наростання": WARN, "пік": (255, 90, 90), "перепочинок": GOOD}
THINKING = {"decide": "думає", "reflect": "пише щоденник", "converse": "розмовляє"}


def status(app, screen: pygame.Surface, rect: pygame.Rect, t: float) -> int:
    """Draws the status + mind panel; returns the y where the log may start."""
    bank = app.bank
    sim = app.sim
    world = sim.world
    hero = world.hero
    hud.frame_rect(screen, rect)
    L = Layout(screen, bank, rect, t)
    L.title(world.clock(), "ui.night" if world.is_night else "ui.day")
    director = world.director
    if director:
        phase = director.phase(world.tick)
        L.bar(PHASE_ICON.get(phase, "ui.tension"), phase, director.tension * 100, 100,
              color=PHASE_COLOR.get(phase), text=f"{director.tension:.2f}")
    # portrait + vitals
    top = L.y
    portrait = "t7.hero.portrait"
    if portrait in bank:
        surf = bank.frame(portrait, t, 3)
        pygame.draw.rect(screen, (10, 9, 18), (L.x, top, surf.get_width() + 4, surf.get_height() + 4))
        screen.blit(surf, (L.x + 2, top + 2))
        name = txt.render(hero.name, "pixel", 14, TEXT)
        screen.blit(name, (L.x + 2, top + surf.get_height() + 8))
        inner = pygame.Rect(L.x + surf.get_width() + 14, top, L.w - surf.get_width() - 14, 0)
        L2 = Layout(screen, bank, pygame.Rect(inner.x - 10, top - 10, inner.width + 20, 400), t)
        L2.bar("ui.hp", NEED_NAMES["hp"], hero.hp)
        for n in NEEDS:
            L2.bar(f"ui.{n}", NEED_NAMES[n], hero.need(n))
        L.y = max(L2.y, top + surf.get_height() + 26) + 2
    else:
        L.bar("ui.hp", NEED_NAMES["hp"], hero.hp)
        for n in NEEDS:
            L.bar(f"ui.{n}", NEED_NAMES[n], hero.need(n))
    light = ("ліхтар" if hero.inventory["headlamp"] else
             f"фальшфеєр {hero.flare_ticks}хв" if hero.flare_ticks else "—")
    L.line(f"{hero.weapon_name} ({hero.attack_power})", icon="ui.weapon", right=light)
    items = [(f"t7.item.{k}", v) for k, v in sorted(hero.inventory.items()) if v > 0]
    if items:
        L.item_grid(items)
    else:
        L.line("Речі: нічого", DIM)
    pod = world.pod
    if pod:
        L.space(2)
        L.bar("ui.power", "капсула", pod.power, 100, color=(120, 220, 255))
        heat = "обігрів ON" if pod.heating else "обігрів off"
        if pod.fault:
            L.line("ЗБІЙ! потрібна руда для ремонту", (255, 110, 110), icon="ui.fault")
        if pod.rescue_at is not None:
            left = max(0, pod.rescue_at - world.tick)
            L.line(f"шатл через {left // 60} год {left % 60:02d} хв", GOOD, icon="ui.shuttle", right=heat)
        elif pod.beacon_repaired:
            L.line("маяк готовий: треба 80 енергії", CYAN, icon="ui.beacon", right=heat)
        else:
            _beacon_parts(L, hero, t, heat)
    comp = world.companion
    if comp:
        if comp.alive:
            L.line(f"{comp.name}: {comp.activity}", MAGENTA, icon="ui.companion", right=f"{comp.trust:.2f}")
        else:
            L.line(f"{comp.name} загинула ({comp.cause_of_death})", DIM, icon="ui.skull")
    threats = sorted({c.name for c in visible_creatures(world) if c.kind.hostile})
    if threats:
        L.line("Поруч: " + ", ".join(threats), (255, 110, 110), icon="ui.threat")
    # mind
    L.space(4)
    L.title("Думки", "ui.brain", color=CYAN)
    if hero.goal:
        L.line(f"Мета: {hero.goal}", TEXT, face="bold", icon="ui.goal")
    if sim.thought:
        L.para(f"«{sim.thought}»", (150, 226, 240), max_lines=4)
    if app.thinking_since is not None:
        dots = "." * (1 + int(time.monotonic() * 2) % 3)
        what = THINKING.get(app.thinking_kind, "думає")
        L.line(f"{what}{dots} {time.monotonic() - app.thinking_since:.0f}с", WARN, icon="ui.thought")
    elif sim.action:
        L.para(f"→ {sim.action.label()}", TEXT, face="bold", max_lines=2)
    calls = getattr(app.brain, "calls", sim.decisions)
    errors = getattr(app.brain, "errors", 0)
    L.line(f"рішень {sim.decisions} · викликів ШІ {calls} · помилок {errors}", DIM, face="pixel", size=12)
    return L.y


def _beacon_parts(L: Layout, hero, t: float, heat: str) -> None:
    x0 = L.x
    L.icon("ui.beacon", x0, L.y)
    x = x0 + 30
    for key, need in BEACON_PARTS.items():
        have = min(hero.inventory[key], need)
        for i in range(need):
            name = f"t7.item.{key}"
            if name in L.bank:
                surf = L.bank.frame(name, t, 1 if need > 2 else 2)
                if i >= have:
                    surf = L.bank.frame(name, t, 1 if need > 2 else 2, tint="gray").copy()
                    surf.set_alpha(110)
                L.s.blit(surf, (x, L.y + (24 - surf.get_height()) // 2))
                x += surf.get_width() + 2
        x += 8
    rs = txt.render(heat, "pixel", 14, DIM)
    L.s.blit(rs, (L.x + L.w - rs.get_width(), L.y + 5))
    L.y += 28


def overlays(app, screen: pygame.Surface, view: pygame.Rect, t: float) -> None:
    bank = app.bank
    sim = app.sim
    world = sim.world
    level = world.level
    god = " · око бога" if app.god_view else ""
    hud.plate(screen, bank, view.x + 10, view.y + 10,
              [("ui.location", level.name + god)], t)
    director = world.director
    if director:
        text = director.banner(world)
        if text:
            urgent = text.startswith("‼")
            hud.banner(screen, bank, view, text.lstrip("⚠‼ "), "ui.warning", t,
                       color=(255, 110, 110) if urgent else WARN, urgent=urgent)
    speed = "ПАУЗА" if app.paused else f"x{app.tps} т/с"
    hud.plate(screen, bank, view.x + 10, view.bottom - 44,
              [("ui.pause" if app.paused else "ui.speed", speed), (None, f"seed {world.seed}"),
               (None, f"zoom {app.zoom}"), (None, app.proj.name)], t, color=DIM)
    if app.show_minimap:
        _minimap(app, screen, view, t)
    if sim.over:
        _ending(app, screen, view, t)


def _minimap(app, screen, view, t) -> None:
    world = app.sim.world
    level = world.level
    hero = world.hero
    known = hero.known(level.id)
    colors = app.minimap_colors

    def color_at(x, y):
        p = (x, y)
        tile = level.tile(p) if (app.god_view or p in hero.visible) else known.get(p)
        if tile is None:
            return None
        c = colors(tile, level.id)
        if not (app.god_view or p in hero.visible):
            c = tuple(v // 2 for v in c)
        return c

    markers = []
    if world.pod and world.pod.level_id == level.id:
        markers.append((*world.pod.pos, (255, 255, 255), False))
    comp = world.companion
    if comp and comp.alive and level.id == "surface" and (comp.pos in known or app.god_view):
        markers.append((*comp.pos, (240, 110, 255), False))
    for c in level.creatures:
        if c.hp > 0 and c.kind.hostile and (app.god_view or c.pos in hero.visible):
            markers.append((*c.pos, (255, 70, 70), False))
    markers.append((*hero.pos, (255, 230, 80), True))
    rect = pygame.Rect(view.right - 250, view.y + 10, 240, 160)
    hud.draw_minimap(screen, rect, level.width, level.height, color_at, markers, t)


def _ending(app, screen, view, t) -> None:
    sim = app.sim
    hero = sim.world.hero
    left = max(0, app.restart_in())
    if hero.rescued:
        title, color, icon = f"{hero.name} врятований!", GOOD, "ui.shuttle"
    else:
        title, color, icon = f"{hero.name} загинув ({hero.cause_of_death})", (255, 110, 110), "ui.skull"
    lines = [f"Прожито до: {sim.world.clock()}",
             f"Артефактів: {hero.inventory['artifact']} · записів у щоденнику: {len(hero.diary)}",
             f"{app.next_hint() or 'Нова капсула'} через {left:.0f} с  (N - нова планета, D - щоденник)"]
    box = pygame.Rect(view.centerx - 300, view.centery - 80, 600, 150)
    hud.frame_rect(screen, box, bg=(14, 12, 22), edge=color)
    x = box.x + 20
    if icon in app.bank:
        screen.blit(app.bank.frame(icon, t, 3), (x, box.y + 18))
        x += 50
    screen.blit(txt.render(title, "bold", 24, color, shadow=(0, 0, 0)), (x, box.y + 18))
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
        blocks.append(("Ще жодного запису. Перший з'явиться опівночі, наприкінці першого солу.", DIM, "text"))
    for sol, entry in reversed(hero.diary):
        blocks.append((f"Сол {sol}", MAGENTA, "bold"))
        blocks.append((entry, TEXT, "text"))
        blocks.append(("", TEXT, "text"))
    return f"Щоденник: {hero.name}", blocks
