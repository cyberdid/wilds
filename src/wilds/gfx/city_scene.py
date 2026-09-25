"""The cyberpunk city drawn with sprites: five themed locations (the Sprawl,
the Docks, Corp Row, the orbital station, the frontier outpost), buildings as
2.5D blocks, street stalls, NPCs of every race and role, the runner, rain and
neon at night, district heat made visible, dead-drop markers and money flying.

Same contract as ``Tau7Scene``: ``update`` turns state changes into effects,
``build`` fills a render Frame, nothing touches the game state.
"""

from __future__ import annotations

import math

from ..cyberpunk.items import ITEMS
from ..cyberpunk.tiles import CTile
from ..world import chebyshev
from .actors import ActorTracker
from .lighting import CITY_SKY, OUTPOST_SKY, STATION_SKY, sky
from .mapping import city_theme, cp_block, cp_ground_base, cp_hero, cp_npc, cp_object, hash2, pick
from .render import FOG_MEMORY, Frame, Renderer
from .tau7_scene import ground_point

SIDES = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}
SIGN_LIGHT = {CTile.SHOP: (90, 255, 140), CTile.BAR: (255, 226, 90), CTile.FIXER: (90, 240, 255),
              CTile.CHECKPOINT: (255, 70, 90), CTile.NEON: (255, 60, 220)}
GOLD, BAD, GOOD = (255, 222, 90), (255, 96, 96), (140, 255, 150)
RAINY = ("sprawl", "docks", "corp")
# isometric building heights per theme: (base, extra per block) - the skyline
SKYLINE = {"sprawl": (18, 14), "docks": (12, 8), "corp": (28, 20), "station": (16, 4), "outpost": (10, 6)}


def _phase(x: int, y: int) -> float:
    return (hash2(x, y, 3) % 1000) / 83.0


class CityScene:
    def __init__(self, renderer: Renderer) -> None:
        self.r = renderer
        self.bank = renderer.bank
        self.reg = renderer.bank.registry
        self.actors = ActorTracker()
        self.reset()

    def reset(self) -> None:
        self.actors.reset()
        self.world_id = None
        self.level_id = None
        self.last: dict[str, object] = {}
        self.until: dict[tuple, float] = {}
        self.timers: dict[str, float] = {}
        self.thought = ""
        self.talking: dict[str, float] = {}  # npc id -> until
        self.free_at: float | None = None
        self.shake_until = 0.0
        self.fade_until = 0.0
        self.r.effects.clear()
        self.r.particles.clear()

    def _every(self, key: str, period: float, now: float) -> bool:
        if now - self.timers.get(key, -1e9) >= period:
            self.timers[key] = now
            return True
        return False

    def _fx(self, name: str, x: float, y: float, now: float, **kw):
        return self.r.effects.spawn(self.bank, name, x, y, now, **kw)

    # --- environment ------------------------------------------------------------------
    def theme(self, world) -> str:
        return city_theme(world.hero.level_id)

    def ambient(self, world):
        theme = self.theme(world)
        hour = world.hour + world.minute / 60
        frames = STATION_SKY if theme == "station" else OUTPOST_SKY if theme == "outpost" else CITY_SKY
        return sky(frames, hour)

    def raining(self, world) -> bool:
        return self.theme(world) in RAINY and (world.is_night or hash2(world.day, 7) % 3 == 0)

    def weather(self, sim) -> tuple:
        return ()

    def hero_point(self, sim, now: float) -> tuple[float, float, float]:
        v = self.actors.views.get("hero")
        pos = self.actors.visual(v, now) if v is not None else sim.world.hero.pos
        gx, gy = ground_point(*pos)
        return gx, gy, 8.0

    def level_size(self, sim) -> tuple[int, int]:
        level = sim.world.level
        return level.width, level.height

    # --- events and diffs ------------------------------------------------------------------
    def on_event(self, ev, now: float, world) -> None:
        if ev.kind != "talk" or ": «" not in ev.text:
            return
        who, _, said = ev.text.partition(": «")
        key = "hero"
        for npc in world.level.npcs:
            if npc.name == who:
                key = ("npc", npc.id)
                self.talking[npc.id] = now + 6
                break
        self.r.effects.say(key, said.rstrip("»"), "speech", now)

    def update(self, sim, now: float, dt: float, thinking: bool, view_rect_world) -> None:
        world = sim.world
        hero = world.hero
        fx = self.r.effects
        if self.world_id != id(world):
            self.reset()
            self.world_id = id(world)
            self.last = {"hp": hero.hp, "nuyen": hero.nuyen, "debt": hero.debt, "essence": hero.essence,
                         "inv": dict(hero.inventory), "contract": None}
        if self.level_id != hero.level_id:
            if self.level_id is not None:
                self.fade_until = now + 0.6
            self.level_id = hero.level_id
            self.r.particles.clear()
        hx, hy = ground_point(*hero.pos)
        d_hp = hero.hp - self.last["hp"]
        if d_hp <= -0.9:
            self._fx("fx.blood", hx, hy, now, z=8)
            fx.text(f"-{-d_hp:.0f}", BAD, hx, hy, now, z=18)
            self.until[("hero", "hurt")] = now + 0.3
            if -d_hp >= 8:
                self.shake_until = now + 0.35
        elif d_hp >= 4.5:
            self._fx("fx.heal", hx, hy, now, z=8, emissive=True)
            fx.text(f"+{d_hp:.0f}", GOOD, hx, hy, now, z=18)
        d_ny = hero.nuyen - self.last["nuyen"]
        if d_ny:
            fx.text(f"{d_ny:+d}¥", GOLD if d_ny > 0 else (255, 150, 110), hx + 10, hy, now, duration=1.8,
                    size=15, z=22)
        d_debt = hero.debt - self.last["debt"]
        if d_debt < 0:
            fx.text(f"борг {d_debt}¥", GOOD, hx - 10, hy, now, duration=2.2, size=14, z=32)
        elif d_debt > 0:
            fx.text(f"борг +{d_debt}¥", BAD, hx - 10, hy, now, duration=2.2, size=14, z=32)
        if hero.essence < self.last["essence"] - 0.01:
            self._fx("fx.heal", hx, hy, now, z=8, emissive=True)
            fx.text(f"есенс {hero.essence - self.last['essence']:+.1f}", (120, 230, 255), hx, hy, now,
                    duration=2.2, size=14, z=40)
        gains = [(k, v - self.last["inv"].get(k, 0)) for k, v in hero.inventory.items()
                 if v > self.last["inv"].get(k, 0)]
        if gains:
            self._fx("fx.pickup", hx, hy, now, z=6, emissive=True)
            for i, (k, n) in enumerate(gains[:3]):
                fx.text(f"+{n} {ITEMS[k].name}", GOOD, hx, hy, now, duration=1.8, size=14, z=50 + i * 9)
        contract = world.contract
        status = (contract.id, contract.status) if contract else None
        if status != self.last["contract"] and contract and contract.status == "delivered":
            self._fx("fx.pickup", hx, hy, now, z=6, emissive=True)
        self.last.update(hp=hero.hp, nuyen=hero.nuyen, debt=hero.debt, essence=hero.essence,
                         inv=dict(hero.inventory), contract=status)
        if sim.thought and sim.thought != self.thought:
            fx.say("hero", sim.thought, "thought", now)
        self.thought = sim.thought
        if thinking:
            b = fx.bubbles.get("hero")
            if b is None or b.kind != "thinking":
                fx.say("hero", "", "thinking", now, duration=1e9)
            if sim.pending == "converse" and sim.pending_conversation:
                self.talking[sim.pending_conversation] = now + 1.0
        elif fx.bubbles.get("hero") and fx.bubbles["hero"].kind == "thinking":
            del fx.bubbles["hero"]
        if hero.free and self.free_at is None:
            self.free_at = now
        self._ambient(sim, now, dt, view_rect_world)
        self.r.particles.update(dt)
        fx.prune(now)
        self.actors.forget_stale(now)

    def _ambient(self, sim, now: float, dt: float, rect) -> None:  # rect: world px in view
        world = sim.world
        level = world.level
        hero = world.hero
        if self.raining(world):
            self.r.particles.rain(rect, dt, 1.0 if world.is_night else 0.6)
            if self._every("splash", 0.07, now):
                x = rect.left + (hash2(int(now * 100), 5) % max(1, rect.width))
                y = rect.top + (hash2(int(now * 100), 9) % max(1, rect.height))
                self._fx("fx.splash", x, y, now, emissive=False)
        for npc in level.npcs:
            hostile = npc.hostile or (npc.role == "ganger" and hero.reputation.get("gangs", 0.0) <= -0.5)
            if hostile and npc.pos in hero.visible and chebyshev(npc.pos, hero.pos) <= 6 \
                    and self._every(f"alert{npc.id}", 2.2, now):
                x, y = ground_point(*npc.pos)
                self._fx("fx.alert", x, y, now, duration=1.1, emissive=True, z=26, vz=4)

    # --- the frame -------------------------------------------------------------------------
    def build(self, sim, f: Frame, god: bool) -> None:
        world = sim.world
        hero = world.hero
        level = world.level
        reg = self.reg
        now = f.now
        visible = hero.visible
        known = hero.known(level.id)
        f.ambient = self.ambient(world)
        night = f.ambient[0] < 190
        tx0, ty0, tx1, ty1 = f.tile_range()
        tx0, ty0 = max(0, tx0), max(0, ty0)
        tx1, ty1 = min(level.width - 1, tx1), min(level.height - 1, ty1)
        f.fog_on = not god
        f.fog_range = (tx0, ty0, tx1, ty1)
        for ty in range(ty0, ty1 + 1):
            for tx in range(tx0, tx1 + 1):
                p = (tx, ty)
                lit = god or p in visible
                if not lit and p not in known:
                    continue
                f.fog_tile(tx, ty, None if lit else FOG_MEMORY)
                tile = level.tile(p) if lit else known[p]
                self._tile(f, level, p, tile, lit, now, night)

        # the courier job's dead drop
        c = world.contract
        if c is not None and c.status == "active" and c.level_id == level.id:
            x, y = ground_point(*c.drop_pos)
            f.sprite("fx.drop_marker", x, y, now, layer=1, emissive=True)
            f.light(x, y, 22, (255, 220, 90), 0.8, glow=True, phase=1.0, z=10)

        # NPCs
        for npc in level.npcs:
            if not (god or npc.pos in visible):
                continue
            v = self.actors.update(("npc", npc.id), npc.pos, now)
            if chebyshev(npc.pos, hero.pos) <= 4:
                self.actors.face(v, hero.pos[0])
            talking = self.talking.get(npc.id, 0) > now
            name = cp_npc(reg, npc.role, npc.race.name.lower(), "talk" if talking else "idle")
            gx, gy = ground_point(*npc.pos)
            f.sprite(name, gx, gy, now - v.anim_since + _phase(*npc.pos), flip=v.facing < 0, layer=2,
                     shadow=12 if npc.race.name == "TROLL" else 9)
            f.anchors[("npc", npc.id)] = (gx, gy, 24 if npc.race.name == "TROLL" else 17)
            if npc.role == "collector" and night:
                f.light(gx, gy, 18, (255, 60, 70), 0.8, glow=True, z=12)

        # the runner
        if hero.alive and not hero.free:
            v = self.actors.update("hero", hero.pos, now)
            moving = self.actors.moving(v, now)
            aug = any(ITEMS[k].cyberware for k, n in hero.inventory.items() if n > 0)
            anim = "hurt" if self.until.get(("hero", "hurt"), 0) > now else "walk" if moving else "idle"
            race = hero.race.name.lower()
            name = cp_hero(reg, race, anim, aug)
            gx, gy = ground_point(*self.actors.visual(v, now))
            tint = ("flat", (255, 250, 250)) if anim == "hurt" and int(now * 20) % 2 else None
            placed = f.sprite(name, gx, gy, now - v.anim_since, flip=v.facing < 0, tint=tint, layer=2,
                              shadow=12 if race == "troll" else 9)
            if name in self.bank:
                placed.xray = self.bank.frame(name, now - v.anim_since, 1, v.facing < 0, "silhouette")
            f.anchors["hero"] = (gx, gy, 25 if race == "troll" else 17)
            f.light(gx, gy, 40, (170, 180, 230), 0.8, z=8)
            if level.heat > 65:
                for i in range(2):
                    a = now * 0.9 + i * math.pi
                    px, py = gx + math.cos(a) * 34, gy + math.sin(a) * 18
                    pz = 30 + math.sin(a * 1.7) * 6
                    f.sprite("fx.police", px, py, now + i, layer=3, sort_y=gy + 40, center=True, z=pz)
                    color = (255, 60, 60) if int(now * 4 + i) % 2 else (70, 110, 255)
                    f.light(px, py, 26, color, 0.9, glow=True, z=pz)

        for e in self.r.effects.fx:
            if e.start > now:
                continue
            x, y, z = e.pos(now)
            f.sprite(e.name, x, y, now - e.start, flip=e.flip, emissive=e.emissive, center=not e.anchored,
                     layer=3, sort_y=y + e.sort_bias, z=z)

    def _tile(self, f: Frame, level, p, tile: CTile, lit: bool, now: float, night: bool) -> None:
        reg = self.reg
        tx, ty = p
        ph = _phase(tx, ty)
        block = cp_block(tile, level.id)
        if block is not None:
            top, face = block
            open_sides = "".join(s for s, (dx, dy) in SIDES.items() if level.in_bounds((tx + dx, ty + dy))
                                 and level.tile((tx + dx, ty + dy)) is not CTile.WALL)
            base, extra = SKYLINE.get(city_theme(level.id), (16, 8))
            height = base + hash2(tx // 8, ty // 5, 31) % (extra + 1)  # one height per city block
            f.block(pick(reg, top, tx, ty), pick(reg, face, tx, ty), tx, ty, now + ph, open_sides, height,
                    memory=not lit)
            if "s" in open_sides and lit and night and hash2(tx, ty, 21) % 3 == 0:
                gx, gy = ground_point(tx, ty)
                f.light(gx, gy, 16, (255, 200, 120), 0.45, phase=ph, z=6)
            return
        underlay = CTile.ROAD if ty % 5 == 0 else CTile.SIDEWALK
        f.ground_tile(pick(reg, cp_ground_base(reg, tile, level.id, underlay), tx, ty), tx, ty, now + ph)
        obj = cp_object(reg, tile, level.id)
        gx, gy = ground_point(tx, ty)
        if obj is not None:
            f.sprite(pick(reg, obj, tx, ty), gx, gy, now + ph, layer=0,
                     tint="memory" if (f.iso and not lit) else None)
        if lit and tile in SIGN_LIGHT:
            color = SIGN_LIGHT[tile]
            if tile is CTile.NEON and hash2(tx, ty, 2) % 2:
                color = (60, 230, 255)
            flick = 0.85 + 0.15 * math.sin(now * 13 + ph) if tile is CTile.NEON else 1.0
            f.light(gx, gy, 34 if tile is not CTile.NEON else 26, color, 0.9 * flick, glow=True, phase=ph,
                    z=14 if tile is not CTile.NEON else 4)
