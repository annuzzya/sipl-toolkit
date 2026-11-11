"""Лексичний аналіз SIPL.

Лексеми: ключові слова, ідентифікатори, натуральні числа, :=  ;  (  )  +  -  *  =  >,
а також логічні зв'язки ∨ (або `or`) та ¬ (або `not`) із БНФ курсу.
Коментар: від `//` до кінця рядка.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import Diagnostic, SiplSyntaxError
from .spans import SourceSpan, SourceText

KEYWORDS = {"begin", "end", "if", "then", "else", "while", "do", "skip"}

# вид лексеми -> опис для повідомлень про помилки
KIND_NAMES = {
    "ID": "ідентифікатор",
    "NUM": "число",
    "ASSIGN": "':='",
    "SEMI": "';'",
    "LPAR": "'('",
    "RPAR": "')'",
    "PLUS": "'+'",
    "MINUS": "'-'",
    "STAR": "'*'",
    "EQ": "'='",
    "GT": "'>'",
    "OR": "'∨'",
    "NOT": "'¬'",
    "EOF": "кінець тексту",
}
for _kw in KEYWORDS:
    KIND_NAMES[_kw] = f"'{_kw}'"

_SINGLE = {
    ";": "SEMI",
    "(": "LPAR",
    ")": "RPAR",
    "+": "PLUS",
    "-": "MINUS",
    "*": "STAR",
    "=": "EQ",
    ">": "GT",
    "∨": "OR",
    "¬": "NOT",
}


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    span: SourceSpan

    def to_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text, "span": self.span.to_dict()}


def tokenize(source: SourceText) -> list[Token]:
    text = source.text
    tokens: list[Token] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        start = i
        if ch.isdigit():
            while i < n and text[i].isdigit():
                i += 1
            if i < n and (text[i].isalpha() or text[i] == "_"):
                raise _lex_error(source, start, i + 1, f"ідентифікатор не може починатися з цифри: '{text[start:i + 1]}…'")
            tokens.append(Token("NUM", text[start:i], source.span(start, i)))
        elif ch.isalpha() or ch == "_":
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
            word = text[start:i]
            if word in KEYWORDS:
                kind = word
            elif word == "or":
                kind = "OR"
            elif word == "not":
                kind = "NOT"
            else:
                kind = "ID"
            tokens.append(Token(kind, word, source.span(start, i)))
        elif text.startswith(":=", i):
            i += 2
            tokens.append(Token("ASSIGN", ":=", source.span(start, i)))
        elif ch in _SINGLE:
            i += 1
            tokens.append(Token(_SINGLE[ch], ch, source.span(start, i)))
        elif ch == ":":
            raise _lex_error(source, start, start + 1, "після ':' очікувалось '=' (оператор присвоювання ':=')")
        else:
            raise _lex_error(source, start, start + 1, f"недопустимий символ {ch!r}")
    tokens.append(Token("EOF", "", source.span(n, n)))
    return tokens


def _lex_error(source: SourceText, start: int, end: int, message: str) -> SiplSyntaxError:
    return SiplSyntaxError(Diagnostic("E-LEX-001", message, source.span(start, end)))
