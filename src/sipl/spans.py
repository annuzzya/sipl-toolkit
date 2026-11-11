"""Позиції в початковому тексті (SourceSpan).

Усі зміщення рахуються в символах Unicode (як індекси рядка Python).
Рядки та колонки нумеруються з 1 — так, як їх показують редактори.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpan:
    start: int  # зміщення першого символу
    end: int  # зміщення першого символу ПІСЛЯ фрагмента
    line: int
    col: int
    end_line: int
    end_col: int

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "line": self.line,
            "col": self.col,
            "end_line": self.end_line,
            "end_col": self.end_col,
        }

    def join(self, other: "SourceSpan") -> "SourceSpan":
        """Найменший проміжок, що охоплює обидва."""
        first, last = (self, other) if self.start <= other.start else (other, self)
        end_src = self if self.end >= other.end else other
        return SourceSpan(first.start, end_src.end, first.line, first.col, end_src.end_line, end_src.end_col)

    def __str__(self) -> str:
        return f"{self.line}:{self.col}"


class SourceText:
    """Початковий текст + швидке перетворення зміщень у (рядок, колонка)."""

    def __init__(self, text: str, name: str = "<input>"):
        self.text = text
        self.name = name
        self._line_starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self._line_starts.append(i + 1)

    def position(self, offset: int) -> tuple[int, int]:
        offset = max(0, min(offset, len(self.text)))
        idx = bisect_right(self._line_starts, offset) - 1
        return idx + 1, offset - self._line_starts[idx] + 1

    def span(self, start: int, end: int) -> SourceSpan:
        line, col = self.position(start)
        end_line, end_col = self.position(end)
        return SourceSpan(start, end, line, col, end_line, end_col)

    def fragment(self, span: SourceSpan) -> str:
        return self.text[span.start : span.end]

    def line_text(self, line: int) -> str:
        if line < 1 or line > len(self._line_starts):
            return ""
        start = self._line_starts[line - 1]
        end = self._line_starts[line] - 1 if line < len(self._line_starts) else len(self.text)
        return self.text[start:end].rstrip("\r")
