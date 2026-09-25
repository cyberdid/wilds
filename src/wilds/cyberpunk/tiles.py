"""Tile types for a city district: glyph, passability, colour, English note."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class CTileInfo:
    glyph: str
    passable: bool
    color: str
    name: str
    blocks_sight: bool = False


class CTile(Enum):
    SIDEWALK = CTileInfo(".", True, "grey58", "sidewalk")
    ROAD = CTileInfo(",", True, "grey35", "wet asphalt road")
    NEON = CTileInfo('"', True, "bright_magenta", "neon-lit pavement")
    ALLEY = CTileInfo(":", True, "grey42", "narrow alley")
    WALL = CTileInfo("#", False, "steel_blue", "building wall", blocks_sight=True)
    DOOR = CTileInfo("+", True, "orange3", "doorway")
    SHOP = CTileInfo("$", True, "bright_green", "storefront")
    BAR = CTileInfo("B", True, "bright_yellow", "bar / safehouse")
    FIXER = CTileInfo("F", True, "bright_cyan", "fixer's office")
    CHECKPOINT = CTileInfo("=", True, "bright_red", "corp checkpoint")
    FENCE = CTileInfo("^", False, "grey50", "chain-link fence", blocks_sight=True)
    TRASH = CTileInfo("%", True, "grey42", "trash / junk")

    @property
    def glyph(self) -> str:
        return self.value.glyph

    @property
    def passable(self) -> bool:
        return self.value.passable

    @property
    def color(self) -> str:
        return self.value.color

    @property
    def label(self) -> str:
        return self.value.name

    @property
    def blocks_sight(self) -> bool:
        return self.value.blocks_sight
