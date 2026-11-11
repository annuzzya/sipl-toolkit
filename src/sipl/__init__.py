"""SIPL Language Toolkit — інструменти для мови SIPL (Simple Programming Language)."""

__version__ = "0.1.0"

from .errors import Diagnostic, SiplError, SiplSyntaxError, render_diagnostic
from .parser import parse, parse_source
from .spans import SourceSpan, SourceText

__all__ = [
    "Diagnostic",
    "SiplError",
    "SiplSyntaxError",
    "SourceSpan",
    "SourceText",
    "parse",
    "parse_source",
    "render_diagnostic",
]
