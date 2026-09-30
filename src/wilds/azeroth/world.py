"""A real-scale zone: lazily generated chunks, placed content, roads.

The world does not hold a grid of the whole zone. Terrain is a function of the tile
(``ZoneTerrain``), chunks of 64x64 tiles are materialised on demand and kept in a
small LRU cache, and the people, creatures and places of the content pack are put
at their wiki coordinates.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..noise import ValueNoise
from ..world import Event
from . import content, quests, settlements
from .route import find_route
from .scale import CHUNK, TICK_SECONDS, Geometry, load_geometry
from .terrain import Macro, Terrain, ZoneTerrain

Pos = tuple[int, int]
CACHE_CHUNKS = 256


@dataclass
class Placement:
    id: str
    title: str
    kind: str        # npc | mob | object | subzone | quest
    pos: Pos
    zone: str        # mulgore | thunder_bluff
    source_map: str  # the map the wiki coordinates were given on
    approx: bool = False  # no coordinates in the wiki: placed near the place its text names


class ZoneWorld:
    def __init__(self, pack_dir: Path | str, seed: int = 0, roads: bool = True) -> None:
        self.pack = Path(pack_dir)
        self.geo: Geometry = load_geometry(self.pack)
        self.terrain = ZoneTerrain(self.geo, Macro.load(self.pack), seed)
        self.seed = seed
        self.tick = 0
        self.events: list[Event] = []
        self.listeners: list[Callable[[Event], None]] = []
        self.hero = None  # set by the simulation
        self._chunks: OrderedDict[Pos, bytes] = OrderedDict()
        self.features: list[dict] = json.loads((self.pack / "features.json").read_text("utf-8"))["features"] \
            if (self.pack / "features.json").exists() else []
        self.placements: list[Placement] = self._place()
        if roads:
            self.build_roads()

    # --- time and journal -------------------------------------------------------------
    @property
    def seconds(self) -> float:
        return self.tick * TICK_SECONDS

    @property
    def day(self) -> int:
        return int(self.seconds // 86400) + 1

    @property
    def hour(self) -> int:
        return int(self.seconds // 3600) % 24

    @property
    def minute(self) -> int:
        return int(self.seconds // 60) % 60

    def clock(self) -> str:
        return f"День {self.day}, {self.hour:02d}:{self.minute:02d}"

    def log(self, text: str, kind: str = "info") -> None:
        ev = Event(self.tick, text, kind)
        self.events.append(ev)
        if len(self.events) > 500:
            del self.events[:100]
        for fn in self.listeners:
            fn(ev)

    # --- terrain ---------------------------------------------------------------------
    def chunk(self, cx: int, cy: int) -> bytes:
        key = (cx, cy)
        data = self._chunks.get(key)
        if data is None:
            data = bytes(int(self.terrain.tile(cx * CHUNK + x, cy * CHUNK + y))
                         for y in range(CHUNK) for x in range(CHUNK))
            self._chunks[key] = data
            while len(self._chunks) > CACHE_CHUNKS:
                self._chunks.popitem(last=False)
        else:
            self._chunks.move_to_end(key)
        return data

    def tile(self, x: int, y: int) -> Terrain:
        if not (0 <= x < self.geo.width and 0 <= y < self.geo.height):
            return Terrain.VOID
        return Terrain(self.chunk(x // CHUNK, y // CHUNK)[(y % CHUNK) * CHUNK + x % CHUNK])

    def passable(self, p: Pos) -> bool:
        return self.tile(*p).passable

    def nearest_passable(self, p: Pos, radius: int = 12) -> Pos | None:
        if self.passable(p):
            return p
        for r in range(1, radius + 1):
            for dx in range(-r, r + 1):
                for dy in (-r, r):
                    for q in ((p[0] + dx, p[1] + dy), (p[0] + dy, p[1] + dx)):
                        if self.passable(q):
                            return q
        return None

    # --- content ---------------------------------------------------------------------
    def _place(self) -> list[Placement]:
        out: list[Placement] = []
        refs = quests.quest_refs(self.pack)  # removed content that live quests still point at stays
        for kind in ("subzone", "npc", "mob", "object"):
            for rec in content.load(self.pack, kind):
                if (rec["removed"] and quests.clean(rec["title"]) not in refs) or not rec["coords"]:
                    continue
                c = rec["coords"][0]
                pos = self.geo.sub_to_tile(c["map"], c["x"], c["y"]) if c["map"].lower() != "mulgore" \
                    else self.geo.pct_to_tile(c["x"], c["y"])
                out.append(Placement(rec["id"], rec["title"], kind, pos, rec["zone"], c["map"]))
        known = {p.title.lower() for p in out}
        for f in self.features:
            if f["name"].lower() not in known:
                sub = f.get("map", "")
                pos = self.geo.sub_to_tile(sub, f["x"], f["y"]) if sub else self.geo.pct_to_tile(f["x"], f["y"])
                out.append(Placement(f["id"], f["name"], f["kind"], pos,
                                     "thunder_bluff" if sub else "mulgore", sub or "Mulgore"))
        out += self._place_by_text(out)
        return out

    def _place_by_text(self, placed: list[Placement]) -> list[Placement]:
        """Creatures and people the wiki gives no coordinates for: near the place their page names."""
        anchors = {p.title.lower(): p.pos for p in placed if p.kind in ("subzone", "settlement", "gate", "lake", "plateau")}
        done = {p.id for p in placed}
        refs = quests.quest_refs(self.pack)
        out: list[Placement] = []
        for kind in ("npc", "mob", "object"):
            for rec in content.load(self.pack, kind):
                if (rec["removed"] and quests.clean(rec["title"]) not in refs) or rec["id"] in done or rec["coords"]:
                    continue
                text = " ".join([rec["info"].get("location", ""), *rec["links"]]).lower()
                hit = next((t for t in sorted(anchors, key=len, reverse=True) if t in text), None)
                if hit is None:
                    continue
                ax, ay = anchors[hit]
                h = sum(map(ord, rec["id"]))  # stable jitter: same spot on every run
                spread = 20
                if hit == "thunder bluff":  # a whole city: spread its people over the rises
                    if kind != "npc":
                        continue
                    rises = settlements.platforms(self)
                    plat = rises[h % len(rises)]
                    ax, ay, spread = plat.center[0], plat.center[1], max(14, plat.radius - 8)
                pos = (ax + h % (2 * spread + 1) - spread, ay + h // 41 % (2 * spread + 1) - spread)
                pos = self.nearest_passable(pos, 12) or pos
                out.append(Placement(rec["id"], rec["title"], kind, pos, rec["zone"], "text", approx=True))
        return out

    def at(self, title: str) -> Placement | None:
        return next((p for p in self.placements if p.title.lower() == title.lower()), None)

    def _wobbly(self, path: list[Pos], name: str) -> set[Pos]:
        """A road along ``path`` that meanders a little instead of following the search's straight legs."""
        noise = ValueNoise(self.seed * 31 + sum(map(ord, name)))
        pts = [(x + (noise.fractal(i / 45, 0.5, 2) - 0.5) * 14, y + (noise.fractal(i / 45, 7.5, 2) - 0.5) * 14)
               for i, (x, y) in enumerate(path)]
        out: set[Pos] = set()
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0))))
            for k in range(steps + 1):
                x, y = x0 + (x1 - x0) * k / steps, y0 + (y1 - y0) * k / steps
                out.update((int(x) + dx, int(y) + dy) for dx in (0, 1, 2) for dy in (0, 1, 2))
        return out

    def build_roads(self) -> None:
        """Lay the roads between settlements along real walkable routes."""
        spec = self.pack / "features.json"
        if not spec.exists():
            return
        roads: set[Pos] = set()
        for road in json.loads(spec.read_text("utf-8")).get("roads", []):
            a = self.geo.pct_to_tile(road["from"][1], road["from"][2])
            b = self.geo.pct_to_tile(road["to"][1], road["to"][2])
            a, b = self.nearest_passable(a, 40) or a, self.nearest_passable(b, 40) or b
            path = find_route(self, a, b)
            roads |= self._wobbly(path or [], road["name"])
        self.terrain.roads = {p for p in roads if self.terrain.in_bounds(p)
                              and self.terrain.tile(*p).passable}
        self._chunks.clear()
