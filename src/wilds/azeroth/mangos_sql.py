"""Streaming reader for the named-column INSERT subset used by MaNGOS SQL dumps."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

_END = object()
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_ESCAPES = {"0": "\0", "b": "\b", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a"}


class _Chars:
    def __init__(self, stream: TextIO) -> None:
        self._source = (char for line in stream for char in line)
        self._buffer: deque[str | object] = deque()

    def peek(self, offset: int = 0) -> str | object:
        while len(self._buffer) <= offset:
            self._buffer.append(next(self._source, _END))
        return self._buffer[offset]

    def get(self) -> str | object:
        self.peek()
        return self._buffer.popleft()


Token = tuple[str, str]


def _tokens(stream: TextIO) -> Iterator[Token]:
    chars = _Chars(stream)
    punctuation = "(),;."
    while (char := chars.get()) is not _END:
        assert isinstance(char, str)
        if char.isspace():
            continue
        if char == "#":
            while (char := chars.get()) is not _END and char != "\n":
                pass
            continue
        if char == "-" and chars.peek() == "-" and (chars.peek(1) is _END or str(chars.peek(1)).isspace()):
            chars.get()
            while (char := chars.get()) is not _END and char != "\n":
                pass
            continue
        if char == "/" and chars.peek() == "*":
            chars.get()
            previous = ""
            while (next_char := chars.get()) is not _END:
                if previous == "*" and next_char == "/":
                    break
                previous = str(next_char)
            continue
        if char in ("'", '"'):
            quote = char
            value: list[str] = []
            while True:
                next_char = chars.get()
                if next_char is _END:
                    raise ValueError("unterminated SQL string literal")
                next_char = str(next_char)
                if next_char == quote:
                    if chars.peek() == quote:
                        chars.get()
                        value.append(quote)
                        continue
                    break
                if next_char == "\\":
                    escaped = chars.get()
                    if escaped is _END:
                        raise ValueError("unterminated SQL escape sequence")
                    escaped = str(escaped)
                    value.append(_ESCAPES.get(escaped, escaped))
                else:
                    value.append(next_char)
            yield "STRING", "".join(value)
            continue
        if char == "`":
            value = []
            while True:
                next_char = chars.get()
                if next_char is _END:
                    raise ValueError("unterminated SQL identifier")
                next_char = str(next_char)
                if next_char == "`":
                    if chars.peek() == "`":
                        chars.get()
                        value.append("`")
                        continue
                    break
                value.append(next_char)
            yield "IDENT", "".join(value)
            continue
        is_number_start = char.isdigit() or (
            char in "+-" and (str(chars.peek()).isdigit() or chars.peek() == ".")
        ) or (char == "." and str(chars.peek()).isdigit())
        if is_number_start:
            literal = [char]
            while chars.peek() is not _END and str(chars.peek()) in "0123456789.eE+-":
                literal.append(str(chars.get()))
            number = "".join(literal)
            yield ("NUMBER", number) if _NUMBER.fullmatch(number) else ("OTHER", number)
            continue
        if char in punctuation:
            yield "PUNCT", char
            continue
        value = [char]
        while chars.peek() is not _END:
            next_char = str(chars.peek())
            if next_char.isspace() or next_char in punctuation + "'\"`#/":
                break
            if next_char == "-" and chars.peek(1) == "-":
                break
            value.append(str(chars.get()))
        yield "IDENT", "".join(value)


class _TokenStream:
    def __init__(self, tokens: Iterator[Token]) -> None:
        self._tokens = tokens
        self._buffer: deque[Token | object] = deque()

    def peek(self) -> Token | object:
        if not self._buffer:
            self._buffer.append(next(self._tokens, _END))
        return self._buffer[0]

    def get(self) -> Token | object:
        self.peek()
        return self._buffer.popleft()


def _skip_statement(tokens: _TokenStream) -> None:
    while (token := tokens.get()) is not _END:
        if token == ("PUNCT", ";"):
            return


def _parse_literal(token: Token, path: Path, table: str) -> str | int | float | None:
    kind, value = token
    if kind == "STRING":
        return value
    if kind == "NUMBER":
        if "." not in value and "e" not in value.lower():
            return int(value)
        return float(value)
    if kind == "IDENT" and value.upper() == "NULL":
        return None
    if kind in ("IDENT", "OTHER"):
        return value
    raise ValueError(f"unsupported value token {token!r} in {path} ({table})")


def parse_insert_rows(path: Path, table: str) -> Iterator[dict[str, str | int | float | None]]:
    """Yield rows from matching ``INSERT INTO table (columns) VALUES (...)`` statements.

    The input is lexed and consumed incrementally, so large dump files and multi-row
    INSERTs do not need to be loaded into memory as complete SQL statements.
    """
    path = Path(path)
    wanted = table.lower()
    with path.open("r", encoding="utf-8", errors="strict", newline="") as file:
        tokens = _TokenStream(_tokens(file))
        while (token := tokens.get()) is not _END:
            if token[0] != "IDENT" or token[1].upper() != "INSERT":
                continue
            into = tokens.get()
            if into == _END or into[0] != "IDENT" or into[1].upper() != "INTO":
                continue
            name = tokens.get()
            while name != _END and name[0] == "IDENT" and name[1].upper() in {
                "LOW_PRIORITY", "DELAYED", "HIGH_PRIORITY", "IGNORE",
            }:
                name = tokens.get()
            if name == _END or name[0] != "IDENT":
                _skip_statement(tokens)
                continue
            table_name = name[1]
            if tokens.peek() == ("PUNCT", "."):
                tokens.get()
                qualified_name = tokens.get()
                if qualified_name == _END or qualified_name[0] != "IDENT":
                    _skip_statement(tokens)
                    continue
                table_name = qualified_name[1]
            if table_name.lower() != wanted:
                _skip_statement(tokens)
                continue
            if tokens.get() != ("PUNCT", "("):
                _skip_statement(tokens)
                continue
            columns: list[str] = []
            while True:
                column = tokens.get()
                if column == _END:
                    raise ValueError(f"unterminated column list in {path} ({table})")
                if column == ("PUNCT", ")"):
                    break
                if column[0] == "IDENT":
                    columns.append(column[1].lower())
                elif column != ("PUNCT", ","):
                    raise ValueError(f"invalid column token {column!r} in {path} ({table})")
            keyword = tokens.get()
            if keyword == _END or keyword[0] != "IDENT" or keyword[1].upper() not in ("VALUES", "VALUE"):
                _skip_statement(tokens)
                continue

            while True:
                if tokens.get() != ("PUNCT", "("):
                    _skip_statement(tokens)
                    break
                values: list[str | int | float | None] = []
                while True:
                    value = tokens.get()
                    if value == _END:
                        raise ValueError(f"unterminated value row in {path} ({table})")
                    if value == ("PUNCT", ","):
                        continue
                    if value == ("PUNCT", ")"):
                        break
                    if value[0] == "PUNCT":
                        raise ValueError(f"unsupported expression token {value!r} in {path} ({table})")
                    values.append(_parse_literal(value, path, table))
                if len(values) != len(columns):
                    raise ValueError(
                        f"{path}: {table} row has {len(values)} values for {len(columns)} columns"
                    )
                yield dict(zip(columns, values, strict=True))
                separator = tokens.get()
                if separator == ("PUNCT", ","):
                    continue
                if separator == ("PUNCT", ";"):
                    break
                if separator is _END:
                    break
                _skip_statement(tokens)
                break
