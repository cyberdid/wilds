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
    "city_people",
)


def load(module: str) -> None:
    importlib.import_module(f"{__name__}.{module}")


def load_all() -> Registry:
    for m in MODULES:
        load(m)
    return SPRITES
