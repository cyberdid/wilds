"""Terminal UI: watch the survivor live on Tau-7. Nothing here changes game rules."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, RichLog, Static

from ..actions import visible_creatures
from ..hero import NEED_NAMES, NEEDS
from ..save import SAVE_DIR, save_game, save_path
from ..sim import Brain, Simulation
from ..tiles import Tile
from ..world import ITEMS, Event, World

SPEEDS = [1, 2, 5, 10, 20, 40, 80]  # ticks per frame
FPS = 20
RESTART_AFTER = 20.0  # seconds after the end before a new planet starts
EVENT_STYLE = {
    "info": "grey70",
    "danger": "bold red",
    "good": "green",
    "brain": "italic cyan",
    "death": "bold white on red",
    "event": "bold magenta",
    "diary": "italic yellow",
    "talk": "bright_cyan",
    "victory": "bold black on green",
}
PREFIX = {"brain": "💭 ", "diary": "📔 ", "event": "⚠ ", "talk": "🗨 "}
THINKING = {"decide": "думає", "reflect": "пише щоденник", "converse": "розмовляє"}


def hero_style(hero) -> str:
    """The @ is a live barometer of the survivor's condition."""
    if hero.hp < 30:
        return "bold bright_red" if int(time.monotonic() * 3) % 2 else "bold red"
    if hero.warmth < 30:
        return "bold bright_blue"
    if min(hero.satiety, hero.hydration) < 20:
        return "bold green_yellow"
    return "bold yellow"


class MapView(Static):
    def __init__(self, app_ref: "WildsApp", **kw) -> None:
        super().__init__(**kw)
        self.app_ref = app_ref

    def render_map(self) -> Text:
        sim = self.app_ref.sim
        world = sim.world
        hero = world.hero
        level = world.level
        god = self.app_ref.god_view
        known = hero.known(level.id)
        seen_items = hero.seen_items.get(level.id, {})
        visible = hero.visible
        creatures = {c.pos: c for c in level.creatures if c.hp > 0}
        comp = world.companion
        comp_pos = comp.pos if comp and comp.alive and level.id == "surface" else None

        width = max(10, self.size.width or 80)
        height = max(5, self.size.height or 30)
        x0 = min(max(hero.pos[0] - width // 2, 0), max(level.width - width, 0))
        y0 = min(max(hero.pos[1] - height // 2, 0), max(level.height - height, 0))
        night = world.is_night and not level.dark
        storm = world.director is not None and world.director.storm_active and not level.dark

        text = Text()
        run_chars: list[str] = []
        run_style: str | None = None

        def put(ch: str, style: str) -> None:
            nonlocal run_style
            if style != run_style and run_chars:
                text.append("".join(run_chars), run_style)
                run_chars.clear()
            run_style = style
            run_chars.append(ch)

        for y in range(y0, min(y0 + height, level.height)):
            for x in range(x0, min(x0 + width, level.width)):
                p = (x, y)
                lit = god or p in visible
                if p == hero.pos and not sim.over:
                    style = hero_style(hero)
                    put("@", style + " on grey23" if hero.sleeping else style)
                elif p == comp_pos and (lit or p in known):
                    put("@", "bold magenta")
                elif lit and p in creatures:
                    c = creatures[p]
                    put(c.kind.glyph, f"bold {c.kind.color}")
                elif lit and level.items.get(p):
                    put(ITEMS[level.items[p][0]].glyph, "bold bright_cyan")
                elif lit:
                    tile = level.tile(p)
                    style = tile.color
                    if tile is Tile.HEATER or (tile is Tile.POD and world.pod and world.pod.heating):
                        style = "bold bright_red" if world.tick % 4 < 2 else "bold yellow"
                    elif storm and not god:
                        style = f"{tile.color} on dark_red"
                    elif night and p not in visible:
                        style = f"dim {tile.color}"
                    put(tile.glyph, style)
                elif p in known:
                    if p in seen_items:
                        put(ITEMS[seen_items[p][0]].glyph, "cyan")
                    else:
                        put(known[p].glyph, "grey35")
                else:
                    put(" ", "")
            put("\n", "")
        if run_chars:
            text.append("".join(run_chars), run_style)
        return text

    def refresh_map(self) -> None:
        self.update(self.render_map())


def _bar(value: float, width: int = 14) -> Text:
    filled = round(value / 100 * width)
    color = "green" if value > 60 else "yellow" if value > 30 else "red"
    t = Text("█" * filled, style=color)
    t.append("░" * (width - filled), style="grey30")
    t.append(f" {value:3.0f}")
    return t


class DiaryScreen(ModalScreen):
    """The survivor's diary, traits and goal (key d); refreshes while open."""

    BINDINGS = [Binding("escape,d,q", "app.pop_screen", "Закрити")]
    CSS = """
    DiaryScreen { align: center middle; }
    #diary { width: 90; max-width: 95%; height: 85%; border: round $warning; background: $surface; padding: 1 2; }
    """

    def __init__(self, app_ref: "WildsApp") -> None:
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
        t.append(f"Щоденник: {hero.name}\n\n", style="bold yellow")
        if hero.traits:
            t.append("Риси: " + "; ".join(hero.traits) + "\n", style="cyan")
        if hero.goal:
            t.append(f"Мета: {hero.goal}\n", style="bold")
        t.append("\n")
        if not hero.diary:
            t.append("Ще жодного запису. Перший з'явиться опівночі, наприкінці першого солу.\n\n", style="grey50")
        for sol, entry in reversed(hero.diary):
            t.append(f"Сол {sol}\n", style="bold magenta")
            t.append(entry + "\n\n", style="italic")
        t.append("Esc / d — закрити", style="grey50")
        return t


class WildsApp(App):
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
        Binding("s", "save", "Зберегти"),
        Binding("g", "god", "Око бога"),
        Binding("n", "new_world", "Нова планета"),
        Binding("q", "quit", "Вихід"),
    ]

    def __init__(self, make_world: Callable[[int], World], brain: Brain, seed: int, speed: int = 1,
                 diary_dir: Path | None = None, save_dir: Path | None = SAVE_DIR,
                 legacy_dir: Path | None = None, loaded: Simulation | None = None) -> None:
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
        self.save_dir = save_dir
        self.legacy_dir = legacy_dir
        if loaded is not None:
            self.sim = loaded
            self.seed = loaded.world.seed
            loaded.brain_name = brain.name
            if self.legacy_dir:
                loaded.legacy_dir = self.legacy_dir
            loaded.world.listeners.append(self._on_event)
            self.generation += 1
        else:
            self.sim = self._new_sim(seed)

    # --- setup ------------------------------------------------------------
    def _new_sim(self, seed: int) -> Simulation:
        world = self.make_world(seed)
        world.listeners.append(self._on_event)
        self.generation += 1
        if hasattr(self.brain, "wrecks_done"):
            self.brain.wrecks_done = set()
        fallback = getattr(self.brain, "fallback", None)
        if fallback is not None:
            fallback.wrecks_done = set()
        sim = Simulation(world)
        sim.brain_name = self.brain.name
        if self.diary_dir:
            self.diary_dir.mkdir(parents=True, exist_ok=True)
            sim.diary_path = self.diary_dir / f"diary-{self.brain.name}-{seed}.md"
        if self.legacy_dir:
            sim.legacy_dir = self.legacy_dir
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
        self.title = "Wilds: Тау-7"
        self.query_one("#map").border_title = "Тау-7"
        self.query_one("#status").border_title = "Вцілілий"
        self.query_one("#mind").border_title = "Думки"
        self.query_one("#log").border_title = "Бортовий журнал"
        self._intro()
        self.set_interval(1 / FPS, self._frame)

    def _intro(self) -> None:
        log = self.query_one("#log", RichLog)
        self._write(log, Text(f"— Планета #{self.sim.world.seed}, мозок: {self.brain.label} —", style="bold"))
        for ev in self.sim.world.events:
            self._on_event(ev)

    @staticmethod
    def _write(log: RichLog, line: Text) -> None:
        # RichLog wraps at a default width until laid out; wrap to the real panel width
        width = log.scrollable_content_region.width
        log.write(line, width=width if width > 10 else 40)

    # --- events -------------------------------------------------------------
    def _on_event(self, ev: Event) -> None:
        try:
            log = self.query_one("#log", RichLog)
        except Exception:
            return
        hh, mm = ev.tick // 60 % 24, ev.tick % 60
        line = Text(f"{hh:02d}:{mm:02d} ", style="grey50")
        line.append(PREFIX.get(ev.kind, "") + ev.text, style=EVENT_STYLE.get(ev.kind, ""))
        self._write(log, line)

    # --- loop -------------------------------------------------------------
    def _frame(self) -> None:
        sim = self.sim
        hero = sim.world.hero
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
                ticks = SPEEDS[self.speed_idx]
                if hero.sleeping or (sim.action and sim.action.effective_name in ("rest", "wait")):
                    ticks *= 4
                for _ in range(ticks):
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
            return  # the planet was replaced while thinking
        if kind == "decide":
            self.sim.apply(result)
        elif kind == "reflect":
            self.sim.apply_reflection(result)
            self.action_save(quiet=True)  # autosave once per sol
        else:
            self.sim.apply_conversation(result)

    # --- rendering ------------------------------------------------------------
    def _render(self) -> None:
        self.query_one("#map", MapView).refresh_map()
        self.query_one("#status", Static).update(self._status_text())
        self.query_one("#mind", Static).update(self._mind_text())
        level = self.sim.world.level
        god = " [око бога]" if self.god_view else ""
        self.query_one("#map").border_title = f"{level.name}{god}"
        state = "ПАУЗА" if self.paused else f"x{SPEEDS[self.speed_idx]}"
        self.query_one("#map").border_subtitle = f"{state} · seed {self.sim.world.seed}"

    def _status_text(self) -> Text:
        world = self.sim.world
        hero = world.hero
        t = Text()
        icon = "☾" if world.is_night else "☀"
        t.append(f"{world.clock()} {icon}", style="bold")
        director = world.director
        if director:
            phase = director.phase(world.tick)
            color = {"пік": "bold red", "наростання": "yellow", "перепочинок": "green"}.get(phase, "grey62")
            t.append(f"  напруга {director.tension:.2f} · {phase}", style=color)
        t.append("\n")
        t.append(f"{NEED_NAMES['hp']:<9}", style="bold")
        t.append_text(_bar(hero.hp))
        t.append("\n")
        for n in NEEDS:
            t.append(f"{NEED_NAMES[n]:<9}")
            t.append_text(_bar(hero.need(n)))
            t.append("\n")
        light = "ліхтар" if hero.inventory["headlamp"] else (
            f"фальшфеєр {hero.flare_ticks}хв" if hero.flare_ticks else "—")
        t.append(f"Зброя: {hero.weapon_name} ({hero.attack_power})  Світло: {light}\n", style="grey70")
        inv = ", ".join(f"{ITEMS[k].name}×{v}" for k, v in sorted(hero.inventory.items()) if v > 0)
        t.append(f"Речі: {inv or 'нічого'}\n", style="grey70")
        pod = world.pod
        if pod:
            heat = "обігрів ON" if pod.heating else "обігрів off"
            fault = " · ЗБІЙ!" if pod.fault else ""
            if pod.rescue_at is not None:
                left = max(0, pod.rescue_at - world.tick)
                beacon = f"шатл через {left // 60} год"
            elif pod.beacon_repaired:
                beacon = "маяк готовий"
            else:
                have = ", ".join(f"{k} {min(hero.inventory[k], n)}/{n}" for k, n in
                                 {"alloy": 3, "circuit": 1}.items())
                beacon = f"маяк: {have}"
            t.append(f"Капсула: ⚡{pod.power:.0f} · {heat}{fault} · {beacon}\n", style="bright_white")
        comp = world.companion
        if comp:
            if comp.alive:
                t.append(f"{comp.name}: {comp.activity} · довіра {comp.trust:.2f}\n", style="magenta")
            else:
                t.append(f"{comp.name} загинула ({comp.cause_of_death})\n", style="grey50")
        if director and director.banner(world):
            t.append(director.banner(world) + "\n", style="bold magenta")
        threats = [c for c in visible_creatures(world) if c.kind.hostile]
        if threats:
            t.append("Поруч: " + ", ".join(sorted({c.name for c in threats})), style="bold red")
        return t

    def _mind_text(self) -> Text:
        sim = self.sim
        hero = sim.world.hero
        t = Text()
        if sim.over:
            left = RESTART_AFTER - (time.monotonic() - (self.ended_at or time.monotonic()))
            if hero.rescued:
                t.append(f"🚀 {hero.name} врятований!\n", style="bold green")
            else:
                t.append(f"† {hero.name} загинув ({hero.cause_of_death}).\n", style="bold red")
            t.append(f"Прожито до: {sim.world.clock()}. Артефактів: {hero.inventory['artifact']}. "
                     f"Записів у щоденнику: {len(hero.diary)}.\n")
            t.append(f"Нова капсула через {max(0, left):.0f} с (N — зараз, d — щоденник)", style="grey70")
            return t
        if hero.goal:
            t.append(f"Мета: {hero.goal}\n", style="bold")
        if sim.thought:
            t.append(f"«{sim.thought}»\n", style="italic cyan")
        if self.thinking_since is not None:
            dots = "." * (1 + int(time.monotonic() * 2) % 3)
            what = THINKING.get(self.thinking_kind, "думає")
            t.append(f"{what}{dots} {time.monotonic() - self.thinking_since:.0f}с", style="yellow")
        elif sim.action:
            t.append(f"→ {sim.action.label()}", style="bold")
        calls = getattr(self.brain, "calls", sim.decisions)
        errors = getattr(self.brain, "errors", 0)
        t.append(f"\nрішень: {sim.decisions}  викликів ШІ: {calls}  помилок: {errors}", style="grey50")
        return t

    # --- actions ---------------------------------------------------------------
    def action_pause(self) -> None:
        self.paused = not self.paused

    def action_faster(self) -> None:
        self.speed_idx = min(self.speed_idx + 1, len(SPEEDS) - 1)

    def action_slower(self) -> None:
        self.speed_idx = max(self.speed_idx - 1, 0)

    def action_god(self) -> None:
        self.god_view = not self.god_view

    def action_save(self, quiet: bool = False) -> None:
        if self.save_dir is None or self.sim.over:
            return
        path = save_path(self.sim, self.brain.name, self.save_dir)
        save_game(self.sim, path, {"wrecks_done": sorted(getattr(self.brain, "wrecks_done", set()))})
        if not quiet:
            self.notify(f"Гру збережено: {path}", title="Збереження")

    async def action_quit(self) -> None:
        self.action_save(quiet=True)
        self.exit()

    def action_diary(self) -> None:
        self.push_screen(DiaryScreen(self))

    def action_new_world(self) -> None:
        self.seed += 1
        self.ended_at = None
        self.thinking_since = None
        self.sim = self._new_sim(self.seed)
        self.query_one("#log", RichLog).clear()
        self._intro()
