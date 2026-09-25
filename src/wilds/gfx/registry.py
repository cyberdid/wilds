"""Name -> Art registry. Sprite modules register into ``SPRITES`` at import time.

Names are dotted lowercase paths (``t7.hero.walk``, ``cp.sprawl.road@2``). A
``@N`` suffix marks a static variant: ``variants("t7.ground.moss")`` returns
every ``t7.ground.moss@N`` so the renderer can pick one per tile position and
break up visible repetition.
"""

from __future__ import annotations

import re

from .pixelart import Art, art

_NAME = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*(@\d+)?$")


class Registry:
    def __init__(self) -> None:
        self._arts: dict[str, Art] = {}
        self._variants: dict[str, list[str]] = {}

    def add(self, name: str, a: Art) -> Art:
        if not _NAME.match(name):
            raise ValueError(f"bad sprite name {name!r} (lowercase dotted, optional @N)")
        if name in self._arts:
            raise ValueError(f"duplicate sprite name {name!r}")
        self._arts[name] = a
        base, _, idx = name.partition("@")
        if idx:
            vs = self._variants.setdefault(base, [])
            vs.append(name)
            vs.sort(key=lambda n: int(n.rpartition("@")[2]))
        return a

    def get(self, name: str) -> Art:
        try:
            return self._arts[name]
        except KeyError:
            raise KeyError(f"no sprite named {name!r}") from None

    def __contains__(self, name: str) -> bool:
        return name in self._arts or name in self._variants

    def __len__(self) -> int:
        return len(self._arts)

    def names(self, prefix: str = "") -> list[str]:
        return sorted(n for n in self._arts if n.startswith(prefix))

    def variants(self, base: str) -> list[str]:
        """All ``base@N`` names in order, or ``[base]`` if it is a plain sprite."""
        if base in self._variants:
            return list(self._variants[base])
        if base in self._arts:
            return [base]
        raise KeyError(f"no sprite or variant set named {base!r}")

    def resolve(self, *candidates: str) -> str | None:
        """First candidate that exists (as a sprite or a variant set)."""
        return next((c for c in candidates if c in self), None)


SPRITES = Registry()


def sprite(name: str, *frames, **kw) -> Art:
    """Define and register in one go: ``sprite("t7.grave", GRID, legend={...})``."""
    return SPRITES.add(name, art(*frames, **kw))


def register(name: str, a: Art) -> Art:
    return SPRITES.add(name, a)
