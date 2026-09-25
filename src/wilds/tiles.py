"""Tile types of the alien planet: glyph, passability, colour and an English name for the LLM."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class TileInfo:
    glyph: str
    passable: bool
    color: str
    name: str
    blocks_sight: bool = False


class Tile(Enum):
    MOSS = TileInfo(".", True, "dark_cyan", "moss")
    DUST = TileInfo(",", True, "orange4", "red dust")
    FLORA = TileInfo("Ψ", True, "medium_purple", "xeno-flora")
    STALK = TileInfo("'", True, "purple4", "cut stalk")
    SPORE_BUSH = TileInfo("%", True, "hot_pink", "spore bush")
    SPORE_BUSH_EMPTY = TileInfo("%", True, "grey42", "harvested spore bush")
    WATER = TileInfo("~", False, "blue", "water")
    ROCK = TileInfo("^", False, "grey70", "ore rock", blocks_sight=True)
    WRECK = TileInfo("▣", True, "bright_cyan", "wreck entrance")
    HEATER = TileInfo("*", True, "bright_red", "heater")
    HEATER_OFF = TileInfo("*", True, "grey42", "dead heater")
    DOME = TileInfo("∩", True, "orange3", "dome")
    GRAVE = TileInfo("†", True, "white", "grave")
    POD = TileInfo("Ø", True, "bold bright_white", "escape pod")
    CRASH = TileInfo("ø", True, "bright_white", "second pod crash site")
    # tiles inside wrecks
    WALL = TileInfo("#", False, "steel_blue", "bulkhead", blocks_sight=True)
    FLOOR = TileInfo("·", True, "grey50", "deck")
    HATCH = TileInfo("<", True, "bright_white", "exit hatch")

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
