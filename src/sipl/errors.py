"""Діагностика: усі помилки прив'язані до SourceSpan і мають стабільний код."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .spans import SourceSpan, SourceText


@dataclass(frozen=True)
class Diagnostic:
    code: str  # напр. E-PARSE-001
    message: str
    span: Optional[SourceSpan] = None
    severity: str = "error"  # error | warning | info
    hint: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "span": self.span.to_dict() if self.span else None,
            "hint": self.hint,
        }


class SiplError(Exception):
    """Помилка з діагностикою."""

    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


class SiplSyntaxError(SiplError):
    pass


def render_diagnostic(diag: Diagnostic, source: Optional[SourceText] = None) -> str:
    """Людський вигляд: «файл:рядок:колонка: помилка [код]: …» + рядок коду з вказівником."""
    where = ""
    if diag.span is not None:
        name = source.name if source else "<input>"
        where = f"{name}:{diag.span.line}:{diag.span.col}: "
    out = [f"{where}{_SEV_UA.get(diag.severity, diag.severity)} [{diag.code}]: {diag.message}"]
    if diag.span is not None and source is not None:
        line = source.line_text(diag.span.line)
        out.append(f"  {diag.span.line:>4} | {line}")
        width = 1
        if diag.span.end_line == diag.span.line:
            width = max(1, diag.span.end_col - diag.span.col)
        out.append("       | " + " " * (diag.span.col - 1) + "^" * width)
    if diag.hint:
        out.append(f"  підказка: {diag.hint}")
    return "\n".join(out)


_SEV_UA = {"error": "помилка", "warning": "попередження", "info": "інформація"}
