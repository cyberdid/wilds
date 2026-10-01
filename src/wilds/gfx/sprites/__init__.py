"""All sprite definitions, one module per family. Nothing is imported eagerly:
``load_all()`` imports every module (registering into ``registry.SPRITES``), and
the export tool can import a single module to preview it in isolation."""

from __future__ import annotations

import importlib

from ..registry import SPRITES, Registry

MODULES = (
    "tau7_terrain",
    "tau7_life",
    "items",
    "ui_icons",
    "fx",
    "city_terrain",
    "city_facades",
    "city_people",
)


# The Azeroth chapter's art (wilds.azeroth.manifest). Kept out of ``load_all`` so Wilds
# does not pay for it; ``load_azeroth`` imports it. ``AZEROTH_DONE`` lists the modules
# that are complete: the coverage test holds exactly those to the manifest.
AZEROTH_MODULES = (
    "az_terrain",
    "az_creatures",
    "az_monsters",
    "az_people_tauren",
    "az_people_other",
    "az_structures",
    "az_thunder_bluff",
    "az_items",
    "az_fx",
)
# structures (bigger tents, tall totems, well-totems, wooden gate) are being redrawn: held out until complete
AZEROTH_DONE: tuple[str, ...] = tuple(m for m in AZEROTH_MODULES if m != "az_structures")


def load(module: str) -> None:
    importlib.import_module(f"{__name__}.{module}")


def load_all() -> Registry:
    for m in MODULES:
        load(m)
    return SPRITES


def load_azeroth() -> Registry:
    for m in AZEROTH_MODULES:
        load(m)
    return SPRITES
