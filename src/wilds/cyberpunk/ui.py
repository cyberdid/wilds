"""Terminal UI for the cyberpunk chapter: same live-aquarium idea as Tau-7's,
adapted to a city block with people instead of a wilderness with fauna."""

from __future__ import annotations

import time
from typing import Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, RichLog, Static

from ..world import Event
from .items import ITEMS
from .sim import Brain, CitySim
from .world import CityWorld

SPEEDS = [1, 2, 5, 10, 20, 40, 80]
FPS = 20
RESTART_AFTER = 20.0
EVENT_STYLE = {
    "info": "grey70", "danger": "bold red", "good": "green", "brain": "italic cyan",
    "death": "bold white on red", "event": "bold magenta", "diary": "italic yellow",
    "talk": "bright_cyan", "victory": "bold black on green",
}
PREFIX = {"brain": "💭 ", "diary": "📔 ", "event": "⚠ ", "talk": "🗨 "}
THINKING = {"decide": "думає", "reflect": "пише щоденник", "converse": "розмовляє"}


class MapView(Static):
    def __init__(self, app_ref: "CyberApp", **kw) -> None:
        super().__init__(**kw)
        self.app_ref = app_ref

    def render_map(self) -> Text:
        sim = self.app_ref.sim
        world = sim.world
        hero = world.hero
        level = world.level
        god = self.app_ref.god_view
        npcs = {n.pos: n for n in level.npcs}
        width = max(10, self.size.width or 80)
        height = max(5, self.size.height or 30)
        x0 = min(max(hero.pos[0] - width // 2, 0), max(level.width - width, 0))
        y0 = min(max(hero.pos[1] - height // 2, 0), max(level.height - height, 0))

        text = Text()
        chars: list[str] = []
        style: str | None = None

        def put(ch: str, sty: str) -> None:
            nonlocal style
            if sty != style and chars:
                text.append("".join(chars), style)
                chars.clear()
            style = sty
            chars.append(ch)

        for y in range(y0, min(y0 + height, level.height)):
            for x in range(x0, min(x0 + width, level.width)):
                p = (x, y)
                lit = god or p in hero.visible
                if p == hero.pos and not sim.over:
                    put("@", "bold yellow")
                elif lit and p in npcs:
                    put("N", "bold bright_cyan")
                elif lit:
                    tile = level.tile(p)
                    put(tile.glyph, tile.color)
                elif p in hero.known():
                    put(hero.known()[p].glyph, "grey35")
                else:
                    put(" ", "")
            put("\n", "")
        if chars:
            text.append("".join(chars), style)
        return text

    def refresh_map(self) -> None:
        self.update(self.render_map())


def _bar(value: float, maxv: float, width: int = 14) -> Text:
    filled = round(max(0.0, min(1.0, value / maxv)) * width)
    color = "green" if value / maxv > 0.6 else "yellow" if value / maxv > 0.3 else "red"
    t = Text("█" * filled, style=color)
    t.append("░" * (width - filled), style="grey30")
    t.append(f" {value:.0f}")
    return t


class DiaryScreen(ModalScreen):
    BINDINGS = [Binding("escape,d,q", "app.pop_screen", "Закрити")]
    CSS = """
    DiaryScreen { align: center middle; }
    #diary { width: 90; max-width: 95%; height: 85%; border: round $warning; background: $surface; padding: 1 2; }
    """

    def __init__(self, app_ref: "CyberApp") -> None:
        super().__init__()
        self.app_ref = app_ref
        self._shown: tuple | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="diary"):
            yield Static(self._text(), id="diary-text")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._refresh)

    def _state(self) -> tuple:
        hero = self.app_ref.sim.world.hero
        return (id(hero), len(hero.diary), tuple(hero.traits), hero.goal)

    def _refresh(self) -> None:
        if self._state() != self._shown:
            self.query_one("#diary-text", Static).update(self._text())

    def _text(self) -> Text:
        self._shown = self._state()
        hero = self.app_ref.sim.world.hero
        t = Text()
        t.append(f"Щоденник: {hero.name} ({hero.race.label})\n\n", style="bold yellow")
        if hero.traits:
            t.append("Риси: " + "; ".join(hero.traits) + "\n", style="cyan")
        if hero.goal:
            t.append(f"Мета: {hero.goal}\n", style="bold")
        t.append("\n")
        if not hero.diary:
            t.append("Ще жодного запису. Перший з'явиться опівночі.\n\n", style="grey50")
        for day, entry in reversed(hero.diary):
            t.append(f"День {day}\n", style="bold magenta")
            t.append(entry + "\n\n", style="italic")
        t.append("Esc / d — закрити", style="grey50")
        return t


class CyberApp(App):
    CSS = """
    Screen { layout: vertical; }
    #main { height: 1fr; }
    #map { width: 1fr; height: 1fr; border: round $primary; padding: 0; }
    #side { width: 48; }
    #status { height: auto; border: round $secondary; padding: 0 1; }
    #mind { height: auto; min-height: 6; border: round $accent; padding: 0 1; }
    #log { height: 1fr; border: round $secondary; }
    """
    BINDINGS = [
        Binding("space", "pause", "Пауза"),
        Binding("plus,equals_sign", "faster", "Швидше"),
        Binding("minus", "slower", "Повільніше"),
        Binding("d", "diary", "Щоденник"),
        Binding("g", "god", "Око бога"),
        Binding("q", "quit", "Вихід"),
    ]

    def __init__(self, make_world: Callable[[int], CityWorld], brain: Brain, seed: int, speed: int = 1,
                 diary_dir=None) -> None:
        super().__init__()
        self.make_world = make_world
        self.brain = brain
        self.seed = seed
        self.diary_dir = diary_dir
        self.speed_idx = max(0, min(len(SPEEDS) - 1, speed))
        self.paused = False
        self.god_view = False
        self.thinking_since: float | None = None
        self.thinking_kind = "decide"
        self.ended_at: float | None = None
        self.generation = 0
        self.sim = self._new_sim(seed)

    def _new_sim(self, seed: int) -> CitySim:
        world = self.make_world(seed)
        world.listeners.append(self._on_event)
        self.generation += 1
        sim = CitySim(world)
        if self.diary_dir:
            self.diary_dir.mkdir(parents=True, exist_ok=True)
            sim.diary_path = self.diary_dir / f"diary-cyberpunk-{self.brain.name}-{seed}.md"
        return sim

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            yield MapView(self, id="map")
            with Vertical(id="side"):
                yield Static(id="status")
                yield Static(id="mind")
                yield RichLog(id="log", wrap=True, markup=False, max_lines=400)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Wilds: Тінемісто"
        # border_title is refreshed per-frame in _render() with the current district
        self.query_one("#status").border_title = "Раннер"
        self.query_one("#mind").border_title = "Думки"
        self.query_one("#log").border_title = "Журнал"
        self._intro()
        self.set_interval(1 / FPS, self._frame)

    def _intro(self) -> None:
        log = self.query_one("#log", RichLog)
        self._write(log, Text(f"— Місто #{self.sim.world.seed}, мозок: {self.brain.label} —", style="bold"))
        for ev in self.sim.world.events:
            self._on_event(ev)

    @staticmethod
    def _write(log: RichLog, line: Text) -> None:
        width = log.scrollable_content_region.width
        log.write(line, width=width if width > 10 else 40)

    def _on_event(self, ev: Event) -> None:
        try:
            log = self.query_one("#log", RichLog)
        except Exception:
            return
        hh, mm = ev.tick // 60 % 24, ev.tick % 60
        line = Text(f"{hh:02d}:{mm:02d} ", style="grey50")
        line.append(PREFIX.get(ev.kind, "") + ev.text, style=EVENT_STYLE.get(ev.kind, ""))
        self._write(log, line)

    def _frame(self) -> None:
        sim = self.sim
        if sim.over:
            if self.ended_at is None:
                self.ended_at = time.monotonic()
            elif time.monotonic() - self.ended_at > RESTART_AFTER and not self.paused:
                self.action_new_world()
                return
        elif not self.paused and self.thinking_since is None:
            if sim.pending:
                self._think(sim.pending)
            else:
                for _ in range(SPEEDS[self.speed_idx]):
                    sim.tick()
                    if sim.pending or sim.over:
                        break
        self._render()

    def _think(self, kind: str) -> None:
        self.thinking_since = time.monotonic()
        self.thinking_kind = kind
        generation = self.generation
        sim = self.sim
        call = {"decide": self.brain.decide, "reflect": self.brain.reflect, "converse": self.brain.converse}[kind]

        def work() -> None:
            result = call(sim)
            self.call_from_thread(self._answered, kind, result, generation)

        self.run_worker(work, thread=True, exclusive=True, group="brain")

    def _answered(self, kind: str, result, generation: int) -> None:
        self.thinking_since = None
        if generation != self.generation:
            return
        if kind == "decide":
            self.sim.apply(result)
        elif kind == "reflect":
            self.sim.apply_reflection(result)
        else:
            self.sim.apply_conversation(result)

    def _render(self) -> None:
        self.query_one("#map", MapView).refresh_map()
        self.query_one("#status", Static).update(self._status_text())
        self.query_one("#mind", Static).update(self._mind_text())
        state = "ПАУЗА" if self.paused else f"x{SPEEDS[self.speed_idx]}"
        self.query_one("#map").border_title = self.sim.world.level.name
        self.query_one("#map").border_subtitle = f"{state} · seed {self.sim.world.seed}"

    def _status_text(self) -> Text:
        world = self.sim.world
        hero = world.hero
        t = Text()
        icon = "☾" if world.is_night else "☀"
        t.append(f"{world.clock()} {icon}\n", style="bold")
        t.append(f"{hero.race.label:<9}", style="bold")
        t.append("здоров'я ")
        t.append_text(_bar(hero.hp, 100))
        t.append("\n")
        t.append("есенс    ")
        t.append_text(_bar(hero.essence, 10))
        t.append("\n")
        t.append(f"нуєни: {hero.nuyen}¥   борг: {hero.debt}¥\n", style="bright_yellow")
        heat = world.level.heat
        heat_style = "red" if heat > 65 else "yellow" if heat > 30 else "grey70"
        t.append(f"теплота району: {heat:.0f}/100", style=heat_style)
        if world.delinquent:
            t.append("  ⚠ прострочений внесок", style="bold red")
        if hero.evicted:
            t.append("  виселення", style="bold red")
        t.append("\n")
        if world.ship is not None:
            t.append(f"корабель: паливо {world.ship.fuel:.0f}  корпус {world.ship.hull:.0f}\n", style="cyan")
        if hero.reputation:
            from .factions import FACTION_NAMES
            rep = "  ".join(f"{FACTION_NAMES.get(f, f)} {v:+.2f}" for f, v in hero.reputation.items())
            t.append(f"репутація: {rep}\n", style="magenta")
        inv = ", ".join(f"{ITEMS[k].name}×{v}" for k, v in sorted(hero.inventory.items()) if v > 0)
        t.append(f"Речі: {inv or 'нічого'}\n", style="grey70")
        if world.contract is not None and world.contract.status != "done":
            t.append(f"Контракт: {world.contract.status}", style="cyan")
        return t

    def _mind_text(self) -> Text:
        sim = self.sim
        hero = sim.world.hero
        t = Text()
        if sim.over:
            left = RESTART_AFTER - (time.monotonic() - (self.ended_at or time.monotonic()))
            if hero.free:
                t.append(f"🎉 {hero.name} розрахувався з боргом!\n", style="bold green")
            else:
                t.append(f"† {hero.name} вибув ({hero.cause_of_death}).\n", style="bold red")
            t.append(f"Нове місто через {max(0, left):.0f} с (d — щоденник)", style="grey70")
            return t
        if hero.goal:
            t.append(f"Мета: {hero.goal}\n", style="bold")
        if sim.thought:
            t.append(f"«{sim.thought}»\n", style="italic cyan")
        if self.thinking_since is not None:
            dots = "." * (1 + int(time.monotonic() * 2) % 3)
            t.append(f"{THINKING.get(self.thinking_kind, 'думає')}{dots} "
                     f"{time.monotonic() - self.thinking_since:.0f}с", style="yellow")
        elif sim.action:
            t.append(f"→ {sim.action.label()}", style="bold")
        calls = getattr(self.brain, "calls", sim.decisions)
        errors = getattr(self.brain, "errors", 0)
        t.append(f"\nрішень: {sim.decisions}  викликів ШІ: {calls}  помилок: {errors}", style="grey50")
        return t

    def action_pause(self) -> None:
        self.paused = not self.paused

    def action_faster(self) -> None:
        self.speed_idx = min(self.speed_idx + 1, len(SPEEDS) - 1)

    def action_slower(self) -> None:
        self.speed_idx = max(self.speed_idx - 1, 0)

    def action_god(self) -> None:
        self.god_view = not self.god_view

    def action_diary(self) -> None:
        self.push_screen(DiaryScreen(self))

    def action_new_world(self) -> None:
        self.seed += 1
        self.ended_at = None
        self.thinking_since = None
        self.sim = self._new_sim(self.seed)
        self.query_one("#log", RichLog).clear()
        self._intro()
