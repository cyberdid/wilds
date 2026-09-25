"""Tau-7 drawn with sprites: terrain, wrecks, the pod, fauna, the survivor and
Lira, plus everything that makes the planet feel alive (day/night, storms,
glowing spores, falling debris, the beacon, the rescue shuttle).

``update`` diffs the simulation once per frame and turns changes into effects
(a hit, a heal, a pickup, a kill, an impact); ``build`` fills a render Frame in
world terms (ground points + height ``z``), so it works in both projections.
Nothing here changes the game state.
"""

from __future__ import annotations

import math

from ..actions import PodAction
from ..creatures import KINDS
from ..tiles import Tile
from ..world import ITEMS, chebyshev
from .actors import ActorTracker
from .lighting import STORM_TINT, TAU7_SKY, WRECK_AMBIENT, sky
from .mapping import hash2, pick, t7_actor, t7_block, t7_ground_base, t7_item, t7_object, wreck_theme
from .render import FOG_MEMORY, TILE, Frame, Renderer

SIDES = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}
CORNERS = {"ne": (1, -1), "nw": (-1, -1), "se": (1, 1), "sw": (-1, 1)}
SHADOW = {"hopper": 7, "hound": 10, "brute": 15, "drone": 8, "android": 9}
WORK = ("gather", "craft", "build", "cook", "pod", "use", "eat")
GLOW_ITEMS = {"artifact": ((120, 255, 240), 18), "power_cell": ((110, 230, 255), 12),
              "circuit": ((140, 255, 200), 10), "flare": ((255, 120, 90), 10)}
WRECK_LIGHT = {"helios": (110, 240, 255), "kepler": (255, 170, 90), "hive": (130, 255, 200)}
BLOCK_HEIGHT = {Tile.ROCK: 12, Tile.WALL: 18}
GOOD, BAD = (140, 255, 150), (255, 90, 90)


def ground_point(x: float, y: float) -> tuple[float, float]:
    """World px of the ground point of a (possibly fractional) tile position."""
    return x * TILE + TILE // 2, y * TILE + TILE - 1


def _phase(x: int, y: int) -> float:
    return (hash2(x, y, 7) % 1000) / 97.0


def _mul(a, b):
    return tuple(int(x * y / 255) for x, y in zip(a, b))


class Tau7Scene:
    def __init__(self, renderer: Renderer) -> None:
        self.r = renderer
        self.bank = renderer.bank
        self.reg = renderer.bank.registry
        self.actors = ActorTracker()
        self._bases_cache: dict[str, list[str]] = {}
        decor = self._bases("t7.decor.")
        self.decor = {
            "moss": [n for n in decor if not any(k in n for k in ("scrap", "crater"))],
            "dust": [n for n in decor if any(k in n for k in ("pebble", "bone", "scrap"))],
        }
        self.reset()

    def _bases(self, prefix: str) -> list[str]:
        if prefix not in self._bases_cache:
            self._bases_cache[prefix] = sorted({n.split("@")[0] for n in self.reg.names(prefix)})
        return self._bases_cache[prefix]

    def reset(self) -> None:
        self.actors.reset()
        self.world_id = None
        self.level_id = None
        self.hp = None
        self.inv: dict[str, int] = {}
        self.creature_hp: dict[int, tuple[float, tuple[int, int], str]] = {}
        self.ev_stage: dict[tuple, str] = {}
        self.until: dict[tuple, float] = {}
        self.timers: dict[str, float] = {}
        self.thought = ""
        self.rescued_at: float | None = None
        self.dead_at: float | None = None
        self.shake_until = 0.0
        self.fade_until = 0.0
        self.entrance_levels: dict = {}
        self.near_tiles: dict = {}
        self.r.effects.clear()
        self.r.particles.clear()

    # --- helpers -----------------------------------------------------------------
    def _every(self, key: str, period: float, now: float) -> bool:
        if now - self.timers.get(key, -1e9) >= period:
            self.timers[key] = now
            return True
        return False

    def _fx(self, name: str, x: float, y: float, now: float, **kw):
        return self.r.effects.spawn(self.bank, name, x, y, now, **kw)

    def ambient(self, world) -> tuple[int, int, int]:
        if world.level.dark:
            return WRECK_AMBIENT
        a = sky(TAU7_SKY, world.hour + world.minute / 60)
        if world.director and world.director.storm_active:
            a = _mul(a, STORM_TINT)
        return a

    def weather(self, sim) -> tuple:
        world = sim.world
        if world.director and world.director.storm_active and not world.level.dark:
            return (("storm", 1.0),)
        return ()

    def hero_point(self, sim, now: float) -> tuple[float, float, float]:
        """World ground point (+ chest height) the camera follows."""
        v = self.actors.views.get("hero")
        pos = self.actors.visual(v, now) if v is not None else sim.world.hero.pos
        gx, gy = ground_point(*pos)
        return gx, gy, 8.0

    def level_size(self, sim) -> tuple[int, int]:
        level = sim.world.level
        return level.width, level.height

    # --- per-frame state diff -> effects ---------------------------------------------
    def on_event(self, ev, now: float, world) -> None:
        if ev.kind != "talk" or ": «" not in ev.text:
            return
        who, _, said = ev.text.partition(": «")
        comp = world.companion
        key = "lira" if comp and who == comp.name else "hero"
        self.r.effects.say(key, said.rstrip("»"), "speech", now)

    def update(self, sim, now: float, dt: float, thinking: bool, area) -> None:
        world = sim.world
        hero = world.hero
        level = world.level
        fx = self.r.effects
        if self.world_id != id(world):
            self.reset()
            self.world_id = id(world)
            self.entrance_levels = {lv.parent[1]: lid for lid, lv in world.levels.items() if lv.parent}
            self.hp = hero.hp
            self.inv = dict(hero.inventory)
        if self.level_id != level.id:
            if self.level_id is not None:
                self.fade_until = now + 0.5
            self.level_id = level.id
            self.creature_hp = {}
            self.near_tiles = {}
            self.r.particles.clear()
        hx, hy = ground_point(*hero.pos)

        # the hero's health
        delta = hero.hp - (self.hp if self.hp is not None else hero.hp)
        if delta <= -0.9:
            self._fx("fx.blood", hx, hy, now, z=8)
            fx.text(f"-{-delta:.0f}", BAD, hx, hy, now, z=18)
            self.until[("hero", "hurt")] = now + 0.22
            if -delta >= 9:
                self.shake_until = now + 0.3
            for c in level.creatures:
                if c.hp > 0 and c.kind.hostile and chebyshev(c.pos, hero.pos) <= 1:
                    self.until[(c.id, "attack")] = now + 0.35
                    self._fx("fx.zap" if c.kind.key in ("drone", "android") else "fx.bite", hx, hy, now,
                             z=7, emissive=True)
        elif delta >= 4.5:
            self._fx("fx.heal", hx, hy, now, z=8, emissive=True)
            fx.text(f"+{delta:.0f}", GOOD, hx, hy, now, z=18)
        self.hp = hero.hp

        # creatures: hits and kills
        seen = {}
        for c in level.creatures:
            if c.hp <= 0:
                continue
            seen[c.id] = (c.hp, c.pos, c.kind.key)
            old = self.creature_hp.get(c.id)
            if old and c.hp < old[0]:
                cx, cy = ground_point(*c.pos)
                weapon = ("fx.slash_plasma" if hero.inventory["plasma_cutter"] else
                          "fx.slash" if hero.inventory["blade"] else "fx.punch")
                self._fx(weapon, cx, cy, now, z=7, emissive=True, flip=c.pos[0] < hero.pos[0])
                fx.text(f"-{old[0] - c.hp:.0f}", (255, 220, 120), cx, cy, now, z=16)
                self.until[(c.id, "hit")] = now + 0.15
                self.until[("hero", "attack")] = now + 0.3
        for cid, (_hp, pos, _kind) in self.creature_hp.items():
            if cid not in seen and chebyshev(pos, hero.pos) <= 2:
                cx, cy = ground_point(*pos)
                self._fx("fx.death_poof", cx, cy, now, z=6)
                self.until[("hero", "attack")] = now + 0.3
        self.creature_hp = seen

        # inventory gains -> floating names
        gains = [(k, v - self.inv.get(k, 0)) for k, v in hero.inventory.items() if v > self.inv.get(k, 0)]
        if gains:
            self._fx("fx.pickup", hx, hy, now, z=6, emissive=True)
            for i, (k, n) in enumerate(gains[:3]):
                fx.text(f"+{n} {ITEMS[k].name}", GOOD, hx, hy, now, duration=1.6, size=14, z=22 + i * 9)
        self.inv = dict(hero.inventory)

        # tiles changing next to the hero (harvest, build)
        near = {}
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                p = (hero.pos[0] + dx, hero.pos[1] + dy)
                if level.in_bounds(p):
                    near[p] = level.tile(p)
        for p, t in near.items():
            old = self.near_tiles.get(p)
            if old is None or old is t:
                continue
            px, py = ground_point(*p)
            if old is Tile.FLORA and t is Tile.STALK:
                self.r.particles.puff(px, py, 7, (170, 130, 240), 26, z=10)
            elif old is Tile.SPORE_BUSH:
                self.r.particles.puff(px, py, 9, (255, 120, 200), 22, z=6)
            elif t in (Tile.HEATER, Tile.DOME):
                self.r.particles.puff(px, py, 12, (200, 190, 170), 30, z=4)
                self._fx("fx.pickup", px, py, now, z=8, emissive=True)
        self.near_tiles = near

        # the director's events
        director = world.director
        if director:
            for e in director.events:
                key = (e.kind, e.warn_at)
                old = self.ev_stage.get(key)
                self.ev_stage[key] = e.stage
                if old == "warning" and e.stage != "warning":
                    self._event_started(e, world, now)

        # thoughts and thinking
        if sim.thought and sim.thought != self.thought:
            fx.say("hero", sim.thought, "thought", now)
        self.thought = sim.thought
        if thinking:
            b = fx.bubbles.get("hero")
            if b is None or b.kind != "thinking":
                fx.say("hero", "", "thinking", now, duration=1e9)
        elif fx.bubbles.get("hero") and fx.bubbles["hero"].kind == "thinking":
            del fx.bubbles["hero"]

        # endings
        if hero.rescued and self.rescued_at is None:
            self.rescued_at = now
        if not hero.alive and self.dead_at is None:
            self.dead_at = now
            self._fx("fx.death_poof", hx, hy, now, z=6)

        self._ambient_emitters(sim, now, dt, area)
        self.r.particles.update(dt)
        fx.prune(now)
        self.actors.forget_stale(now)

    def _event_started(self, e, world, now: float) -> None:
        pos = e.data.get("pos")
        if e.kind == "orbital_debris" and pos and world.hero.level_id == "surface":
            x, y = ground_point(*pos)
            fall = 0.45
            self._fx("fx.meteor", x, y, now, duration=fall, z=170, vz=-170 / fall, emissive=True,
                     light=(40, (255, 170, 90)))
            boom = self._fx("fx.explosion", x, y, now, z=10, emissive=True, light=(70, (255, 180, 100)))
            if boom:
                boom.start += fall
                boom.until += fall
            self.shake_until = now + fall + 0.45
            for _ in range(3):
                self.r.particles.puff(x, y, 10, (190, 150, 120), 45, z=6)
        elif e.kind == "distress_signal" and pos and world.hero.level_id == "surface":
            x, y = ground_point(*pos)
            self._fx("fx.meteor", x - 160, y, now, duration=0.9, z=180, vx=160 / 0.9, vz=-180 / 0.9,
                     emissive=True, light=(30, (255, 200, 140)))
        elif e.kind == "pod_fault" and world.pod:
            x, y = ground_point(*world.pod.pos)
            for i in range(4):
                self._fx("fx.spark", x + (i - 2) * 3, y, now, z=10, emissive=True, light=(14, (160, 220, 255)))

    def _ambient_emitters(self, sim, now: float, dt: float, area) -> None:
        world = sim.world
        hero = world.hero
        level = world.level
        pts = self.r.particles
        on_surface = not level.dark
        pod = world.pod
        if on_surface and pod and pod.level_id == level.id:
            px, py = ground_point(*pod.pos)
            if pod.fault and self._every("fault", 0.55, now):
                self._fx("fx.spark", px + (hash2(int(now * 10), 1) % 11) - 5, py, now, z=12, emissive=True,
                         light=(14, (170, 220, 255)))
                if self._every("fault_smoke", 1.6, now):
                    self._fx("fx.smoke", px + 3, py, now, z=14, vz=9)
            transmitting = isinstance(sim.action, PodAction) and getattr(sim.action, "cmd", "") == "transmit"
            if (pod.rescue_at is not None or transmitting) and self._every(
                    "beacon", 0.9 if transmitting else 2.6, now):
                self._fx("fx.beacon_wave", px, py, now, z=20, emissive=True, light=(24, (140, 255, 170)))
        comp = world.companion
        if on_surface and comp and comp.state == "stranded" and self._every("crash_smoke", 0.8, now):
            cx, cy = ground_point(*comp.pos)
            self._fx("fx.smoke", cx + 4, cy, now, z=14, vz=10)
        if on_surface:
            for pos in level.heaters:
                if pos in hero.visible:
                    hx, hy = ground_point(*pos)
                    pts.embers(hx, hy, dt, 2.5, key=f"ember{pos}", z=10)
        gx, gy = ground_point(*hero.pos)
        if hero.alive and hero.sleeping and self._every("zzz", 1.4, now):
            self._fx("fx.zzz", gx + 5, gy, now, duration=1.4, z=16, vz=9, vx=3, emissive=True)
        if hero.alive and not hero.sleeping and hero.warmth < 30 and self._every("frost", 0.8, now):
            self._fx("fx.frost", gx + (hash2(int(now * 7), 3) % 13) - 6, gy, now, duration=0.8, z=10,
                     vz=4, emissive=True)
        director = world.director
        if director and director.storm_active and on_surface:
            pts.storm(area, dt, 1.0)
        elif on_surface and world.is_night:
            pts.spores(area, dt, 1.0)

    # --- actors ------------------------------------------------------------------------
    def _hero_anim(self, sim, v, now: float) -> str:
        hero = sim.world.hero
        if hero.sleeping:
            return "sleep"
        if self.until.get(("hero", "hurt"), 0) > now:
            return "hurt"
        if self.until.get(("hero", "attack"), 0) > now:
            return "attack"
        if self.actors.moving(v, now):
            return "walk"
        act = sim.action.effective_name if sim.action else ""
        if act == "drink":
            return "drink"
        if act in WORK:
            return "work"
        return "idle"

    def _lira_anim(self, comp, v, now: float) -> str:
        if comp.state == "stranded":
            return "wave"
        if comp.activity == "спить":
            return "sleep"
        if self.actors.moving(v, now):
            return "carry" if comp.carrying else "walk"
        if comp._task == "work" and comp.activity == "збирає волокно":
            return "work"
        return "idle"

    # --- the frame -----------------------------------------------------------------------
    def build(self, sim, f: Frame, god: bool) -> None:
        world = sim.world
        hero = world.hero
        level = world.level
        reg = self.reg
        now = f.now
        visible = hero.visible
        known = hero.known(level.id)
        seen_items = hero.seen_items.get(level.id, {})
        f.ambient = self.ambient(world)
        night = level.dark or f.ambient[0] < 200
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
                self._tile(f, world, level, p, tile, lit, now, night)
                items = level.items.get(p) if lit else seen_items.get(p)
                if items:
                    self._item(f, items[0], tx, ty, now, lit and night, lit)
        if level.dark and level.exit_pos and (god or level.exit_pos in visible or level.exit_pos in known):
            ex, ey = ground_point(*level.exit_pos)
            f.light(ex, ey, 30, WRECK_LIGHT.get(wreck_theme(level.id), (200, 220, 255)), 0.8, glow=True, z=8)

        # director warnings drawn in the world
        director = world.director
        if director and not level.dark:
            for e in director.events:
                if e.kind == "orbital_debris" and e.stage == "warning" and e.data.get("pos"):
                    x, y = ground_point(*e.data["pos"])
                    f.sprite("fx.impact_marker", x, y, now, emissive=True, center=True, layer=3, z=f.flat_z)
                    f.light(x, y, 30, (255, 80, 70), 0.6 + 0.3 * math.sin(now * 6), glow=True, z=f.flat_z)

        # creatures
        for c in level.creatures:
            if c.hp <= 0 or not (god or c.pos in visible):
                continue
            v = self.actors.update(c.id, c.pos, now)
            attacking = self.until.get((c.id, "attack"), 0) > now
            if attacking:
                self.actors.face(v, hero.pos[0])
            anim = "attack" if attacking else ("move" if self.actors.moving(v, now) else "idle")
            name = t7_actor(reg, c.kind.key, anim)
            gx, gy = ground_point(*self.actors.visual(v, now))
            tint = ("flat", (255, 255, 255)) if self.until.get((c.id, "hit"), 0) > now else None
            f.sprite(name, gx, gy, now - v.anim_since + c.id * 0.13, flip=v.facing < 0, tint=tint,
                     layer=2, shadow=SHADOW.get(c.kind.key, 9))
            if c.kind.key in ("drone", "android") and night:
                f.light(gx, gy, 16, (255, 90, 90) if c.kind.key == "drone" else (120, 240, 255), 0.7,
                        glow=True, phase=c.id, z=9)
            if KINDS[c.kind.key].hostile:
                f.anchors[("c", c.id)] = (gx, gy, 16)

        # Lira
        comp = world.companion
        if comp and comp.alive and level.id == "surface" and (god or comp.pos in visible or comp.pos in known):
            v = self.actors.update("lira", comp.pos, now)
            name = t7_actor(reg, "lira", self._lira_anim(comp, v, now))
            gx, gy = ground_point(*self.actors.visual(v, now))
            f.sprite(name, gx, gy, now - v.anim_since, flip=v.facing < 0, layer=2, shadow=8)
            f.anchors["lira"] = (gx, gy, 17)
            if night:
                f.light(gx, gy, 14, (150, 230, 255), 0.5, z=7)

        # the survivor
        if hero.alive and not hero.rescued:
            v = self.actors.update("hero", hero.pos, now)
            name = t7_actor(reg, "hero", self._hero_anim(sim, v, now))
            gx, gy = ground_point(*self.actors.visual(v, now))
            tint = None
            if self.until.get(("hero", "hurt"), 0) > now:
                tint = ("flat", (255, 250, 250))
            elif hero.hp < 30 and int(now * 3) % 2:
                tint = ("mul", (255, 150, 150))
            elif hero.warmth < 30:
                tint = ("mul", (170, 205, 255))
            placed = f.sprite(name, gx, gy, now - v.anim_since, flip=v.facing < 0, tint=tint, layer=2, shadow=9)
            if name in self.bank:
                placed.xray = self.bank.frame(name, now - v.anim_since, 1, v.facing < 0, "silhouette")
            f.anchors["hero"] = (gx, gy, 17)
            radius = hero.sight_radius(world) * TILE
            if hero.inventory["headlamp"]:
                f.light(gx, gy, radius + 10, (230, 240, 255), 1.0, z=8)
            elif hero.flare_ticks or (hero.inventory["flare"] and (level.dark or world.is_night)):
                f.light(gx, gy, radius + 12, (255, 160, 110), 1.0, flicker=0.9, glow=True, z=8)
            else:
                f.light(gx, gy, max(28, radius), (150, 160, 205), 0.75, z=8)

        # the rescue shuttle
        if hero.rescued and world.pod and self.rescued_at is not None and level.id == "surface":
            px, py = ground_point(*world.pod.pos)
            drop = max(0.0, 150 - (now - self.rescued_at) * 55)
            f.sprite("fx.shuttle", px + 26, py, now, layer=2, shadow=22 if drop < 40 else 0, z=drop)
            f.light(px + 26, py, 50, (255, 210, 150), 0.9, glow=True, z=drop)
            if drop > 0:  # two nozzles, flames blasting down
                for dx in (-10, 9):
                    self.r.particles.embers(px + 26 + dx, py, 1 / 60, 18, key=f"thrust{dx}", z=drop, down=True)

        # effects
        for e in self.r.effects.fx:
            if e.start > now:
                continue
            x, y, z = e.pos(now)
            f.sprite(e.name, x, y, now - e.start, flip=e.flip, emissive=e.emissive, center=not e.anchored,
                     layer=3, sort_y=y + e.sort_bias, z=z)

    def _tile(self, f: Frame, world, level, p, tile: Tile, lit: bool, now: float, night: bool) -> None:
        reg = self.reg
        tx, ty = p
        ph = _phase(tx, ty)
        block = t7_block(tile, level.id)
        if block is not None:
            top, face = block
            open_sides = "".join(s for s, (dx, dy) in SIDES.items()
                                 if level.in_bounds((tx + dx, ty + dy)) and level.tile((tx + dx, ty + dy)) is not tile)
            f.block(pick(reg, top, tx, ty), pick(reg, face, tx, ty), tx, ty, now + ph, open_sides,
                    BLOCK_HEIGHT.get(tile, 12), memory=not lit)
            return
        underlay = self._underlay(level, p)
        base = t7_ground_base(tile, level.id, underlay)
        if tile is Tile.FLORA and "t7.ground.forest" in reg:
            base = "t7.ground.forest"
        f.ground_tile(pick(reg, base, tx, ty), tx, ty, now + ph)
        if tile is Tile.WATER:
            self._shore(f, level, tx, ty, now + ph)
        memory = "memory" if (f.iso and not lit) else None
        obj = t7_object(tile, self.entrance_levels.get(p))
        gx, gy = ground_point(tx, ty)
        if obj is not None:
            f.sprite(pick(reg, obj, tx, ty), gx, gy, now + ph, layer=0, tint=memory)
            self._object_extras(f, world, tile, p, gx, gy, now, lit, night)
        elif tile in (Tile.MOSS, Tile.DUST) and hash2(tx, ty, 11) % 100 < 4:
            options = self.decor["dust" if tile is Tile.DUST else "moss"]
            if options:
                name = pick(reg, options[hash2(tx, ty, 13) % len(options)], tx, ty)
                f.sprite(name, gx, gy, now + ph, layer=-1, tint=memory, solid=False)
                if "glow" in name and lit and night:
                    f.light(gx, gy, 10, (120, 255, 230), 0.6, glow=True, phase=ph, z=4)
        elif tile is Tile.FLOOR and hash2(tx, ty, 17) % 100 < 6:
            options = self._bases(f"t7.{wreck_theme(level.id)}.decor.")
            if options:
                f.sprite(pick(reg, options[hash2(tx, ty, 19) % len(options)], tx, ty), gx, gy, now + ph,
                         layer=-1, tint=memory, solid=False)

    def _underlay(self, level, p) -> Tile:
        dust = moss = 0
        for dx, dy in SIDES.values():
            q = (p[0] + dx, p[1] + dy)
            if level.in_bounds(q):
                t = level.tile(q)
                dust += t is Tile.DUST
                moss += t in (Tile.MOSS, Tile.FLORA, Tile.STALK)
        return Tile.DUST if dust > moss else Tile.MOSS

    def _shore(self, f: Frame, level, tx: int, ty: int, t: float) -> None:
        def land(dx, dy):
            q = (tx + dx, ty + dy)
            return level.in_bounds(q) and level.tile(q) is not Tile.WATER

        for side, (dx, dy) in SIDES.items():
            if land(dx, dy):
                f.ground_tile(f"t7.water.edge.{side}", tx, ty, t)
        for corner, (dx, dy) in CORNERS.items():
            if land(dx, dy) and not land(dx, 0) and not land(0, dy):
                f.ground_tile(f"t7.water.corner.{corner}", tx, ty, t)
        if land(0, -1):
            f.ground_tile("t7.water.bank", tx, ty, t)

    def _object_extras(self, f: Frame, world, tile: Tile, p, gx: float, gy: float, now: float, lit: bool,
                       night: bool) -> None:
        ph = _phase(*p)
        if tile is Tile.POD and world.pod:
            pod = world.pod
            if pod.beacon_repaired:
                f.sprite("t7.pod.antenna", gx, gy, now + ph, layer=0, sort_y=gy + 0.1)
            if pod.heating:
                f.sprite("t7.pod.glow", gx, gy, now + ph, layer=0, sort_y=gy + 0.2, emissive=True)
                if lit:
                    f.light(gx, gy, 44, (255, 190, 120), 0.95, flicker=0.2, glow=True, z=8)
            if lit:
                color = (255, 70, 70) if pod.fault else (120, 255, 150) if pod.beacon_repaired else (255, 200, 90)
                f.light(gx, gy, 12, color, 0.6 + 0.4 * (int(now * 2) % 2), glow=True, z=14)
            return
        if not lit:
            return
        if tile is Tile.HEATER:
            f.light(gx, gy, 46, (255, 150, 80), 1.0, flicker=0.8, glow=True, phase=ph, z=6)
        elif tile is Tile.SPORE_BUSH and night:
            f.light(gx, gy, 14, (255, 110, 200), 0.55 + 0.2 * math.sin(now * 2 + ph), glow=True, z=5)
        elif tile is Tile.FLORA and night and hash2(*p, 5) % 4 == 0:
            f.light(gx, gy, 9, (180, 140, 255), 0.4, glow=True, phase=ph, z=14)
        elif tile is Tile.WRECK:
            color = WRECK_LIGHT.get(wreck_theme(self.entrance_levels.get(p, "wreck_1")), (200, 220, 255))
            f.light(gx, gy, 26, color, 0.5 + 0.5 * (int(now * 1.5 + ph) % 2), glow=True, z=10)
        elif tile is Tile.CRASH:
            comp = world.companion
            if comp and comp.state == "stranded":
                f.light(gx, gy, 30, (255, 150, 70), 0.9, flicker=0.9, glow=True, phase=ph, z=6)

    def _item(self, f: Frame, key: str, tx: int, ty: int, now: float, glow: bool, lit: bool) -> None:
        gx, gy = ground_point(tx, ty)
        bob = 1 if int(now * 2 + tx * 0.7 + ty) % 2 else 0
        tint = "memory" if (f.iso and not lit) else None
        f.sprite(t7_item(key), gx, gy, now + _phase(tx, ty), layer=1, sort_y=gy - 1, shadow=6, z=bob, tint=tint,
                 solid=False)
        if glow and key in GLOW_ITEMS:
            color, r = GLOW_ITEMS[key]
            f.light(gx, gy, r, color, 0.7, glow=True, phase=tx + ty, z=5)
