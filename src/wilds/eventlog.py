"""The full journal of a game run, as a plain-text file: ``logs/events-<brain>-<seed>.log``
(``events-cyberpunk-...`` for a standalone city run; a campaign keeps both chapters
in the Tau-7 file).

It records everything: every line the world logs (the in-game journal: events,
the hero's thoughts, diary entries, conversations, the director's warnings),
every brain decision with the reason the brain was woken and a snapshot of the
hero, the outcome of every action, and the front-end's own milestones (chapter
start and end, saves, new worlds, the campaign moving on).

It works in every mode (terminal UI, sprite window, headless) and changes
nothing: it hangs on ``world.listeners`` - which ``save_game`` strips before
pickling - and only reads ``sim.history``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

DAY = 24 * 60


def log_name(brain_name: str, seed: int, chapter: str = "tau7") -> str:
    prefix = "events" if chapter == "tau7" else f"events-{chapter}"
    return f"{prefix}-{brain_name}-{seed}.log"


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.path.open("a", encoding="utf-8", buffering=1)
        self.sim = None
        self._decisions = 0
        self._pending: list = []  # history entries whose outcome is not logged yet
        self._ended = False
        self._write(f"##### {time.strftime('%Y-%m-%d %H:%M:%S')} · {' '.join(sys.argv[1:]) or 'wilds'}")

    @classmethod
    def for_game(cls, log_dir: Path | str | None, brain_name: str, seed: int,
                 chapter: str = "tau7") -> "EventLog | None":
        if not log_dir:
            return None
        return cls(Path(log_dir) / log_name(brain_name, seed, chapter))

    # --- wiring ---------------------------------------------------------------
    def attach(self, sim, title: str, brain_label: str, resumed: bool = False) -> None:
        """Follow a (new or loaded) simulation from now on."""
        self.detach()
        self.sim = sim
        self._decisions = sim.decisions
        self._pending = [e for e in sim.history if not e.outcome]
        self._ended = False
        world = sim.world
        self._write("")
        self._write(f"===== {title} · seed {world.seed} · мозок {brain_label}"
                    + (" · продовження збереження" if resumed else "") + " =====")
        if not resumed:
            for ev in world.events:  # the opening lines were logged before we listened
                self._event(ev)
        if resumed or sim.decisions:  # a fresh run logs its state with the first decision
            self._state()
        world.listeners.append(self._on_event)

    def detach(self) -> None:
        if self.sim is not None:
            self._sync()
            try:
                self.sim.world.listeners.remove(self._on_event)
            except ValueError:
                pass
        self.sim = None

    def close(self) -> None:
        if self._f.closed:
            return
        if self.sim is not None:
            self.check_end()
            self.detach()
        self._f.close()

    # --- writing -----------------------------------------------------------------
    def _write(self, line: str) -> None:
        if not self._f.closed:
            self._f.write(line + "\n")

    def _clock(self, tick: int) -> str:
        word = "Сол" if self.sim is not None and hasattr(self.sim.world, "pod") else "День"
        return f"{word} {tick // DAY + 1} {tick // 60 % 24:02d}:{tick % 60:02d}"

    def _line(self, tick: int, tag: str, text: str) -> None:
        self._write(f"[{self._clock(tick)}] {tag:<9} {text}")

    def meta(self, text: str) -> None:
        """A front-end milestone (save, new world, campaign step)."""
        tick = self.sim.world.tick if self.sim is not None else 0
        self._line(tick, "* гра", text)

    def _on_event(self, ev) -> None:
        self._sync()
        self._event(ev)

    def _event(self, ev) -> None:
        text = ev.text if ev.kind != "brain" else f"«{ev.text}»"
        self._line(ev.tick, ev.kind, text.replace("\n", " / "))

    # --- decisions, outcomes, state ------------------------------------------------------
    def _sync(self) -> None:
        sim = self.sim
        if sim is None:
            return
        for entry in list(self._pending):
            if entry.outcome:
                self._line(sim.world.tick, "підсумок", f"{entry.action} {entry.target}".strip() + f" → {entry.outcome}")
                self._pending.remove(entry)
        new = sim.decisions - self._decisions
        if new <= 0:
            return
        self._decisions = sim.decisions
        for entry in sim.history[-new:]:
            reason = getattr(sim, "wake_reason", "")
            self._line(entry.tick, "рішення", f"{entry.action} {entry.target}".strip()
                       + (f" · причина: {reason}" if reason else ""))
            if entry.outcome:
                self._line(entry.tick, "підсумок", f"{entry.action} → {entry.outcome}")
            else:
                self._pending.append(entry)
        self._state()

    def _state(self) -> None:
        sim = self.sim
        world = sim.world
        hero = world.hero
        inv = ", ".join(f"{k}×{v}" for k, v in sorted(hero.inventory.items()) if v > 0) or "—"
        if hasattr(world, "pod"):  # Tau-7
            parts = [f"hp {hero.hp:.0f}", f"ситість {hero.satiety:.0f}", f"вода {hero.hydration:.0f}",
                     f"тепло {hero.warmth:.0f}", f"енергія {hero.energy:.0f}",
                     f"{hero.level_id} {hero.pos[0]},{hero.pos[1]}", f"речі: {inv}"]
            pod = world.pod
            if pod:
                flags = [f"енергія {pod.power:.0f}"] + (["обігрів"] if pod.heating else []) + \
                        (["ЗБІЙ"] if pod.fault else []) + (["маяк готовий"] if pod.beacon_repaired else []) + \
                        (["сигнал передано"] if pod.rescue_at is not None else [])
                parts.append("капсула: " + ", ".join(flags))
            comp = world.companion
            if comp:
                parts.append(f"{comp.name}: {comp.activity}, довіра {comp.trust:.2f}" if comp.alive
                             else f"{comp.name}: загинула")
        else:  # the city
            parts = [f"hp {hero.hp:.0f}", f"есенс {hero.essence:.1f}", f"{hero.nuyen}¥", f"борг {hero.debt}¥",
                     f"{hero.level_id} {hero.pos[0]},{hero.pos[1]}", f"теплота {world.level.heat:.0f}",
                     f"речі: {inv}"]
            c = world.contract
            if c is not None and c.status != "done":
                parts.append(f"контракт {c.id}: {c.status}, {c.reward}¥")
            if hero.reputation:
                parts.append("репутація: " + ", ".join(f"{k} {v:+.2f}" for k, v in hero.reputation.items()))
        self._line(world.tick, "стан", " · ".join(parts))

    def check_end(self) -> bool:
        """Write the ending once, the first time the run is over. True if it is over."""
        sim = self.sim
        if sim is None or not sim.over:
            return False
        if self._ended:
            return True
        self._ended = True
        self._sync()
        world = sim.world
        hero = world.hero
        if getattr(hero, "rescued", False):
            how = "врятований"
        elif getattr(hero, "free", False):
            how = "вільний: борг погашено"
        else:
            how = f"загинув: {hero.cause_of_death or 'невідомо'}"
        self._line(world.tick, "КІНЕЦЬ", f"{hero.name} {how} · рішень {sim.decisions} · {world.clock()}")
        legacy = getattr(sim, "legacy_path", None)
        if legacy:
            self._line(world.tick, "КІНЕЦЬ", f"спадок для наступної глави: {legacy}")
        self._state()
        return True
