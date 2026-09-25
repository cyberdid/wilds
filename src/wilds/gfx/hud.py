"""HUD drawing primitives for the sprite front-end: pixel-styled panels, bars
with icons, item grids, the event log, a minimap, banners and overlays.
Chapter-specific content lives in ``tau7_hud.py`` / ``city_hud.py``."""

from __future__ import annotations

import math

import pygame

from . import text as txt
from .bank import SpriteBank

PANEL_BG = (17, 15, 27)
PANEL_BG2 = (24, 21, 38)
EDGE = (62, 55, 94)
EDGE_HI = (98, 88, 140)
TITLE = (255, 212, 120)
TEXT = (224, 222, 238)
DIM = (140, 136, 166)
FAINT = (92, 88, 116)
GOOD = (122, 232, 132)
WARN = (255, 206, 90)
BAD = (255, 92, 92)
CYAN = (110, 232, 244)
MAGENTA = (232, 120, 255)

LOG_COLORS = {
    "info": (178, 176, 194), "danger": (255, 104, 104), "good": (126, 232, 136), "brain": (110, 226, 240),
    "death": (255, 255, 255), "event": (232, 128, 255), "diary": (255, 222, 116), "talk": (132, 240, 255),
    "victory": (150, 255, 160),
}


def frame_rect(screen: pygame.Surface, rect: pygame.Rect, bg=PANEL_BG, edge=EDGE, hi=EDGE_HI) -> None:
    """A pixel-art panel: 2px border with a lit top-left edge and a notched corner."""
    pygame.draw.rect(screen, bg, rect)
    pygame.draw.rect(screen, edge, rect, 2)
    pygame.draw.line(screen, hi, (rect.left + 2, rect.top + 2), (rect.right - 4, rect.top + 2))
    pygame.draw.line(screen, hi, (rect.left + 2, rect.top + 2), (rect.left + 2, rect.bottom - 4))
    for cx, cy in (rect.topleft, (rect.right - 1, rect.top), (rect.left, rect.bottom - 1),
                   (rect.right - 1, rect.bottom - 1)):
        screen.set_at((cx, cy), (0, 0, 0))


def bar_color(ratio: float) -> tuple[int, int, int]:
    return GOOD if ratio > 0.6 else WARN if ratio > 0.3 else BAD


class Layout:
    """Immediate-mode vertical layout inside a panel."""

    def __init__(self, screen: pygame.Surface, bank: SpriteBank, rect: pygame.Rect, t: float,
                 pad: int = 10) -> None:
        self.s = screen
        self.bank = bank
        self.rect = rect
        self.t = t
        self.x = rect.x + pad
        self.y = rect.y + pad
        self.w = rect.width - 2 * pad

    @property
    def room(self) -> int:
        return self.rect.bottom - 8 - self.y

    def space(self, n: int = 6) -> None:
        self.y += n

    def icon(self, name: str, x: int, y: int, scale: int = 2) -> int:
        if name not in self.bank:
            return 0
        surf = self.bank.frame(name, self.t, scale)
        self.s.blit(surf, (x, y))
        return surf.get_width()

    def title(self, text: str, icon: str | None = None, color=TITLE) -> None:
        x = self.x
        if icon:
            x += self.icon(icon, x, self.y - 2) + 6
        surf = txt.render(text.upper(), "pixel", 16, color, shadow=(0, 0, 0))
        self.s.blit(surf, (x, self.y))
        self.y += surf.get_height() + 2
        pygame.draw.line(self.s, EDGE, (self.x, self.y), (self.x + self.w, self.y))
        self.y += 6

    def line(self, text: str, color=TEXT, face: str = "text", size: int = 15, icon: str | None = None,
             right: str | None = None, right_color=DIM) -> None:
        x = self.x
        h = txt.line_height(face, size)
        if icon:
            x += self.icon(icon, x, self.y + (h - 24) // 2) + 6
        rs = txt.render(right, "pixel", 14, right_color) if right else None
        max_w = self.x + self.w - x - (rs.get_width() + 8 if rs else 0)
        text = txt.clean(text)
        surf = txt.render(text, face, size, color)
        if surf.get_width() > max_w:
            while text and txt.font(face, size).size(text + "…")[0] > max_w:
                text = text[:-1]
            surf = txt.render(text + "…", face, size, color)
        self.s.blit(surf, (x, self.y))
        if rs:
            self.s.blit(rs, (self.x + self.w - rs.get_width(), self.y + (h - rs.get_height()) // 2))
        self.y += max(h, 26 if icon else 0)

    def para(self, text: str, color=TEXT, face: str = "text", size: int = 15, max_lines: int = 99,
             indent: int = 0) -> None:
        lines = txt.wrap(txt.clean(text), face, size, self.w - indent)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1][:-1] + "…"
        lh = txt.line_height(face, size)
        for ln in lines:
            self.s.blit(txt.render(ln, face, size, color), (self.x + indent, self.y))
            self.y += lh

    def bar(self, icon: str, label: str, value: float, maxv: float = 100.0, color=None,
            text: str | None = None, bipolar: bool = False) -> None:
        h = 24
        x = self.x + self.icon(icon, self.x, self.y) + 8
        lab = txt.render(label, "text", 14, DIM)
        self.s.blit(lab, (x, self.y + (h - lab.get_height()) // 2))
        bx = x + 86
        bw = self.x + self.w - bx - 44
        by = self.y + 7
        ratio = max(0.0, min(1.0, (value + maxv) / (2 * maxv) if bipolar else value / maxv if maxv else 0))
        pygame.draw.rect(self.s, (8, 7, 14), (bx - 1, by - 1, bw + 2, 12))
        pygame.draw.rect(self.s, (38, 34, 56), (bx, by, bw, 10))
        col = color or (bar_color(ratio) if not bipolar else (GOOD if value >= 0 else BAD))
        if bipolar:
            mid = bx + bw // 2
            fill = int(abs(value) / maxv * bw / 2)
            r = (mid, by, fill, 10) if value >= 0 else (mid - fill, by, fill, 10)
            pygame.draw.rect(self.s, col, r)
            pygame.draw.line(self.s, DIM, (mid, by - 1), (mid, by + 10))
        else:
            fill = int(ratio * bw)
            if fill:
                pygame.draw.rect(self.s, col, (bx, by, fill, 10))
                light = tuple(min(255, c + 60) for c in col)
                pygame.draw.line(self.s, light, (bx, by), (bx + fill - 1, by))
        for k in range(1, 10):  # pixel notches every 10%
            nx = bx + bw * k // 10
            self.s.set_at((nx, by + 9), (0, 0, 0))
        val = txt.render(text if text is not None else f"{value:.0f}", "pixel", 14, TEXT)
        self.s.blit(val, (self.x + self.w - val.get_width(), self.y + (h - val.get_height()) // 2))
        self.y += h + 2

    def item_grid(self, entries: list[tuple[str, int]], cell: int = 36) -> None:
        """Item icons (16x16 sprites at 2x) with count badges, wrapping."""
        cols = max(1, self.w // cell)
        for i, (name, count) in enumerate(entries):
            cx = self.x + (i % cols) * cell
            cy = self.y + (i // cols) * cell
            pygame.draw.rect(self.s, PANEL_BG2, (cx, cy, cell - 4, cell - 4))
            pygame.draw.rect(self.s, EDGE, (cx, cy, cell - 4, cell - 4), 1)
            self.icon(name, cx + (cell - 4 - 32) // 2, cy + (cell - 4 - 32) // 2)
            if count > 1:
                badge = txt.render(str(count), "pixel", 12, TEXT, shadow=(0, 0, 0))
                self.s.blit(badge, (cx + cell - 6 - badge.get_width(), cy + cell - 6 - badge.get_height()))
        if entries:
            self.y += ((len(entries) - 1) // cols + 1) * cell + 2


def draw_log(screen: pygame.Surface, bank: SpriteBank, rect: pygame.Rect, events, t: float) -> None:
    """Newest event at the bottom; wraps text; fills upward until the panel is full."""
    size = 14
    lh = txt.line_height("text", size)
    y = rect.bottom - 6
    x = rect.x + 8
    width = rect.width - 16 - 44
    prev = screen.get_clip()
    screen.set_clip(rect)
    for ev in reversed(events):
        color = LOG_COLORS.get(ev.kind, TEXT)
        lines = txt.wrap(txt.clean(ev.text), "text", size, width)[:6]
        block = lh * len(lines)
        y -= block + 3
        if y + block < rect.y:
            break
        stamp = txt.render(f"{ev.tick // 60 % 24:02d}:{ev.tick % 60:02d}", "pixel", 12, FAINT)
        screen.blit(stamp, (x, y + 2))
        icon = f"ui.log.{ev.kind}"
        if icon in bank:
            screen.blit(bank.frame(icon, t, 2), (x + 30, y + 1))
        if ev.kind in ("death", "victory"):
            bg = (150, 30, 40) if ev.kind == "death" else (40, 120, 60)
            pygame.draw.rect(screen, bg, (x + 48, y, width - 4, block))
        for i, ln in enumerate(lines):
            screen.blit(txt.render(ln, "text", size, color), (x + 50, y + i * lh))
    screen.set_clip(prev)


def draw_minimap(screen: pygame.Surface, rect: pygame.Rect, w: int, h: int, color_at, markers, t: float) -> None:
    """color_at(x, y) -> RGB or None (unknown); markers: [(x, y, color, blink)]."""
    scale = max(1, min(rect.width // w, rect.height // h))
    surf = pygame.Surface((w, h))
    surf.fill((6, 5, 12))
    for y in range(h):
        for x in range(w):
            c = color_at(x, y)
            if c is not None:
                surf.set_at((x, y), c)
    for mx, my, color, blink in markers:
        if not blink or int(t * 3) % 2:
            surf.set_at((mx, my), color)
    big = pygame.transform.scale(surf, (w * scale, h * scale))
    box = pygame.Rect(rect.right - w * scale - 6, rect.y, w * scale + 6, h * scale + 6)
    frame_rect(screen, box, bg=(6, 5, 12))
    screen.blit(big, (box.x + 3, box.y + 3))


def banner(screen: pygame.Surface, bank: SpriteBank, view: pygame.Rect, text: str, icon: str | None, t: float,
           color=WARN, urgent: bool = False) -> None:
    surf = txt.render(txt.clean(text), "bold", 18, color, shadow=(0, 0, 0))
    w = surf.get_width() + (40 if icon else 0) + 28
    rect = pygame.Rect(view.centerx - w // 2, view.y + 12, w, 38)
    pulse = (math.sin(t * 6) + 1) / 2 if urgent else 0.0
    edge = tuple(int(e + (c - e) * pulse) for e, c in zip(EDGE, color))
    frame_rect(screen, rect, bg=(20, 14, 26), edge=edge)
    x = rect.x + 14
    if icon and icon in bank:
        screen.blit(bank.frame(icon, t, 2), (x, rect.y + 7))
        x += 32
    screen.blit(surf, (x, rect.y + (rect.height - surf.get_height()) // 2))


def plate(screen: pygame.Surface, bank: SpriteBank, x: int, y: int, parts: list[tuple[str | None, str]], t: float,
          color=TEXT) -> pygame.Rect:
    """A small label plate: [(icon, text), ...] in a row."""
    items = []
    width = 12
    for icon, label in parts:
        surf = txt.render(txt.clean(label), "pixel", 16, color, shadow=(0, 0, 0))
        items.append((icon, surf))
        width += surf.get_width() + (30 if icon else 0) + 12
    rect = pygame.Rect(x, y, width, 34)
    frame_rect(screen, rect, bg=(14, 12, 22))
    cx = x + 10
    for icon, surf in items:
        if icon and icon in bank:
            screen.blit(bank.frame(icon, t, 2), (cx, y + 5))
            cx += 30
        screen.blit(surf, (cx, y + (34 - surf.get_height()) // 2))
        cx += surf.get_width() + 12
    return rect


def overlay_box(screen: pygame.Surface, w: int, h: int) -> pygame.Rect:
    sw, sh = screen.get_size()
    dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
    dim.fill((4, 3, 10, 170))
    screen.blit(dim, (0, 0))
    rect = pygame.Rect((sw - w) // 2, (sh - h) // 2, w, h)
    frame_rect(screen, rect)
    return rect


def text_overlay(screen: pygame.Surface, title: str, blocks: list[tuple[str, tuple, str]], scroll: int = 0,
                 hint: str = "") -> int:
    """A scrollable text window: blocks = [(text, color, face)]. Returns max scroll."""
    sw, sh = screen.get_size()
    rect = overlay_box(screen, min(860, sw - 60), sh - 80)
    head = txt.render(title, "pixel", 20, TITLE, shadow=(0, 0, 0))
    screen.blit(head, (rect.x + 18, rect.y + 14))
    body = pygame.Rect(rect.x + 18, rect.y + 50, rect.width - 36, rect.height - 84)
    lines: list[tuple[str, tuple, str]] = []
    for text, color, face in blocks:
        size = 17 if face != "pixel" else 16
        for ln in txt.wrap(text, face, size, body.width):
            lines.append((ln, color, face))
    lh = txt.line_height("text", 17)
    visible = body.height // lh
    max_scroll = max(0, len(lines) - visible)
    scroll = max(0, min(scroll, max_scroll))
    prev = screen.get_clip()
    screen.set_clip(body)
    for i, (ln, color, face) in enumerate(lines[scroll:scroll + visible + 1]):
        screen.blit(txt.render(ln, face, 17 if face != "pixel" else 16, color), (body.x, body.y + i * lh))
    screen.set_clip(prev)
    if hint:
        h = txt.render(hint, "pixel", 14, DIM)
        screen.blit(h, (rect.x + 18, rect.bottom - 26))
    return max_scroll
