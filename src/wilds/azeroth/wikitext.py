"""A small MediaWiki-wikitext reader: templates, sections, coordinates, plain text.

Only what the content builder needs; no external parser. Templates are read
with balanced-brace matching so nested ``{{...}}`` inside arguments survive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_REF = re.compile(r"<ref\b[^>]*?/>|<ref\b[^>]*>.*?</ref>", re.S | re.I)
_TAG = re.compile(r"</?(?:br|small|big|center|div|span|sup|sub|nowiki|poem|blockquote|onlyinclude|noinclude|includeonly)\b[^>]*>", re.I)
_FILE = re.compile(r"\[\[\s*(?:File|Image):[^\[\]]*(?:\[\[[^\]]*\]\][^\[\]]*)*\]\]", re.I)
_LINK = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_EXT = re.compile(r"\[(?:https?://)[^\s\]]+\s*([^\]]*)\]")
_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)
_CATEGORY = re.compile(r"\[\[\s*Category:([^\]|]+)[^\]]*\]\]", re.I)
_COORD_NAMES = {"co", "coords", "coord", "c", "loc"}


@dataclass
class Template:
    name: str
    args: list[str] = field(default_factory=list)  # positional
    named: dict[str, str] = field(default_factory=dict)
    raw: str = ""


def _split_args(body: str) -> list[str]:
    parts, depth_t, depth_l, cur = [], 0, 0, []
    i = 0
    while i < len(body):
        two = body[i:i + 2]
        if two == "{{":
            depth_t += 1
            cur.append(two)
            i += 2
        elif two == "}}":
            depth_t -= 1
            cur.append(two)
            i += 2
        elif two == "[[":
            depth_l += 1
            cur.append(two)
            i += 2
        elif two == "]]":
            depth_l -= 1
            cur.append(two)
            i += 2
        elif body[i] == "|" and depth_t == 0 and depth_l == 0:
            parts.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(body[i])
            i += 1
    parts.append("".join(cur))
    return parts


def parse_template(raw: str) -> Template:
    body = raw[2:-2]
    parts = _split_args(body)
    t = Template(parts[0].strip(), raw=raw)
    for p in parts[1:]:
        m = re.match(r"\s*([A-Za-z_][\w \-]*?)\s*=(.*)", p, re.S)
        if m and "[[" not in m.group(1):
            t.named[m.group(1).strip().lower()] = m.group(2).strip()
        else:
            t.args.append(p.strip())
    return t


def find_templates(text: str) -> list[Template]:
    """Top-level ``{{...}}`` templates in order of appearance."""
    out, depth, start, i = [], 0, 0, 0
    while i < len(text) - 1:
        two = text[i:i + 2]
        if two == "{{":
            if depth == 0:
                start = i
            depth += 1
            i += 2
        elif two == "}}" and depth:
            depth -= 1
            i += 2
            if depth == 0:
                out.append(parse_template(text[start:i]))
        else:
            i += 1
    return out


def find_all_templates(text: str) -> list[Template]:
    """Templates at any nesting depth."""
    out: list[Template] = []
    for t in find_templates(text):
        out.append(t)
        inner = t.raw[2:-2]
        out.extend(find_all_templates(inner[inner.find("|") + 1:] if "|" in inner else ""))
    return out


def template(text: str, *names: str) -> Template | None:
    wanted = {n.lower() for n in names}
    return next((t for t in find_templates(text) if t.name.lower() in wanted), None)


def coords(text: str) -> list[tuple[float, float, str]]:
    """(x%, y%, map) from {{co|x|y|map}}-style templates, anywhere in the text."""
    out = []
    for t in find_all_templates(text):
        if t.name.lower() in _COORD_NAMES and len(t.args) >= 2:
            try:
                out.append((float(t.args[0]), float(t.args[1]), t.args[2] if len(t.args) > 2 else ""))
            except ValueError:
                continue
    return out


def categories(text: str) -> list[str]:
    return sorted({m.group(1).strip() for m in _CATEGORY.finditer(text)})


def sections(text: str) -> dict[str, str]:
    """Heading -> body ('' holds the lead before the first heading)."""
    out: dict[str, str] = {}
    marks = list(_HEADING.finditer(text))
    out[""] = text[:marks[0].start()] if marks else text
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(2)] = text[m.end():end]
    return out


_KEEP_ARG = {"npc": -1, "quest": 0, "item": 0, "spell": 0, "zone": 0, "faction": 0}


def _replace_templates(text: str) -> str:
    """Drop templates, keeping the human text of the few that carry a name."""
    res, last = [], 0
    depth, start = 0, 0
    i = 0
    while i < len(text) - 1:
        two = text[i:i + 2]
        if two == "{{":
            if depth == 0:
                start = i
                res.append(text[last:i])
            depth += 1
            i += 2
        elif two == "}}" and depth:
            depth -= 1
            i += 2
            if depth == 0:
                t = parse_template(text[start:i])
                key = t.name.lower()
                if key in _KEEP_ARG and t.args:
                    res.append(strip_markup(t.args[_KEEP_ARG[key]]))
                elif key in ("level", "horde", "alliance") and t.args and key == "level":
                    res.append(t.args[0])
                last = i
        else:
            i += 1
    res.append(text[last:])
    return "".join(res)


def strip_markup(text: str) -> str:
    """Readable plain text: links resolved, refs/templates/tables/tags removed."""
    text = _COMMENT.sub("", text)
    text = _REF.sub("", text)
    text = _FILE.sub("", text)
    text = _replace_templates(text)
    text = re.sub(r"\{\|.*?\|\}", "", text, flags=re.S)
    text = _LINK.sub(r"\1", text)
    text = _EXT.sub(r"\1", text)
    text = _TAG.sub(" ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"^[*#:;]+\s*", lambda m: "- " if "*" in m.group(0) or "#" in m.group(0) else "", text, flags=re.M)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def links(text: str) -> list[str]:
    """Targets of [[wikilinks]] (no files/categories), in order, unique."""
    seen, out = set(), []
    for m in re.finditer(r"\[\[([^\]|#]+)", _COMMENT.sub("", text)):
        target = m.group(1).strip()
        if ":" in target and target.split(":")[0].lower() in ("file", "image", "category"):
            continue
        if target not in seen:
            seen.add(target)
            out.append(target)
    return out
